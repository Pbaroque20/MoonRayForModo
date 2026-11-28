// Rhea's drag pictures from colours kept on the surfaces (rhea/DESIGN.md 30).
//
// The mesh gradient (mesh_warp.h, DESIGN.md 28) interpolates the last picture's colours in screen space: a turn to look
// behind the model shows what that picture never held (gaps, filled from around them), a surface seen edge on stretches
// its triangles into spikes, and its cost grows with the picture's edges (the user's dragon, 2026-11-22: "it struggles
// to drag because it's geometrically complex"). Here the colours live on the surfaces instead (the user: "it would be
// better if the interpolations are object-space, so that there aren't any gaps when the user tries to look behind the
// model").
//
// ObjectStore: every picture XPU2 finishes (each kept as the warp's source) adds its colours to cells on the surfaces it
// shows - a sparse hash of cubes in trace space, each a few of that picture's pixels wide, kept at four sizes, by the side
// they face (the six directions) - weighted by the pixel's samples. Pictures from other views add to it: the far side of
// the model is there once some picture has shown it. A pixel at a silhouette (two surfaces, or the environment, in it) adds
// nothing; the environment's pixels add to a map of directions.
//
// ObjectWarp: a view drawn from the store. The CPU lane's own scene (Embree) gives each ray its first hit, on the meshes
// as they are, whatever the last picture held; the hit's colour is the store's at that point, interpolated between its
// cells (trilinear), a coarser size where the finer has none. Rays go out on a grid, sparser the more the picture holds
// (a budget of rays), and between them the colours are interpolated (bilinear) where the four corners are one smooth
// surface; a cell they are not (a silhouette, a crease) takes a ray every pixel. What no picture has shown yet is filled
// from the grid around it (its doubt 1: XPU2's completion fade takes those regions first). A radial vignette (the fine
// grid in the middle alone, a coarse one outside) came first; with the cells along grazing surfaces the whole picture was
// clean and cheap enough (the user, 2026-11-22: "much cleaner, we can remove vignette").
//
// Streamed (the user: "the reconstructions should be streamed. the user should be able to see the radial topology
// updating in realtime"): a grid four times sparser first, blurred, over all of it, then the fine grid ring by ring from
// the centre out (rings of equal area, so of about equal time), each shown as it lands; the next move stops it where it is.
#pragma once
#include "view.h"
#include "virtual_surface.h"
#include "async_cpu.h"
#include "rhea_store_core.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <unordered_map>
#include <vector>

