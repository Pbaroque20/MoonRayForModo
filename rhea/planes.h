// Rhea's virtual planes past the front hyperplane (rhea/DESIGN.md 25): the slanted planes and the back plane. The front
// hyperplane is the probes' Bregman Delaunay triangulation over the picture (persistent.h); a pixel it does not hold for
// is taken by a slanted plane, else by the back plane, the GPU's depths deciding each.
//
// - The slanted planes (PlanarLayer): probes on one flat surface (neighbours on the front triangulation whose normals
//   agree and that lie on each other's plane) make a planar region; each region is triangulated in its own plane's
//   coordinates, where a grazing wall's probes are not foreshortened and no triangle crosses to another surface, and its
//   triangles are drawn into the picture as geometry is, the nearest kept. A pixel whose front triangle spans two
//   surfaces (at grazing angles, most of them) takes its own surface's plane instead.
// - The back plane (BackPlane): camera resolution, behind every probe: each pixel of the last picture that met one
//   surface keeps its point (from the z-buffer, the depth outputs) and its light (the surface's colour divided out). On
//   a camera move each point goes into the new view, the nearest kept, and counts where the new frame's own depths at
//   that pixel hold it: distant and small things, too far or too small for probes, keep per-pixel light.
#pragma once
#include "persistent.h"
#include <array>
#include <numeric>

namespace rhea {

// A probe's light and colour as summed (persistent.h's WorldProbe), demodulated where both are bright enough.
inline bool probeLight(const WorldProbe& p, float demodFloor, double light[3], bool& demod) {
    return ProbeField::probeLightOf(p, demodFloor, light, demod);
}

class PlanarLayer {
public:
    struct Tri {
        int k[3];       // the frame's probes (FieldFrame indices)
        Plane plane;    // its lifted plane (the verification's)
        bool edge = false;  // its corners' light too far apart (the radiance-edge rule)
        bool bridged = false;  // it spans what does not lie on its plane (support)
        int covered = 0;       // its pixels (their centres inside it)
    };
    std::vector<Tri> tris;
    std::vector<int> triOf;  // each pixel's nearest planar triangle, -1 none
    size_t regions = 0, planar = 0;  // regions of three probes or more; their probes

    // No planar regions (the layer off, or a directional camera's: its planes do not lift to planes).
    void none(unsigned W, unsigned H) { tris.clear(), triOf.assign(size_t(W) * H, -1), regions = planar = 0; }

