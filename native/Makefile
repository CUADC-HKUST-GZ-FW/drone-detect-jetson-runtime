CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -DNDEBUG
CUDA_HOME ?= /usr/local/cuda
TRT_INC ?= /usr/include/aarch64-linux-gnu
TRT_LIB ?= /usr/lib/aarch64-linux-gnu
BUILD_DIR ?= build

OPENCV_CFLAGS := $(shell pkg-config --cflags opencv4 2>/dev/null)
OPENCV_LIBS := $(shell pkg-config --libs opencv4 2>/dev/null)

CPPFLAGS += -I$(CUDA_HOME)/include -I$(TRT_INC) $(OPENCV_CFLAGS)
LDFLAGS += -L$(CUDA_HOME)/lib64 -L$(TRT_LIB)
LDLIBS += -lnvinfer -lnvinfer_plugin -lcudart $(OPENCV_LIBS) -lpthread

TARGETS := \
	$(BUILD_DIR)/native_trt_runner_800 \
	$(BUILD_DIR)/native_trt_video_runner_800 \
	$(BUILD_DIR)/native_trt_video_runner_1024 \
	$(BUILD_DIR)/native_trt_video_pipeline_runner_1024 \
	$(BUILD_DIR)/native_trt_video_strict_square_runner_1024 \
	$(BUILD_DIR)/cascade_trt_runner \
	$(BUILD_DIR)/cascade_trt_pipeline_runner

.PHONY: all clean

all: $(TARGETS)

$(BUILD_DIR):
	mkdir -p $@

$(BUILD_DIR)/%: %.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(CPPFLAGS) $< -o $@ $(LDFLAGS) $(LDLIBS)

clean:
	rm -rf $(BUILD_DIR)
