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
#include "async_render.h"
#include <numeric>

namespace rhea {

namespace async = xpu2::interactive::async;

struct RealtimeOptions {
    unsigned phase2Max = 2;   // phase 2's samples a pixel a frame, at most (DESIGN.md 17)
    unsigned probeSpp = 64;   // a new probe's pixel's samples
    unsigned keepSpp = 4;     // a known probe's pixel's samples a frame
    unsigned nBg = 1;         // the sky's samples a frame
    // At rest phase 2's samples a frame double each frame (the cap's, twice, four times... up to restMax): the sums are
    // XPU2's samples, and longer frames spend less on each frame's fixed costs, so the picture converges at XPU2's pace.
    unsigned restMax = 32;
    unsigned cell = 8, gapPasses = 2;
    double m0 = 32;           // phase 1 counts as this many samples (accumulated: not growing, DESIGN.md 18)
    double tauR = 0.25, tol = 0.002, fade = 0.95;
    bool demod = true, cleanAbsorb = true;
    int probeFull = -1;       // -1: whole-light probes where the scene bounces diffusely
    unsigned threads = 4;     // the CPU's part (the field)
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
    if (plan.camera.type != surface::CameraPerspective) return "not a perspective camera";
    if (plan.camera.dof) return "depth of field";
    if (plan.camera.motion) return "motion blur";
    if (!outputsOf(plan).complete()) return "the scene lacks Rhea's outputs";
    Frame f;
    if (!f.init(plan.camera)) return "the camera's frame";
    return "";
}

// The state of one realtime view: the field of probes, and the sums of the frames since the camera last moved.
class Realtime {
public:
    RealtimeOptions op;

