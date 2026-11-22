// Rhea's drag pictures from colours kept on the surfaces (rhea/DESIGN.md 30).
//
// The mesh gradient (mesh_warp.h, DESIGN.md 28) interpolates the last picture's colours in screen space: a turn to look
// behind the model shows what that picture never held (gaps, filled from around them), a surface seen edge on stretches
// its triangles into spikes, and its cost grows with the picture's edges (the user's dragon, 2026-11-22: "it struggles
// to drag because it's geometrically complex"). Here the colours live on the surfaces instead (the user: "it would be
// better if the interpolations are object-space, so that there aren't any gaps when the user tries to look behind the
// model"), and a drag's picture is made only where the eye is (a radial vignette: "the computation is only where the user
// cares, and the reprojection gracefully ends outside of this vignette").
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
// (a budget of rays inside the vignette), and between them the colours are interpolated (bilinear) where the four corners
// are one smooth surface; a cell they are not (a silhouette, a crease) takes a ray every pixel. Outside the vignette a grid
// four times sparser, blurred, its light falling off toward the corners. What no picture has shown yet is filled from the
// grid around it (its doubt 1: XPU2's completion fade takes those regions first).
//
// Streamed (the user: "the reconstructions should be streamed. the user should be able to see the radial topology
// updating in realtime"): the coarse grid's picture first, over all of it, then the fine grid ring by ring from the
// centre out (rings of equal area, so of about equal time), each shown as it lands; the next move stops it where it is.
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

class ObjectStore {
public:
    struct Options {
        double scale = 3;      // a finest cell's side, in pixels of the picture that adds to it
        int levels = 4;        // the sizes kept: the finest and three, each twice the one before
        double jump = 0.03;    // a neighbour whose depth differs by more (relative) is another surface
        size_t maxCells = size_t(1) << 22;  // past this the store starts again from the next picture
        unsigned threads = 8;
    };
    Options op;
    double addSeconds = 0;
    size_t added = 0;  // pixels the last picture added

    void clear() {
        table.clear(), used = 0;
        sky.assign(SkyW * SkyH * 4, 0.0f), skyFilled.clear();
    }
    bool empty() const { return used == 0 && skyFilled.empty(); }
    size_t cells() const { return used; }

    // A picture's pixel size at depth 1 (perspective and directional: a pixel's footprint is this times its depth;
    // orthographic: this, at every depth).
    static double pixelAngle(const View& v) {
        surface::V3 a, b;
        const double cx = 0.5 * v.width, cy = 0.5 * v.height;
        if (!v.pointAt(cx, cy, 1.0, a) || !v.pointAt(cx + 1.0, cy, 1.0, b)) return 0;
        return std::sqrt(double(b.x - a.x) * (b.x - a.x) + double(b.y - a.y) * (b.y - a.y) + double(b.z - a.z) * (b.z - a.z));
    }
    static double footprint(const View& v, double angle, double depth) { return v.kind == View::Orthographic ? angle : angle * depth; }

