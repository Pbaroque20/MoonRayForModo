// Rhea as XPU2's realtime engine (rhea/DESIGN.md 21): one frame at a time of persistent probes (persistent.h), each a
// plan XPU2's renderer takes as it is (a sample map, gather tiles, the first hit only past phase 2's samples), and the
// frame's picture made of the probes' reconstruction and phase 2's samples.
//
// The fallback to XPU2 is the combination itself, pixel by pixel: a pixel the GPU's samples do not verify, or whose
// light the probes do not trust, takes phase 1's weight 0 and is XPU2's samples alone, and while the camera rests every
// frame's samples are summed, so that phase 1's weight m / (m + N) falls as XPU2's samples pile up. Nothing restarts
// but what XPU2's realtime restarts too (a moved camera: the sums; an edit: the probes as well).
//
// The plan must carry Rhea's outputs (rdla.py writes them for XPU2 RT (Rhea)): the light emitted and the direct light
// at the first hit (LPEs C[<L.>O] and C[DGS][<L.>O]), the first hit's albedo, and the nearest and farthest first-hit
// depths (the state variable depth, math filters min and max).
#pragma once
#include "persistent.h"
#include "planes.h"
#include "mesh_warp.h"
#include "object_warp.h"
#include "async_render.h"
#include <cstdio>
#include <numeric>
#include <string>

namespace rhea {

namespace async = xpu2::interactive::async;

struct RealtimeOptions {
    unsigned phase2Max = 2;   // phase 2's samples a pixel a frame, at most (DESIGN.md 17)
    // Phase 2's samples where the probes' triangle holds, at most (0: as phase2Max gives). 1: on Sponza Rhea's frame
    // took 2.0 s, not 3.1 (46,000 samples, not 62,000), and the moves' pictures were as good on the whole (XPU2's
    // frame after it had the time it saved); at 720p on the test scene, 0.95 million samples, not 1.7 (DESIGN.md 26).
    unsigned trustedSpp = 1;
    unsigned probeSpp = 64;   // a new probe's pixel's samples
    unsigned keepSpp = 4;     // a known probe's pixel's samples a frame
    bool residentTextures = true;  // a frame's textures read only from what the card holds (Plan::residentTextures)
    double probeShare = 0.5;  // the probes' samples a frame at most this share of phase 2's (new ones share what is left)
    unsigned nBg = 1;         // the sky's samples a frame
    // At rest phase 2's samples a frame double each frame (the cap's, twice, four times... up to restMax): the sums are
    // XPU2's samples, and longer frames spend less on each frame's fixed costs, so the picture converges at XPU2's pace.
    unsigned restMax = 32;
    // The frame's samples a pixel (the session's realtime frame: its plan's spp), phase 2's at rest never past it; 0: none.
    unsigned target = 0;
    unsigned cell = 8, gapPasses = 2;
    double m0 = 32;           // phase 1 counts as this many samples (accumulated: not growing, DESIGN.md 18)
    // Spherical, fisheye and dome cameras: their light interpolated over triangles the lens bends, phase 1 counts for
    // less (DESIGN.md 22: at 32 its one-signed bias showed against XPU2 at 32 samples; at 8 neither measure did).
    double m0Directional = 8;
    double tauR = 0.25, tol = 0.002, fade = 0.95;
    bool demod = true, cleanAbsorb = true;
    // A pixel verifies, or gives its probe light, only where its alpha is whole (off: on the test scene it held back
    // probes that were right, and the out of focus bias it was meant for was not misses; DESIGN.md 22).
    bool coverage = false;
    // The surface's own plane for slanted surfaces (FieldOptions::slant, planeLight; DESIGN.md 23).
    bool slant = true, planeLight = true;
    // The virtual planes past the front hyperplane (planes.h, DESIGN.md 25): a pixel the probes' triangulation does not
    // hold is taken by its surface's slanted plane (planar), else by the back plane's reprojected light (backPlane),
    // the frame's own depths deciding each. quietNeed: a pixel either holds asks for no probe.
    bool planar = true, backPlane = true, quietNeed = true;
    bool prune = true;  // probes their neighbours on their plane predict, dormant (ProbeField::prune)
    // A camera move's first picture (DESIGN.md 26): the last picture shown moved into the new view by its depths (warp),
    // at once, before any of the GPU's work; XPU2's pictures folded into it where their depths hold its points, the warp
    // counting as warpWeight samples (a hole filled from a neighbour, a quarter) and fading as XPU2's frame goes on.
    bool warp = true;
    double warpWeight = 8;
    // The warp as a mesh gradient (mesh_warp.h, DESIGN.md 28): the picture's colour at sparse points (cells of warpCell
    // pixels at 1280 x 720, finer where its depth jumps by warpJump), averaged over each point's surface (fully within
    // warpSoft of its plane, less up to warpJump), drawn as triangles into the new view; the environment moved as
    // directions; what lay behind filled from the farthest around it. Off: pixel by pixel, as DESIGN.md 26.
    bool warpMesh = true;
    double warpCell = 16, warpJump = 0.03, warpSoft = 0.01;
    // The warp's source is the last picture rendered: Rhea's frame, or XPU2's once its samples reach this share of the
    // pixels; a warp (or a picture mostly made of one) is never the next warp's source (warpChain: it was, and a long drag
    // lost more each step, down to black).
    double warpKeepCoverage = 0.95;
    bool warpChain = false;
    // The drag's picture from colours kept on the surfaces (object_warp.h, DESIGN.md 30): every picture kept as the
    // warp's source adds to the store, and a move's picture is the CPU scene's first hits coloured from it, streamed in
    // rings from the centre out. Off: the mesh gradient (warpMesh).
    bool objectSpace = true;
    double storeScale = 2, storeGrazing = 8;
    size_t objectRays = 60000;
    unsigned objectRings = 3;
    bool objectAntialias = true;  // phase one's finished picture through FXAA (object_warp.h Fxaa)
    // The store's light and albedo apart (ObjectStore::Options::albedo): the albedo in cells half as wide, multiplied by
    // the cells' light (the user's composite from the outputs the pictures carry). Off: the colours as they are.
    bool storeAlbedo = false;
    // After a move's warp, the next move looked for this long before any of the GPU's work (seconds; the kit sends a
    // drag's steps about 60 ms apart): a drag then goes at the warp's pace, not the GPU frame's stop (0.2 s at 720p).
    // 0.15 s: in Modo the kit makes a step at each of its 60 ms ticks, with its own 18 ms or so, and sends it once the
    // last is applied: steps came 80 to 100 ms apart, past an 80 ms hold (RESULTS.md section 21).
    double dragHold = 0.15;
    // The probes' screen cells grow with the picture (cell times the square root of its pixels over 320 x 240's): as many
    // probes at 1280 x 720 as at 320 x 240, where 22,000 had taken 0.12 s to place and 0.7 s of the GPU's (DESIGN.md 26).
    bool cellsByPicture = true;
    double planarEdge = 4;    // a slanted plane's triangle's sides at most this many cells (PlanarLayer::build)
    double planarSupport = 0.85;  // a slanted plane's triangle used where this share of its pixels lie on it (PlanarLayer::support)
    double backCap = 1024;    // the back plane's weight a pixel at most (samples)
    // The back plane's light divided by its pixel's colour, and multiplied by the new pixel's (off: kept as it was, its
    // texture with it): on Sponza glossy light divided by a dark colour came back 2-3 times too bright, and a frame at
    // rest's fine texture beats a camera move's coarse one (DESIGN.md 25).
    bool backDemod = false;
    // The back plane looked up from each frame's own depths, its light blended from the stored pixels about each point
    // (BackPlane::gather; off: each stored point lifted to the pixel it lands in, BackPlane::reproject).
    bool backGather = true;
    // The planes' light counts as this share of the probes' (m0, the back plane's samples at most m0): measured against
    // the reference their light was 2 to 8 times better than their pixels' own few samples where the probes' was 10 times
    // (DESIGN.md 25).
    // On Sponza the back plane looked up from the frame's depths was 3 to 5 times better: its whole weight.
    double planarWeight = 0.25, backWeight = 1.0;
    double backTol = 0.01;    // a reprojected point's reach past the pixel's depths: at most this (relative), or the depths' slope
    int probeFull = -1;       // -1: whole-light probes where the scene bounces diffusely
    unsigned threads = 4;     // the CPU's part (the field)
    // An investigation: each frame's reconstruction, phase 1's mask (0 XPU2's alone, 0.5 verified, 1 phase 1 used) and
    // the picture, written into this folder as raw floats (four a pixel, film order) by finish.
    std::string debugFolder;
};

// Where Rhea's outputs lie in a pixel's AOV values (-1: missing).
struct RealtimeOutputs {
    int emission = -1, direct = -1, albedo = -1, depthMin = -1, depthMax = -1;
    bool complete() const { return emission >= 0 && direct >= 0 && albedo >= 0 && depthMin >= 0 && depthMax >= 0; }
};

// An output's first value in a pixel's AOV values, by its name (-1: none).
inline int outputOffset(const cpu::Plan& plan, const std::string& name) {
    if (!plan.aovs) return -1;
    for (const auto* o : plan.aovs->all)
        if (o->name == name && o->entry >= 0) return int(plan.aovs->entries[o->entry].offset);
    return -1;
}

inline RealtimeOutputs outputsOf(const cpu::Plan& plan) {
    RealtimeOutputs o;
    o.emission = outputOffset(plan, "/rhea_emission"), o.direct = outputOffset(plan, "/rhea_direct");
    o.albedo = outputOffset(plan, "/rhea_albedo");
    o.depthMin = outputOffset(plan, "/rhea_depth_min"), o.depthMax = outputOffset(plan, "/rhea_depth_max");
    return o;
}

// Why a plan cannot take Rhea's frames (empty: it can). Rhea's lift is a still pinhole perspective camera's (DESIGN.md
// 19, cameras): other cameras, depth of field and motion blur are XPU2's frames as they were.
inline std::string unsupported(const cpu::Plan& plan) {
    if (!plan.paths) return "not the path tracer";
    if (!plan.pixelSamples.empty()) return "a pixel sample map";
    const surface::Camera& c = plan.camera;
    if (c.type == surface::CameraBake) return "a bake camera";
    if (c.type == surface::CameraDome && c.k[surface::DomeInterocular] != 0.0f) return "a dome's stereo eyes";
    if (c.type == surface::CameraSpherical && (c.flags & surface::SphInsideOut)) return "an inside-out spherical camera";
    if (!outputsOf(plan).complete()) return "the scene lacks Rhea's outputs";
    View v;
    if (!v.init(c, plan.width, plan.height)) return "the camera's view";
    return "";
}

// The state of one realtime view: the field of probes, and the sums of the frames since the camera last moved.
class Realtime {
public:
    RealtimeOptions op;

