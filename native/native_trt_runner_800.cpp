#include <NvInfer.h>
#include <cuda_runtime_api.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
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
    if (severity <= Severity::kWARNING) {
      std::cerr << "[TRT] " << msg << "\n";
    }
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
  if (!f) {
    throw std::runtime_error("cannot open engine: " + path);
  }
  f.seekg(0, std::ios::end);
  std::vector<char> data(static_cast<size_t>(f.tellg()));
  f.seekg(0, std::ios::beg);
  f.read(data.data(), static_cast<std::streamsize>(data.size()));
  return data;
}

static size_t dtype_size(nvinfer1::DataType t) {
  switch (t) {
    case nvinfer1::DataType::kFLOAT:
      return 4;
    case nvinfer1::DataType::kHALF:
      return 2;
    case nvinfer1::DataType::kINT8:
      return 1;
    case nvinfer1::DataType::kINT32:
      return 4;
    case nvinfer1::DataType::kBOOL:
      return 1;
    case nvinfer1::DataType::kUINT8:
      return 1;
#if NV_TENSORRT_MAJOR >= 10
    case nvinfer1::DataType::kFP8:
      return 1;
#endif
    default:
      return 4;
  }
}

static size_t volume(const nvinfer1::Dims& d) {
  size_t v = 1;
  for (int i = 0; i < d.nbDims; ++i) {
    v *= static_cast<size_t>(std::max<int64_t>(1, d.d[i]));
  }
  return v;
}

static std::string dims_str(const nvinfer1::Dims& d) {
  std::ostringstream oss;
  oss << "[";
  for (int i = 0; i < d.nbDims; ++i) {
    if (i) oss << ",";
    oss << d.d[i];
  }
  oss << "]";
  return oss.str();
}

static double percentile(std::vector<double> xs, double p) {
  if (xs.empty()) return 0.0;
  std::sort(xs.begin(), xs.end());
  double k = (xs.size() - 1) * p / 100.0;
  size_t lo = static_cast<size_t>(k);
  size_t hi = std::min(lo + 1, xs.size() - 1);
  double frac = k - static_cast<double>(lo);
  return xs[lo] * (1.0 - frac) + xs[hi] * frac;
}