    // Everything forgotten: an edit to the scene (anything but the camera alone), or a new scene.
    void reset() {
        field = ProbeField{};
        frame = 0;
        clearSums();
        haveCamera = false;
    }
    // The picture's sums forgotten, the probes kept: the camera has moved.
    void clearSums() {
        acc = Sums{};
    }
    unsigned framesAtRest() const { return acc.frames; }
    // The least of phase 2's samples a pixel holds since the camera last moved (XPU2's samples: the frame's end).
    double leastSamples() const {
        if (acc.nfull.empty()) return 0;
        return *std::min_element(acc.nfull.begin(), acc.nfull.end());
    }
    // The last frame's shares: the pixels verified, and those whose phase 1 counted.
    double verified = 0, trusted = 0;
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
        plan->seed = b.seed + frame * 7919u;
        field.prepare(*plan, scene, fieldOptions(), frame, f);
        fieldSeconds = f.seconds, probes = f.ids.size(), spawned = f.spawned + f.gapSpawned;
        // Phase 2's samples: the cap's; the sky the last frame met, the background's.
        const unsigned cell = std::max(2u, op.cell);
        nCount.assign(N, nHi);
        for (size_t i = 0; i < N; ++i) {
            const int t = f.triOf[i];
            const unsigned x = unsigned(i % W), y = unsigned(i / W);
            if (t >= 0 && !f.triGap[t]) nCount[i] = nLo;
            else if (t < 0 && field.sky[size_t(y / cell) * field.cellsX + x / cell]) nCount[i] = nBg;
        }
        total = nCount;
        std::vector<unsigned> extra(N, 0);
        for (size_t j = 0; j < f.ids.size(); ++j) {
            const size_t px = size_t(f.pixel[j]);
            extra[px] = std::max(extra[px], f.fresh[j] ? op.probeSpp : op.keepSpp);
        }
        for (size_t i = 0; i < N; ++i) total[i] += extra[i];
        // Rhea's samples a pixel, uniform within it: no sampling generations (a sample map is only read without them).
        plan->adaptive = false, plan->sampleBudget = 0;
        plan->pixelSamples = total;
        plan->fullSamples.clear();
        if (!op.probeFull) plan->fullSamples = nCount;
        plan->spp = *std::max_element(total.begin(), total.end());
        // Gather tiles: the pixels sorted by their samples, 64 to a tile, spread over the frame's tiles.
        const size_t tiles = ((W + 7) / 8) * ((H + 7) / 8);
        std::vector<unsigned> order(N);
        std::iota(order.begin(), order.end(), 0u);
        std::stable_sort(order.begin(), order.end(), [&](unsigned a, unsigned c) { return total[a] > total[c]; });
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
        direct.assign(N * 4, 0.0f), depthMin.assign(N, 0.0f), depthMax.assign(N, 0.0f);
        const bool demod = o.demod && outputs.albedo >= 0;
        albedo.assign(demod ? N * 3 : 0, 0.0f);
        for (size_t i = 0; i < N; ++i) {
            const float* av = &r.aov[i * stride];
            for (int c = 0; c < 3; ++c) direct[i * 4 + c] = av[outputs.emission + c] + av[outputs.direct + c];
            direct[i * 4 + 3] = 1;
            if (demod)
                for (int c = 0; c < 3; ++c) albedo[i * 3 + c] = av[outputs.albedo + c];
            depthMin[i] = av[outputs.depthMin], depthMax[i] = av[outputs.depthMax];
        }
        const FieldOptions fo = fieldOptions();
        field.absorb(f, o.probeFull ? r.rgba : direct, demod ? &albedo : nullptr, total, moved, o.fade, o.cleanAbsorb ? &depthMin : nullptr,
                     o.cleanAbsorb ? &depthMax : nullptr, &fo);
        field.reconstruct(f, fo, demod ? &albedo : nullptr, recon, wrec, fstate);
        verified = field.verify(f, fo, depthMin, depthMax, ok);
        // The sums since the camera last moved: the beauty and direct light times their samples, the samples (all, and
        // full paths), phase 1's weight; the reconstruction is the latest (its probes' sums hold the frames before).
        if (acc.nb.empty()) {
            acc.nb.assign(N * 3, 0.0), acc.nd.assign(N * 3, 0.0);
            acc.n.assign(N, 0.0), acc.nfull.assign(N, 0.0), acc.m.assign(N, 0.0), acc.alpha.assign(N, 0.0);
            acc.aov.assign(r.aov.size(), 0.0);
        }
        size_t used = 0;
        for (size_t i = 0; i < N; ++i) {
            const bool use = fstate[i] == FieldTrusted && ok[i];
            used += use;
            const double Nt = total[i];
            for (int c = 0; c < 3; ++c) {
                acc.nb[i * 3 + c] += Nt * r.rgba[i * 4 + c];
                acc.nd[i * 3 + c] += Nt * direct[i * 4 + c];
            }
            acc.alpha[i] += Nt * r.rgba[i * 4 + 3];
            acc.n[i] += Nt, acc.nfull[i] += nCount[i], acc.m[i] += use ? o.m0 : 0.0;
            if (acc.aov.size() == r.aov.size())
                for (size_t c = 0; c < stride; ++c) acc.aov[i * stride + c] += Nt * r.aov[i * stride + c];
        }
        trusted = N ? double(used) / double(N) : 0;
        const unsigned K = ++acc.frames;
        out = r;
        out.rgba.assign(N * 4, 0.0f);
        out.counts.assign(N, 0);
        for (size_t i = 0; i < N; ++i) {
            const double n = acc.n[i];
            out.counts[i] = static_cast<std::uint32_t>(std::min(n, 4.0e9));
            if (n <= 0) continue;
            const double m = acc.m[i] / K, k = m / (m + n);
            for (int c = 0; c < 3; ++c) {
                const double b = acc.nb[i * 3 + c] / n, d = acc.nd[i * 3 + c] / n, rec = recon[i * 4 + c];
                const double v = o.probeFull ? b + k * (rec - b) : (acc.nb[i * 3 + c] - acc.nd[i * 3 + c]) / std::max(acc.nfull[i], 1.0) + (1 - k) * d + k * rec;
                out.rgba[i * 4 + c] = std::isfinite(v) ? float(v) : 0.0f;
            }
            out.rgba[i * 4 + 3] = float(acc.alpha[i] / n);
            if (acc.aov.size() == out.aov.size())
                for (size_t c = 0; c < stride; ++c) out.aov[i * stride + c] = float(acc.aov[i * stride + c] / n);
        }
    }

private:
    struct Sums {
        std::vector<double> nb, nd, n, nfull, m, alpha, aov;
        unsigned frames = 0;
    };
    ProbeField field;
    FieldFrame f;
    Sums acc;
    surface::Camera camera{};
    bool haveCamera = false, moved = true;
    unsigned frame = 0, W = 0, H = 0, nLo = 2, nHi = 2, nBg = 1;
    float filterWidth = 1.0f;
    size_t N = 0;
    RealtimeOutputs outputs;
    std::vector<unsigned> nCount, total;
    std::vector<float> direct, albedo, depthMin, depthMax, recon, wrec;
    std::vector<uint8_t> fstate, ok;

    FieldOptions fieldOptions() const {
        FieldOptions fo;
        fo.cell = std::max(2u, op.cell), fo.gapPasses = op.gapPasses, fo.tol = op.tol;
        fo.footprint = 0.5 * std::max(1.0, double(filterWidth)), fo.tauR = op.tauR, fo.demod = op.demod, fo.threads = op.threads;
        return fo;
    }
    static bool sameCamera(const surface::Camera& a, const surface::Camera& b) {
        for (int i = 0; i < 4; ++i)
            for (int j = 0; j < 4; ++j)
                if (a.cameraToRender.m[i][j] != b.cameraToRender.m[i][j] || a.rasterToCamera.m[i][j] != b.rasterToCamera.m[i][j]) return false;
        return true;
    }
};

}  // namespace rhea
