// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// MoonLightIPR preview session: a long-lived process the plugin feeds packed scenes.
// Usage: moonlightipr_session <kernel.ptx>
//
// Commands arrive on standard input, one per line:
//   scene <generation> <path>   load a packed scene and restart accumulation
//   pause                       stop sampling but keep everything loaded
//   quit
// Events leave on standard output, in the form the MoonRay session already uses:
//   @@MODO_SESSION APPLIED <generation>    the scene is loaded
//   @@MODO_SHARED <generation> beauty ...  a frame is waiting in shared memory
//   @@MODO_SESSION DONE <generation>       the sample target was reached
//   @@MODO_SESSION FAILED <generation>     the scene was rejected; the reason is on standard error
#include "moonlightipr/moonlightipr.h"
#include "scene_loader.h"
#include "modo_shared_image.h"

#include <chrono>
#include <condition_variable>
#include <deque>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

// Standard input blocks, so a reader thread hands lines to the render loop.
class Commands {
public:
    Commands() : reader([this] {
        std::string line;
        while (std::getline(std::cin, line)) push(line);
        push("quit");   // the plugin closed the pipe or exited
    }) { reader.detach(); }

    bool waiting() {
        std::lock_guard<std::mutex> lock(mutex);
        return !lines.empty();
    }
    std::string next() {
        std::unique_lock<std::mutex> lock(mutex);
        ready.wait(lock, [this] { return !lines.empty(); });
        std::string line = lines.front();
        lines.pop_front();
        return line;
    }

private:
    void push(const std::string& line) {
        { std::lock_guard<std::mutex> lock(mutex); lines.push_back(line); }
        ready.notify_one();
    }
    std::mutex mutex;
    std::condition_variable ready;
    std::deque<std::string> lines;
    std::thread reader;
};

void event(const char* kind, const std::string& generation) {
    std::cout << "\n@@MODO_SESSION " << kind << " " << generation << std::endl;
}

}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: moonlightipr_session <kernel.ptx>" << std::endl;
        return 2;
    }
    try {
        moonlightipr::Renderer renderer(argv[1]);
        moonlightipr::SceneLoader loader(renderer);
        std::cout << "MoonLightIPR GPU preview on " << renderer.deviceName() << std::endl;
        Commands commands;
        ModoSharedImage sharedImage;
        std::vector<float> pixels;

        for (;;) {
            std::istringstream command(commands.next());
            std::string verb, generation, path;
            command >> verb >> generation;
            std::getline(command >> std::ws, path);     // a path may contain spaces
            if (verb == "quit") return 0;
            if (verb == "pause") continue;      // stop sampling; the loaded scene stays for the next one
            if (verb != "scene" || generation.empty() || path.empty()) {
                std::cerr << "MoonLightIPR ignored an unknown command" << std::endl;
                continue;
            }
            moonlightipr::SceneSettings settings;
            try {
                settings = loader.apply(path);
            } catch (const std::exception& error) {
                std::cerr << "MoonLightIPR scene rejected: " << error.what() << std::endl;
                event("FAILED", generation);
                continue;
            }
            event("APPLIED", generation);

            pixels.resize(size_t(settings.width) * settings.height * 3);
            auto lastFrame = std::chrono::steady_clock::now();
            uint32_t published = 0;
            auto publish = [&]() {
                if (!sharedImage.ready()) return false;
                if (settings.denoise) renderer.readDenoised(pixels.data()); else renderer.readBeauty(pixels.data());
                const bool sent = sharedImage.publish(generation, "beauty", settings.width, settings.height,
                    [&](size_t i, float* rgb) { rgb[0] = pixels[i * 3]; rgb[1] = pixels[i * 3 + 1]; rgb[2] = pixels[i * 3 + 2]; });
                if (sent) published = renderer.sampleCount();
                return sent;
            };
            while (renderer.sampleCount() < settings.targetSamples && !commands.waiting()) {
                renderer.render();
                // Show the first sample at once, then at most 30 frames a second.
                const auto now = std::chrono::steady_clock::now();
                if (!published || now - lastFrame >= std::chrono::milliseconds(33)) {
                    if (publish()) lastFrame = std::chrono::steady_clock::now();
                }
            }
            if (commands.waiting()) continue;   // a newer scene replaces this one

            // The viewer may still hold the previous frame; wait for it before the final one.
            while (published != renderer.sampleCount() && !commands.waiting() && !publish())
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
            if (!commands.waiting()) event("DONE", generation);
        }
    } catch (const std::exception& error) {
        std::cerr << "MoonLightIPR session failed: " << error.what() << std::endl;
        return 1;
    }
}