    // The frame's planar regions, triangulated in their planes and drawn into the picture.
    // maxEdge: a triangle's longest side in the picture at most this (pixels): a region's triangulation spans its convex
    // hull, and its long sides cross what the region does not hold (a column's foot, a shadow between its probes).
    void build(const FieldFrame& f, const std::vector<WorldProbe>& probes, unsigned W, unsigned H, double tol, double tauR, float demodFloor,
               double maxEdge = 1e300) {
        tris.clear(), regions = planar = 0;
        triOf.assign(size_t(W) * H, -1);
        const size_t n = f.ids.size();
        if (n < 3 || f.normal.size() != n) return;
        // Union-find over the front triangulation's edges: two probes on one plane.
        std::vector<int> parent(n);
        std::iota(parent.begin(), parent.end(), 0);
        auto find = [&](int a) {
            while (parent[a] != a) a = parent[a] = parent[parent[a]];
            return a;
        };
        auto samePlane = [&](int a, int b) { return ProbeField::samePlane(f, probes, a, b, tol); };
        for (size_t t = 0; t * 3 < f.tris.size(); ++t)
            for (int e = 0; e < 3; ++e) {
                const int a = f.tris[3 * t + e], b = f.tris[3 * t + (e + 1) % 3];
                if (samePlane(a, b)) parent[find(a)] = find(b);
            }
        std::vector<std::vector<int>> members(n);
        for (size_t k = 0; k < n; ++k) members[find(int(k))].push_back(int(k));
        // The probes' light, for the radiance-edge rule.
        std::vector<double> lum(n, -1.0);
        for (size_t k = 0; k < n; ++k) {
            double l[3];
            bool dm;
            if (probeLight(probes[f.ids[k]], demodFloor, l, dm)) lum[k] = 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
        }
        std::vector<double> best(size_t(W) * H, -1e300);
        for (const auto& m : members) {
            if (m.size() < 3) continue;
            ++regions, planar += m.size();
            // The region's plane and two axes in it.
            D3 nn{0, 0, 0};
            for (int k : m) nn.x += f.normal[k].x, nn.y += f.normal[k].y, nn.z += f.normal[k].z;
            const double nl = std::sqrt(nn.x * nn.x + nn.y * nn.y + nn.z * nn.z);
            if (!(nl > 0)) continue;
            nn = {nn.x / nl, nn.y / nl, nn.z / nl};
            D3 e1 = std::fabs(nn.x) < 0.9 ? D3{1, 0, 0} : D3{0, 1, 0};
            const double dd = e1.x * nn.x + e1.y * nn.y + e1.z * nn.z;
            e1 = {e1.x - dd * nn.x, e1.y - dd * nn.y, e1.z - dd * nn.z};
            const double el = std::sqrt(e1.x * e1.x + e1.y * e1.y + e1.z * e1.z);
            e1 = {e1.x / el, e1.y / el, e1.z / el};
            const D3 e2{nn.y * e1.z - nn.z * e1.y, nn.z * e1.x - nn.x * e1.z, nn.x * e1.y - nn.y * e1.x};
            const surface::V3& o = probes[f.ids[m[0]]].P;
            std::vector<double> uv;
            uv.reserve(m.size() * 2);
            for (int k : m) {
                const surface::V3& p = probes[f.ids[k]].P;
                const D3 d{double(p.x) - o.x, double(p.y) - o.y, double(p.z) - o.z};
                uv.push_back(d.x * e1.x + d.y * e1.y + d.z * e1.z), uv.push_back(d.x * e2.x + d.y * e2.y + d.z * e2.z);
            }
            const Delaunay dl(uv);
            for (size_t t = 0; t * 3 < dl.triangles.size(); ++t) {
                Tri tri;
                for (int j = 0; j < 3; ++j) tri.k[j] = m[dl.triangles[3 * t + j]];
                double x[3], y[3], w[3];
                for (int j = 0; j < 3; ++j) x[j] = f.xy[2 * tri.k[j]], y[j] = f.xy[2 * tri.k[j] + 1], w[j] = f.w[tri.k[j]];
                bool small = true;
                for (int j = 0; j < 3; ++j) {
                    const double dx = x[(j + 1) % 3] - x[j], dy = y[(j + 1) % 3] - y[j];
                    small = small && dx * dx + dy * dy <= maxEdge * maxEdge;
                }
                if (!small) continue;
                tri.plane = planeThrough(x, y, w);
                if (!tri.plane.ok) continue;
                double lo = 1e300, hi = -1e300, mean = 0;
                bool lit = true;
                for (int j = 0; j < 3; ++j) {
                    lit = lit && lum[tri.k[j]] >= 0;
                    lo = std::min(lo, lum[tri.k[j]]), hi = std::max(hi, lum[tri.k[j]]), mean += lum[tri.k[j]] / 3;
                }
                if (!lit) continue;
                tri.edge = (hi - lo) / (mean + 1e-3) > tauR;
                const int id = int(tris.size());
                tris.push_back(tri);
                // Drawn into the picture: each pixel's centre inside, the nearest (largest w) kept.
                const int x0 = std::max(0, int(std::floor(std::min({x[0], x[1], x[2]}) - 0.5)));
                const int x1 = std::min(int(W) - 1, int(std::ceil(std::max({x[0], x[1], x[2]}))));
                const int y0 = std::max(0, int(std::floor(std::min({y[0], y[1], y[2]}) - 0.5)));
                const int y1 = std::min(int(H) - 1, int(std::ceil(std::max({y[0], y[1], y[2]}))));
                for (int py = y0; py <= y1; ++py)
                    for (int px = x0; px <= x1; ++px) {
                        double b[3];
                        if (!barycentric(px + 0.5, py + 0.5, x, y, b, 1e-9)) continue;
                        const double here = tri.plane.at(px + 0.5, py + 0.5);
                        const size_t i = size_t(py) * W + px;
                        ++tris[size_t(id)].covered;
                        if (here > best[i]) best[i] = here, triOf[i] = id;
                    }
            }
        }
    }

