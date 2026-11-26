// Visibility-first geometry (the user's "just in time rendering for geometry", 2026-11-26): a heavy scene's coarse first
// pass (coarse_geometry.h) is followed by a plan whose geometry the camera sees is at full detail and the rest stand-ins
// still, then by the full plan, each made behind the pictures on the refine job's thread (xpu2_session.cc RefineJob).
//
// 1. What the camera sees: a grid of camera rays (every stride pixels each way) traced on the coarse plan's CPU scene,
//    their first hits (in the frame and not behind anything; what is seen only through glass is left to the full plan).
// 2. Everything else stays a stand-in: the coarse pass's own meshes, taken over as they are (cpu::Limits::fullDetail).
// 3. The full plan then takes the visible meshes over and makes the rest. Neither the coarse plan nor the visible one is
//    the scene complete: their samples are pictures alone, as the coarse pass's are, and the frame renders from its
//    start on the full plan, so that the film is XPU2's to the bit.
// A camera moved meanwhile sees on what is rendered then: the geometry it newly sees goes before the rest (promoted).
// XPU2_SESSION_VISIBLE_FIRST=0: the coarse pass's full plan straight after it, as before. Host code alone.
#pragma once
#include "async_cpu.h"
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <memory>
#include <set>
#include <string>
#include <thread>
#include <vector>

namespace xpu2::interactive::visibility {

inline bool on() {
    static const bool v = [] {
        const char* e = std::getenv("XPU2_SESSION_VISIBLE_FIRST");
        return !(e && e[0] == '0');
    }();
    return v;
}
// One camera ray every stride pixels each way (XPU2_SESSION_VISIBLE_STRIDE, 4 by default: 32,400 rays at 960x540).
inline unsigned stride() {
    static const unsigned v = [] {
        const char* e = std::getenv("XPU2_SESSION_VISIBLE_STRIDE");
        const long n = e ? std::atol(e) : 0;
        return n > 0 ? unsigned(std::min(n, 64L)) : 4u;
    }();
    return v;
}

struct Seen {
    std::shared_ptr<std::set<std::string>> geometries = std::make_shared<std::set<std::string>>();  // every geometry seen
    std::set<std::string> standIns;     // the plan's stand-in geometries (a coarse mesh of theirs)
    std::set<std::string> standInsSeen; // of them, the ones seen
    size_t rays = 0, hits = 0;
    double seconds = 0;
    // Worth a plan of its own: some stand-ins seen, and some not (all seen: the full plan is that plan).
    bool worth() const { return !standInsSeen.empty() && standInsSeen.size() < standIns.size(); }
};

// The geometries the camera's rays meet first on a plan's CPU scene (the plan's camera, or the one given).
inline Seen seen(const cpu::Plan& plan, const async::CpuScene& scene, const surface::Camera* camera = nullptr) {
    const auto began = std::chrono::steady_clock::now();
    Seen out;
    for (const auto& m : plan.meshes)
        if (m.data && m.data->coarse && !m.geometry.empty()) out.standIns.insert(m.geometry);
    const surface::Camera& cam = camera ? *camera : plan.camera;
    const unsigned w = plan.width, h = plan.height, s = stride();
    if (!w || !h || plan.meshes.empty()) return out;
    const unsigned rows = (h + s - 1) / s, cols = (w + s - 1) / s;
    const unsigned threads = std::max(1u, std::min(8u, std::thread::hardware_concurrency() / 2));
    std::vector<std::vector<unsigned char>> hit(threads, std::vector<unsigned char>(plan.meshes.size(), 0));
    std::vector<size_t> rays(threads, 0), hits(threads, 0);
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < threads; ++t)
        pool.emplace_back([&, t] {
            const async::CpuBackend backend{scene};
            for (unsigned r = t; r < rows; r += threads)
                for (unsigned c = 0; c < cols; ++c) {
                    surface::Ray ray;
                    if (!surface::cameraRay(cam, float(c * s) + 0.5f * float(s), float(r * s) + 0.5f * float(s), ray)) continue;
                    ray.mask = 1u;  // a camera ray
                    ++rays[t];
                    const resume::Hit found = backend.trace(ray);
                    if (found.geom == ~0u || found.geom >= hit[t].size()) continue;
                    ++hits[t];
                    hit[t][found.geom] = 1;
                }
        });
    for (auto& p : pool) p.join();
    for (unsigned t = 0; t < threads; ++t) {
        out.rays += rays[t];
        out.hits += hits[t];
        for (size_t i = 0; i < plan.meshes.size(); ++i)
            if (hit[t][i] && !plan.meshes[i].geometry.empty()) out.geometries->insert(plan.meshes[i].geometry);
    }
    for (const auto& g : out.standIns)
        if (out.geometries->count(g)) out.standInsSeen.insert(g);
    out.seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
    return out;
}

}  // namespace xpu2::interactive::visibility
