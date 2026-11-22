// Rhea's drag pictures as a mesh gradient (rhea/DESIGN.md 28).
//
// A camera move's first picture is the last picture rendered, moved into the new view. Moved pixel by pixel (DESIGN.md
// 26) it broke into specks and streaks: a magnified surface left gaps between its pixels, the environment (no depth) went
// black, and each warp of a warp lost more, until a long drag was black with a few strips (the user's video, 2026-11-21).
//
// Here the picture becomes a mesh first (build): its points sparse where the picture is smooth, denser where its depth
// jumps, each point the picture's colour around it averaged over its own surface - a neighbour counts fully while its
// depth is within `soft` of the point's plane, less and less up to `jump`, not at all past it (the elevations' threshold
// decides how far a colour reaches toward the next point). The environment's points are directions. The picture's edges
// go on as skirts (its border points pushed out a picture's width at their own depth), so that a turn shows the sky and
// the ground going on rather than a smear. The mesh's triangles are drawn into the new view (warp), their points' colours
// interpolated across them - a mesh gradient - the nearest surface winning; what no triangle covers (what lay behind a
// surface, a crack between cells of two sizes) is closed from its own surface or filled from the farthest around it,
// coarse to fine (push-pull). Textures come out as averaged colour, as phase 1 has them.
//
// Edges (the user, 2026-11-21: the gradients "splotch between the dragon and the sky"): a pixel at a silhouette holds
// both sides' samples, but the depth outputs leave the environment's out (a miss puts no depth), so it reads as the
// surface's with the sky's colour in it - and with depth of field that band is several pixels wide. A pixel is mixed
// where its alpha says the environment is in it (alpha that holds the environment at 0) or its depth outputs' nearest and
// farthest are a jump apart: mixed pixels give their colour to no point but their own, and one mostly the environment's
// (alpha under a half) is left out of the mesh (filled from the farthest around it, as what lay behind).
#pragma once
#include "view.h"
#include "virtual_surface.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <vector>

namespace rhea {

class MeshWarp {
public:
    struct Options {
        double cell = 16;    // the coarsest cell, pixels of a 1280 x 720 picture (scaled by the picture's size, a power of two)
        double jump = 0.03;  // a depth jump between neighbouring pixels: the lifted depth off its neighbours' line by this share
        double soft = 0.01;  // a point's colour takes its neighbours within this share of depth off its plane, less up to jump
        bool skirts = true;  // the picture's edges pushed out a picture's width, at their depth (the environment's as directions)
        bool mixed = true;   // silhouette pixels (alpha, depth range) kept out of other points' colour
        unsigned threads = 8;
    };
    Options op;
    size_t vertexCount = 0, triangleCount = 0, mixedCount = 0, droppedCount = 0;
    unsigned cellSize = 0;  // the coarsest cell this picture's mesh was built with
    double buildSeconds = 0, warpSeconds = 0, drawnShare = 0;

    bool valid() const { return ok; }
    void clear() { ok = false; }

