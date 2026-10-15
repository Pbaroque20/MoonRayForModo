// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar.
// modo_composite: runs a compositor graph, already turned into steps by the plugin (compositor.py), over the
// buffers of a finished render. On the graphics card where there is one, otherwise on the processor; both run the
// same code for every pixel (ops.h), so they give the same picture.
//
//   modo_composite <steps file> [--cpu] [--ptx <MoonLightIPRComposite.ptx>]
//
// The steps file, a line each:
//   size <width> <height>               0 0: as large as the first picture read
//   kernel <taps> <weight>...          a blur kernel; numbered from 0 in the order given
//   load <slot> <file.pfm>             a buffer, three channels (or one, taken for all three)
//   step <kind> <a> <b> <m> <out> <i0> <i1> <f0> ... <f5>
//   save <slot> <file.pfm>
// It says on standard output which it ran on: "@@COMPOSITE gpu <name>" or "@@COMPOSITE cpu <threads>".
#include "ops.h"

#include <cuda_runtime.h>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

using composite::Step;

struct Plan {
    int width = 0, height = 0;
    std::vector<float> kernels;
    std::vector<std::pair<int, std::string>> loads, saves;
    std::vector<Step> steps;
    int slots = 0;
};

Plan readPlan(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("Cannot read the steps: " + path);
    Plan plan;
    std::string line;
    while (std::getline(in, line)) {
        std::istringstream words(line);
        std::string what;
        if (!(words >> what)) continue;
        if (what == "size") {
            words >> plan.width >> plan.height;
        } else if (what == "kernel") {
            int taps = 0;
            words >> taps;
            for (int i = 0; i < taps; ++i) { float w = 0; words >> w; plan.kernels.push_back(w); }
        } else if (what == "load" || what == "save") {
            int slot = -1;
            words >> slot >> std::ws;
            std::string file;
            std::getline(words, file);
            (what == "load" ? plan.loads : plan.saves).push_back({slot, file});
            plan.slots = std::max(plan.slots, slot + 1);
        } else if (what == "step") {
            Step s{};
            words >> s.kind >> s.a >> s.b >> s.m >> s.out >> s.i0 >> s.i1;
            for (float& f : s.f) words >> f;
            plan.steps.push_back(s);
            plan.slots = std::max({plan.slots, s.a + 1, s.b + 1, s.m + 1, s.out + 1});
        } else {
            throw std::runtime_error("Unknown line in the steps: " + line);
        }
        if (!words && !words.eof()) throw std::runtime_error("Cannot read the line: " + line);
    }
    if (plan.width <= 0 || plan.height <= 0) {
        // Of the render: the first picture read says.
        if (plan.loads.empty()) throw std::runtime_error("The steps give no size and read no picture");
        std::ifstream first(plan.loads.front().second, std::ios::binary);
        std::string kind;
        first >> kind >> plan.width >> plan.height;
        if (!first || plan.width <= 0 || plan.height <= 0) throw std::runtime_error("Cannot read the size of " + plan.loads.front().second);
    }
    if (plan.kernels.empty()) plan.kernels.push_back(1.0f);
    return plan;
}

// A PFM picture, rows from the top, three floats a pixel. PFM keeps its bottom row first.
void readPfm(const std::string& path, int width, int height, std::vector<float>& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot read " + path);
    std::string kind; int w = 0, h = 0; float scale = 0;
    in >> kind >> w >> h >> scale;
    in.get();
    if ((kind != "PF" && kind != "Pf") || w != width || h != height)
        throw std::runtime_error("Not a picture of the render's size: " + path);
    const int channels = kind == "PF" ? 3 : 1;
    std::vector<float> data(size_t(w) * h * channels);
    in.read(reinterpret_cast<char*>(data.data()), std::streamsize(data.size() * sizeof(float)));
    if (!in) throw std::runtime_error("The picture is cut short: " + path);
    if (scale > 0) {    // big-endian
        for (float& v : data) { unsigned char* b = reinterpret_cast<unsigned char*>(&v); std::swap(b[0], b[3]); std::swap(b[1], b[2]); }
    }
    out.assign(size_t(w) * h * 3, 0.0f);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            for (int c = 0; c < 3; ++c)
                out[(size_t(y) * w + x) * 3 + c] = data[(size_t(h - 1 - y) * w + x) * channels + (channels == 3 ? c : 0)];
}

void writePfm(const std::string& path, int width, int height, const std::vector<float>& picture) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot write " + path);
    out << "PF\n" << width << " " << height << "\n-1.0\n";
    for (int y = height - 1; y >= 0; --y)
        out.write(reinterpret_cast<const char*>(picture.data() + size_t(y) * width * 3), std::streamsize(size_t(width) * 3 * sizeof(float)));
    if (!out) throw std::runtime_error("Cannot write " + path);
}

void check(cudaError_t result, const char* what) {
    if (result != cudaSuccess) throw std::runtime_error(std::string(what) + ": " + cudaGetErrorString(result));
}