    // A picture's colours onto the surfaces it shows: depth its nearest first-hit depth (0 none), depthFar its farthest
    // (empty: none).
    void add(const View& view, unsigned w, unsigned h, const std::vector<float>& rgba, const std::vector<std::uint32_t>& counts,
             const std::vector<float>& depth, const std::vector<float>& depthFar) {
        const auto began = std::chrono::steady_clock::now();
        const size_t n = size_t(w) * h;
        added = 0;
        if (rgba.size() != n * 4 || depth.size() != n || counts.size() != n) return;
        if (used > op.maxCells) clear();
        if (table.empty()) grow(size_t(1) << 16);
        if (sky.empty()) sky.assign(SkyW * SkyH * 4, 0.0f);
        const double angle = pixelAngle(view);
        if (!(angle > 0)) return;
        // Every pixel at a large picture would cost more than it adds: a stride keeps it under a third of a million.
        const unsigned stride = unsigned(std::max(1.0, std::floor(std::sqrt(double(n) / 330000.0))));
        struct Add {
            surface::V3 p;
            int level;
            std::uint8_t bins[2];
            float rgb[3], weight;
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
                if (!(d > 0)) {
                    // The environment: by direction (alpha little: no surface's coverage in it).
                    if (c[3] > 0.02f && c[3] < 0.98f) continue;
                    surface::Ray ray;
                    if (!view.ray(x + 0.5, y + 0.5, ray)) continue;
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
                e.level = levelOf(footprint(view, angle, d) * op.scale * stride);
                binsOf(nn, e.bins);
                e.rgb[0] = c[0], e.rgb[1] = c[1], e.rgb[2] = c[2], e.weight = weight;
                perRow[r].push_back(e);
            }
        });
        for (auto& row : perRow)
            for (const Add& e : row) {
                for (int k = 0; k < op.levels; ++k) {
                    const int level = e.level + k;
                    const double size = std::ldexp(1.0, level);
                    const long long cx = (long long)std::floor(e.p.x / size), cy = (long long)std::floor(e.p.y / size), cz = (long long)std::floor(e.p.z / size);
                    for (int b = 0; b < 2; ++b) {
                        if (e.bins[b] == NoBin) continue;
                        Entry& t = slot(cx, cy, cz, level, e.bins[b]);
                        t.r += e.rgb[0] * e.weight, t.g += e.rgb[1] * e.weight, t.b += e.rgb[2] * e.weight, t.w += e.weight;
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

    // The colour at a surface's point (trace space; n its normal facing the camera), the cells' sides footprint's level:
    // true where the store holds it (confidence the share of the neighbouring cells it has, at the finest level it has).
    bool lookup(const surface::V3& p, const D3& n, double foot, float rgb[3], float& confidence) const {
        confidence = 0;
        if (!used) return false;
        std::uint8_t bins[2];
        binsOf(n, bins);
        const int first = levelOf(foot * op.scale);
        double acc[3] = {0, 0, 0}, have = 0;
        for (int k = 0; k < op.levels + 2; ++k) {
            const int level = first + k;
            const double size = std::ldexp(1.0, level);
            const double fx = p.x / size - 0.5, fy = p.y / size - 0.5, fz = p.z / size - 0.5;
            const long long x0 = (long long)std::floor(fx), y0 = (long long)std::floor(fy), z0 = (long long)std::floor(fz);
            const double tx = fx - x0, ty = fy - y0, tz = fz - z0;
            double c[3] = {0, 0, 0}, wsum = 0;
            for (int corner = 0; corner < 8; ++corner) {
                const int dx = corner & 1, dy = corner >> 1 & 1, dz = corner >> 2 & 1;
                const double tri = (dx ? tx : 1 - tx) * (dy ? ty : 1 - ty) * (dz ? tz : 1 - tz);
                if (tri <= 0) continue;
                const Entry* e = find(x0 + dx, y0 + dy, z0 + dz, level, bins[0]);
                if (!e && bins[1] != NoBin) e = find(x0 + dx, y0 + dy, z0 + dz, level, bins[1]);
                if (!e || !(e->w > 0)) continue;
                c[0] += tri * e->r / e->w, c[1] += tri * e->g / e->w, c[2] += tri * e->b / e->w, wsum += tri;
            }
            if (wsum <= 0) continue;
            // This level's share of what the finer ones left.
            const double take = (1.0 - have) * std::min(1.0, wsum / 0.5);
            for (int ch = 0; ch < 3; ++ch) acc[ch] += take * c[ch] / wsum;
            if (have == 0) confidence = float(std::min(1.0, wsum));
            have += take;
            if (have > 0.999) break;
        }
        if (have <= 0) return false;
        for (int ch = 0; ch < 3; ++ch) rgb[ch] = float(acc[ch] / have);
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
    struct Entry {
        long long x = 0, y = 0, z = 0;
        std::int16_t level = 0;
        std::uint8_t bin = 0, full = 0;
        float r = 0, g = 0, b = 0, w = 0;
    };
    std::vector<Entry> table;
    size_t used = 0;
    std::vector<float> sky, skyFilled;  // rgb and weight a direction: summed, and its holes filled (fillSky)

    static int levelOf(double side) { return side > 0 ? int(std::floor(std::log2(side))) : -60; }
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
    static std::uint64_t hashOf(long long x, long long y, long long z, int level, int bin) {
        std::uint64_t h = std::uint64_t(x) * 0x9E3779B97F4A7C15ull;
        h ^= std::uint64_t(y) * 0xC2B2AE3D27D4EB4Full + (h << 6) + (h >> 2);
        h ^= std::uint64_t(z) * 0x165667B19E3779F9ull + (h << 6) + (h >> 2);
        h ^= (std::uint64_t(std::uint16_t(level)) << 8 | std::uint64_t(bin)) * 0x27D4EB2F165667C5ull;
        h ^= h >> 31, h *= 0xBF58476D1CE4E5B9ull, h ^= h >> 29;
        return h;
    }
    const Entry* find(long long x, long long y, long long z, int level, int bin) const {
        if (table.empty()) return nullptr;
        const size_t mask = table.size() - 1;
        for (size_t i = hashOf(x, y, z, level, bin) & mask;; i = (i + 1) & mask) {
            const Entry& e = table[i];
            if (!e.full) return nullptr;
            if (e.x == x && e.y == y && e.z == z && e.level == level && e.bin == bin) return &e;
        }
    }
    Entry& slot(long long x, long long y, long long z, int level, int bin) {
        if ((used + 1) * 2 > table.size()) grow(table.size() * 2);
        const size_t mask = table.size() - 1;
        for (size_t i = hashOf(x, y, z, level, bin) & mask;; i = (i + 1) & mask) {
            Entry& e = table[i];
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
        old.swap(table);
        table.assign(std::max<size_t>(size, 1024), Entry{});
        const size_t mask = table.size() - 1;
        for (const Entry& e : old) {
            if (!e.full) continue;
            size_t i = hashOf(e.x, e.y, e.z, e.level, e.bin) & mask;
            while (table[i].full) i = (i + 1) & mask;
            table[i] = e;
        }
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
    // The directions no picture has shown, from those around them (push-pull, the map wrapping round in u).
    void fillSky() {
        struct Level {
            unsigned w, h;
            std::vector<float> m;
        };
        std::vector<Level> lv;
        lv.push_back({unsigned(SkyW), unsigned(SkyH), std::vector<float>(SkyW * SkyH * 4)});
        for (size_t i = 0; i < SkyW * SkyH; ++i) {
            const float* s = &sky[i * 4];
            float* m = &lv[0].m[i * 4];
            if (s[3] > 0)
                for (int c = 0; c < 3; ++c) m[c] = s[c] / s[3];
            m[3] = s[3] > 0 ? 1.0f : 0.0f;
        }
        while (lv.back().w > 1 || lv.back().h > 1) {
            const Level& f = lv.back();
            Level c{std::max(1u, (f.w + 1) / 2), std::max(1u, (f.h + 1) / 2), {}};
            c.m.assign(size_t(c.w) * c.h * 4, 0.0f);
            for (unsigned y = 0; y < f.h; ++y)
                for (unsigned x = 0; x < f.w; ++x) {
                    const float* s = &f.m[(size_t(y) * f.w + x) * 4];
                    if (!(s[3] > 0)) continue;
                    float* d = &c.m[(size_t(y / 2) * c.w + x / 2) * 4];
                    for (int k = 0; k < 3; ++k) d[k] += s[k] * s[3];
                    d[3] += s[3];
                }
            for (size_t i = 0; i < size_t(c.w) * c.h; ++i) {
                float* d = &c.m[i * 4];
                if (d[3] > 0)
                    for (int k = 0; k < 3; ++k) d[k] /= d[3];
                d[3] = d[3] > 0 ? 1.0f : 0.0f;
            }
            lv.push_back(std::move(c));
        }
        for (size_t k = lv.size() - 1; k-- > 0;) {
            Level& f = lv[k];
            const Level& c = lv[k + 1];
            for (unsigned y = 0; y < f.h; ++y)
                for (unsigned x = 0; x < f.w; ++x) {
                    float* d = &f.m[(size_t(y) * f.w + x) * 4];
                    if (d[3] > 0) continue;
                    const float* s = &c.m[(size_t(std::min(y / 2, c.h - 1)) * c.w + std::min(x / 2, c.w - 1)) * 4];
                    if (!(s[3] > 0)) continue;
                    for (int q = 0; q < 3; ++q) d[q] = s[q];
                    d[3] = 1.0f;
                }
        }
        skyFilled.swap(lv[0].m);
    }
};

class ObjectWarp {
public:
    struct Options {
        double vignette = 0.75;  // the vignette's radius, a share of the picture's half diagonal (0: the whole picture)
        double soft = 0.25;      // its edge: the share of the radius over which it goes to the coarse grid outside
        double dim = 0.6;        // the light at the picture's corners, outside the vignette (1: as inside)
        size_t rays = 60000;     // the grid's rays inside the vignette, at most (the stride from it)
        double jump = 0.03;      // corners whose depths differ by more (relative) are another surface: a ray a pixel
        unsigned rings = 3;      // the fine grid's stages, rings of equal area from the centre out (streamed)
        unsigned threads = 8;
    };
    Options op;
    size_t rays = 0, edgeRays = 0;
    unsigned stride = 0, stages = 0;
    double seconds = 0, firstSeconds = 0, unknown = 0;  // the view's time, its first picture's, the rays the store had nothing for

    // A view of the store through camera nv, by the scene's first hits: each pixel's colour (rgb), lifted depth w (-1 the
    // environment), depth (0 none), state (1 drawn, 2 filled from around it) and doubt (0 to 1). Streamed (the user,
    // 2026-11-22: "the reconstructions should be streamed. the user should be able to see the radial topology updating
    // in realtime"): stage() is called once the whole picture is there from the coarse grid, then after each ring of the
    // fine grid from the centre out; false from it stops the drawing where it stands (the next move has come).
    bool draw(const View& nv, const async::CpuScene& scene, const ObjectStore& store, unsigned w, unsigned h, std::vector<float>& color,
              std::vector<double>& outW, std::vector<float>& outDepth, std::vector<std::uint8_t>& state, std::vector<float>& doubt,
              const std::function<bool()>& stage = {}) {
        const auto began = std::chrono::steady_clock::now();
        const size_t n = size_t(w) * h;
        rays = edgeRays = 0, stages = 0, unknown = 0, firstSeconds = 0;
        if (!w || !h) return false;
        const double angle = ObjectStore::pixelAngle(nv);
        if (!(angle > 0)) return false;
        const double cx = 0.5 * w, cy = 0.5 * h, half = std::sqrt(cx * cx + cy * cy);
        const bool whole = !(op.vignette > 0);
        const double R = whole ? half + 1.0 : op.vignette * half, R0 = whole ? R : R * (1.0 - std::clamp(op.soft, 0.0, 0.99));
        const double inside = std::min(double(n), 3.14159265358979 * R * R);
        stride = unsigned(std::max(1.0, std::ceil(std::sqrt(inside / double(std::max<size_t>(op.rays, 1000))))));
        const unsigned S = stride * 4;
        color.assign(n * 3, 0.0f), outW.assign(n, -1.0), outDepth.assign(n, 0.0f), state.assign(n, 2), doubt.assign(n, 1.0f);
        std::atomic<size_t> traced{0}, empty{0}, edge{0};
        auto shadeRay = [&](double x, double y, Node& o) {
            surface::Ray ray;
            if (!nv.ray(x, y, ray)) {
                o.kind = 3;
                return;
            }
            ray.mask = 1u;
            async::CpuBackend backend{scene};
            const resume::Hit hit = backend.trace(ray);
            traced.fetch_add(1, std::memory_order_relaxed);
            if (hit.geom == ~0u) {
                o.kind = 2;
                o.known = store.skyAt(D3{ray.direction.x, ray.direction.y, ray.direction.z}, o.rgb);
                o.conf = o.known ? 1.0f : 0.0f;
            } else {
                o.kind = 1;
                const double d = nv.depthOf(nv.camera(hit.point));
                o.depth = float(d), o.w = nv.wOf(d);
                const D3 nn = nv.toward(D3{hit.normal.x, hit.normal.y, hit.normal.z}, hit.point);
                o.known = store.lookup(hit.point, nn, ObjectStore::footprint(nv, angle, d), o.rgb, o.conf);
            }
            if (!o.known) empty.fetch_add(1, std::memory_order_relaxed);
        };
        auto radius = [&](double x, double y) { return std::sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy)); };
        // A grid's nodes traced between two radii, then those the store had nothing for filled from the known around them.
        auto trace = [&](Grid& g, double from, double to) {
            parallel(std::max(1u, op.threads), g.gh, [&](size_t j) {
                for (unsigned i = 0; i < g.gw; ++i) {
                    const double x = std::min<double>(double(i) * g.step, w - 1) + 0.5, y = std::min<double>(double(j) * g.step, h - 1) + 0.5;
                    const double r = radius(x, y);
                    if (r < from || r >= to) continue;
                    shadeRay(x, y, g.nodes[j * g.gw + i]);
                }
            });
            fillNodes(g);
        };
        // Each pixel's colour from a grid: bilinear between its cell's corners; smooth: they are one smooth surface.
        auto sample = [&](const Grid& g, unsigned x, unsigned y, Pixel& p, bool* smoothOut) {
            const unsigned i = x / g.step, j = y / g.step;
            const Node* c[4] = {&g.nodes[size_t(j) * g.gw + i], &g.nodes[size_t(j) * g.gw + i + 1], &g.nodes[size_t(j + 1) * g.gw + i],
                                &g.nodes[size_t(j + 1) * g.gw + i + 1]};
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
        // The light outside the vignette, falling off toward the corners.
        auto fall = [&](double r) { return r <= R ? 1.0 : 1.0 - (1.0 - op.dim) * std::clamp((r - R) / std::max(1.0, half - R), 0.0, 1.0); };
        auto write = [&](size_t i, const Pixel& p) {
            for (int ch = 0; ch < 3; ++ch) color[i * 3 + ch] = p.rgb[ch];
            outW[i] = p.w, outDepth[i] = p.depth;
            state[i] = p.conf > 0 ? 1 : 2;
            doubt[i] = std::clamp(1.0f - p.conf, 0.0f, 1.0f);
        };
        // The coarse grid over the whole picture: its first picture.
        Grid coarse = makeGrid(S, w, h);
        trace(coarse, 0.0, 1e30);
        std::vector<Pixel> outside(n);
        parallel(std::max(1u, op.threads), h, [&](size_t yy) {
            const unsigned y = unsigned(yy);
            for (unsigned x = 0; x < w; ++x) {
                const size_t i = size_t(y) * w + x;
                Pixel& p = outside[i];
                sample(coarse, x, y, p, nullptr);
                const double f = fall(radius(x + 0.5, y + 0.5));
                for (int ch = 0; ch < 3; ++ch) p.rgb[ch] = float(p.rgb[ch] * f);
                write(i, p);
            }
        });
        firstSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
        ++stages;
        auto finish = [&] {
            edgeRays = edge.load();
            rays = traced.load();
            unknown = rays ? double(empty.load()) / double(rays) : 0.0;
            seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
        };
        if (stage && !stage()) {
            finish();
            return true;
        }
        // The fine grid ring by ring, rings of equal area out to the vignette's edge: each ring's pixels from the fine grid
        // (a ray a pixel in a cell its corners are not one smooth surface of), its outer band going over to the coarse grid's
        // until the next ring comes.
        Grid fine = makeGrid(stride, w, h);
        const double reach = R + 2.0 * stride;
        const unsigned rings = std::max(1u, op.rings);
        const double band = std::max(4.0 * stride, 0.08 * R);
        std::vector<Pixel> inner(n);
        std::vector<std::uint8_t> have(n, 0);
        double tracedTo = 0, validTo = 0;
        for (unsigned k = 1; k <= rings; ++k) {
            const bool last = k == rings;
            const double to = last ? reach : reach * std::sqrt(double(k) / rings);
            trace(fine, tracedTo, to);
            tracedTo = to;
            // A pixel's fine colour once its cell's corners are all traced: up to a cell and a half inside the ring.
            const double valid = last ? reach : std::max(0.0, to - 1.5 * stride);
            const double from = validTo;
            parallel(std::max(1u, op.threads), h, [&](size_t yy) {
                const unsigned y = unsigned(yy);
                for (unsigned x = 0; x < w; ++x) {
                    const size_t i = size_t(y) * w + x;
                    const double r = radius(x + 0.5, y + 0.5);
                    if (r >= valid) continue;
                    if (!have[i] && r >= from - 1.0) {
                        Pixel& p = inner[i];
                        bool smooth = false;
                        sample(fine, x, y, p, &smooth);
                        if (!smooth) {
                            // A silhouette or a crease in the cell: the pixel's own ray.
                            Node own;
                            shadeRay(x + 0.5, y + 0.5, own);
                            edge.fetch_add(1, std::memory_order_relaxed);
                            if (own.kind == 1 || own.kind == 2) {
                                if (own.known) {
                                    for (int ch = 0; ch < 3; ++ch) p.rgb[ch] = own.rgb[ch];
                                    p.conf = own.conf;
                                } else p.conf = 0;  // nothing in the store: the cell's colours, as filled
                                p.w = own.kind == 1 ? own.w : -1.0, p.depth = own.kind == 1 ? own.depth : 0.0f;
                            }
                        }
                        have[i] = 1;
                    }
                    if (!have[i]) continue;
                    // Over to the coarse grid: at the vignette's edge in the last ring, else in this ring's outer band.
                    double t = last ? (r <= R0 ? 0.0 : r >= R ? 1.0 : (r - R0) / std::max(1e-9, R - R0))
                                    : std::clamp((r - (valid - band)) / band, 0.0, 1.0);
                    if (whole && last) t = 0;
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
            validTo = valid;
            ++stages;
            if (!last && stage && !stage()) break;
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
        bool known = false;
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
    // Nodes at multiples of the step, the last row and column at the picture's edge.
    static Grid makeGrid(unsigned step, unsigned w, unsigned h) {
        Grid g;
        g.step = step, g.gw = (w - 1) / step + 2, g.gh = (h - 1) / step + 2;
        g.nodes.assign(size_t(g.gw) * g.gh, Node{});
        return g;
    }
    // The traced nodes the store had nothing for, from the known around them (push-pull over the grid).
    static void fillNodes(Grid& g) {
        std::vector<float> c(size_t(g.gw) * g.gh * 4, 0.0f);
        for (size_t k = 0; k < g.nodes.size(); ++k)
            if (g.nodes[k].known) c[k * 4] = g.nodes[k].rgb[0], c[k * 4 + 1] = g.nodes[k].rgb[1], c[k * 4 + 2] = g.nodes[k].rgb[2], c[k * 4 + 3] = 1;
        fillGrid(c, g.gw, g.gh);
        for (size_t k = 0; k < g.nodes.size(); ++k) {
            Node& o = g.nodes[k];
            if ((o.kind == 1 || o.kind == 2) && !o.known && c[k * 4 + 3] > 0) o.rgb[0] = c[k * 4], o.rgb[1] = c[k * 4 + 1], o.rgb[2] = c[k * 4 + 2];
        }
    }
    // Push-pull: rgba a node (a 0 or 1), the empty nodes from the known around them, coarse to fine.
    static void fillGrid(std::vector<float>& c, unsigned w, unsigned h) {
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
                    for (int k = 0; k < 3; ++k) d[k] += s[k];
                    d[3] += 1;
                }
            for (size_t i = 0; i < size_t(q.w) * q.h; ++i) {
                float* d = &q.m[i * 4];
                if (d[3] > 0)
                    for (int k = 0; k < 3; ++k) d[k] /= d[3];
                d[3] = d[3] > 0 ? 1.0f : 0.0f;
            }
            lv.push_back(std::move(q));
        }
        for (size_t k = lv.size() - 1; k-- > 0;) {
            Level& f = lv[k];
            const Level& q = lv[k + 1];
            for (unsigned y = 0; y < f.h; ++y)
                for (unsigned x = 0; x < f.w; ++x) {
                    float* d = &f.m[(size_t(y) * f.w + x) * 4];
                    if (d[3] > 0) continue;
                    const float* s = &q.m[(size_t(std::min(y / 2, q.h - 1)) * q.w + std::min(x / 2, q.w - 1)) * 4];
                    if (!(s[3] > 0)) continue;
                    for (int r = 0; r < 3; ++r) d[r] = s[r];
                    d[3] = 1.0f;
                }
        }
        c.swap(lv[0].m);
    }
};

}  // namespace rhea