namespace rhea {

namespace async = xpu2::interactive::async;

// The weighted pull-push of a grid (Gortler and others, The Lumigraph, 1996): rgb and a weight (0 to 1) a texel. The
// weights' averages go up level by level (a parent's weight its children's, at most whole); coming back down, a texel short
// of a whole weight takes the rest from the coarser level's estimate, interpolated (bilinear): a smooth colour interpolation
// from the texels that hold their colour, where copying the coarser texel made blocks of its size (the user, 2026-11-22:
// the "splotchy backgrounds").
// pullPush taking depth into account (the user, 2026-11-22: "do the depth-aware fill"; the Bregman divergence of Rhea's
// research, its lifted inverse depth): z is each texel's lifted inverse depth (> 0, the surface there; 0 none). A texel
// short of colour takes it from the coarser level's texels about it weighed by how near their colour's depth is to its
// own (relative, exp(-(d / sigma)^2)): a tyre's colour no longer runs onto the floor beside it, nor a wall's onto the
// object before it. Where none near in depth holds colour, the plain weights (pullPush's), so nothing is left unfilled.
// Each coarser texel carries the depth of the colour it holds (its known texels', averaged by their weight) and the
// depth of its region's surface (every texel's with a depth, for one that held no colour and was filled).
// ids (DESIGN.md 38): each texel's object (0 none); a texel short of colour then takes it from texels of its own object
// first (each coarser texel carrying the object most of its colour's weight came from), others weighing a fiftieth.
inline void pullPushDepth(std::vector<float>& c, const std::vector<float>& z, unsigned w, unsigned h, double sigma,
                          const std::vector<std::uint32_t>* ids = nullptr) {
    struct Level {
        unsigned w, h;
        std::vector<float> m;      // rgb, weight
        std::vector<float> zc, zg;  // the colour's depth, the surface's depth (0: none)
        std::vector<std::uint32_t> ic, ig;  // the colour's object, the surface's (ids)
    };
    const bool objects = ids && ids->size() == size_t(w) * h;
    std::vector<Level> lv;
    lv.push_back({w, h, c, z, z, {}, {}});
    if (objects) {
        lv[0].ig = *ids;
        lv[0].ic.assign(ids->size(), 0u);
        for (size_t i = 0; i < ids->size(); ++i)
            if (c[i * 4 + 3] > 0) lv[0].ic[i] = (*ids)[i];
    }
    while (lv.back().w > 1 || lv.back().h > 1) {
        const Level& f = lv.back();
        Level q{std::max(1u, (f.w + 1) / 2), std::max(1u, (f.h + 1) / 2), {}, {}, {}, {}, {}};
        const size_t qn = size_t(q.w) * q.h;
        q.m.assign(qn * 4, 0.0f), q.zc.assign(qn, 0.0f), q.zg.assign(qn, 0.0f);
        std::vector<float> zcw(qn, 0.0f), zgn(qn, 0.0f), icw(objects ? qn : 0, 0.0f);
        if (objects) q.ic.assign(qn, 0u), q.ig.assign(qn, 0u);
        for (unsigned y = 0; y < f.h; ++y)
            for (unsigned x = 0; x < f.w; ++x) {
                const size_t fi = size_t(y) * f.w + x, qi = size_t(y / 2) * q.w + x / 2;
                if (f.zg[fi] > 0) q.zg[qi] += f.zg[fi], zgn[qi] += 1.0f;
                if (objects && !q.ig[qi]) q.ig[qi] = f.ig[fi];
                const float* s = &f.m[fi * 4];
                if (!(s[3] > 0)) continue;
                if (objects && f.ic[fi] && s[3] > icw[qi]) q.ic[qi] = f.ic[fi], icw[qi] = s[3];
                float* d = &q.m[qi * 4];
                for (int k = 0; k < 3; ++k) d[k] += s[k] * s[3];
                d[3] += s[3];
                if (f.zc[fi] > 0) q.zc[qi] += f.zc[fi] * s[3], zcw[qi] += s[3];
            }
        for (size_t i = 0; i < qn; ++i) {
            float* d = &q.m[i * 4];
            if (d[3] > 0)
                for (int k = 0; k < 3; ++k) d[k] /= d[3];
            d[3] = std::min(1.0f, d[3]);
            q.zc[i] = zcw[i] > 0 ? q.zc[i] / zcw[i] : 0.0f;
            q.zg[i] = zgn[i] > 0 ? q.zg[i] / zgn[i] : 0.0f;
        }
        lv.push_back(std::move(q));
    }
    if (lv.back().m[3] > 0) lv.back().m[3] = 1.0f;
    const double inv = sigma > 0 ? 1.0 / sigma : 0.0;
    auto near = [&](float a, float b) {
        if (!(a > 0) || !(b > 0) || !(inv > 0)) return 1.0;
        const double d = std::fabs(double(a) - b) / std::max(a, b) * inv;
        return std::exp(-d * d);
    };
    for (size_t k = lv.size() - 1; k-- > 0;) {
        Level& f = lv[k];
        const Level& q = lv[k + 1];
        for (unsigned y = 0; y < f.h; ++y)
            for (unsigned x = 0; x < f.w; ++x) {
                const size_t fi = size_t(y) * f.w + x;
                float* d = &f.m[fi * 4];
                if (d[3] >= 1.0f) continue;
                const double qx = std::clamp((x + 0.5) * 0.5 - 0.5, 0.0, double(q.w - 1)), qy = std::clamp((y + 0.5) * 0.5 - 0.5, 0.0, double(q.h - 1));
                const unsigned x0 = unsigned(qx), y0 = unsigned(qy), x1 = std::min(x0 + 1, q.w - 1), y1 = std::min(y0 + 1, q.h - 1);
                const double tx = qx - x0, ty = qy - y0;
                const double wt[4] = {(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty};
                const size_t at[4] = {size_t(y0) * q.w + x0, size_t(y0) * q.w + x1, size_t(y1) * q.w + x0, size_t(y1) * q.w + x1};
                const float own = f.zg[fi];
                const std::uint32_t ownObj = objects ? f.ig[fi] : 0u;
                double up[3] = {0, 0, 0}, sw = 0, plain[3] = {0, 0, 0}, pw = 0;
                for (int j = 0; j < 4; ++j) {
                    const float* s = &q.m[at[j] * 4];
                    const double a = wt[j] * s[3];
                    if (!(a > 0)) continue;
                    const double b = a * near(own, q.zc[at[j]]) * (ownObj && q.ic[at[j]] && q.ic[at[j]] != ownObj ? 0.02 : 1.0);
                    for (int ch = 0; ch < 3; ++ch) plain[ch] += a * s[ch], up[ch] += b * s[ch];
                    pw += a, sw += b;
                }
                if (!(pw > 0)) continue;
                // Near in depth where any is (a hundredth of the plain weight at least), else the plain fill.
                const bool deep = sw > 1e-2 * pw;
                const double own3 = std::max(0.0f, d[3]);
                for (int ch = 0; ch < 3; ++ch) d[ch] = float(own3 * d[ch] + (1.0 - own3) * (deep ? up[ch] / sw : plain[ch] / pw));
                d[3] = 1.0f;
                // Its colour is now its own surface's.
                if (!(f.zc[fi] > 0)) f.zc[fi] = own;
                if (objects && ownObj) f.ic[fi] = ownObj;
            }
    }
    c.swap(lv.front().m);
}

// The uniform cubic B-spline's four weights at t in [0, 1] (the nodes at -1, 0, 1, 2): smooth to the second derivative,
// a blur and an interpolation in one.
inline void cubicBSpline(double t, double wt[4]) {
    const double t2 = t * t, t3 = t2 * t, u = 1.0 - t;
    wt[0] = u * u * u / 6.0;
    wt[1] = (3.0 * t3 - 6.0 * t2 + 4.0) / 6.0;
    wt[2] = (-3.0 * t3 + 3.0 * t2 + 3.0 * t + 1.0) / 6.0;
    wt[3] = t3 / 6.0;
}

inline void pullPush(std::vector<float>& c, unsigned w, unsigned h) {
    struct Level {
        unsigned w, h;
        std::vector<float> m;
    };
    std::vector<Level> lv;
    lv.push_back({w, h, c});
    while (lv.back().w > 1 || lv.back().h > 1) {
        const Level& f = lv.back();
        Level q{std::max(1u, (f.w + 1) / 2), std::max(1u, (f.h + 1) / 2), {}};
        q.m.assign(size_t(q.w) * q.h * 4, 0.0f);
        for (unsigned y = 0; y < f.h; ++y)
            for (unsigned x = 0; x < f.w; ++x) {
                const float* s = &f.m[(size_t(y) * f.w + x) * 4];
                if (!(s[3] > 0)) continue;
                float* d = &q.m[(size_t(y / 2) * q.w + x / 2) * 4];
                for (int k = 0; k < 3; ++k) d[k] += s[k] * s[3];
                d[3] += s[3];
            }
        for (size_t i = 0; i < size_t(q.w) * q.h; ++i) {
            float* d = &q.m[i * 4];
            if (d[3] > 0)
                for (int k = 0; k < 3; ++k) d[k] /= d[3];
            d[3] = std::min(1.0f, d[3]);
        }
        lv.push_back(std::move(q));
    }
    // The coarsest: whatever it holds, whole (nothing coarser to take the rest from).
    if (lv.back().m[3] > 0) lv.back().m[3] = 1.0f;
    for (size_t k = lv.size() - 1; k-- > 0;) {
        Level& f = lv[k];
        const Level& q = lv[k + 1];
        for (unsigned y = 0; y < f.h; ++y)
            for (unsigned x = 0; x < f.w; ++x) {
                float* d = &f.m[(size_t(y) * f.w + x) * 4];
                if (d[3] >= 1.0f) continue;
                // The coarser level at this texel's centre, bilinear between the texels that hold anything.
                const double qx = std::clamp((x + 0.5) * 0.5 - 0.5, 0.0, double(q.w - 1)), qy = std::clamp((y + 0.5) * 0.5 - 0.5, 0.0, double(q.h - 1));
                const unsigned x0 = unsigned(qx), y0 = unsigned(qy), x1 = std::min(x0 + 1, q.w - 1), y1 = std::min(y0 + 1, q.h - 1);
                const double tx = qx - x0, ty = qy - y0;
                const double wt[4] = {(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty};
                const float* s[4] = {&q.m[(size_t(y0) * q.w + x0) * 4], &q.m[(size_t(y0) * q.w + x1) * 4], &q.m[(size_t(y1) * q.w + x0) * 4],
                                     &q.m[(size_t(y1) * q.w + x1) * 4]};
                double up[3] = {0, 0, 0}, sw = 0;
                for (int j = 0; j < 4; ++j) {
                    const double a = wt[j] * s[j][3];
                    if (!(a > 0)) continue;
                    for (int ch = 0; ch < 3; ++ch) up[ch] += a * s[j][ch];
                    sw += a;
                }
                if (!(sw > 0)) continue;
                const double own = std::max(0.0f, d[3]);
                for (int ch = 0; ch < 3; ++ch) d[ch] = float(own * d[ch] + (1.0 - own) * up[ch] / sw);
                d[3] = 1.0f;
            }
    }
    c.swap(lv[0].m);
}

class ObjectStore {
public:
    struct Options {
        double scale = 2;       // a finest cell's side, in pixels of the picture that adds to it (along its surface)
        int levels = 4;         // the sizes kept: the finest and three, each twice the one before
        double jump = 0.03;     // a neighbour whose depth differs by more (relative) is another surface
        double grazing = 8;     // a surface seen edge on: a pixel's length along it counted at most this many times its width
        // The light and the albedo apart (the user, 2026-11-22: "re-use those buffers, like z-depth and albedo, with a
        // composite to get cleaner first phases"): each cell holds the picture's colour, albedo and emission, cells half as
        // wide its albedo alone; a hit's colour is the fine albedo times the cell's light (its colour less emission over
        // its albedo), its emission added back. Off: the colour as it was.
        bool albedo = false;
        size_t maxCells = size_t(1) << 22;  // past this the store starts again from the next picture
        unsigned threads = 8;
        // Cells of one object each (DESIGN.md 38; XPU2_SESSION_RHEA_STORE_OBJECTS): a pixel's object from its first hit, so
        // that a tyre's colour and the floor's under it never share a cell. Needs Outputs::extra.
        bool byObject = false;
        // The sparse radiance cache (DESIGN.md 43; XPU2_SESSION_RHEA_SPARSE): each cell keeps, beside its means, how its
        // light changes across it (a least-squares slope from its pixels' places: Hermite, first-order records), and a
        // lookup reads a cell as its mean plus that slope times the way to the point, so a few cells interpolate as a
        // gradient; and a pixel is added from the coarsest size down, a finer cell made for it only where the coarser one
        // (of sparseMinWeight at least) does not foresee its light within sparseTolerance (relative): fine cells where the
        // light changes (shadows' edges, highlights), coarse ones where it is smooth. Cells there already keep learning.
        bool sparse = false;
        double sparseTolerance = 0.08, sparseMinWeight = 2.0;
    };
    // What a learning picture's pixel adds besides its outputs (Realtime::learn, from its own first hit): its object, and
    // the light reflected toward it along the mirror direction (where known: the store's colour where the reflected ray
    // met a surface, the environment's where it left the scene).
    struct PixelExtra {
        float reflected[3] = {0, 0, 0};
        std::uint32_t obj = 0;
        bool reflectedKnown = false;
    };
    // A picture's outputs for the composite: its AOV values, a pixel's count of them, and where the first hit's albedo,
    // the light emitted at it and the light reflected diffusely there are among them (-1: none).
    struct Outputs {
        const std::vector<float>* aov = nullptr;
        size_t stride = 0;
        int albedo = -1, emission = -1, diffuse = -1;
        const std::vector<PixelExtra>* extra = nullptr;  // a pixel each, or none
        // Into cells this many sizes coarser than its pixels' (a picture of a sample or two a pixel: rheaLearnAhead's;
        // its noise averaged over more of them).
        int coarser = 0;
        // Each pixel's weight scaled by this (a pixel each; none: 1): the sample filter's (DESIGN.md 40), less for noisier pixels.
        const std::vector<float>* scale = nullptr;
    };
    // A lookup's parts (lookup's parts): the diffuse light, the emission, and where the cells hold it, the specular light
    // and the light reflected toward the camera that saw it, with the share of the cells' weight that had it.
    struct Parts {
        float colour[3] = {0, 0, 0}, diffuse[3] = {0, 0, 0}, emission[3] = {0, 0, 0}, specular[3] = {0, 0, 0}, reflected[3] = {0, 0, 0};
        float share = 0;  // of the weight with a known reflection (and a diffuse output)
        float albedo[3] = {0, 0, 0};  // the cells' albedo (the smoothing's demodulation)
    };
    Options op;
    double addSeconds = 0;
    size_t added = 0;  // pixels the last picture added

    void clear() {
        light.clear(), fine.clear();
        sky.assign(SkyW * SkyH * 4, 0.0f), skyFilled.clear();
        generation = freshGeneration();
    }
    bool empty() const { return light.used == 0 && skyFilled.empty(); }
    size_t cells() const { return light.used + fine.used; }
    // What the store holds in memory, in bytes (its tables' slots and the environment's).
    size_t bytes() const {
        return (light.slots.size() + fine.slots.size()) * sizeof(Table::Entry) + light.extras.size() * sizeof(Table::Extra) + light.grads.size() * sizeof(Table::Grad) +
               (sky.size() + skyFilled.size()) * sizeof(float);
    }
    // A store taken in from elsewhere (rhea_cache.h: kept between realtime's runs, or read from a file): the lookups'
    // memo, keyed by the store's place and generation, must not take it for the one that stood there before.
    void renewed() { generation = freshGeneration(); }

    // The store written out and read back (rhea_cache.h, the radiance cache on disk): its options that shape the cells
    // (a store made under others is not read), each table's cells, and the environment. False where it cannot be.
    // 2: cells with their object and the diffuse, specular and reflected light (DESIGN.md 35, 38).
    static constexpr std::uint32_t FileForm = 2;
    bool save(std::FILE* f) const {
        auto put = [&](const void* p, size_t n) { return n == 0 || std::fwrite(p, 1, n, f) == n; };
        const std::uint32_t form = FileForm, entry = sizeof(Table::Entry);
        const double shape[3] = {op.scale, op.grazing, op.jump};
        const std::int32_t levels = op.levels, albedo = (op.albedo ? 1 : 0) | (op.byObject ? 2 : 0);
        bool ok = put("RHEASTOR", 8) && put(&form, 4) && put(&entry, 4) && put(shape, sizeof shape) && put(&levels, 4) && put(&albedo, 4);
        for (const Table* t : {&light, &fine}) {
            const std::uint64_t used = t->used;
            ok = ok && put(&used, 8);
            for (const Table::Entry& e : t->slots)
                if (e.full) ok = ok && put(&e, sizeof e);
        }
        for (const std::vector<float>* v : {&sky, &skyFilled}) {
            const std::uint64_t n = v->size();
            ok = ok && put(&n, 8) && put(v->data(), v->size() * sizeof(float));
        }
        return ok;
    }
    bool load(std::FILE* f) {
        auto get = [&](void* p, size_t n) { return n == 0 || std::fread(p, 1, n, f) == n; };
        char magic[8];
        std::uint32_t form = 0, entry = 0;
        double shape[3];
        std::int32_t levels = 0, albedo = 0;
        if (!get(magic, 8) || std::memcmp(magic, "RHEASTOR", 8) != 0 || !get(&form, 4) || form != FileForm || !get(&entry, 4) ||
            entry != sizeof(Table::Entry) || !get(shape, sizeof shape) || !get(&levels, 4) || !get(&albedo, 4))
            return false;
        if (shape[0] != op.scale || shape[1] != op.grazing || shape[2] != op.jump || levels != op.levels || albedo != ((op.albedo ? 1 : 0) | (op.byObject ? 2 : 0))) return false;
        Table tables[2];
        for (Table& t : tables) {
            std::uint64_t used = 0;
            if (!get(&used, 8) || used > op.maxCells * 4) return false;
            size_t size = size_t(1) << 16;
            while ((used + 1) * 2 > size) size *= 2;
            t.slots.assign(used ? size : 0, Table::Entry{});
            const size_t mask = t.slots.size() - 1;
            for (std::uint64_t k = 0; k < used; ++k) {
                Table::Entry e;
                if (!get(&e, sizeof e) || !e.full) return false;
                size_t i = Table::hashOf(e.x, e.y, e.z, e.level, e.bin, e.obj) & mask;
                while (t.slots[i].full) i = (i + 1) & mask;
                t.slots[i] = e;
            }
            t.used = size_t(used);
        }
        std::vector<float> held[2];
        for (std::vector<float>& v : held) {
            std::uint64_t n = 0;
            if (!get(&n, 8) || (n != 0 && n != SkyW * SkyH * 4)) return false;
            v.resize(size_t(n));
            if (!get(v.data(), v.size() * sizeof(float))) return false;
        }
        light = std::move(tables[0]), fine = std::move(tables[1]);
        light.regrown = fine.regrown = true;
        sky = std::move(held[0]), skyFilled = std::move(held[1]);
        renewed();
        return true;
    }

    // A picture's pixel size at depth 1 (perspective and directional: a pixel's footprint is this times its depth;
    // orthographic: this, at every depth).
    static double pixelAngle(const View& v) {
        surface::V3 a, b;
        const double cx = 0.5 * v.width, cy = 0.5 * v.height;
        if (!v.pointAt(cx, cy, 1.0, a) || !v.pointAt(cx + 1.0, cy, 1.0, b)) return 0;
        return std::sqrt(double(b.x - a.x) * (b.x - a.x) + double(b.y - a.y) * (b.y - a.y) + double(b.z - a.z) * (b.z - a.z));
    }
    static double footprint(const View& v, double angle, double depth) { return v.kind == View::Orthographic ? angle : angle * depth; }
    // How much longer a pixel is along a surface than across it: one over the cosine between the surface's normal and
    // the ray, at most `most` (a surface seen edge on, the sea toward the horizon).
    static double stretch(const D3& n, const D3& d, double most) {
        const double nl = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z), dl = std::sqrt(d.x * d.x + d.y * d.y + d.z * d.z);
        if (!(nl > 0) || !(dl > 0)) return 1.0;
        const double c = std::fabs(n.x * d.x + n.y * d.y + n.z * d.z) / (nl * dl);
        return 1.0 / std::max(c, 1.0 / std::max(1.0, most));
    }

    // A picture's colours onto the surfaces it shows: depth its nearest first-hit depth (0 none), depthFar its farthest
    // (empty: none); outs its albedo and emission, for the composite.
    // A cell's colour at d (its place in the cell, cell units from its middle; op.sparse): its mean plus its least-squares
    // slope times the way from its pixels' centroid. The slope regularised (a cell's pixels lie on a surface, so its
    // spread across the surface is none), its change held to the mean either way (no negative light, no runaway).
    static void cellColour(const xpu2::interactive::rheastore::Entry& e, const float* gs, const double d[3], double out[3]) {
        const double W = e.v[VW];
        double pc[3], C[3][3];
        for (int i = 0; i < 3; ++i) pc[i] = gs[i] / W;
        static const int ij[6][2] = {{0, 0}, {1, 1}, {2, 2}, {0, 1}, {0, 2}, {1, 2}};
        for (int k = 0; k < 6; ++k) {
            const int a = ij[k][0], b = ij[k][1];
            C[a][b] = C[b][a] = gs[3 + k] / W - pc[a] * pc[b];
        }
        for (int i = 0; i < 3; ++i) C[i][i] += 0.01;
        const double det = C[0][0] * (C[1][1] * C[2][2] - C[1][2] * C[2][1]) - C[0][1] * (C[1][0] * C[2][2] - C[1][2] * C[2][0]) +
                           C[0][2] * (C[1][0] * C[2][1] - C[1][1] * C[2][0]);
        for (int c = 0; c < 3; ++c) out[c] = e.v[c] / W;
        if (!(std::fabs(det) > 1e-12)) return;
        double inv[3][3];
        inv[0][0] = (C[1][1] * C[2][2] - C[1][2] * C[2][1]) / det, inv[0][1] = (C[0][2] * C[2][1] - C[0][1] * C[2][2]) / det;
        inv[0][2] = (C[0][1] * C[1][2] - C[0][2] * C[1][1]) / det, inv[1][0] = (C[1][2] * C[2][0] - C[1][0] * C[2][2]) / det;
        inv[1][1] = (C[0][0] * C[2][2] - C[0][2] * C[2][0]) / det, inv[1][2] = (C[0][2] * C[1][0] - C[0][0] * C[1][2]) / det;
        inv[2][0] = (C[1][0] * C[2][1] - C[1][1] * C[2][0]) / det, inv[2][1] = (C[0][1] * C[2][0] - C[0][0] * C[2][1]) / det;
        inv[2][2] = (C[0][0] * C[1][1] - C[0][1] * C[1][0]) / det;
        for (int c = 0; c < 3; ++c) {
            const double mean = out[c];
            double b[3];
            for (int i = 0; i < 3; ++i) b[i] = gs[9 + c * 3 + i] / W - pc[i] * mean;
            double change = 0;
            for (int i = 0; i < 3; ++i) {
                double slope = 0;
                for (int j = 0; j < 3; ++j) slope += inv[i][j] * b[j];
                change += slope * (d[i] - pc[i]);
            }
            out[c] = mean + std::clamp(change, -mean, mean);
        }
    }
    // A pixel's place in a cell of a size (cell units from its middle; the cell floor(p / size)).
    static void inCell(const surface::V3& p, int level, double d[3]) {
        const double size = std::ldexp(1.0, level);
        const double q[3] = {p.x / size, p.y / size, p.z / size};
        for (int i = 0; i < 3; ++i) d[i] = q[i] - (std::floor(q[i]) + 0.5);
    }
    void add(const View& view, unsigned w, unsigned h, const std::vector<float>& rgba, const std::vector<std::uint32_t>& counts,
             const std::vector<float>& depth, const std::vector<float>& depthFar, const Outputs* outputs = nullptr) {
        const Outputs outs = outputs ? *outputs : Outputs{};
        const auto began = std::chrono::steady_clock::now();
        const size_t n = size_t(w) * h;
        added = 0;
        generation = freshGeneration();  // the cells about to change: the lookups' memo (means) starts again
        if (rgba.size() != n * 4 || depth.size() != n || counts.size() != n) return;
        if (cells() > op.maxCells) clear();
        if (sky.empty()) sky.assign(SkyW * SkyH * 4, 0.0f);
        const double angle = pixelAngle(view);
        if (!(angle > 0)) return;
        const bool parts = outs.aov && outs.stride && outs.aov->size() == n * outs.stride && outs.albedo >= 0 &&
                           size_t(outs.albedo) + 3 <= outs.stride && (outs.emission < 0 || size_t(outs.emission) + 3 <= outs.stride);
        const bool diffuse = parts && outs.diffuse >= 0 && size_t(outs.diffuse) + 3 <= outs.stride;
        const std::vector<PixelExtra>* extra = outs.extra && outs.extra->size() == n ? outs.extra : nullptr;
        // Every pixel at a large picture would cost more than it adds: a stride keeps it under a third of a million.
        const unsigned stride = unsigned(std::max(1.0, std::floor(std::sqrt(double(n) / 330000.0))));
        struct Add {
            surface::V3 p;
            int level;
            std::uint8_t bins[2];
            std::uint32_t obj;
            float v[NV], weight;  // as a cell's sums (Table::Entry::v), v[VW] unused
        };
        const unsigned rows = (h + stride - 1) / stride;
        std::vector<std::vector<Add>> perRow(rows);
        std::vector<std::vector<std::array<float, 6>>> skyRow(rows);
        auto at = [&](unsigned x, unsigned y, surface::V3& p) { return depth[size_t(y) * w + x] > 0 && view.pointAt(x + 0.5, y + 0.5, depth[size_t(y) * w + x], p); };
        parallel(std::max(1u, op.threads), rows, [&](size_t r) {
            const unsigned y = unsigned(r) * stride;
            for (unsigned x = 0; x < w; x += stride) {
                const size_t i = size_t(y) * w + x;
                if (!counts[i]) continue;
                const float d = depth[i];
                const float* c = &rgba[i * 4];
                if (!(std::isfinite(c[0]) && std::isfinite(c[1]) && std::isfinite(c[2]))) continue;
                const float weight = float(std::min<std::uint32_t>(counts[i], 64u)) / 64.0f;
                surface::Ray ray;
                if (!view.ray(x + 0.5, y + 0.5, ray)) continue;
                if (!(d > 0)) {
                    // The environment: by direction (alpha little: no surface's coverage in it).
                    if (c[3] > 0.02f && c[3] < 0.98f) continue;
                    skyRow[r].push_back({ray.direction.x, ray.direction.y, ray.direction.z, c[0], c[1], c[2]});
                    continue;
                }
                // A silhouette's pixel (the environment in it, or two depths a jump apart) adds nothing.
                if (c[3] < 0.98f) continue;
                if (depthFar.size() == n && depthFar[i] > 0 && (depthFar[i] - d) > op.jump * d) continue;
                surface::V3 p, px0, px1, py0, py1;
                if (!view.pointAt(x + 0.5, y + 0.5, d, p)) continue;
                // The surface's side, from its neighbours on the same surface (one-sided at its edges).
                auto near = [&](int dx, int dy, surface::V3& q) {
                    const int xx = int(x) + dx, yy = int(y) + dy;
                    if (xx < 0 || yy < 0 || xx >= int(w) || yy >= int(h)) return false;
                    const float dd = depth[size_t(yy) * w + size_t(xx)];
                    return dd > 0 && std::fabs(dd - d) <= op.jump * d && at(unsigned(xx), unsigned(yy), q);
                };
                const bool l = near(-1, 0, px0), rr = near(1, 0, px1), u = near(0, -1, py0), dn = near(0, 1, py1);
                if (!(l || rr) || !(u || dn)) continue;
                const surface::V3 a0 = l ? px0 : p, a1 = rr ? px1 : p, b0 = u ? py0 : p, b1 = dn ? py1 : p;
                const D3 ex{double(a1.x) - a0.x, double(a1.y) - a0.y, double(a1.z) - a0.z}, ey{double(b1.x) - b0.x, double(b1.y) - b0.y, double(b1.z) - b0.z};
                D3 nn{ex.y * ey.z - ex.z * ey.y, ex.z * ey.x - ex.x * ey.z, ex.x * ey.y - ex.y * ey.x};
                nn = view.toward(nn, p);
                if (!(nn.x != 0 || nn.y != 0 || nn.z != 0)) continue;
                Add e;
                e.p = p;
                const double along = stretch(nn, D3{ray.direction.x, ray.direction.y, ray.direction.z}, op.grazing);
                e.level = levelOf(footprint(view, angle, d) * along * op.scale * stride) + std::max(0, outs.coarser);
                binsOf(nn, e.bins);
                for (int k = 0; k < NV; ++k) e.v[k] = 0;
                for (int k = 0; k < 3; ++k) e.v[k] = c[k];
                e.obj = op.byObject && extra ? (*extra)[i].obj : 0u;
                if (parts) {
                    const float* o = &(*outs.aov)[i * outs.stride];
                    for (int k = 0; k < 3; ++k) {
                        e.v[3 + k] = std::isfinite(o[outs.albedo + k]) ? std::max(0.0f, o[outs.albedo + k]) : 0.0f;
                        e.v[6 + k] = outs.emission >= 0 && std::isfinite(o[outs.emission + k]) ? std::max(0.0f, o[outs.emission + k]) : 0.0f;
                    }
                    if (diffuse) {
                        for (int k = 0; k < 3; ++k) e.v[VD + k] = std::isfinite(o[outs.diffuse + k]) ? std::max(0.0f, o[outs.diffuse + k]) : 0.0f;
                        // The specular light (all the pixel's light but its emission and its diffuse light) beside the light
                        // reflected toward the camera along the mirror direction: their ratio is the surface's specular
                        // reflectance as that view saw it (Realtime::learn; lookup's parts).
                        if (extra && (*extra)[i].reflectedKnown) {
                            for (int k = 0; k < 3; ++k) {
                                e.v[VS + k] = std::max(0.0f, c[k] - e.v[VD + k] - e.v[6 + k]);
                                e.v[VR + k] = std::max(0.0f, (*extra)[i].reflected[k]);
                            }
                            e.v[VWS] = 1.0f;
                        }
                    }
                }
                e.weight = outs.scale && outs.scale->size() == n ? weight * (*outs.scale)[i] : weight;
                perRow[r].push_back(e);
            }
        });
        for (auto& row : perRow)
            for (const Add& e : row) {
                for (int b = 0; b < 2; ++b) {
                    if (e.bins[b] == NoBin) continue;
                    auto into = [&](Table::Entry& t, size_t idx, int level) {
                        for (int q = 0; q < NB; ++q) t.v[q] += e.v[q] * e.weight;
                        t.v[VW] += e.weight;
                        // The view-dependent sums beside it, where this store learns them (a diffuse output).
                        if (diffuse) {
                            Table::Extra& x = light.more(idx);
                            for (int q = NB; q < NV; ++q) x.v[q - NB] += e.v[q] * e.weight;
                        }
                        if (op.sparse) {
                            // Its slope's sums (cellColour).
                            Table::Grad& g = light.slope(idx);
                            double d[3];
                            inCell(e.p, level, d);
                            const float wgt = e.weight;
                            for (int i = 0; i < 3; ++i) g.s[i] += float(wgt * d[i]);
                            g.s[3] += float(wgt * d[0] * d[0]), g.s[4] += float(wgt * d[1] * d[1]), g.s[5] += float(wgt * d[2] * d[2]);
                            g.s[6] += float(wgt * d[0] * d[1]), g.s[7] += float(wgt * d[0] * d[2]), g.s[8] += float(wgt * d[1] * d[2]);
                            for (int c = 0; c < 3; ++c)
                                for (int i = 0; i < 3; ++i) g.s[9 + c * 3 + i] += float(wgt * d[i] * e.v[c]);
                        }
                    };
                    if (!op.sparse) {
                        for (int k = 0; k < op.levels; ++k) {
                            Table::Entry& t = light.slot(e.p, e.level + k, e.bins[b], e.obj);
                            into(t, light.last, e.level + k);
                        }
                    } else {
                        // Coarsest first; a finer cell made only where this one does not foresee the pixel (op.sparse). A
                        // pixel of few samples is noisier: its tolerance wider.
                        const double tolerance = op.sparseTolerance * (1.0 + 2.0 * (1.0 - std::clamp(double(e.weight), 0.0, 1.0)));
                        bool finer = true;
                        for (int k = op.levels - 1; k >= 0; --k) {
                            const int level = e.level + k;
                            if (finer) {
                                Table::Entry& t = light.slot(e.p, level, e.bins[b], e.obj);
                                const size_t idx = light.last;
                                if (k > 0 && t.v[VW] >= op.sparseMinWeight) {
                                    double d[3], seen[3];
                                    inCell(e.p, level, d);
                                    cellColour(t, light.slope(idx).s, d, seen);
                                    const double scale = std::max(0.2126 * seen[0] + 0.7152 * seen[1] + 0.0722 * seen[2],
                                                                  0.2126 * e.v[0] + 0.7152 * e.v[1] + 0.0722 * e.v[2]) + 0.02;
                                    double off = 0;
                                    for (int c = 0; c < 3; ++c) off = std::max(off, std::fabs(seen[c] - double(e.v[c])));
                                    if (off <= tolerance * scale) finer = false;
                                }
                                into(t, idx, level);
                            } else {
                                // Finer cells made before keep learning; none made for this pixel.
                                const double size = std::ldexp(1.0, level);
                                const long long i = light.index((long long)std::floor(e.p.x / size), (long long)std::floor(e.p.y / size),
                                                                (long long)std::floor(e.p.z / size), level, e.bins[b], e.obj);
                                if (i >= 0) {
                                    light.touch(size_t(i));
                                    into(light.slots[size_t(i)], size_t(i), level);
                                }
                            }
                        }
                    }
                    // The albedo alone, in cells half as wide.
                    if (op.albedo && parts)
                        for (int k = 0; k < op.levels + 1; ++k) {
                            Table::Entry& t = fine.slot(e.p, e.level - 1 + k, e.bins[b], e.obj);
                            for (int q = 0; q < 3; ++q) t.v[q] += e.v[3 + q] * e.weight;
                            t.v[9] += e.weight;
                        }
                }
                ++added;
            }
        bool skyAdded = false;
        for (auto& row : skyRow)
            for (const auto& s : row) {
                const int k = skyCell(D3{s[0], s[1], s[2]});
                if (k < 0) continue;
                float* m = &sky[size_t(k) * 4];
                m[0] += s[3], m[1] += s[4], m[2] += s[5], m[3] += 1.0f;
                skyAdded = true;
            }
        if (skyAdded) fillSky();
        addSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
    }

    // The colour at a surface's point (trace space; n its normal facing the camera, dir the ray to it, foot a pixel's
    // width there): true where the store holds it (confidence: the share of the neighbouring cells it has, at the finest
    // size it has).
    // up: how many sizes coarser than the point's own its colour came from.
    // maxUp: the most sizes up from the point's own the lookup climbs (-1: up to op.levels + 6). A point no picture has
    // shown climbed every size, up to 16 hash probes each, the most of a drag step's lookups on the user's car.
    // obj: the hit's object (op.byObject: its cells alone). parts: the colour's parts, where wanted.
    bool lookup(const surface::V3& p, const D3& n, const D3& dir, double foot, float rgb[3], float& confidence, int* up = nullptr,
                int maxUp = -1, std::uint32_t obj = 0, Parts* parts = nullptr) const {
        confidence = 0;
        if (up) *up = 0;
        if (!light.used) return false;
        if (!op.byObject) obj = 0;
        std::uint8_t bins[2];
        binsOf(n, bins);
        const int first = levelOf(foot * stretch(n, dir, op.grazing) * op.scale);
        double m[NV];
        int sizesUp = 0;
        const int levels = maxUp >= 0 ? std::min(op.levels + 6, maxUp + 1) : op.levels + 6;
        const bool more = parts && !light.extras.empty();
        if (!means(light, p, bins, obj, first, levels, m, confidence, &sizesUp, more ? NV : NB)) return false;
        if (up) *up = sizesUp;
        for (int ch = 0; ch < 3; ++ch) rgb[ch] = float(std::max(0.0, m[ch]));
        if (parts && !more) *parts = Parts{}, parts->colour[0] = rgb[0], parts->colour[1] = rgb[1], parts->colour[2] = rgb[2];
        if (parts)
            for (int ch = 0; ch < 3; ++ch) parts->albedo[ch] = float(std::max(0.0, m[3 + ch]));
        if (more) {
            for (int ch = 0; ch < 3; ++ch) {
                parts->colour[ch] = rgb[ch];
                parts->emission[ch] = float(std::max(0.0, m[6 + ch]));
                parts->diffuse[ch] = float(std::max(0.0, m[VD + ch]));
                parts->specular[ch] = m[VWS] > 0 ? float(std::max(0.0, m[VS + ch] / m[VWS])) : 0.0f;
                parts->reflected[ch] = m[VWS] > 0 ? float(std::max(0.0, m[VR + ch] / m[VWS])) : 0.0f;
            }
            parts->share = float(std::clamp(m[VWS], 0.0, 1.0));
        }
        if (op.albedo && fine.used) {
            double a[NV];
            float fineConfidence;
            if (means(fine, p, bins, obj, first - 1, op.levels + 7, a, fineConfidence, nullptr))
                for (int ch = 0; ch < 3; ++ch)
                    if (m[3 + ch] > 0.02) rgb[ch] = float(std::max(0.0, a[ch] * (m[ch] - m[6 + ch]) / m[3 + ch] + m[6 + ch]));
        }
        return true;
    }
    // The scene's environment lights' radiance in a direction (trace space), as a ray leaving the scene there meets them.
    static bool environment(const cpu::Plan& plan, const surface::V3& p, const surface::V3& dir, float rgb[3], double blur = 0) {
        namespace L = xpu2::interactive::lights;
        rgb[0] = rgb[1] = rgb[2] = 0.0f;
        bool any = false;
        for (const L::Light& l : plan.lights) {
            if (l.type != L::Env) continue;
            L::Hit h{};
            if (!L::intersectShapeHere(l, p, nullptr, dir, 3.4e38f, h)) continue;
            float pdf = 0;
            const surface::V3 c = L::evalShapeHere(l, p, dir, h, pdf, blur > 0 ? float(std::log2(blur)) : L::NoFootprint);
            if (!(std::isfinite(c.x) && std::isfinite(c.y) && std::isfinite(c.z))) continue;
            rgb[0] += c.x, rgb[1] += c.y, rgb[2] += c.z;
            any = true;
        }
        return any;
    }
    // The light reflected toward a ray's first hit along its mirror direction (the shading normal's): the store's colour
    // where the reflected ray meets a surface (at cells a few times the hit's footprint), the environment lights' where it
    // leaves the scene. False where neither is known. The same at learning (Realtime::learn) and at a view's lookups
    // (ObjectWarp), so that the specular light divided by it at one and multiplied by it at the other agree.
    bool reflectedAt(const async::CpuBackend& backend, const cpu::Plan& plan, const surface::Ray& ray, const resume::Hit& hit, double foot, double blur, bool traced,
                     float out[3]) const {
        out[0] = out[1] = out[2] = 0.0f;
        if (hit.geom == ~0u) return false;
        const double dl = std::sqrt(double(ray.direction.x) * ray.direction.x + double(ray.direction.y) * ray.direction.y +
                                    double(ray.direction.z) * ray.direction.z);
        if (!(dl > 0)) return false;
        const D3 d{ray.direction.x / dl, ray.direction.y / dl, ray.direction.z / dl};
        D3 nn{hit.normal.x, hit.normal.y, hit.normal.z};
        xpu2::interactive::shade::State st{};
        if (backend.surfaceState(hit, ray, st)) nn = D3{st.N.x, st.N.y, st.N.z};
        const double nl = std::sqrt(nn.x * nn.x + nn.y * nn.y + nn.z * nn.z);
        if (!(nl > 0)) return false;
        nn = D3{nn.x / nl, nn.y / nl, nn.z / nl};
        double dn = d.x * nn.x + d.y * nn.y + d.z * nn.z;
        if (dn > 0) nn = D3{-nn.x, -nn.y, -nn.z}, dn = -dn;  // facing the viewer
        const surface::V3 r{float(d.x - 2 * dn * nn.x), float(d.y - 2 * dn * nn.y), float(d.z - 2 * dn * nn.z)};
        // Untraced (traced false): the environment's light in the mirror direction, whatever stands in the way (no ray).
        if (!traced) return environment(plan, hit.point, r, out, blur);
        surface::Ray rr = ray;
        rr.origin = hit.origin, rr.direction = r, rr.nearT = 0.0f, rr.farT = 3.4e38f;
        const resume::Hit h2 = backend.trace(rr);
        if (h2.geom == ~0u) return environment(plan, hit.point, r, out, blur);
        float conf = 0;
        int up = 0;
        const D3 n2{h2.normal.x, h2.normal.y, h2.normal.z};
        return lookup(h2.point, n2, D3{r.x, r.y, r.z}, std::max(foot * 2.0, blur * double(h2.t)), out, conf, &up, 5, h2.geom + 1);
    }
    // The colour table for the graphics card's copy (rhea_store_core.h, DESIGN.md 37): its slots, and what changed since
    // the last sending (cardChanges: whole, or the dirty pages of PageSlots slots each; then forgotten).
    const std::vector<xpu2::interactive::rheastore::Entry>& cardSlots() const { return light.slots; }
    const std::vector<xpu2::interactive::rheastore::Extra>& cardExtras() const { return light.extras; }
    bool cardChanges(std::vector<std::pair<size_t, size_t>>& pages) {
        pages.clear();
        const bool whole = light.regrown;
        if (!whole)
            for (size_t k = 0; k < light.dirty.size(); ++k)
                if (light.dirty[k]) {
                    const size_t from = k * Table::PageSlots, to = std::min(light.slots.size(), from + Table::PageSlots);
                    if (from < to) {
                        if (!pages.empty() && pages.back().second == from) pages.back().second = to;
                        else pages.emplace_back(from, to);
                    }
                }
        light.regrown = false;
        std::fill(light.dirty.begin(), light.dirty.end(), std::uint8_t(0));
        return whole;
    }
    // The lookups' view for the card (its options' part).
    void cardView(xpu2::interactive::rheastore::View& v) const {
        v.levels = op.levels, v.byObject = op.byObject ? 1 : 0, v.scale = op.scale, v.grazing = op.grazing;
    }
    // The environment's colour in a direction (trace space): false where no picture has shown it.
    bool skyAt(const D3& d, float rgb[3]) const {
        if (skyFilled.empty()) return false;
        double u, v;
        if (!skyUV(d, u, v)) return false;
        const double fx = u * SkyW - 0.5, fy = v * SkyH - 0.5;
        const int x0 = int(std::floor(fx)), y0 = int(std::floor(fy));
        const double tx = fx - x0, ty = fy - y0;
        double c[3] = {0, 0, 0}, wsum = 0;
        for (int k = 0; k < 4; ++k) {
            const int xx = ((x0 + (k & 1)) % int(SkyW) + int(SkyW)) % int(SkyW), yy = std::clamp(y0 + (k >> 1), 0, int(SkyH) - 1);
            const double wt = ((k & 1) ? tx : 1 - tx) * ((k >> 1) ? ty : 1 - ty);
            const float* m = &skyFilled[(size_t(yy) * SkyW + size_t(xx)) * 4];
            if (!(m[3] > 0)) continue;
            for (int ch = 0; ch < 3; ++ch) c[ch] += wt * m[ch];
            wsum += wt;
        }
        if (wsum <= 0) return false;
        for (int ch = 0; ch < 3; ++ch) rgb[ch] = float(c[ch] / wsum);
        return true;
    }

private:
    static constexpr std::uint8_t NoBin = 255;
    // A cell's sums (Table::Entry::v): the weight's place among them, the diffuse light's, the specular light's, the
    // reflected light's and their weight's.
    static constexpr int NB = xpu2::interactive::rheastore::NB, NV = xpu2::interactive::rheastore::NV, VW = xpu2::interactive::rheastore::VW,
                         VD = xpu2::interactive::rheastore::VD,
                         VS = xpu2::interactive::rheastore::VS, VR = xpu2::interactive::rheastore::VR, VWS = xpu2::interactive::rheastore::VWS;
    static constexpr size_t SkyW = 256, SkyH = 128;
    // A sparse hash of cubes: by their place at their size (2^level a side) and the side their surface faces; each the
    // weighted sums of what was added to it (colour, albedo, emission) and the weights.
    struct Table {
        // v: the sums of colour (0-2), albedo (3-5), emission (6-8), the weight (9), the diffuse light (10-12), and, from the
        // pixels whose reflected light was known (op.specular), their specular light (13-15), that reflected light (16-18)
        // and their weight (19). obj: the object the cell is of (op.byObject; 0 otherwise).
        // (Its layout and hash shared with the graphics card's copy: rhea_store_core.h.)
        using Entry = xpu2::interactive::rheastore::Entry;
        using Extra = xpu2::interactive::rheastore::Extra;
        // A slot's sums for its light's slope (op.sparse), d its pixels' places in the cell (cell units, -0.5 to 0.5 from
        // its middle), L their colour, all weighted as its means: d (0-2), d d' (3-8: xx yy zz xy xz yz), d L (9-17: a colour
        // channel's three).
        struct Grad {
            float s[18] = {};
        };
        std::vector<Entry> slots;
        std::vector<Extra> extras;  // a slot's view-dependent sums each (more()), or none
        std::vector<Grad> grads;    // a slot's slope sums each (slope()), or none
        size_t used = 0;
        size_t last = 0;  // the slot slot() last gave
        // The view-dependent sums, made for every slot where first asked for.
        Extra& more(size_t i) {
            if (extras.size() != slots.size()) extras.assign(slots.size(), Extra{}), regrown = true;
            return extras[i];
        }
        Grad& slope(size_t i) {
            if (grads.size() != slots.size()) grads.assign(slots.size(), Grad{});
            return grads[i];
        }
        // A slot's index (find's, for a table that may be added to), or -1.
        long long index(long long x, long long y, long long z, int level, int bin, std::uint32_t obj) const {
            const Entry* e = find(x, y, z, level, bin, obj);
            return e ? (long long)(e - slots.data()) : -1;
        }
        // The card's copy (rheaStore): pages of slots written since it was last sent, or the whole (regrown).
        static constexpr size_t PageSlots = 4096;
        std::vector<std::uint8_t> dirty;
        bool regrown = true;
        void touch(size_t i) {
            const size_t page = i / PageSlots;
            if (page >= dirty.size()) dirty.resize(slots.size() / PageSlots + 1, 0);
            dirty[page] = 1;
        }
        void clear() { slots.clear(), extras.clear(), grads.clear(), used = 0, dirty.clear(), regrown = true; }
        static std::uint64_t hashOf(long long x, long long y, long long z, int level, int bin, std::uint32_t obj) {
            return xpu2::interactive::rheastore::hashOf(x, y, z, level, bin, obj);
        }
        const Entry* find(long long x, long long y, long long z, int level, int bin, std::uint32_t obj) const {
            if (slots.empty()) return nullptr;
            const size_t mask = slots.size() - 1;
            for (size_t i = hashOf(x, y, z, level, bin, obj) & mask;; i = (i + 1) & mask) {
                const Entry& e = slots[i];
                if (!e.full) return nullptr;
                if (e.x == x && e.y == y && e.z == z && e.level == level && e.bin == bin && e.obj == obj) return &e;
            }
        }
        Entry& slot(const surface::V3& p, int level, int bin, std::uint32_t obj) {
            const double size = std::ldexp(1.0, level);
            const long long x = (long long)std::floor(p.x / size), y = (long long)std::floor(p.y / size), z = (long long)std::floor(p.z / size);
            if ((used + 1) * 2 > slots.size()) grow(std::max<size_t>(slots.size() * 2, size_t(1) << 16));
            const size_t mask = slots.size() - 1;
            for (size_t i = hashOf(x, y, z, level, bin, obj) & mask;; i = (i + 1) & mask) {
                Entry& e = slots[i];
                if (!e.full) {
                    e = Entry{};
                    e.x = x, e.y = y, e.z = z, e.level = std::int16_t(level), e.bin = std::uint8_t(bin), e.full = 1, e.obj = obj;
                    ++used;
                    touch(i);
                    if (!extras.empty()) extras[i] = Extra{};
                    if (!grads.empty()) grads[i] = Grad{};
                    last = i;
                    return e;
                }
                if (e.x == x && e.y == y && e.z == z && e.level == level && e.bin == bin && e.obj == obj) {
                    touch(i);
                    last = i;
                    return e;
                }
            }
        }
        void grow(size_t size) {
            std::vector<Entry> old;
            std::vector<Extra> oldMore;
            std::vector<Grad> oldGrads;
            old.swap(slots), oldMore.swap(extras), oldGrads.swap(grads);
            slots.assign(size, Entry{});
            if (!oldMore.empty()) extras.assign(size, Extra{});
            if (!oldGrads.empty()) grads.assign(size, Grad{});
            regrown = true, dirty.assign(size / PageSlots + 1, 0);
            const size_t mask = slots.size() - 1;
            for (size_t k = 0; k < old.size(); ++k) {
                const Entry& e = old[k];
                if (!e.full) continue;
                size_t i = hashOf(e.x, e.y, e.z, e.level, e.bin, e.obj) & mask;
                while (slots[i].full) i = (i + 1) & mask;
                slots[i] = e;
                if (!oldMore.empty()) extras[i] = oldMore[k];
                if (!oldGrads.empty()) grads[i] = oldGrads[k];
            }
        }
    };
    Table light, fine;  // the colours (with albedo and emission), and the albedo in cells half as wide (op.albedo)
    // Changed with the cells (add, clear, renewed): the lookups' memo holds for one generation. Drawn from one count for
    // every store, so that a store moved into another's place (rhea_cache.h) never meets the memo of the one before.
    std::uint64_t generation = freshGeneration();
    static std::uint64_t freshGeneration() {
        static std::atomic<std::uint64_t> next{1};
        return next.fetch_add(1);
    }
    std::vector<float> sky, skyFilled;  // rgb and weight a direction: summed, and its holes filled (fillSky)

    static int levelOf(double side) { return side > 0 ? int(std::floor(std::log2(side))) : -60; }
    // A thread's last eight cells at a size (means): neighbouring rays meet the same cells.
    struct Memo {
        const ObjectStore* store = nullptr;
        const Table* table = nullptr;
        std::uint64_t generation = ~0ull;
        int level = 0;
        std::uint8_t bins[2] = {0, 0};
        std::uint32_t obj = 0;
        long long x0 = 0, y0 = 0, z0 = 0;
        const Table::Entry* e[8] = {};
    };
    // The side a normal faces: its largest axis and sign, and the next where it is nearly as large (the boundary's
    // cells kept in both, so that a surface at 45 degrees finds its colour from either).
    static void binsOf(const D3& n, std::uint8_t out[2]) {
        const double a[3] = {std::fabs(n.x), std::fabs(n.y), std::fabs(n.z)}, s[3] = {n.x, n.y, n.z};
        int i0 = 0;
        for (int k = 1; k < 3; ++k)
            if (a[k] > a[i0]) i0 = k;
        int i1 = (i0 + 1) % 3;
        for (int k = 0; k < 3; ++k)
            if (k != i0 && a[k] > a[i1]) i1 = k;
        out[0] = std::uint8_t(i0 * 2 + (s[i0] < 0));
        out[1] = a[i1] > 0.75 * a[i0] ? std::uint8_t(i1 * 2 + (s[i1] < 0)) : NoBin;
    }
    // Table t's means (v[0..8] over its weight) at p: trilinear between the cells about it at the first size that has
    // any, the coarser sizes filling what the finer leave (a size's share by the cells it has).
    bool means(const Table& t, const surface::V3& p, const std::uint8_t bins[2], std::uint32_t obj, int first, int levels, double out[NV],
               float& confidence, int* up, int nv = VW + 1) const {
        double acc[NV] = {}, have = 0;
        confidence = 0;
        for (int k = 0; k < levels; ++k) {
            const int level = first + k;
            const double size = std::ldexp(1.0, level);
            const double fx = p.x / size - 0.5, fy = p.y / size - 0.5, fz = p.z / size - 0.5;
            const long long x0 = (long long)std::floor(fx), y0 = (long long)std::floor(fy), z0 = (long long)std::floor(fz);
            const double tx = fx - x0, ty = fy - y0, tz = fz - z0;
            // The eight cells about the point: found again only where the last lookup at this size (this thread's, a
            // neighbouring ray's, most often) was about other cells.
            static thread_local Memo memo[8];
            Memo& m = memo[unsigned(level) & 7u];
            if (m.store != this || m.table != &t || m.generation != generation || m.level != level || m.bins[0] != bins[0] ||
                m.bins[1] != bins[1] || m.obj != obj || m.x0 != x0 || m.y0 != y0 || m.z0 != z0) {
                for (int corner = 0; corner < 8; ++corner) {
                    const int dx = corner & 1, dy = corner >> 1 & 1, dz = corner >> 2 & 1;
                    const Table::Entry* e = t.find(x0 + dx, y0 + dy, z0 + dz, level, bins[0], obj);
                    if (!e && bins[1] != NoBin) e = t.find(x0 + dx, y0 + dy, z0 + dz, level, bins[1], obj);
                    m.e[corner] = e && e->v[VW] > 0 ? e : nullptr;
                }
                m.store = this, m.table = &t, m.generation = generation, m.level = level, m.bins[0] = bins[0], m.bins[1] = bins[1], m.obj = obj;
                m.x0 = x0, m.y0 = y0, m.z0 = z0;
            }
            double c[NV] = {}, wsum = 0;
            for (int corner = 0; corner < 8; ++corner) {
                const Table::Entry* e = m.e[corner];
                if (!e) continue;
                const int dx = corner & 1, dy = corner >> 1 & 1, dz = corner >> 2 & 1;
                const double tri = (dx ? tx : 1 - tx) * (dy ? ty : 1 - ty) * (dz ? tz : 1 - tz);
                if (tri <= 0) continue;
                const double k = tri / e->v[VW];
                const size_t at = size_t(e - t.slots.data());
                if (op.sparse && &t == &light && t.grads.size() == t.slots.size()) {
                    // Its colour at the point by its slope (cellColour), the rest by its means.
                    const double d[3] = {p.x / size - (double(x0 + dx) + 0.5), p.y / size - (double(y0 + dy) + 0.5), p.z / size - (double(z0 + dz) + 0.5)};
                    double col[3];
                    cellColour(*e, t.grads[at].s, d, col);
                    for (int q = 0; q < 3; ++q) c[q] += tri * col[q];
                    for (int q = 3; q < std::min(nv, NB); ++q) c[q] += k * e->v[q];
                } else
                    for (int q = 0; q < std::min(nv, NB); ++q) c[q] += k * e->v[q];
                if (nv > NB && !t.extras.empty()) {
                    const Table::Extra& x = t.extras[at];
                    for (int q = NB; q < nv; ++q) c[q] += k * x.v[q - NB];
                }
                wsum += tri;
            }
            if (wsum <= 0) continue;
            const double take = (1.0 - have) * std::min(1.0, wsum / 0.5);
            for (int q = 0; q < nv; ++q) acc[q] += take * c[q] / wsum;
            if (have == 0) {
                confidence = float(std::min(1.0, wsum));
                if (up) *up = k;
            }
            have += take;
            if (have > 0.999) break;
        }
        if (have <= 0) return false;
        for (int q = 0; q < nv; ++q) out[q] = acc[q] / have;
        return true;
    }
    static bool skyUV(const D3& d, double& u, double& v) {
        const double l = std::sqrt(d.x * d.x + d.y * d.y + d.z * d.z);
        if (!(l > 0)) return false;
        u = 0.5 + std::atan2(d.x, -d.z) / (2 * 3.14159265358979323846);
        v = std::acos(std::clamp(d.y / l, -1.0, 1.0)) / 3.14159265358979323846;
        return std::isfinite(u) && std::isfinite(v);
    }
    static int skyCell(const D3& d) {
        double u, v;
        if (!skyUV(d, u, v)) return -1;
        const int x = std::clamp(int(u * SkyW), 0, int(SkyW) - 1), y = std::clamp(int(v * SkyH), 0, int(SkyH) - 1);
        return y * int(SkyW) + x;
    }
    // The directions no picture has shown, from those around them (pullPush: smooth, no blocks).
    void fillSky() {
        std::vector<float> c(SkyW * SkyH * 4, 0.0f);
        for (size_t i = 0; i < SkyW * SkyH; ++i) {
            const float* m = &sky[i * 4];
            if (!(m[3] > 0)) continue;
            for (int k = 0; k < 3; ++k) c[i * 4 + k] = m[k] / m[3];
            c[i * 4 + 3] = 1.0f;
        }
        pullPush(c, unsigned(SkyW), unsigned(SkyH));
        skyFilled.swap(c);
    }
};

// Screen-space anti-aliasing of phase one's picture (the user, 2026-11-22: "is it possible for rhea phase 1 to have
// screen-space anti-aliasing? if it's cheap and makes the image nice and smooth would be good"): FXAA's quality pass
// (Lottes, 2011), on the picture's luma (HDR values brought to [0, 1) by l / (1 + l)). A pixel whose neighbourhood's
// luma range is small is left as it is; else its edge's direction is found from the 3x3 around it, the edge followed both
// ways to its ends, and the pixel blended across it by how far it lies from the nearer end, at least by the 3x3's
// low-pass share (sub-pixel aliasing). Phase one's silhouettes are a ray a pixel, hard: this smooths their steps.
struct Fxaa {
    double edgeThreshold = 0.125, edgeThresholdMin = 0.0312, subpix = 0.75;

    void apply(std::vector<float>& rgb, unsigned w, unsigned h, unsigned threads) const {
        const size_t n = size_t(w) * h;
        if (rgb.size() != n * 3 || w < 3 || h < 3) return;
        std::vector<float> luma(n);
        parallel(std::max(1u, threads), h, [&](size_t y) {
            for (size_t i = y * w; i < (y + 1) * w; ++i) {
                const double l = 0.299 * rgb[i * 3] + 0.587 * rgb[i * 3 + 1] + 0.114 * rgb[i * 3 + 2];
                luma[i] = std::isfinite(l) && l > 0 ? float(l / (1.0 + l)) : 0.0f;
            }
        });
        std::vector<float> out(rgb);
        auto L = [&](int x, int y) {
            x = std::clamp(x, 0, int(w) - 1), y = std::clamp(y, 0, int(h) - 1);
            return double(luma[size_t(y) * w + size_t(x)]);
        };
        // The picture's colour at a place between pixels (bilinear; pixel centres at integers).
        auto colourAt = [&](double fx, double fy, float o[3]) {
            fx = std::clamp(fx, 0.0, double(w - 1)), fy = std::clamp(fy, 0.0, double(h - 1));
            const int x0 = int(std::floor(fx)), y0 = int(std::floor(fy));
            const int x1 = std::min(x0 + 1, int(w) - 1), y1 = std::min(y0 + 1, int(h) - 1);
            const double tx = fx - x0, ty = fy - y0;
            for (int c = 0; c < 3; ++c) {
                const double a = rgb[(size_t(y0) * w + x0) * 3 + c], b = rgb[(size_t(y0) * w + x1) * 3 + c];
                const double d = rgb[(size_t(y1) * w + x0) * 3 + c], e = rgb[(size_t(y1) * w + x1) * 3 + c];
                o[c] = float((a + tx * (b - a)) + ty * ((d + tx * (e - d)) - (a + tx * (b - a))));
            }
        };
        // FXAA's search steps along the edge (its quality preset 12).
        static constexpr double steps[] = {1.0, 1.5, 2.0, 2.0, 2.0, 2.0, 4.0, 8.0};
        parallel(std::max(1u, threads), h, [&](size_t yy) {
            const int y = int(yy);
            for (int x = 0; x < int(w); ++x) {
                const double m = L(x, y), nn = L(x, y - 1), s = L(x, y + 1), e = L(x + 1, y), ww = L(x - 1, y);
                const double most = std::max({m, nn, s, e, ww}), least = std::min({m, nn, s, e, ww});
                const double range = most - least;
                if (range < std::max(edgeThresholdMin, most * edgeThreshold)) continue;
                const double nw = L(x - 1, y - 1), ne = L(x + 1, y - 1), sw = L(x - 1, y + 1), se = L(x + 1, y + 1);
                // The low-pass share: how far the pixel stands from its neighbours' mean, for sub-pixel aliasing.
                const double mean = (2.0 * (nn + s + e + ww) + (nw + ne + sw + se)) / 12.0;
                const double sub0 = std::clamp(std::fabs(mean - m) / range, 0.0, 1.0);
                const double sub1 = (-2.0 * sub0 + 3.0) * sub0 * sub0;
                const double subBlend = sub1 * sub1 * subpix;
                // The edge's direction: horizontal where the luma changes more from row to row.
                const double edgeH = std::fabs(nw - 2 * ww + sw) + 2 * std::fabs(nn - 2 * m + s) + std::fabs(ne - 2 * e + se);
                const double edgeV = std::fabs(nw - 2 * nn + ne) + 2 * std::fabs(ww - 2 * m + e) + std::fabs(sw - 2 * s + se);
                const bool horizontal = edgeH >= edgeV;
                // Which side of the pixel the edge is on (the steeper gradient), and the step across it.
                const double l1 = horizontal ? nn : ww, l2 = horizontal ? s : e;
                const double g1 = std::fabs(l1 - m), g2 = std::fabs(l2 - m);
                const bool first = g1 >= g2;
                const double gradient = 0.25 * std::max(g1, g2);
                double across = first ? -1.0 : 1.0;
                const double side = first ? l1 : l2;
                const double edgeLuma = 0.5 * (m + side);
                // Follow the edge both ways, half a pixel across toward that side, to where its luma leaves the edge's.
                const double ox = horizontal ? 0.0 : 0.5 * across, oy = horizontal ? 0.5 * across : 0.0;
                const double dx = horizontal ? 1.0 : 0.0, dy = horizontal ? 0.0 : 1.0;
                auto lumaAt = [&](double fx, double fy) {
                    fx = std::clamp(fx, 0.0, double(w - 1)), fy = std::clamp(fy, 0.0, double(h - 1));
                    const int x0 = int(std::floor(fx)), y0 = int(std::floor(fy));
                    const int x1 = std::min(x0 + 1, int(w) - 1), y1 = std::min(y0 + 1, int(h) - 1);
                    const double tx = fx - x0, ty = fy - y0;
                    const double a = luma[size_t(y0) * w + x0], b = luma[size_t(y0) * w + x1], c = luma[size_t(y1) * w + x0], d = luma[size_t(y1) * w + x1];
                    return (a + tx * (b - a)) + ty * ((c + tx * (d - c)) - (a + tx * (b - a)));
                };
                double px = x + ox, py = y + oy, qx = px, qy = py, dn = 0, dp = 0;
                bool doneN = false, doneP = false;
                double endN = 0, endP = 0;
                for (double step : steps) {
                    if (!doneN) {
                        px -= dx * step, py -= dy * step, dn += step;
                        endN = lumaAt(px, py) - edgeLuma;
                        doneN = std::fabs(endN) >= gradient;
                    }
                    if (!doneP) {
                        qx += dx * step, qy += dy * step, dp += step;
                        endP = lumaAt(qx, qy) - edgeLuma;
                        doneP = std::fabs(endP) >= gradient;
                    }
                    if (doneN && doneP) break;
                }
                // The nearer end decides: the pixel blends across the edge only if the luma there goes the other way
                // from its own (it is on the edge's step), by how far it is from that end.
                const bool nearerN = dn < dp;
                const double endLuma = nearerN ? endN : endP;
                const bool step = (m - edgeLuma < 0) != (endLuma < 0);
                const double edgeBlend = step ? 0.5 - std::min(dn, dp) / (dn + dp) : 0.0;
                const double blend = std::max(edgeBlend, subBlend);
                if (blend <= 0) continue;
                float o[3];
                colourAt(x + (horizontal ? 0.0 : across * blend), y + (horizontal ? across * blend : 0.0), o);
                for (int c = 0; c < 3; ++c) out[(size_t(y) * w + x) * 3 + c] = o[c];
            }
        });
        rgb.swap(out);
    }
};

class ObjectWarp {
public:
    struct Options {
        size_t rays = 60000;     // the fine grid's rays, at most (its stride from it)
        double jump = 0.03;      // corners whose depths differ by more (relative) are another surface: a ray a pixel
        unsigned rings = 3;      // the fine grid's stages, rings of equal area from the centre out (streamed)
        bool antialias = true;   // the finished picture through FXAA (Fxaa)
        bool packets = true;     // rays four at a time (Embree's packets), where the scene is triangles alone
        // The store's answer trusted where it came from the point's own size or the next (a curved scale's few cells are
        // its detail), or from up to trustUp sizes coarser with at least this share of the cells about the point holding
        // colour; else the colour interpolated from the trusted (fillNodes): a coarse answer from a few cells is a block.
        double trust = 0.15;
        int trustUp = 3;
        // The most sizes up a lookup climbs (ObjectStore::lookup's maxUp): an answer past trustUp weighs little in the
        // interpolation, and the climb through empty sizes was the dearest part of a drag step. -1: every size.
        int lookupUp = 5;
        // The fill of what the store did not answer for, by depth (pullPushDepth): sources whose depth is off by about this
        // share (relative, in lifted inverse depth) weigh little. 0: the plain fill (pullPush).
        double fillDepth = 0.06;
        // The fine grid coarse to fine (the user, 2026-11-22: "do the adaptive sampling"; Rhea's research refined "within a
        // variance"), where it is drawn as one ring (a drag's step): a block of 4 x 4 fine cells whose corners (the coarse
        // grid's nodes) are one smooth surface of about one colour is interpolated, not traced; another is split once in
        // four, each part again interpolated or traced whole. Colours alike: each channel's spread under adaptColour of
        // their mean brightness.
        bool adaptive = true;
        double adaptColour = 0.06;
        // With nothing in the store (the first frame of realtime): each hit's material colour (the CPU's), lit from the
        // camera, so that phase one has a first look before XPU2's first pictures fade in.
        bool firstLook = true;
        // View-dependent light (DESIGN.md 35; XPU2_SESSION_RHEA_SPECULAR): where the store's cells hold a surface's specular
        // light beside the light that was reflected toward the view that saw it, the specular light is made again for this
        // view: the reflectance they give times the light reflected toward this ray (ObjectStore::reflectedAt). specMax: the
        // most that reflectance may be (more is no mirror: transmission, a rough lobe), specShare: the least share of the
        // cells' weight that knew its reflection.
        bool specular = false;
        double specMax = 1.5, specShare = 0.3;
        bool specTrace = false;  // the reflected ray traced (a surface in the way: its colour), else the environment alone
        double specBlur = 0.15;  // the reflection's blur (radians): the environment's filtered over it, a surface's cells as wide
        // Edges by object and crease (DESIGN.md 38; XPU2_SESSION_RHEA_OBJECT_EDGES): grid corners of different objects, or
        // whose normals part by more than creaseCos, are no smooth surface (their pixels traced each); the fills take a
        // node's colour from its own object; a ray's lookups from its object's cells (ObjectStore::Options::byObject).
        bool objectEdges = false;
        double creaseCos = 0.8;
        // The light smoothed over its surfaces (DESIGN.md 39; XPU2_SESSION_RHEA_SMOOTH): the fine grid's light, the cells'
        // albedo divided out where it is at least smoothFloor (else the colour itself), through smoothPasses a-trous passes
        // (rheastore::smoothNode) kept to a node's object, plane (smoothDepth, lifted depth's share), facing (normals' cosine
        // to smoothNormal) and light (smoothLight, luminance's share), then multiplied back. Where the fine grid is drawn as
        // one ring (a drag's step, the adaptive pass), on the card where it takes them (cardSmooth), else on the CPU.
        bool smooth = false;
        // Rhea Draft (DESIGN.md 42): black lines where MoonLightIPR's Draft draws them (rheastore::draftEdge: silhouettes,
        // objects' boundaries, creases), over the smoothed light (smooth, kept from crossing a line) times the surface's
        // colour; what the store does not know a flat fill (the first look's colour under a soft light), not the fill from
        // around. lineSamples: a pixel's fixed places, lineSamples x lineSamples; lineApart: the rays' spacing, which is the
        // line's width (pixels; 0: one pixel a 1100 of width, one at least; it was MoonLightIPR's two, and the user found
        // the lines too thick, 2026-11-28); lineColour: the ink (black).
        bool draft = false;
        int lineSamples = 1;
        double lineApart = 0, lineCrease = 0.82, linePlane = 0.03;
        float lineColour[3] = {0, 0, 0};
        int smoothPasses = 3;
        double smoothDepth = 0.02, smoothNormal = 32, smoothLight = 0.25, smoothFloor = 0.02;
        unsigned threads = 8;
    };
    Options op;
    size_t specularRebuilt = 0;  // the last view's nodes whose specular light was made again (op.specular)
    size_t rays = 0, edgeRays = 0;
    unsigned stride = 0, stages = 0;
    double seconds = 0, firstSeconds = 0, unknown = 0;  // the view's time, its first picture's, the rays the store had nothing for
    // The rays given the first look (the store empty: the material's colour lit from the camera, or the environment's grey):
    // the store knew 1 - unknown - firstLooks of the view (rhea_cache.h's measure of a store taken back).
    double firstLooks = 0;
    // Where the time went (seconds): the coarse grid's rays, its picture (sampled, blurred, written), the rings' grid rays,
    // their pictures (the edges' own rays among them), FXAA, and the stages shown (stage(): the session's part).
    double coarseRaySeconds = 0, coarsePictureSeconds = 0, ringRaySeconds = 0, ringPictureSeconds = 0, fxaaSeconds = 0, stageSeconds = 0;
    bool packetsUsed = false;
    // The graphics card's first hits (the session's, XPU2's launch mode 5): count rays at once into hits, each as the path
    // tracer's own; false where the card does not take them now (a frame's launches out), the CPU tracing them. A stage's
    // rays go to it together (the coarse grid, a ring, a ring's edges), the store's lookups staying on the CPU's threads
    // (the user, 2026-11-22: "have Rhea phase 1 use both gpu/cpu"). Empty: the CPU alone.
    // looks: each ray's lookup in the store's copy on the card (cardStore), where wanted (null: hits alone).
    std::function<bool(const surface::Ray*, size_t, resume::Hit*, xpu2::interactive::rheastore::Look*)> cardTrace;
    // cardTrace in two (the card's launch queued, then its hits waited for): the fine grid's rays, every ring's, sent once
    // the coarse grid is traced and traced while the coarse picture is made and shown. Either empty: the rings' rays as
    // they come.
    std::function<bool(const surface::Ray*, size_t, bool)> cardBegin;
    std::function<bool(resume::Hit*, xpu2::interactive::rheastore::Look*)> cardEnd;
    // The store's lookups on the card beside its first hits (DESIGN.md 37; XPU2_SESSION_RHEA_GPU_STORE): the session's
    // copy of the store brought up to date and this view's lookup settings sent; true where the card answers this view's
    // lookups (its hits' looks then used in place of the CPU's, the environment's and the specular light's own work
    // left to the CPU). Empty: the CPU's lookups.
    std::function<bool(const xpu2::interactive::rheastore::View&)> cardStore;
    size_t cardLooked = 0;  // the last view's hits whose colour the card looked up
    // The smoothing on the card (launch mode 6): nodes, light in and out, settings, passes; false where it does not take it.
    std::function<bool(const xpu2::interactive::rheastore::SmoothNode*, float*, const xpu2::interactive::rheastore::SmoothParams&, int)>
        cardSmooth;
    // Rhea Draft's lines on the card (launch mode 7): the chief rays' camera, the settings, a float a pixel out; false where
    // it does not take them (the CPU finds them).
    std::function<bool(const surface::Camera&, const xpu2::interactive::rheastore::LineSettings&, float*)> cardLines;
    double lineSeconds = 0;  // the last view's lines, and whether the card found them
    bool linesOnCard = false;
    std::vector<float> lines;  // the last view's line coverage, a pixel each (op.draft)
    double smoothSeconds = 0;  // the last view's smoothing, and whether the card did it
    bool smoothedOnCard = false;
    // The last view's rays the card traced, and the time its calls took (rays out, launch, hits back; a begun launch's from
    // its end's wait alone).
    size_t cardRays = 0;
    double cardSeconds = 0;
    // The last view's CPU time in the rays' making (rows, rays), the hits' shading (the store's lookups), the fills.
    double rowsSeconds = 0, shadeSeconds = 0, fillSeconds = 0;
    // The last view's fine nodes interpolated, not traced (Options::adaptive), and its time choosing them.
    size_t interpolated = 0;
    double adaptSeconds = 0;

    // A view of the store through camera nv, by the scene's first hits: each pixel's colour (rgb), lifted depth w (-1 the
    // environment), depth (0 none), state (1 drawn, 2 filled from around it) and doubt (0 to 1). Streamed (the user,
    // 2026-11-22: "the reconstructions should be streamed. the user should be able to see the radial topology updating
    // in realtime"): stage() is called once the whole picture is there from the coarse grid, then after each ring of the
    // fine grid from the centre out; false from it stops the drawing where it stands (the next move has come).
    bool draw(const View& nv, const async::CpuScene& scene, const ObjectStore& store, unsigned w, unsigned h, std::vector<float>& color,
              std::vector<double>& outW, std::vector<float>& outDepth, std::vector<std::uint8_t>& state, std::vector<float>& doubt,
              const std::function<bool()>& stage = {}) {
        using Clock = std::chrono::steady_clock;
        const auto began = Clock::now();
        auto since = [](Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); };
        const size_t n = size_t(w) * h;
        rays = edgeRays = 0, stages = 0, unknown = 0, firstSeconds = 0, firstLooks = 0;
        coarseRaySeconds = coarsePictureSeconds = ringRaySeconds = ringPictureSeconds = fxaaSeconds = stageSeconds = 0;
        cardRays = 0, cardSeconds = 0, rowsSeconds = shadeSeconds = fillSeconds = 0, interpolated = 0, adaptSeconds = 0;
        if (!w || !h) return false;
        const double angle = ObjectStore::pixelAngle(nv);
        if (!(angle > 0)) return false;
        const unsigned threads = std::max(1u, op.threads);
        const double cx = 0.5 * w, cy = 0.5 * h, half = std::sqrt(cx * cx + cy * cy);
        stride = unsigned(std::max(1.0, std::ceil(std::sqrt(double(n) / double(std::max<size_t>(op.rays, 1000))))));
        const unsigned S = stride * 4;
        color.assign(n * 3, 0.0f), outW.assign(n, -1.0), outDepth.assign(n, 0.0f), state.assign(n, 2), doubt.assign(n, 1.0f);
        // Packets where every mesh is triangles: the curves' and points' own intersectors take one ray at a time.
        packetsUsed = op.packets && trianglesAlone(scene);
        std::atomic<size_t> traced{0}, empty{0}, edge{0}, looked{0}, specularMade{0};
        // A hit's colour from the store (or the environment's), into a node: trusted where the store's cells about it hold
        // it (op.trust, op.trustUp), else weighed little in the interpolation. The store empty (realtime's first frame):
        // the first look, the hit's material colour lit from the camera.
        const bool firstLook = op.firstLook && store.empty();
        if (op.draft) findLines(nv, scene, w, h, threads);
        else lines.clear();
        // The card's copy of the store, where it answers this view's lookups (not the albedo composite's finer table).
        bool cardLooks = false;
        cardLooked = 0;
        // (Not while the store is sparse: the card's lookups know no slopes yet, DESIGN.md 43.)
        if (cardStore && cardTrace && !store.op.albedo && !store.op.sparse && !store.empty()) {
            xpu2::interactive::rheastore::View sv;
            store.cardView(sv);
            sv.lookupUp = op.lookupUp, sv.angle = angle, sv.kind = int(nv.kind), sv.parts = op.specular ? 1 : 0;
            for (int i = 0; i < 4; ++i)
                for (int j = 0; j < 4; ++j) sv.toCamera[i][j] = nv.toCamera[i][j];
            const D3 f = nv.focal();
            sv.fp[0] = f.x, sv.fp[1] = f.y, sv.fp[2] = f.z;
            cardLooks = cardStore(sv);
        }
        std::atomic<size_t> lookedOnCard{0};
        using Look = xpu2::interactive::rheastore::Look;
        auto shade = [&](const async::CpuBackend& backend, const surface::Ray& ray, const resume::Hit& hit, Node& o, const Look* look = nullptr) {
            if (hit.geom == ~0u) {
                o.kind = 2;
                o.known = store.skyAt(D3{ray.direction.x, ray.direction.y, ray.direction.z}, o.rgb);
                o.conf = o.known ? 1.0f : 0.0f, o.weight = o.known ? 1.0f : 0.0f;
                if (!o.known && firstLook) o.rgb[0] = o.rgb[1] = o.rgb[2] = 0.5f, o.known = true, o.weight = 1.0f, looked.fetch_add(1, std::memory_order_relaxed);
                return;
            }
            o.kind = 1;
            o.obj = hit.geom + 1;
            const double d = nv.depthOf(nv.camera(hit.point));
            o.depth = float(d), o.w = nv.wOf(d);
            const D3 nn = nv.toward(D3{hit.normal.x, hit.normal.y, hit.normal.z}, hit.point);
            o.n[0] = float(nn.x), o.n[1] = float(nn.y), o.n[2] = float(nn.z);
            int up = 0;
            ObjectStore::Parts parts;
            const double foot = ObjectStore::footprint(nv, angle, d);
            bool found;
            if (look) {  // the card's lookup (rhea_store_core.h: ObjectStore::lookup's arithmetic)
                found = look->found != 0;
                for (int ch = 0; ch < 3; ++ch) {
                    o.rgb[ch] = look->rgb[ch];
                    parts.colour[ch] = look->rgb[ch], parts.diffuse[ch] = look->diffuse[ch], parts.emission[ch] = look->emission[ch];
                    parts.specular[ch] = look->specular[ch], parts.reflected[ch] = look->reflected[ch];
                }
                o.conf = look->conf, up = look->up, parts.share = look->share;
                for (int ch = 0; ch < 3; ++ch) parts.albedo[ch] = look->albedo[ch];
                lookedOnCard.fetch_add(1, std::memory_order_relaxed);
            } else
                found = store.lookup(hit.point, nn, D3{ray.direction.x, ray.direction.y, ray.direction.z}, foot, o.rgb, o.conf, &up, op.lookupUp,
                                     o.obj, op.specular || op.smooth ? &parts : nullptr);
            o.known = found && (up <= 1 || (up <= op.trustUp && o.conf >= op.trust));
            if (found)
                for (int ch = 0; ch < 3; ++ch) o.a[ch] = parts.albedo[ch];
            // The specular light made again for this view: the reflectance the cells saw times the light reflected now.
            if (found && op.specular && parts.share >= op.specShare && scene.plan) {
                const double spec = parts.specular[0] + parts.specular[1] + parts.specular[2];
                const double all = parts.colour[0] + parts.colour[1] + parts.colour[2];
                float now[3];
                if (spec > 0.02 * all + 1e-4 && store.reflectedAt(backend, *scene.plan, ray, hit, foot, op.specBlur, op.specTrace, now)) {
                    for (int ch = 0; ch < 3; ++ch) {
                        // A reflectance past specMax is no mirror's (light through glass, a rough lobe): kept as seen.
                        const double was = parts.reflected[ch], k = was > 1e-4 ? parts.specular[ch] / was : -1.0;
                        const double rest = std::max(0.0, double(parts.colour[ch]) - parts.specular[ch]);
                        o.rgb[ch] = float(k >= 0 && k <= op.specMax ? rest + k * now[ch] : parts.colour[ch]);
                    }
                    specularMade.fetch_add(1, std::memory_order_relaxed);
                }
            }
            o.weight = o.known ? 1.0f : found ? float(0.25 * std::max(0.0f, o.conf) / (1.0 + std::max(0, up - op.trustUp))) : 0.0f;
            if ((!found && firstLook) || (op.draft && !o.known)) {
                surface::Lambert l{};
                backend.material(hit, ray, l);
                o.a[0] = l.albedo.x, o.a[1] = l.albedo.y, o.a[2] = l.albedo.z;
                const double dl = std::sqrt(double(ray.direction.x) * ray.direction.x + double(ray.direction.y) * ray.direction.y +
                                            double(ray.direction.z) * ray.direction.z);
                const double nl = std::sqrt(nn.x * nn.x + nn.y * nn.y + nn.z * nn.z);
                const double facing = dl > 0 && nl > 0 ? std::fabs(nn.x * ray.direction.x + nn.y * ray.direction.y + nn.z * ray.direction.z) / (dl * nl) : 1.0;
                const double lit = 0.35 + 0.65 * facing;
                const double base[3] = {l.albedo.x, l.albedo.y, l.albedo.z};
                // A dark material (black paint, glass, water, metal: next to no diffuse colour) keeps its own darkness, its
                // shape read from the sky reflected at grazing angles (Schlick's Fresnel from a dielectric's 4%): the
                // store's sky in the mirror direction where it has it, else a pale grey. It was clay grey, which "doesn't
                // look good" (the user, 2026-11-22, of a black car). Light materials as they were: a floor's far
                // grazing part kept its own colour, not the sky's.
                const double lum = 0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2];
                const double dark = std::clamp((0.3 - lum) / 0.2, 0.0, 1.0);
                double sheen[3] = {0, 0, 0};
                if (dark > 0 && dl > 0 && nl > 0) {
                    const double c = 1.0 - std::min(1.0, facing), c2 = c * c;
                    const double fresnel = 0.04 + 0.96 * c2 * c2 * c;
                    const D3 d{ray.direction.x / dl, ray.direction.y / dl, ray.direction.z / dl}, nh{nn.x / nl, nn.y / nl, nn.z / nl};
                    const double dn = d.x * nh.x + d.y * nh.y + d.z * nh.z;
                    const D3 mirror{d.x - 2 * dn * nh.x, d.y - 2 * dn * nh.y, d.z - 2 * dn * nh.z};
                    float sky[3] = {0.6f, 0.6f, 0.62f};
                    store.skyAt(mirror, sky);
                    for (int ch = 0; ch < 3; ++ch) sheen[ch] = dark * fresnel * sky[ch];
                }
                o.rgb[0] = float(base[0] * lit + sheen[0] + l.emission.x), o.rgb[1] = float(base[1] * lit + sheen[1] + l.emission.y),
                o.rgb[2] = float(base[2] * lit + sheen[2] + l.emission.z);
                o.known = true, o.weight = 1.0f, o.conf = 0.0f, o.fill = true;
                // Rhea Draft: lit as the view is (lightFills), here where every fill is made, a grid node's and a pixel's
                // own ray's alike (the pixels between nodes stayed dark when only the nodes were, 2026-11-28).
                if (op.draft && draftLightSet_) {
                    const float* lightHere = fillLight(o.obj);
                    for (int ch = 0; ch < 3; ++ch) o.rgb[ch] *= lightHere[ch];
                    o.fillLit = true;
                }
                looked.fetch_add(1, std::memory_order_relaxed);
            }
        };
        // Rays through raster places (x, y), each node shaded: four at a time where packets may be used. Adds the rays and
        // those the store had nothing for to the counts (once a row: one atomic each, not one a ray).
        auto shadeAll = [&](Batch& b) {
            async::CpuBackend backend{scene};
            surface::Ray ray4[4];
            Node* to4[4];
            int k = 0;
            size_t made = 0, unknownHere = 0;
            auto flush = [&] {
                resume::Hit hits[4];
                if (packetsUsed && k > 1) trace4(scene, backend, ray4, k, hits);
                else
                    for (int q = 0; q < k; ++q) hits[q] = backend.trace(ray4[q]);
                for (int q = 0; q < k; ++q) {
                    shade(backend, ray4[q], hits[q], *to4[q]);
                    ++made;
                    if (!to4[q]->known) ++unknownHere;
                }
                k = 0;
            };
            for (size_t i = 0; i < b.to.size(); ++i) {
                surface::Ray ray;
                if (!nv.ray(b.x[i], b.y[i], ray)) {
                    b.to[i]->kind = 3;
                    continue;
                }
                ray.mask = 1u;
                ray4[k] = ray, to4[k] = b.to[i], ++k;
                if (k == 4) flush();
            }
            if (k) flush();
            traced.fetch_add(made, std::memory_order_relaxed);
            empty.fetch_add(unknownHere, std::memory_order_relaxed);
        };
        // Every row's rays on the card at once (cardTrace), each row then shaded on a CPU thread (the store's lookups). False
        // where the card did not take them: the caller's rows then traced on the CPU (shadeAll), as before.
        // Each row's rays made (nv.ray; a place with none, kind 3), all of them into one list (flat), each row's first at at.
        auto makeRays = [&](std::vector<Batch>& rowsOf, std::vector<surface::Ray>& flat, std::vector<size_t>& at) -> size_t {
            const auto t = Clock::now();
            parallel(threads, rowsOf.size(), [&](size_t r) {
                Batch& b = rowsOf[r];
                b.rays.clear(), b.rto.clear();
                for (size_t i = 0; i < b.to.size(); ++i) {
                    surface::Ray ray;
                    if (!nv.ray(b.x[i], b.y[i], ray)) {
                        b.to[i]->kind = 3;
                        continue;
                    }
                    ray.mask = 1u;
                    b.rays.push_back(ray), b.rto.push_back(b.to[i]);
                }
            });
            at.assign(rowsOf.size() + 1, 0);
            for (size_t r = 0; r < rowsOf.size(); ++r) at[r + 1] = at[r] + rowsOf[r].rays.size();
            flat.resize(at.back());
            parallel(threads, rowsOf.size(), [&](size_t r) { std::copy(rowsOf[r].rays.begin(), rowsOf[r].rays.end(), flat.begin() + at[r]); });
            rowsSeconds += since(t);
            return at.back();
        };
        // Each row's nodes shaded from their hits (a row a CPU thread): the store's lookups.
        auto shadeHits = [&](std::vector<Batch>& rowsOf, const std::vector<surface::Ray>& rays, const std::vector<resume::Hit>& hits,
                             const std::vector<size_t>& at, const std::vector<Look>* looks = nullptr) {
            const auto t = Clock::now();
            parallel(threads, rowsOf.size(), [&](size_t r) {
                async::CpuBackend backend{scene};
                size_t unknownHere = 0;
                for (size_t k = at[r]; k < at[r + 1]; ++k) {
                    Node& o = *rowsOf[r].rto[k - at[r]];
                    shade(backend, rays[k], hits[k], o, looks ? &(*looks)[k] : nullptr);
                    if (!o.known) ++unknownHere;
                }
                traced.fetch_add(at[r + 1] - at[r], std::memory_order_relaxed);
                empty.fetch_add(unknownHere, std::memory_order_relaxed);
            });
            shadeSeconds += since(t);
        };
        auto shadeOnCard = [&](std::vector<Batch>& rowsOf) -> bool {
            if (!cardTrace || rowsOf.empty()) return false;
            const size_t count = makeRays(rowsOf, cardRays_, rowAt_);
            if (!count) return true;
            cardHits_.resize(count);
            if (cardLooks) cardLooks_.resize(count);
            const auto sent = Clock::now();
            if (!cardTrace(cardRays_.data(), count, cardHits_.data(), cardLooks ? cardLooks_.data() : nullptr)) return false;
            cardSeconds += since(sent);
            cardRays += count;
            shadeHits(rowsOf, cardRays_, cardHits_, rowAt_, cardLooks ? &cardLooks_ : nullptr);
            return true;
        };
        // Each row's rays traced and shaded: on the card where it takes them, else on the CPU a row a thread.
        auto shadeRows = [&](std::vector<Batch>& rowsOf) {
            if (shadeOnCard(rowsOf)) return;
            const auto t = Clock::now();
            parallel(threads, rowsOf.size(), [&](size_t r) { shadeAll(rowsOf[r]); });
            shadeSeconds += since(t);  // the CPU's tracing with its shading
        };
        auto radius = [&](double x, double y) { return std::sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy)); };
        // A grid's nodes between two radii into rows (rowsOf, a batch each).
        auto ringRows = [&](Grid& g, double from, double to, std::vector<Batch>& rowsOf) {
            const auto t = Clock::now();
            rowsOf.resize(g.gh);
            parallel(threads, g.gh, [&](size_t j) {
                Batch& b = rowsOf[j];
                b.clear();
                for (unsigned i = 0; i < g.gw; ++i) {
                    const double x = std::min<double>(double(i) * g.step, w - 1) + 0.5, y = std::min<double>(double(j) * g.step, h - 1) + 0.5;
                    const double r = radius(x, y);
                    if (r < from || r >= to) continue;
                    b.add(x, y, &g.nodes[j * g.gw + i]);
                }
            });
            rowsSeconds += since(t);
        };
        // The fine grid's rays, every ring's, on the card ahead (cardBegin): sent once the coarse grid is traced, traced
        // while the coarse picture is made and shown, waited for at the first ring (fineEnd). fineAt_: each fine node's
        // ray and hit in fineRays_ and fineHits_ (-1: none, its kind 3).
        bool fineAhead = false, fineWaiting = false;
        auto fineEnd = [&]() -> bool {
            if (fineWaiting) {
                const auto t = Clock::now();
                fineWaiting = false;
                if (!cardEnd(fineHits_.data(), cardLooks ? fineLooks_.data() : nullptr)) fineAhead = false;
                cardSeconds += since(t);
            }
            return fineAhead;
        };
        // (A view stopped before the first ring still waits for the card's launch: its buffers are the next one's.)
        struct WaitForCard {
            const std::function<bool()> end;
            ~WaitForCard() { end(); }
        } waitForCard{[&] { return fineEnd(); }};
        auto sendFine = [&] {
            if (!cardBegin || !cardEnd) return;
            layGrid(fine, stride, w, h);
            ringRows(fine, 0.0, 1e30, fineRows_);
            const size_t count = makeRays(fineRows_, fineRays_, fineRowAt_);
            if (!count) return;
            fineHits_.resize(count);
            if (cardLooks) fineLooks_.resize(count);
            const auto sent = Clock::now();
            if (!cardBegin(fineRays_.data(), count, cardLooks)) return;
            cardSeconds += since(sent);
            cardRays += count;
            fineAt_.assign(fine.nodes.size(), -1);
            parallel(threads, fineRows_.size(), [&](size_t r) {
                const Batch& b = fineRows_[r];
                for (size_t k = 0; k < b.rto.size(); ++k) fineAt_[size_t(b.rto[k] - fine.nodes.data())] = std::int64_t(fineRowAt_[r] + k);
            });
            fineAhead = fineWaiting = true;
        };
        // A grid's nodes traced between two radii, a row at a time, then those the store had nothing for filled from the
        // known around them. The fine grid's from the card's hits ahead where they were sent (sendFine).
        auto trace = [&](Grid& g, double from, double to) {
            ringRows(g, from, to, rows_);
            if (&g == &fine && fineAhead && fineEnd()) {
                const auto t = Clock::now();
                parallel(threads, rows_.size(), [&](size_t r) {
                    async::CpuBackend backend{scene};
                    size_t made = 0, unknownHere = 0;
                    for (Node* o : rows_[r].to) {
                        const std::int64_t k = fineAt_[size_t(o - fine.nodes.data())];
                        if (k < 0) continue;  // no ray there (its kind 3)
                        shade(backend, fineRays_[size_t(k)], fineHits_[size_t(k)], *o, cardLooks ? &fineLooks_[size_t(k)] : nullptr);
                        ++made;
                        if (!o->known) ++unknownHere;
                    }
                    traced.fetch_add(made, std::memory_order_relaxed);
                    empty.fetch_add(unknownHere, std::memory_order_relaxed);
                });
                shadeSeconds += since(t);
            } else
                shadeRows(rows_);
            const auto t = Clock::now();
            fillNodes(g, op.fillDepth, op.objectEdges);
            fillSeconds += since(t);
        };
        // Two surface nodes on one object and no crease between them (op.objectEdges; else always).
        auto oneSurface = [&](const Node* a, const Node* b) {
            if (!op.objectEdges || a->kind != 1 || b->kind != 1) return true;
            if (a->obj != b->obj) return false;
            const double c = double(a->n[0]) * b->n[0] + double(a->n[1]) * b->n[1] + double(a->n[2]) * b->n[2];
            const double la = std::sqrt(double(a->n[0]) * a->n[0] + double(a->n[1]) * a->n[1] + double(a->n[2]) * a->n[2]);
            const double lb = std::sqrt(double(b->n[0]) * b->n[0] + double(b->n[1]) * b->n[1] + double(b->n[2]) * b->n[2]);
            return !(la > 0 && lb > 0) || c >= op.creaseCos * la * lb;
        };
        // Each pixel's colour from a grid: bilinear between its cell's corners; smooth: they are one smooth surface.
        auto sample = [&](const Grid& g, unsigned x, unsigned y, Pixel& p, bool* smoothOut) {
            const auto c = corners(g, x, y);
            const unsigned i = x / g.step, j = y / g.step;
            const double x0 = double(i) * g.step, x1 = std::min<double>(double(i + 1) * g.step, w - 1);
            const double y0 = double(j) * g.step, y1 = std::min<double>(double(j + 1) * g.step, h - 1);
            const double tx = x1 > x0 ? std::clamp((x - x0) / (x1 - x0), 0.0, 1.0) : 0.0, ty = y1 > y0 ? std::clamp((y - y0) / (y1 - y0), 0.0, 1.0) : 0.0;
            const double wt[4] = {(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty};
            double rgb[3] = {0, 0, 0}, conf = 0, sw = 0;
            int best = -1;
            for (int k = 0; k < 4; ++k) {
                if (c[k]->kind == 0 || c[k]->kind == 3) continue;
                for (int ch = 0; ch < 3; ++ch) rgb[ch] += wt[k] * c[k]->rgb[ch];
                conf += wt[k] * (c[k]->known ? c[k]->conf : 0.0f);
                sw += wt[k];
                if (best < 0 || wt[k] > wt[best]) best = k;
            }
            p = Pixel{};
            if (sw > 0)
                for (int ch = 0; ch < 3; ++ch) p.rgb[ch] = float(rgb[ch] / sw);
            p.conf = sw > 0 ? float(conf / sw) : 0.0f;
            p.w = best >= 0 && c[best]->kind == 1 ? c[best]->w : -1.0;
            p.depth = best >= 0 && c[best]->kind == 1 ? c[best]->depth : 0.0f;
            if (smoothOut) {
                bool ok = true;
                for (int k = 0; k < 4 && ok; ++k) ok = c[k]->kind == c[0]->kind && (c[k]->kind == 1 || c[k]->kind == 2);
                if (ok && c[0]->kind == 1) {
                    double lo = c[0]->w, hi = c[0]->w;
                    for (int k = 1; k < 4; ++k) lo = std::min(lo, c[k]->w), hi = std::max(hi, c[k]->w);
                    ok = lo > 0 && (hi - lo) <= op.jump * hi;
                    for (int k = 1; k < 4 && ok; ++k) ok = oneSurface(c[0], c[k]);
                }
                *smoothOut = ok;
            }
        };
        auto write = [&](size_t i, const Pixel& p) {
            for (int ch = 0; ch < 3; ++ch) color[i * 3 + ch] = p.rgb[ch];
            outW[i] = p.w, outDepth[i] = p.depth;
            state[i] = p.conf > 0 ? 1 : 2;
            doubt[i] = std::clamp(1.0f - p.conf, 0.0f, 1.0f);
        };
        auto showStage = [&] {
            if (!stage) return true;
            const auto t = Clock::now();
            const bool go = stage();
            stageSeconds += since(t);
            return go;
        };
        // The coarse grid over the whole picture: the first picture.
        auto t0 = Clock::now();
        layGrid(coarse, S, w, h);
        trace(coarse, 0.0, 1e30);
        coarseRaySeconds = since(t0);
        t0 = Clock::now();
        outside.resize(n);
        // Each pixel a cubic B-spline over the 4 x 4 coarse nodes about it (the user, 2026-11-22: the pictures were most of a
        // drag's step): smooth, with no grid steps along silhouettes, in one pass. It was bilinear then blurred over about a
        // step by two box passes each way at the picture's size, 5 ms of the car's 34. Its depth the nearest surface corner's.
        parallel(threads, h, [&](size_t yy) {
            const unsigned y = unsigned(yy);
            const unsigned gw = coarse.gw, gh = coarse.gh;
            const unsigned j = std::min(y / S, gh - 2);
            const double y0 = double(j) * S, y1 = std::min<double>(double(j + 1) * S, h - 1);
            const double ty = y1 > y0 ? std::clamp((y - y0) / (y1 - y0), 0.0, 1.0) : 0.0;
            double wy[4];
            cubicBSpline(ty, wy);
            for (unsigned x = 0; x < w; ++x) {
                const unsigned i = std::min(x / S, gw - 2);
                const double x0 = double(i) * S, x1 = std::min<double>(double(i + 1) * S, w - 1);
                const double tx = x1 > x0 ? std::clamp((x - x0) / (x1 - x0), 0.0, 1.0) : 0.0;
                double wx[4];
                cubicBSpline(tx, wx);
                double rgb[3] = {0, 0, 0}, conf = 0, sw = 0;
                for (int b = 0; b < 4; ++b) {
                    const unsigned jj = unsigned(std::clamp(int(j) - 1 + b, 0, int(gh) - 1));
                    for (int a = 0; a < 4; ++a) {
                        const Node& o = coarse.nodes[size_t(jj) * gw + unsigned(std::clamp(int(i) - 1 + a, 0, int(gw) - 1))];
                        if (o.kind == 0 || o.kind == 3) continue;
                        const double k = wx[a] * wy[b];
                        for (int ch = 0; ch < 3; ++ch) rgb[ch] += k * o.rgb[ch];
                        conf += k * (o.known ? o.conf : 0.0f);
                        sw += k;
                    }
                }
                Pixel p;
                if (sw > 0) {
                    for (int ch = 0; ch < 3; ++ch) p.rgb[ch] = float(rgb[ch] / sw);
                    p.conf = float(conf / sw);
                }
                const Node* near = &coarse.nodes[size_t(j + (ty >= 0.5)) * gw + i + (tx >= 0.5)];
                p.w = near->kind == 1 ? near->w : -1.0, p.depth = near->kind == 1 ? near->depth : 0.0f;
                const size_t at = size_t(y) * w + x;
                outside[at] = p;
                write(at, p);
            }
        });
        coarsePictureSeconds = since(t0);
        firstSeconds = since(began);
        ++stages;
        auto finish = [&] {
            edgeRays = edge.load();
            rays = traced.load();
            unknown = rays ? double(empty.load()) / double(rays) : 0.0;
            firstLooks = rays ? double(looked.load()) / double(rays) : 0.0;
            specularRebuilt = specularMade.load();
            cardLooked = lookedOnCard.load();
            seconds = since(began);
        };
        if (!showStage()) {
            finish();
            return true;
        }
        // Coarse to fine (op.adaptive) where the fine grid is drawn as one ring (a drag's step): its nodes chosen as the
        // blocks ask, so its rays are not sent ahead.
        const bool adaptiveNow = op.adaptive && std::max(1u, op.rings) == 1 && S == 4 * stride;
        // The fine grid's rays, every ring's, to the card in one launch once the first picture is out (sent before it, their
        // making, 3 ms on the user's car, held the first picture back); each ring shaded from their hits.
        if (!adaptiveNow) sendFine();
        // The fine grid coarse to fine: the coarse grid's nodes are the fine grid's every fourth; a block of 4 x 4 fine cells
        // whose corners are one smooth surface of about one colour interpolated, another split once in four (its middle
        // nodes traced), each part interpolated or traced whole; then the fill (as trace's).
        auto adaptiveFine = [&] {
            const auto began = Clock::now();
            const unsigned fw = fine.gw, fh = fine.gh;
            fineSet_.assign(size_t(fw) * fh, 0);
            auto node = [&](unsigned i, unsigned j) -> Node& { return fine.nodes[size_t(j) * fw + i]; };
            auto setAt = [&](unsigned i, unsigned j) -> std::uint8_t& { return fineSet_[size_t(j) * fw + i]; };
            for (unsigned cj = 0; cj < coarse.gh; ++cj)
                for (unsigned ci = 0; ci < coarse.gw; ++ci) {
                    const unsigned i = std::min(4 * ci, fw - 1), j = std::min(4 * cj, fh - 1);
                    node(i, j) = coarse.nodes[size_t(cj) * coarse.gw + ci];
                    setAt(i, j) = 1;
                }
            // One smooth surface (or the environment) of about one colour at the four corners of [i0, i1] x [j0, j1].
            auto smooth = [&](unsigned i0, unsigned j0, unsigned i1, unsigned j1) {
                const Node* c[4] = {&node(i0, j0), &node(i1, j0), &node(i0, j1), &node(i1, j1)};
                const std::uint8_t kind = c[0]->kind;
                if (kind != 1 && kind != 2) return false;
                double lo = c[0]->w, hi = c[0]->w, mean = 0;
                for (const Node* o : c) {
                    if (o->kind != kind) return false;
                    lo = std::min(lo, o->w), hi = std::max(hi, o->w);
                    mean += 0.25 * (0.2126 * o->rgb[0] + 0.7152 * o->rgb[1] + 0.0722 * o->rgb[2]);
                }
                if (kind == 1 && !(lo > 0 && (hi - lo) <= op.jump * hi)) return false;
                for (int k = 1; k < 4; ++k)
                    if (!oneSurface(c[0], c[k])) return false;
                const double tolerance = op.adaptColour * std::max(0.02, mean);
                for (int ch = 0; ch < 3; ++ch) {
                    float a = c[0]->rgb[ch], b = a;
                    for (const Node* o : c) a = std::min(a, o->rgb[ch]), b = std::max(b, o->rgb[ch]);
                    if (b - a > tolerance) return false;
                }
                return true;
            };
            // The nodes [i0, i1] x [j0, j1] owns not yet made, bilinear from its corners. A part owns its inside and its top
            // and left sides, its right and bottom too at the grid's edge: the parts of a level never share a node, so they
            // are interpolated in parallel (a smooth neighbour's side is the same line between the same two corners).
            std::atomic<size_t> madeHere{0};
            auto interpolate = [&](unsigned i0, unsigned j0, unsigned i1, unsigned j1) {
                const Node* c[4] = {&node(i0, j0), &node(i1, j0), &node(i0, j1), &node(i1, j1)};
                const bool known = c[0]->known && c[1]->known && c[2]->known && c[3]->known;
                const unsigned iEnd = i1 == fw - 1 ? i1 : i1 - 1, jEnd = j1 == fh - 1 ? j1 : j1 - 1;
                size_t made = 0;
                for (unsigned j = j0; j <= jEnd; ++j)
                    for (unsigned i = i0; i <= iEnd; ++i) {
                        if (setAt(i, j)) continue;
                        const double tx = i1 > i0 ? double(i - i0) / (i1 - i0) : 0.0, ty = j1 > j0 ? double(j - j0) / (j1 - j0) : 0.0;
                        const double wt[4] = {(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty};
                        Node o;
                        double w = 0, depth = 0, conf = 0, weight = 0, rgb[3] = {0, 0, 0}, alb[3] = {0, 0, 0};
                        for (int q = 0; q < 4; ++q) {
                            for (int ch = 0; ch < 3; ++ch) rgb[ch] += wt[q] * c[q]->rgb[ch], alb[ch] += wt[q] * c[q]->a[ch];
                            w += wt[q] * c[q]->w, depth += wt[q] * c[q]->depth, conf += wt[q] * c[q]->conf, weight += wt[q] * c[q]->weight;
                        }
                        for (int ch = 0; ch < 3; ++ch) o.rgb[ch] = float(rgb[ch]), o.a[ch] = float(alb[ch]);
                        o.w = w, o.depth = float(depth), o.conf = float(conf), o.weight = float(weight);
                        o.kind = c[0]->kind, o.known = known, o.obj = c[0]->obj;
                        for (int ch = 0; ch < 3; ++ch) o.n[ch] = c[0]->n[ch];
                        node(i, j) = o;
                        setAt(i, j) = 2;
                        ++made;
                    }
                madeHere.fetch_add(made, std::memory_order_relaxed);
            };
            using Part = std::array<unsigned, 4>;
            auto interpolateAll = [&](const std::vector<Part>& parts) {
                parallel(threads, parts.size(), [&](size_t k) { interpolate(parts[k][0], parts[k][1], parts[k][2], parts[k][3]); });
            };
            // The nodes [i0, i1] x [j0, j1] owns not yet made (as interpolate's), asked for.
            auto askOwned = [&](unsigned i0, unsigned j0, unsigned i1, unsigned j1, std::vector<std::pair<unsigned, unsigned>>& to) {
                const unsigned iEnd = i1 == fw - 1 ? i1 : i1 - 1, jEnd = j1 == fh - 1 ? j1 : j1 - 1;
                for (unsigned j = j0; j <= jEnd; ++j)
                    for (unsigned i = i0; i <= iEnd; ++i)
                        if (!setAt(i, j)) to.emplace_back(i, j);
            };
            // The nodes asked for, traced together (the card's or the CPU's), a row at a time.
            auto traceAsked = [&](const std::vector<std::pair<unsigned, unsigned>>& asked) {
                if (asked.empty()) return;
                rows_.resize(fh);
                for (auto& b : rows_) b.clear();
                for (const auto& [i, j] : asked) {
                    if (setAt(i, j)) continue;
                    setAt(i, j) = 1;
                    rows_[j].add(std::min<double>(double(i) * stride, w - 1) + 0.5, std::min<double>(double(j) * stride, h - 1) + 0.5, &node(i, j));
                }
                shadeRows(rows_);
            };
            std::vector<Part> refine, smoothParts;
            std::vector<std::pair<unsigned, unsigned>> asked;
            for (unsigned j0 = 0; j0 + 1 < fh; j0 += 4)
                for (unsigned i0 = 0; i0 + 1 < fw; i0 += 4) {
                    const unsigned i1 = std::min(i0 + 4, fw - 1), j1 = std::min(j0 + 4, fh - 1);
                    if (smooth(i0, j0, i1, j1)) {
                        smoothParts.push_back({i0, j0, i1, j1});
                        continue;
                    }
                    refine.push_back({i0, j0, i1, j1});
                    const unsigned im = std::min(i0 + 2, i1), jm = std::min(j0 + 2, j1);
                    for (const auto& p : {std::make_pair(im, j0), std::make_pair(i0, jm), std::make_pair(im, jm), std::make_pair(i1, jm),
                                          std::make_pair(im, j1)})
                        asked.push_back(p);
                }
            interpolateAll(smoothParts);
            const double choosing = std::chrono::duration<double>(Clock::now() - began).count();
            traceAsked(asked);
            const auto second = Clock::now();
            asked.clear(), smoothParts.clear();
            for (const auto& [i0, j0, i1, j1] : refine) {
                const unsigned im = std::min(i0 + 2, i1), jm = std::min(j0 + 2, j1);
                const unsigned part[4][4] = {{i0, j0, im, jm}, {im, j0, i1, jm}, {i0, jm, im, j1}, {im, jm, i1, j1}};
                for (const auto& p : part) {
                    if (p[2] <= p[0] || p[3] <= p[1]) continue;
                    if (smooth(p[0], p[1], p[2], p[3])) smoothParts.push_back({p[0], p[1], p[2], p[3]});
                    else askOwned(p[0], p[1], p[2], p[3], asked);
                }
            }
            interpolateAll(smoothParts);
            adaptSeconds = choosing + std::chrono::duration<double>(Clock::now() - second).count();
            traceAsked(asked);
            interpolated = madeHere.load();
            // Any node no part owned (none should be): traced.
            asked.clear();
            for (unsigned j = 0; j < fh; ++j)
                for (unsigned i = 0; i < fw; ++i)
                    if (!setAt(i, j)) asked.emplace_back(i, j);
            traceAsked(asked);
            const auto t = Clock::now();
            fillNodes(fine, op.fillDepth, op.objectEdges);
            fillSeconds += since(t);
            if (op.draft) lightFills(fine);
            if (op.smooth || op.draft) smoothGrid(fine, threads);
        };
        // The fine grid ring by ring, rings of equal area out to the picture's corners: each ring's pixels from the fine
        // grid (a ray a pixel in a cell its corners are not one smooth surface of, those rays a row's together), its outer
        // band going over to the coarse grid's until the next ring comes.
        if (!fineAhead) layGrid(fine, stride, w, h);  // (laid already where its rays went to the card ahead)
        const double reach = half + 2.0 * stride;
        const unsigned rings = std::max(1u, op.rings);
        const double band = std::max(4.0 * stride, 0.08 * half);
        inner.resize(n);
        have.assign(n, 0);
        double tracedTo = 0, validTo = 0;
        for (unsigned k = 1; k <= rings; ++k) {
            const bool last = k == rings;
            const double to = last ? reach : reach * std::sqrt(double(k) / rings);
            t0 = Clock::now();
            if (adaptiveNow) adaptiveFine();  // one ring: the whole fine grid, coarse to fine
            else trace(fine, tracedTo, to);
            ringRaySeconds += since(t0);
            t0 = Clock::now();
            tracedTo = to;
            // A pixel's fine colour once its cell's corners are all traced: up to a cell and a half inside the ring.
            const double valid = last ? reach : std::max(0.0, to - 1.5 * stride);
            const double from = validTo;
            // The pixels newly in reach: bilinear from the fine grid; a cell that is not one smooth surface, a ray of the
            // pixel's own. Those rays found a row at a time, then traced all together (the card's, or a row a CPU thread),
            // then each row's pixels made.
            edgeX_.resize(h), edgeNodes_.resize(h), edgeRows_.resize(h);
            parallel(threads, h, [&](size_t yy) {
                const unsigned y = unsigned(yy);
                std::vector<unsigned>& edges = edgeX_[y];
                edges.clear();
                for (unsigned x = 0; x < w; ++x) {
                    const size_t i = size_t(y) * w + x;
                    const double r = radius(x + 0.5, y + 0.5);
                    if (r >= valid || have[i] || r < from - 1.0) continue;
                    bool smooth = false;
                    sample(fine, x, y, inner[i], &smooth);
                    if (!smooth) edges.push_back(x);
                    have[i] = 1;
                }
                std::vector<Node>& own = edgeNodes_[y];
                own.assign(edges.size(), Node{});
                Batch& b = edgeRows_[y];
                b.clear();
                for (size_t e = 0; e < edges.size(); ++e) b.add(edges[e] + 0.5, y + 0.5, &own[e]);
                edge.fetch_add(edges.size(), std::memory_order_relaxed);
            });
            shadeRows(edgeRows_);
            parallel(threads, h, [&](size_t yy) {
                const unsigned y = unsigned(yy);
                const std::vector<unsigned>& edges = edgeX_[y];
                if (!edges.empty()) {
                    const std::vector<Node>& own = edgeNodes_[y];
                    for (size_t e = 0; e < edges.size(); ++e) {
                        const unsigned x = edges[e];
                        Pixel& p = inner[size_t(y) * w + x];
                        const Node& o = own[e];
                        if (o.kind != 1 && o.kind != 2) continue;
                        if (o.known) {
                            for (int ch = 0; ch < 3; ++ch) p.rgb[ch] = o.rgb[ch];
                            p.conf = o.conf;
                        } else {
                            // Nothing in the store: the colour of the cell's corner nearest it on its own surface (or the
                            // environment's), not the cell's mix across the edge (the environment bled into a silhouette
                            // the lens had blurred).
                            const Node* best = nullptr;
                            for (const Node* c : corners(fine, x, y))
                                if (c->kind == o.kind && (!best || (o.kind == 1 && std::fabs(c->w - o.w) < std::fabs(best->w - o.w)))) best = c;
                            // Its own object's nearest, where a corner is of it (op.objectEdges).
                            if (op.objectEdges && o.kind == 1) {
                                const Node* own = nullptr;
                                for (const Node* c : corners(fine, x, y))
                                    if (c->kind == 1 && c->obj == o.obj && (!own || std::fabs(c->w - o.w) < std::fabs(own->w - o.w))) own = c;
                                if (own) best = own;
                            }
                            if (best)
                                for (int ch = 0; ch < 3; ++ch) p.rgb[ch] = best->rgb[ch];
                            p.conf = 0;
                        }
                        p.w = o.kind == 1 ? o.w : -1.0, p.depth = o.kind == 1 ? o.depth : 0.0f;
                    }
                }
                for (unsigned x = 0; x < w; ++x) {
                    const size_t i = size_t(y) * w + x;
                    if (!have[i]) continue;
                    const double r = radius(x + 0.5, y + 0.5);
                    if (r >= valid) continue;
                    // Over to the coarse grid in this ring's outer band, until the next ring comes (the last: none).
                    const double t = last ? 0.0 : std::clamp((r - (valid - band)) / band, 0.0, 1.0);
                    const double b = t * t * (3 - 2 * t);
                    const Pixel& a = inner[i];
                    const Pixel& o = outside[i];
                    Pixel m;
                    for (int ch = 0; ch < 3; ++ch) m.rgb[ch] = float(a.rgb[ch] + b * (o.rgb[ch] - a.rgb[ch]));
                    m.conf = float(a.conf + b * (o.conf - a.conf));
                    m.w = b < 0.5 ? a.w : o.w, m.depth = b < 0.5 ? a.depth : o.depth;
                    write(i, m);
                }
            });
            ringPictureSeconds += since(t0);
            validTo = valid;
            ++stages;
            // The finished picture's silhouettes smoothed (the rings before it are on screen for a moment only).
            if (last && op.draft && lines.size() == n)
                parallel(threads, h, [&](size_t y) {
                    for (size_t i = y * w; i < (y + 1) * w; ++i) {
                        const float a = lines[i];
                        if (a > 0)
                            for (int ch = 0; ch < 3; ++ch) color[i * 3 + ch] += a * (op.lineColour[ch] - color[i * 3 + ch]);
                    }
                });
            if (last && op.antialias) {
                t0 = Clock::now();
                Fxaa{}.apply(color, w, h, threads);
                fxaaSeconds = since(t0);
            }
            if (!last && !showStage()) break;
        }
        finish();
        return true;
    }

private:
    struct Node {
        float rgb[3] = {0, 0, 0};
        float conf = 0, depth = 0;
        double w = -1;
        std::uint8_t kind = 0;  // 0 not traced, 1 a surface, 2 the environment, 3 nothing (no ray there)
        bool known = false;     // its colour trusted
        float weight = 0;       // its colour's weight in the interpolation (fillNodes): 1 trusted, less from coarse cells, 0 none
        std::uint32_t obj = 0;  // its hit's object plus one (0: none)
        float n[3] = {0, 0, 0};  // its hit's geometric normal (facing the ray)
        float a[3] = {0, 0, 0};  // the cells' albedo at it (the smoothing's demodulation; 0: none)
        bool fill = false;       // its colour the first look's (the store had none): Rhea Draft lights it as the view's light
        bool fillLit = false;    // that light laid on it already (where it was made)
    };
    struct Pixel {
        float rgb[3] = {0, 0, 0};
        float conf = 0, depth = 0;
        double w = -1;
    };
    struct Grid {
        unsigned step = 1, gw = 0, gh = 0;
        std::vector<Node> nodes;
    };
    // A row's rays to trace: raster places and the nodes they shade; on the card's way, the rays made and their nodes.
    struct Batch {
        std::vector<double> x, y;
        std::vector<Node*> to;
        std::vector<surface::Ray> rays;
        std::vector<Node*> rto;
        void clear() { x.clear(), y.clear(), to.clear(); }
        void add(double px, double py, Node* o) { x.push_back(px), y.push_back(py), to.push_back(o); }
    };
    // Kept from view to view (a drag's steps): no allocation a step.
    Grid coarse, fine;
    std::vector<Pixel> outside, inner, blurred;
    std::vector<std::uint8_t> have;
    std::vector<Batch> rows_, edgeRows_;              // a grid's rows, a ring's edge pixels' rows
    std::vector<std::vector<unsigned>> edgeX_;        // each row's edge pixels
    std::vector<std::vector<Node>> edgeNodes_;        // and their nodes
    std::vector<size_t> rowAt_;                       // each row's first ray on the card's way
    std::vector<surface::Ray> cardRays_;
    std::vector<resume::Hit> cardHits_;
    std::vector<xpu2::interactive::rheastore::Look> cardLooks_, fineLooks_;  // the card's lookups (cardStore)
    std::vector<Batch> fineRows_;                     // the fine grid's rows, traced ahead on the card
    std::vector<size_t> fineRowAt_;
    std::vector<surface::Ray> fineRays_;
    std::vector<resume::Hit> fineHits_;
    std::vector<std::int64_t> fineAt_;                // each fine node's ray in fineRays_ (-1: none)
    std::vector<std::uint8_t> fineSet_;               // adaptive: each fine node made (1 traced or the coarse grid's, 2 interpolated)

    // Whether every mesh of the scene is triangles (no curves, no points): Embree's packets meet them all.
    static bool trianglesAlone(const async::CpuScene& scene) {
        if (!scene.plan) return false;
        for (const auto& m : scene.plan->meshes)
            if (!m.data || m.data->points || m.data->curveBasis) return false;
        return true;
    }
    // Up to four rays at once (Embree's packets), each hit made as CpuBackend::trace makes a triangle's.
    static void trace4(const async::CpuScene& scene, const async::CpuBackend& backend, const surface::Ray* rays, int count, resume::Hit* hits) {
        alignas(16) RTCRayHit4 rh;
        alignas(16) int valid[4];
        for (int k = 0; k < 4; ++k) {
            const bool on = k < count;
            const surface::Ray& r = rays[on ? k : 0];
            valid[k] = on ? -1 : 0;
            rh.ray.org_x[k] = r.origin.x, rh.ray.org_y[k] = r.origin.y, rh.ray.org_z[k] = r.origin.z;
            rh.ray.dir_x[k] = r.direction.x, rh.ray.dir_y[k] = r.direction.y, rh.ray.dir_z[k] = r.direction.z;
            rh.ray.tnear[k] = r.nearT, rh.ray.tfar[k] = r.farT, rh.ray.time[k] = backend.time;
            rh.ray.mask[k] = r.mask, rh.ray.id[k] = unsigned(k), rh.ray.flags[k] = 0;
            rh.hit.geomID[k] = RTC_INVALID_GEOMETRY_ID;
            for (unsigned l = 0; l < RTC_MAX_INSTANCE_LEVEL_COUNT; ++l) rh.hit.instID[l][k] = RTC_INVALID_GEOMETRY_ID;
        }
        RTCIntersectArguments args;
        rtcInitIntersectArguments(&args);
        rtcIntersect4(valid, scene.scene, &rh, &args);
        for (int k = 0; k < count; ++k) {
            resume::Hit& out = hits[k];
            out = resume::Hit{};
            if (rh.hit.geomID[k] == RTC_INVALID_GEOMETRY_ID) continue;
            out.geom = rh.hit.instID[0][k] != RTC_INVALID_GEOMETRY_ID ? rh.hit.instID[0][k] : rh.hit.geomID[k];
            out.prim = rh.hit.primID[k];
            const auto& mesh = *scene.plan->meshes[out.geom].data;
            if (mesh.points || mesh.curveBasis) {  // not met: such scenes take one ray at a time
                out = backend.trace(rays[k]);
                continue;
            }
            const auto t = mesh.triangles[out.prim];
            if (!resume::geometryHit(out, rays[k], backend.vertexOf(out.geom, mesh, t.a), backend.vertexOf(out.geom, mesh, t.b),
                                     backend.vertexOf(out.geom, mesh, t.c)))
                out.normal = {};
        }
    }
    // A box blur of the pixels' colour and confidence, radius r, twice each way (about a Gaussian); tmp its scratch.
    static void blur(std::vector<Pixel>& px, std::vector<Pixel>& tmp, unsigned w, unsigned h, unsigned r, unsigned threads) {
        if (!r || px.size() != size_t(w) * h) return;
        tmp.resize(px.size());
        auto pass = [&](const std::vector<Pixel>& from, std::vector<Pixel>& to, bool across) {
            const unsigned lines = across ? h : w, len = across ? w : h;
            parallel(std::max(1u, threads), lines, [&](size_t line) {
                auto at = [&](unsigned k) -> size_t { return across ? size_t(line) * w + k : size_t(k) * w + line; };
                double s[4] = {0, 0, 0, 0};
                int count = 0;
                for (unsigned k = 0; k <= std::min(r, len - 1); ++k) {
                    const Pixel& p = from[at(k)];
                    s[0] += p.rgb[0], s[1] += p.rgb[1], s[2] += p.rgb[2], s[3] += p.conf, ++count;
                }
                for (unsigned k = 0; k < len; ++k) {
                    Pixel& o = to[at(k)];
                    o = from[at(k)];
                    for (int ch = 0; ch < 3; ++ch) o.rgb[ch] = float(s[ch] / count);
                    o.conf = float(s[3] / count);
                    if (k + r + 1 < len) {
                        const Pixel& p = from[at(k + r + 1)];
                        s[0] += p.rgb[0], s[1] += p.rgb[1], s[2] += p.rgb[2], s[3] += p.conf, ++count;
                    }
                    if (k >= r) {
                        const Pixel& p = from[at(k - r)];
                        s[0] -= p.rgb[0], s[1] -= p.rgb[1], s[2] -= p.rgb[2], s[3] -= p.conf, --count;
                    }
                }
            });
        };
        for (int it = 0; it < 2; ++it) {
            pass(px, tmp, true);
            pass(tmp, px, false);
        }
    }
    // The grid's light smoothed over its surfaces (Options::smooth, rheastore::smoothNode): on the card where cardSmooth
    // takes it, else on the CPU's threads, the same arithmetic.
    void smoothGrid(Grid& g, unsigned threads) {
        namespace R = xpu2::interactive::rheastore;
        const auto began = std::chrono::steady_clock::now();
        smoothedOnCard = false;
        const size_t count = g.nodes.size();
        smoothNodes_.assign(count, R::SmoothNode{});
        smoothLight_.assign(count * 3, 0.0f);
        const float floorA = float(op.smoothFloor);
        parallel(threads, g.gh, [&](size_t j) {
            for (size_t k = j * g.gw; k < (j + 1) * g.gw; ++k) {
                const Node& o = g.nodes[k];
                for (int ch = 0; ch < 3; ++ch) smoothLight_[k * 3 + ch] = o.rgb[ch];
                if (o.kind != 1 || !(o.w > 0)) continue;
                R::SmoothNode& sn = smoothNodes_[k];
                sn.w = float(o.w), sn.obj = o.obj;
                // On a line (Rhea Draft): left as it is, and no neighbour's (gradients stop at the lines).
                if (!lines.empty()) {
                    const size_t px = std::min<size_t>(size_t(k % g.gw) * g.step, lineW_ - 1), py = std::min<size_t>(size_t(k / g.gw) * g.step, lineH_ - 1);
                    if (lines[py * lineW_ + px] > 0.25f) sn.flags |= 2u;
                }
                const float l = std::sqrt(o.n[0] * o.n[0] + o.n[1] * o.n[1] + o.n[2] * o.n[2]);
                if (l > 0) sn.n[0] = o.n[0] / l, sn.n[1] = o.n[1] / l, sn.n[2] = o.n[2] / l;
                const float lumA = 0.2126f * o.a[0] + 0.7152f * o.a[1] + 0.0722f * o.a[2];
                if (lumA >= floorA) {
                    sn.flags |= 1u;  // (|=: kept the line's mark above, which = cleared, so the smoothing crossed lines)
                    for (int ch = 0; ch < 3; ++ch) smoothLight_[k * 3 + ch] = o.rgb[ch] / std::max(o.a[ch], floorA);
                }
            }
        });
        R::SmoothParams sp;
        sp.gw = int(g.gw), sp.gh = int(g.gh), sp.depth = float(op.smoothDepth), sp.normal = float(op.smoothNormal), sp.light = float(op.smoothLight);
        const int passes = std::clamp(op.smoothPasses, 0, 6);
        if (cardSmooth && cardSmooth(smoothNodes_.data(), smoothLight_.data(), sp, passes)) smoothedOnCard = true;
        else {
            smoothOut_.resize(count * 3);
            for (int k = 0; k < passes; ++k) {
                sp.step = 1 << k;
                parallel(threads, g.gh, [&](size_t j) {
                    for (unsigned i = 0; i < g.gw; ++i) R::smoothNode(sp, smoothNodes_.data(), smoothLight_.data(), int(i), int(j), &smoothOut_[(j * g.gw + i) * 3]);
                });
                smoothLight_.swap(smoothOut_);
            }
        }
        parallel(threads, g.gh, [&](size_t j) {
            for (size_t k = j * g.gw; k < (j + 1) * g.gw; ++k) {
                Node& o = g.nodes[k];
                if (o.kind != 1 || !(o.w > 0)) continue;
                const bool demod = smoothNodes_[k].flags & 1u;
                for (int ch = 0; ch < 3; ++ch)
                    o.rgb[ch] = std::max(0.0f, smoothLight_[k * 3 + ch] * (demod ? std::max(o.a[ch], floorA) : 1.0f));
            }
        });
        smoothSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
    }
    // Rhea Draft's flat fill lit as the view is (DESIGN.md 42): a surface the store has nothing for was its albedo under a
    // light of one, so a bright room's unknown wall came out near black beside the same wall known (the interior's left
    // wall, the block behind the car). Its colour is now times its object's light: the mean of that object's known
    // surfaces' light over their albedo (a floor lit as the floor is, a wall as the wall), else, for an object the store
    // knows nothing of yet, the view's median light (the mean let a white sofa light a dark wooden floor white). Both
    // eased from view to view (half each) so a fill does not pulse as the known share changes.
    float draftLight_[3] = {1, 1, 1};
    bool draftLightSet_ = false;
    std::unordered_map<std::uint32_t, std::array<float, 3>> objLight_;
    const float* fillLight(std::uint32_t obj) const {
        const auto it = objLight_.find(obj);
        return it != objLight_.end() ? it->second.data() : draftLight_;
    }
    void lightFills(Grid& g) {
        struct Sum { double l[3] = {0, 0, 0}; size_t n = 0; };
        std::unordered_map<std::uint32_t, Sum> sums;
        std::vector<float> all[3];
        for (const Node& o : g.nodes) {
            if (o.kind != 1 || !o.known || o.fill) continue;
            const double lum = 0.2126 * o.a[0] + 0.7152 * o.a[1] + 0.0722 * o.a[2];
            if (lum < 0.05) continue;
            Sum& s = sums[o.obj];
            for (int ch = 0; ch < 3; ++ch) {
                const float light = o.rgb[ch] / std::max(0.02f, o.a[ch]);
                s.l[ch] += light;
                all[ch].push_back(light);
            }
            ++s.n;
        }
        if (all[0].size() >= 64) {
            for (int ch = 0; ch < 3; ++ch) {
                auto mid = all[ch].begin() + all[ch].size() / 2;
                std::nth_element(all[ch].begin(), mid, all[ch].end());
                const float now = std::clamp(*mid, 0.05f, 50.0f);
                draftLight_[ch] = draftLightSet_ ? 0.5f * (draftLight_[ch] + now) : now;
            }
            draftLightSet_ = true;
        }
        for (const auto& [obj, s] : sums) {
            if (s.n < 8) continue;
            auto found = objLight_.find(obj);
            std::array<float, 3> now;
            for (int ch = 0; ch < 3; ++ch) now[ch] = float(std::clamp(s.l[ch] / double(s.n), 0.05, 50.0));
            if (found == objLight_.end()) objLight_.emplace(obj, now);
            else for (int ch = 0; ch < 3; ++ch) found->second[ch] = 0.5f * (found->second[ch] + now[ch]);
        }
        if (!draftLightSet_) return;
        // Those made before the view's light was known (the first view's): lit now.
        for (Node& o : g.nodes)
            if (o.fill && !o.fillLit) {
                const float* lightHere = fillLight(o.obj);
                for (int ch = 0; ch < 3; ++ch) o.rgb[ch] *= lightHere[ch];
                o.fillLit = true;
            }
    }
    // Rhea Draft's lines for this view (op.draft): on the card where it takes them, else the CPU's rays, the same test.
    size_t lineW_ = 0, lineH_ = 0;
    void findLines(const View& nv, const async::CpuScene& scene, unsigned w, unsigned h, unsigned threads) {
        namespace R = xpu2::interactive::rheastore;
        const auto began = std::chrono::steady_clock::now();
        R::LineSettings ls;
        ls.width = int(w), ls.height = int(h), ls.samples = std::clamp(op.lineSamples, 1, 4);
        ls.apart = float(op.lineApart > 0 ? op.lineApart : std::max(1.0, double(w) / 1100.0));
        ls.crease = float(op.lineCrease), ls.plane = float(op.linePlane);
        lines.assign(size_t(w) * h, 0.0f), lineW_ = w, lineH_ = h;
        linesOnCard = cardLines && cardLines(nv.chief(), ls, lines.data());
        if (!linesOnCard)
            parallel(threads, h, [&](size_t y) {
                async::CpuBackend backend{scene};
                const int S = ls.samples;
                for (unsigned x = 0; x < w; ++x) {
                    float cover = 0;
                    for (int sy = 0; sy < S; ++sy)
                        for (int sx = 0; sx < S; ++sx) {
                            const double px = x + (sx + 0.5) / S, py = y + (sy + 0.5) / S;
                            const double at[3][2] = {{px, py}, {px + ls.apart, py}, {px, py + ls.apart}};
                            unsigned g[3];
                            float n3[3][3], p3[3][3], t[3];
                            bool made[3];
                            for (int k = 0; k < 3; ++k) {
                                surface::Ray r;
                                made[k] = nv.ray(at[k][0], at[k][1], r);
                                g[k] = ~0u, t[k] = 0;
                                if (!made[k]) continue;
                                r.mask = 1u;
                                const resume::Hit hh = backend.trace(r);
                                g[k] = hh.geom, t[k] = hh.t;
                                n3[k][0] = hh.normal.x, n3[k][1] = hh.normal.y, n3[k][2] = hh.normal.z;
                                p3[k][0] = hh.point.x, p3[k][1] = hh.point.y, p3[k][2] = hh.point.z;
                            }
                            if (!made[0]) continue;
                            const bool edge = (made[1] && R::draftEdge(g[0], n3[0], p3[0], t[0], g[1], n3[1], p3[1], t[1], ls.crease, ls.plane)) ||
                                              (made[2] && R::draftEdge(g[0], n3[0], p3[0], t[0], g[2], n3[2], p3[2], t[2], ls.crease, ls.plane));
                            cover += edge ? 1.0f : 0.0f;
                        }
                    lines[size_t(y) * w + x] = cover / float(S * S);
                }
            });
        lineSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
    }
    std::vector<xpu2::interactive::rheastore::SmoothNode> smoothNodes_;
    std::vector<float> smoothLight_, smoothOut_;
    // Nodes at multiples of the step, the last row and column at the picture's edge (the vectors kept, cleared).
    static void layGrid(Grid& g, unsigned step, unsigned w, unsigned h) {
        g.step = step, g.gw = (w - 1) / step + 2, g.gh = (h - 1) / step + 2;
        g.nodes.assign(size_t(g.gw) * g.gh, Node{});
    }
    // The colours of the nodes the store did not answer for with confidence, interpolated from those it did (pullPush, each
    // node by its weight: whole where trusted, a little where the store's answer came from coarse cells, none where it had
    // nothing): a surface's from the surfaces', the environment's from the environment's, so that neither bleeds into the
    // other at a silhouette. The colour interpolation first, the coarse cells only where no trusted node is near (the user,
    // 2026-11-22: "in coarse areas where the shading is unpredictable, that should just be handed over to an auto-color
    // interpolation"; "it should be first a color interpolation then generate the coarse-smooth area").
    // The surfaces' by depth (pullPushDepth, depth > 0: its tolerance), the environment's plainly.
    static void fillNodes(Grid& g, double depth, bool byObject = false) {
        for (std::uint8_t kind = 1; kind <= 2; ++kind) {
            std::vector<float> c(size_t(g.gw) * g.gh * 4, 0.0f);
            std::vector<float> z;
            std::vector<std::uint32_t> ids;
            const bool byDepth = kind == 1 && depth > 0;
            if (byDepth) z.assign(size_t(g.gw) * g.gh, 0.0f);
            if (byDepth && byObject) {
                ids.assign(size_t(g.gw) * g.gh, 0u);
                for (size_t k = 0; k < g.nodes.size(); ++k)
                    if (g.nodes[k].kind == 1) ids[k] = g.nodes[k].obj;
            }
            bool any = false, needed = false;
            for (size_t k = 0; k < g.nodes.size(); ++k) {
                const Node& o = g.nodes[k];
                if (o.kind != kind) continue;
                if (byDepth && o.w > 0) z[k] = float(o.w);
                if (o.weight > 0) {
                    c[k * 4] = o.rgb[0], c[k * 4 + 1] = o.rgb[1], c[k * 4 + 2] = o.rgb[2], c[k * 4 + 3] = std::min(1.0f, o.weight);
                    any = true;
                }
                if (o.weight < 1) needed = true;
            }
            if (!any || !needed) continue;
            if (byDepth) pullPushDepth(c, z, g.gw, g.gh, depth, ids.empty() ? nullptr : &ids);
            else pullPush(c, g.gw, g.gh);
            for (size_t k = 0; k < g.nodes.size(); ++k) {
                Node& o = g.nodes[k];
                if (o.kind == kind && o.weight < 1 && c[k * 4 + 3] > 0) o.rgb[0] = c[k * 4], o.rgb[1] = c[k * 4 + 1], o.rgb[2] = c[k * 4 + 2];
            }
        }
    }
    // A pixel's cell's four corners in a grid.
    static std::array<const Node*, 4> corners(const Grid& g, unsigned x, unsigned y) {
        const unsigned i = x / g.step, j = y / g.step;
        return {&g.nodes[size_t(j) * g.gw + i], &g.nodes[size_t(j) * g.gw + i + 1], &g.nodes[size_t(j + 1) * g.gw + i],
                &g.nodes[size_t(j + 1) * g.gw + i + 1]};
    }
};

}  // namespace rhea