    // Everything forgotten: an edit to the scene (anything but the camera alone), or a new scene.
    // Everything forgotten: a new scene, an edit.
    void reset() {
        resetProbes();
        last = Shown{}, warped = Warped{}, lastKind = 0;
        mesh.clear();
        store.clear();
    }
    // The probes, sums and planes forgotten, the last picture kept for the next move's warp: other geometry for the same
    // scene (the full plan after a coarse first pass; a camera move that tessellates camera-dependent geometry again, a
    // displaced sea's) - the warp needs only the picture and its depths. Forgetting it there, a move of the user's dragon
    // over a sea had no warp, so no first phase for the completion fade (2026-11-22: "there's no fade").
    void resetProbes() {
        field = ProbeField{};
        frame = 0;
        clearSums();
        haveCamera = false;
        back.clear(), haveBack = false;
    }
    // The picture's sums forgotten, the probes kept: the camera has moved.
    void clearSums() {
        acc.frames = 0;  // the vectors kept for the next frame, which writes them (no allocation a move)
    }
    unsigned framesAtRest() const { return acc.frames; }
    // The least of phase 2's samples a pixel holds since the camera last moved (XPU2's samples: the frame's end).
    double leastSamples() const {
        if (acc.frames == 0) return 0;
        return *std::min_element(acc.nfull.begin(), acc.nfull.end());
    }
    // The last frame's shares: the pixels verified, and those whose phase 1 counted (all layers), and phase 1's pixels
    // by layer: the probes' triangulation (front), the slanted planes, the back plane; the planar regions.
    double verified = 0, trusted = 0, shareFront = 0, sharePlanar = 0, shareBack = 0;
    // The last frame's CPU time in the planes: building and looking up (with the pixels' layers), storing the back plane;
    // and the last store after XPU2's frame at rest.
    double planesSeconds = 0, storeSeconds = 0, restStoreSeconds = 0;
    // The last frame's pruning: the probes it made dormant, those it woke, the dormant ones it saw.
    size_t pruned = 0, woken = 0, dormant = 0;
    size_t regions = 0;
    size_t probes = 0, spawned = 0;
    double fieldSeconds = 0;

    // Frame k's plan: the base plan (its camera current) with Rhea's samples a pixel. moved: the camera differs from the
    // last frame's (the sums start again and the probes' light fades as it is taken in).
    std::shared_ptr<cpu::Plan> prepare(const std::shared_ptr<const cpu::Plan>& base, const async::CpuScene& scene) {
        const cpu::Plan& b = *base;
        W = b.width, H = b.height, N = size_t(W) * H;
        if (field.width && (field.width != W || field.height != H)) reset();
        moved = !haveCamera || !sameCamera(camera, b.camera);
        if (moved) clearSums();
        camera = b.camera, haveCamera = true;
        if (op.probeFull < 0) op.probeFull = b.maxDiffuseDepth > 0 ? 1 : 0;
        nLo = std::min(op.phase2Max, op.probeFull ? 2u : 4u), nHi = std::min(op.phase2Max, op.probeFull ? 16u : 32u);
        if (op.trustedSpp > 0) nLo = std::min(nLo, op.trustedSpp);
        nBg = std::min(op.nBg, op.phase2Max);
        if (!moved && acc.frames > 0) {
            const unsigned grow = std::min(acc.frames, 6u);
            const unsigned cap = std::max(op.phase2Max, std::min(op.restMax, op.phase2Max << grow));
            nLo = nHi = cap;
            nBg = std::min(cap, std::max(1u, op.nBg) << grow);
        }
        outputs = outputsOf(b);
        filterWidth = b.filterWidth;
        auto plan = std::make_shared<cpu::Plan>(b);
        // A moved camera starts each pixel's sequence anew (its own seed); at rest the frames go on with the seed and
        // each pixel's samples past those it holds (Plan::sampleBase), so that the frames' samples stratify together as
        // one frame's would: drawn afresh each frame, they did not, and pixels phase 1 does not take were noisier than
        // XPU2's at the same samples (DESIGN.md 22).
        if (moved) ++moves;
        plan->seed = b.seed + moves * 7919u;
        plan->sampleBase.clear();
        if (!moved && acc.frames > 0) {
            plan->sampleBase.resize(N);
            for (size_t i = 0; i < N; ++i) plan->sampleBase[i] = static_cast<unsigned>(std::min(acc.n[i], 4.0e9));
        }
        field.prepare(*plan, scene, fieldOptions(), frame, f);
        fieldSeconds = f.seconds, probes = f.ids.size(), spawned = f.spawned + f.gapSpawned;
        // Phase 2's samples: the cap's; the sky the last frame met, the background's.
        const unsigned cell = cellNow();
        nCount.assign(N, nHi);
        for (size_t i = 0; i < N; ++i) {
            const int t = f.triOf[i];
            const unsigned x = unsigned(i % W), y = unsigned(i / W);
            if (t >= 0 && !f.triGap[t]) nCount[i] = nLo;
            else if (t < 0 && field.sky[size_t(y / cell) * field.cellsX + x / cell]) nCount[i] = nBg;
            // At rest no pixel takes more than it lacks of the frame's samples (op.target): the last frame of a run
            // doubled its cost for the two samples it lacked (DESIGN.md 23).
            if (!moved && op.target > 0 && acc.frames > 0) {
                const double lacking = double(op.target) - acc.nfull[i];
                nCount[i] = unsigned(std::max(1.0, std::min(double(nCount[i]), std::ceil(lacking))));
            }
        }
        total = nCount;
        // The probes' samples within a budget: at most probeShare of phase 2's, the known probes' keepSpp first, the new
        // (or unlit) ones sharing the rest, never fewer than keepSpp nor more than probeSpp. Unlit, 2,114 probes at 64 had
        // taken 135k of a Sponza frame's 176k samples (DESIGN.md 24).
        size_t fresh = 0, kept = 0;
        for (size_t j = 0; j < f.ids.size(); ++j) (f.fresh[j] ? fresh : kept) += 1;
        double phase2 = 0;
        for (size_t i = 0; i < N; ++i) phase2 += nCount[i];
        const double budget = op.probeShare * phase2 - double(kept) * op.keepSpp;
        const unsigned freshSpp = fresh ? unsigned(std::max(double(op.keepSpp), std::min(double(op.probeSpp), budget / double(fresh)))) : op.probeSpp;
        std::vector<unsigned> extra(N, 0);
        for (size_t j = 0; j < f.ids.size(); ++j) {
            const size_t px = size_t(f.pixel[j]);
            extra[px] = std::max(extra[px], f.fresh[j] ? freshSpp : op.keepSpp);
        }
        for (size_t i = 0; i < N; ++i) total[i] += extra[i];
        // Rhea's samples a pixel, uniform within it: no sampling generations (a sample map is only read without them).
        plan->adaptive = false, plan->sampleBudget = 0;
        // Textures as the card holds them: the coarse levels, and whatever tiles XPU2's frames at rest brought; a camera
        // move's frame streams none and renders nothing again (the user: "the textures on first phase is too heavy, it
        // should just get the average color ... then the textures can stream in once standard XPU2 realtime kicks in").
        plan->residentTextures = op.residentTextures;
        plan->pixelSamples = total;
        plan->fullSamples.clear();
        if (!op.probeFull) plan->fullSamples = nCount;
        plan->spp = *std::max_element(total.begin(), total.end());
        // Gather tiles: the pixels sorted by their samples, 64 to a tile, spread over the frame's tiles.
        const size_t tiles = ((W + 7) / 8) * ((H + 7) / 8);
        // The order by a counting sort, most samples first and each count's pixels in their order (as the stable sort
        // had it): samples a pixel are small numbers, and the sort had been n log n over every pixel.
        std::vector<unsigned> order(N);
        {
            const unsigned most = N ? *std::max_element(total.begin(), total.end()) : 0;
            std::vector<size_t> start(size_t(most) + 2, 0);
            for (size_t i = 0; i < N; ++i) ++start[size_t(most - total[i]) + 1];
            for (size_t k = 1; k < start.size(); ++k) start[k] += start[k - 1];
            for (size_t i = 0; i < N; ++i) order[start[most - total[i]]++] = unsigned(i);
        }
        plan->gather.assign(tiles * 64, ~0u);
        size_t step = 397;
        while (std::gcd(step, tiles) != 1) ++step;
        for (size_t q = 0; q * 64 < N; ++q)
            for (size_t j = 0; j < 64 && q * 64 + j < N; ++j) plan->gather[((q * step) % tiles) * 64 + j] = order[q * 64 + j];
        ++frame;
        return plan;
    }