    // The mesh of a picture seen through `view`: its colour (rgba), samples, and its nearest first-hit depth a pixel (0
    // none: the environment where the pixel has colour) and farthest (empty: not known). False where it has nothing to move.
    bool build(const View& view, unsigned w, unsigned h, const std::vector<float>& rgba, const std::vector<std::uint32_t>& counts,
               const std::vector<float>& depth, const std::vector<float>& depthFar) {
        const auto began = std::chrono::steady_clock::now();
        ok = false;
        const size_t n = size_t(w) * h;
        if (!w || !h || w < 2 || h < 2 || rgba.size() != n * 4 || depth.size() != n || view.kind == View::Directional) return false;
        src = view, W = w, H = h;
        const unsigned threads = std::max(1u, op.threads);
        // Each pixel: a surface (its lifted depth), the environment (colour, no depth: lifted depth 0), or nothing.
        kind.resize(n), lw.resize(n), color.resize(n * 3), mixed.assign(n, 0);
        std::vector<double> farthest(H, 0.0);
        std::vector<size_t> skyClear(H, 0), skyAll(H, 0), solid(H, 0), surfaces(H, 0);
        parallel(threads, H, [&](size_t y) {
            double far = 0;
            for (size_t i = y * W; i < (y + 1) * W; ++i) {
                bool lit = i < counts.size() && counts[i] > 0;
                for (int k = 0; k < 3; ++k) {
                    const float v = rgba[i * 4 + k];
                    const float c = std::isfinite(v) ? std::max(0.0f, v) : 0.0f;
                    lit = lit || c > 0;
                    color[i * 3 + k] = c;
                }
                const float d = depth[i];
                const float a = rgba[i * 4 + 3];
                if (lit && d > 0 && std::isfinite(d)) {
                    kind[i] = 1, lw[i] = view.wOf(d), far = std::max(far, double(d));
                    ++surfaces[y];
                    solid[y] += a >= 0.9f;
                } else if (lit && !(d > 0)) {
                    kind[i] = 2, lw[i] = 0;
                    ++skyAll[y];
                    skyClear[y] += std::isfinite(a) && a <= 0.05f;
                } else kind[i] = 0, lw[i] = -1;
            }
            farthest[y] = far;
        });
        far = 1;
        for (double f : farthest) far = std::max(far, f);
        // Alpha tells the environment apart where the environment's pixels have none and most of the surfaces' are whole.
        size_t sc = 0, sa = 0, so = 0, su = 0;
        for (size_t y = 0; y < H; ++y) sc += skyClear[y], sa += skyAll[y], so += solid[y], su += surfaces[y];
        const bool alphaSays = op.mixed && su > 0 && so * 2 >= su && (sa == 0 || sc * 10 >= sa * 9);
        const bool farSays = op.mixed && depthFar.size() == n;
        std::vector<size_t> mixedIn(H, 0), droppedIn(H, 0);
        if (alphaSays || farSays)
            parallel(threads, H, [&](size_t y) {
                for (size_t i = y * W; i < (y + 1) * W; ++i) {
                    if (kind[i] != 1) continue;
                    const float a = rgba[i * 4 + 3];
                    bool m = false;
                    if (alphaSays && std::isfinite(a) && a < 0.98f) {
                        // Mostly the environment's: out of the mesh (filled as what lay behind).
                        if (a < 0.5f) {
                            kind[i] = 0, lw[i] = -1, ++droppedIn[y];
                            continue;
                        }
                        m = true;
                    }
                    if (farSays && !m) {
                        const float df = depthFar[i];
                        if (std::isfinite(df) && df > 0) {
                            const double wf = view.wOf(df);
                            m = std::fabs(lw[i] - wf) > op.jump * std::max(lw[i], wf);
                        }
                    }
                    if (m) mixed[i] = 1, ++mixedIn[y];
                }
            });
        mixedCount = droppedCount = 0;
        for (size_t y = 0; y < H; ++y) mixedCount += mixedIn[y], droppedCount += droppedIn[y];
        // The jumps between neighbours (horizontal: a pixel and the next; vertical: a pixel and the one below).
        eh.assign(n, 0), ev.assign(n, 0);
        auto jumpBetween = [&](size_t a, size_t b, long long beforeA, long long afterB) -> uint8_t {
            const uint8_t ka = kind[a], kb = kind[b];
            if (ka != kb || ka == 0) return 1;
            if (ka == 2) return 0;
            const double wa = lw[a], wb = lw[b], m = std::max(wa, wb);
            if (!(m > 0)) return 1;
            // Off the line through the neighbours (on a plane the lifted depth is affine across the picture: none), from
            // either side; a pixel at the picture's edge or a surface's, its step alone.
            double e = -1;
            if (beforeA >= 0 && kind[size_t(beforeA)] == 1) e = std::fabs(wb - (2 * wa - lw[size_t(beforeA)]));
            if (afterB >= 0 && kind[size_t(afterB)] == 1) {
                const double e2 = std::fabs(wa - (2 * wb - lw[size_t(afterB)]));
                e = e < 0 ? e2 : std::min(e, e2);
            }
            if (e < 0) e = std::fabs(wb - wa);
            return e > op.jump * m ? 1 : 0;
        };
        parallel(threads, H, [&](size_t y) {
            for (unsigned x = 0; x < W; ++x) {
                const size_t i = y * W + x;
                if (x + 1 < W) eh[i] = jumpBetween(i, i + 1, x > 0 ? (long long)(i - 1) : -1, x + 2 < W ? (long long)(i + 2) : -1);
                if (y + 1 < H) ev[i] = jumpBetween(i, i + W, y > 0 ? (long long)(i - W) : -1, y + 2 < H ? (long long)(i + 2 * W) : -1);
            }
        });
        // Summed areas of the jumps and of the empty pixels: whether a cell is smooth, in four reads.
        sumOf(eh, seh), sumOf(ev, sev);
        empty.resize(n);
        for (size_t i = 0; i < n; ++i) empty[i] = kind[i] == 0;
        sumOf(empty, sempty);
        // The cells, coarse to fine: a smooth cell two triangles over its corners, a cell with a jump four of half its
        // size, a pixel's cell the triangles no jump crosses.
        const double scale = std::sqrt(double(W) * double(H) / (1280.0 * 720.0));
        const double want = std::max(1.0, op.cell * scale);
        cellSize = 1;
        while (cellSize * 2 <= want * 1.41421356) cellSize *= 2;
        const unsigned S = cellSize;
        const unsigned rows = (H - 1 + S - 1) / S;
        std::vector<std::vector<std::uint32_t>> found(rows);
        parallel(threads, rows, [&](size_t r) {
            std::vector<std::uint32_t>& out = found[r];
            out.clear();
            for (unsigned x0 = 0; x0 + 1 < W; x0 += S) cell(x0, unsigned(r) * S, S, out);
        });
        // The skirts: along each edge, segments of the border smooth between their ends (halved where not, as cells
        // are), each a quad from the border out to a picture's width beyond it. Their corners: the border pixels (as
        // points of the mesh) and their pushed-out twins (virtual points, numbered past the pixels).
        std::vector<std::uint32_t> skirt;
        twins.clear();
        if (op.skirts) {
            const unsigned M = std::max(W, H);
            auto side = [&](int which) {
                // which: 0 left, 1 right (along y), 2 top, 3 bottom (along x).
                const bool vertical = which < 2;
                const unsigned length = vertical ? H : W;
                for (unsigned s0 = 0; s0 + 1 < length; s0 += S) segment(which, s0, std::min(s0 + S, length - 1), S, M, skirt);
            };
            for (int which = 0; which < 4; ++which) side(which);
        }
        tris.clear();
        for (auto& f : found) tris.insert(tris.end(), f.begin(), f.end());
        tris.insert(tris.end(), skirt.begin(), skirt.end());
        if (tris.empty()) return false;
        // The points: each pixel a corner uses, once; a twin, after them.
        at.assign(n, -1);
        verts.clear();
        for (std::uint32_t& p : tris) {
            if (p < n) {
                if (at[p] < 0) {
                    at[p] = (long long)verts.size();
                    Vertex v;
                    v.pixel = p, v.x = float(p % W) + 0.5f, v.y = float(p / W) + 0.5f;
                    verts.push_back(v);
                }
                p = std::uint32_t(at[p]);
            }
        }
        const size_t firstTwin = verts.size();
        for (const Twin& t : twins) {
            Vertex v;
            v.pixel = t.pixel, v.x = t.x, v.y = t.y, v.twin = true;
            verts.push_back(v);
        }
        for (std::uint32_t& p : tris)
            if (p >= n && p != std::uint32_t(-1)) p = std::uint32_t(firstTwin + (p - n));
        // Each point's colour: the picture around it over its own surface, as far as its cell reaches (a coarse cell's
        // corner half that cell, a fine one's a pixel or two), the nearer pixels counting more; a twin, its border pixel's.
        parallel(threads, (firstTwin + 255) / 256, [&](size_t chunk) {
            for (size_t v = chunk * 256; v < std::min(firstTwin, (chunk + 1) * 256); ++v) shade(verts[v]);
        });
        for (size_t v = firstTwin; v < verts.size(); ++v) {
            const long long b = at[verts[v].pixel];
            if (b >= 0) {
                const Vertex& from = verts[size_t(b)];
                std::copy_n(from.c, 3, verts[v].c);
                verts[v].depth = from.depth, verts[v].sky = from.sky;
            } else {
                Vertex tmp;
                tmp.pixel = verts[v].pixel;
                shade(tmp);
                std::copy_n(tmp.c, 3, verts[v].c);
                verts[v].depth = tmp.depth, verts[v].sky = tmp.sky;
            }
        }
        vertexCount = verts.size(), triangleCount = tris.size() / 3;
        buildSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
        ok = true;
        return true;
    }