    // A pixel's light by its planar triangle (demodulated corners, perspective-correct over the plane, times the pixel's
    // colour); false where it has none, or the triangle is a light edge.
    bool lightAt(const FieldFrame& f, const std::vector<WorldProbe>& probes, unsigned x, unsigned y, unsigned W, const float* pixelAlbedo,
                 float demodFloor, bool demodOn, double out[3]) const {
        const int t = triOf[size_t(y) * W + x];
        if (t < 0 || tris[size_t(t)].edge || tris[size_t(t)].bridged) return false;
        const Tri& tri = tris[size_t(t)];
        double tx[3], ty[3], b[3], light[3][3];
        bool dm[3], demod = demodOn && pixelAlbedo && 0.2126 * pixelAlbedo[0] + 0.7152 * pixelAlbedo[1] + 0.0722 * pixelAlbedo[2] >= demodFloor;
        for (int j = 0; j < 3; ++j) {
            tx[j] = f.xy[2 * tri.k[j]], ty[j] = f.xy[2 * tri.k[j] + 1];
            if (!probeLight(probes[f.ids[tri.k[j]]], demodFloor, light[j], dm[j])) return false;
            demod = demod && dm[j];
        }
        if (!demod) {
            // The corners' light as it is: plain radiance (metal, emitters, the dark).
            for (int j = 0; j < 3; ++j) {
                const WorldProbe& p = probes[f.ids[tri.k[j]]];
                for (int c = 0; c < 3; ++c) light[j][c] = p.sum[c] / p.weight;
            }
        }
        if (!barycentric(x + 0.5, y + 0.5, tx, ty, b, 1e-6)) b[0] = 1, b[1] = b[2] = 0;
        const double s = b[0] * f.w[tri.k[0]] + b[1] * f.w[tri.k[1]] + b[2] * f.w[tri.k[2]];
        if (s > 0 && f.view.kind != View::Orthographic)
            for (int j = 0; j < 3; ++j) b[j] = b[j] * f.w[tri.k[j]] / s;
        for (int c = 0; c < 3; ++c) {
            const double v = b[0] * light[0][c] + b[1] * light[1][c] + b[2] * light[2][c];
            out[c] = std::max(0.0, demod ? pixelAlbedo[c] * v : v);
        }
        return true;
    }
    const Plane* planeAt(unsigned x, unsigned y, unsigned W) const {
        const int t = triOf[size_t(y) * W + x];
        return t < 0 || tris[size_t(t)].bridged ? nullptr : &tris[size_t(t)].plane;
    }

    // The frame's own depths over each triangle: one whose pixels do not lie on its plane, at least share of them, spans
    // something nearer (an object standing on the plane, its foot and its shadow) or a hole, and is not used. Its corners
    // lit and the plane in shadow under the object, its light had been 28 to 44% bright about Sponza's columns (DESIGN.md
    // 25); the corners' light rule cannot see a shadow wholly inside a triangle. Returns the triangles kept.
    size_t support(const View& view, const std::vector<float>& depthMin, const std::vector<float>& depthMax, const FieldOptions& fo, unsigned W,
                   double share) {
        std::vector<int> held(tris.size(), 0);
        for (size_t i = 0; i < triOf.size(); ++i) {
            const int t = triOf[i];
            if (t >= 0 && ProbeField::planeHolds(view, tris[size_t(t)].plane, unsigned(i % W), unsigned(i / W), depthMin[i], depthMax[i], fo)) ++held[size_t(t)];
        }
        size_t kept = 0;
        for (size_t t = 0; t < tris.size(); ++t) {
            tris[t].bridged = double(held[t]) < share * double(tris[t].covered);
            kept += !tris[t].bridged;
        }
        return kept;
    }
};

class BackPlane {
public:
    // The last picture's pixels: each one's point (trace space), its light (demodulated where demod), its weight (the
    // samples behind it, faded on moves).
    std::vector<float> P, L, weight, wv;  // wv: each point's lifted depth in the view it was stored from
    std::vector<uint8_t> valid, demod;
    unsigned W = 0, H = 0;
    View view;  // the view it was stored from (gather looks its points up there)
    bool empty() const { return valid.empty(); }
    void clear() { P.clear(), L.clear(), weight.clear(), wv.clear(), valid.clear(), demod.clear(), W = H = 0; }

    // The back plane as a frame sees it, a pixel each: the nearest point landing there (w its lifted depth, -1 none), its
    // light, weight and demodulation, and held: the frame's own depths at the pixel hold it (set by the frame's user).
    // gathered: looked up from the frame's own depths (gather), held already decided.
    struct Seen {
        std::vector<double> w;
        std::vector<float> P, L, weight;
        std::vector<uint8_t> demod, held;
        bool gathered = false;
    };

