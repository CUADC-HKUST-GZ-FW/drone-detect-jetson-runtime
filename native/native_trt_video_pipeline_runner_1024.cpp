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

struct Slot {
  float* input_host{};
  double read_ms{};
  double pre_ms{};
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

static cv::VideoCapture make_cap(const std::string& video_path, int caps_w, int caps_h) {
  std::string caps = "video/x-raw,format=BGRx";
  if (caps_w > 0 && caps_h > 0) {
    caps += ",width=" + std::to_string(caps_w) + ",height=" + std::to_string(caps_h);
  }
  std::string pipe =
      "filesrc location=" + video_path +
      " ! qtdemux ! h264parse ! nvv4l2decoder enable-max-performance=1"
      " ! nvvidconv ! " + caps +
      " ! videoconvert ! video/x-raw,format=BGR"
      " ! appsink drop=true sync=false max-buffers=4";
  cv::VideoCapture cap(pipe, cv::CAP_GSTREAMER);
  if (!cap.isOpened()) cap.open(video_path);
  return cap;
}

class Preprocessor {
 public:
  explicit Preprocessor(int target) : target_(target) {
    canvas_.create(target_, target_, CV_8UC3);
    rgb_.create(target_, target_, CV_8UC3);
    f32_.create(target_, target_, CV_32FC3);
  }

  void run(const cv::Mat& frame, float* dst) {
    canvas_.setTo(cv::Scalar(114, 114, 114));
    double scale = std::min(static_cast<double>(target_) / frame.cols, static_cast<double>(target_) / frame.rows);
    int nw = static_cast<int>(std::round(frame.cols * scale));
    int nh = static_cast<int>(std::round(frame.rows * scale));
    int x = (target_ - nw) / 2;
    int y = (target_ - nh) / 2;
    resized_.create(nh, nw, CV_8UC3);
    cv::resize(frame, resized_, cv::Size(nw, nh), 0, 0, cv::INTER_LINEAR);
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
  cv::Mat canvas_;
  cv::Mat resized_;
  cv::Mat rgb_;
  cv::Mat f32_;
};

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "usage: " << argv[0] << " <raw.engine> <video.mp4> [warmup_sec=5] [measure_sec=60] [target=1024] [slots=4] [caps_w=0] [caps_h=0]\n";
    return 1;
  }
  std::string engine_path = argv[1];
  std::string video_path = argv[2];
  double warmup_sec = argc > 3 ? std::atof(argv[3]) : 5.0;
  double measure_sec = argc > 4 ? std::atof(argv[4]) : 60.0;
  int target = argc > 5 ? std::atoi(argv[5]) : 1024;
  int slots_n = argc > 6 ? std::atoi(argv[6]) : 4;
  int caps_w = argc > 7 ? std::atoi(argv[7]) : 0;
  int caps_h = argc > 8 ? std::atoi(argv[8]) : 0;

  Logger logger;
  auto bytes = read_file(engine_path);
  auto* runtime = nvinfer1::createInferRuntime(logger);
  auto* engine = runtime->deserializeCudaEngine(bytes.data(), bytes.size());
  auto* context = engine->createExecutionContext();
  if (!engine || !context) return 2;

  std::string input_name;
  size_t input_bytes = 0;
  void* input_dev{};
  std::vector<std::string> output_names;
  std::vector<void*> output_host;
  std::vector<void*> output_dev;
  std::vector<size_t> output_bytes;

  for (int i = 0; i < engine->getNbIOTensors(); ++i) {
    const char* name = engine->getIOTensorName(i);
    auto dims = engine->getTensorShape(name);
    size_t nbytes = volume(dims) * dtype_size(engine->getTensorDataType(name));
    if (engine->getTensorIOMode(name) == nvinfer1::TensorIOMode::kINPUT) {
      input_name = name;
      input_bytes = nbytes;
      check_cuda(cudaMalloc(&input_dev, nbytes), "input dev");
      context->setTensorAddress(name, input_dev);
    } else {
      output_names.push_back(name);
      void* h{};
      void* d{};
      check_cuda(cudaHostAlloc(&h, nbytes, cudaHostAllocDefault), "output host");
      check_cuda(cudaMalloc(&d, nbytes), "output dev");
      context->setTensorAddress(name, d);
      output_host.push_back(h);
      output_dev.push_back(d);
      output_bytes.push_back(nbytes);
    }
  }
  if (input_name.empty() || output_names.empty()) return 3;

  std::vector<Slot> slots(slots_n);
  for (auto& s : slots) {
    check_cuda(cudaHostAlloc(reinterpret_cast<void**>(&s.input_host), input_bytes, cudaHostAllocDefault), "slot input host");
  }

