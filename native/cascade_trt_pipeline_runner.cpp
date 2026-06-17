#include <NvInfer.h>
#include <cuda_runtime_api.h>
#include <opencv2/opencv.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <mutex>
#include <numeric>
#include <string>
#include <thread>
#include <tuple>
#include <vector>

using Clock = std::chrono::steady_clock;

class Logger final : public nvinfer1::ILogger {
 public:
  void log(Severity severity, const char* msg) noexcept override {
    if (severity <= Severity::kWARNING) std::cerr << "[TRT] " << msg << "\n";
  }
};

static void check_cuda(cudaError_t e, const char* what) {
  if (e != cudaSuccess) {
    std::cerr << "CUDA error at " << what << ": " << cudaGetErrorString(e) << "\n";
    std::exit(2);
  }
}

static std::vector<char> read_file(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("cannot open engine: " + path);
  f.seekg(0, std::ios::end);
  std::vector<char> data(static_cast<size_t>(f.tellg()));
  f.seekg(0, std::ios::beg);
  f.read(data.data(), static_cast<std::streamsize>(data.size()));
  return data;
}

static size_t dtype_size(nvinfer1::DataType t) {
  switch (t) {
    case nvinfer1::DataType::kFLOAT: return 4;
    case nvinfer1::DataType::kHALF: return 2;
    case nvinfer1::DataType::kINT8: return 1;
    case nvinfer1::DataType::kINT32: return 4;
    case nvinfer1::DataType::kBOOL: return 1;
    case nvinfer1::DataType::kUINT8: return 1;
    default: return 4;
  }
}

static size_t volume(const nvinfer1::Dims& d) {
  size_t v = 1;
  for (int i = 0; i < d.nbDims; ++i) v *= static_cast<size_t>(std::max<int64_t>(1, d.d[i]));
  return v;
}

static int dim_at(const nvinfer1::Dims& d, int idx_from_end) {
  int idx = d.nbDims - idx_from_end;
  return idx >= 0 && idx < d.nbDims ? static_cast<int>(d.d[idx]) : 0;
}

static double mean(const std::vector<double>& xs) {
  if (xs.empty()) return 0.0;
  return std::accumulate(xs.begin(), xs.end(), 0.0) / static_cast<double>(xs.size());
}

static double pct(std::vector<double> xs, double p) {
  if (xs.empty()) return 0.0;
  std::sort(xs.begin(), xs.end());
  double k = (xs.size() - 1) * p / 100.0;
  size_t lo = static_cast<size_t>(k);
  size_t hi = std::min(lo + 1, xs.size() - 1);
  double f = k - static_cast<double>(lo);
  return xs[lo] * (1.0 - f) + xs[hi] * f;
}

class TrtEngine {
 public:
  TrtEngine(const std::string& path, Logger& logger) {
    auto bytes = read_file(path);
    runtime_ = nvinfer1::createInferRuntime(logger);
    engine_ = runtime_->deserializeCudaEngine(bytes.data(), bytes.size());
    context_ = engine_->createExecutionContext();
    if (!engine_ || !context_) throw std::runtime_error("failed to create TRT context");
    for (int i = 0; i < engine_->getNbIOTensors(); ++i) {
      const char* name = engine_->getIOTensorName(i);
      auto dims = engine_->getTensorShape(name);
      size_t nbytes = volume(dims) * dtype_size(engine_->getTensorDataType(name));
      if (engine_->getTensorIOMode(name) == nvinfer1::TensorIOMode::kINPUT) {
        input_name_ = name;
        input_bytes_ = nbytes;
        input_w_ = dim_at(dims, 1);
        check_cuda(cudaMalloc(&input_dev_, nbytes), "TRT input dev");
        context_->setTensorAddress(name, input_dev_);
      } else {
        void* h{};
        void* d{};
        check_cuda(cudaHostAlloc(&h, nbytes, cudaHostAllocDefault), "TRT output host");
        check_cuda(cudaMalloc(&d, nbytes), "TRT output dev");
        context_->setTensorAddress(name, d);
        output_host_.push_back(h);
        output_dev_.push_back(d);
        output_bytes_.push_back(nbytes);
      }
    }
  }