    // The back plane looked up from a frame's own depths (the frame's view, its nearest first-hit depths): each pixel's
    // point found where it lay in the stored view, and its light blended from the four stored pixels about it that saw
    // that point's surface (their lifted depths within reach of the point's), as realtime path tracers reproject their
    // history. Exact to a fraction of a pixel where the forward lift (reproject) moved each point to the pixel it landed
    // in, its texture and edges up to half a pixel off, and no holes where the camera comes closer. held where at least a
    // quarter of the blend's weight found the surface.
    void gather(const View& now, unsigned w, unsigned h, unsigned threads, const std::vector<float>& depthMin, double reach, Seen& s) const {
        const size_t N = size_t(w) * h;
        s.w.assign(N, -1.0), s.P.assign(N * 3, 0.0f), s.L.assign(N * 3, 0.0f), s.weight.assign(N, 0.0f), s.demod.assign(N, 0), s.held.assign(N, 0);
        s.gathered = true;
        if (valid.empty() || wv.size() != valid.size()) return;
        parallel(threads, h, [&](size_t y) {
            for (unsigned x = 0; x < w; ++x) {
                const size_t i = y * w + x;
                const float d = depthMin[i];
                if (!(std::isfinite(d) && d > 0)) continue;
                surface::V3 p;
                if (!now.pointAt(x + 0.5, y + 0.5, d, p)) continue;
                double ox = x + 0.5, oy = y + 0.5, ow;  // where a directional camera's lift starts looking
                if (!view.lift(p, ox, oy, ow, true) || !(ow > 0)) continue;
                // The four stored pixels about (ox, oy), bilinear, each where it saw this surface.
                const double fx = ox - 0.5, fy = oy - 0.5;
                const int x0 = int(std::floor(fx)), y0 = int(std::floor(fy));
                const double ax = fx - x0, ay = fy - y0;
                double sum = 0, light[3] = {0, 0, 0}, wt = 0;
                bool dm = false;
                for (int t = 0; t < 4; ++t) {
                    const int tx = x0 + (t & 1), ty = y0 + (t >> 1);
                    if (tx < 0 || ty < 0 || tx >= int(W) || ty >= int(H)) continue;
                    const size_t k = size_t(ty) * W + size_t(tx);
                    if (!valid[k] || std::fabs(double(wv[k]) - ow) > reach * ow) continue;
                    const double b = ((t & 1) ? ax : 1 - ax) * ((t >> 1) ? ay : 1 - ay);
                    if (!(b > 0)) continue;
                    if (sum > 0 && bool(demod[k]) != dm) continue;  // one kind of light in a blend
                    if (sum == 0) dm = demod[k];
                    sum += b, wt += b * weight[k];
                    for (int c = 0; c < 3; ++c) light[c] += b * L[k * 3 + c];
                }
                if (sum < 0.25) continue;
                s.w[i] = now.wOf(d), s.weight[i] = float(wt / sum), s.demod[i] = dm, s.held[i] = 1;
                s.P[i * 3] = p.x, s.P[i * 3 + 1] = p.y, s.P[i * 3 + 2] = p.z;
                for (int c = 0; c < 3; ++c) s.L[i * 3 + c] = float(light[c] / sum);
            }
        });
    }

    // Into a frame's view (the points lifted in parallel, the nearest kept).
    void reproject(const View& view, unsigned w, unsigned h, unsigned threads, Seen& s) const {
        const size_t N = size_t(w) * h;
        s.w.assign(N, -1.0), s.P.assign(N * 3, 0.0f), s.L.assign(N * 3, 0.0f), s.weight.assign(N, 0.0f), s.demod.assign(N, 0), s.held.assign(N, 0);
        s.gathered = false;
        if (valid.empty()) return;
        std::vector<long long> at(valid.size(), -1);
        std::vector<double> lw(valid.size(), 0.0);
        parallel(threads, H, [&](size_t y) {
            for (unsigned x = 0; x < W; ++x) {
                const size_t k = y * W + x;
                if (!valid[k]) continue;
                double px = x + 0.5, py = y + 0.5, ww;  // the old pixel: where a directional camera's lift starts looking
                if (!view.lift(surface::V3{P[k * 3], P[k * 3 + 1], P[k * 3 + 2]}, px, py, ww, true)) continue;
                if (!(px >= 0 && py >= 0 && px < w && py < h) || !(ww > 0)) continue;
                at[k] = (long long)(size_t(py) * w + size_t(px)), lw[k] = ww;
            }
        });
        for (size_t k = 0; k < valid.size(); ++k) {
            if (at[k] < 0) continue;
            const size_t i = size_t(at[k]);
            if (lw[k] <= s.w[i]) continue;
            s.w[i] = lw[k], s.weight[i] = weight[k], s.demod[i] = demod[k];
            for (int c = 0; c < 3; ++c) s.P[i * 3 + c] = P[k * 3 + c], s.L[i * 3 + c] = L[k * 3 + c];
        }
    }
    // The back plane as its own camera sees it (the camera unmoved): every point held where it is.
    void asSeen(Seen& s) const {
        s.w.assign(wv.begin(), wv.end()), s.P = P, s.L = L, s.weight = weight, s.demod = demod, s.held = valid, s.gathered = true;
    }

