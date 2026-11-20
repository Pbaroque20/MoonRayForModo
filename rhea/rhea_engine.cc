// Rhea: a probe tracer over XPU2's asynchronous renderer (rhea/DESIGN.md).
//
// rhea_engine scene runtime ptx assets output [key=value ...]
//
// Geometry. Rhea's indexer (virtual_surface.h) reconstructs the frame's visible surface from probes in geometric passes:
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
#include <numeric>
#include <thread>

using namespace xpu2::interactive;
namespace rdl = scene_rdl2::rdl2;
using Clock = std::chrono::steady_clock;

static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

namespace {

struct Options {
    // nLo, nHi 0: by the probes' light (4 and 32 with direct-light probes, 2 and 16 with whole-light ones).
    unsigned threads = 12, probeSpp = 64, nLo = 0, nHi = 0, nBg = 1;
    int mode = 1, p1mode = 1;  // the GPU shades, the CPU does the geometry (the CPU lane in a gathered frame holds its end up)
    double m0 = 128, tauR = 0.25, margin = -1;  // margin -1: from the pixel filter
    rhea::SurfaceOptions surface;
    std::string override_;
    unsigned repeats = 3;            // timed runs after one warm-up
    std::vector<unsigned> xpu2Spp;  // XPU2 frames to time in the same process (samples a pixel)
    // Phase 2's frame cache (mixed::Config::frameCache): on, the chance a bounce that reaches it goes on, the depth
    // tolerance; OpenQMC past the first hit (qmc_depth: vertices of nonMirrorDepth below it), and in XPU2's frames too.
    bool gather = true;  // probe frames over gather tiles (Plan::gather; needs a GPU program with them)
    bool oneFrame = true;  // probes and phase 2 in one frame (a depth limit per pixel, Plan::fullSamples)
    // Probes carry the whole light (full paths), not the direct light alone: phase 1 reconstructs the beauty and phase 2
    // corrects it, final = B + k (R1 - B). One frame only.
    int probeFull = -1;  // -1: when the scene has diffuse bounces (max_diffuse_depth > 0), whose light is smooth
    int gather2 = -1;  // phase 2 over gather tiles, its pixels sorted by their samples (-1: in one frame only)
    // XPU2's grid for Rhea's frame: the progressive order (ranges handed out no further than the least-sampled cell's)
    // and the sample indices a chunk holds.
    bool progressive = true;
    unsigned chunkSamples = 4;
    bool curvature = true;   // the reconstruction's second-order term (VirtualSurface::curvature)
    int curvSpan = 4;       // its second differences across neighbours this many strides away
    bool cache = false;  // off by default: it needs the engine's own GPU program (build_rhea.py --gpu)
    double cacheP = 0.25, cacheTol = 0.02;
    unsigned qmcDepth = 0, xpu2Qmc = 0;
    // A sequence of frames along a camera path (DESIGN.md 11): frames, the camera's yaw swing in degrees (frame k at
    // swing sin(2 pi k / frames)), and XPU2's samples a pixel on the same path. Run in sequence, then pipelined (the CPU
    // prepares the next frame's geometry and finishes the last while the GPU renders this one).
    unsigned frames = 0, seqXpu2 = 36, seqThreads = 4;
    // Jittered frames (DESIGN.md 13): each frame's probe lattice offset by the R2 sequence within a stride, and its
    // samples drawn afresh (the seed); accumulate: the still camera's running average written at 1, 2, 4, ... frames.
    bool jitter = false, accumulate = false;  // jitter: measured, off (RESULTS.md 11: costs 5-8% for a sliver of bias)
    // Accumulated frames: phase 1 counts as m K^accumPower samples over K frames against phase 2's sum of samples, so its
    // weight (and its bias) fades as phase 2's samples pile up (power < 1); 1 keeps a frame's weight, as averaging frames.
    double accumPower = 0.5;
    unsigned seed = 0;
    unsigned floorSpp = 9;
    bool demod = true;  // demodulated light (DESIGN.md 16): needs the albedo output (run_rhea.py adds it); one frame  // the floor's frame: XPU2's samples a pixel, every pixel (DESIGN.md 15)  // added to the scene's seed: every frame's samples drawn afresh (a reference independent of a run)  // seqThreads: the pipelined CPU work's threads, below normal
    double orbit = 0;
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

// The states' colours in classes.png (rhea::State order).
const float palette[rhea::States][3] = {{0.1f, 0.1f, 0.1f}, {0.2f, 0.8f, 0.3f}, {0.2f, 0.5f, 1.0f}, {0.0f, 0.8f, 0.8f}, {0.9f, 0.2f, 0.2f},
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
            else if (k == "coverage") op.surface.coverage = v != "0";
            else if (k == "light_tol") op.surface.lightTol = std::stod(v);
            else if (k == "light_passes") op.surface.lightPasses = unsigned(std::stoul(v));
            else if (k == "gather") op.gather = v != "0";
            else if (k == "gather2") op.gather2 = std::stoi(v);
            else if (k == "progressive") op.progressive = v != "0";
            else if (k == "probe_full") op.probeFull = std::stoi(v);
            else if (k == "chunk") op.chunkSamples = unsigned(std::stoul(v));
            else if (k == "one_frame") op.oneFrame = v != "0";
            else if (k == "frames") op.frames = unsigned(std::stoul(v));
            else if (k == "orbit") op.orbit = std::stod(v);
            else if (k == "seq_xpu2") op.seqXpu2 = unsigned(std::stoul(v));
            else if (k == "seq_threads") op.seqThreads = unsigned(std::stoul(v));
            else if (k == "jitter") op.jitter = v != "0";
            else if (k == "accumulate") op.accumulate = v != "0";
            else if (k == "accum_power") op.accumPower = std::stod(v);
            else if (k == "seed") op.seed = unsigned(std::stoul(v));
            else if (k == "floor_area") op.surface.floorArea = std::stod(v);
            else if (k == "floor_spp") op.floorSpp = unsigned(std::stoul(v));
            else if (k == "demod") op.demod = v != "0";
            else if (k == "curvature") op.curvature = v != "0";
            else if (k == "curv_span") op.curvSpan = std::stoi(v);
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
        const_cast<cpu::Plan&>(*plan).seed += op.seed;  // the engine's own plan, before the lanes take it
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
        // Probes carry the whole light where the scene bounces diffusely (the smooth light probes reconstruct best),
        // else its direct light alone; phase 2's samples follow.
        if (op.probeFull < 0) op.probeFull = plan->maxDiffuseDepth > 0 ? 1 : 0;
        if (!op.oneFrame || op.surface.lightPasses || op.cache) op.probeFull = 0;  // whole-light probes ride in phase 2's frame
        if (!op.nLo) op.nLo = op.probeFull ? 2 : 4;
        if (!op.nHi) op.nHi = op.probeFull ? 16 : 32;
        cpu::need(op.probeSpp >= 1 && op.probeSpp <= spp && op.nHi <= spp && op.nLo <= spp && op.nBg >= 1 && op.nLo >= 1,
                  "Sample counts must lie in [1, the scene's samples a pixel]");
        if (op.margin < 0) op.margin = std::max(1.0, 0.5 * plan->filterWidth + 0.5);
        op.surface.margin = op.margin;
        rhea::Frame frame;
        cpu::need(frame.init(plan->camera), "Camera frame");
        // The frame cache's lift on the device takes the camera transform as affine (three columns and a translation).
        cpu::need(std::fabs(frame.toCamera[0][3]) < 1e-9 && std::fabs(frame.toCamera[1][3]) < 1e-9 && std::fabs(frame.toCamera[2][3]) < 1e-9 &&
                      std::fabs(frame.toCamera[3][3] - 1) < 1e-9,
                  "An affine camera transform");
        const size_t N = size_t(W) * H;

        // Rhea's indexer: the geometry index, kept across frames (clusters now, topologies when a probe needs them).
        rhea::GeometryIndex index;
        stamp = Clock::now();
        index.index(*plan, op.threads);
        report["index_seconds"] = since(stamp);
        report["index_clusters"] = Json::UInt64(index.clusterCount);
        Json::Value runs(Json::arrayValue);
        rhea::VirtualSurface vs;

        // Run 0 warms up (texture tiles reach the card, topologies are made); runs 1..repeats are timed.
        for (unsigned rep = 0; rep <= op.repeats; ++rep) {
        const bool last = rep == op.repeats;

        // The geometric passes.
        stamp = Clock::now();
        vs.build(*plan, cpuScene, frame, index, op.surface);
        const double geometrySeconds = since(stamp);

        // One frame (DESIGN.md 10) unless light passes or the frame cache need the probes' light before phase 2.
        const bool oneFrame = op.oneFrame && !op.surface.lightPasses && !op.cache;

        // Phase 1 in frames of its own: probe frames, the probes' direct light (max_depth 0, probe_spp samples a probe), each frame lighting
        // the probes that have no light yet; between them, light passes split the quads whose light bends too much
        // (VirtualSurface::refineLight), whose new probes the next frame lights. A probe frame's pixels are gathered
        // into tiles (Plan::gather), spread over the grid's cells, so that its chunks hold probes and not empty pixels.
        const unsigned tilesX = (W + 7) / 8, tilesY = (H + 7) / 8, tilesAll = tilesX * tilesY;
        double phase1Seconds = 0, lightSeconds = 0, phase1Sampling = 0;
        unsigned probeFrames = 0;
        uint64_t p1Gpu = 0, p1Cpu = 0;
        std::vector<float> phase1(N * 4, 0.0f);
        for (unsigned pass = 0; !oneFrame && !vs.floored; ++pass) {
            const std::vector<int> which = vs.unlit();
            if (!which.empty()) {
                auto p1 = std::make_shared<cpu::Plan>(*plan);
                p1->maxDepth = 0;
                p1->pixelSamples.assign(N, 0u);
                p1->spp = op.probeSpp;
                if (op.gather) {
                    p1->gather.assign(size_t(tilesAll) * 64, ~0u);
                    const size_t used = (which.size() + 63) / 64;
                    for (size_t k = 0; k < used; ++k) {
                        const size_t tile = (k * tilesAll) / used;
                        for (size_t j = 0; j < 64 && k * 64 + j < which.size(); ++j) {
                            const auto& s = vs.sites[which[k * 64 + j]];
                            p1->gather[tile * 64 + j] = unsigned(size_t(s.py) * W + s.px);
                        }
                    }
                }
                for (int i : which) p1->pixelSamples[size_t(vs.sites[i].py) * W + vs.sites[i].px] = op.probeSpp;
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
                phase1Seconds += since(stamp);
                phase1Sampling += r1.seconds;
                p1Gpu += r1.gpuSamples, p1Cpu += r1.cpuSamples;
                ++probeFrames;
                vs.takeRadiance(r1.rgba, which);
                for (int i : which) {
                    const size_t px = size_t(vs.sites[i].py) * W + vs.sites[i].px;
                    for (int c = 0; c < 4; ++c) phase1[px * 4 + c] = r1.rgba[px * 4 + c];
                }
            }
            if (pass >= op.surface.lightPasses) break;
            stamp = Clock::now();
            const size_t splits = vs.refineLight(*plan, cpuScene, frame, index, op.surface);
            lightSeconds += since(stamp);
            if (!splits) break;
        }

        // The piece: the virtual surface with the probes' light, packed; each pixel evaluated from it alone. In one frame
        // the first pass has the geometry alone (the states, and so phase 2's samples); the probes' light comes with the
        // frame, and the region pass runs again.
        stamp = Clock::now();
        std::vector<uint8_t> piece;
        std::vector<float> recon(N * 4, 0.0f), wvis(N, 0.0f);
        std::vector<uint8_t> cls(N, rhea::Truncated), level(N, 0);
        std::vector<int> ownerOf(N, -1), leafOf(N, -1);
        std::vector<float> albedo;  // the pixels' colours (the frame's albedo output), once the frame has them
        auto regionPass = [&] {
            piece = rhea::pack(vs, float(op.tauR), op.curvature, op.curvSpan);
            const rhea::SurfaceView view(piece);
            rhea::parallel(op.threads, H, [&](size_t y) {
                for (unsigned x = 0; x < W; ++x) {
                    const size_t i = y * W + x;
                    const rhea::PixelSurface p = rhea::evaluate(view, int(x), int(y), albedo.empty() ? nullptr : &albedo[i * 3]);
                    for (int c = 0; c < 3; ++c) recon[i * 4 + c] = p.rgb[c];
                    recon[i * 4 + 3] = 1;
                    wvis[i] = p.w;
                    cls[i] = p.state;
                    level[i] = uint8_t(std::min(p.level, 5));
                    ownerOf[i] = p.owner;
                    leafOf[i] = p.leaf;
                }
            });
        };
        regionPass();
        // Each state's phase 2 samples and phase 1's weight.
        std::vector<float> mWeight(N, 0.0f);
        std::vector<unsigned> nCount(N, op.nHi);
        for (size_t i = 0; i < N; ++i) {
            switch (cls[i]) {
                case rhea::Background: nCount[i] = op.nBg, mWeight[i] = float(op.m0); break;
                case rhea::Trusted: nCount[i] = op.nLo, mWeight[i] = float(op.m0); break;
                default: nCount[i] = op.nHi, mWeight[i] = 0; break;
            }
        }
        if (vs.floored) {
            // The floor: the frame as XPU2 renders it, floor_spp samples every pixel, no reconstruction.
            nCount.assign(N, op.floorSpp);
            mWeight.assign(N, 0.0f);
        }
        double regionSeconds = since(stamp);

        // Phase 2: full paths, n(x) a pixel, with the direct light's two expressions. In one frame each probe's pixel
        // also takes probe_spp samples past its n(x) full paths that stop at the first hit (Plan::fullSamples, a depth
        // limit per pixel): its direct light output, over all its samples, is the probe's light.
        auto p2 = std::make_shared<cpu::Plan>(*plan);
        std::vector<unsigned> total = nCount;
        if (oneFrame && !vs.floored) {
            // Probe samples only where a converged leaf reads them.
            const std::vector<uint8_t> used = vs.usedSites();
            for (size_t i = 0; i < vs.sites.size(); ++i)
                if (used[i]) total[size_t(vs.sites[i].py) * W + vs.sites[i].px] += op.probeSpp;
            if (!op.probeFull) p2->fullSamples = nCount;  // probe samples stop at the first hit
        }
        p2->pixelSamples = total;
        p2->spp = *std::max_element(total.begin(), total.end());
        if (vs.floored) p2->pixelSamples.clear();  // the floor: XPU2's own frame, floor_spp every pixel
        // Phase 2's pixels gathered by their samples (Plan::gather): sorted by count, most first, 64 to a tile in image
        // order, so a tile's pixels take the same samples and none waits on a deeper neighbour. The tiles are spread over
        // the grid's cells (a stride prime to their number), so the deep ones are not all in the first cells.
        if (!vs.floored && (op.gather2 > 0 || (op.gather2 < 0 && oneFrame))) {
            std::vector<unsigned> order(N);
            for (size_t i = 0; i < N; ++i) order[i] = unsigned(i);
            std::stable_sort(order.begin(), order.end(), [&](unsigned a, unsigned b) { return total[a] > total[b]; });
            p2->gather.assign(size_t(tilesAll) * 64, ~0u);
            size_t step = 397;
            while (std::gcd(step, size_t(tilesAll)) != 1) ++step;
            for (size_t k = 0; k * 64 < N; ++k) {
                const size_t tile = (k * step) % tilesAll;
                for (size_t j = 0; j < 64 && k * 64 + j < N; ++j) p2->gather[tile * 64 + j] = order[k * 64 + j];
            }
        }
        // The frame cache: phase 1's radiance and the visible inverse depth where the virtual surface converged, for
        // phase 2's bounces (async_integrator.h frameCacheAt), and OpenQMC past the first hit.
        if (op.cache) {
            auto cache = std::make_shared<std::vector<float>>(N * 4, 0.0f);
            for (size_t i = 0; i < N; ++i) {
                if (cls[i] != rhea::Trusted) continue;
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
        const int offEmit = aovOffset(*p2, "/rhea_emission"), offDirect = aovOffset(*p2, "/rhea_direct");
        cpu::need(offEmit >= 0 && offDirect >= 0, "The scene needs the outputs /rhea_emission and /rhea_direct (run_rhea.py adds them)");
        async::RenderOptions o2;
        o2.threads = op.threads;
        o2.mode = op.mode;
        o2.grid.progressive = op.progressive;
        o2.grid.samplesPerChunk = std::max(1u, op.chunkSamples);
        stamp = Clock::now();
        if (gpu) gpu->updateCamera(p2);
        async::RenderResult r2;
        {
            async::Renderer renderer(p2, cpuScene, gpu.get());
            r2 = renderer.render(o2);
        }
        cpu::need(!r2.failed, r2.error.empty() ? "Phase 2 failed" : r2.error);
        const double phase2Seconds = since(stamp);
        const size_t stride = r2.aov.size() / N;
        cpu::need(stride * N == r2.aov.size(), "AOV layout");
        // The direct light over each pixel's samples (its full paths' first hits and its probe samples alike).
        std::vector<float> direct2(N * 4, 0.0f);
        for (size_t i = 0; i < N; ++i) {
            const float* av = &r2.aov[i * stride];
            for (int c = 0; c < 3; ++c) direct2[i * 4 + c] = av[offEmit + c] + av[offDirect + c];
            direct2[i * 4 + 3] = 1;
        }
        if (oneFrame && !vs.floored) {
            // The probes' light, then the region pass again with it (the radiance-edge rule can now judge, and lowers
            // phase 1's weight there; phase 2's samples were set by the geometry).
            stamp = Clock::now();
            std::vector<int> all(vs.sites.size());
            for (size_t i = 0; i < all.size(); ++i) all[i] = int(i);
            const int offAlbedo = aovOffset(*p2, "/rhea_albedo");
            vs.demodulate = op.demod && offAlbedo >= 0;
            if (vs.demodulate) {
                albedo.assign(N * 3, 0.0f);
                for (size_t i = 0; i < N; ++i)
                    for (int c = 0; c < 3; ++c) albedo[i * 3 + c] = r2.aov[i * stride + offAlbedo + c];
            }
            vs.takeRadiance(op.probeFull ? r2.rgba : direct2, all, vs.demodulate ? &albedo : nullptr);
            regionPass();
            for (size_t i = 0; i < N; ++i)
                if (cls[i] == rhea::Edge) mWeight[i] = 0;
            regionSeconds += since(stamp);
        }

        // The combination. N(x) samples in all, n(x) of them full paths: the beauty's mean is (n (D + I) + (N - n) D) / N
        // over the samples' direct light D and indirect light I, so I = N (beauty - D) / n from the full paths alone,
        // and the direct light, D from all N, takes phase 1's reconstruction as before:
        //   final = I + (1 - k) D + k R1,   k = m / (m + N).
        // Without probe samples (N = n) it is B + k (R1 - D), the two-frame combination.
        stamp = Clock::now();
        std::vector<float> final(N * 4, 0.0f);
        double samples2 = 0, probeSamples = 0;
        uint64_t classCount[rhea::States] = {};
        for (size_t i = 0; i < N; ++i) {
            ++classCount[cls[i]];
            const float n = float(nCount[i]), Nt = float(total[i]), m = mWeight[i], k = m / (m + Nt);
            samples2 += n, probeSamples += Nt - n;
            for (int c = 0; c < 3; ++c) {
                const float d = direct2[i * 4 + c], b = r2.rgba[i * 4 + c];
                // Probes with the whole light: R1 is the beauty's reconstruction, B over all N samples its correction.
                final[i * 4 + c] = oneFrame && op.probeFull ? b + k * (recon[i * 4 + c] - b)
                                                            : Nt / n * (b - d) + (1 - k) * d + k * recon[i * 4 + c];
            }
            final[i * 4 + 3] = r2.rgba[i * 4 + 3];
        }
        const double combineSeconds = since(stamp);
        if (oneFrame) {
            ++probeFrames;  // the probes rode in phase 2's frame
            for (const auto& s : vs.sites) {
                const size_t px = size_t(s.py) * W + s.px;
                for (int c = 0; c < 3; ++c) phase1[px * 4 + c] = direct2[px * 4 + c];
                phase1[px * 4 + 3] = 1;
            }
        }

        {
            Json::Value t;
            t["geometry_seconds"] = geometrySeconds;
            t["phase1_seconds"] = phase1Seconds;
            t["phase1_sampling_seconds"] = phase1Sampling;
            t["light_seconds"] = lightSeconds;
            t["probe_frames"] = probeFrames;
            t["one_frame"] = oneFrame;
            t["floored"] = vs.floored;
            t["first_pass_area"] = vs.firstPassArea;
            t["region_seconds"] = regionSeconds;
            t["phase2_seconds"] = phase2Seconds;
            t["phase2_sampling_seconds"] = r2.seconds;
            t["combine_seconds"] = combineSeconds;
            t["total_seconds"] = geometrySeconds + phase1Seconds + lightSeconds + regionSeconds + phase2Seconds + combineSeconds;
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
                for (int s = 0; s < rhea::States; ++s)
                    if (p.states[s]) j["leaves"][rhea::stateName(s)] = Json::UInt64(p.states[s]);
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
        rhea::parallel(op.threads, H, [&](size_t y) {
            async::CpuBackend backend{cpuScene};
            for (unsigned x = 0; x < W; ++x) {
                surface::Ray ray;
                if (!surface::cameraRay(plan->camera, x + 0.5f, y + 0.5f, ray)) continue;
                ray.mask = 1u;
                const resume::Hit h = backend.trace(ray);
                if (h.geom == ~0u) continue;
                const surface::V3 p{ray.origin.x + h.t * ray.direction.x, ray.origin.y + h.t * ray.direction.y, ray.origin.z + h.t * ray.direction.z};
                const rhea::D3 c = frame.camera(p);
                if (c.z < 0) wTrue[y * W + x] = float(1.0 / -c.z);
                gTrue[y * W + x] = h.geom;
            }
        });
        std::vector<double> rel;
        uint64_t over1 = 0, over10 = 0, meshWrong = 0, backgroundWrong = 0, trusted = 0;
        std::vector<float> geomerr(N * 4, 0.0f);
        for (size_t i = 0; i < N; ++i) {
            geomerr[i * 4 + 3] = 1;
            if (cls[i] == rhea::Background) {
                if (gTrue[i] != ~0u) {
                    ++backgroundWrong;
                    geomerr[i * 4 + 2] = 1;
                }
                continue;
            }
            if (cls[i] != rhea::Trusted && cls[i] != rhea::Edge) continue;
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
        writeFloats(out / "phase1.rgba", phase1);
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
            std::ofstream o(out / "surface.rhea", std::ios::binary);
            o.write(reinterpret_cast<const char*>(piece.data()), std::streamsize(piece.size()));
        }

        uint64_t hit = 0, truncated = 0, trisSum = 0, ringsMax = 0, leafStates[rhea::States] = {}, leavesTotal = 0;
        for (const auto& s : vs.sites) {
            hit += s.hit;
            truncated += s.patch.truncated;
            trisSum += s.patch.prims.size();
            ringsMax = std::max<uint64_t>(ringsMax, s.patch.rings);
        }
        // Why quads split (a split quad keeps the test it failed), and how much of the frame each pass left converged.
        uint64_t refinedBy[rhea::States] = {};
        int deepest = 0;
        for (const auto& q : vs.quads) deepest = std::max(deepest, q.level);
        std::vector<double> convergedArea(size_t(deepest) + 1, 0.0);
        for (const auto& q : vs.quads) {
            if (q.child >= 0) {
                ++refinedBy[q.state];
                continue;
            }
            ++leafStates[q.state], ++leavesTotal;
            if (q.state != rhea::Trusted && q.state != rhea::Background) continue;
            for (size_t p = size_t(q.level); p < convergedArea.size(); ++p) convergedArea[p] += double(q.x1 - q.x0) * double(q.y1 - q.y0);
        }
        for (int s = 0; s < rhea::States; ++s)
            if (refinedBy[s]) report["refined_by"][rhea::stateName(s)] = Json::UInt64(refinedBy[s]);
        for (double a : convergedArea) report["converged_area_by_level"].append(a / (double(W - 1) * double(H - 1)));
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
        o["m0"] = op.m0, o["tau_r"] = op.tauR, o["rings"] = op.surface.rings, o["tris"] = op.surface.tris, o["coverage"] = op.surface.coverage;
        o["light_tol"] = op.surface.lightTol, o["light_passes"] = op.surface.lightPasses, o["gather"] = op.gather, o["gather2"] = op.gather2, o["progressive"] = op.progressive, o["probe_full"] = op.probeFull, o["chunk"] = op.chunkSamples, o["one_frame"] = op.oneFrame, o["frames"] = op.frames, o["orbit"] = op.orbit, o["jitter"] = op.jitter, o["accumulate"] = op.accumulate, o["accum_power"] = op.accumPower, o["seed"] = op.seed, o["floor_area"] = op.surface.floorArea, o["floor_spp"] = op.floorSpp, o["demod"] = op.demod, o["curvature"] = op.curvature, o["curv_span"] = op.curvSpan;
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
        for (const auto& l : vs.lights) {
            Json::Value j;
            j["tested"] = Json::UInt64(l.tested), j["split"] = Json::UInt64(l.split), j["largest_error"] = l.largest;
            j["test_seconds"] = l.testSeconds, j["pass_seconds"] = l.passSeconds;
            report["light_passes"].append(j);
        }
        report["leaves"] = Json::UInt64(leavesTotal);
        for (int s = 0; s < rhea::States; ++s) report["leaf_states"][rhea::stateName(s)] = Json::UInt64(leafStates[s]);
        report["topology"]["meshes"] = Json::UInt64(topologies);
        report["topology"]["triangles"] = Json::UInt64(topoTris);
        report["topology"]["welded_vertices"] = Json::UInt64(welded);
        report["topology"]["border_edges"] = Json::UInt64(borders);
        report["topology"]["non_manifold_edges"] = Json::UInt64(nonManifold);
        report["piece_bytes"] = Json::UInt64(piece.size());
        report["frame_cache_bytes"] = Json::UInt64(N * 16);
        report["mesh_bytes"] = Json::UInt64(meshBytes);
        for (int c = 0; c < rhea::States; ++c) report["classes"][rhea::stateName(c)] = double(classCount[c]) / double(N);
        report["phase2_samples_per_pixel"] = samples2 / double(N);
        report["probe_samples_in_phase2_per_pixel"] = probeSamples / double(N);
        report["phase1_probe_samples_per_pixel"] = double(vs.sites.size()) * op.probeSpp / double(N);
        report["timing"] = runs[rep];
        report["phase1_gpu_samples"] = Json::UInt64(p1Gpu);
        report["phase1_cpu_samples"] = Json::UInt64(p1Cpu);
        report["phase2_gpu_samples"] = Json::UInt64(r2.gpuSamples);
        report["phase2_cpu_samples"] = Json::UInt64(r2.cpuSamples);
        // The frame's GPU launches: queued and collected (seconds from the frame's start), time on the device, chunks.
        report["phase2_launches"] = Json::UInt64(r2.launches);
        for (const auto& l : r2.launchTrace) {
            Json::Value j(Json::arrayValue);
            j.append(l.queued), j.append(l.collected), j.append(l.deviceSeconds), j.append(Json::UInt64(l.chunks));
            report["phase2_launch_trace"].append(j);
        }
        }  // runs
        report["runs"] = runs;

        // A sequence of frames along a camera path, one frame each (probes in phase 2's frame), first one after the other,
        // then pipelined: while the GPU renders frame k, a CPU thread finishes frame k - 1 (the probes' light, the region
        // pass, the combination) and prepares frame k + 1 (its geometric passes, states, samples and plan). Three slots
        // turn round. Frame 0 is the run's own camera; its final picture is written to check the pipeline changes nothing.
        if (op.frames) {
            cpu::need(!op.surface.lightPasses && !op.cache, "A sequence renders one frame each: no light passes, no frame cache");
            const unsigned F = op.frames, tilesAll = ((W + 7) / 8) * ((H + 7) / 8);
            const int offE = aovOffset(*plan, "/rhea_emission"), offD = aovOffset(*plan, "/rhea_direct");
            cpu::need(offE >= 0 && offD >= 0, "The scene needs the outputs /rhea_emission and /rhea_direct");
            auto cameraAt = [&](unsigned k) {
                surface::Camera c = plan->camera;
                const double pi = 3.14159265358979323846;
                const double a = op.orbit * pi / 180.0 * std::sin(2 * pi * double(k) / double(F));
                const double cs = std::cos(a), sn = std::sin(a);
                const double R[4][4] = {{cs, 0, -sn, 0}, {0, 1, 0, 0}, {sn, 0, cs, 0}, {0, 0, 0, 1}};  // yaw, camera space
                for (int i = 0; i < 4; ++i)
                    for (int j = 0; j < 4; ++j) {
                        double v = 0;
                        for (int q = 0; q < 4; ++q) v += R[i][q] * plan->camera.cameraToRender.m[q][j];
                        c.cameraToRender.m[i][j] = float(v);
                    }
                return c;
            };
            struct Slot {
                std::shared_ptr<cpu::Plan> plan;
                rhea::Frame frame;
                rhea::VirtualSurface vs;
                std::vector<unsigned> nCount, total;
                std::vector<float> mWeight, recon, direct, final, albedo;
                std::vector<uint8_t> cls;
                async::RenderResult r;
                double prepare = 0, render = 0, finish = 0;
            };
            unsigned threads = op.threads;  // the CPU work's threads: all of them in sequence, seq_threads when pipelined
            auto regionInto = [&](Slot& s) {
                const std::vector<uint8_t> bytes = rhea::pack(s.vs, float(op.tauR), op.curvature, op.curvSpan);
                const rhea::SurfaceView view(bytes);
                s.recon.assign(N * 4, 0.0f);
                s.cls.assign(N, rhea::Truncated);
                rhea::parallel(threads, H, [&](size_t y) {
                    for (unsigned x = 0; x < W; ++x) {
                        const size_t i = y * W + x;
                        const rhea::PixelSurface ps = rhea::evaluate(view, int(x), int(y), s.albedo.empty() ? nullptr : &s.albedo[i * 3]);
                        for (int c = 0; c < 3; ++c) s.recon[i * 4 + c] = ps.rgb[c];
                        s.cls[i] = ps.state;
                    }
                });
            };
            auto prepare = [&](Slot& s, unsigned k) {
                const auto t0 = Clock::now();
                s.plan = std::make_shared<cpu::Plan>(*plan);
                s.plan->camera = cameraAt(k);
                cpu::need(s.frame.init(s.plan->camera), "Camera frame");
                rhea::SurfaceOptions so = op.surface;
                so.threads = threads;
                // Frame k's lattice offset (R2: the plastic number's fractions) and seed; frame 0 keeps both.
                if (op.jitter) {
                    so.ox = int(std::floor(std::fmod(0.7548776662466927 * k, 1.0) * op.surface.s0));
                    so.oy = int(std::floor(std::fmod(0.5698402909980532 * k, 1.0) * op.surface.s0));
                }
                s.plan->seed = plan->seed + k * 7919u;
                s.vs.build(*s.plan, cpuScene, s.frame, index, so);
                s.albedo.clear();  // the geometry's pass: no colours yet
                regionInto(s);
                s.nCount.assign(N, op.nHi);
                s.mWeight.assign(N, 0.0f);
                for (size_t i = 0; i < N; ++i) {
                    if (s.cls[i] == rhea::Background) s.nCount[i] = op.nBg, s.mWeight[i] = float(op.m0);
                    else if (s.cls[i] == rhea::Trusted) s.nCount[i] = op.nLo, s.mWeight[i] = float(op.m0);
                }
                if (s.vs.floored) s.nCount.assign(N, op.floorSpp), s.mWeight.assign(N, 0.0f);  // the floor
                s.total = s.nCount;
                if (!s.vs.floored) {
                    const std::vector<uint8_t> used = s.vs.usedSites();
                    for (size_t i = 0; i < s.vs.sites.size(); ++i)
                        if (used[i]) s.total[size_t(s.vs.sites[i].py) * W + s.vs.sites[i].px] += op.probeSpp;
                }
                s.plan->pixelSamples = s.total;
                if (!op.probeFull && !s.vs.floored) s.plan->fullSamples = s.nCount;
                s.plan->spp = *std::max_element(s.total.begin(), s.total.end());
                s.plan->qmcDepth = op.qmcDepth;
                std::vector<unsigned> order(N);
                for (size_t i = 0; i < N; ++i) order[i] = unsigned(i);
                std::stable_sort(order.begin(), order.end(), [&](unsigned a, unsigned b) { return s.total[a] > s.total[b]; });
                if (s.vs.floored) {
                    s.plan->pixelSamples.clear();  // the floor: XPU2's own frame, its own tiles
                    s.prepare = since(t0);
                    return;
                }
                s.plan->gather.assign(size_t(tilesAll) * 64, ~0u);
                size_t step = 397;
                while (std::gcd(step, size_t(tilesAll)) != 1) ++step;
                for (size_t q = 0; q * 64 < N; ++q)
                    for (size_t j = 0; j < 64 && q * 64 + j < N; ++j) s.plan->gather[((q * step) % tilesAll) * 64 + j] = order[q * 64 + j];
                s.prepare = since(t0);
            };
            auto render = [&](Slot& s) {
                const auto t0 = Clock::now();
                if (gpu) gpu->updateCamera(s.plan);
                async::RenderOptions o;
                o.threads = op.threads;
                o.mode = op.mode;
                {
                    async::Renderer renderer(s.plan, cpuScene, gpu.get());
                    s.r = renderer.render(o);
                }
                cpu::need(!s.r.failed, s.r.error.empty() ? "Sequence frame failed" : s.r.error);
                s.render = since(t0);
            };
            auto finish = [&](Slot& s) {
                const auto t0 = Clock::now();
                const size_t stride = s.r.aov.size() / N;
                s.direct.assign(N * 4, 0.0f);
                for (size_t i = 0; i < N; ++i)
                    for (int c = 0; c < 3; ++c) s.direct[i * 4 + c] = s.r.aov[i * stride + offE + c] + s.r.aov[i * stride + offD + c];
                std::vector<int> all(s.vs.sites.size());
                for (size_t i = 0; i < all.size(); ++i) all[i] = int(i);
                if (!s.vs.floored) {
                    const int offA = aovOffset(*s.plan, "/rhea_albedo");
                    s.vs.demodulate = op.demod && offA >= 0;
                    s.albedo.clear();
                    if (s.vs.demodulate) {
                        s.albedo.assign(N * 3, 0.0f);
                        for (size_t i = 0; i < N; ++i)
                            for (int c = 0; c < 3; ++c) s.albedo[i * 3 + c] = s.r.aov[i * stride + offA + c];
                    }
                    s.vs.takeRadiance(op.probeFull ? s.r.rgba : s.direct, all, s.vs.demodulate ? &s.albedo : nullptr);
                    regionInto(s);
                }
                s.final.assign(N * 4, 0.0f);
                for (size_t i = 0; i < N; ++i) {
                    const float m = s.cls[i] == rhea::Edge ? 0.0f : s.mWeight[i];
                    s.mWeight[i] = m;
                    const float n = float(s.nCount[i]), Nt = float(s.total[i]), k = m / (m + Nt);
                    for (int c = 0; c < 3; ++c) {
                        const float d = s.direct[i * 4 + c];
                        const float b = s.r.rgba[i * 4 + c];
                        s.final[i * 4 + c] = op.probeFull ? b + k * (s.recon[i * 4 + c] - b) : Nt / n * (b - d) + (1 - k) * d + k * s.recon[i * 4 + c];
                    }
                    s.final[i * 4 + 3] = s.r.rgba[i * 4 + 3];
                }
                s.finish = since(t0);
            };
            auto median = [](std::vector<double> v) {
                std::sort(v.begin(), v.end());
                return v.empty() ? 0.0 : v[v.size() / 2];
            };
            Json::Value seq;
            seq["frames"] = F;
            seq["orbit_degrees"] = op.orbit;
            std::vector<Slot> slots(3);
            std::vector<float> first;
            cpu::need(!op.accumulate || op.orbit == 0, "Accumulating needs a still camera (orbit=0)");
            // The running average of frames, written at 1, 2, 4, ... frames (accumulate).
            auto accumulator = [&](const std::string& prefix) {
                return [&, prefix, sum = std::vector<double>(N * 4, 0.0), count = 0u](const std::vector<float>& f) mutable {
                    for (size_t i = 0; i < N * 4; ++i) sum[i] += f[i];
                    ++count;
                    if (count & (count - 1)) return;  // a power of two
                    std::vector<float> avg(N * 4);
                    for (size_t i = 0; i < N * 4; ++i) avg[i] = float(sum[i] / count);
                    writeFloats(out / (prefix + std::to_string(count) + ".rgba"), avg);
                };
            };
            auto naive = accumulator("naive-");
            auto accumulateXpu2 = accumulator("xpu2-accum-");
            // The convergent accumulation: each pixel's sums over the frames of its beauty and direct light (times their
            // samples), its samples (all, and full paths), phase 1's reconstruction and weight; at 1, 2, 4, ... frames
            // they combine as one frame does, with phase 1 counting as mean(m) K^accumPower samples.
            struct Sums {
                std::vector<double> nb, nd, n, nfull, r1, m;
                unsigned frames = 0;
            } acc;
            auto accumulate = [&](const Slot& s) {
                if (acc.nb.empty()) {
                    acc.nb.assign(N * 3, 0.0), acc.nd.assign(N * 3, 0.0), acc.r1.assign(N * 3, 0.0);
                    acc.n.assign(N, 0.0), acc.nfull.assign(N, 0.0), acc.m.assign(N, 0.0);
                }
                naive(s.final);
                for (size_t i = 0; i < N; ++i) {
                    const double Nt = s.total[i];
                    for (int c = 0; c < 3; ++c) {
                        acc.nb[i * 3 + c] += Nt * s.r.rgba[i * 4 + c];
                        acc.nd[i * 3 + c] += Nt * s.direct[i * 4 + c];
                        acc.r1[i * 3 + c] += s.recon[i * 4 + c];
                    }
                    acc.n[i] += Nt, acc.nfull[i] += s.nCount[i], acc.m[i] += s.mWeight[i];
                }
                const unsigned K = ++acc.frames;
                if (K & (K - 1)) return;
                const double grow = std::pow(double(K), op.accumPower);
                std::vector<float> img(N * 4, 1.0f);
                for (size_t i = 0; i < N; ++i) {
                    const double m = acc.m[i] / K * grow, k = m / (m + acc.n[i]);
                    for (int c = 0; c < 3; ++c) {
                        const double b = acc.nb[i * 3 + c] / acc.n[i], d = acc.nd[i * 3 + c] / acc.n[i], r = acc.r1[i * 3 + c] / K;
                        const double v = op.probeFull ? b + k * (r - b)
                                                      : (acc.nb[i * 3 + c] - acc.nd[i * 3 + c]) / acc.nfull[i] + (1 - k) * d + k * r;
                        img[i * 4 + c] = float(v);
                    }
                }
                writeFloats(out / ("accum-" + std::to_string(K) + ".rgba"), img);
            };
            // One after the other.
            {
                std::vector<double> period, pr, re, fi;
                const auto t = Clock::now();
                for (unsigned k = 0; k < F; ++k) {
                    const auto t0 = Clock::now();
                    Slot& s = slots[0];
                    prepare(s, k);
                    render(s);
                    finish(s);
                    period.push_back(since(t0)), pr.push_back(s.prepare), re.push_back(s.render), fi.push_back(s.finish);
                }
                Json::Value j;
                j["seconds"] = since(t);
                j["frame_median"] = median(period), j["prepare_median"] = median(pr), j["render_median"] = median(re), j["finish_median"] = median(fi);
                seq["serial"] = j;
            }
            // Pipelined.
            {
                std::vector<double> period, pr, re, fi;
                const auto t = Clock::now();
                prepare(slots[0], 0);
                threads = std::max(1u, op.seqThreads);
                auto mark = Clock::now();
                for (unsigned k = 0; k < F; ++k) {
                    std::thread cpuWork([&] {
                        const rhea::LowPriorityWork low;  // below the renderer's threads, on its own pool
                        if (k > 0) {
                            finish(slots[(k - 1) % 3]);
                            if (k == 1) first = slots[0].final;
                            if (op.accumulate) accumulate(slots[(k - 1) % 3]);
                        }
                        if (k + 1 < F) prepare(slots[(k + 1) % 3], k + 1);
                    });
                    render(slots[k % 3]);
                    cpuWork.join();
                    const Slot& done = slots[k % 3];
                    re.push_back(done.render);
                    if (k + 1 < F) pr.push_back(slots[(k + 1) % 3].prepare);
                    if (k > 0) fi.push_back(slots[(k - 1) % 3].finish);
                    period.push_back(since(mark));
                    mark = Clock::now();
                }
                finish(slots[(F - 1) % 3]);
                if (op.accumulate) accumulate(slots[(F - 1) % 3]);
                threads = op.threads;
                if (F == 1) first = slots[0].final;
                Json::Value j;
                j["seconds"] = since(t);
                j["frame_median"] = median(period), j["prepare_median"] = median(pr), j["render_median"] = median(re), j["finish_median"] = median(fi);
                j["threads"] = std::max(1u, op.seqThreads);
                seq["pipelined"] = j;
            }
            writeFloats(out / "sequence-final.rgba", first);
            // XPU2 on the same path: a camera move each frame (its camera-only update) and seq_xpu2 samples a pixel.
            {
                std::vector<double> period;
                const auto t = Clock::now();
                for (unsigned k = 0; k < F; ++k) {
                    const auto t0 = Clock::now();
                    auto px = std::make_shared<cpu::Plan>(*plan);
                    px->camera = cameraAt(k);
                    px->spp = op.seqXpu2;
                    px->seed = plan->seed + k * 7919u;
                    if (gpu) gpu->updateCamera(px);
                    async::RenderOptions o;
                    o.threads = op.threads;
                    o.mode = op.mode;
                    async::Renderer renderer(px, cpuScene, gpu.get());
                    const async::RenderResult rx = renderer.render(o);
                    cpu::need(!rx.failed, rx.error.empty() ? "XPU2 sequence frame failed" : rx.error);
                    period.push_back(since(t0));
                    if (op.accumulate) accumulateXpu2(rx.rgba);
                }
                Json::Value j;
                j["spp"] = op.seqXpu2;
                j["seconds"] = since(t);
                j["frame_median"] = median(period);
                seq["xpu2"] = j;
            }
            report["sequence"] = seq;
        }

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
            report["xpu2_launches"][std::to_string(n)] = Json::UInt64(rx.launches);
            for (const auto& l : rx.launchTrace) {
                Json::Value j(Json::arrayValue);
                j.append(l.queued), j.append(l.collected), j.append(l.deviceSeconds), j.append(Json::UInt64(l.chunks));
                report["xpu2_launch_trace"][std::to_string(n)].append(j);
            }
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