// On the graphics card: false where there is none, or it cannot be used, so that the processor does it.
bool onGraphicsCard(const Plan& plan, std::vector<std::vector<float>>& pictures, const std::string& ptxPath) {
    int count = 0;
    if (cudaGetDeviceCount(&count) != cudaSuccess || count == 0) return false;
    std::ifstream file(ptxPath, std::ios::binary);
    const std::string ptx((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    if (ptx.empty()) return false;
    cudaLibrary_t library = nullptr;
    if (cudaLibraryLoadData(&library, ptx.c_str(), nullptr, nullptr, 0, nullptr, nullptr, 0) != cudaSuccess) return false;
    cudaKernel_t kernel = nullptr;
    check(cudaLibraryGetKernel(&kernel, library, "compositeStep"), "Finding the compositor's program");
    const size_t size = size_t(plan.width) * plan.height * 3 * sizeof(float);
    std::vector<float*> slots(plan.slots, nullptr);
    for (int i = 0; i < plan.slots; ++i) {
        check(cudaMalloc(reinterpret_cast<void**>(&slots[i]), size), "Room for a picture on the graphics card");
        if (!pictures[i].empty()) check(cudaMemcpy(slots[i], pictures[i].data(), size, cudaMemcpyHostToDevice), "Sending a picture");
        else check(cudaMemset(slots[i], 0, size), "Clearing a picture");
    }
    float** slotTable = nullptr;
    float* kernels = nullptr;
    check(cudaMalloc(reinterpret_cast<void**>(&slotTable), slots.size() * sizeof(float*)), "Room for the picture table");
    check(cudaMemcpy(slotTable, slots.data(), slots.size() * sizeof(float*), cudaMemcpyHostToDevice), "Sending the picture table");
    check(cudaMalloc(reinterpret_cast<void**>(&kernels), plan.kernels.size() * sizeof(float)), "Room for the blur kernels");
    check(cudaMemcpy(kernels, plan.kernels.data(), plan.kernels.size() * sizeof(float), cudaMemcpyHostToDevice), "Sending the blur kernels");
    composite::Pictures device{slotTable, kernels, plan.width, plan.height};
    const dim3 block(16, 16), grid((plan.width + 15) / 16, (plan.height + 15) / 16);
    for (Step step : plan.steps) {
        void* args[] = {&step, &device};
        check(cudaLaunchKernel(reinterpret_cast<const void*>(kernel), grid, block, args, 0, nullptr), "Running a step");
    }
    check(cudaDeviceSynchronize(), "Finishing the steps");
    for (const auto& saved : plan.saves) {
        pictures[saved.first].resize(size_t(plan.width) * plan.height * 3);
        check(cudaMemcpy(pictures[saved.first].data(), slots[saved.first], size, cudaMemcpyDeviceToHost), "Taking a picture back");
    }
    for (float* slot : slots) cudaFree(slot);
    cudaFree(slotTable);
    cudaFree(kernels);
    cudaLibraryUnload(library);
    cudaDeviceProp properties{};
    cudaGetDeviceProperties(&properties, 0);
    std::cout << "@@COMPOSITE gpu " << properties.name << std::endl;
    return true;
}

void onProcessor(const Plan& plan, std::vector<std::vector<float>>& pictures) {
    const size_t size = size_t(plan.width) * plan.height * 3;
    for (auto& picture : pictures) if (picture.empty()) picture.assign(size, 0.0f);
    std::vector<float*> slots;
    for (auto& picture : pictures) slots.push_back(picture.data());
    const composite::Pictures host{slots.data(), plan.kernels.data(), plan.width, plan.height};
    const int threads = std::max(1u, std::thread::hardware_concurrency());
    for (const Step& step : plan.steps) {
        std::vector<std::thread> workers;
        for (int t = 0; t < threads; ++t) {
            workers.emplace_back([&, t]() {
                for (int y = t; y < plan.height; y += threads)
                    for (int x = 0; x < plan.width; ++x) {
                        float value[3];
                        composite::evaluate(step, host, x, y, value);
                        float* out = slots[step.out] + (size_t(y) * plan.width + x) * 3;
                        out[0] = value[0]; out[1] = value[1]; out[2] = value[2];
                    }
            });
        }
        for (auto& worker : workers) worker.join();
    }
    std::cout << "@@COMPOSITE cpu " << threads << std::endl;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) throw std::runtime_error("modo_composite <steps file> [--cpu] [--ptx <file>]");
        bool cpu = false;
        std::string ptx;
        for (int i = 2; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--cpu") cpu = true;
            else if (arg == "--ptx" && i + 1 < argc) ptx = argv[++i];
        }
        if (ptx.empty()) {
            std::string self = argv[0];
            const size_t slash = self.find_last_of("/\\");
            ptx = (slash == std::string::npos ? std::string() : self.substr(0, slash + 1)) + "MoonLightIPRComposite.ptx";
        }
        const Plan plan = readPlan(argv[1]);
        for (const Step& step : plan.steps) {
            const int largest = (step.kind == composite::MEDIAN) ? step.i0 * step.i0 : 0;
            if (largest > 169) throw std::runtime_error("A median wider than 13 pixels");
            if ((step.kind == composite::BLUR_X || step.kind == composite::BLUR_Y) && (step.i1 < 0 || size_t(step.i1 + step.i0) > plan.kernels.size()))
                throw std::runtime_error("A blur kernel that is not there");
        }
        std::vector<std::vector<float>> pictures(plan.slots);
        for (const auto& loaded : plan.loads) readPfm(loaded.second, plan.width, plan.height, pictures[loaded.first]);
        bool done = false;
        if (!cpu) {
            try {
                done = onGraphicsCard(plan, pictures, ptx);
            } catch (const std::exception& error) {
                std::cerr << "Graphics card compositing failed (" << error.what() << "); the processor does it." << std::endl;
            }
        }
        if (!done) onProcessor(plan, pictures);
        for (const auto& saved : plan.saves) writePfm(saved.second, plan.width, plan.height, pictures[saved.first]);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "modo_composite: " << error.what() << std::endl;
        return 1;
    }
}
