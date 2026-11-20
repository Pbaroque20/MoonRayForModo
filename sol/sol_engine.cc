// Sol: a probe tracer over XPU2's asynchronous renderer (sol/DESIGN.md).
//
// sol_engine scene runtime ptx assets output [key=value ...]
//
// Geometry. Sol's indexer (virtual_surface.h) reconstructs the frame's visible surface from probes in geometric passes:
//   a coarse quadtree of probes (stride s0), each probe's camera ray traced on the CPU (Embree) and its mesh scanned
//   ring by ring (scan.h); a quad that has not converged within the tolerance (sandwich gap, the scans' topology, other
//   geometry in front) splits for the next pass, down to min_stride. The result is the virtual surface: sites and quads,
//   packed as one piece any device evaluates per pixel without the meshes.
// Phase 1. An XPU2 frame of the probes' direct light (max_depth 0, probe_spp samples a probe pixel, none elsewhere).
// Phase 2. An XPU2 frame of full paths, n(x) samples a pixel by the pixel's state in the virtual surface (trusted,
//   background, or not converged), with two light path outputs that sum to a path's direct light at its first hit
//   (C[<L.>O] and C[DGS][<L.>O]).
// Combination. final = B + m / (m + n) (R1 - D): B and D phase 2's beauty and direct light means, R1 the virtual
//   surface's reconstruction of phase 1's light, m the samples it counts as (0 where not converged).
//
// Writes raw float32 RGBA films and prints one JSON report. No Modo API.
#include "async_render.h"
#include "virtual_surface.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
#include <thread>

using namespace xpu2::interactive;
namespace rdl = scene_rdl2::rdl2;
using Clock = std::chrono::steady_clock;

static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

namespace {

struct Options {
    unsigned threads = 12, probeSpp = 16, nLo = 8, nHi = 32, nBg = 1;
    int mode = 2, p1mode = 1;
    double m0 = 64, tauR = 0.25, margin = -1;  // margin -1: from the pixel filter
    sol::SurfaceOptions surface;
    std::string override_;
    unsigned repeats = 3;            // timed runs after one warm-up
    std::vector<unsigned> xpu2Spp;  // XPU2 frames to time in the same process (samples a pixel)
    // Phase 2's frame cache (mixed::Config::frameCache): on, the chance a bounce that reaches it goes on, the depth
    // tolerance; OpenQMC past the first hit (qmc_depth: vertices of nonMirrorDepth below it), and in XPU2's frames too.
    bool cache = false;  // off by default: it needs the engine's own GPU program (build_sol.py --gpu)
    double cacheP = 0.25, cacheTol = 0.02;
    unsigned qmcDepth = 0, xpu2Qmc = 0;
};

uint32_t mix(uint32_t a) {
    a ^= a >> 16;
    a *= 0x7feb352du;
    a ^= a >> 15;
    a *= 0x846ca68bu;
    a ^= a >> 16;
    return a;
}

std::string readFile(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    return f ? std::string((std::istreambuf_iterator<char>(f)), {}) : std::string();
}

void writeFloats(const fs::path& p, const std::vector<float>& v) {
    std::ofstream o(p, std::ios::binary);
    o.write(reinterpret_cast<const char*>(v.data()), v.size() * sizeof(float));
    cpu::need(bool(o), "Image write");
}

// An output's channel offset in a pixel's AOV values (-1: not there).
int aovOffset(const cpu::Plan& plan, const std::string& name) {
    if (!plan.aovs) return -1;
    for (const auto* o : plan.aovs->all)
        if (o->name == name && o->entry >= 0) return int(plan.aovs->entries[o->entry].offset);
    return -1;
}

// The states' colours in classes.png (sol::State order).
const float palette[sol::States][3] = {{0.1f, 0.1f, 0.1f}, {0.2f, 0.8f, 0.3f}, {0.2f, 0.5f, 1.0f}, {0.0f, 0.8f, 0.8f}, {0.9f, 0.2f, 0.2f},
                                       {1.0f, 1.0f, 1.0f}, {0.8f, 0.2f, 0.9f}, {1.0f, 0.5f, 0.1f}, {0.9f, 0.8f, 0.2f}, {0.5f, 0.5f, 0.5f}};
// A quadtree level's colour in leaves.png (coarse dark blue to fine yellow).
const float levels[6][3] = {{0.10f, 0.15f, 0.45f}, {0.15f, 0.40f, 0.65f}, {0.20f, 0.60f, 0.55f}, {0.55f, 0.75f, 0.30f}, {0.95f, 0.85f, 0.25f},
                            {1.0f, 0.5f, 0.2f}};

}  // namespace