    // The mesh drawn into `nv` (the same picture size): a pixel's colour (rgb), lifted depth (-1 none, 0 the environment),
    // depth (0 the environment), the picture's pixel its outputs come from, and whether a triangle drew it (1) or the
    // fill did (2). False where nothing of the mesh is seen.
    bool warp(const View& nv, std::vector<float>& outColor, std::vector<double>& outW, std::vector<float>& outDepth,
              std::vector<long long>& outFrom, std::vector<uint8_t>& outState) {
        const auto began = std::chrono::steady_clock::now();
        if (!ok || nv.kind == View::Directional) return false;
        const size_t n = size_t(W) * H;
        const unsigned threads = std::max(1u, op.threads);
        // The points moved: a surface's by its depth, the environment's as directions (a point far past the scene).
        proj.resize(verts.size());
        const double away = far * 1e6;
        parallel(threads, (verts.size() + 255) / 256, [&](size_t chunk) {
            for (size_t v = chunk * 256; v < std::min(verts.size(), (chunk + 1) * 256); ++v) {
                const Vertex& q = verts[v];
                Moved& m = proj[v];
                m.seen = false;
                surface::V3 p;
                if (!src.pointAt(double(q.x), double(q.y), q.sky ? away : double(q.depth), p)) continue;
                double px, py, ww;
                if (!nv.lift(p, px, py, ww)) continue;
                if (!std::isfinite(px) || !std::isfinite(py) || std::fabs(px) > 1e7 || std::fabs(py) > 1e7) continue;
                if (q.sky) ww = 0;
                else if (!(ww > 0)) continue;
                m.x = px, m.y = py, m.w = ww, m.seen = true;
            }
        });
        outColor.assign(n * 3, 0.0f), outW.assign(n, -1.0), outDepth.assign(n, 0.0f), outFrom.assign(n, -1), outState.assign(n, 0);
        // The triangles into bands of rows (each band drawn by one thread, nearest first), each where its rows are.
        const unsigned bands = std::max(1u, std::min(H, threads * 8));
        const unsigned bandRows = (H + bands - 1) / bands;
        bandStart.assign(bands + 1, 0);
        const size_t T = tris.size() / 3;
        span.resize(T);
        for (size_t t = 0; t < T; ++t) {
            const Moved &a = proj[tris[t * 3]], &b = proj[tris[t * 3 + 1]], &c = proj[tris[t * 3 + 2]];
            span[t] = {1, 0};
            if (!a.seen || !b.seen || !c.seen) continue;
            const double lo = std::min({a.y, b.y, c.y}), hi = std::max({a.y, b.y, c.y});
            const long long r0 = std::max(0LL, (long long)std::ceil(lo - 0.5)), r1 = std::min((long long)H - 1, (long long)std::floor(hi - 0.5));
            if (r0 > r1) continue;
            span[t] = {unsigned(r0 / bandRows), unsigned(r1 / bandRows)};
            for (unsigned k = span[t].first; k <= span[t].second; ++k) ++bandStart[k + 1];
        }
        for (unsigned k = 0; k < bands; ++k) bandStart[k + 1] += bandStart[k];
        bandTris.resize(bandStart[bands]);
        {
            std::vector<size_t> fill(bandStart.begin(), bandStart.end() - 1);
            for (size_t t = 0; t < T; ++t)
                if (span[t].first <= span[t].second)
                    for (unsigned k = span[t].first; k <= span[t].second; ++k) bandTris[fill[k]++] = std::uint32_t(t);
        }
        const bool ortho = nv.kind == View::Orthographic;
        const double K = nv.depthScale();
        parallel(threads, bands, [&](size_t band) {
            const long long rowLo = (long long)band * bandRows, rowHi = std::min((long long)H, rowLo + bandRows) - 1;
            for (size_t e = bandStart[band]; e < bandStart[band + 1]; ++e) {
                const size_t t = bandTris[e];
                const std::uint32_t ia = tris[t * 3], ib = tris[t * 3 + 1], ic = tris[t * 3 + 2];
                const Moved &a = proj[ia], &b = proj[ib], &c = proj[ic];
                const double e1x = b.x - a.x, e1y = b.y - a.y, e2x = c.x - a.x, e2y = c.y - a.y;
                const double area = e1x * e2y - e2x * e1y;
                if (!(std::fabs(area) > 1e-12)) continue;
                const double inv = 1.0 / area;
                const long long y0 = std::max(rowLo, (long long)std::ceil(std::min({a.y, b.y, c.y}) - 0.5));
                const long long y1 = std::min(rowHi, (long long)std::floor(std::max({a.y, b.y, c.y}) - 0.5));
                const long long x0 = std::max(0LL, (long long)std::ceil(std::min({a.x, b.x, c.x}) - 0.5));
                const long long x1 = std::min((long long)W - 1, (long long)std::floor(std::max({a.x, b.x, c.x}) - 0.5));
                const Vertex &va = verts[ia], &vb = verts[ib], &vc = verts[ic];
                const bool sky = va.sky;
                for (long long y = y0; y <= y1; ++y) {
                    const double py = double(y) + 0.5 - a.y;
                    for (long long x = x0; x <= x1; ++x) {
                        const double px = double(x) + 0.5 - a.x;
                        const double l1 = (px * e2y - e2x * py) * inv, l2 = (e1x * py - px * e1y) * inv, l0 = 1.0 - l1 - l2;
                        if (l0 < -1e-7 || l1 < -1e-7 || l2 < -1e-7) continue;
                        const double ww = sky ? 0.0 : l0 * a.w + l1 * b.w + l2 * c.w;
                        const size_t i = size_t(y) * W + size_t(x);
                        if (ww <= outW[i]) continue;
                        outW[i] = ww;
                        for (int k = 0; k < 3; ++k) outColor[i * 3 + k] = float(l0 * va.c[k] + l1 * vb.c[k] + l2 * vc.c[k]);
                        const Vertex& near = l0 >= l1 && l0 >= l2 ? va : (l1 >= l2 ? vb : vc);
                        outFrom[i] = (long long)near.pixel;
                        outState[i] = 1;
                        outDepth[i] = sky ? 0.0f : float(ortho ? K * (1.0 - ww) : 1.0 / ww);
                    }
                }
            }
        });
        size_t drawn = 0;
        for (size_t i = 0; i < n; ++i) drawn += outState[i] != 0;
        drawnShare = n ? double(drawn) / double(n) : 0;
        if (!drawn) return false;
        if (drawn < n) {
            close(outColor, outW, outDepth, outFrom, outState, ortho, K);
            fill(outColor, outW, outDepth, outFrom, outState, ortho, K);
        }
        warpSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
        return true;
    }

private:
    struct Vertex {
        std::uint32_t pixel = 0;  // the picture's pixel (a twin's: its border pixel)
        float x = 0, y = 0;       // where it is in the picture (raster, a pixel's centre at +0.5; a twin's past the edge)
        float c[3] = {};
        float depth = 0;
        bool sky = false, twin = false;
    };
    struct Twin {
        std::uint32_t pixel;
        float x, y;
    };
    struct Moved {
        double x = 0, y = 0, w = 0;
        bool seen = false;
    };
    struct Level {
        unsigned w = 0, h = 0;
        std::vector<float> c;
        std::vector<double> lw;
        std::vector<long long> from;
        std::vector<uint8_t> ok;
    };
    bool ok = false;
    View src;
    unsigned W = 0, H = 0;
    double far = 1;
    std::vector<uint8_t> kind, eh, ev, empty, mixed;
    std::vector<double> lw;
    std::vector<float> color;
    std::vector<int> seh, sev, sempty;
    std::vector<std::uint32_t> tris;
    std::vector<long long> at;
    std::vector<Vertex> verts;
    std::vector<Twin> twins;
    std::vector<Moved> proj;
    std::vector<std::pair<unsigned, unsigned>> span;
    std::vector<size_t> bandStart;
    std::vector<std::uint32_t> bandTris;
    std::vector<Level> levels;
    std::vector<uint8_t> closeState;