    // The frame's picture: r (the frame of prepare's plan) made into Rhea's combination and summed with the frames
    // since the camera last moved, as XPU2's result with its rgba, counts and AOV values the sums'.
    void finish(const async::RenderResult& r, async::RenderResult& out) {
        const size_t stride = N ? r.aov.size() / N : 0;
        const RealtimeOptions& o = op;
        direct.resize(N * 4), depthMin.resize(N), depthMax.resize(N), coverage.resize(N);
        const bool demod = o.demod && outputs.albedo >= 0;
        albedo.resize(demod ? N * 3 : 0);
        const unsigned threads = std::max(1u, o.threads);
        // The frame's outputs a pixel each, in parallel (rows); each pixel's coverage, the beauty's alpha: misses leave no
        // depth (ProbeField::verify).
        parallel(threads, H, [&](size_t y) {
            for (size_t i = y * W; i < (y + 1) * W; ++i) {
                const float* av = &r.aov[i * stride];
                for (int c = 0; c < 3; ++c) direct[i * 4 + c] = av[outputs.emission + c] + av[outputs.direct + c];
                direct[i * 4 + 3] = 1;
                if (demod)
                    for (int c = 0; c < 3; ++c) albedo[i * 3 + c] = av[outputs.albedo + c];
                depthMin[i] = av[outputs.depthMin], depthMax[i] = av[outputs.depthMax];
                coverage[i] = o.coverage ? r.rgba[i * 4 + 3] : 1.0f;
            }
        });
        const FieldOptions fo = fieldOptions();
        field.absorb(f, o.probeFull ? r.rgba : direct, demod ? &albedo : nullptr, total, moved, o.fade, o.cleanAbsorb ? &depthMin : nullptr,
                     o.cleanAbsorb ? &depthMax : nullptr, &fo, &coverage);
        field.reconstruct(f, fo, demod ? &albedo : nullptr, recon, wrec, fstate);
        verified = field.verify(f, fo, depthMin, depthMax, ok, &coverage);
        // The probes the triangulation can do without, made dormant for the next frame; dormant ones the reconstruction no
        // longer gives, woken (ProbeField::prune).
        pruned = field.prune(f, fo, demod ? &albedo : nullptr, recon, fstate, woken);
        woken += f.woken, dormant = f.dormantIds.size();
        // The sums since the camera last moved: the beauty and direct light times their samples, the samples (all, and
        // full paths), phase 1's weight and its light times that weight. Phase 1's light is each frame's own where it
        // was used, weighted as it was: the latest reconstruction with the weight of all frames darkened pixels that
        // verified in some frames and not the latest (out of focus, where verification comes and goes), its light
        // there the reconstruction's nothing (DESIGN.md 22).
        // The first frame of a camera (since XPU2 renders the camera at rest, the only one) writes the sums into the
        // vectors the last camera's left; the outputs are kept as the frames' mean in floats (the frame's own for the
        // first), not as sums in doubles (at 720p 110 MB, summed and divided again a frame).
        const bool first = acc.frames == 0;
        if (first) {
            acc.nb.resize(N * 3), acc.nd.resize(N * 3), acc.r1.resize(N * 3);
            acc.n.resize(N), acc.nfull.resize(N), acc.m.resize(N), acc.alpha.resize(N);
            acc.aov = r.aov;
        }
        const double m0 = f.view.kind == View::Directional ? o.m0Directional : o.m0;
        // The virtual planes (planes.h, DESIGN.md 25): the slanted planes from the frame's probes, the back plane as the
        // last picture left it, lifted into this frame. A pixel takes the first layer whose surface its depths hold:
        // the front triangulation (trusted and verified), its surface's slanted plane, the back plane.
        const auto planesBegan = std::chrono::steady_clock::now();
        if (o.planar && f.view.kind != View::Directional) {
            planar.build(f, field.probes, W, H, fo.tol, fo.tauR, fo.demodFloor, o.planarEdge * fo.cell);
            planar.support(f.view, depthMin, depthMax, fo, W, o.planarSupport);
        } else {
            planar.none(W, H);
        }
        if (!o.backPlane) back.clear(), haveBack = false;
        // Looked up from this frame's depths (gather), or each stored point lifted into it (reproject: the first way).
        if (o.backGather) back.gather(f.view, W, H, o.threads, depthMin, 2 * fo.tol + o.backTol, seen);
        else back.reproject(f.view, W, H, o.threads, seen);
        // The pixels' lifted depths (the nearest), for the back plane's reach: a slanted surface's depths change across
        // a pixel, and a point lands anywhere in it.
        std::vector<double> wn(N, 0.0);
        parallel(threads, H, [&](size_t y) {
            for (size_t i = y * W; i < (y + 1) * W; ++i)
                if (std::isfinite(depthMin[i]) && depthMin[i] > 0) wn[i] = f.view.wOf(depthMin[i]);
        });
        layer.assign(N, 0);
        std::vector<float> light1(o.debugFolder.empty() ? 0 : N * 4, 0.0f);  // an investigation: phase 1's light by whichever layer
        std::vector<size_t> usedRows(size_t(H) * 3, 0);
        const bool sumAovs = !first && acc.aov.size() == r.aov.size();
        parallel(threads, H, [&](size_t row) {
          size_t& used = usedRows[row * 3];
          size_t& usedPlanar = usedRows[row * 3 + 1];
          size_t& usedBack = usedRows[row * 3 + 2];
          for (size_t i = row * W; i < (row + 1) * W; ++i) {
            const unsigned x = unsigned(i % W), y = unsigned(row);
            double w1 = 0, L1[3] = {0, 0, 0};
            if (fstate[i] == FieldTrusted && ok[i]) {
                w1 = m0, layer[i] = 1, ++used;
                for (int c = 0; c < 3; ++c) L1[c] = recon[i * 4 + c];
            }
            // A slanted plane only where the probes' triangle failed for its geometry (a gap, the verification, none):
            // one the probes refused for its light (a light edge, a shadow's border) is no plane's either, a plane's
            // larger triangles there having corners that agree across the shadow.
            if (!w1 && planar.triOf[i] >= 0 && fstate[i] != FieldEdge) {
                const Plane* pl = planar.planeAt(x, y, W);
                double L[3];
                if (pl && ProbeField::planeHolds(f.view, *pl, x, y, depthMin[i], depthMax[i], fo) &&
                    planar.lightAt(f, field.probes, x, y, W, demod ? &albedo[i * 3] : nullptr, fo.demodFloor, demod, L)) {
                    w1 = o.planarWeight * m0, layer[i] = 2, ++usedPlanar;
                    for (int c = 0; c < 3; ++c) L1[c] = L[c];
                }
            }
            if (seen.w[i] > 0 && wn[i] > 0) {
                // The back plane: one surface at the pixel (its depths close), the reprojected point on it, and its light
                // demodulated only where the pixel's colour can take it back. Held, it gathers this frame's samples
                // (store), whichever layer the pixel takes.
                const double w0 = wn[i], wf = f.view.wOf(std::max(depthMax[i], depthMin[i]));
                double slope = 0;
                if (x > 0 && x + 1 < W && wn[i - 1] > 0 && wn[i + 1] > 0) slope = std::max(slope, 0.5 * std::fabs(wn[i + 1] - wn[i - 1]));
                if (y > 0 && y + 1 < H && wn[i - W] > 0 && wn[i + W] > 0) slope = std::max(slope, 0.5 * std::fabs(wn[i + W] - wn[i - W]));
                const double reach = w0 * (2 * fo.tol + std::min(o.backTol, slope / w0));
                const bool one = (w0 - wf) <= 2 * fo.tol * w0 && ProbeField::whole(r.rgba[i * 4 + 3]);
                const double bw = seen.w[i];
                const bool pixelDemod = demod && 0.2126 * albedo[i * 3] + 0.7152 * albedo[i * 3 + 1] + 0.0722 * albedo[i * 3 + 2] >= fo.demodFloor;
                seen.held[i] = one && (seen.gathered ? seen.held[i] != 0 : bw >= wf - reach && bw <= w0 + reach);
                if (!w1 && seen.held[i] && (!seen.demod[i] || pixelDemod)) {
                    // Its light the surface's reflected light (reflectedOf), and what the pixel sees emitted this frame.
                    w1 = o.backWeight * std::min(m0, double(seen.weight[i])), layer[i] = 3, ++usedBack;
                    for (int c = 0; c < 3; ++c)
                        L1[c] = std::max(0.0, double(seen.L[i * 3 + c]) * (seen.demod[i] ? albedo[i * 3 + c] : 1.0f)) +
                                (outputs.emission >= 0 ? double(r.aov[i * stride + outputs.emission + c]) : 0.0);
                }
            }
            const double Nt = total[i];
            if (first) {
                for (int c = 0; c < 3; ++c) {
                    acc.nb[i * 3 + c] = Nt * r.rgba[i * 4 + c];
                    acc.nd[i * 3 + c] = Nt * direct[i * 4 + c];
                    acc.r1[i * 3 + c] = w1 > 0 ? w1 * L1[c] : 0.0;
                }
                acc.alpha[i] = Nt * r.rgba[i * 4 + 3];
                acc.n[i] = Nt, acc.nfull[i] = nCount[i], acc.m[i] = w1;
            } else {
                const double before = acc.n[i];
                for (int c = 0; c < 3; ++c) {
                    acc.nb[i * 3 + c] += Nt * r.rgba[i * 4 + c];
                    acc.nd[i * 3 + c] += Nt * direct[i * 4 + c];
                }
                acc.alpha[i] += Nt * r.rgba[i * 4 + 3];
                acc.n[i] += Nt, acc.nfull[i] += nCount[i], acc.m[i] += w1;
                if (w1 > 0)
                    for (int c = 0; c < 3; ++c) acc.r1[i * 3 + c] += w1 * L1[c];
                if (sumAovs && before + Nt > 0)
                    for (size_t c = 0; c < stride; ++c)
                        acc.aov[i * stride + c] = float((before * acc.aov[i * stride + c] + Nt * r.aov[i * stride + c]) / (before + Nt));
            }
            if (!light1.empty())
                for (int c = 0; c < 3; ++c) light1[i * 4 + c] = float(L1[c]);
          }
        });
        size_t used = 0, usedPlanar = 0, usedBack = 0;
        for (size_t row = 0; row < H; ++row) used += usedRows[row * 3], usedPlanar += usedRows[row * 3 + 1], usedBack += usedRows[row * 3 + 2];
        shareFront = N ? double(used) / double(N) : 0, sharePlanar = N ? double(usedPlanar) / double(N) : 0;
        shareBack = N ? double(usedBack) / double(N) : 0, regions = planar.regions;
        trusted = shareFront + sharePlanar + shareBack;
        // A pixel another layer holds asks for no probe: the probes go where no layer holds (the user: "would it be
        // performant if the probes were culled ...").
        if (o.quietNeed && field.cellsX) {
            const unsigned cell = cellNow();
            std::vector<uint8_t> open(field.need.size(), 0);
            for (size_t i = 0; i < N; ++i)
                if (!ok[i] && !layer[i]) open[size_t((i / W) / cell) * field.cellsX + (i % W) / cell] = 1;
            for (size_t c = 0; c < field.need.size(); ++c) field.need[c] = field.need[c] && open[c];
        }
        // The back plane takes this frame's samples, the light it held folded in (faded: the camera has moved).
        const auto storeBegan = std::chrono::steady_clock::now();
        if (o.backPlane) {
            back.store(f.view, W, H, o.threads, reflectedOf(o.probeFull ? r.rgba : direct, r), demod && o.backDemod ? &albedo : nullptr, depthMin,
                       depthMax, total, fo.tol, fo.demodFloor, &seen, moved ? o.fade : 1.0, o.backCap);
            backCamera = camera, haveBack = true;
        }
        planesSeconds = std::chrono::duration<double>(storeBegan - planesBegan).count();
        storeSeconds = secondsSince(storeBegan);
        if (!o.debugFolder.empty()) {
            std::vector<float> mask(N * 4, 1.0f), layers(N * 4, 1.0f);
            for (size_t i = 0; i < N; ++i) {
                const float v = (fstate[i] == FieldTrusted && ok[i]) ? 1.0f : ok[i] ? 0.5f : 0.0f;
                // Red: phase 1 used (1), verified (0.5), neither (0); green: the field's state (none 0, trusted 1/3, a
                // gap 2/3, a light edge 1); blue: phase 2's samples this frame over 64.
                mask[i * 4] = v, mask[i * 4 + 1] = float(fstate[i]) / 3.0f, mask[i * 4 + 2] = float(nCount[i]) / 64.0f;
                // The layer phase 1 came from: red the front, green a slanted plane, blue the back plane.
                layers[i * 4] = layer[i] == 1, layers[i * 4 + 1] = layer[i] == 2, layers[i * 4 + 2] = layer[i] == 3;
            }
            auto put = [&](const char* name, const std::vector<float>& v) {
                std::FILE* fh = std::fopen((o.debugFolder + "/" + name).c_str(), "wb");
                if (fh) std::fwrite(v.data(), sizeof(float), v.size(), fh), std::fclose(fh);
            };
            put("recon.rgba", recon), put("mask.rgba", mask), put("direct.rgba", direct), put("layers.rgba", layers);
            put("light1.rgba", light1);
            // Each Rhea frame's own, kept (frame k: the field's frame count): the layers and their light frame by frame.
            const std::string k = std::to_string(frame);
            put(("layers-" + k + ".rgba").c_str(), layers), put(("light1-" + k + ".rgba").c_str(), light1);
            put(("beauty-" + k + ".rgba").c_str(), r.rgba);
        }
        const unsigned K = ++acc.frames;
        out = r;
        out.rgba.assign(N * 4, 0.0f);
        out.counts.assign(N, 0);
        parallel(threads, H, [&](size_t row) {
          for (size_t i = row * W; i < (row + 1) * W; ++i) {
            const double n = acc.n[i];
            out.counts[i] = static_cast<std::uint32_t>(std::min(n, 4.0e9));
            if (n <= 0) continue;
            const double m = acc.m[i] / K, k = m / (m + n);
            for (int c = 0; c < 3; ++c) {
                const double b = acc.nb[i * 3 + c] / n, d = acc.nd[i * 3 + c] / n, rec = acc.m[i] > 0 ? acc.r1[i * 3 + c] / acc.m[i] : 0.0;
                const double v = o.probeFull ? b + k * (rec - b) : (acc.nb[i * 3 + c] - acc.nd[i * 3 + c]) / std::max(acc.nfull[i], 1.0) + (1 - k) * d + k * rec;
                out.rgba[i * 4 + c] = std::isfinite(v) ? float(v) : 0.0f;
            }
            out.rgba[i * 4 + 3] = float(acc.alpha[i] / n);
            // The outputs: the frame's own where it is the first (out = r), else the frames' mean.
            if (K > 1 && acc.aov.size() == out.aov.size())
                std::copy_n(&acc.aov[i * stride], stride, &out.aov[i * stride]);
          }
        });
    }