    // A picture's pixels that met one surface (their depths within the tolerance of each other) kept: light (four a
    // pixel: what the probes carry), albedo (three a pixel, or none), depths, samples a pixel. prior: the back plane as
    // this picture saw it; where the picture's depths held a point (prior->held) its light is folded in, its weight faded
    // by fade (a camera move), so that the back plane gathers samples over the frames as the probes do.
    void store(const View& view, unsigned w, unsigned h, unsigned threads, const std::vector<float>& light, const std::vector<float>* albedo,
               const std::vector<float>& depthMin, const std::vector<float>& depthMax, const std::vector<unsigned>& counts, double tol,
               float demodFloor, const Seen* prior, double fade, double cap) {
        W = w, H = h, this->view = view;
        const size_t N = size_t(w) * h;
        P.assign(N * 3, 0.0f), L.assign(N * 3, 0.0f), weight.assign(N, 0.0f), wv.assign(N, 0.0f), valid.assign(N, 0), demod.assign(N, 0);
        if (prior && prior->held.size() != N) prior = nullptr;
        parallel(threads, h, [&](size_t y) {
            for (unsigned x = 0; x < w; ++x) {
                const size_t i = y * w + x;
                const bool had = prior && prior->held[i];
                const float d0 = depthMin[i], d1 = std::max(depthMax[i], depthMin[i]);
                const double n = i < counts.size() ? double(counts[i]) : 0.0;
                bool fresh = n > 0 && std::isfinite(d0) && d0 > 0 && std::isfinite(d1);
                if (fresh) {
                    const double w0 = view.wOf(d0), w1 = view.wOf(d1);
                    fresh = w0 > 0 && (w0 - w1) <= 2 * tol * w0;  // one surface
                }
                surface::V3 p;
                if (fresh) fresh = view.pointAt(x + 0.5, y + 0.5, d0, p);
                if (!fresh && !had) continue;
                if (!fresh) {
                    // Nothing new here (a frame stopped before this pixel): the point as it was.
                    for (int c = 0; c < 3; ++c) P[i * 3 + c] = prior->P[i * 3 + c], L[i * 3 + c] = prior->L[i * 3 + c];
                    weight[i] = float(fade * prior->weight[i]), demod[i] = prior->demod[i], valid[i] = prior->w[i] > 0;
                    wv[i] = float(prior->w[i]);
                    continue;
                }
                const float* a = albedo ? &(*albedo)[i * 3] : nullptr;
                const bool dm = a && 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2] >= demodFloor;
                const double pw = had && prior->demod[i] == dm ? fade * prior->weight[i] : 0.0;
                for (int c = 0; c < 3; ++c) {
                    const double v = dm ? light[i * 4 + c] / std::max(a[c], demodFloor) : light[i * 4 + c];
                    // prior->L only where there is a prior: XPU2's first frame of a scene ended with none, and read through
                    // the null pointer it ended the session (0xC0000005 reading 0x30), the kit falling back to MoonRay XPU.
                    const double mixed = pw > 0 ? (n * v + pw * prior->L[i * 3 + c]) / (n + pw) : v;
                    L[i * 3 + c] = std::isfinite(mixed) ? float(mixed) : 0.0f;
                }
                P[i * 3] = p.x, P[i * 3 + 1] = p.y, P[i * 3 + 2] = p.z;
                weight[i] = float(std::min(cap, n + pw)), demod[i] = dm, valid[i] = 1, wv[i] = float(view.wOf(d0));
            }
        });
    }
};

}  // namespace rhea