static double mean(const std::vector<double>& xs) {
  if (xs.empty()) return 0.0;
  return std::accumulate(xs.begin(), xs.end(), 0.0) / static_cast<double>(xs.size());
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: " << argv[0] << " <raw.engine> [warmup_sec=5] [measure_sec=60]\n";
    return 1;
  }
  const std::string engine_path = argv[1];
  const double warmup_sec = argc > 2 ? std::atof(argv[2]) : 5.0;
  const double measure_sec = argc > 3 ? std::atof(argv[3]) : 60.0;

  Logger logger;
  auto bytes = read_file(engine_path);
  auto* runtime = nvinfer1::createInferRuntime(logger);
  auto* engine = runtime->deserializeCudaEngine(bytes.data(), bytes.size());
  if (!engine) {
    std::cerr << "deserializeCudaEngine failed\n";
    return 2;
  }
  auto* context = engine->createExecutionContext();
  if (!context) {
    std::cerr << "createExecutionContext failed\n";
    return 3;
  }

  std::string input_name;
  std::vector<std::string> output_names;
  for (int i = 0; i < engine->getNbIOTensors(); ++i) {
    const char* name = engine->getIOTensorName(i);
    auto mode = engine->getTensorIOMode(name);
    auto dims = engine->getTensorShape(name);
    auto type = engine->getTensorDataType(name);
    std::cerr << (mode == nvinfer1::TensorIOMode::kINPUT ? "INPUT " : "OUTPUT ")
              << name << " shape=" << dims_str(dims) << " dtype_bytes=" << dtype_size(type) << "\n";
    if (mode == nvinfer1::TensorIOMode::kINPUT) {
      input_name = name;
    } else {
      output_names.push_back(name);
    }
  }
  if (input_name.empty() || output_names.empty()) {
    std::cerr << "missing input/output tensors\n";
    return 4;
  }

  cudaStream_t stream{};
  check_cuda(cudaStreamCreate(&stream), "cudaStreamCreate");

  std::vector<std::string> tensor_names;
  tensor_names.push_back(input_name);
  tensor_names.insert(tensor_names.end(), output_names.begin(), output_names.end());

  struct Buf {
    std::string name;
    bool input{};
    size_t bytes{};
    void* host{};
    void* dev{};
  };
  std::vector<Buf> bufs;
  for (const auto& name : tensor_names) {
    auto dims = engine->getTensorShape(name.c_str());
    auto type = engine->getTensorDataType(name.c_str());
    size_t nbytes = volume(dims) * dtype_size(type);
    Buf b;
    b.name = name;
    b.input = (name == input_name);
    b.bytes = nbytes;
    check_cuda(cudaHostAlloc(&b.host, nbytes, cudaHostAllocDefault), "cudaHostAlloc");
    check_cuda(cudaMalloc(&b.dev, nbytes), "cudaMalloc");
    std::memset(b.host, b.input ? 0x3c : 0, nbytes);
    if (b.input) {
      check_cuda(cudaMemcpyAsync(b.dev, b.host, nbytes, cudaMemcpyHostToDevice, stream), "initial H2D");
    }
    context->setTensorAddress(name.c_str(), b.dev);
    bufs.push_back(b);
  }
  check_cuda(cudaStreamSynchronize(stream), "initial sync");

  auto run_one = [&](bool copy_input, bool copy_output) {
    auto t0 = Clock::now();
    for (auto& b : bufs) {
      if (b.input && copy_input) {
        check_cuda(cudaMemcpyAsync(b.dev, b.host, b.bytes, cudaMemcpyHostToDevice, stream), "H2D");
      }
    }
    if (!context->enqueueV3(stream)) {
      std::cerr << "enqueueV3 failed\n";
      std::exit(5);
    }
    for (auto& b : bufs) {
      if (!b.input && copy_output) {
        check_cuda(cudaMemcpyAsync(b.host, b.dev, b.bytes, cudaMemcpyDeviceToHost, stream), "D2H");
      }
    }
    check_cuda(cudaStreamSynchronize(stream), "sync");
    auto t1 = Clock::now();
    return std::chrono::duration<double, std::milli>(t1 - t0).count();
  };

  auto run_mode = [&](const std::string& name, bool copy_input, bool copy_output) {
    auto warm_end = Clock::now() + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(warmup_sec));
    while (Clock::now() < warm_end) {
      (void)run_one(copy_input, copy_output);
    }
    std::vector<double> times;
    auto start = Clock::now();
    auto end = start + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(measure_sec));
    while (Clock::now() < end) {
      times.push_back(run_one(copy_input, copy_output));
    }
    auto stop = Clock::now();
    double wall = std::chrono::duration<double>(stop - start).count();
    std::cout << "{"
              << "\"mode\":\"" << name << "\","
              << "\"frames\":" << times.size() << ","
              << "\"wall_sec\":" << wall << ","
              << "\"wall_fps\":" << (times.empty() ? 0.0 : times.size() / wall) << ","
              << "\"mean_ms\":" << mean(times) << ","
              << "\"p50_ms\":" << percentile(times, 50) << ","
              << "\"p90_ms\":" << percentile(times, 90) << ","
              << "\"p99_ms\":" << percentile(times, 99) << ","
              << "\"copy_input\":" << (copy_input ? "true" : "false") << ","
              << "\"copy_output\":" << (copy_output ? "true" : "false")
              << "}" << std::endl;
  };

  run_mode("native_trt_gpu_resident", false, false);
  run_mode("native_trt_h2d_d2h", true, true);

  for (auto& b : bufs) {
    cudaFree(b.dev);
    cudaFreeHost(b.host);
  }
  cudaStreamDestroy(stream);
  delete context;
  delete engine;
  delete runtime;
  return 0;
}
