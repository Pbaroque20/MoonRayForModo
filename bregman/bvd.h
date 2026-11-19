// Bregman Voronoi diagrams over the camera frame (bregman/DESIGN.md, section 3).
//
// The camera frame is the domain X of Boissonnat, Nielsen and Nock's Bregman Voronoi diagrams (DCG 2010, "the paper").
// A camera-space point P lifts to (x, y, w): its raster position and its inverse depth w = 1 / depth. The lift is
// projective, so every plane of the scene becomes a plane of the lifted space: the plane of a probe's hit triangle is
// the paper's tangent hyperplane H_p (eq. 5) of the generator F = s W, where W is the visible surface's inverse depth
// over the frame and s = +1 or -1 its local convexity. Then
//   - D_F(x || p) = s (W(x) - H_p(x)) (Lemma 1): the inverse-depth gap at pixel x between the visible surface and p's
//     plane;
//   - the first-type diagram is the maximization diagram of the s H_p (paper section 4.2), here taken as the arg min of
//     |W(x) - H_p(x)| with W(x) read exactly from the radial scans' depths (scan.h);
//   - the Bregman Delaunay triangulation is the lower convex hull of the lifted sites (p, s W(p)), projected (section
//     5.1), computed here by brute force over the few sites of a probe window, with F made strictly convex by
//     eps |x|^2 (an affine part changes no diagram, Property 4, so on a plane it is the Euclidean Delaunay one).
// Host code; double precision.
#pragma once
#include "surface_core.h"
#include <array>
#include <cmath>
#include <vector>

namespace bregman {

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

// A site of a window's diagram: a probe's frame position, its lifted height W(p) and its tangent hyperplane.
struct Site {
    double x = 0, y = 0, w = 0;
    Plane h;
    int probe = -1;
};

// The Bregman Delaunay triangulation of a few sites (paper section 5.1): the lower hull of (X, Y, s W / wc + eps |X|^2)
// in coordinates normalized about (cx, cy) by spacing, faces counter-clockwise in the frame.
inline std::vector<std::array<int, 3>> bregmanDelaunay(const std::vector<Site>& s, int sign, double cx, double cy, double spacing,
                                                       double wc, double eps = 1e-6) {
    const int n = int(s.size());
    std::vector<double> X(n), Y(n), Z(n);
    for (int i = 0; i < n; ++i) {
        X[i] = (s[i].x - cx) / spacing;
        Y[i] = (s[i].y - cy) / spacing;
        Z[i] = sign * s[i].w / wc + eps * (X[i] * X[i] + Y[i] * Y[i]);
    }
    std::vector<std::array<int, 3>> faces;
    for (int i = 0; i < n; ++i)
        for (int j = i + 1; j < n; ++j)
            for (int k = j + 1; k < n; ++k) {
                const double ux = X[j] - X[i], uy = Y[j] - Y[i], vx = X[k] - X[i], vy = Y[k] - Y[i];
                const double area = ux * vy - uy * vx;
                if (std::fabs(area) < 1e-9) continue;
                const double uz = Z[j] - Z[i], vz = Z[k] - Z[i];
                const double al = (uz * vy - uy * vz) / area, be = (ux * vz - uz * vx) / area, ga = Z[i] - al * X[i] - be * Y[i];
                bool lower = true;
                for (int l = 0; l < n && lower; ++l) {
                    if (l == i || l == j || l == k) continue;
                    if (Z[l] - (al * X[l] + be * Y[l] + ga) < -1e-12) lower = false;
                }
                if (!lower) continue;
                // Co-circular sites (a tie the perturbation left) give overlapping faces: keep the first that covers.
                faces.push_back(area > 0 ? std::array<int, 3>{i, j, k} : std::array<int, 3>{i, k, j});
            }
    return faces;
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

}  // namespace bregman
