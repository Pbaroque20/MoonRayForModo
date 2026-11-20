// Bregman Voronoi diagrams over the camera frame (sol/DESIGN.md, section 3).
//
// The camera frame is the domain X of Boissonnat, Nielsen and Nock's Bregman Voronoi diagrams (DCG 2010, "the paper").
// A camera-space point P lifts to (x, y, w): its raster position and its inverse depth w = 1 / depth. The lift is
// projective, so every plane of the scene becomes a plane of the lifted space: the plane of a probe's hit triangle is
// the paper's tangent hyperplane H_p (eq. 5) of the generator F = s W, where W is the visible surface's inverse depth
// over the frame and s = +1 or -1 its local convexity. Then
//   - D_F(x || p) = s (W(x) - H_p(x)) (Lemma 1): the inverse-depth gap at pixel x between the visible surface and p's
//     plane; the Bregman Voronoi cell of p holds the pixels whose surface p's plane predicts best;
//   - the Bregman Delaunay triangulation is the lower convex hull of the lifted sites (p, s W(p)) (section 5.1). On four
//     sites of a lattice quad it is one of the quad's two diagonals, chosen by one orientation test (quadDiagonal);
//   - the sandwich (section 4.2 with 5.1): for convex F, max_p H_p <= F <= the Delaunay interpolation, so the gap
//     between them bounds the reconstruction's error from the sites alone (sandwichGap).
// Host code; double precision.
#pragma once
#include "surface_core.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

namespace sol {

namespace surface = xpu2::interactive::surface;

struct D3 {
    double x = 0, y = 0, z = 0;
};

// The inverse of a 4x4 matrix (Gauss-Jordan with partial pivoting); false when singular.
inline bool invert4(const double a[4][4], double out[4][4]) {
    double m[4][8];
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 8; ++j) m[i][j] = j < 4 ? a[i][j] : (j - 4 == i ? 1.0 : 0.0);
    for (int c = 0; c < 4; ++c) {
        int p = c;
        for (int r = c + 1; r < 4; ++r)
            if (std::fabs(m[r][c]) > std::fabs(m[p][c])) p = r;
        if (std::fabs(m[p][c]) < 1e-300) return false;
        if (p != c)
            for (int j = 0; j < 8; ++j) std::swap(m[p][j], m[c][j]);
        const double d = m[c][c];
        for (int j = 0; j < 8; ++j) m[c][j] /= d;
        for (int r = 0; r < 4; ++r) {
            if (r == c) continue;
            const double f = m[r][c];
            if (f == 0) continue;
            for (int j = 0; j < 8; ++j) m[r][j] -= f * m[c][j];
        }
    }
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) out[i][j] = m[i][j + 4];
    return true;
}

// The camera frame and the lift onto it. Matrices are surface::Matrix's: row vectors, p' = [p 1] M.
struct Frame {
    double toCamera[4][4] = {};  // trace space (the rays' and the meshes') to camera space
    D3 o, ex, ey;                // the camera point of raster (x, y, -1) is o + x ex + y ey (a plane of constant z)
    double det = 0;
    D3 eye;                      // the camera's position in trace space
    bool init(const surface::Camera& c) {
        double m[4][4];
        for (int i = 0; i < 4; ++i)
            for (int j = 0; j < 4; ++j) m[i][j] = c.cameraToRender.m[i][j];
        if (!invert4(m, toCamera)) return false;
        surface::V3 a, b, d;
        if (!surface::point(c.rasterToCamera, {0, 0, -1}, a) || !surface::point(c.rasterToCamera, {1, 0, -1}, b) ||
            !surface::point(c.rasterToCamera, {0, 1, -1}, d))
            return false;
        o = {a.x, a.y, a.z};
        ex = {b.x - a.x, b.y - a.y, b.z - a.z};
        ey = {d.x - a.x, d.y - a.y, d.z - a.z};
        det = ex.x * ey.y - ex.y * ey.x;
        // A perspective camera's raster plane has one depth; the lift below assumes it.
        if (!(o.z < 0) || std::fabs(ex.z) > 1e-6 * std::fabs(o.z) || std::fabs(ey.z) > 1e-6 * std::fabs(o.z) || det == 0) return false;
        eye = {m[3][0] / m[3][3], m[3][1] / m[3][3], m[3][2] / m[3][3]};
        return true;
    }
    D3 camera(const surface::V3& p) const {
        const double v[4] = {p.x, p.y, p.z, 1.0};
        double r[4];
        for (int j = 0; j < 4; ++j) r[j] = v[0] * toCamera[0][j] + v[1] * toCamera[1][j] + v[2] * toCamera[2][j] + v[3] * toCamera[3][j];
        return {r[0] / r[3], r[1] / r[3], r[2] / r[3]};
    }
    // The lift of a camera-space point: raster x, y and inverse depth w; false behind the camera.
    bool liftCamera(const D3& c, double& x, double& y, double& w) const {
        if (!(c.z < -1e-12)) return false;
        const double t = o.z / c.z;
        const double qx = t * c.x - o.x, qy = t * c.y - o.y;
        x = (qx * ey.y - qy * ey.x) / det;
        y = (ex.x * qy - ex.y * qx) / det;
        w = 1.0 / -c.z;
        return std::isfinite(x) && std::isfinite(y) && std::isfinite(w);
    }
    bool lift(const surface::V3& p, double& x, double& y, double& w) const { return liftCamera(camera(p), x, y, w); }
};