    // XPU2 at rest (DESIGN.md 24): Rhea renders the camera's moves, XPU2 the camera at rest.
    // Whether the probes are there, and whether the plan's camera is another than the last frame's (a camera move).
    bool hasProbes() const { return !field.probes.empty(); }
    // The camera as last seen, apart from the probes' (the warp alone, no probes: XPU2_SESSION_RHEA_PROBES=0, the
    // ablation's first step, RESULTS.md 25).
    bool movedSince(const cpu::Plan& b) const {
        return !haveSeen || !sameCamera(seenCamera, b.camera) || seenW != b.width || seenH != b.height;
    }
    // (The picture's size too: with no probes nothing else sets it; prepare resets the probes on a change of size.)
    void see(const cpu::Plan& b) {
        seenCamera = b.camera, haveSeen = true, seenW = b.width, seenH = b.height;
        W = b.width, H = b.height, N = size_t(W) * H;
    }
    bool cameraChanged(const cpu::Plan& b) const {
        return !haveCamera || !sameCamera(camera, b.camera) || field.width != b.width || field.height != b.height;
    }
    // The probes placed for the plan's camera without a frame of Rhea's (a new scene, an edit): lit by XPU2's frame at
    // rest when it is done (absorbRest).
    void place(const std::shared_ptr<const cpu::Plan>& base, const async::CpuScene& scene) { (void)prepare(base, scene); }
    // How much the field holds of an XPU2 frame's light: its probes' summed weight (a test of absorbRest).
    double fieldWeight() const {
        double w = 0;
        for (const auto& p : field.probes) w += p.weight;
        return w;
    }
    // XPU2's frame at rest (x: its film so far, fraction: how far it has come) folded into Rhea's sums: its samples are
    // full paths, its direct light its outputs'. Rhea's part (phase 1 and its own samples) fades as (1 - fraction)^2, so
    // that the frame begins as Rhea's picture and ends as XPU2's own: kept at full weight, Rhea's few even samples
    // stood beside XPU2's in pixels its generations had left early, and the frame ended a little noisier than XPU2's.
    void merge(const async::RenderResult& x, double fraction, async::RenderResult& out) const {
        out = x;
        if (acc.frames == 0 || x.rgba.size() != N * 4 || N == 0) return;
        const size_t stride = x.aov.size() / N;
        const bool aovs = stride > 0 && outputs.emission >= 0 && outputs.direct >= 0;
        const unsigned K = std::max(1u, acc.frames);
        const double fade = std::pow(std::max(0.0, 1.0 - fraction), 2.0);
        out.rgba.assign(N * 4, 0.0f);
        out.counts.assign(N, 0);
        for (size_t i = 0; i < N; ++i) {
            const double c = i < x.counts.size() ? double(x.counts[i]) : 0.0;
            const float* av = aovs ? &x.aov[i * stride] : nullptr;
            const double s = c > 0 ? fade : 1.0;  // Rhea's part's weight: whole where XPU2 has nothing yet
            const double n = s * acc.n[i] + c, nfull = s * acc.nfull[i] + c;
            out.counts[i] = static_cast<std::uint32_t>(std::min(n, 4.0e9));
            if (n <= 0) continue;
            const double m = acc.m[i] / K * s, k = m / (m + n);
            for (int ch = 0; ch < 3; ++ch) {
                const double bx = x.rgba[i * 4 + ch], dx = av ? double(av[outputs.emission + ch]) + av[outputs.direct + ch] : bx;
                const double nb = s * acc.nb[i * 3 + ch] + c * bx, nd = s * acc.nd[i * 3 + ch] + c * dx;
                const double rec = acc.m[i] > 0 ? acc.r1[i * 3 + ch] / acc.m[i] : 0.0;
                const double v = op.probeFull ? nb / n + k * (rec - nb / n) : (nb - nd) / std::max(nfull, 1.0) + (1 - k) * nd / n + k * rec;
                out.rgba[i * 4 + ch] = std::isfinite(v) ? float(v) : 0.0f;
            }
            out.rgba[i * 4 + 3] = float((s * acc.alpha[i] + c * x.rgba[i * 4 + 3]) / n);
            if (acc.aov.size() == x.aov.size())
                for (size_t ch = 0; ch < stride; ++ch)
                    out.aov[i * stride + ch] = float((s * acc.n[i] * acc.aov[i * stride + ch] + c * x.aov[i * stride + ch]) / n);
        }
    }
    // The probes take the light of XPU2's frame at rest (its samples a pixel their weight, as a frame of Rhea's): the next
    // camera move begins with probes lit by many samples, at no cost of the GPU's.
    void absorbRest(const async::RenderResult& x) {
        if (f.ids.empty() || x.rgba.size() != N * 4 || x.counts.size() != N || N == 0) return;
        const size_t stride = x.aov.size() / N;
        if (!stride || outputs.emission < 0 || outputs.direct < 0 || outputs.depthMin < 0 || outputs.depthMax < 0) return;
        const bool demod = op.demod && outputs.albedo >= 0;
        std::vector<float> d(N * 4, 1.0f), a(demod ? N * 3 : 0, 0.0f), dmin(N), dmax(N);
        std::vector<unsigned> samples(N);
        for (size_t i = 0; i < N; ++i) {
            const float* av = &x.aov[i * stride];
            for (int c = 0; c < 3; ++c) d[i * 4 + c] = av[outputs.emission + c] + av[outputs.direct + c];
            if (demod)
                for (int c = 0; c < 3; ++c) a[i * 3 + c] = av[outputs.albedo + c];
            dmin[i] = av[outputs.depthMin], dmax[i] = av[outputs.depthMax];
            samples[i] = x.counts[i];
        }
        const FieldOptions fo = fieldOptions();
        field.absorb(f, op.probeFull ? x.rgba : d, demod ? &a : nullptr, samples, false, op.fade, op.cleanAbsorb ? &dmin : nullptr,
                     op.cleanAbsorb ? &dmax : nullptr, &fo);
        // The back plane takes XPU2's frame too: the camera unmoved since Rhea's frame, its points stay where they are and
        // XPU2's samples fold into them (a frame stopped early keeps the pixels it never reached).
        const auto restBegan = std::chrono::steady_clock::now();
        if (op.backPlane) {
            BackPlane::Seen same;
            const bool unmoved = haveBack && sameCamera(backCamera, camera);
            if (unmoved) back.asSeen(same);
            back.store(f.view, W, H, op.threads, reflectedOf(op.probeFull ? x.rgba : d, x), demod && op.backDemod ? &a : nullptr, dmin, dmax, samples,
                       fo.tol, fo.demodFloor, unmoved ? &same : nullptr, 1.0, op.backCap);
            backCamera = camera, haveBack = true;
        }
        restStoreSeconds = secondsSince(restBegan);
    }
    // A picture's light (four a pixel) less what its pixels see emitted (the emission output: lights seen directly and
    // emissive surfaces), for the back plane: a light seen in front of a wall has no depth of its own (the depth outputs
    // are the wall's), and kept as the wall's light it went with the wall on a move, a white blob where the light no
    // longer was (Sponza, DESIGN.md 25). The frame that uses the back plane adds its own pixels' emission.
    std::vector<float> reflectedOf(const std::vector<float>& light, const async::RenderResult& r) const {
        std::vector<float> out(light);
        const size_t stride = N ? r.aov.size() / N : 0;
        if (!stride || outputs.emission < 0 || light.size() != N * 4) return out;
        parallel(std::max(1u, op.threads), H, [&](size_t y) {
            for (size_t i = y * W; i < (y + 1) * W; ++i)
                for (int c = 0; c < 3; ++c) out[i * 4 + c] = std::max(0.0f, light[i * 4 + c] - r.aov[i * stride + outputs.emission + c]);
        });
        return out;
    }
    // A camera move's first picture (DESIGN.md 26, 28): the last picture rendered (keepShown) moved into the plan's
    // camera - as a mesh gradient (warpMesh: mesh_warp.h), else each pixel lifted by its depth and the nearest kept, the
    // holes a move opens filled from the farthest neighbour, three passes; its outputs moved with it (each pixel's from
    // the picture's pixel nearest its place in the mesh). False where there is no picture to move (a new scene,
    // an edit, another size), the camera is a lens camera's (spherical, fisheye, dome: each pixel's lift a search), or the
    // warp is off.
    const async::RenderResult* warpTo(const cpu::Plan& b) { return warpInto(b, warpPicture) ? &warpPicture : nullptr; }
    bool warpInto(const cpu::Plan& b, async::RenderResult& out) {
        warped.valid = false, objectDrawn = false;
        warped.screen.rgba.clear(), warped.screen.aov.clear(), warped.screen.counts.clear();
        if (!op.warp || !last.valid || last.W != b.width || last.H != b.height || last.view.kind == View::Directional) return false;
        View nv;
        if (!nv.init(b.camera, b.width, b.height) || nv.kind == View::Directional) return false;
        if (nv.needsDepthScale()) nv.setDepthScale(last.view.depthScale());
        const unsigned w = b.width, h = b.height, threads = std::max(1u, op.threads);
        const size_t n = size_t(w) * h;
        const size_t stride = last.result.aov.size() / n;
        if (op.objectSpace && traceScene && !store.empty() && nv.kind != View::Directional) return objectInto(b, nv, out, stride);
        // The mesh gradient (mesh_warp.h), built from the picture when it was kept; else pixel by pixel.
        bool meshed = false;
        if (op.warpMesh && mesh.valid()) {
            if (!mesh.warp(nv, warped.color, warped.w, warped.depth, warped.from, warped.state, &warped.doubt)) return false;
            meshed = true;
        }
        warped.meshed = meshed;
        if (!meshed) {
            std::vector<long long>& at = warped.scratchAt;
            std::vector<double>& lw = warped.scratchW;
            std::vector<float>& ld = warped.scratchD;
            at.assign(n, -1), lw.resize(n), ld.resize(n);
            parallel(threads, h, [&](size_t y) {
                for (unsigned x = 0; x < w; ++x) {
                    const size_t i = y * w + x;
                    const float d = last.depth[i];
                    if (!(d > 0)) continue;
                    surface::V3 p;
                    if (!last.view.pointAt(x + 0.5, y + 0.5, d, p)) continue;
                    double px, py, ww;
                    if (!nv.lift(p, px, py, ww) || !(px >= 0 && py >= 0 && px < w && py < h) || !(ww > 0)) continue;
                    at[i] = (long long)(size_t(py) * w + size_t(px)), lw[i] = ww, ld[i] = float(nv.depthOf(nv.camera(p)));
                }
            });
            warped.w.assign(n, -1.0), warped.depth.assign(n, 0.0f), warped.state.assign(n, 0), warped.from.assign(n, -1);
            for (size_t i = 0; i < n; ++i) {
                if (at[i] < 0) continue;
                const size_t t = size_t(at[i]);
                if (lw[i] <= warped.w[t]) continue;
                warped.w[t] = lw[i], warped.depth[t] = ld[i], warped.state[t] = 1, warped.from[t] = (long long)i;
            }
            // The holes: a pixel's farthest landed (or filled) neighbour, three passes; a pass reads only what the passes
            // before it set (their state), so that it writes in place.
            std::vector<uint8_t>& before = warped.scratchState;
            for (int pass = 0; pass < 3; ++pass) {
                before = warped.state;
                parallel(threads, h, [&](size_t y) {
                    for (unsigned x = 0; x < w; ++x) {
                        const size_t i = y * w + x;
                        if (before[i]) continue;
                        long long best = -1;
                        for (int dy = -1; dy <= 1; ++dy)
                            for (int dx = -1; dx <= 1; ++dx) {
                                const int xx = int(x) + dx, yy = int(y) + dy;
                                if ((!dx && !dy) || xx < 0 || yy < 0 || xx >= int(w) || yy >= int(h)) continue;
                                const size_t j = size_t(yy) * w + size_t(xx);
                                if (before[j] && (best < 0 || warped.w[j] < warped.w[size_t(best)])) best = (long long)j;
                            }
                        if (best < 0) continue;
                        const size_t j = size_t(best);
                        warped.state[i] = 2, warped.w[i] = warped.w[j], warped.depth[i] = warped.depth[j], warped.from[i] = warped.from[j];
                    }
                });
            }
            warped.color.assign(n * 3, 0.0f);
            for (size_t i = 0; i < n; ++i)
                if (warped.from[i] >= 0)
                    for (int c = 0; c < 3; ++c) warped.color[i * 3 + c] = last.result.rgba[size_t(warped.from[i]) * 4 + c];
        }
        // The picture: the last one's pixels where they came to, its outputs with them, its depth outputs the new view's
        // (the warped points', so that a picture made of it can be moved again). Only what a picture shows: its colour,
        // samples and outputs.
        const RealtimeOutputs o = outputsOf(b);
        // Its vectors kept from move to move (no allocation, no page faults: at 720p a picture and its outputs are 70 MB).
        out.cancelled = out.drained = out.failed = false;
        out.rgba.resize(n * 4), out.aov.resize(n * stride), out.counts.resize(n);
        parallel(threads, h, [&](size_t y) {
            for (unsigned x = 0; x < w; ++x) {
                const size_t i = y * w + x;
                const long long s = warped.from[i];
                if (s < 0) {
                    std::fill_n(&out.rgba[i * 4], 4, 0.0f);
                    if (stride) std::fill_n(&out.aov[i * stride], stride, 0.0f);
                    out.counts[i] = 0;
                    continue;
                }
                std::copy_n(&warped.color[i * 3], 3, &out.rgba[i * 4]);
                out.rgba[i * 4 + 3] = last.result.rgba[size_t(s) * 4 + 3];
                if (stride) {
                    std::copy_n(&last.result.aov[size_t(s) * stride], stride, &out.aov[i * stride]);
                    if (warped.w[i] > 0) {
                        if (o.depthMin >= 0) out.aov[i * stride + size_t(o.depthMin)] = warped.depth[i];
                        if (o.depthMax >= 0) out.aov[i * stride + size_t(o.depthMax)] = warped.depth[i];
                    }
                }
                out.counts[i] = 1;
            }
        });
        size_t landed = 0;
        for (size_t i = 0; i < n; ++i) landed += warped.state[i] == 1;
        warped.stride = stride, warped.view = nv, warped.outputs = o;
        warped.valid = true;
        warpShare = n ? double(landed) / double(n) : 0;
        return true;
    }
    // A move's picture from the colours on the surfaces (objectSpace, object_warp.h): the CPU scene's first hits through
    // the new camera, coloured from the store, streamed to onStage (the coarse grid's picture, then each ring's). Its
    // outputs: none but its depths (the warp's), its alpha whole where a surface is.
    bool objectInto(const cpu::Plan& b, const View& nv, async::RenderResult& out, size_t stride) {
        const unsigned w = b.width, h = b.height, threads = std::max(1u, op.threads);
        const size_t n = size_t(w) * h;
        const RealtimeOutputs o = outputsOf(b);
        ObjectWarp::Options& wo = objectWarp.op;
        wo.rays = op.objectRays, wo.jump = op.warpJump;
        wo.rings = op.objectRings, wo.threads = threads, wo.antialias = op.objectAntialias;
        out.cancelled = out.drained = out.failed = false;
        out.rgba.resize(n * 4), out.aov.assign(n * stride, 0.0f), out.counts.assign(n, 1u);
        auto fill = [&] {
            parallel(threads, h, [&](size_t y) {
                for (size_t i = y * w; i < (y + 1) * w; ++i) {
                    std::copy_n(&warped.color[i * 3], 3, &out.rgba[i * 4]);
                    const float d = warped.depth[i];
                    out.rgba[i * 4 + 3] = d > 0 ? 1.0f : 0.0f;
                    if (stride) {
                        if (o.depthMin >= 0) out.aov[i * stride + size_t(o.depthMin)] = d;
                        if (o.depthMax >= 0) out.aov[i * stride + size_t(o.depthMax)] = d;
                    }
                }
            });
        };
        warped.stride = stride, warped.view = nv, warped.outputs = o, warped.meshed = false;
        warped.from.assign(n, -1);
        std::function<bool()> stage;
        if (onStage) stage = [&] {
            fill();
            return onStage(out);
        };
        if (!objectWarp.draw(nv, *traceScene, store, w, h, warped.color, warped.w, warped.depth, warped.state, warped.doubt, stage)) return false;
        objectDrawn = true;
        fill();
        size_t landed = 0;
        for (size_t i = 0; i < n; ++i) landed += warped.state[i] == 1;
        warped.valid = true;
        warpShare = n ? double(landed) / double(n) : 0;
        return true;
    }
    // XPU2's picture of the camera's move (x, fraction: how far its frame has come) with the warp folded in: where its
    // samples' depths hold the warped point (the nearest within the reach), the warp counts as warpWeight samples (a
    // filled hole a quarter) fading as (1 - fraction)^2; where it has no samples yet, the warp alone; elsewhere XPU2's.
    // Returns the share of the pixels XPU2's samples have reached (1 where there is no warp to fold in).
    double mergeWarp(const async::RenderResult& x, double fraction, async::RenderResult& out) const {
        out = x;
        const size_t n = size_t(W) * H;
        if (!warped.valid || !last.valid || x.rgba.size() != n * 4 || warped.state.size() != n || last.result.rgba.size() != n * 4 ||
            warped.color.size() != n * 3)
            return 1.0;
        std::vector<size_t> reached(H, 0);
        const size_t stride = n ? x.aov.size() / n : 0;
        const int dmin = warped.outputs.depthMin, dmax = warped.outputs.depthMax;
        const double fade = std::pow(std::max(0.0, 1.0 - fraction), 2.0);
        // A mesh's depths are its cells' planes, not the surface's own (a wave, a dragon's scales): XPU2's samples agree
        // with it within three depth jumps (it took XPU2's lone samples for another surface: dark specks on the sea).
        const double reach = warped.meshed ? std::max(2 * op.tol + op.backTol, 3 * op.warpJump) : 2 * op.tol + op.backTol;
        const bool sameAovs = stride == warped.stride && last.result.aov.size() == n * stride;
        parallel(std::max(1u, op.threads), H, [&](size_t y) {
            for (unsigned px = 0; px < W; ++px) {
                const size_t i = y * W + px;
                const uint8_t st = warped.state[i];
                if (!st) {
                    if (i < x.counts.size() && x.counts[i] > 0) ++reached[y];
                    continue;
                }
                const size_t s = size_t(warped.from[i]);
                const float* wc = &warped.color[i * 3];
                const double c = i < x.counts.size() ? double(x.counts[i]) : 0.0;
                if (c <= 0) {
                    std::copy_n(wc, 3, &out.rgba[i * 4]);
                    out.rgba[i * 4 + 3] = last.result.rgba[s * 4 + 3];
                    // A pixel the warp shows: no gap (the session's denoiser filled "gaps" from XPU2's few samples around,
                    // the warp thrown away: the blocks in the user's video).
                    if (i < out.counts.size()) out.counts[i] = 1;
                    if (sameAovs && stride) {
                        std::copy_n(&last.result.aov[s * stride], stride, &out.aov[i * stride]);
                        if (warped.w[i] > 0) {
                            if (dmin >= 0) out.aov[i * stride + size_t(dmin)] = warped.depth[i];
                            if (dmax >= 0) out.aov[i * stride + size_t(dmax)] = warped.depth[i];
                        }
                    }
                    continue;
                }
                ++reached[y];
                if (dmin < 0 || stride == 0) continue;
                const double d = x.aov[i * stride + size_t(dmin)];
                if (!(std::isfinite(d) && d > 0)) continue;
                const double wx = warped.view.wOf(d);
                if (!(std::fabs(warped.w[i] - wx) <= reach * wx)) continue;
                const double m = op.warpWeight * (st == 1 ? 1.0 : 0.25) * fade, k = m / (m + c);
                for (int ch = 0; ch < 3; ++ch) out.rgba[i * 4 + ch] = float(x.rgba[i * 4 + ch] + k * (wc[ch] - x.rgba[i * 4 + ch]));
            }
        });
        size_t all = 0;
        for (size_t r : reached) all += r;
        return n ? double(all) / double(n) : 1.0;
    }
    bool hasWarp() const { return warped.valid; }
    // The completion fade (DESIGN.md 29): XPU2's frame after a move finishes its seed region by region, the regions where
    // the warp is likely worst first. The regions: the picture's cells (cellSize pixels a side, the work grid's), ranked by
    // the warp's doubt over them (a pixel the fill made counts 1; an edge or detail averaged away, up to 1), split into
    // count regions of as many cells each; each 8-pixel tile given its cell's region (tileBatch, the image's tile order).
    // False where there is no warp.
    bool warpRegions(unsigned count, unsigned cellSize, std::vector<std::uint16_t>& tileBatch) const {
        const size_t n = size_t(W) * H;
        if (!warped.valid || !count || !cellSize || warped.state.size() != n) return false;
        const unsigned cx = (W + cellSize - 1) / cellSize, cy = (H + cellSize - 1) / cellSize;
        std::vector<std::pair<double, unsigned>> cells(size_t(cx) * cy);
        for (unsigned j = 0; j < cy; ++j)
            for (unsigned i = 0; i < cx; ++i) {
                double sum = 0;
                size_t m = 0;
                for (unsigned y = j * cellSize; y < std::min(H, (j + 1) * cellSize); ++y)
                    for (unsigned x = i * cellSize; x < std::min(W, (i + 1) * cellSize); ++x, ++m) {
                        const size_t p = size_t(y) * W + x;
                        sum += warped.state[p] != 1 ? 1.0 : (warped.doubt.size() == n ? double(warped.doubt[p]) : 0.0);
                    }
                cells[size_t(j) * cx + i] = {m ? sum / double(m) : 0.0, j * cx + i};
            }
        std::stable_sort(cells.begin(), cells.end(), [](const auto& a, const auto& b) { return a.first > b.first; });
        std::vector<std::uint16_t> cellBatch(cells.size());
        const unsigned regionsWanted = std::min<unsigned>(count, unsigned(cells.size()));
        for (size_t r = 0; r < cells.size(); ++r) cellBatch[cells[r].second] = std::uint16_t(r * regionsWanted / cells.size());
        const unsigned tx = (W + 7) / 8, ty = (H + 7) / 8, per = cellSize / 8;
        tileBatch.assign(size_t(tx) * ty, 0);
        for (unsigned j = 0; j < ty; ++j)
            for (unsigned i = 0; i < tx; ++i) tileBatch[size_t(j) * tx + i] = cellBatch[size_t(j / per) * cx + i / per];
        return true;
    }
    // XPU2's picture (x) over the warp by each pixel's alpha (its finished region's fade, feathered: 0 the warp, 1 XPU2's
    // own): the warp's colour and outputs where alpha is 0 (no gap there), XPU2's where it is 1, the colours blended
    // between. Returns the share of pixels wholly XPU2's.
    double completeWarp(const async::RenderResult& x, const std::vector<float>& alpha, async::RenderResult& out) const {
        out = x;
        const size_t n = size_t(W) * H;
        // From what was on screen (screenAsWarp, screenWarp): its alpha and outputs, pixel for pixel; else the warp's, from
        // the last picture kept.
        const async::RenderResult& screen = warped.screen;
        const bool fromScreen = screen.rgba.size() == n * 4;
        if (!warped.valid || x.rgba.size() != n * 4 || alpha.size() != n || warped.color.size() != n * 3) return 1.0;
        if (!fromScreen && (!last.valid || last.result.rgba.size() != n * 4)) return 1.0;
        const size_t stride = n ? x.aov.size() / n : 0;
        const int dmin = warped.outputs.depthMin, dmax = warped.outputs.depthMax;
        const bool sameAovs = last.valid && stride == warped.stride && last.result.aov.size() == n * stride;
        const bool screenAovs = fromScreen && stride && screen.aov.size() == n * stride;
        if (out.counts.size() != n) out.counts.assign(n, 0);
        std::vector<size_t> whole(H, 0);
        parallel(std::max(1u, op.threads), H, [&](size_t y) {
            for (unsigned px = 0; px < W; ++px) {
                const size_t i = y * W + px;
                const bool sampled = i < x.counts.size() && x.counts[i] > 0;
                const double a = sampled ? std::clamp(double(alpha[i]), 0.0, 1.0) : 0.0;
                if (a >= 1.0) {
                    ++whole[y];
                    continue;
                }
                const long long s = warped.from[i];
                const float* wc = &warped.color[i * 3];
                for (int ch = 0; ch < 3; ++ch) out.rgba[i * 4 + ch] = float(wc[ch] + a * (double(x.rgba[i * 4 + ch]) - wc[ch]));
                if (fromScreen) {
                    if (a < 0.5) {
                        out.rgba[i * 4 + 3] = screen.rgba[i * 4 + 3];
                        if (screenAovs) std::copy_n(&screen.aov[i * stride], stride, &out.aov[i * stride]);
                    }
                } else if (a < 0.5 && s >= 0) {
                    out.rgba[i * 4 + 3] = last.result.rgba[size_t(s) * 4 + 3];
                    if (sameAovs && stride) {
                        std::copy_n(&last.result.aov[size_t(s) * stride], stride, &out.aov[i * stride]);
                        if (warped.w[i] > 0) {
                            if (dmin >= 0) out.aov[i * stride + size_t(dmin)] = warped.depth[i];
                            if (dmax >= 0) out.aov[i * stride + size_t(dmax)] = warped.depth[i];
                        }
                    }
                }
                out.counts[i] = std::max<std::uint32_t>(out.counts[i], 1u);
            }
        });
        size_t all = 0;
        for (size_t r : whole) all += r;
        return n ? double(all) / double(n) : 1.0;
    }
    // The pictures the session publishes, the last kept for the next move's warp (keepLast): the warp's own (it is
    // Realtime's), or another taken by swapping its vectors (the session's merged pictures, which it no longer needs).
    void publishedWarp() { lastKind = 1; }
    // coverage: the share of its pixels XPU2's (or Rhea's) samples reached (mergeWarp's).
    void published(async::RenderResult&& r, double coverage = 1.0) {
        shownCopy.rgba.swap(r.rgba), shownCopy.counts.swap(r.counts), shownCopy.aov.swap(r.aov);
        lastKind = 2, shownCoverage = coverage;
    }
    void publishedCopy(const async::RenderResult& r) {
        shownCopy.rgba = r.rgba, shownCopy.counts = r.counts, shownCopy.aov = r.aov;
        lastKind = 2, shownCoverage = 1.0;
    }
    // The last picture published becomes the next move's source (its vectors swapped in, the old ones kept for reuse).
    void keepLast(const cpu::Plan& b) {
        async::RenderResult& from = lastKind == 1 ? warpPicture : shownCopy;
        if (!lastKind) {
            last.valid = false;
            return;
        }
        // A warp, or a picture XPU2's samples had not yet covered: the source stays the last picture rendered.
        if (!op.warpChain && last.valid && (lastKind == 1 || shownCoverage < op.warpKeepCoverage)) {
            lastKind = 0;
            return;
        }
        last.result.rgba.swap(from.rgba), last.result.counts.swap(from.counts), last.result.aov.swap(from.aov);
        lastKind = 0;
        depthsOf(b);
    }
    void dropWarp() { warped.valid = false; }
    // What a frame left on screen (the session's last picture of it, for its camera), kept through an edit's reset: a frame
    // with nothing to warp (an edit, the kit telling of the scene again) fades XPU2's frame in over it (screenWarp) rather
    // than showing XPU2's first pictures, black where its samples have not reached (the user's video, 2026-11-22).
    void keepScreen(const cpu::Plan& b, const async::RenderResult& r) {
        const size_t n = size_t(b.width) * b.height;
        if (r.rgba.size() != n * 4) return;
        keptScreen.picture.rgba = r.rgba, keptScreen.picture.counts = r.counts, keptScreen.picture.aov = r.aov;
        keptScreen.camera = b.camera, keptScreen.w = b.width, keptScreen.h = b.height, keptScreen.valid = true;
    }
    // The last picture published as what is on screen (a frame stopped): the warp's, or the last other one.
    void keepScreenPublished(const cpu::Plan& b) {
        if (lastKind == 1) keepScreen(b, warpPicture);
        else if (lastKind == 2) keepScreen(b, shownCopy);
    }
    // The kept screen as this frame's warp, where it is of this camera and size: true where it is.
    bool screenWarp(const cpu::Plan& b) {
        const size_t n = size_t(b.width) * b.height;
        if (!keptScreen.valid || keptScreen.w != b.width || keptScreen.h != b.height || !sameCamera(keptScreen.camera, b.camera) || keptScreen.picture.rgba.size() != n * 4) return false;
        View nv;
        if (!nv.init(b.camera, b.width, b.height)) return false;
        W = b.width, H = b.height, N = n;
        const RealtimeOutputs o = outputsOf(b);
        const size_t stride = keptScreen.picture.aov.size() / n;
        warped.color.resize(n * 3), warped.w.assign(n, -1.0), warped.depth.assign(n, 0.0f), warped.state.assign(n, 1);
        warped.from.assign(n, -1), warped.doubt.assign(n, 0.5f);
        for (size_t i = 0; i < n; ++i) {
            for (int c = 0; c < 3; ++c) warped.color[i * 3 + c] = keptScreen.picture.rgba[i * 4 + c];
            const float d = stride && o.depthMin >= 0 ? keptScreen.picture.aov[i * stride + size_t(o.depthMin)] : 0.0f;
            if (d > 0 && std::isfinite(d)) warped.depth[i] = d, warped.w[i] = nv.wOf(d);
        }
        warped.screen = keptScreen.picture;
        warped.stride = stride, warped.view = nv, warped.outputs = o, warped.meshed = false;
        objectDrawn = false;
        warped.valid = true;
        return true;
    }
    // A frame stopped with more than the warp on screen (XPU2's pictures faded in over it): that picture, for the same
    // camera, becomes the next frame's starting point (the mouse let go: Modo tells of the camera where the drag left it,
    // a frame with no move, whose fade starts from what is on screen). Before keepLast, which may take shownCopy's vectors.
    void screenAsWarp() {
        const size_t n = size_t(W) * H;
        if (!warped.valid || lastKind != 2 || shownCopy.rgba.size() != n * 4 || warped.color.size() != n * 3) return;
        warped.screen.rgba = shownCopy.rgba, warped.screen.counts = shownCopy.counts, warped.screen.aov = shownCopy.aov;
        parallel(std::max(1u, op.threads), H, [&](size_t y) {
            for (size_t i = y * W; i < (y + 1) * W; ++i)
                for (int c = 0; c < 3; ++c) warped.color[i * 3 + c] = shownCopy.rgba[i * 4 + c];
        });
    }
    double warpShare = 0;  // the last warp's pixels that landed (not filled)
    // The last picture shown, kept for the next camera move's warp, its depths its own nearest first-hit depth output
    // (XPU2's where its samples reached, Rhea's frame's, or the warp's own: warpTo writes the new view's). A frame a move
    // stops gives no picture of its own: the session keeps the last it published.
    void keepShown(const cpu::Plan& b, const async::RenderResult& shown, double coverage = 1.0) {
        // Mostly a warp (XPU2's samples short of warpKeepCoverage of it): the source stays the last picture rendered.
        if (!op.warpChain && last.valid && warped.valid && coverage < op.warpKeepCoverage) {
            lastKind = 0;
            return;
        }
        last.valid = false;
        const size_t n = size_t(b.width) * b.height;
        if (!op.warp || shown.rgba.size() != n * 4) return;
        // Only what a picture shows (its colour, samples and outputs), into the vectors it had (no allocation a move).
        last.result.rgba = shown.rgba, last.result.counts = shown.counts, last.result.aov = shown.aov;
        lastKind = 0;
        depthsOf(b);
    }
    // The kept picture's depths (its nearest first-hit depth output) and view.
    void depthsOf(const cpu::Plan& b) {
        last.valid = false;
        const size_t n = size_t(b.width) * b.height;
        const RealtimeOutputs o = outputsOf(b);
        const size_t stride = n ? last.result.aov.size() / n : 0;
        if (!op.warp || last.result.rgba.size() != n * 4 || o.depthMin < 0 || !stride || !last.view.init(b.camera, b.width, b.height)) return;
        if (last.view.needsDepthScale()) {
            // The probes' scale; without probes (XPU2_SESSION_RHEA_PROBES=0), twice the picture's farthest depth.
            double K = f.view.kind == View::Orthographic ? f.view.depthScale() : 0.0;
            if (!(K > 0)) {
                double farthest = 0;
                for (size_t i = 0; i < n; ++i) {
                    const float d = last.result.aov[i * stride + size_t(o.depthMin)];
                    if (std::isfinite(d) && d > farthest) farthest = d;
                }
                K = 2.0 * std::max(1.0, farthest);
            }
            last.view.setDepthScale(K);
        }
        last.W = b.width, last.H = b.height;
        last.depth.resize(n);
        // The farthest first-hit depth too (the mesh's silhouette pixels: nearest and farthest a jump apart).
        if (o.depthMax >= 0) last.depthFar.resize(n);
        else last.depthFar.clear();
        parallel(std::max(1u, op.threads), b.height, [&](size_t y) {
            for (size_t i = y * b.width; i < (y + 1) * b.width; ++i) {
                const float d = last.result.aov[i * stride + size_t(o.depthMin)];
                last.depth[i] = std::isfinite(d) && d > 0 ? d : 0.0f;
                if (o.depthMax >= 0) {
                    const float f = last.result.aov[i * stride + size_t(o.depthMax)];
                    last.depthFar[i] = std::isfinite(f) && f > 0 ? f : 0.0f;
                }
            }
        });
        last.valid = true;
        mesh.clear();
        if (op.objectSpace) {
            store.op.scale = op.storeScale, store.op.jump = op.warpJump, store.op.threads = std::max(1u, op.threads);
            store.op.grazing = op.storeGrazing, store.op.albedo = op.storeAlbedo;
            ObjectStore::Outputs outs;
            outs.aov = &last.result.aov, outs.stride = stride, outs.albedo = o.albedo, outs.emission = o.emission;
            store.add(last.view, b.width, b.height, last.result.rgba, last.result.counts, last.depth, last.depthFar, &outs);
        } else if (op.warpMesh) {
            mesh.op.cell = op.warpCell, mesh.op.jump = op.warpJump, mesh.op.soft = op.warpSoft, mesh.op.threads = std::max(1u, op.threads);
            mesh.build(last.view, b.width, b.height, last.result.rgba, last.result.counts, last.depth, last.depthFar);
        }
    }
    // The warp's mesh (vertices, triangles, seconds to build and to draw, the share its triangles drew).
    const MeshWarp& warpMeshInfo() const { return mesh; }

