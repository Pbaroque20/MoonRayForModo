// The Bregman engine's prototype (bregman/DESIGN.md): two-phase light transport over XPU2's asynchronous renderer.
//
// bregman_engine scene runtime ptx assets output [key=value ...]
//
// Phase 1. Probes on a lattice of stride s: on the GPU (and CPU, p1mode), an XPU2 frame of the probe pixels' direct
//   light (max_depth 0, probe_spp samples each, every other pixel none); at the same time on the host, each probe's
//   camera ray is traced (Embree, CpuBackend), its mesh scanned ring by ring (scan.h) and the patch's depths
//   rasterized over its window. The windows' depths make the region buffer: each pixel's visible inverse depth, the
//   probes whose patches are that surface there, the Bregman Voronoi cell (the probe whose tangent hyperplane predicts
//   it best) and its Bregman Delaunay triangle (bvd.h).
// Phase 2. An XPU2 frame of full paths, n(x) samples a pixel by the pixel's class (trusted, cell only, untrusted,
//   background), with two light path outputs that sum to a path's direct light at its first hit (C[<L.>O] and
//   C[DGS][<L.>O]).
// Combination. final = B + m / (m + n) (R1 - D): B and D phase 2's beauty and direct light means, R1 phase 1's
//   reconstruction, m the samples it counts as (0 where untrusted). The indirect light is phase 2's alone, unbiased;
//   phase 1's bias in the direct light falls as m / (m + n) with phase 2's samples.
//
// Writes raw float32 RGBA films (phase1, recon, phase2, direct2, final, classes, cells, depth) and prints one JSON
// report. No Modo API.
#include "async_render.h"
#include "scan.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
#include <map>
#include <thread>

using namespace xpu2::interactive;
namespace rdl = scene_rdl2::rdl2;
using Clock = std::chrono::steady_clock;

static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

namespace {

struct Options {
    unsigned threads = 12, stride = 4, probeSpp = 64, nLo = 4, nMid = 16, nHi = 64, nBg = 1, rings = 64, tris = 4096;
    int mode = 2, p1mode = 1;
    double m0 = 64, tauD = 0.01, tauR = 0.25;
    bool overlap = true;
    std::string override_;
    unsigned repeats = 3;            // timed runs after one warm-up
    std::vector<unsigned> xpu2Spp;  // XPU2 frames to time in the same process (samples a pixel)
    // Phase 2's frame cache (mixed::Config::frameCache): on, the chance a bounce that reaches it goes on, the depth
    // tolerance; OpenQMC past the first hit (qmc_depth: vertices of nonMirrorDepth below it), and in XPU2's frames too.
    bool cache = false;  // off by default: it needs the engine's own GPU program (build_bregman.py --gpu)
    double cacheP = 0.25, cacheTol = 0.02;
    unsigned qmcDepth = 0, xpu2Qmc = 0;
};

// A probe: its pixel, its hit, its patch's depth over its window, its site.
struct Probe {
    int px = 0, py = 0;
    bool hit = false;
    uint32_t geom = ~0u, prim = 0;
    bregman::Site site;
    bregman::DepthTile tile;
    uint32_t patchTris = 0, rings = 0;
    bool truncated = false;
};

enum Class : uint8_t { Background = 0, Trusted = 1, CellOnly = 2, Untrusted = 3, Uncovered = 4, Edge = 5, Saddle = 6, Silhouette = 7 };
constexpr int Classes = 8;

uint32_t mix(uint32_t a) {
    a ^= a >> 16;
    a *= 0x7feb352du;
    a ^= a >> 15;
    a *= 0x846ca68bu;
    a ^= a >> 16;
    return a;
}

template <class F>
void parallel(unsigned threads, size_t n, F f) {
    std::atomic<size_t> next{0};
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < std::max(1u, threads); ++t)
        pool.emplace_back([&] {
            for (size_t i; (i = next.fetch_add(1)) < n;) f(i);
        });
    for (auto& t : pool) t.join();
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

double luminance(const float* c) { return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }

// An output's channel offset in a pixel's AOV values (-1: not there).
int aovOffset(const cpu::Plan& plan, const std::string& name) {
    if (!plan.aovs) return -1;
    for (const auto* o : plan.aovs->all)
        if (o->name == name && o->entry >= 0) return int(plan.aovs->entries[o->entry].offset);
    return -1;
}

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
            else if (k == "stride") op.stride = unsigned(std::stoul(v));
            else if (k == "probe_spp") op.probeSpp = unsigned(std::stoul(v));
            else if (k == "n_lo") op.nLo = unsigned(std::stoul(v));
            else if (k == "n_mid") op.nMid = unsigned(std::stoul(v));
            else if (k == "n_hi") op.nHi = unsigned(std::stoul(v));
            else if (k == "n_bg") op.nBg = unsigned(std::stoul(v));
            else if (k == "m0") op.m0 = std::stod(v);
            else if (k == "tau_d") op.tauD = std::stod(v);
            else if (k == "tau_r") op.tauR = std::stod(v);
            else if (k == "rings") op.rings = unsigned(std::stoul(v));
            else if (k == "tris") op.tris = unsigned(std::stoul(v));
            else if (k == "overlap") op.overlap = v != "0";
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
        cpu::need(op.stride >= 1 && op.stride <= 16 && op.mode >= 0 && op.mode <= 2 && op.p1mode >= 0 && op.p1mode <= 2, "Option bounds");
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

