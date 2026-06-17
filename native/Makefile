CXX ?= g++
CUDA_HOME ?= /usr/local/cuda
BUILD_DIR ?= build

OPENCV_CFLAGS := $(shell pkg-config --cflags opencv4 2>/dev/null)
OPENCV_LIBS := $(shell pkg-config --libs opencv4 2>/dev/null)

CXXFLAGS ?= -O3 -DNDEBUG -std=c++17 -Wall -Wextra
CXXFLAGS += $(OPENCV_CFLAGS) -I/usr/include/opencv4 -I/usr/include/aarch64-linux-gnu -I$(CUDA_HOME)/include
LDFLAGS += -L/usr/lib/aarch64-linux-gnu -L$(CUDA_HOME)/lib64
LDLIBS += $(OPENCV_LIBS) -lnvinfer -lnvinfer_plugin -lcudart -lpthread

BINS := $(BUILD_DIR)/native_trt_video_pipeline_runner $(BUILD_DIR)/native_trt_video_strict_square_runner

.PHONY: all clean

all: $(BINS)

$(BUILD_DIR):
	mkdir -p $@

$(BUILD_DIR)/native_trt_video_pipeline_runner: native_trt_video_pipeline_runner.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS) $(LDLIBS)

$(BUILD_DIR)/native_trt_video_strict_square_runner: native_trt_video_strict_square_runner.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS) $(LDLIBS)

clean:
	rm -rf $(BUILD_DIR)
