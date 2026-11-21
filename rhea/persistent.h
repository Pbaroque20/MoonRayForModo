// Persistent probes (rhea/DESIGN.md 18): probes that live in world space from frame to frame, the frame's Bregman Delaunay
// triangulation over wherever they land, and the GPU's own camera rays verifying the reconstruction.
//
// A probe is a point on a triangle of a plan mesh with its light summed over the frames it was sampled in. Each frame:
//   - prepare (CPU, before the frame): the probes are lifted onto the new frame and kept where a camera ray at their
//     raster point still meets their triangle; new probes go only where the last frame asked for them (its
//     verification failed in a cell, or a cell holds no probe and was not sky); the frame's probes are triangulated
//     (Delaunator, then Bregman flips) and where a triangle's sandwich gap passes the tolerance a probe is added at its
//     centre and the triangulation made again, a few passes;
//   - absorb (after the frame): each probe takes its pixel's light where every sample of the pixel met its surface (its
//     tangent plane holds the pixel's depths), its sums faded first when the camera has moved (view-dependent light
//     then follows);
//   - reconstruct: each pixel's light interpolated over its triangle (divided by the corners' colours and multiplied by
//     the pixel's own where they have one), its inverse depth the triangle's plane;
//   - verify: the frame's nearest and farthest first-hit depths at the pixel (the depth output, min and max) within the
//     tolerance of the plane over the pixel's footprint, or no hit where no triangle is. A pixel that fails takes no
//     phase 1 this frame and asks for a probe in its cell for the next.
// The radial scans and the CPU's exactness tests (coverage, creases, what lies in front) have no part here: what each
// pixel sees is what the GPU's samples meet.
#pragma once
#include "delaunay.h"
#include "view.h"
#include "virtual_surface.h"

namespace rhea {

struct WorldProbe {
    uint32_t geom = ~0u, prim = 0;
    float u = 0, v = 0;  // the hit's barycentrics on its triangle
    surface::V3 P{};     // the point (trace space)
    double sum[3] = {0, 0, 0}, sumAlbedo[3] = {0, 0, 0}, weight = 0;  // light and colour times samples, faded on moves
    unsigned born = 0, seen = 0;
    double lx = 0, ly = 0;  // where it was last seen in the picture (where a directional camera's lift starts looking)
    bool placed = false;
};

struct FieldOptions {
    unsigned cell = 8;       // the screen's cells: at most one new probe a cell a frame where one is asked for
    double spacing = 2;      // no new probe nearer than this (pixels) to another
    unsigned gapPasses = 2;  // sandwich-gap refinement passes a frame
    double tol = 0.002;      // the geometric tolerance (relative inverse depth)
    // The surface's own plane (DESIGN.md 23): a triangle's geometric fit judged along its surface's normal, so that the
    // sandwich gap's tolerance in the lifted depth is tol / cos of the surface's angle to the camera (at most 20 times:
    // cos 0.05), and its light interpolated over the surface (each corner weighted by its w) rather than linearly over
    // the picture, which perspective skews on a slanted surface.
    bool slant = true, planeLight = true;
    double footprint = 0.5;  // the pixel filter's reach about a pixel's centre (pixels), for the verification
    double tauR = 0.25;      // the radiance-edge rule (bvd: the corners' light spread over their mean)
    float demodFloor = 0.02f;
    bool demod = true;
    unsigned threads = 12;
    // At most this many probes a cell before a failed verification asks for another: where the frame's samples meet
    // more than one surface whatever the probes (out of focus, moving, an edge), more probes do not help.
    unsigned maxPerCell = 4;
};

enum FieldState : uint8_t { FieldNone = 0, FieldTrusted = 1, FieldGap = 2, FieldEdge = 3 };

// One frame's view of the field.
struct FieldFrame {
    View view;  // the camera (view.h)
    unsigned index = 0;
    std::vector<int> ids;          // the field's probes in the frame
    std::vector<double> xy, w;     // their raster points and inverse depths
    std::vector<Plane> h;          // their tangent planes
    std::vector<double> facing;    // how squarely their surfaces face the camera (View::facing)
    std::vector<D3> normal;        // their surfaces' unit normals (trace space), turned to face the camera (planes.h)
    std::vector<int> pixel;        // their pixels
    std::vector<uint8_t> fresh;    // new this frame
    std::vector<int> tris;         // triangles, three indices into ids
    std::vector<uint8_t> triGap;   // a triangle's sandwich gap past the tolerance
    std::vector<Plane> triPlane;   // a triangle's plane (its interpolation)
    std::vector<int> triOf;        // each pixel's triangle, -1 none
    size_t candidates = 0, visible = 0, spawned = 0, gapSpawned = 0, flips = 0;
    double seconds = 0;
};

class ProbeField {
public:
    std::vector<WorldProbe> probes;
    unsigned width = 0, height = 0, cellsX = 0, cellsY = 0;
    std::vector<uint8_t> need;  // cells the last verification asked a probe for
    std::vector<uint8_t> sky;   // cells the last frame met nothing in
    size_t mixed = 0;           // the last absorb's probes whose pixel met more than their surface (they took nothing)