        const unsigned W = plan->width, H = plan->height, S = op.stride, spp = plan->spp;
        cpu::need(op.probeSpp >= 1 && op.probeSpp <= spp && op.nHi <= spp && op.nMid <= spp && op.nLo <= spp && op.nBg >= 1 && op.nLo >= 1,
                  "Sample counts must lie in [1, the scene's samples a pixel]");
        const unsigned BX = (W + S - 1) / S, BY = (H + S - 1) / S;
        bregman::Frame frame;
        cpu::need(frame.init(plan->camera), "Camera frame");
        // The frame cache's lift on the device takes the camera transform as affine (three columns and a translation).
        cpu::need(std::fabs(frame.toCamera[0][3]) < 1e-9 && std::fabs(frame.toCamera[1][3]) < 1e-9 && std::fabs(frame.toCamera[2][3]) < 1e-9 &&
                      std::fabs(frame.toCamera[3][3] - 1) < 1e-9,
                  "An affine camera transform");
        const size_t N = size_t(W) * H;

        // Each mesh's topology, made the first time a probe hits it and kept (as XPU2 keeps a mesh's tessellation).
        std::map<uint32_t, bregman::Topology> topologies;
        Json::Value runs(Json::arrayValue);
        // Run 0 warms up (texture tiles reach the card, topologies are made); runs 1..repeats are timed.
        for (unsigned rep = 0; rep <= op.repeats; ++rep) {
        const bool last = rep == op.repeats;

        // The lattice: one probe a block, its pixel chosen from the block and the frame's seed.
        std::vector<Probe> probes(size_t(BX) * BY);
        for (unsigned by = 0; by < BY; ++by)
            for (unsigned bx = 0; bx < BX; ++bx) {
                const uint32_t h = mix(mix(bx * 0x9e3779b9u ^ by) ^ plan->seed);
                Probe& p = probes[size_t(by) * BX + bx];
                p.px = int(std::min(W - 1, bx * S + h % S));
                p.py = int(std::min(H - 1, by * S + (h / S) % S));
            }

        // Phase 1's frame: the probes' direct light (max_depth 0), probe_spp samples a probe pixel, none elsewhere.
        auto p1 = std::make_shared<cpu::Plan>(*plan);
        p1->maxDepth = 0;
        p1->pixelSamples.assign(size_t(W) * H, 0u);
        for (const auto& p : probes) p1->pixelSamples[size_t(p.py) * W + p.px] = op.probeSpp;
        // The grid hands out sample indices up to the plan's spp for every pixel: no more than any pixel takes.
        p1->spp = op.probeSpp;
        async::RenderOptions o1;
        o1.threads = op.threads;
        o1.mode = op.p1mode;
        async::RenderResult r1;
        double phase1Render = 0;

        // The host's half of phase 1: probe hits, topologies, scans, depth tiles.
        double traceSeconds = 0, topologySeconds = 0, scanSeconds = 0;
        auto hostPhase1 = [&] {
            auto t = Clock::now();
            parallel(op.threads, probes.size(), [&](size_t i) {
                Probe& p = probes[i];
                surface::Ray ray;
                if (!surface::cameraRay(plan->camera, p.px + 0.5f, p.py + 0.5f, ray)) return;
                async::CpuBackend backend{cpuScene};
                const resume::Hit h = backend.trace(ray);
                if (h.geom == ~0u) return;
                const auto& m = *plan->meshes[h.geom].data;
                if (m.points || m.curveBasis || m.triangles.empty()) return;  // not a triangle mesh: no scan
                p.hit = true;
                p.geom = h.geom;
                p.prim = h.prim;
            });
            traceSeconds = since(t);
            t = Clock::now();
            std::vector<uint32_t> geoms;
            for (const auto& p : probes)
                if (p.hit && !topologies.count(p.geom)) geoms.push_back(p.geom);
            std::sort(geoms.begin(), geoms.end());
            geoms.erase(std::unique(geoms.begin(), geoms.end()), geoms.end());
            for (uint32_t g : geoms) topologies[g];
            parallel(op.threads, geoms.size(), [&](size_t i) { topologies[geoms[i]] = bregman::buildTopology(*plan->meshes[geoms[i]].data); });
            topologySeconds = since(t);
            t = Clock::now();
            parallel(op.threads, probes.size(), [&](size_t i) {
                Probe& p = probes[i];
                if (!p.hit) return;
                const int bx = int(i % BX), by = int(i / BX);
                const int x0 = std::max(0, (bx - 1) * int(S)), y0 = std::max(0, (by - 1) * int(S));
                const int x1 = std::min(int(W), (bx + 2) * int(S)), y1 = std::min(int(H), (by + 2) * int(S));
                const bregman::Patch patch = bregman::scan(frame, *plan, topologies.at(p.geom), p.geom, p.prim, x0, y0, x1, y1, op.rings, op.tris);
                if (patch.tris.empty()) {
                    p.hit = false;
                    return;
                }
                const auto& seed = patch.tris.front();
                p.site.h = bregman::planeThrough(seed.x, seed.y, seed.w);
                if (!p.site.h.ok) {
                    p.hit = false;
                    return;
                }
                p.site.x = p.px + 0.5;
                p.site.y = p.py + 0.5;
                p.site.w = p.site.h.at(p.site.x, p.site.y);  // the hit's inverse depth, on its triangle's plane
                p.site.probe = int(i);
                p.tile = bregman::rasterize(patch, x0, y0, x1, y1);
                p.patchTris = uint32_t(patch.tris.size());
                p.rings = patch.rings;
                p.truncated = patch.truncated;
            });
            scanSeconds = since(t);
        };
        stamp = Clock::now();
        if (op.overlap && op.p1mode == 1) {
            // The GPU renders the probes' light while the CPU scans: neither waits for the other.
            std::thread host(hostPhase1);
            if (gpu) gpu->updateCamera(p1);
            const auto t = Clock::now();
            async::Renderer renderer(p1, cpuScene, gpu.get());
            r1 = renderer.render(o1);
            phase1Render = since(t);
            host.join();
        } else {
            hostPhase1();
            if (gpu) gpu->updateCamera(p1);
            const auto t = Clock::now();
            async::Renderer renderer(p1, cpuScene, gpu.get());
            r1 = renderer.render(o1);
            phase1Render = since(t);
        }
        cpu::need(!r1.failed, r1.error.empty() ? "Phase 1 failed" : r1.error);
        const double phase1Seconds = since(stamp);

        // The region buffer and the reconstruction.
        stamp = Clock::now();
        std::vector<float> recon(N * 4, 0.0f), wvis(N, 0.0f), classes(N * 4, 0.0f), cells(N * 4, 0.0f), depth(N * 4, 0.0f);
        std::vector<uint8_t> cls(N, Untrusted);
        std::vector<uint32_t> visGeom(N, ~0u);  // the mesh of the visible patch surface
        std::vector<int> ownerOf(N, -1);         // the cell's probe
        std::vector<float> mWeight(N, 0.0f);
        std::vector<unsigned> nCount(N, op.nHi);
        auto radiance = [&](const Probe& p) { return &r1.rgba[(size_t(p.py) * W + p.px) * 4]; };
        // A window's Bregman Delaunay triangulation, by its block and the sites the pixel sees (a 9-bit mask).
        struct Tri {
            std::vector<bregman::Site> sites;
            std::vector<std::array<int, 3>> faces;
            int sign = 1;
            bool saddle = false;
        };
        std::vector<std::map<uint32_t, Tri>> bdt(size_t(BX) * BY);
        std::vector<std::mutex> bdtLocks(64);
        std::atomic<uint64_t> facesMade{0}, saddles{0};
        parallel(op.threads, H, [&](size_t yy) {
            const int y = int(yy);
            for (int x = 0; x < int(W); ++x) {
                const size_t pix = size_t(y) * W + x;
                const int bx = x / int(S), by = y / int(S);
                int cand[9];
                int nc = 0, hits = 0;
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int cx = bx + dx, cy = by + dy;
                        if (cx < 0 || cy < 0 || cx >= int(BX) || cy >= int(BY)) continue;
                        cand[nc++] = cy * int(BX) + cx;
                        hits += probes[size_t(cy) * BX + cx].hit;
                    }
                // The visible inverse depth: the nearest patch surface over this pixel.
                double wv = 0;
                for (int k = 0; k < nc; ++k) {
                    const Probe& p = probes[cand[k]];
                    if (!p.hit) continue;
                    const auto& t = p.tile;
                    const int lx = x - t.x0, ly = y - t.y0;
                    if (lx < 0 || ly < 0 || lx >= t.width || ly >= t.height) continue;
                    const double w = t.w[size_t(ly) * t.width + lx];
                    if (w > wv) {
                        wv = w;
                        visGeom[pix] = p.geom;
                    }
                }
                wvis[pix] = float(wv);
                float* rc = &recon[pix * 4];
                if (wv == 0) {
                    if (hits == 0) {
                        // Every probe around it missed: the background, as they saw it.
                        for (int k = 0; k < nc; ++k)
                            for (int c = 0; c < 4; ++c) rc[c] += radiance(probes[cand[k]])[c] / float(nc);
                        cls[pix] = Background;
                    } else {
                        cls[pix] = Uncovered;
                    }
                    continue;
                }
                // The probes whose patch is the visible surface here, and their divergences D(x || p).
                uint32_t mask = 0;
                int owner = -1;
                double best = 1e300, bestDist = 1e300;
                double D[9];
                for (int k = 0; k < nc; ++k) {
                    const Probe& p = probes[cand[k]];
                    D[k] = 1e300;
                    if (!p.hit) continue;
                    const auto& t = p.tile;
                    const int lx = x - t.x0, ly = y - t.y0;
                    if (lx < 0 || ly < 0 || lx >= t.width || ly >= t.height) continue;
                    const double w = t.w[size_t(ly) * t.width + lx];
                    if (w == 0 || std::fabs(w - wv) > 1e-6 * wv) continue;
                    mask |= 1u << k;
                    D[k] = std::fabs(wv - p.site.h.at(x + 0.5, y + 0.5)) / wv;
                    const double dist = (p.site.x - x - 0.5) * (p.site.x - x - 0.5) + (p.site.y - y - 0.5) * (p.site.y - y - 0.5);
                    if (D[k] < best - 1e-12 || (D[k] <= best + 1e-12 && dist < bestDist)) {
                        best = std::min(best, D[k]);
                        bestDist = dist;
                        owner = k;
                    }
                }
                if (owner < 0) {
                    cls[pix] = Uncovered;
                    continue;
                }
                const Probe& op0 = probes[cand[owner]];
                ownerOf[pix] = cand[owner];
                const uint32_t oid = mix(uint32_t(cand[owner]) + 1);
                cells[pix * 4] = float(oid & 255) / 255.f, cells[pix * 4 + 1] = float((oid >> 8) & 255) / 255.f,
                cells[pix * 4 + 2] = float((oid >> 16) & 255) / 255.f, cells[pix * 4 + 3] = 1;
                // The Bregman Delaunay triangulation of the connected sites.
                const size_t blk = size_t(by) * BX + bx;
                const Tri* tri = nullptr;
                {
                    std::lock_guard<std::mutex> lock(bdtLocks[blk % bdtLocks.size()]);
                    auto it = bdt[blk].find(mask);
                    if (it == bdt[blk].end()) {
                        Tri t;
                        for (int k = 0; k < nc; ++k)
                            if (mask & (1u << k)) t.sites.push_back(probes[cand[k]].site);
                        // The generator's sign: the local convexity the sites' pairwise divergences agree on.
                        int pos = 0, neg = 0;
                        for (const auto& a : t.sites)
                            for (const auto& b : t.sites) {
                                if (&a == &b) continue;
                                const double e = (b.w - a.h.at(b.x, b.y)) / b.w;
                                if (e > 1e-7) ++pos;
                                if (e < -1e-7) ++neg;
                            }
                        t.sign = neg > pos ? -1 : 1;
                        // A saddle (or a bumpy, displaced surface at the lattice's scale): a third of the pairs or more
                        // disagree with the majority's convexity. A few dissenting pairs are the surface's fine relief.
                        t.saddle = 3 * std::min(pos, neg) >= pos + neg && pos + neg > 0;
                        saddles += t.saddle;
                        if (t.sites.size() >= 3) {
                            t.faces = bregman::bregmanDelaunay(t.sites, t.sign, (bx + 0.5) * S, (by + 0.5) * S, double(S), wv);
                            facesMade += t.faces.size();
                        }
                        it = bdt[blk].emplace(mask, std::move(t)).first;
                    }
                    tri = &it->second;
                }
                // Its triangle here: barycentric weights over three probes, or the cell's probe alone.
                int face = -1;
                double b[3] = {0, 0, 0};
                for (size_t f = 0; f < tri->faces.size() && face < 0; ++f) {
                    const auto& F = tri->faces[f];
                    const double tx[3] = {tri->sites[F[0]].x, tri->sites[F[1]].x, tri->sites[F[2]].x};
                    const double ty[3] = {tri->sites[F[0]].y, tri->sites[F[1]].y, tri->sites[F[2]].y};
                    if (bregman::barycentric(x + 0.5, y + 0.5, tx, ty, b)) face = int(f);
                }
                Class c = CellOnly;
                double maxD = best;
                if (face >= 0 && !tri->saddle) {
                    const auto& F = tri->faces[face];
                    double lo = 1e300, hi = -1e300, mean = 0;
                    for (int k = 0; k < 3; ++k) {
                        const Probe& p = probes[tri->sites[F[k]].probe];
                        const double L = luminance(radiance(p));
                        lo = std::min(lo, L), hi = std::max(hi, L), mean += L / 3;
                        for (int j = 0; j < nc; ++j)
                            if (cand[j] == tri->sites[F[k]].probe) maxD = std::max(maxD, D[j]);
                        for (int ch = 0; ch < 4; ++ch) rc[ch] += float(b[k]) * radiance(p)[ch];
                    }
                    c = (hi - lo) / (mean + 1e-3) > op.tauR ? Edge : Trusted;
                } else {
                    for (int ch = 0; ch < 4; ++ch) rc[ch] = radiance(op0)[ch];
                    if (tri->saddle) c = Saddle;
                }
                if (maxD > op.tauD) c = Untrusted;
                cls[pix] = c;
            }
        });
        // Silhouettes, from the scans' depths: a pixel whose footprint may hold another surface (a neighbour with no
        // patch surface, another mesh, or a depth its cell's plane does not predict) is a blend the probes do not see.
        std::vector<uint8_t> cls0 = cls;
        parallel(op.threads, H, [&](size_t yy) {
            const int y = int(yy);
            for (int x = 0; x < int(W); ++x) {
                const size_t pix = size_t(y) * W + x;
                if (cls0[pix] != Trusted && cls0[pix] != CellOnly && cls0[pix] != Background) continue;
                bool edge = false;
                for (int dy = -1; dy <= 1 && !edge; ++dy)
                    for (int dx = -1; dx <= 1 && !edge; ++dx) {
                        const int nx = x + dx, ny = y + dy;
                        if ((!dx && !dy) || nx < 0 || ny < 0 || nx >= int(W) || ny >= int(H)) continue;
                        const size_t q = size_t(ny) * W + nx;
                        if (cls0[pix] == Background) {
                            edge = wvis[q] != 0;  // the background beside a surface
                            continue;
                        }
                        if (wvis[q] == 0 || visGeom[q] != visGeom[pix]) {
                            edge = true;
                            continue;
                        }
                        const auto& h = probes[ownerOf[pix]].site.h;
                        edge = std::fabs(wvis[q] - h.at(nx + 0.5, ny + 0.5)) / wvis[q] > op.tauD;
                    }
                if (edge) cls[pix] = Silhouette;
            }
        });
        // Each class's phase 2 samples and phase 1's weight.
        static const float palette[Classes][3] = {{0.1f, 0.1f, 0.1f}, {0.2f, 0.8f, 0.3f}, {0.9f, 0.8f, 0.2f}, {0.9f, 0.2f, 0.2f},
                                                  {0.8f, 0.2f, 0.9f}, {1.0f, 0.5f, 0.1f}, {0.2f, 0.5f, 1.0f}, {1.0f, 1.0f, 1.0f}};
        uint64_t classCount[Classes] = {};
        for (size_t i = 0; i < N; ++i) {
            const Class c = Class(cls[i]);
            ++classCount[c];
            switch (c) {
                case Background: nCount[i] = op.nBg, mWeight[i] = float(op.m0); break;
                case Trusted: nCount[i] = op.nLo, mWeight[i] = float(op.m0); break;
                case CellOnly: nCount[i] = op.nMid, mWeight[i] = float(op.m0 / 4); break;
                default: nCount[i] = op.nHi, mWeight[i] = 0; break;
            }
            for (int k = 0; k < 3; ++k) classes[i * 4 + k] = palette[c][k];
            classes[i * 4 + 3] = 1;
            for (int k = 0; k < 3; ++k) depth[i * 4 + k] = wvis[i];
            depth[i * 4 + 3] = 1;
        }
        const double regionSeconds = since(stamp);