    // The back plane's pixels (a share of the picture): what the next camera move can lift.
    double backShare() const {
        if (back.valid.empty()) return 0;
        size_t n = 0;
        for (uint8_t v : back.valid) n += v;
        return double(n) / double(back.valid.size());
    }

private:
    struct Sums {
        std::vector<double> nb, nd, n, nfull, m, alpha, r1;
        std::vector<float> aov;  // the frames' outputs, their mean by samples (the first frame's own)
        unsigned frames = 0;
    };
    ProbeField field;
    FieldFrame f;
    Sums acc;
    PlanarLayer planar;
    BackPlane back;
    // The last picture shown (keepShown) and its warp into the current camera (warpTo).
    struct Shown {
        View view;
        unsigned W = 0, H = 0;
        async::RenderResult result;
        std::vector<float> depth;     // a pixel's nearest first-hit depth (0 none)
        std::vector<float> depthFar;  // its farthest (empty: no such output)
        bool valid = false;
    };
    struct Warped {
        View view;
        std::vector<double> w;          // the warped point's lifted depth (-1 none)
        std::vector<float> depth;       // its depth (the depth outputs' measure)
        std::vector<uint8_t> state;     // 0 none, 1 landed, 2 a hole filled from a neighbour
        std::vector<long long> from;    // the last picture's pixel its outputs are read from
        std::vector<float> color;       // its colour (rgb)
        bool meshed = false;            // drawn from the mesh (mesh_warp.h)
        std::vector<float> doubt;       // how far the mesh is likely off (0 to 1; what the fill made, 1; empty: pixel by pixel)
        // What was on screen for this camera when a frame stopped past the warp (screenAsWarp): the next frame's fade
        // starts from it (colour above, alpha and outputs here) instead of the warp. Empty: the warp's own.
        async::RenderResult screen;
        size_t stride = 0;
        RealtimeOutputs outputs;
        bool valid = false;
        std::vector<long long> scratchAt;  // kept between moves: no allocation a move
        std::vector<double> scratchW;
        std::vector<float> scratchD;
        std::vector<uint8_t> scratchState;
    };
    Shown last;
    Warped warped;
    async::RenderResult warpPicture, shownCopy;  // the warp's picture and the last other one published, kept for reuse
    int lastKind = 0;                            // the last published: 0 none kept, 1 the warp's, 2 shownCopy
    double shownCoverage = 1.0;                  // shownCopy's share of pixels XPU2's samples reached
    MeshWarp mesh;                               // the kept picture's mesh (warpMesh)
public:
    // The colours on the surfaces (objectSpace), and the drawing of a view from them; the scene its rays meet (the
    // session's CPU scene for the plan the move renders: null, no such picture), and what to do with each of its streamed
    // pictures (false: stop, the next move has come).
    ObjectStore store;
    ObjectWarp objectWarp;
    const async::CpuScene* traceScene = nullptr;
    std::function<bool(const async::RenderResult&)> onStage;
    bool objectDrawn = false;  // the last warp was drawn from the store
    struct KeptScreen {
        async::RenderResult picture;
        surface::Camera camera{};
        unsigned w = 0, h = 0;
        bool valid = false;
    } keptScreen;  // keepScreen
    // Whether the last warp was drawn to its end (a stream the next move stopped was not).
    bool warpComplete() const { return !objectDrawn || objectWarp.stages > objectWarp.op.rings; }
private:
    // The probes' screen cell for the picture (cellsByPicture).
    unsigned cellNow() const {
        const unsigned c = std::max(2u, op.cell);
        if (!op.cellsByPicture || !W || !H) return c;
        const double s = std::sqrt(double(W) * double(H) / (320.0 * 240.0));
        return std::max(c, unsigned(std::lround(double(c) * s)));
    }
    BackPlane::Seen seen;
    std::vector<uint8_t> layer;  // the layer each pixel's phase 1 came from: 0 none, 1 the front, 2 a slanted plane, 3 the back plane
    surface::Camera camera{}, backCamera{}, seenCamera{};
    bool haveCamera = false, moved = true, haveBack = false, haveSeen = false;
    unsigned seenW = 0, seenH = 0;
    unsigned frame = 0, moves = 0, W = 0, H = 0, nLo = 2, nHi = 2, nBg = 1;
    float filterWidth = 1.0f;
    size_t N = 0;
    RealtimeOutputs outputs;
    std::vector<unsigned> nCount, total;
    std::vector<float> direct, albedo, depthMin, depthMax, recon, wrec, coverage;
    std::vector<uint8_t> fstate, ok;