    void sumOf(const std::vector<uint8_t>& v, std::vector<int>& s) const {
        const size_t sw = size_t(W) + 1;
        s.assign(sw * (size_t(H) + 1), 0);
        for (size_t y = 0; y < H; ++y) {
            int run = 0;
            const int* above = &s[y * sw];
            int* row = &s[(y + 1) * sw];
            for (size_t x = 0; x < W; ++x) {
                run += v[y * W + x];
                row[x + 1] = above[x + 1] + run;
            }
        }
    }
    // The sum over pixels [x0, x1] x [y0, y1] (empty where x1 < x0 or y1 < y0).
    int rect(const std::vector<int>& s, long long x0, long long y0, long long x1, long long y1) const {
        if (x1 < x0 || y1 < y0) return 0;
        const size_t sw = size_t(W) + 1;
        return s[size_t(y1 + 1) * sw + size_t(x1 + 1)] - s[size_t(y0) * sw + size_t(x1 + 1)] - s[size_t(y1 + 1) * sw + size_t(x0)] +
               s[size_t(y0) * sw + size_t(x0)];
    }
    // A cell of size s at (x0, y0): its corners (x0, y0) to (x0 + s, y0 + s), clipped to the picture.
    void cell(unsigned x0, unsigned y0, unsigned s, std::vector<std::uint32_t>& out) const {
        const unsigned x1 = std::min(x0 + s, W - 1), y1 = std::min(y0 + s, H - 1);
        if (x1 <= x0 || y1 <= y0) return;
        const long long area = (long long)(x1 - x0 + 1) * (y1 - y0 + 1);
        if (rect(sempty, x0, y0, x1, y1) == area) return;
        if (rect(seh, x0, y0, (long long)x1 - 1, y1) == 0 && rect(sev, x0, y0, x1, (long long)y1 - 1) == 0) {
            const std::uint32_t a = y0 * W + x0, b = y0 * W + x1, c = y1 * W + x0, d = y1 * W + x1;
            out.insert(out.end(), {a, b, d, a, d, c});
            return;
        }
        if (s == 1) {
            // Four pixels: the triangles whose sides no jump crosses, of the split (one diagonal or the other) that keeps more.
            const std::uint32_t a = y0 * W + x0, b = a + 1, c = a + W, d = c + 1;
            const bool ab = !eh[a], cd = !eh[c], ac = !ev[a], bd = !ev[b];
            const bool t1 = ab && bd, t2 = ac && cd, t3 = ab && ac, t4 = bd && cd;
            if (int(t1) + int(t2) >= int(t3) + int(t4)) {
                if (t1) out.insert(out.end(), {a, b, d});
                if (t2) out.insert(out.end(), {a, d, c});
            } else {
                if (t3) out.insert(out.end(), {a, b, c});
                if (t4) out.insert(out.end(), {b, d, c});
            }
            return;
        }
        const unsigned h = s / 2;
        cell(x0, y0, h, out), cell(x0 + h, y0, h, out), cell(x0, y0 + h, h, out), cell(x0 + h, y0 + h, h, out);
    }
    // A skirt's segment along one edge (which: 0 left, 1 right, 2 top, 3 bottom) from s0 to s1: smooth (one kind, no
    // jump, nothing empty), a quad out to M pixels past the edge; else halved, down to a pixel's step.
    void segment(int which, unsigned s0, unsigned s1, unsigned s, unsigned M, std::vector<std::uint32_t>& out) {
        if (s1 <= s0) return;
        const bool vertical = which < 2;
        const unsigned fixed = which == 0 ? 0 : which == 1 ? W - 1 : which == 2 ? 0 : H - 1;
        auto pixelAt = [&](unsigned along) -> std::uint32_t { return vertical ? along * W + fixed : fixed * W + along; };
        const long long ex0 = vertical ? fixed : s0, ey0 = vertical ? s0 : fixed, ex1 = vertical ? fixed : s1, ey1 = vertical ? s1 : fixed;
        const bool emptyHere = rect(sempty, ex0, ey0, ex1, ey1) > 0;
        const bool jumps = vertical ? rect(sev, fixed, s0, fixed, (long long)s1 - 1) > 0 : rect(seh, s0, fixed, (long long)s1 - 1, fixed) > 0;
        if (emptyHere || jumps) {
            if (s <= 1) return;
            const unsigned h = s / 2;
            segment(which, s0, std::min(s0 + h, s1), h, M, out);
            segment(which, s0 + h, s1, h, M, out);
            return;
        }
        const std::uint32_t a = pixelAt(s0), b = pixelAt(s1);
        const size_t n = size_t(W) * H;
        auto twinOf = [&](std::uint32_t p, unsigned along) -> std::uint32_t {
            const float c = float(along) + 0.5f;
            Twin t{p, 0, 0};
            if (which == 0) t.x = -float(M) + 0.5f, t.y = c;
            else if (which == 1) t.x = float(W - 1 + M) + 0.5f, t.y = c;
            else if (which == 2) t.x = c, t.y = -float(M) + 0.5f;
            else t.x = c, t.y = float(H - 1 + M) + 0.5f;
            twins.push_back(t);
            return std::uint32_t(n + twins.size() - 1);
        };
        const std::uint32_t ta = twinOf(a, s0), tb = twinOf(b, s1);
        out.insert(out.end(), {a, b, tb, a, tb, ta});
    }
    // A point's colour: its surface's pixels around it (the environment's, if it is the environment's), as far as the
    // coarsest cell it is a corner of reaches, tent-weighted, a neighbour off the point's plane by soft to jump less and
    // less, past jump not at all; a mixed pixel (a silhouette's) counts for no point but its own.
    void shade(Vertex& v) const {
        const size_t i = v.pixel;
        const unsigned x = unsigned(i % W), y = unsigned(i / W);
        unsigned p = cellSize;
        while (p > 1 && ((x % p) || (y % p))) p >>= 1;
        const uint8_t kv = kind[i];
        const bool mv = mixed[i] != 0;
        const int r = mv ? 0 : std::max(1, int(p / 2));
        v.sky = kv == 2;
        v.depth = 0.0f;
        const double wv = lw[i];
        double gx = 0, gy = 0;
        if (kv == 1) {
            v.depth = float(src.kind == View::Orthographic ? src.depthScale() * (1.0 - wv) : 1.0 / wv);
            const bool left = x > 0 && !eh[i - 1], right = x + 1 < W && !eh[i];
            const bool up = y > 0 && !ev[i - W], down = y + 1 < H && !ev[i];
            gx = left && right ? (lw[i + 1] - lw[i - 1]) / 2 : right ? lw[i + 1] - wv : left ? wv - lw[i - 1] : 0.0;
            gy = up && down ? (lw[i + W] - lw[i - W]) / 2 : down ? lw[i + W] - wv : up ? wv - lw[i - W] : 0.0;
        }
        double sum[3] = {}, weight = 0;
        const int yl = std::max(0, int(y) - r), yh = std::min(int(H) - 1, int(y) + r);
        const int xl = std::max(0, int(x) - r), xh = std::min(int(W) - 1, int(x) + r);
        for (int yy = yl; yy <= yh; ++yy)
            for (int xx = xl; xx <= xh; ++xx) {
                const size_t j = size_t(yy) * W + size_t(xx);
                if (kind[j] != kv || (j != i && mixed[j])) continue;
                const int dx = xx - int(x), dy = yy - int(y);
                double a = double(r + 1 - std::abs(dx)) * double(r + 1 - std::abs(dy));
                if (kv == 1) {
                    const double off = std::fabs(lw[j] - (wv + gx * dx + gy * dy)) / wv;
                    if (off >= op.jump) continue;
                    if (off > op.soft) {
                        const double t = (off - op.soft) / std::max(1e-12, op.jump - op.soft);
                        a *= 1.0 - t * t * (3.0 - 2.0 * t);
                    }
                }
                for (int k = 0; k < 3; ++k) sum[k] += a * color[j * 3 + k];
                weight += a;
            }
        for (int k = 0; k < 3; ++k) v.c[k] = weight > 0 ? float(sum[k] / weight) : (i < color.size() / 3 ? color[i * 3 + k] : 0.0f);
    }
    // Cracks (a pixel no triangle drew between two of one surface, left and right or above and below: where cells of two
    // sizes meet, or a magnified surface's seam), closed from those two.
    void close(std::vector<float>& c0, std::vector<double>& w0, std::vector<float>& d0, std::vector<long long>& f0, std::vector<uint8_t>& s0,
               bool ortho, double K) {
        const unsigned threads = std::max(1u, op.threads);
        closeState = s0;
        parallel(threads, H, [&](size_t y) {
            for (unsigned x = 0; x < W; ++x) {
                const size_t i = y * W + x;
                if (closeState[i]) continue;
                long long a = -1, b = -1;
                auto same = [&](size_t p, size_t q) {
                    if (closeState[p] != 1 || closeState[q] != 1) return false;
                    const double wp = w0[p], wq = w0[q];
                    if (wp == 0 || wq == 0) return wp == wq;
                    return std::fabs(wp - wq) <= 2 * op.jump * std::max(wp, wq);
                };
                if (x > 0 && x + 1 < W && same(i - 1, i + 1)) a = (long long)(i - 1), b = (long long)(i + 1);
                else if (y > 0 && y + 1 < H && same(i - W, i + W)) a = (long long)(i - W), b = (long long)(i + W);
                if (a < 0) continue;
                for (int k = 0; k < 3; ++k) c0[i * 3 + k] = 0.5f * (c0[size_t(a) * 3 + k] + c0[size_t(b) * 3 + k]);
                w0[i] = 0.5 * (w0[size_t(a)] + w0[size_t(b)]);
                f0[i] = f0[size_t(a)];
                d0[i] = w0[i] > 0 ? float(ortho ? K * (1.0 - w0[i]) : 1.0 / w0[i]) : 0.0f;
                s0[i] = 2;
            }
        });
    }
    // The pixels still empty: from the farthest around them, coarse to fine. Each coarser level keeps, of its four
    // pixels, the farthest's lifted depth and outputs and the mean colour of those as far (within a sixth); then, finest
    // last, a pixel still empty takes the coarser level's colour, bilinearly over those of its four nearest that are as
    // far as the farthest of them (no blend of a surface into what lay behind it), and that one's depth and outputs.
    void fill(std::vector<float>& c0, std::vector<double>& w0, std::vector<float>& d0, std::vector<long long>& f0, std::vector<uint8_t>& s0,
              bool ortho, double K) {
        const unsigned threads = std::max(1u, op.threads);
        unsigned lwid = W, lhei = H;
        size_t count = 0;
        while (lwid > 1 || lhei > 1) lwid = (lwid + 1) / 2, lhei = (lhei + 1) / 2, ++count;
        if (levels.size() < count + 1) levels.resize(count + 1);
        // Level 0 is the picture's own (its arrays read in place).
        auto okAt = [&](size_t k, size_t i) -> bool { return k == 0 ? s0[i] != 0 : levels[k].ok[i] != 0; };
        auto wAt = [&](size_t k, size_t i) -> double { return k == 0 ? w0[i] : levels[k].lw[i]; };
        auto cAt = [&](size_t k, size_t i) -> const float* { return k == 0 ? &c0[i * 3] : &levels[k].c[i * 3]; };
        auto fAt = [&](size_t k, size_t i) -> long long { return k == 0 ? f0[i] : levels[k].from[i]; };
        levels[0].w = W, levels[0].h = H;
        for (size_t k = 1; k <= count; ++k) {
            Level& L = levels[k];
            const unsigned pw = levels[k - 1].w, ph = levels[k - 1].h;
            L.w = (pw + 1) / 2, L.h = (ph + 1) / 2;
            const size_t m = size_t(L.w) * L.h;
            L.c.assign(m * 3, 0.0f), L.lw.assign(m, -1.0), L.from.assign(m, -1), L.ok.assign(m, 0);
            parallel(threads, L.h, [&](size_t y) {
                for (unsigned x = 0; x < L.w; ++x) {
                    double wmin = 1e300;
                    long long fmin = -1;
                    size_t kids[4];
                    int nk = 0;
                    for (unsigned dy = 0; dy < 2; ++dy)
                        for (unsigned dx = 0; dx < 2; ++dx) {
                            const unsigned cx = 2 * x + dx, cy = unsigned(2 * y + dy);
                            if (cx >= pw || cy >= ph) continue;
                            const size_t j = size_t(cy) * pw + cx;
                            if (!okAt(k - 1, j)) continue;
                            kids[nk++] = j;
                            if (wAt(k - 1, j) < wmin) wmin = wAt(k - 1, j), fmin = fAt(k - 1, j);
                        }
                    if (!nk) continue;
                    const size_t i = size_t(y) * L.w + x;
                    double sum[3] = {};
                    int used = 0;
                    for (int q = 0; q < nk; ++q) {
                        if (wAt(k - 1, kids[q]) > wmin + wmin / 6.0 + 1e-12) continue;
                        const float* c = cAt(k - 1, kids[q]);
                        for (int ch = 0; ch < 3; ++ch) sum[ch] += c[ch];
                        ++used;
                    }
                    for (int ch = 0; ch < 3; ++ch) L.c[i * 3 + ch] = float(sum[ch] / used);
                    L.lw[i] = wmin, L.from[i] = fmin, L.ok[i] = 1;
                }
            });
        }
        if (!levels[count].ok[0]) return;
        for (size_t k = count; k-- > 0;) {
            const Level& P = levels[k + 1];
            const unsigned lw2 = levels[k].w, lh2 = levels[k].h;
            parallel(threads, lh2, [&](size_t y) {
                for (unsigned x = 0; x < lw2; ++x) {
                    const size_t i = size_t(y) * lw2 + x;
                    if (okAt(k, i)) continue;
                    // The coarser level at this pixel's centre: its four nearest (all filled by now), bilinearly, over those
                    // as far as the farthest of them.
                    const double u = (x + 0.5) / 2.0 - 0.5, v = (double(y) + 0.5) / 2.0 - 0.5;
                    const int ux = std::clamp(int(std::floor(u)), 0, int(P.w) - 1), vy = std::clamp(int(std::floor(v)), 0, int(P.h) - 1);
                    const int ux1 = std::min(ux + 1, int(P.w) - 1), vy1 = std::min(vy + 1, int(P.h) - 1);
                    const double fx = std::clamp(u - ux, 0.0, 1.0), fy = std::clamp(v - vy, 0.0, 1.0);
                    const size_t q[4] = {size_t(vy) * P.w + ux, size_t(vy) * P.w + ux1, size_t(vy1) * P.w + ux, size_t(vy1) * P.w + ux1};
                    const double bw[4] = {(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy};
                    double wmin = 1e300;
                    int farthest = 0;
                    for (int j = 0; j < 4; ++j)
                        if (P.lw[q[j]] < wmin) wmin = P.lw[q[j]], farthest = j;
                    double c[3] = {}, total = 0;
                    for (int j = 0; j < 4; ++j) {
                        if (P.lw[q[j]] > wmin + wmin / 6.0 + 1e-12) continue;
                        const double t = bw[j] + 1e-6;
                        for (int ch = 0; ch < 3; ++ch) c[ch] += t * P.c[q[j] * 3 + ch];
                        total += t;
                    }
                    const size_t parent = q[farthest];
                    if (k == 0) {
                        for (int ch = 0; ch < 3; ++ch) c0[i * 3 + ch] = float(c[ch] / total);
                        w0[i] = P.lw[parent], f0[i] = P.from[parent], s0[i] = 2;
                        d0[i] = P.lw[parent] > 0 ? float(ortho ? K * (1.0 - P.lw[parent]) : 1.0 / P.lw[parent]) : 0.0f;
                    } else {
                        Level& L = levels[k];
                        for (int ch = 0; ch < 3; ++ch) L.c[i * 3 + ch] = float(c[ch] / total);
                        L.lw[i] = P.lw[parent], L.from[i] = P.from[parent], L.ok[i] = 1;
                    }
                }
            });
        }
    }
};

}  // namespace rhea