int main(int argc, char** argv) {
    try {
        cpu::need(argc >= 6, "scene runtime ptx assets output [key=value ...]");
        const auto began = Clock::now();
        const fs::path out(argv[5]);
        Options op;
        for (int i = 6; i < argc; ++i) {
            const std::string a = argv[i];
            const auto eq = a.find('=');
            cpu::need(eq != std::string::npos, "option " + a);
            const std::string k = a.substr(0, eq), v = a.substr(eq + 1);
            if (k == "threads") op.threads = unsigned(std::stoul(v));
            else if (k == "mode") op.mode = std::stoi(v);
            else if (k == "p1mode") op.p1mode = std::stoi(v);
            else if (k == "s0") op.surface.s0 = unsigned(std::stoul(v));
            else if (k == "min_stride") op.surface.minStride = unsigned(std::stoul(v));
            else if (k == "tol") op.surface.tol = std::stod(v);
            else if (k == "margin") op.margin = std::stod(v);
            else if (k == "probe_spp") op.probeSpp = unsigned(std::stoul(v));
            else if (k == "n_lo") op.nLo = unsigned(std::stoul(v));
            else if (k == "n_hi") op.nHi = unsigned(std::stoul(v));
            else if (k == "n_bg") op.nBg = unsigned(std::stoul(v));
            else if (k == "m0") op.m0 = std::stod(v);
            else if (k == "tau_r") op.tauR = std::stod(v);
            else if (k == "rings") op.surface.rings = unsigned(std::stoul(v));
            else if (k == "tris") op.surface.tris = unsigned(std::stoul(v));
            else if (k == "override") op.override_ = v;
            else if (k == "repeats") op.repeats = unsigned(std::stoul(v));
            else if (k == "cache") op.cache = v != "0";
            else if (k == "cache_p") op.cacheP = std::stod(v);
            else if (k == "cache_tol") op.cacheTol = std::stod(v);
            else if (k == "qmc_depth") op.qmcDepth = unsigned(std::stoul(v));
            else if (k == "xpu2_qmc") op.xpu2Qmc = unsigned(std::stoul(v));
            else if (k == "xpu2_spp") {
                for (size_t a = 0, b; a < v.size(); a = b + 1) {
                    b = v.find(',', a);
                    if (b == std::string::npos) b = v.size();
                    op.xpu2Spp.push_back(unsigned(std::stoul(v.substr(a, b - a))));
                }
            }
            else cpu::need(false, "unknown option " + k);
        }
        op.surface.threads = op.threads;
        cpu::need(op.surface.s0 >= 2 && op.surface.s0 <= 256 && op.surface.minStride >= 1 && op.mode >= 0 && op.mode <= 2 && op.p1mode >= 0 &&
                      op.p1mode <= 2 && op.surface.tol > 0,
                  "Option bounds");
        if (op.mode == 0) op.p1mode = 0;

        // The GPU program and its modules, as async_probe.cc reads them.
        const fs::path ptxDir = fs::path(argv[3]).parent_path();
        const std::string ptx = readFile(argv[3]);
        cpu::need(!ptx.empty(), "PTX read");
        async::GpuOptions gpuOptions;
        const std::string materialPtx = readFile(ptxDir / "material" / "async_material.ptx"), chainPtx = readFile(ptxDir / "adaptive" / "async_adaptive.ptx");
        gpuOptions.mapsPtx = readFile(ptxDir / "maps" / "async_maps.ptx");
        gpuOptions.lightsPtx = readFile(ptxDir / "lights" / "async_lights.ptx");
        gpuOptions.lobesPtx = readFile(ptxDir / "lobes" / "async_lobes.ptx");
        gpuOptions.volumesPtx = readFile(ptxDir / "volumes" / "async_volumes.ptx");
        gpuOptions.volumeMapsPtx = readFile(ptxDir / "volumemaps" / "async_volumes.ptx");
        gpuOptions.dwaPtx = readFile(ptxDir / "dwa" / "async_dwa.ptx");
        gpuOptions.dwaLobesPtx = readFile(ptxDir / "dwalobes" / "async_dwalobes.ptx");
        gpuOptions.extrasPtx = readFile(ptxDir / "extras" / "async_extras.ptx");

        Json::Value report;
        auto stamp = Clock::now();
        rdl::SceneContext source;
        source.setProxyModeEnabled(true);
        source.setDsoPath(argv[2]);
        rdl::readSceneFromFile(argv[1], source);
        if (!op.override_.empty()) rdl::readSceneFromFile(op.override_, source);
        report["read_seconds"] = since(stamp);

        stamp = Clock::now();
        CanonicalSession canonical(argv[2], {3301, 0, 0, 0});
        auto frameKey = canonical.prepare(source, out / "canonical", {3301, 1, 1, 1});
        cpu::sequenceDirectory() = ptxDir;
        cpu::PlanView plan = cpu::prepare(canonical, frameKey, {}, cpu::Limits{}, argv[4], cpu::Domain::SurfaceTextures, true, true);
        cpu::need(canonical.acknowledge(frameKey) && canonical.publish(frameKey), "Canonical publish");
        cpu::need(!plan->adaptive, "The engine samples uniformly: set XPU2_SESSION_UNIFORM_BUDGET=0 and a uniform scene");
        cpu::need(plan->pixelSamples.empty(), "A scene with its own pixel sample map");
        cpu::need(plan->camera.type == surface::CameraPerspective && !plan->camera.dof && !plan->motion.on,
                  "The prototype lifts a still perspective camera without depth of field");
        report["plan_seconds"] = since(stamp);

        stamp = Clock::now();
        async::CpuScene cpuScene(plan);
        report["embree_seconds"] = since(stamp);
        stamp = Clock::now();
        std::unique_ptr<async::GpuLane> gpu;
        if (op.mode != 0) {
            gpu = std::make_unique<async::GpuLane>(ptx, materialPtx, chainPtx, gpuOptions);
            gpu->prepare(plan);
        }
        report["gpu_prepare_seconds"] = since(stamp);
        report["prepare_seconds"] = since(began);

        const unsigned W = plan->width, H = plan->height, spp = plan->spp;
        cpu::need(op.probeSpp >= 1 && op.probeSpp <= spp && op.nHi <= spp && op.nLo <= spp && op.nBg >= 1 && op.nLo >= 1,
                  "Sample counts must lie in [1, the scene's samples a pixel]");
        if (op.margin < 0) op.margin = std::max(1.0, 0.5 * plan->filterWidth + 0.5);
        op.surface.margin = op.margin;
        sol::Frame frame;
        cpu::need(frame.init(plan->camera), "Camera frame");
        // The frame cache's lift on the device takes the camera transform as affine (three columns and a translation).
        cpu::need(std::fabs(frame.toCamera[0][3]) < 1e-9 && std::fabs(frame.toCamera[1][3]) < 1e-9 && std::fabs(frame.toCamera[2][3]) < 1e-9 &&
                      std::fabs(frame.toCamera[3][3] - 1) < 1e-9,
                  "An affine camera transform");
        const size_t N = size_t(W) * H;

        // Sol's indexer: the geometry index, kept across frames (clusters now, topologies when a probe needs them).
        sol::GeometryIndex index;
        stamp = Clock::now();
        index.index(*plan, op.threads);
        report["index_seconds"] = since(stamp);
        report["index_clusters"] = Json::UInt64(index.clusterCount);
        Json::Value runs(Json::arrayValue);
        sol::VirtualSurface vs;

        // Run 0 warms up (texture tiles reach the card, topologies are made); runs 1..repeats are timed.
        for (unsigned rep = 0; rep <= op.repeats; ++rep) {
        const bool last = rep == op.repeats;

        // The geometric passes.
        stamp = Clock::now();
        vs.build(*plan, cpuScene, frame, index, op.surface);
        const double geometrySeconds = since(stamp);

        // Phase 1's frame: the probes' direct light (max_depth 0), probe_spp samples a probe pixel, none elsewhere.
        auto p1 = std::make_shared<cpu::Plan>(*plan);
        p1->maxDepth = 0;
        p1->pixelSamples.assign(N, 0u);
        for (const auto& s : vs.sites) p1->pixelSamples[size_t(s.py) * W + s.px] = op.probeSpp;
        // The grid hands out sample indices up to the plan's spp for every pixel: no more than any pixel takes.
        p1->spp = op.probeSpp;
        async::RenderOptions o1;
        o1.threads = op.threads;
        o1.mode = op.p1mode;
        stamp = Clock::now();
        if (gpu) gpu->updateCamera(p1);
        async::RenderResult r1;
        {
            async::Renderer renderer(p1, cpuScene, gpu.get());
            r1 = renderer.render(o1);
        }
        cpu::need(!r1.failed, r1.error.empty() ? "Phase 1 failed" : r1.error);
        const double phase1Seconds = since(stamp);

        // The piece: the virtual surface with the probes' light, packed; each pixel evaluated from it alone.
        stamp = Clock::now();
        vs.takeRadiance(r1.rgba);
        const std::vector<uint8_t> piece = sol::pack(vs, float(op.tauR));
        const sol::SurfaceView view(piece);
        std::vector<float> recon(N * 4, 0.0f), wvis(N, 0.0f);
        std::vector<uint8_t> cls(N, sol::Truncated), level(N, 0);
        std::vector<int> ownerOf(N, -1), leafOf(N, -1);
        sol::parallel(op.threads, H, [&](size_t y) {
            for (unsigned x = 0; x < W; ++x) {
                const size_t i = y * W + x;
                const sol::PixelSurface p = sol::evaluate(view, int(x), int(y));
                for (int c = 0; c < 3; ++c) recon[i * 4 + c] = p.rgb[c];
                recon[i * 4 + 3] = 1;
                wvis[i] = p.w;
                cls[i] = p.state;
                level[i] = uint8_t(std::min(p.level, 5));
                ownerOf[i] = p.owner;
                leafOf[i] = p.leaf;
            }
        });
        // Each state's phase 2 samples and phase 1's weight.
        std::vector<float> mWeight(N, 0.0f);
        std::vector<unsigned> nCount(N, op.nHi);
        uint64_t classCount[sol::States] = {};
        for (size_t i = 0; i < N; ++i) {
            ++classCount[cls[i]];
            switch (cls[i]) {
                case sol::Background: nCount[i] = op.nBg, mWeight[i] = float(op.m0); break;
                case sol::Trusted: nCount[i] = op.nLo, mWeight[i] = float(op.m0); break;
                default: nCount[i] = op.nHi, mWeight[i] = 0; break;
            }
        }
        const double regionSeconds = since(stamp);

        // Phase 2: full paths, n(x) a pixel, with the direct light's two expressions.
        auto p2 = std::make_shared<cpu::Plan>(*plan);
        p2->pixelSamples = nCount;
        p2->spp = *std::max_element(nCount.begin(), nCount.end());
        // The frame cache: phase 1's radiance and the visible inverse depth where the virtual surface converged, for
        // phase 2's bounces (async_integrator.h frameCacheAt), and OpenQMC past the first hit.
        if (op.cache) {
            auto cache = std::make_shared<std::vector<float>>(N * 4, 0.0f);
            for (size_t i = 0; i < N; ++i) {
                if (cls[i] != sol::Trusted) continue;
                for (int k = 0; k < 3; ++k) (*cache)[i * 4 + k] = recon[i * 4 + k];
                (*cache)[i * 4 + 3] = wvis[i];
            }
            p2->frameCache = cache;
            p2->cacheContinue = float(op.cacheP);
            p2->cacheDepthTolerance = float(op.cacheTol);
            for (int i = 0; i < 4; ++i)
                for (int j = 0; j < 3; ++j) p2->cacheToCamera[i * 3 + j] = float(frame.toCamera[i][j]);
            const float raster[8] = {float(frame.o.x), float(frame.o.y), float(frame.o.z), float(frame.ex.x), float(frame.ex.y),
                                     float(frame.ey.x), float(frame.ey.y), float(frame.det)};
            std::copy(raster, raster + 8, p2->cacheRaster);
        }
        p2->qmcDepth = op.qmcDepth;
        const int offEmit = aovOffset(*p2, "/sol_emission"), offDirect = aovOffset(*p2, "/sol_direct");
        cpu::need(offEmit >= 0 && offDirect >= 0, "The scene needs the outputs /sol_emission and /sol_direct (run_sol.py adds them)");
        async::RenderOptions o2;
        o2.threads = op.threads;
        o2.mode = op.mode;
        stamp = Clock::now();
        if (gpu) gpu->updateCamera(p2);
        async::RenderResult r2;
        {
            async::Renderer renderer(p2, cpuScene, gpu.get());
            r2 = renderer.render(o2);
        }
        cpu::need(!r2.failed, r2.error.empty() ? "Phase 2 failed" : r2.error);
        const double phase2Seconds = since(stamp);

        // The combination.
        stamp = Clock::now();
        const size_t stride = r2.aov.size() / N;
        cpu::need(stride * N == r2.aov.size(), "AOV layout");
        std::vector<float> direct2(N * 4, 0.0f), final(N * 4, 0.0f);
        double samples2 = 0;
        for (size_t i = 0; i < N; ++i) {
            const float* av = &r2.aov[i * stride];
            const float n = float(nCount[i]), m = mWeight[i], k = m / (m + n);
            samples2 += n;
            for (int c = 0; c < 3; ++c) {
                const float d = av[offEmit + c] + av[offDirect + c];
                direct2[i * 4 + c] = d;
                final[i * 4 + c] = r2.rgba[i * 4 + c] + k * (recon[i * 4 + c] - d);
            }
            direct2[i * 4 + 3] = 1;
            final[i * 4 + 3] = r2.rgba[i * 4 + 3];
        }
        const double combineSeconds = since(stamp);

        {
            Json::Value t;
            t["geometry_seconds"] = geometrySeconds;
            t["phase1_seconds"] = phase1Seconds;
            t["phase1_sampling_seconds"] = r1.seconds;
            t["region_seconds"] = regionSeconds;
            t["phase2_seconds"] = phase2Seconds;
            t["phase2_sampling_seconds"] = r2.seconds;
            t["combine_seconds"] = combineSeconds;
            t["total_seconds"] = geometrySeconds + phase1Seconds + regionSeconds + phase2Seconds + combineSeconds;
            t["clusters_seconds"] = vs.clusterSeconds;
            t["topology_seconds"] = vs.topologySeconds;
            Json::Value ps(Json::arrayValue);
            for (const auto& p : vs.passes) {
                Json::Value j;
                j["level"] = p.level;
                j["quads"] = Json::UInt64(p.quads);
                j["new_sites"] = Json::UInt64(p.newSites);
                j["sites"] = Json::UInt64(p.sites);
                j["refined"] = Json::UInt64(p.refined);
                for (int s = 0; s < sol::States; ++s)
                    if (p.states[s]) j["leaves"][sol::stateName(s)] = Json::UInt64(p.states[s]);
                j["trace_seconds"] = p.traceSeconds;
                j["scan_seconds"] = p.scanSeconds;
                j["test_seconds"] = p.testSeconds;
                j["seconds"] = p.seconds;
                ps.append(j);
            }
            t["passes"] = ps;
            t["warm_up"] = rep == 0;
            runs.append(t);
        }
        if (!last) continue;

        // What the virtual surface is worth: every pixel's centre traced (for the report alone, not timed), its true
        // inverse depth and mesh against the reconstruction's where it converged.
        std::vector<float> wTrue(N, 0.0f);
        std::vector<uint32_t> gTrue(N, ~0u);
        sol::parallel(op.threads, H, [&](size_t y) {
            async::CpuBackend backend{cpuScene};
            for (unsigned x = 0; x < W; ++x) {
                surface::Ray ray;
                if (!surface::cameraRay(plan->camera, x + 0.5f, y + 0.5f, ray)) continue;
                ray.mask = 1u;
                const resume::Hit h = backend.trace(ray);
                if (h.geom == ~0u) continue;
                const surface::V3 p{ray.origin.x + h.t * ray.direction.x, ray.origin.y + h.t * ray.direction.y, ray.origin.z + h.t * ray.direction.z};
                const sol::D3 c = frame.camera(p);
                if (c.z < 0) wTrue[y * W + x] = float(1.0 / -c.z);
                gTrue[y * W + x] = h.geom;
            }
        });
        std::vector<double> rel;
        uint64_t over1 = 0, over10 = 0, meshWrong = 0, backgroundWrong = 0, trusted = 0;
        std::vector<float> geomerr(N * 4, 0.0f);
        for (size_t i = 0; i < N; ++i) {
            geomerr[i * 4 + 3] = 1;
            if (cls[i] == sol::Background) {
                if (gTrue[i] != ~0u) {
                    ++backgroundWrong;
                    geomerr[i * 4 + 2] = 1;
                }
                continue;
            }
            if (cls[i] != sol::Trusted && cls[i] != sol::Edge) continue;
            ++trusted;
            const uint32_t g = vs.sites[ownerOf[i]].geom;
            if (gTrue[i] != g) {
                ++meshWrong;
                geomerr[i * 4 + 2] = 1;
                continue;
            }
            const double e = std::fabs(double(wvis[i]) - wTrue[i]) / std::max(1e-30, double(wTrue[i]));
            rel.push_back(e);
            over1 += e > op.surface.tol;
            over10 += e > 10 * op.surface.tol;
            geomerr[i * 4] = float(std::min(1.0, e / op.surface.tol));
            geomerr[i * 4 + 1] = float(std::min(1.0, e / op.surface.tol)) * 0.3f;
        }
        std::sort(rel.begin(), rel.end());
        auto at = [&](double q) { return rel.empty() ? 0.0 : rel[std::min(rel.size() - 1, size_t(q * rel.size()))]; };
        double meanRel = 0;
        for (double e : rel) meanRel += e / double(rel.size());
        Json::Value ge;
        ge["converged_pixels"] = Json::UInt64(trusted);
        ge["relative_error_mean"] = meanRel;
        ge["relative_error_p99"] = at(0.99);
        ge["relative_error_max"] = rel.empty() ? 0.0 : rel.back();
        ge["over_tolerance"] = Json::UInt64(over1);
        ge["over_10x_tolerance"] = Json::UInt64(over10);
        ge["other_mesh_seen"] = Json::UInt64(meshWrong);
        ge["background_hits_geometry"] = Json::UInt64(backgroundWrong);
        report["geometric_error"] = ge;

        // Films.
        std::vector<float> classes(N * 4, 1.0f), cells(N * 4, 1.0f), depth(N * 4, 1.0f), leaves(N * 4, 1.0f), nmap(N * 4, 1.0f), truth(N * 4, 1.0f);
        float wTop = 0;
        for (size_t i = 0; i < N; ++i) wTop = std::max({wTop, wvis[i], wTrue[i]});
        for (size_t i = 0; i < N; ++i) {
            const unsigned x = unsigned(i % W), y = unsigned(i / W);
            for (int k = 0; k < 3; ++k) classes[i * 4 + k] = palette[cls[i]][k];
            const uint32_t oid = mix(uint32_t(ownerOf[i]) + 1);
            cells[i * 4] = float(oid & 255) / 255.f, cells[i * 4 + 1] = float((oid >> 8) & 255) / 255.f, cells[i * 4 + 2] = float((oid >> 16) & 255) / 255.f;
            for (int k = 0; k < 3; ++k) depth[i * 4 + k] = wTop > 0 ? wvis[i] / wTop : 0, truth[i * 4 + k] = wTop > 0 ? wTrue[i] / wTop : 0;
            // A leaf's colour by its level, darker on its border.
            const auto& q = vs.quads[leafOf[i]];
            const bool border = int(x) == q.x0 || int(y) == q.y0;
            for (int k = 0; k < 3; ++k) leaves[i * 4 + k] = levels[level[i]][k] * (border ? 0.35f : 1.0f);
            for (int k = 0; k < 3; ++k) nmap[i * 4 + k] = float(nCount[i]) / float(op.nHi);
        }
        writeFloats(out / "phase1.rgba", r1.rgba);
        writeFloats(out / "recon.rgba", recon);
        writeFloats(out / "phase2.rgba", r2.rgba);
        writeFloats(out / "direct2.rgba", direct2);
        writeFloats(out / "final.rgba", final);
        writeFloats(out / "classes.rgba", classes);
        writeFloats(out / "cells.rgba", cells);
        writeFloats(out / "depth.rgba", depth);
        writeFloats(out / "depth-true.rgba", truth);
        writeFloats(out / "leaves.rgba", leaves);
        writeFloats(out / "geomerr.rgba", geomerr);
        writeFloats(out / "samples2.rgba", nmap);
        {
            std::ofstream o(out / "surface.sol", std::ios::binary);
            o.write(reinterpret_cast<const char*>(piece.data()), std::streamsize(piece.size()));
        }

        uint64_t hit = 0, truncated = 0, trisSum = 0, ringsMax = 0, leafStates[sol::States] = {}, leavesTotal = 0;
        for (const auto& s : vs.sites) {
            hit += s.hit;
            truncated += s.patch.truncated;
            trisSum += s.patch.prims.size();
            ringsMax = std::max<uint64_t>(ringsMax, s.patch.rings);
        }
        // Why quads split (a split quad keeps the test it failed), and how much of the frame each pass left converged.
        uint64_t refinedBy[sol::States] = {};
        std::vector<double> convergedArea(vs.passes.size(), 0.0);
        for (const auto& q : vs.quads) {
            if (q.child >= 0) {
                ++refinedBy[q.state];
                continue;
            }
            ++leafStates[q.state], ++leavesTotal;
            if (q.state != sol::Trusted && q.state != sol::Background) continue;
            for (size_t p = size_t(q.level); p < convergedArea.size(); ++p) convergedArea[p] += double(q.x1 - q.x0) * double(q.y1 - q.y0);
        }
        for (int s = 0; s < sol::States; ++s)
            if (refinedBy[s]) report["refined_by"][sol::stateName(s)] = Json::UInt64(refinedBy[s]);
        for (double a : convergedArea) report["converged_area_by_pass"].append(a / (double(W - 1) * double(H - 1)));
        uint64_t welded = 0, borders = 0, nonManifold = 0, topoTris = 0, topologies = 0, meshBytes = 0;
        for (const auto& mi : index.meshes) {
            if (mi.data) meshBytes += mi.data->positions.size() * 12 + mi.data->triangles.size() * 12;
            if (!mi.topology) continue;
            ++topologies;
            welded += mi.topology->welded, borders += mi.topology->borders, nonManifold += mi.topology->nonManifold, topoTris += mi.topology->nbr.size() / 3;
        }
        report["width"] = W;
        report["height"] = H;
        report["scene_spp"] = spp;
        Json::Value o;
        o["s0"] = op.surface.s0, o["min_stride"] = op.surface.minStride, o["tol"] = op.surface.tol, o["margin"] = op.margin;
        o["probe_spp"] = op.probeSpp, o["n_lo"] = op.nLo, o["n_hi"] = op.nHi, o["n_bg"] = op.nBg;
        o["m0"] = op.m0, o["tau_r"] = op.tauR, o["rings"] = op.surface.rings, o["tris"] = op.surface.tris;
        o["mode"] = op.mode, o["p1mode"] = op.p1mode, o["threads"] = op.threads;
        o["cache"] = op.cache, o["cache_p"] = op.cacheP, o["cache_tol"] = op.cacheTol, o["qmc_depth"] = op.qmcDepth, o["xpu2_qmc"] = op.xpu2Qmc;
        report["options"] = o;
        report["probes"] = Json::UInt64(vs.sites.size());
        report["probes_hit"] = Json::UInt64(hit);
        report["patch_triangles_mean"] = hit ? double(trisSum) / double(hit) : 0.0;
        report["patch_rings_max"] = Json::UInt64(ringsMax);
        report["patches_truncated"] = Json::UInt64(truncated);
        report["scan_triangles_visited"] = Json::UInt64(vs.visited);
        report["quads"] = Json::UInt64(vs.quads.size());
        report["leaves"] = Json::UInt64(leavesTotal);
        for (int s = 0; s < sol::States; ++s) report["leaf_states"][sol::stateName(s)] = Json::UInt64(leafStates[s]);
        report["topology"]["meshes"] = Json::UInt64(topologies);
        report["topology"]["triangles"] = Json::UInt64(topoTris);
        report["topology"]["welded_vertices"] = Json::UInt64(welded);
        report["topology"]["border_edges"] = Json::UInt64(borders);
        report["topology"]["non_manifold_edges"] = Json::UInt64(nonManifold);
        report["piece_bytes"] = Json::UInt64(piece.size());
        report["frame_cache_bytes"] = Json::UInt64(N * 16);
        report["mesh_bytes"] = Json::UInt64(meshBytes);
        for (int c = 0; c < sol::States; ++c) report["classes"][sol::stateName(c)] = double(classCount[c]) / double(N);
        report["phase2_samples_per_pixel"] = samples2 / double(N);
        report["phase1_probe_samples_per_pixel"] = double(vs.sites.size()) * op.probeSpp / double(N);
        report["timing"] = runs[rep];
        report["phase1_gpu_samples"] = Json::UInt64(r1.gpuSamples);
        report["phase1_cpu_samples"] = Json::UInt64(r1.cpuSamples);
        report["phase2_gpu_samples"] = Json::UInt64(r2.gpuSamples);
        report["phase2_cpu_samples"] = Json::UInt64(r2.cpuSamples);
        }  // runs
        report["runs"] = runs;

        // XPU2 itself, in this process, timed as the phases are (the lane's configuration, the renderer, the frame):
        // the scene with n samples a pixel, for each n of xpu2_spp, warmed up once and then repeats times.
        for (unsigned n : op.xpu2Spp) {
            cpu::need(n >= 1 && n <= 16384, "xpu2_spp");
            auto px = std::make_shared<cpu::Plan>(*plan);
            px->spp = n;
            px->qmcDepth = op.xpu2Qmc;
            Json::Value times(Json::arrayValue);
            async::RenderResult rx;
            for (unsigned rep = 0; rep <= op.repeats; ++rep) {
                async::RenderOptions ox;
                ox.threads = op.threads;
                ox.mode = op.mode;
                const auto t = Clock::now();
                if (gpu) gpu->updateCamera(px);
                async::Renderer renderer(px, cpuScene, gpu.get());
                rx = renderer.render(ox);
                cpu::need(!rx.failed, rx.error.empty() ? "XPU2 frame failed" : rx.error);
                Json::Value row;
                row["seconds"] = since(t);
                row["sampling_seconds"] = rx.seconds;
                row["warm_up"] = rep == 0;
                times.append(row);
            }
            writeFloats(out / ("xpu2-" + std::to_string(n) + ".rgba"), rx.rgba);
            report["xpu2"][std::to_string(n)] = times;
        }
        report["status"] = "passed";
        Json::StreamWriterBuilder bld;
        bld["indentation"] = "";
        std::cout << Json::writeString(bld, report) << std::endl;
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << std::endl;
        return 1;
    }
}