    FieldOptions fieldOptions() const {
        FieldOptions fo;
        fo.cell = cellNow(), fo.gapPasses = op.gapPasses, fo.tol = op.tol;
        fo.footprint = 0.5 * std::max(1.0, double(filterWidth)), fo.tauR = op.tauR, fo.demod = op.demod, fo.threads = op.threads;
        fo.slant = op.slant, fo.planeLight = op.planeLight, fo.prune = op.prune;
        return fo;
    }
    // The same picture's camera: its place, projection, lens and the settings of its kind (a focus or a fisheye's field of
    // view changed is a moved camera: the sums start again).
    static bool sameCamera(const surface::Camera& a, const surface::Camera& b) {
        for (int i = 0; i < 4; ++i)
            for (int j = 0; j < 4; ++j)
                if (a.cameraToRender.m[i][j] != b.cameraToRender.m[i][j] || a.rasterToCamera.m[i][j] != b.rasterToCamera.m[i][j]) return false;
        if (a.type != b.type || a.dof != b.dof || a.lensRadius != b.lensRadius || a.focusDistance != b.focusDistance || a.bokeh != b.bokeh ||
            a.bokehSides != b.bokehSides || a.bokehAngle != b.bokehAngle || a.flags != b.flags || a.mode != b.mode || a.motion != b.motion ||
            a.regionX != b.regionX || a.regionY != b.regionY || a.nearClip != b.nearClip || a.farClip != b.farClip)
            return false;
        for (int k = 0; k < 12; ++k)
            if (a.k[k] != b.k[k]) return false;
        return true;
    }
};

}  // namespace rhea