  ~TrtEngine() {
    cudaFree(input_dev_);
    for (auto* p : output_dev_) cudaFree(p);
    for (auto* p : output_host_) cudaFreeHost(p);
    delete context_;
    delete engine_;
    delete runtime_;
  }

  double run(cudaStream_t stream, const float* input_host) {
    auto t0 = Clock::now();
    check_cuda(cudaMemcpyAsync(input_dev_, input_host, input_bytes_, cudaMemcpyHostToDevice, stream), "TRT H2D");
    if (!context_->enqueueV3(stream)) std::exit(4);
    for (size_t i = 0; i < output_dev_.size(); ++i) {
      check_cuda(cudaMemcpyAsync(output_host_[i], output_dev_[i], output_bytes_[i], cudaMemcpyDeviceToHost, stream), "TRT D2H");
    }
    check_cuda(cudaStreamSynchronize(stream), "TRT sync");
    auto t1 = Clock::now();
    return std::chrono::duration<double, std::milli>(t1 - t0).count();
  }

  float* output0() const { return static_cast<float*>(output_host_[0]); }
  size_t output0_count() const { return output_bytes_[0] / sizeof(float); }
  int input_w() const { return input_w_; }
  size_t input_bytes() const { return input_bytes_; }

 private:
  nvinfer1::IRuntime* runtime_{};
  nvinfer1::ICudaEngine* engine_{};
  nvinfer1::IExecutionContext* context_{};
  std::string input_name_;
  int input_w_{};
  size_t input_bytes_{};
  void* input_dev_{};
  std::vector<void*> output_host_, output_dev_;
  std::vector<size_t> output_bytes_;
};

struct Queue {
  std::mutex mu;
  std::condition_variable cv;
  std::deque<int> q;
  bool stopped{};
  bool pop(int& out) {
    std::unique_lock<std::mutex> lock(mu);
    cv.wait(lock, [&] { return stopped || !q.empty(); });
    if (q.empty()) return false;
    out = q.front();
    q.pop_front();
    return true;
  }
  void push(int v) {
    {
      std::lock_guard<std::mutex> lock(mu);
      q.push_back(v);
    }
    cv.notify_one();
  }
  void stop() {
    {
      std::lock_guard<std::mutex> lock(mu);
      stopped = true;
    }
    cv.notify_all();
  }
};

struct Stage1Slot {
  cv::Mat frame_bgr;
  float* host{};
  double read_ms{}, pre1_ms{};
};

struct Stage2Slot {
  float* host{};
  double read_ms{}, pre1_ms{}, infer1_ms{}, crop_ms{};
  float score{};
  double roi_area{};
  bool fallback{};
};

static cv::VideoCapture make_square_cap(const std::string& video_path, int target, int content_h) {
  int y = (target - content_h) / 2;
  std::string pipe =
      "filesrc location=" + video_path +
      " ! qtdemux ! h264parse ! nvv4l2decoder enable-max-performance=1"
      " ! nvvidconv ! video/x-raw(memory:NVMM),format=RGBA,width=" + std::to_string(target) +
      ",height=" + std::to_string(content_h) +
      " ! nvcompositor name=comp background=black sink_0::xpos=0 sink_0::ypos=" + std::to_string(y) +
      " sink_0::width=" + std::to_string(target) +
      " sink_0::height=" + std::to_string(content_h) +
      " ! video/x-raw(memory:NVMM),format=RGBA,width=" + std::to_string(target) +
      ",height=" + std::to_string(target) +
      " ! nvvidconv ! video/x-raw,format=BGRx"
      " ! videoconvert ! video/x-raw,format=BGR"
      " ! appsink drop=true sync=false max-buffers=4";
  return cv::VideoCapture(pipe, cv::CAP_GSTREAMER);
}