    void prepare(const cpu::Plan& plan, const async::CpuScene& scene, const FieldOptions& op, unsigned frameIndex, FieldFrame& f) {
        const auto began = std::chrono::steady_clock::now();
        if (!width) {
            width = plan.width, height = plan.height;
            cellsX = (width + op.cell - 1) / op.cell, cellsY = (height + op.cell - 1) / op.cell;
            need.assign(size_t(cellsX) * cellsY, 0);
            sky.assign(size_t(cellsX) * cellsY, 0);
        }
        f = FieldFrame{};
        f.index = frameIndex;
        cpu::need(f.view.init(plan.camera, plan.width, plan.height), "Camera view");
        if (f.view.needsDepthScale()) f.view.setDepthScale(depthScale(plan, f.view));
        // The known probes lifted onto the frame, kept where a camera ray still meets their triangle.
        std::vector<int> cand;
        std::vector<double> cx, cy, cw;
        for (int i = 0; i < int(probes.size()); ++i) {
            double x = probes[i].lx, y = probes[i].ly, w;
            if (!f.view.lift(probes[i].P, x, y, w, probes[i].placed)) continue;
            if (x < 0 || y < 0 || x >= width || y >= height) continue;
            cand.push_back(i), cx.push_back(x), cy.push_back(y), cw.push_back(w);
        }
        f.candidates = cand.size();
        std::vector<uint8_t> seen(cand.size(), 0);
        parallel(op.threads, cand.size(), [&](size_t k) {
            surface::Ray ray;
            if (!f.view.ray(cx[k], cy[k], ray)) return;
            ray.mask = 1u;
            async::CpuBackend backend{scene};
            const resume::Hit hit = backend.trace(ray);
            const WorldProbe& p = probes[cand[k]];
            seen[k] = hit.geom == p.geom && hit.prim == p.prim;
        });
        // A grid of the frame's probes by pixel, for the spacing of new ones.
        std::vector<std::vector<int>> grid(size_t(cellsX) * cellsY);
        auto add = [&](int id, double x, double y, double w, bool isFresh) {
            WorldProbe& p = probes[id];
            p.lx = x, p.ly = y, p.placed = true;
            const cpu::Mesh& e = plan.meshes[p.geom];
            const Plane h = f.view.tangent(e, *e.data, p.prim, p.P, x, y);
            const int px = std::min(int(width) - 1, std::max(0, int(x))), py = std::min(int(height) - 1, std::max(0, int(y)));
            f.ids.push_back(id), f.xy.push_back(x), f.xy.push_back(y), f.w.push_back(w), f.h.push_back(h);
            {
                const auto& tr = e.data->triangles[p.prim];
                const surface::V3 a = vertexOf(e, *e.data, tr.a), b = vertexOf(e, *e.data, tr.b), c = vertexOf(e, *e.data, tr.c);
                const double ux = b.x - a.x, uy = b.y - a.y, uz = b.z - a.z, vx = c.x - a.x, vy = c.y - a.y, vz = c.z - a.z;
                const D3 n{uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx};
                f.facing.push_back(f.view.facing(n, p.P));
                f.normal.push_back(f.view.toward(n, p.P));
            }
            f.pixel.push_back(py * int(width) + px), f.fresh.push_back(isFresh || p.weight <= 0);
            grid[size_t(py / op.cell) * cellsX + px / op.cell].push_back(int(f.ids.size()) - 1);
        };
        for (size_t k = 0; k < cand.size(); ++k)
            if (seen[k]) {
                add(cand[k], cx[k], cy[k], cw[k], false);
                probes[cand[k]].seen = frameIndex;
            }
        f.visible = f.ids.size();
        auto near = [&](double x, double y) {
            const int gx = int(x) / int(op.cell), gy = int(y) / int(op.cell);
            for (int dy = -1; dy <= 1; ++dy)
                for (int dx = -1; dx <= 1; ++dx) {
                    const int qx = gx + dx, qy = gy + dy;
                    if (qx < 0 || qy < 0 || qx >= int(cellsX) || qy >= int(cellsY)) continue;
                    for (int j : grid[size_t(qy) * cellsX + qx]) {
                        const double ddx = f.xy[2 * j] - x, ddy = f.xy[2 * j + 1] - y;
                        if (ddx * ddx + ddy * ddy < op.spacing * op.spacing) return true;
                    }
                }
            return false;
        };
        // New probes at these raster points (pixel centres): traced, kept where they meet a mesh's triangle.
        auto spawn = [&](const std::vector<std::pair<int, int>>& at, size_t& count) {
            std::vector<resume::Hit> hits(at.size());
            std::vector<surface::Ray> rays(at.size());
            parallel(op.threads, at.size(), [&](size_t k) {
                surface::Ray ray;
                hits[k].geom = ~0u;
                if (!f.view.ray(at[k].first + 0.5, at[k].second + 0.5, ray)) return;
                ray.mask = 1u;
                async::CpuBackend backend{scene};
                hits[k] = backend.trace(ray);
                rays[k] = ray;
            });
            for (size_t k = 0; k < at.size(); ++k) {
                const resume::Hit& hit = hits[k];
                const size_t cell = size_t(at[k].second / op.cell) * cellsX + at[k].first / op.cell;
                if (hit.geom == ~0u) {
                    sky[cell] = 1;
                    continue;
                }
                const auto& m = *plan.meshes[hit.geom].data;
                if (m.points || m.curveBasis || m.triangles.empty()) continue;  // not a triangle: no probe
                WorldProbe p;
                p.geom = hit.geom, p.prim = hit.prim, p.u = hit.u, p.v = hit.v;
                const surface::Ray& r = rays[k];
                p.P = {r.origin.x + hit.t * r.direction.x, r.origin.y + hit.t * r.direction.y, r.origin.z + hit.t * r.direction.z};
                p.born = p.seen = frameIndex;
                double x = at[k].first + 0.5, y = at[k].second + 0.5, w;
                if (!f.view.lift(p.P, x, y, w, true)) continue;
                probes.push_back(p);
                add(int(probes.size()) - 1, x, y, w, true);
                ++count;
            }
        };
        {
            std::vector<std::pair<int, int>> at;
            for (unsigned cyi = 0; cyi < cellsY; ++cyi)
                for (unsigned cxi = 0; cxi < cellsX; ++cxi) {
                    const size_t cell = size_t(cyi) * cellsX + cxi;
                    const bool empty = grid[cell].empty();
                    if (!need[cell] && !(empty && !sky[cell])) continue;
                    if (!empty && grid[cell].size() >= op.maxPerCell) continue;
                    // A pixel of the cell, jittered by the frame: the cell's centre region.
                    const uint32_t hsh = hash(uint32_t(cell) * 0x9e3779b9u ^ frameIndex * 0x85ebca6bu);
                    const int x0 = int(cxi * op.cell), y0 = int(cyi * op.cell);
                    const int x1 = std::min(int(width), x0 + int(op.cell)), y1 = std::min(int(height), y0 + int(op.cell));
                    const int px = x0 + int(hsh % uint32_t(x1 - x0)), py = y0 + int((hsh >> 16) % uint32_t(y1 - y0));
                    if (near(px + 0.5, py + 0.5)) continue;
                    at.push_back({px, py});
                }
            spawn(at, f.spawned);
        }
        // Triangulate; where a triangle's sandwich gap passes the tolerance, a probe at its centre, and again.
        for (unsigned pass = 0;; ++pass) {
            triangulate(op, f);
            if (pass >= op.gapPasses) break;
            std::vector<std::pair<int, int>> at;
            for (size_t t = 0; t < f.triGap.size(); ++t) {
                if (!f.triGap[t]) continue;
                const int a = f.tris[3 * t], b = f.tris[3 * t + 1], c = f.tris[3 * t + 2];
                const double x = (f.xy[2 * a] + f.xy[2 * b] + f.xy[2 * c]) / 3, y = (f.xy[2 * a + 1] + f.xy[2 * b + 1] + f.xy[2 * c + 1]) / 3;
                if (near(x, y)) continue;
                at.push_back({int(x), int(y)});
            }
            if (at.empty()) break;
            spawn(at, f.gapSpawned);
        }
        f.seconds = secondsSince(began);
    }

