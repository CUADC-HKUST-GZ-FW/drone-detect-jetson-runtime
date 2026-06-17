#include <NvInfer.h>
#include <cuda_runtime_api.h>
#include <opencv2/opencv.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
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

struct Buffers {
  std::string input_name;
  std::vector<std::string> output_names;
  void* input_host{};
  void* input_dev{};
  size_t input_bytes{};
  std::vector<void*> output_host;
  std::vector<void*> output_dev;
  std::vector<size_t> output_bytes;
};

static void preprocess_bgr_to_nchw(const cv::Mat& frame, float* dst, int target) {
  cv::Mat canvas(target, target, CV_8UC3, cv::Scalar(114, 114, 114));
  double scale = std::min(static_cast<double>(target) / frame.cols, static_cast<double>(target) / frame.rows);
  int nw = static_cast<int>(std::round(frame.cols * scale));
  int nh = static_cast<int>(std::round(frame.rows * scale));
  int x = (target - nw) / 2;
  int y = (target - nh) / 2;
  cv::Mat resized;
  cv::resize(frame, resized, cv::Size(nw, nh), 0, 0, cv::INTER_LINEAR);
  resized.copyTo(canvas(cv::Rect(x, y, nw, nh)));

  cv::Mat rgb, f32;
  cv::cvtColor(canvas, rgb, cv::COLOR_BGR2RGB);
  rgb.convertTo(f32, CV_32F, 1.0 / 255.0);
  std::vector<cv::Mat> chw = {
      cv::Mat(target, target, CV_32F, dst),
      cv::Mat(target, target, CV_32F, dst + target * target),
      cv::Mat(target, target, CV_32F, dst + 2 * target * target),
  };
  cv::split(f32, chw);
}

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "usage: " << argv[0] << " <raw.engine> <video.mp4> [warmup_sec=5] [measure_sec=60]\n";
    return 1;
  }
  std::string engine_path = argv[1];
  std::string video_path = argv[2];
  double warmup_sec = argc > 3 ? std::atof(argv[3]) : 5.0;
  double measure_sec = argc > 4 ? std::atof(argv[4]) : 60.0;

  Logger logger;
  auto bytes = read_file(engine_path);
  auto* runtime = nvinfer1::createInferRuntime(logger);
  auto* engine = runtime->deserializeCudaEngine(bytes.data(), bytes.size());
  auto* context = engine->createExecutionContext();
  if (!engine || !context) return 2;

  Buffers b;
  for (int i = 0; i < engine->getNbIOTensors(); ++i) {
    const char* name = engine->getIOTensorName(i);
    auto dims = engine->getTensorShape(name);
    size_t nbytes = volume(dims) * dtype_size(engine->getTensorDataType(name));
    if (engine->getTensorIOMode(name) == nvinfer1::TensorIOMode::kINPUT) {
      b.input_name = name;
      b.input_bytes = nbytes;
      check_cuda(cudaHostAlloc(&b.input_host, nbytes, cudaHostAllocDefault), "input host");
      check_cuda(cudaMalloc(&b.input_dev, nbytes), "input dev");
      context->setTensorAddress(name, b.input_dev);
    } else {
      b.output_names.push_back(name);
      void* h{};
      void* d{};
      check_cuda(cudaHostAlloc(&h, nbytes, cudaHostAllocDefault), "output host");
      check_cuda(cudaMalloc(&d, nbytes), "output dev");
      context->setTensorAddress(name, d);
      b.output_host.push_back(h);
      b.output_dev.push_back(d);
      b.output_bytes.push_back(nbytes);
    }
  }

  cudaStream_t stream{};
  check_cuda(cudaStreamCreate(&stream), "stream");

  auto make_cap = [&]() {
    std::string pipe =
        "filesrc location=" + video_path +
        " ! qtdemux ! h264parse ! nvv4l2decoder enable-max-performance=1"
        " ! nvvidconv ! video/x-raw,format=BGRx"
        " ! videoconvert ! video/x-raw,format=BGR"
        " ! appsink drop=true sync=false max-buffers=2";
    cv::VideoCapture cap(pipe, cv::CAP_GSTREAMER);
    if (!cap.isOpened()) {
      cap.open(video_path);
    }
    return cap;
  };

  cv::VideoCapture cap = make_cap();
  if (!cap.isOpened()) {
    std::cerr << "cannot open video\n";
    return 3;
  }

  std::vector<double> wall, read_ms, pre_ms, infer_ms;
  int frames = 0;
  auto run_until = [&](double seconds, bool measure) {
    auto end = Clock::now() + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(seconds));
    cv::Mat frame;
    while (Clock::now() < end) {
      auto t0 = Clock::now();
      auto r0 = Clock::now();
      if (!cap.read(frame)) {
        cap.release();
        cap = make_cap();
        if (!cap.read(frame)) break;
      }
      auto r1 = Clock::now();
      preprocess_bgr_to_nchw(frame, static_cast<float*>(b.input_host), 800);
      auto p1 = Clock::now();
      check_cuda(cudaMemcpyAsync(b.input_dev, b.input_host, b.input_bytes, cudaMemcpyHostToDevice, stream), "H2D");
      if (!context->enqueueV3(stream)) {
        std::cerr << "enqueue failed\n";
        std::exit(4);
      }
      for (size_t i = 0; i < b.output_dev.size(); ++i) {
        check_cuda(cudaMemcpyAsync(b.output_host[i], b.output_dev[i], b.output_bytes[i], cudaMemcpyDeviceToHost, stream), "D2H");
      }
      check_cuda(cudaStreamSynchronize(stream), "sync");
      auto t1 = Clock::now();
      if (measure) {
        frames++;
        wall.push_back(std::chrono::duration<double, std::milli>(t1 - t0).count());
        read_ms.push_back(std::chrono::duration<double, std::milli>(r1 - r0).count());
        pre_ms.push_back(std::chrono::duration<double, std::milli>(p1 - r1).count());
        infer_ms.push_back(std::chrono::duration<double, std::milli>(t1 - p1).count());
      }
    }
  };

  run_until(warmup_sec, false);
  auto start = Clock::now();
  run_until(measure_sec, true);
  auto stop = Clock::now();
  double wall_sec = std::chrono::duration<double>(stop - start).count();
  std::cout << "{"
            << "\"mode\":\"native_cpp_gstreamer_preprocess_trt\","
            << "\"frames\":" << frames << ","
            << "\"wall_sec\":" << wall_sec << ","
            << "\"wall_fps\":" << (frames / wall_sec) << ","
            << "\"mean_wall_ms\":" << mean(wall) << ","
            << "\"p90_wall_ms\":" << pct(wall, 90) << ","
            << "\"p99_wall_ms\":" << pct(wall, 99) << ","
            << "\"mean_read_ms\":" << mean(read_ms) << ","
            << "\"mean_preprocess_ms\":" << mean(pre_ms) << ","
            << "\"mean_infer_copy_ms\":" << mean(infer_ms)
            << "}\n";

  cap.release();
  cudaStreamDestroy(stream);
  cudaFree(b.input_dev);
  cudaFreeHost(b.input_host);
  for (auto* p : b.output_dev) cudaFree(p);
  for (auto* p : b.output_host) cudaFreeHost(p);
  delete context;
  delete engine;
  delete runtime;
  return 0;
}