// A plane of the lifted space, w = a x + b y + c: the lift of a scene plane (a hyperplane H_p of the paper).
struct Plane {
    double a = 0, b = 0, c = 0;
    bool ok = false;
    double at(double x, double y) const { return a * x + b * y + c; }
};

// The plane through three lifted points (a triangle's lift is exactly planar).
inline Plane planeThrough(const double x[3], const double y[3], const double w[3]) {
    Plane p;
    const double ux = x[1] - x[0], uy = y[1] - y[0], uw = w[1] - w[0];
    const double vx = x[2] - x[0], vy = y[2] - y[0], vw = w[2] - w[0];
    const double d = ux * vy - uy * vx;
    if (std::fabs(d) < 1e-12) return p;  // seen edge on: no plane over the frame
    p.a = (uw * vy - uy * vw) / d;
    p.b = (ux * vw - uw * vx) / d;
    p.c = w[0] - p.a * x[0] - p.b * y[0];
    p.ok = std::isfinite(p.a) && std::isfinite(p.b) && std::isfinite(p.c);
    return p;
}

// Barycentric coordinates of (x, y) in a frame triangle; false when outside (by more than tol).
inline bool barycentric(double x, double y, const double tx[3], const double ty[3], double b[3], double tol = 1e-9) {
    const double d = (ty[1] - ty[2]) * (tx[0] - tx[2]) + (tx[2] - tx[1]) * (ty[0] - ty[2]);
    if (std::fabs(d) < 1e-18) return false;
    b[0] = ((ty[1] - ty[2]) * (x - tx[2]) + (tx[2] - tx[1]) * (y - ty[2])) / d;
    b[1] = ((ty[2] - ty[0]) * (x - tx[2]) + (tx[0] - tx[2]) * (y - ty[2])) / d;
    b[2] = 1.0 - b[0] - b[1];
    return b[0] >= -tol && b[1] >= -tol && b[2] >= -tol;
}

// The local convexity of a few sites (x, y, w, H): +1 where every site's plane lies under the others' heights (F = W
// convex there), -1 where over (concave), 0 a saddle (both, past eps relative). D_F(b || a) = s (w_b - H_a(b)).
inline int convexity(const double* x, const double* y, const double* w, const Plane* h, int n, double eps = 1e-7) {
    int pos = 0, neg = 0;
    for (int i = 0; i < n; ++i)
        for (int j = 0; j < n; ++j) {
            if (i == j) continue;
            const double e = (w[j] - h[i].at(x[j], y[j])) / w[j];
            pos += e > eps;
            neg += e < -eps;
        }
    return pos && neg ? 0 : (neg ? -1 : 1);
}

// The Bregman Delaunay triangulation of a quad's four corners a, b, c, d (counter-clockwise in the frame): true for the
// diagonal ac (triangles abc, acd), false for bd (abd, bcd). The lower hull of (x, y, s w): ac is a hull edge when d lies
// on or over the plane through a, b and c. A tie (four sites on one plane) keeps ac.
inline bool quadDiagonal(const double* x, const double* y, const double* w, int sign) {
    double z[4];
    for (int i = 0; i < 4; ++i) z[i] = (sign < 0 ? -1.0 : 1.0) * w[i];
    const double xs[3] = {x[0], x[1], x[2]}, ys[3] = {y[0], y[1], y[2]}, zs[3] = {z[0], z[1], z[2]};
    const Plane p = planeThrough(xs, ys, zs);
    if (!p.ok) return true;
    const double scale = std::max({std::fabs(z[0]), std::fabs(z[1]), std::fabs(z[2]), std::fabs(z[3])});
    return z[3] - p.at(x[3], y[3]) >= -1e-12 * scale;
}

// The sandwich gap at (x, y): how far apart the bounds on the true inverse depth are there, given the Delaunay
// interpolation t and the sites' planes h. Convex (sign +1): max H <= W <= t; concave (-1): t <= W <= min H; a saddle
// (0) has no bound, and its gap is the spread of everything (t and every plane). Bounds that cross (t under a plane of
// a convex piece) are evidence against the convexity: their crossing counts as the gap.
inline double sandwichGap(double x, double y, double t, const Plane* h, int n, int sign) {
    double lo = t, hi = t, top = -1e300, bottom = 1e300;
    for (int i = 0; i < n; ++i) {
        const double v = h[i].at(x, y);
        lo = std::min(lo, v), hi = std::max(hi, v);
        top = std::max(top, v), bottom = std::min(bottom, v);
    }
    if (sign > 0) return std::fabs(t - top);
    if (sign < 0) return std::fabs(bottom - t);
    return hi - lo;
}

}  // namespace sol