    // A plane holds a pixel's samples: their nearest and farthest first-hit depths (depthMin, depthMax) lie within the
    // plane's inverse depths over the pixel's footprint, widened by the tolerance.
    static bool planeHolds(const View& view, const Plane& pl, unsigned x, unsigned y, float depthMin, float depthMax, const FieldOptions& op) {
        if (!(std::isfinite(depthMin) && depthMin > 0) || !pl.ok) return false;
        double lo = 1e300, hi = -1e300;
        for (int k = 0; k < 4; ++k) {
            const double v = pl.at(x + 0.5 + ((k & 1) ? op.footprint : -op.footprint), y + 0.5 + ((k & 2) ? op.footprint : -op.footprint));
            lo = std::min(lo, v), hi = std::max(hi, v);
        }
        const double wNear = view.wOf(depthMin), wFar = view.wOf(std::max(depthMax, depthMin));
        return wFar >= lo * (1 - op.tol) && wNear <= hi * (1 + op.tol);
    }

    // Each probe in the frame takes its pixel's light (rgba) and colour (albedo, three a pixel, or none), times the
    // samples its pixel took; its sums faded first when the camera has moved. With the frame's depths (depthMin and
    // depthMax), only where every sample of the pixel met the probe's own surface (its tangent plane holds them): a
    // probe that has come to lie in a pixel across an edge would otherwise take in the light beyond it.
    // And only where every sample of the pixel met something (its alpha, the beauty's, is whole): misses leave no
    // depth, and a pixel some of whose samples went past an edge to the sky (a wide lens' out of focus edge) would
    // otherwise pass the depths and give its probe the sky's darkness.
    void absorb(const FieldFrame& f, const std::vector<float>& rgba, const std::vector<float>* albedo, const std::vector<unsigned>& samples,
                bool moved, double fade, const std::vector<float>* depthMin = nullptr, const std::vector<float>* depthMax = nullptr,
                const FieldOptions* op = nullptr, const std::vector<float>* coverage = nullptr) {
        mixed = 0;
        std::vector<uint8_t> done(probes.size(), 0);
        for (size_t k = 0; k < f.ids.size(); ++k) {
            WorldProbe& p = probes[f.ids[k]];
            if (done[f.ids[k]]) continue;
            done[f.ids[k]] = 1;
            const size_t px = size_t(f.pixel[k]);
            const double n = samples[px];
            if (n <= 0) continue;
            if (depthMin && depthMax && op) {
                const unsigned x = unsigned(px % width), y = unsigned(px / width);
                if (!planeHolds(f.view, f.h[k], x, y, (*depthMin)[px], (*depthMax)[px], *op) || (coverage && !whole((*coverage)[px]))) {
                    ++mixed;
                    continue;
                }
            }
            if (moved)
                for (int c = 0; c < 3; ++c) p.sum[c] *= fade, p.sumAlbedo[c] *= fade;
            if (moved) p.weight *= fade;
            for (int c = 0; c < 3; ++c) {
                p.sum[c] += n * rgba[px * 4 + c];
                p.sumAlbedo[c] += n * (albedo ? (*albedo)[px * 3 + c] : 0.0f);
            }
            p.weight += n;
        }
    }