static void square_bgr_to_nchw(cv::Mat& frame, float* dst, int target, int content_h) {
  int pad_y = (target - content_h) / 2;
  if (pad_y > 0) {
    frame(cv::Rect(0, 0, target, pad_y)).setTo(cv::Scalar(114, 114, 114));
    frame(cv::Rect(0, pad_y + content_h, target, target - pad_y - content_h)).setTo(cv::Scalar(114, 114, 114));
  }
  cv::Mat rgb, f32;
  cv::cvtColor(frame, rgb, cv::COLOR_BGR2RGB);
  rgb.convertTo(f32, CV_32F, 1.0 / 255.0);
  cv::Mat chw[] = {
      cv::Mat(target, target, CV_32F, dst),
      cv::Mat(target, target, CV_32F, dst + target * target),
      cv::Mat(target, target, CV_32F, dst + 2 * target * target),
  };
  cv::split(f32, chw);
}

class CropPreprocessor {
 public:
  explicit CropPreprocessor(int target) : target_(target) {
    canvas_.create(target_, target_, CV_8UC3);
    rgb_.create(target_, target_, CV_8UC3);
    f32_.create(target_, target_, CV_32FC3);
  }
  void run(const cv::Mat& roi, float* dst) {
    canvas_.setTo(cv::Scalar(114, 114, 114));
    double scale = std::min(static_cast<double>(target_) / roi.cols, static_cast<double>(target_) / roi.rows);
    int nw = std::max(1, static_cast<int>(std::round(roi.cols * scale)));
    int nh = std::max(1, static_cast<int>(std::round(roi.rows * scale)));
    int x = (target_ - nw) / 2, y = (target_ - nh) / 2;
    resized_.create(nh, nw, CV_8UC3);
    cv::resize(roi, resized_, cv::Size(nw, nh), 0, 0, cv::INTER_LINEAR);
    resized_.copyTo(canvas_(cv::Rect(x, y, nw, nh)));
    cv::cvtColor(canvas_, rgb_, cv::COLOR_BGR2RGB);
    rgb_.convertTo(f32_, CV_32F, 1.0 / 255.0);
    cv::Mat chw[] = {
        cv::Mat(target_, target_, CV_32F, dst),
        cv::Mat(target_, target_, CV_32F, dst + target_ * target_),
        cv::Mat(target_, target_, CV_32F, dst + 2 * target_ * target_),
    };
    cv::split(f32_, chw);
  }
 private:
  int target_;
  cv::Mat canvas_, resized_, rgb_, f32_;
};

static cv::Rect select_top_box(const float* out, size_t count, int size, float conf, bool& found, float& score_out) {
  found = false;
  score_out = 0.0f;
  cv::Rect best(size / 4, size / 4, size / 2, size / 2);
  for (size_t i = 0; i + 5 < count; i += 6) {
    const float score = out[i + 4];
    if (score < conf || score <= score_out) continue;
    int x1 = std::clamp(static_cast<int>(std::floor(out[i + 0])), 0, size - 1);
    int y1 = std::clamp(static_cast<int>(std::floor(out[i + 1])), 0, size - 1);
    int x2 = std::clamp(static_cast<int>(std::ceil(out[i + 2])), 0, size - 1);
    int y2 = std::clamp(static_cast<int>(std::ceil(out[i + 3])), 0, size - 1);
    if (x2 <= x1 + 2 || y2 <= y1 + 2) continue;
    best = cv::Rect(x1, y1, x2 - x1, y2 - y1);
    score_out = score;
    found = true;
  }
  return best;
}

static void select_top_type(const float* out, size_t count, float conf, bool& found, float& score_out, int& class_out) {
  found = false;
  score_out = 0.0f;
  class_out = -1;
  for (size_t i = 0; i + 5 < count; i += 6) {
    const float score = out[i + 4];
    if (score < conf || score <= score_out) continue;
    score_out = score;
    class_out = static_cast<int>(std::round(out[i + 5]));
    found = true;
  }
}

