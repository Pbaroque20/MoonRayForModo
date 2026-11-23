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
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <vector>

namespace rhea {

namespace async = xpu2::interactive::async;

// The weighted pull-push of a grid (Gortler and others, The Lumigraph, 1996): rgb and a weight (0 to 1) a texel. The
// weights' averages go up level by level (a parent's weight its children's, at most whole); coming back down, a texel short
// of a whole weight takes the rest from the coarser level's estimate, interpolated (bilinear): a smooth colour interpolation
// from the texels that hold their colour, where copying the coarser texel made blocks of its size (the user, 2026-11-22:
// the "splotchy backgrounds").
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
    };
    // A picture's outputs for the composite: its AOV values, a pixel's count of them, and where the first hit's albedo
    // and the light emitted at it are among them (-1: none).
    struct Outputs {
        const std::vector<float>* aov = nullptr;
        size_t stride = 0;
        int albedo = -1, emission = -1;
    };
    Options op;
    double addSeconds = 0;
    size_t added = 0;  // pixels the last picture added

    void clear() {
        light.clear(), fine.clear();
        sky.assign(SkyW * SkyH * 4, 0.0f), skyFilled.clear();
        ++generation;
    }
    bool empty() const { return light.used == 0 && skyFilled.empty(); }
    size_t cells() const { return light.used + fine.used; }

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
    void add(const View& view, unsigned w, unsigned h, const std::vector<float>& rgba, const std::vector<std::uint32_t>& counts,
             const std::vector<float>& depth, const std::vector<float>& depthFar, const Outputs* outputs = nullptr) {
        const Outputs outs = outputs ? *outputs : Outputs{};
        const auto began = std::chrono::steady_clock::now();
        const size_t n = size_t(w) * h;
        added = 0;
        ++generation;  // the cells about to change: the lookups' memo (means) starts again
        if (rgba.size() != n * 4 || depth.size() != n || counts.size() != n) return;
        if (cells() > op.maxCells) clear();
        if (sky.empty()) sky.assign(SkyW * SkyH * 4, 0.0f);
        const double angle = pixelAngle(view);
        if (!(angle > 0)) return;
        const bool parts = outs.aov && outs.stride && outs.aov->size() == n * outs.stride && outs.albedo >= 0 &&
                           size_t(outs.albedo) + 3 <= outs.stride && (outs.emission < 0 || size_t(outs.emission) + 3 <= outs.stride);
        // Every pixel at a large picture would cost more than it adds: a stride keeps it under a third of a million.
        const unsigned stride = unsigned(std::max(1.0, std::floor(std::sqrt(double(n) / 330000.0))));
        struct Add {
            surface::V3 p;
            int level;
            std::uint8_t bins[2];
            float v[9], weight;  // colour, albedo, emission
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
                e.level = levelOf(footprint(view, angle, d) * along * op.scale * stride);
                binsOf(nn, e.bins);
                for (int k = 0; k < 9; ++k) e.v[k] = 0;
                for (int k = 0; k < 3; ++k) e.v[k] = c[k];
                if (parts) {
                    const float* o = &(*outs.aov)[i * outs.stride];
                    for (int k = 0; k < 3; ++k) {
                        e.v[3 + k] = std::isfinite(o[outs.albedo + k]) ? std::max(0.0f, o[outs.albedo + k]) : 0.0f;
                        e.v[6 + k] = outs.emission >= 0 && std::isfinite(o[outs.emission + k]) ? std::max(0.0f, o[outs.emission + k]) : 0.0f;
                    }
                }
                e.weight = weight;
                perRow[r].push_back(e);
            }
        });
        for (auto& row : perRow)
            for (const Add& e : row) {
                for (int b = 0; b < 2; ++b) {
                    if (e.bins[b] == NoBin) continue;
                    for (int k = 0; k < op.levels; ++k) {
                        Table::Entry& t = light.slot(e.p, e.level + k, e.bins[b]);
                        for (int q = 0; q < 9; ++q) t.v[q] += e.v[q] * e.weight;
                        t.v[9] += e.weight;
                    }
                    // The albedo alone, in cells half as wide.
                    if (op.albedo && parts)
                        for (int k = 0; k < op.levels + 1; ++k) {
                            Table::Entry& t = fine.slot(e.p, e.level - 1 + k, e.bins[b]);
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
    bool lookup(const surface::V3& p, const D3& n, const D3& dir, double foot, float rgb[3], float& confidence, int* up = nullptr) const {
        confidence = 0;
        if (up) *up = 0;
        if (!light.used) return false;
        std::uint8_t bins[2];
        binsOf(n, bins);
        const int first = levelOf(foot * stretch(n, dir, op.grazing) * op.scale);
        double m[9];
        int sizesUp = 0;
        if (!means(light, p, bins, first, op.levels + 6, m, confidence, &sizesUp)) return false;
        if (up) *up = sizesUp;
        for (int ch = 0; ch < 3; ++ch) rgb[ch] = float(std::max(0.0, m[ch]));
        if (op.albedo && fine.used) {
            double a[9];
            float fineConfidence;
            if (means(fine, p, bins, first - 1, op.levels + 7, a, fineConfidence, nullptr))
                for (int ch = 0; ch < 3; ++ch)
                    if (m[3 + ch] > 0.02) rgb[ch] = float(std::max(0.0, a[ch] * (m[ch] - m[6 + ch]) / m[3 + ch] + m[6 + ch]));
        }
        return true;
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
    static constexpr size_t SkyW = 256, SkyH = 128;
    // A sparse hash of cubes: by their place at their size (2^level a side) and the side their surface faces; each the
    // weighted sums of what was added to it (colour, albedo, emission) and the weights.
    struct Table {
        struct Entry {
            long long x = 0, y = 0, z = 0;
            std::int16_t level = 0;
            std::uint8_t bin = 0, full = 0;
            float v[10] = {};
        };
        std::vector<Entry> slots;
        size_t used = 0;
        void clear() { slots.clear(), used = 0; }
        static std::uint64_t hashOf(long long x, long long y, long long z, int level, int bin) {
            std::uint64_t h = std::uint64_t(x) * 0x9E3779B97F4A7C15ull;
            h ^= std::uint64_t(y) * 0xC2B2AE3D27D4EB4Full + (h << 6) + (h >> 2);
            h ^= std::uint64_t(z) * 0x165667B19E3779F9ull + (h << 6) + (h >> 2);
            h ^= (std::uint64_t(std::uint16_t(level)) << 8 | std::uint64_t(bin)) * 0x27D4EB2F165667C5ull;
            h ^= h >> 31, h *= 0xBF58476D1CE4E5B9ull, h ^= h >> 29;
            return h;
        }
        const Entry* find(long long x, long long y, long long z, int level, int bin) const {
            if (slots.empty()) return nullptr;
            const size_t mask = slots.size() - 1;
            for (size_t i = hashOf(x, y, z, level, bin) & mask;; i = (i + 1) & mask) {
                const Entry& e = slots[i];
                if (!e.full) return nullptr;
                if (e.x == x && e.y == y && e.z == z && e.level == level && e.bin == bin) return &e;
            }
        }
        Entry& slot(const surface::V3& p, int level, int bin) {
            const double size = std::ldexp(1.0, level);
            const long long x = (long long)std::floor(p.x / size), y = (long long)std::floor(p.y / size), z = (long long)std::floor(p.z / size);
            if ((used + 1) * 2 > slots.size()) grow(std::max<size_t>(slots.size() * 2, size_t(1) << 16));
            const size_t mask = slots.size() - 1;
            for (size_t i = hashOf(x, y, z, level, bin) & mask;; i = (i + 1) & mask) {
                Entry& e = slots[i];
                if (!e.full) {
                    e = Entry{};
                    e.x = x, e.y = y, e.z = z, e.level = std::int16_t(level), e.bin = std::uint8_t(bin), e.full = 1;
                    ++used;
                    return e;
                }
                if (e.x == x && e.y == y && e.z == z && e.level == level && e.bin == bin) return e;
            }
        }
        void grow(size_t size) {
            std::vector<Entry> old;
            old.swap(slots);
            slots.assign(size, Entry{});
            const size_t mask = slots.size() - 1;
            for (const Entry& e : old) {
                if (!e.full) continue;
                size_t i = hashOf(e.x, e.y, e.z, e.level, e.bin) & mask;
                while (slots[i].full) i = (i + 1) & mask;
                slots[i] = e;
            }
        }
    };
    Table light, fine;  // the colours (with albedo and emission), and the albedo in cells half as wide (op.albedo)
    std::uint64_t generation = 0;  // changed with the cells (add, clear): the lookups' memo holds for one generation
    std::vector<float> sky, skyFilled;  // rgb and weight a direction: summed, and its holes filled (fillSky)

    static int levelOf(double side) { return side > 0 ? int(std::floor(std::log2(side))) : -60; }
    // A thread's last eight cells at a size (means): neighbouring rays meet the same cells.
    struct Memo {
        const ObjectStore* store = nullptr;
        const Table* table = nullptr;
        std::uint64_t generation = ~0ull;
        int level = 0;
        std::uint8_t bins[2] = {0, 0};
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
    bool means(const Table& t, const surface::V3& p, const std::uint8_t bins[2], int first, int levels, double out[9], float& confidence,
               int* up) const {
        double acc[9] = {}, have = 0;
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
                m.bins[1] != bins[1] || m.x0 != x0 || m.y0 != y0 || m.z0 != z0) {
                for (int corner = 0; corner < 8; ++corner) {
                    const int dx = corner & 1, dy = corner >> 1 & 1, dz = corner >> 2 & 1;
                    const Table::Entry* e = t.find(x0 + dx, y0 + dy, z0 + dz, level, bins[0]);
                    if (!e && bins[1] != NoBin) e = t.find(x0 + dx, y0 + dy, z0 + dz, level, bins[1]);
                    m.e[corner] = e && e->v[9] > 0 ? e : nullptr;
                }
                m.store = this, m.table = &t, m.generation = generation, m.level = level, m.bins[0] = bins[0], m.bins[1] = bins[1];
                m.x0 = x0, m.y0 = y0, m.z0 = z0;
            }
            double c[9] = {}, wsum = 0;
            for (int corner = 0; corner < 8; ++corner) {
                const Table::Entry* e = m.e[corner];
                if (!e) continue;
                const int dx = corner & 1, dy = corner >> 1 & 1, dz = corner >> 2 & 1;
                const double tri = (dx ? tx : 1 - tx) * (dy ? ty : 1 - ty) * (dz ? tz : 1 - tz);
                if (tri <= 0) continue;
                const double k = tri / e->v[9];
                for (int q = 0; q < 9; ++q) c[q] += k * e->v[q];
                wsum += tri;
            }
            if (wsum <= 0) continue;
            const double take = (1.0 - have) * std::min(1.0, wsum / 0.5);
            for (int q = 0; q < 9; ++q) acc[q] += take * c[q] / wsum;
            if (have == 0) {
                confidence = float(std::min(1.0, wsum));
                if (up) *up = k;
            }
            have += take;
            if (have > 0.999) break;
        }
        if (have <= 0) return false;
        for (int q = 0; q < 9; ++q) out[q] = acc[q] / have;
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
        // With nothing in the store (the first frame of realtime): each hit's material colour (the CPU's), lit from the
        // camera, so that phase one has a first look before XPU2's first pictures fade in.
        bool firstLook = true;
        unsigned threads = 8;
    };
    Options op;
    size_t rays = 0, edgeRays = 0;
    unsigned stride = 0, stages = 0;
    double seconds = 0, firstSeconds = 0, unknown = 0;  // the view's time, its first picture's, the rays the store had nothing for
    // Where the time went (seconds): the coarse grid's rays, its picture (sampled, blurred, written), the rings' grid rays,
    // their pictures (the edges' own rays among them), FXAA, and the stages shown (stage(): the session's part).
    double coarseRaySeconds = 0, coarsePictureSeconds = 0, ringRaySeconds = 0, ringPictureSeconds = 0, fxaaSeconds = 0, stageSeconds = 0;
    bool packetsUsed = false;
    // The graphics card's first hits (the session's, XPU2's launch mode 5): count rays at once into hits, each as the path
    // tracer's own; false where the card does not take them now (a frame's launches out), the CPU tracing them. A stage's
    // rays go to it together (the coarse grid, a ring, a ring's edges), the store's lookups staying on the CPU's threads
    // (the user, 2026-11-22: "have Rhea phase 1 use both gpu/cpu"). Empty: the CPU alone.
    std::function<bool(const surface::Ray*, size_t, resume::Hit*)> cardTrace;
    // The last view's rays the card traced, and the time its calls took (rays out, launch, hits back).
    size_t cardRays = 0;
    double cardSeconds = 0;

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
        rays = edgeRays = 0, stages = 0, unknown = 0, firstSeconds = 0;
        coarseRaySeconds = coarsePictureSeconds = ringRaySeconds = ringPictureSeconds = fxaaSeconds = stageSeconds = 0;
        cardRays = 0, cardSeconds = 0;
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
        std::atomic<size_t> traced{0}, empty{0}, edge{0};
        // A hit's colour from the store (or the environment's), into a node: trusted where the store's cells about it hold
        // it (op.trust, op.trustUp), else weighed little in the interpolation. The store empty (realtime's first frame):
        // the first look, the hit's material colour lit from the camera.
        const bool firstLook = op.firstLook && store.empty();
        auto shade = [&](const async::CpuBackend& backend, const surface::Ray& ray, const resume::Hit& hit, Node& o) {
            if (hit.geom == ~0u) {
                o.kind = 2;
                o.known = store.skyAt(D3{ray.direction.x, ray.direction.y, ray.direction.z}, o.rgb);
                o.conf = o.known ? 1.0f : 0.0f, o.weight = o.known ? 1.0f : 0.0f;
                if (!o.known && firstLook) o.rgb[0] = o.rgb[1] = o.rgb[2] = 0.5f, o.known = true, o.weight = 1.0f;
                return;
            }
            o.kind = 1;
            const double d = nv.depthOf(nv.camera(hit.point));
            o.depth = float(d), o.w = nv.wOf(d);
            const D3 nn = nv.toward(D3{hit.normal.x, hit.normal.y, hit.normal.z}, hit.point);
            int up = 0;
            const bool found = store.lookup(hit.point, nn, D3{ray.direction.x, ray.direction.y, ray.direction.z},
                                            ObjectStore::footprint(nv, angle, d), o.rgb, o.conf, &up);
            o.known = found && (up <= 1 || (up <= op.trustUp && o.conf >= op.trust));
            o.weight = o.known ? 1.0f : found ? float(0.25 * std::max(0.0f, o.conf) / (1.0 + std::max(0, up - op.trustUp))) : 0.0f;
            if (!found && firstLook) {
                surface::Lambert l{};
                backend.material(hit, ray, l);
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
                o.known = true, o.weight = 1.0f, o.conf = 0.0f;
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
        auto shadeOnCard = [&](std::vector<Batch>& rowsOf) -> bool {
            if (!cardTrace || rowsOf.empty()) return false;
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
            rowAt_.assign(rowsOf.size() + 1, 0);
            for (size_t r = 0; r < rowsOf.size(); ++r) rowAt_[r + 1] = rowAt_[r] + rowsOf[r].rays.size();
            const size_t count = rowAt_.back();
            if (!count) return true;
            cardRays_.resize(count), cardHits_.resize(count);
            parallel(threads, rowsOf.size(), [&](size_t r) { std::copy(rowsOf[r].rays.begin(), rowsOf[r].rays.end(), cardRays_.begin() + rowAt_[r]); });
            const auto sent = Clock::now();
            if (!cardTrace(cardRays_.data(), count, cardHits_.data())) return false;
            cardSeconds += since(sent);
            cardRays += count;
            parallel(threads, rowsOf.size(), [&](size_t r) {
                async::CpuBackend backend{scene};
                size_t unknownHere = 0;
                for (size_t k = rowAt_[r]; k < rowAt_[r + 1]; ++k) {
                    Node& o = *rowsOf[r].rto[k - rowAt_[r]];
                    shade(backend, cardRays_[k], cardHits_[k], o);
                    if (!o.known) ++unknownHere;
                }
                traced.fetch_add(rowAt_[r + 1] - rowAt_[r], std::memory_order_relaxed);
                empty.fetch_add(unknownHere, std::memory_order_relaxed);
            });
            return true;
        };
        // Each row's rays traced and shaded: on the card where it takes them, else on the CPU a row a thread.
        auto shadeRows = [&](std::vector<Batch>& rowsOf) {
            if (shadeOnCard(rowsOf)) return;
            parallel(threads, rowsOf.size(), [&](size_t r) { shadeAll(rowsOf[r]); });
        };
        auto radius = [&](double x, double y) { return std::sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy)); };
        // A grid's nodes traced between two radii, a row at a time, then those the store had nothing for filled from the
        // known around them.
        auto trace = [&](Grid& g, double from, double to) {
            rows_.resize(g.gh);
            parallel(threads, g.gh, [&](size_t j) {
                Batch& b = rows_[j];
                b.clear();
                for (unsigned i = 0; i < g.gw; ++i) {
                    const double x = std::min<double>(double(i) * g.step, w - 1) + 0.5, y = std::min<double>(double(j) * g.step, h - 1) + 0.5;
                    const double r = radius(x, y);
                    if (r < from || r >= to) continue;
                    b.add(x, y, &g.nodes[j * g.gw + i]);
                }
            });
            shadeRows(rows_);
            fillNodes(g);
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
        parallel(threads, h, [&](size_t yy) {
            const unsigned y = unsigned(yy);
            for (unsigned x = 0; x < w; ++x) sample(coarse, x, y, outside[size_t(y) * w + x], nullptr);
        });
        // Blurred over about its step (two box passes each way): bilinear alone left the grid's steps along silhouettes.
        blur(outside, blurred, w, h, std::max(1u, S / 2), threads);
        parallel(threads, h, [&](size_t yy) {
            for (size_t i = yy * w; i < (yy + 1) * w; ++i) write(i, outside[i]);
        });
        coarsePictureSeconds = since(t0);
        firstSeconds = since(began);
        ++stages;
        auto finish = [&] {
            edgeRays = edge.load();
            rays = traced.load();
            unknown = rays ? double(empty.load()) / double(rays) : 0.0;
            seconds = since(began);
        };
        if (!showStage()) {
            finish();
            return true;
        }
        // The fine grid ring by ring, rings of equal area out to the picture's corners: each ring's pixels from the fine
        // grid (a ray a pixel in a cell its corners are not one smooth surface of, those rays a row's together), its outer
        // band going over to the coarse grid's until the next ring comes.
        layGrid(fine, stride, w, h);
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
            trace(fine, tracedTo, to);
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
    static void fillNodes(Grid& g) {
        for (std::uint8_t kind = 1; kind <= 2; ++kind) {
            std::vector<float> c(size_t(g.gw) * g.gh * 4, 0.0f);
            bool any = false, needed = false;
            for (size_t k = 0; k < g.nodes.size(); ++k) {
                const Node& o = g.nodes[k];
                if (o.kind != kind) continue;
                if (o.weight > 0) {
                    c[k * 4] = o.rgb[0], c[k * 4 + 1] = o.rgb[1], c[k * 4 + 2] = o.rgb[2], c[k * 4 + 3] = std::min(1.0f, o.weight);
                    any = true;
                }
                if (o.weight < 1) needed = true;
            }
            if (!any || !needed) continue;
            pullPush(c, g.gw, g.gh);
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