    // Each pixel's reconstruction: light (recon, four a pixel), inverse depth (wrec, 0 none) and state.
    void reconstruct(const FieldFrame& f, const FieldOptions& op, const std::vector<float>* albedo, std::vector<float>& recon,
                     std::vector<float>& wrec, std::vector<uint8_t>& state) const {
        const size_t N = size_t(width) * height;
        recon.assign(N * 4, 0.0f), wrec.assign(N, 0.0f), state.assign(N, FieldNone);
        auto lum = [](const double* c) { return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
        parallel(op.threads, height, [&](size_t y) {
            for (unsigned x = 0; x < width; ++x) {
                const size_t i = y * width + x;
                recon[i * 4 + 3] = 1;
                const int t = f.triOf[i];
                if (t < 0) continue;
                const int k[3] = {f.tris[3 * t], f.tris[3 * t + 1], f.tris[3 * t + 2]};
                double tx[3], ty[3], b[3];
                for (int j = 0; j < 3; ++j) tx[j] = f.xy[2 * k[j]], ty[j] = f.xy[2 * k[j] + 1];
                if (!barycentric(x + 0.5, y + 0.5, tx, ty, b, 1e-6)) b[0] = 1, b[1] = b[2] = 0;
                // Over the surface, not the picture: the corners weighted by their w (perspective-correct; an
                // orthographic picture is affine, its weights already the surface's).
                if (op.planeLight && f.view.kind != View::Orthographic) {
                    const double s = b[0] * f.w[k[0]] + b[1] * f.w[k[1]] + b[2] * f.w[k[2]];
                    if (s > 0)
                        for (int j = 0; j < 3; ++j) b[j] = b[j] * f.w[k[j]] / s;
                }
                double L[3][3], A[3][3];
                bool lit = true;
                for (int j = 0; j < 3; ++j) {
                    const WorldProbe& p = probes[f.ids[k[j]]];
                    lit = lit && p.weight > 0;
                    for (int c = 0; c < 3; ++c) L[j][c] = p.weight > 0 ? p.sum[c] / p.weight : 0, A[j][c] = p.weight > 0 ? p.sumAlbedo[c] / p.weight : 0;
                }
                if (!lit) continue;
                const float* pa = albedo ? &(*albedo)[i * 3] : nullptr;
                const double floor = op.demodFloor;
                bool demod = op.demod && pa && 0.2126 * pa[0] + 0.7152 * pa[1] + 0.0722 * pa[2] >= floor;
                for (int j = 0; j < 3; ++j) demod = demod && lum(A[j]) >= floor;
                double light[3][3];
                for (int j = 0; j < 3; ++j)
                    for (int c = 0; c < 3; ++c) light[j][c] = demod ? L[j][c] / std::max(A[j][c], floor) : L[j][c];
                for (int c = 0; c < 3; ++c) {
                    const double v = b[0] * light[0][c] + b[1] * light[1][c] + b[2] * light[2][c];
                    recon[i * 4 + c] = float(std::max(0.0, demod ? pa[c] * v : v));
                }
                wrec[i] = float(f.triPlane[t].at(x + 0.5, y + 0.5));
                double lo = 1e300, hi = -1e300, mean = 0;
                for (int j = 0; j < 3; ++j) {
                    const double l = lum(light[j]);
                    lo = std::min(lo, l), hi = std::max(hi, l), mean += l / 3;
                }
                state[i] = f.triGap[t] ? FieldGap : (hi - lo) / (mean + 1e-3) > op.tauR ? FieldEdge : FieldTrusted;
            }
        });
    }

    // The GPU's verification: ok[i] where the frame's samples met what the reconstruction says (depthMin and depthMax:
    // the nearest and farthest first-hit camera depths at the pixel, +inf and -inf where none hit). Asks for probes in
    // the cells that failed and notes the cells that met nothing. Returns the share of pixels verified.
    // coverage (the beauty's alpha, each pixel's share of samples that met something): a pixel under a triangle passes
    // only where it is whole, its samples' depths alone saying nothing of those that missed.
    double verify(const FieldFrame& f, const FieldOptions& op, const std::vector<float>& depthMin, const std::vector<float>& depthMax,
                  std::vector<uint8_t>& ok, const std::vector<float>* coverage = nullptr) {
        const size_t N = size_t(width) * height;
        ok.assign(N, 0);
        std::fill(need.begin(), need.end(), 0);
        std::vector<uint32_t> hits(need.size(), 0);
        size_t good = 0;
        for (size_t i = 0; i < N; ++i) {
            const unsigned x = unsigned(i % width), y = unsigned(i / width);
            const size_t cell = size_t(y / op.cell) * cellsX + x / op.cell;
            const bool any = std::isfinite(depthMin[i]) && depthMin[i] > 0;
            if (any) ++hits[cell];
            const int t = f.triOf[i];
            bool pass;
            if (t < 0) {
                pass = !any;  // no triangle: right only where the samples met nothing
            } else if (!any || (coverage && !whole((*coverage)[i]))) {
                pass = false;
            } else {
                pass = planeHolds(f.view, f.triPlane[t], x, y, depthMin[i], depthMax[i], op);  // the triangle's plane holds every sample
            }
            ok[i] = pass;
            good += pass;
            if (!pass) need[cell] = 1;
        }
        for (size_t c = 0; c < need.size(); ++c) sky[c] = hits[c] == 0;
        return double(good) / double(N);
    }

    // A pixel's coverage whole: every sample met something.
    static bool whole(float alpha) { return alpha >= 0.999f; }

private:
    // The scene's bounds (trace space), once a field: an orthographic camera's depth scale is twice the farthest depth
    // they reach from it (view.h).
    bool bounded = false;
    D3 lo{0, 0, 0}, hi{0, 0, 0};
    double depthScale(const cpu::Plan& plan, const View& view) {
        if (!bounded) {
            bounded = true;
            lo = {1e300, 1e300, 1e300}, hi = {-1e300, -1e300, -1e300};
            for (const cpu::Mesh& e : plan.meshes) {
                if (!e.data) continue;
                for (uint32_t i = 0; i < uint32_t(e.data->positions.size()); ++i) {
                    const surface::V3 p = vertexOf(e, *e.data, i);
                    lo = {std::min(lo.x, double(p.x)), std::min(lo.y, double(p.y)), std::min(lo.z, double(p.z))};
                    hi = {std::max(hi.x, double(p.x)), std::max(hi.y, double(p.y)), std::max(hi.z, double(p.z))};
                }
            }
        }
        double most = 1e-3;
        if (lo.x <= hi.x)
            for (int k = 0; k < 8; ++k) {
                const surface::V3 c{float(k & 1 ? hi.x : lo.x), float(k & 2 ? hi.y : lo.y), float(k & 4 ? hi.z : lo.z)};
                most = std::max(most, view.depthOf(view.camera(c)));
            }
        return 2.0 * most;
    }
    static uint32_t hash(uint32_t a) {
        a ^= a >> 16, a *= 0x7feb352du, a ^= a >> 15, a *= 0x846ca68bu, a ^= a >> 16;
        return a;
    }

    void triangulate(const FieldOptions& op, FieldFrame& f) const {
        f.tris.clear(), f.triGap.clear(), f.triPlane.clear();
        f.triOf.assign(size_t(width) * height, -1);
        if (f.ids.size() < 3) return;
        Delaunay d(f.xy);
        f.flips += size_t(d.bregmanFlips(f.w, f.h));
        f.tris = d.triangles;
        const size_t T = f.tris.size() / 3;
        f.triGap.assign(T, 0), f.triPlane.assign(T, Plane{});
        std::vector<int8_t> sign(T, 1);
        for (size_t t = 0; t < T; ++t) {
            const int k[3] = {f.tris[3 * t], f.tris[3 * t + 1], f.tris[3 * t + 2]};
            double x[3], y[3], w[3];
            Plane h[3];
            for (int j = 0; j < 3; ++j) x[j] = f.xy[2 * k[j]], y[j] = f.xy[2 * k[j] + 1], w[j] = f.w[k[j]], h[j] = f.h[k[j]];
            f.triPlane[t] = planeThrough(x, y, w);
            const bool planes = h[0].ok && h[1].ok && h[2].ok && f.triPlane[t].ok;
            sign[t] = int8_t(planes ? convexity(x, y, w, h, 3) : 0);
            if (!planes) f.triGap[t] = 1;
        }
        // Each pixel's triangle, and the sandwich gap over each triangle's pixels.
        std::vector<double> gap(T, 0.0);
        for (size_t t = 0; t < T; ++t) {
            const int k[3] = {f.tris[3 * t], f.tris[3 * t + 1], f.tris[3 * t + 2]};
            double tx[3], ty[3];
            Plane h[3];
            for (int j = 0; j < 3; ++j) tx[j] = f.xy[2 * k[j]], ty[j] = f.xy[2 * k[j] + 1], h[j] = f.h[k[j]];
            const int x0 = std::max(0, int(std::floor(std::min({tx[0], tx[1], tx[2]}) - 0.5)));
            const int x1 = std::min(int(width) - 1, int(std::ceil(std::max({tx[0], tx[1], tx[2]}))));
            const int y0 = std::max(0, int(std::floor(std::min({ty[0], ty[1], ty[2]}) - 0.5)));
            const int y1 = std::min(int(height) - 1, int(std::ceil(std::max({ty[0], ty[1], ty[2]}))));
            for (int py = y0; py <= y1; ++py)
                for (int px = x0; px <= x1; ++px) {
                    double b[3];
                    if (!barycentric(px + 0.5, py + 0.5, tx, ty, b, 1e-9)) continue;
                    int& slot = f.triOf[size_t(py) * width + px];
                    if (slot < 0) slot = int(t);
                    if (f.triGap[t] && !f.triPlane[t].ok) continue;
                    const double tw = f.triPlane[t].at(px + 0.5, py + 0.5);
                    if (tw > 0) gap[t] = std::max(gap[t], sandwichGap(px + 0.5, py + 0.5, tw, h, 3, sign[t]) / tw);
                }
        }
        for (size_t t = 0; t < T; ++t)
            {
                const int* k = &f.tris[3 * t];
                const double cosine = op.slant && !f.facing.empty() ? std::max(0.05, (f.facing[k[0]] + f.facing[k[1]] + f.facing[k[2]]) / 3.0) : 1.0;
                if (gap[t] > op.tol / cosine) f.triGap[t] = 1;
            }
    }
};

}  // namespace rhea
