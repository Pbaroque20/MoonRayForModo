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
#include <cstdio>
#include <numeric>
#include <string>

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
        // A moved camera starts each pixel's sequence anew (its own seed); at rest the frames go on with the seed and
        // each pixel's samples past those it holds (Plan::sampleBase), so that the frames' samples stratify together as
        // one frame's would: drawn afresh each frame, they did not, and pixels phase 1 does not take were noisier than
        // XPU2's at the same samples (DESIGN.md 22).
        if (moved) ++moves;
        plan->seed = b.seed + moves * 7919u;
        plan->sampleBase.clear();
        if (!moved && !acc.n.empty()) {
            plan->sampleBase.resize(N);
            for (size_t i = 0; i < N; ++i) plan->sampleBase[i] = static_cast<unsigned>(std::min(acc.n[i], 4.0e9));
        }
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
            // At rest no pixel takes more than it lacks of the frame's samples (op.target): the last frame of a run
            // doubled its cost for the two samples it lacked (DESIGN.md 23).
            if (!moved && op.target > 0 && !acc.nfull.empty()) {
                const double lacking = double(op.target) - acc.nfull[i];
                nCount[i] = unsigned(std::max(1.0, std::min(double(nCount[i]), std::ceil(lacking))));
            }
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
        // Each pixel's coverage, the beauty's alpha: misses leave no depth (ProbeField::verify).
        coverage.assign(N, 1.0f);
        for (size_t i = 0; i < N; ++i) coverage[i] = o.coverage ? r.rgba[i * 4 + 3] : 1.0f;
        field.absorb(f, o.probeFull ? r.rgba : direct, demod ? &albedo : nullptr, total, moved, o.fade, o.cleanAbsorb ? &depthMin : nullptr,
                     o.cleanAbsorb ? &depthMax : nullptr, &fo, &coverage);
        field.reconstruct(f, fo, demod ? &albedo : nullptr, recon, wrec, fstate);
        verified = field.verify(f, fo, depthMin, depthMax, ok, &coverage);
        // The sums since the camera last moved: the beauty and direct light times their samples, the samples (all, and
        // full paths), phase 1's weight and its light times that weight. Phase 1's light is each frame's own where it
        // was used, weighted as it was: the latest reconstruction with the weight of all frames darkened pixels that
        // verified in some frames and not the latest (out of focus, where verification comes and goes), its light
        // there the reconstruction's nothing (DESIGN.md 22).
        if (acc.nb.empty()) {
            acc.nb.assign(N * 3, 0.0), acc.nd.assign(N * 3, 0.0);
            acc.n.assign(N, 0.0), acc.nfull.assign(N, 0.0), acc.m.assign(N, 0.0), acc.alpha.assign(N, 0.0), acc.r1.assign(N * 3, 0.0);
            acc.aov.assign(r.aov.size(), 0.0);
        }
        size_t used = 0;
        const double m0 = f.view.kind == View::Directional ? o.m0Directional : o.m0;
        for (size_t i = 0; i < N; ++i) {
            const bool use = fstate[i] == FieldTrusted && ok[i];
            used += use;
            const double Nt = total[i];
            for (int c = 0; c < 3; ++c) {
                acc.nb[i * 3 + c] += Nt * r.rgba[i * 4 + c];
                acc.nd[i * 3 + c] += Nt * direct[i * 4 + c];
            }
            acc.alpha[i] += Nt * r.rgba[i * 4 + 3];
            acc.n[i] += Nt, acc.nfull[i] += nCount[i], acc.m[i] += use ? m0 : 0.0;
            if (use)
                for (int c = 0; c < 3; ++c) acc.r1[i * 3 + c] += m0 * recon[i * 4 + c];
            if (acc.aov.size() == r.aov.size())
                for (size_t c = 0; c < stride; ++c) acc.aov[i * stride + c] += Nt * r.aov[i * stride + c];
        }
        trusted = N ? double(used) / double(N) : 0;
        if (!o.debugFolder.empty()) {
            std::vector<float> mask(N * 4, 1.0f);
            for (size_t i = 0; i < N; ++i) {
                const float v = (fstate[i] == FieldTrusted && ok[i]) ? 1.0f : ok[i] ? 0.5f : 0.0f;
                // Red: phase 1 used (1), verified (0.5), neither (0); green: the field's state (none 0, trusted 1/3, a
                // gap 2/3, a light edge 1); blue: phase 2's samples this frame over 64.
                mask[i * 4] = v, mask[i * 4 + 1] = float(fstate[i]) / 3.0f, mask[i * 4 + 2] = float(nCount[i]) / 64.0f;
            }
            auto put = [&](const char* name, const std::vector<float>& v) {
                std::FILE* fh = std::fopen((o.debugFolder + "/" + name).c_str(), "wb");
                if (fh) std::fwrite(v.data(), sizeof(float), v.size(), fh), std::fclose(fh);
            };
            put("recon.rgba", recon), put("mask.rgba", mask), put("direct.rgba", direct);
        }
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
                const double b = acc.nb[i * 3 + c] / n, d = acc.nd[i * 3 + c] / n, rec = acc.m[i] > 0 ? acc.r1[i * 3 + c] / acc.m[i] : 0.0;
                const double v = o.probeFull ? b + k * (rec - b) : (acc.nb[i * 3 + c] - acc.nd[i * 3 + c]) / std::max(acc.nfull[i], 1.0) + (1 - k) * d + k * rec;
                out.rgba[i * 4 + c] = std::isfinite(v) ? float(v) : 0.0f;
            }
            out.rgba[i * 4 + 3] = float(acc.alpha[i] / n);
            if (acc.aov.size() == out.aov.size())
                for (size_t c = 0; c < stride; ++c) out.aov[i * stride + c] = float(acc.aov[i * stride + c] / n);
        }
    }

    // XPU2 at rest (DESIGN.md 24): Rhea renders the camera's moves, XPU2 the camera at rest.
    // Whether the probes are there, and whether the plan's camera is another than the last frame's (a camera move).
    bool hasProbes() const { return !field.probes.empty(); }
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
        if (acc.n.empty() || x.rgba.size() != N * 4 || N == 0) return;
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
                for (size_t ch = 0; ch < stride; ++ch) out.aov[i * stride + ch] = float((s * acc.aov[i * stride + ch] + c * x.aov[i * stride + ch]) / n);
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
    }

private:
    struct Sums {
        std::vector<double> nb, nd, n, nfull, m, alpha, aov, r1;
        unsigned frames = 0;
    };
    ProbeField field;
    FieldFrame f;
    Sums acc;
    surface::Camera camera{};
    bool haveCamera = false, moved = true;
    unsigned frame = 0, moves = 0, W = 0, H = 0, nLo = 2, nHi = 2, nBg = 1;
    float filterWidth = 1.0f;
    size_t N = 0;
    RealtimeOutputs outputs;
    std::vector<unsigned> nCount, total;
    std::vector<float> direct, albedo, depthMin, depthMax, recon, wrec, coverage;
    std::vector<uint8_t> fstate, ok;

    FieldOptions fieldOptions() const {
        FieldOptions fo;
        fo.cell = std::max(2u, op.cell), fo.gapPasses = op.gapPasses, fo.tol = op.tol;
        fo.footprint = 0.5 * std::max(1.0, double(filterWidth)), fo.tauR = op.tauR, fo.demod = op.demod, fo.threads = op.threads;
        fo.slant = op.slant, fo.planeLight = op.planeLight;
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
