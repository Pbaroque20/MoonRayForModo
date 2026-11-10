// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// MoonLightIPR preview session: a long-lived process the plugin feeds packed scenes.
// Usage: moonlightipr_session <kernel.ptx>
//
// Commands arrive on standard input, one per line:
//   scene <generation> <path>   load a packed scene and restart accumulation
//   pause                       stop sampling but keep everything loaded
//   finish <generation>         stop sampling and send what is rendered so far as the finished picture
//   quit
// Events leave on standard output, in the form the MoonRay session already uses:
//   @@MODO_SESSION APPLIED <generation>    the scene is loaded
//   @@MODO_SHARED <generation> beauty ...  a frame is waiting in shared memory
//   @@MODO_SESSION DONE <generation>       the picture is clean, or the sample target was reached
//   @@MODO_SESSION SAMPLES <generation> <n> the frame about to be sent holds n samples a pixel
// AOVs ("aov <n> <name>", 0 for the beauty): 1 to 4 a light pass (AovPass), rendered in place of the beauty, the
// render begun again with it; from 5 a geometry AOV (AovSlot n - 5), gathered beside the beauty, all of them at once
// from the first asked for (the render then begun again, once), and after that only another picture sent, at once, in
// the middle of a render or after it. Either is sent under its name.
//   @@MODO_SESSION FAILED <generation>     the scene was rejected; the reason is on standard error
#include "moonlightipr/moonlightipr.h"
#include "scene_loader.h"
#include "modo_shared_image.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
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
    // The line that next() would give, without taking it.
    std::string front() {
        std::lock_guard<std::mutex> lock(mutex);
        return lines.empty() ? std::string() : lines.front();
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

// The light passes (1 to LIGHT_PASSES, AovPass) and the geometry AOVs after them (AovSlot), as src/device/shared.h has them.
const unsigned LIGHT_PASSES = 4, GEOMETRY_AOVS = 5;

void event(const char* kind, const std::string& generation) {
    std::cout << "\n@@MODO_SESSION " << kind << " " << generation << std::endl;
}

// How many samples a pixel the frame just sent holds, for the label under the picture.
void samplesSent(const std::string& generation, uint32_t samples) {
    std::cout << "\n@@MODO_SESSION SAMPLES " << generation << " " << samples << std::endl;
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

        // How long a render is spread over at least (see the render loop). MOONLIGHTIPR_PACE, in seconds, chooses for
        // experiments; 0 renders as fast as the graphics card can.
        const char* paced = std::getenv("MOONLIGHTIPR_PACE");
        const std::chrono::duration<double> pace(paced ? std::max(0.0, std::atof(paced)) : 8.0);

        // The scene last applied, for a finish to send as it stands.
        moonlightipr::SceneSettings lastSettings;
        std::string lastGeneration;
        // Which picture is sent of a scene that is denoised: the denoised one, or the beauty as it is rendered.
        // Both are there all the while; the host says which it is looking at, and may change its mind at any time.
        bool showDenoised = true, viewChanged = false;
        // The AOV looked at (its AovSlot, or -1 for the beauty), by the host's name for it, which its frames are sent under.
        int aovShown = -1;
        std::string aovName;
        // The picture sent: the AOV looked at, else the denoised picture or the beauty. Its name is returned.
        auto readPicture = [&](const moonlightipr::SceneSettings& settings) -> std::string {
            if (aovShown >= 0 && renderer.aovs()) { renderer.readAov(uint32_t(aovShown), pixels.data()); return aovName; }
            // A light pass, in the beauty's place: not denoised.
            if (renderer.pass()) { renderer.readBeauty(pixels.data()); return aovName; }
            if (settings.denoise && showDenoised) renderer.readDenoised(pixels.data()); else renderer.readBeauty(pixels.data());
            return "beauty";
        };
        // Takes what the host says about that as it comes, in the middle of a render or between two. True where
        // something else is waiting, which is for the render to give way to.
        auto interrupted = [&]() {
            while (commands.waiting()) {
                const std::string line = commands.front();
                if (line.rfind("aov ", 0) == 0) {
                    // Another AOV while they are gathered (or the beauty): only another picture to send.
                    std::istringstream words(line.substr(4));
                    unsigned n = 0;
                    std::string name;
                    words >> n >> name;
                    // Another light pass, or the first geometry AOV: the render begins again with it.
                    if ((n <= LIGHT_PASSES && n != renderer.pass()) || (n > LIGHT_PASSES && !renderer.aovs())) return true;
                    commands.next();
                    aovShown = n > LIGHT_PASSES ? int(n - LIGHT_PASSES - 1) : -1;
                    aovName = n ? name : std::string();
                    viewChanged = true;
                    continue;
                }
                if (line.rfind("view ", 0) != 0) return true;
                commands.next();
                const bool denoised = line.find(" beauty") == std::string::npos;
                if (denoised != showDenoised) { showDenoised = denoised; viewChanged = true; }
            }
            return false;
        };
        auto send = [&](const moonlightipr::SceneSettings& settings, const std::string& generation) {
            if (!sharedImage.ready()) return false;
            const std::string key = readPicture(settings);
            // Said before the frame, so that the frame is shown with its own count.
            samplesSent(generation, renderer.sampleCount());
            return sharedImage.publish(generation, key, settings.width, settings.height,
                [&](size_t i, float* rgb) { rgb[0] = pixels[i * 3]; rgb[1] = pixels[i * 3 + 1]; rgb[2] = pixels[i * 3 + 2]; });
        };

        for (;;) {
            std::istringstream command(commands.next());
            std::string verb, generation, path;
            command >> verb >> generation;
            std::getline(command >> std::ws, path);     // a path may contain spaces
            moonlightipr::SceneSettings settings;
            if (verb == "quit") return 0;
            if (verb == "aov") {
                const unsigned n = unsigned(std::strtoul(generation.c_str(), nullptr, 10));
                if (n > LIGHT_PASSES + GEOMETRY_AOVS) continue;
                aovShown = n > LIGHT_PASSES ? int(n - LIGHT_PASSES - 1) : -1;
                aovName = n ? path : std::string();
                // Another light pass (or the beauty again), or the first geometry AOV asked for: rendered again with it,
                // a render already finished as well, unless the host has more to say first (a new scene).
                const bool again = n <= LIGHT_PASSES ? n != renderer.pass() : !renderer.aovs();
                if (again) {
                    if (n <= LIGHT_PASSES) renderer.setPass(n); else renderer.setAovs(true);
                    if (lastGeneration.empty() || commands.waiting()) continue;
                    settings = lastSettings;
                    generation = lastGeneration;
                    goto render;
                }
                // Between renders: the picture there is, sent as the one now looked at.
                if (!lastGeneration.empty() && renderer.sampleCount() > 0)
                    while (!interrupted() && !send(lastSettings, lastGeneration))
                        std::this_thread::sleep_for(std::chrono::milliseconds(2));
                continue;
            }
            if (verb == "pause") continue;      // stop sampling; the loaded scene stays for the next one
            if (verb == "view") {
                // Between renders: the picture there is, sent again as the one now looked at.
                const bool denoised = path != "beauty";
                if (denoised != showDenoised) {
                    showDenoised = denoised;
                    if (!lastGeneration.empty() && renderer.sampleCount() > 0)
                        while (!interrupted() && !send(lastSettings, lastGeneration))
                            std::this_thread::sleep_for(std::chrono::milliseconds(2));
                    viewChanged = false;
                }
                continue;
            }
            if (verb == "finish") {
                // Stopped by the user, who wants what there is: sent whole, and reported as done.
                if (!lastGeneration.empty() && generation == lastGeneration && renderer.sampleCount() > 0) {
                    while (!commands.waiting() && !send(lastSettings, generation))
                        std::this_thread::sleep_for(std::chrono::milliseconds(2));
                    if (!commands.waiting()) event("DONE", generation);
                }
                continue;
            }
            if (verb != "scene" || generation.empty() || path.empty()) {
                std::cerr << "MoonLightIPR ignored an unknown command" << std::endl;
                continue;
            }
            try {
                settings = loader.apply(path);
            } catch (const std::exception& error) {
                std::cerr << "MoonLightIPR scene rejected: " << error.what() << std::endl;
                event("FAILED", generation);
                continue;
            }
            event("APPLIED", generation);
            lastSettings = settings;
            lastGeneration = generation;

        render:
            pixels.resize(size_t(settings.width) * settings.height * 3);
            const auto began = std::chrono::steady_clock::now();
            auto lastFrame = began;
            uint32_t published = 0;
            auto publish = [&]() {
                if (!sharedImage.ready()) return false;
                const std::string key = readPicture(settings);
                samplesSent(generation, renderer.sampleCount());
                const bool sent = sharedImage.publish(generation, key, settings.width, settings.height,
                    [&](size_t i, float* rgb) { rgb[0] = pixels[i * 3]; rgb[1] = pixels[i * 3 + 1]; rgb[2] = pixels[i * 3 + 2]; });
                if (sent) published = renderer.sampleCount();
                return sent;
            };
            while (renderer.sampleCount() < settings.targetSamples && !renderer.converged() && !interrupted()) {
                renderer.render();
                // Paced: the samples are spread over about PACE, however quickly the graphics card could gather
                // them, so that it is left room between them and an edit (a step of a drag) has it at once. The
                // first is shown as soon as it is rendered, with no wait; a scene the card cannot render that quickly is not slowed.
                // A scene that asks for it flat out (a playblast's frame) has no edit to leave room for.
                const auto due = began + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                    (settings.flatOut ? std::chrono::duration<double>(0.0) : pace) * (double(renderer.sampleCount() - 1) / double(settings.targetSamples)));
                while (std::chrono::steady_clock::now() < due && !interrupted())
                    std::this_thread::sleep_for(std::min<std::chrono::steady_clock::duration>(due - std::chrono::steady_clock::now(), std::chrono::milliseconds(5)));
                if (interrupted()) break;
                // The other picture was asked for: it is sent at once, not at the next thirtieth of a second.
                if (viewChanged) { viewChanged = false; published = 0; }
                // Show the first sample at once, then at most 30 frames a second while an edit is fresh, and fewer as
                // the picture settles (each frame shown is denoised and copied): 10 a second after the first one,
                // 4 after four.
                const auto now = std::chrono::steady_clock::now();
                const auto settled = now - began;
                const auto interval = std::chrono::milliseconds(settled < std::chrono::seconds(1) ? 33 : settled < std::chrono::seconds(4) ? 100 : 250);
                if (!published || now - lastFrame >= interval) {
                    if (publish()) lastFrame = std::chrono::steady_clock::now();
                }
            }
            if (interrupted()) continue;   // a newer scene replaces this one

            // The viewer may still hold the previous frame; wait for it before the final one.
            if (viewChanged) { viewChanged = false; published = 0; }
            while (published != renderer.sampleCount() && !interrupted() && !publish())
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
            if (renderer.converged() && !interrupted())
                std::cout << "MoonLightIPR clean at " << renderer.sampleCount() << " samples a pixel" << std::endl;
            if (!interrupted()) event("DONE", generation);
        }
    } catch (const std::exception& error) {
        std::cerr << "MoonLightIPR session failed: " << error.what() << std::endl;
        return 1;
    }
}