        // Phase 2: full paths, n(x) a pixel, with the direct light's two expressions.
        auto p2 = std::make_shared<cpu::Plan>(*plan);
        p2->pixelSamples = nCount;
        p2->spp = *std::max_element(nCount.begin(), nCount.end());
        // The frame cache: phase 1's radiance and the visible inverse depth where phase 1 is trusted (the cell's or the
        // triangle's), for phase 2's bounces (async_integrator.h frameCacheAt), and OpenQMC past the first hit.
        if (op.cache) {
            auto cache = std::make_shared<std::vector<float>>(N * 4, 0.0f);
            for (size_t i = 0; i < N; ++i) {
                if (cls[i] != Trusted && cls[i] != CellOnly) continue;
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
        const int offEmit = aovOffset(*p2, "/bregman_emission"), offDirect = aovOffset(*p2, "/bregman_direct");
        cpu::need(offEmit >= 0 && offDirect >= 0, "The scene needs the outputs /bregman_emission and /bregman_direct (run_bregman.py adds them)");
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
            t["phase1_seconds"] = phase1Seconds;
            t["phase1_render_seconds"] = phase1Render;
            t["phase1_sampling_seconds"] = r1.seconds;
            t["probe_trace_seconds"] = traceSeconds;
            t["topology_seconds"] = topologySeconds;
            t["scan_seconds"] = scanSeconds;
            t["region_seconds"] = regionSeconds;
            t["phase2_seconds"] = phase2Seconds;
            t["phase2_sampling_seconds"] = r2.seconds;
            t["combine_seconds"] = combineSeconds;
            t["total_seconds"] = phase1Seconds + regionSeconds + phase2Seconds + combineSeconds;
            t["warm_up"] = rep == 0;
            runs.append(t);
        }
        if (!last) continue;

        writeFloats(out / "phase1.rgba", r1.rgba);
        writeFloats(out / "recon.rgba", recon);
        writeFloats(out / "phase2.rgba", r2.rgba);
        writeFloats(out / "direct2.rgba", direct2);
        writeFloats(out / "final.rgba", final);
        writeFloats(out / "classes.rgba", classes);
        writeFloats(out / "cells.rgba", cells);
        writeFloats(out / "depth.rgba", depth);
        {
            std::vector<float> nmap(N * 4, 0.0f);
            for (size_t i = 0; i < N; ++i) {
                for (int k = 0; k < 3; ++k) nmap[i * 4 + k] = float(nCount[i]) / float(op.nHi);
                nmap[i * 4 + 3] = 1;
            }
            writeFloats(out / "samples2.rgba", nmap);
        }

        uint64_t hit = 0, truncated = 0, trisSum = 0, ringsMax = 0;
        for (const auto& p : probes) {
            hit += p.hit;
            truncated += p.truncated;
            trisSum += p.patchTris;
            ringsMax = std::max<uint64_t>(ringsMax, p.rings);
        }
        uint64_t welded = 0, borders = 0, nonManifold = 0, topoTris = 0;
        for (const auto& [g, t] : topologies) welded += t.welded, borders += t.borders, nonManifold += t.nonManifold, topoTris += t.nbr.size() / 3;
        report["width"] = W;
        report["height"] = H;
        report["scene_spp"] = spp;
        Json::Value o;
        o["stride"] = S, o["probe_spp"] = op.probeSpp, o["n_lo"] = op.nLo, o["n_mid"] = op.nMid, o["n_hi"] = op.nHi, o["n_bg"] = op.nBg;
        o["m0"] = op.m0, o["tau_d"] = op.tauD, o["tau_r"] = op.tauR, o["rings"] = op.rings, o["tris"] = op.tris;
        o["mode"] = op.mode, o["p1mode"] = op.p1mode, o["overlap"] = op.overlap, o["threads"] = op.threads;
        o["cache"] = op.cache, o["cache_p"] = op.cacheP, o["cache_tol"] = op.cacheTol, o["qmc_depth"] = op.qmcDepth, o["xpu2_qmc"] = op.xpu2Qmc;
        report["options"] = o;
        report["probes"] = Json::UInt64(probes.size());
        report["probes_hit"] = Json::UInt64(hit);
        report["patch_triangles_mean"] = hit ? double(trisSum) / double(hit) : 0.0;
        report["patch_rings_max"] = Json::UInt64(ringsMax);
        report["patches_truncated"] = Json::UInt64(truncated);
        report["topology"]["meshes"] = Json::UInt64(topologies.size());
        report["topology"]["triangles"] = Json::UInt64(topoTris);
        report["topology"]["welded_vertices"] = Json::UInt64(welded);
        report["topology"]["border_edges"] = Json::UInt64(borders);
        report["topology"]["non_manifold_edges"] = Json::UInt64(nonManifold);
        report["bdt_faces"] = Json::UInt64(facesMade.load());
        report["bdt_saddle_windows"] = Json::UInt64(saddles.load());
        static const char* names[Classes] = {"background", "trusted", "cell_only", "untrusted", "uncovered", "edge", "saddle", "silhouette"};
        for (int c = 0; c < Classes; ++c) report["classes"][names[c]] = double(classCount[c]) / double(N);
        report["phase2_samples_per_pixel"] = samples2 / double(N);
        report["phase1_probe_samples_per_pixel"] = double(probes.size()) * op.probeSpp / double(N);
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