  cudaStream_t stream{};
  check_cuda(cudaStreamCreate(&stream), "stream");

  auto run_phase = [&](double seconds, bool measure) {
    Queue free_q;
    Queue ready_q;
    for (int i = 0; i < slots_n; ++i) free_q.push(i);
    std::atomic<bool> producer_done{false};
    std::atomic<int> frames{0};
    std::vector<double> read_ms;
    std::vector<double> pre_ms;
    std::vector<double> infer_ms;
    std::vector<double> wall_ms;
    auto start = Clock::now();
    auto end = start + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(seconds));

    std::thread producer([&] {
      cv::VideoCapture cap = make_cap(video_path, caps_w, caps_h);
      Preprocessor prep(target);
      cv::Mat frame;
      while (Clock::now() < end) {
        int idx = -1;
        if (!free_q.pop(idx)) break;
        auto t0 = Clock::now();
        auto r0 = Clock::now();
        if (!cap.read(frame)) {
          cap.release();
          cap = make_cap(video_path, caps_w, caps_h);
          if (!cap.read(frame)) {
            free_q.push(idx);
            break;
          }
        }
        auto r1 = Clock::now();
        prep.run(frame, slots[idx].input_host);
        auto p1 = Clock::now();
        slots[idx].read_ms = std::chrono::duration<double, std::milli>(r1 - r0).count();
        slots[idx].pre_ms = std::chrono::duration<double, std::milli>(p1 - r1).count();
        ready_q.push(idx);
        (void)t0;
      }
      producer_done = true;
      ready_q.stop();
      cap.release();
    });

    while (!producer_done || true) {
      int idx = -1;
      if (!ready_q.pop(idx)) break;
      auto t0 = Clock::now();
      check_cuda(cudaMemcpyAsync(input_dev, slots[idx].input_host, input_bytes, cudaMemcpyHostToDevice, stream), "H2D");
      if (!context->enqueueV3(stream)) {
        std::cerr << "enqueue failed\n";
        std::exit(4);
      }
      for (size_t i = 0; i < output_dev.size(); ++i) {
        check_cuda(cudaMemcpyAsync(output_host[i], output_dev[i], output_bytes[i], cudaMemcpyDeviceToHost, stream), "D2H");
      }
      check_cuda(cudaStreamSynchronize(stream), "sync");
      auto t1 = Clock::now();
      if (measure) {
        ++frames;
        read_ms.push_back(slots[idx].read_ms);
        pre_ms.push_back(slots[idx].pre_ms);
        infer_ms.push_back(std::chrono::duration<double, std::milli>(t1 - t0).count());
        wall_ms.push_back(slots[idx].read_ms + slots[idx].pre_ms + std::chrono::duration<double, std::milli>(t1 - t0).count());
      }
      free_q.push(idx);
    }
    free_q.stop();
    producer.join();
    auto stop = Clock::now();
    double wall_sec = std::chrono::duration<double>(stop - start).count();
    return std::tuple<int, double, std::vector<double>, std::vector<double>, std::vector<double>, std::vector<double>>(
        frames.load(), wall_sec, read_ms, pre_ms, infer_ms, wall_ms);
  };

  (void)run_phase(warmup_sec, false);
  auto [frames, wall_sec, read_ms, pre_ms, infer_ms, wall_ms] = run_phase(measure_sec, true);

  std::cout << "{"
            << "\"mode\":\"native_cpp_gstreamer_preprocess_trt_pipeline\","
            << "\"target\":" << target << ","
            << "\"slots\":" << slots_n << ","
            << "\"caps_w\":" << caps_w << ","
            << "\"caps_h\":" << caps_h << ","
            << "\"frames\":" << frames << ","
            << "\"wall_sec\":" << wall_sec << ","
            << "\"wall_fps\":" << (frames / wall_sec) << ","
            << "\"mean_wall_ms\":" << mean(wall_ms) << ","
            << "\"p90_wall_ms\":" << pct(wall_ms, 90) << ","
            << "\"p99_wall_ms\":" << pct(wall_ms, 99) << ","
            << "\"mean_read_ms\":" << mean(read_ms) << ","
            << "\"mean_preprocess_ms\":" << mean(pre_ms) << ","
            << "\"mean_infer_copy_ms\":" << mean(infer_ms)
            << "}\n";

  cudaStreamDestroy(stream);
  cudaFree(input_dev);
  for (auto& s : slots) cudaFreeHost(s.input_host);
  for (auto* p : output_dev) cudaFree(p);
  for (auto* p : output_host) cudaFreeHost(p);
  delete context;
  delete engine;
  delete runtime;
  return 0;
}