int main(int argc, char** argv) {
  if (argc < 5) {
    std::cerr << "usage: " << argv[0] << " <stage1.raw.engine> <stage2.raw.engine> <video.mp4> <stage1_size> [stage2_size=416] [warmup=5] [measure=60] [s1_slots=4] [s2_slots=4]\n";
    return 1;
  }
  const std::string stage1_path = argv[1], stage2_path = argv[2], video_path = argv[3];
  const int stage1_size = std::atoi(argv[4]);
  const int stage2_size = argc > 5 ? std::atoi(argv[5]) : 416;
  const double warmup_sec = argc > 6 ? std::atof(argv[6]) : 5.0;
  const double measure_sec = argc > 7 ? std::atof(argv[7]) : 60.0;
  const int s1_slots_n = argc > 8 ? std::atoi(argv[8]) : 4;
  const int s2_slots_n = argc > 9 ? std::atoi(argv[9]) : 4;
  const int content_h = static_cast<int>(std::round(stage1_size * 9.0 / 16.0));

  Logger logger;
  TrtEngine stage1(stage1_path, logger), stage2(stage2_path, logger);
  if (stage1.input_w() != stage1_size || stage2.input_w() != stage2_size) return 2;
  cudaStream_t s1_stream{}, s2_stream{};
  check_cuda(cudaStreamCreate(&s1_stream), "s1 stream");
  check_cuda(cudaStreamCreate(&s2_stream), "s2 stream");

  std::vector<Stage1Slot> s1_slots(s1_slots_n);
  for (auto& s : s1_slots) {
    s.frame_bgr.create(stage1_size, stage1_size, CV_8UC3);
    check_cuda(cudaHostAlloc(reinterpret_cast<void**>(&s.host), stage1.input_bytes(), cudaHostAllocDefault), "s1 host");
  }
  std::vector<Stage2Slot> s2_slots(s2_slots_n);
  for (auto& s : s2_slots) check_cuda(cudaHostAlloc(reinterpret_cast<void**>(&s.host), stage2.input_bytes(), cudaHostAllocDefault), "s2 host");

  auto run_phase = [&](double seconds, bool measure) {
    Queue free1, ready1, free2, ready2;
    for (int i = 0; i < s1_slots_n; ++i) free1.push(i);
    for (int i = 0; i < s2_slots_n; ++i) free2.push(i);
    std::vector<double> read_ms, pre1_ms, infer1_ms, crop_ms, infer2_ms, type_parse_ms, active_ms, scores, roi_area, type_scores;
    int fallbacks = 0;
    std::atomic<int> frames{0};
    auto start = Clock::now();
    auto end = start + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(seconds));

    std::thread producer([&] {
      cv::VideoCapture cap = make_square_cap(video_path, stage1_size, content_h);
      cv::Mat frame;
      while (Clock::now() < end) {
        int idx = -1;
        if (!free1.pop(idx)) break;
        auto r0 = Clock::now();
        if (!cap.read(frame)) {
          cap.release();
          cap = make_square_cap(video_path, stage1_size, content_h);
          if (!cap.read(frame)) {
            free1.push(idx);
            break;
          }
        }
        auto r1 = Clock::now();
        if (frame.cols != stage1_size || frame.rows != stage1_size) std::exit(5);
        frame.copyTo(s1_slots[idx].frame_bgr);
        square_bgr_to_nchw(s1_slots[idx].frame_bgr, s1_slots[idx].host, stage1_size, content_h);
        auto p1 = Clock::now();
        s1_slots[idx].read_ms = std::chrono::duration<double, std::milli>(r1 - r0).count();
        s1_slots[idx].pre1_ms = std::chrono::duration<double, std::milli>(p1 - r1).count();
        ready1.push(idx);
      }
      ready1.stop();
      cap.release();
    });

    std::thread stage1_worker([&] {
      CropPreprocessor crop_pre(stage2_size);
      while (true) {
        int idx1 = -1;
        if (!ready1.pop(idx1)) break;
        double t1 = stage1.run(s1_stream, s1_slots[idx1].host);
        bool found = false;
        float score = 0.0f;
        cv::Rect box = select_top_box(stage1.output0(), stage1.output0_count(), stage1_size, 0.25f, found, score);
        int idx2 = -1;
        if (!free2.pop(idx2)) break;
        auto c0 = Clock::now();
        crop_pre.run(s1_slots[idx1].frame_bgr(box), s2_slots[idx2].host);
        auto c1 = Clock::now();
        s2_slots[idx2].read_ms = s1_slots[idx1].read_ms;
        s2_slots[idx2].pre1_ms = s1_slots[idx1].pre1_ms;
        s2_slots[idx2].infer1_ms = t1;
        s2_slots[idx2].crop_ms = std::chrono::duration<double, std::milli>(c1 - c0).count();
        s2_slots[idx2].score = score;
        s2_slots[idx2].roi_area = static_cast<double>(box.area()) / (stage1_size * stage1_size);
        s2_slots[idx2].fallback = !found;
        free1.push(idx1);
        ready2.push(idx2);
      }
      ready2.stop();
    });

    while (true) {
      int idx2 = -1;
      if (!ready2.pop(idx2)) break;
      double t2 = stage2.run(s2_stream, s2_slots[idx2].host);
      auto tp0 = Clock::now();
      bool type_found = false;
      float type_score = 0.0f;
      int type_class = -1;
      select_top_type(stage2.output0(), stage2.output0_count(), 0.25f, type_found, type_score, type_class);
      auto tp1 = Clock::now();
      if (measure) {
        ++frames;
        if (s2_slots[idx2].fallback) ++fallbacks;
        read_ms.push_back(s2_slots[idx2].read_ms);
        pre1_ms.push_back(s2_slots[idx2].pre1_ms);
        infer1_ms.push_back(s2_slots[idx2].infer1_ms);
        crop_ms.push_back(s2_slots[idx2].crop_ms);
        infer2_ms.push_back(t2);
        const double tp_ms = std::chrono::duration<double, std::milli>(tp1 - tp0).count();
        type_parse_ms.push_back(tp_ms);
        active_ms.push_back(s2_slots[idx2].read_ms + s2_slots[idx2].pre1_ms + s2_slots[idx2].infer1_ms + s2_slots[idx2].crop_ms + t2 + tp_ms);
        scores.push_back(s2_slots[idx2].score);
        roi_area.push_back(s2_slots[idx2].roi_area);
        type_scores.push_back(type_score);
      }
      free2.push(idx2);
    }
    free1.stop();
    free2.stop();
    producer.join();
    stage1_worker.join();
    auto stop = Clock::now();
    double wall_sec = std::chrono::duration<double>(stop - start).count();
    return std::tuple<int, double, int, std::vector<double>, std::vector<double>, std::vector<double>, std::vector<double>, std::vector<double>, std::vector<double>, std::vector<double>, std::vector<double>>(
        frames.load(), wall_sec, fallbacks, read_ms, pre1_ms, infer1_ms, crop_ms, infer2_ms, active_ms, scores, roi_area);
  };

  (void)run_phase(warmup_sec, false);
  auto [frames, wall_sec, fallbacks, read_ms, pre1_ms, infer1_ms, crop_ms, infer2_ms, active_ms, scores, roi_area] = run_phase(measure_sec, true);
  std::cout << "{"
            << "\"mode\":\"cascade_stage1_stage2_pipeline_parallel\","
            << "\"stage1_size\":" << stage1_size << ","
            << "\"stage2_requested_size\":400,"
            << "\"stage2_actual_size\":" << stage2_size << ","
            << "\"frames\":" << frames << ","
            << "\"wall_sec\":" << wall_sec << ","
            << "\"wall_fps\":" << (frames / wall_sec) << ","
            << "\"fallback_frames\":" << fallbacks << ","
            << "\"mean_read_ms\":" << mean(read_ms) << ","
            << "\"mean_stage1_pre_ms\":" << mean(pre1_ms) << ","
            << "\"mean_stage1_infer_ms\":" << mean(infer1_ms) << ","
            << "\"mean_crop_stage2_pre_ms\":" << mean(crop_ms) << ","
            << "\"mean_stage2_infer_ms\":" << mean(infer2_ms) << ","
            << "\"stage2_type_parse_included\":true,"
            << "\"mean_active_ms\":" << mean(active_ms) << ","
            << "\"p90_active_ms\":" << pct(active_ms, 90) << ","
            << "\"p99_active_ms\":" << pct(active_ms, 99) << ","
            << "\"mean_stage1_score\":" << mean(scores) << ","
            << "\"mean_roi_area_fraction\":" << mean(roi_area)
            << "}\n";

  cudaStreamDestroy(s1_stream);
  cudaStreamDestroy(s2_stream);
  for (auto& s : s1_slots) cudaFreeHost(s.host);
  for (auto& s : s2_slots) cudaFreeHost(s.host);
  return 0;
}
