// Rhea's view of XPU2's camera for persistent probes (rhea/DESIGN.md 22): where a trace-space point lands in the picture
// and its lifted depth w, the chief ray through a pixel, and a probe's tangent plane in the lifted space, for every camera
// kind XPU2 renders but the bake camera.
//
// - Perspective (with depth of field or not): the lift of bvd.h's Frame, w the inverse depth (planes stay planes).
// - Orthographic: the picture is affine in camera space, so a plane stays a plane in (x, y, depth); w = 1 - depth / K,
//   K twice the farthest depth the scene reaches (setDepthScale), so that w falls as depth grows and stays in (0, 1].
// - Spherical, fisheye and dome (directional): no plane stays a plane; a point's place is found from the camera's own
//   rays (XPU2's camera_core.h), by Gauss-Newton from where it was last seen (or a coarse grid of the picture's rays),
//   w = 1 / distance, tangent planes by local differences. The GPU's verification is what holds them to the picture.
//
// Depth of field and motion blur keep the pinhole at the lens' centre and the shutter's open: pixels whose samples meet
// what that does not (out of focus, moving) fail the verification and are XPU2's samples alone.
//
// Raster places are the picture's own (from its corner, pixels): a render region's offset is taken out, as XPU2's rays
// (cameraSampleAt) put it in.
#pragma once
#include "bvd.h"
#include "scan.h"
#include "camera_core.h"

namespace rhea {

class View {
public:
    enum Kind { Perspective, Orthographic, Directional };
    Kind kind = Perspective;
    double toCamera[4][4] = {}, toTrace[4][4] = {};  // trace space to camera space, and back (row vectors)
    unsigned width = 0, height = 0;
    // The perspective camera's focal point (camera space): toward's, for the graphics card's lookups (rhea_store_core.h).
    D3 focal() const { return fp; }
    // The chief rays' camera (the lens' centre): Rhea Draft's lines on the card (rhea_store_core.h LineSettings).
    const surface::Camera& chief() const { return cam; }

    // False for a camera Rhea's probes cannot follow (bake), or a degenerate one.
    bool init(const surface::Camera& c, unsigned w, unsigned h) {
        cam = c, width = w, height = h;
        cam.dof = 0;  // the chief ray: the lens' centre
        regionX = c.regionX, regionY = c.regionY;
        for (int i = 0; i < 4; ++i)
            for (int j = 0; j < 4; ++j) toTrace[i][j] = c.cameraToRender.m[i][j];
        if (!invert4(toTrace, toCamera)) return false;
        local = cam;
        for (int i = 0; i < 4; ++i)
            for (int j = 0; j < 4; ++j) local.cameraToRender.m[i][j] = local.camera2Render.m[i][j] = local.render2World.m[i][j] = float(i == j);
        switch (c.type) {
        case surface::CameraPerspective:
        case surface::CameraOrthographic: {
            kind = c.type == surface::CameraPerspective ? Perspective : Orthographic;
            surface::V3 a, b, d;
            if (!surface::point(c.rasterToCamera, {0, 0, -1}, a) || !surface::point(c.rasterToCamera, {1, 0, -1}, b) ||
                !surface::point(c.rasterToCamera, {0, 1, -1}, d))
                return false;
            o = {a.x, a.y, a.z};
            ex = {b.x - a.x, b.y - a.y, b.z - a.z};
            ey = {d.x - a.x, d.y - a.y, d.z - a.z};
            det = ex.x * ey.y - ex.y * ey.x;
            if (det == 0) return false;
            if (kind == Perspective && (!(o.z < 0) || std::fabs(ex.z) > 1e-6 * std::fabs(o.z) || std::fabs(ey.z) > 1e-6 * std::fabs(o.z))) return false;
            fp = {c.focalPoint.x, c.focalPoint.y, c.focalPoint.z};
            if (kind == Perspective && !(o.z < fp.z)) return false;
            return true;
        }
        case surface::CameraSpherical:
        case surface::CameraFisheye:
        case surface::CameraDome: {
            kind = Directional;
            // A coarse grid of the picture's rays (camera space), for a first guess where none is given.
            step = std::max(4u, std::min(32u, std::max(w, h) / 48));
            gx = (w + step - 1) / step, gy = (h + step - 1) / step;
            grid.assign(size_t(gx) * gy, D3{0, 0, 0});
            gridOk.assign(grid.size(), 0);
            for (unsigned j = 0; j < gy; ++j)
                for (unsigned i = 0; i < gx; ++i) {
                    D3 d;
                    const size_t k = size_t(j) * gx + i;
                    if (direction(i * step + 0.5 * step, j * step + 0.5 * step, d)) grid[k] = d, gridOk[k] = 1;
                }
            return true;
        }
        default:
            return false;
        }
    }
    // An orthographic camera's depth scale K (twice the farthest depth the scene reaches from it).
    void setDepthScale(double k) { K = k > 0 ? k : 1.0; }
    double depthScale() const { return K; }
    bool needsDepthScale() const { return kind == Orthographic; }

    D3 camera(const surface::V3& p) const {
        const double v[4] = {p.x, p.y, p.z, 1.0};
        double r[4];
        for (int j = 0; j < 4; ++j) r[j] = v[0] * toCamera[0][j] + v[1] * toCamera[1][j] + v[2] * toCamera[2][j] + v[3] * toCamera[3][j];
        return {r[0] / r[3], r[1] / r[3], r[2] / r[3]};
    }
    // A camera-space point's depth as the depth output measures it: -z for perspective and orthographic cameras, the
    // ray's length for the others (Camera::computeZDistance).
    double depthOf(const D3& c) const { return kind == Directional ? std::sqrt(c.x * c.x + c.y * c.y + c.z * c.z) : -c.z; }
    // How squarely a surface faces the camera at a point: |cos| of the angle between its normal (trace space) and the
    // ray to the point (1 face on, 0 edge on).
    double facing(const D3& n, const surface::V3& p) const {
        const D3 nc{n.x * toCamera[0][0] + n.y * toCamera[1][0] + n.z * toCamera[2][0], n.x * toCamera[0][1] + n.y * toCamera[1][1] + n.z * toCamera[2][1],
                    n.x * toCamera[0][2] + n.y * toCamera[1][2] + n.z * toCamera[2][2]};
        D3 v{0, 0, -1};
        if (kind != Orthographic) {
            const D3 c = camera(p);
            v = {c.x - (kind == Perspective ? fp.x : 0.0), c.y - (kind == Perspective ? fp.y : 0.0), c.z - (kind == Perspective ? fp.z : 0.0)};
        }
        const double nl = std::sqrt(nc.x * nc.x + nc.y * nc.y + nc.z * nc.z), vl = std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
        return nl > 0 && vl > 0 ? std::fabs(nc.x * v.x + nc.y * v.y + nc.z * v.z) / (nl * vl) : 1.0;
    }
    // A surface's unit normal (trace space) at a point, turned to face the camera (planes.h compares neighbours' normals,
    // whatever the meshes' winding).
    D3 toward(const D3& n, const surface::V3& p) const {
        const double l = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z);
        if (!(l > 0)) return D3{0, 0, 0};
        D3 u{n.x / l, n.y / l, n.z / l};
        const D3 nc{u.x * toCamera[0][0] + u.y * toCamera[1][0] + u.z * toCamera[2][0], u.x * toCamera[0][1] + u.y * toCamera[1][1] + u.z * toCamera[2][1],
                    u.x * toCamera[0][2] + u.y * toCamera[1][2] + u.z * toCamera[2][2]};
        D3 v{0, 0, -1};
        if (kind != Orthographic) {
            const D3 c = camera(p);
            v = {c.x - (kind == Perspective ? fp.x : 0.0), c.y - (kind == Perspective ? fp.y : 0.0), c.z - (kind == Perspective ? fp.z : 0.0)};
        }
        if (nc.x * v.x + nc.y * v.y + nc.z * v.z > 0) u = {-u.x, -u.y, -u.z};
        return u;
    }
    // The lifted depth of a depth (the verification's, from the depth output).
    double wOf(double depth) const { return kind == Orthographic ? 1.0 - depth / K : 1.0 / depth; }
    // The point (trace space) the chief ray through raster (x, y) meets at a depth as the depth output measures it (the
    // back plane's points, from the z-buffer). False where the camera has no ray there.
    bool pointAt(double x, double y, double depth, surface::V3& out) const {
        if (!(depth > 0) || !std::isfinite(depth)) return false;
        if (kind != Directional) {
            // The raster plane's point (as lift reads it back), then along the chief ray (from the focal point, or
            // straight for an orthographic camera) to the depth: no camera ray made (a frame's every pixel, twice).
            const double rx = x + regionX, ry = y + regionY;
            const D3 q{o.x + ex.x * rx + ey.x * ry, o.y + ex.y * rx + ey.y * ry, o.z + ex.z * rx + ey.z * ry};
            D3 c{q.x, q.y, -depth};
            if (kind == Perspective) {
                const D3 d{q.x - fp.x, q.y - fp.y, q.z - fp.z};
                if (!(d.z < 0)) return false;
                const double t = (-depth - fp.z) / d.z;
                c = {fp.x + t * d.x, fp.y + t * d.y, -depth};
            }
            const double v[4] = {c.x, c.y, c.z, 1.0};
            double r[4];
            for (int j = 0; j < 4; ++j) r[j] = v[0] * toTrace[0][j] + v[1] * toTrace[1][j] + v[2] * toTrace[2][j] + v[3] * toTrace[3][j];
            if (!(std::fabs(r[3]) > 1e-30)) return false;
            out = {float(r[0] / r[3]), float(r[1] / r[3]), float(r[2] / r[3])};
            return true;
        }
        surface::Ray r;
        if (!ray(x, y, r)) return false;
        const surface::V3 o0{r.origin.x, r.origin.y, r.origin.z};
        const surface::V3 o1{r.origin.x + r.direction.x, r.origin.y + r.direction.y, r.origin.z + r.direction.z};
        double t;
        if (kind == Directional) {
            const double l = std::sqrt(double(r.direction.x) * r.direction.x + double(r.direction.y) * r.direction.y + double(r.direction.z) * r.direction.z);
            if (!(l > 0)) return false;
            const D3 c0 = camera(o0);
            // The depth is the distance from the camera's centre; the ray starts there (or about it, a lens' offset).
            t = (depth - std::sqrt(c0.x * c0.x + c0.y * c0.y + c0.z * c0.z)) / l;
        } else {
            const double z0 = camera(o0).z, z1 = camera(o1).z;
            if (!(std::fabs(z1 - z0) > 1e-30)) return false;
            t = (-depth - z0) / (z1 - z0);
        }
        if (!(t > 0) || !std::isfinite(t)) return false;
        out = {float(r.origin.x + t * r.direction.x), float(r.origin.y + t * r.direction.y), float(r.origin.z + t * r.direction.z)};
        return true;
    }

    // Where a trace-space point lands (raster x, y of the picture) and its lifted depth; hinted: x, y hold where to start
    // looking (directional cameras). False where the camera does not see it.
    bool lift(const surface::V3& p, double& x, double& y, double& w, bool hinted = false) const {
        const D3 c = camera(p);
        switch (kind) {
        case Perspective: {
            // The ray from the focal point (perspectiveRay) through the raster plane: where it crosses it.
            if (!(c.z < fp.z - 1e-12)) return false;
            const double t = (o.z - fp.z) / (c.z - fp.z);
            const double qx = fp.x + t * (c.x - fp.x) - o.x, qy = fp.y + t * (c.y - fp.y) - o.y;
            x = (qx * ey.y - qy * ey.x) / det - regionX;
            y = (ex.x * qy - ex.y * qx) / det - regionY;
            w = 1.0 / -c.z;
            break;
        }
        case Orthographic: {
            const double d = -c.z;
            if (!(d > 1e-12) || !(d < K)) return false;
            const double qx = c.x - o.x, qy = c.y - o.y;
            x = (qx * ey.y - qy * ey.x) / det - regionX;
            y = (ex.x * qy - ex.y * qx) / det - regionY;
            w = 1.0 - d / K;
            break;
        }
        case Directional: {
            const double r = std::sqrt(c.x * c.x + c.y * c.y + c.z * c.z);
            if (!(r > 1e-12)) return false;
            const D3 u{c.x / r, c.y / r, c.z / r};
            if (!hinted && !guess(u, x, y)) return false;
            if (!solve(u, x, y) && !(hinted && guess(u, x, y) && solve(u, x, y))) return false;
            w = 1.0 / r;
            break;
        }
        }
        return std::isfinite(x) && std::isfinite(y) && std::isfinite(w);
    }

    // The chief ray through raster (x, y) of the picture: the lens' centre, the shutter's open (trace space).
    bool ray(double x, double y, surface::Ray& out) const {
        return surface::cameraSampleAt(cam, float(x), float(y), 0.0f, 0.0f, out) == surface::CameraResult::Made;
    }

    // The tangent plane of the lifted surface at a probe: point p on a mesh triangle, seen at x, y. Perspective and
    // orthographic lifts take a triangle to a plane, so it is the plane through the corners' lifts; for the others, the
    // plane through the lifts of p and two points a pixel or so from it on the triangle.
    Plane tangent(const cpu::Mesh& e, const cpu::MeshData& m, uint32_t prim, const surface::V3& p, double x, double y) const {
        const auto& t = m.triangles[prim];
        const surface::V3 a = vertexOf(e, m, t.a), b = vertexOf(e, m, t.b), c = vertexOf(e, m, t.c);
        if (kind != Directional) {
            double lx[3], ly[3], lw[3];
            const surface::V3 v[3] = {a, b, c};
            for (int k = 0; k < 3; ++k)
                if (!lift(v[k], lx[k], ly[k], lw[k])) return Plane{};
            return planeThrough(lx, ly, lw);
        }
        // Two directions on the triangle, and a step of about a pixel at the probe's distance.
        const D3 u{b.x - a.x, b.y - a.y, b.z - a.z}, v{c.x - a.x, c.y - a.y, c.z - a.z};
        const double ul = std::sqrt(u.x * u.x + u.y * u.y + u.z * u.z);
        D3 n{u.y * v.z - u.z * v.y, u.z * v.x - u.x * v.z, u.x * v.y - u.y * v.x};
        const double nl = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z);
        if (!(ul > 0) || !(nl > 0)) return Plane{};
        const D3 t1{u.x / ul, u.y / ul, u.z / ul};
        n = {n.x / nl, n.y / nl, n.z / nl};
        const D3 t2{n.y * t1.z - n.z * t1.y, n.z * t1.x - n.x * t1.z, n.x * t1.y - n.y * t1.x};
        D3 d0, d1;
        if (!direction(x, y, d0) || !direction(x + 1.0, y, d1)) return Plane{};
        const D3 pc = camera(p);
        const double r = std::sqrt(pc.x * pc.x + pc.y * pc.y + pc.z * pc.z);
        const double angle = std::sqrt((d1.x - d0.x) * (d1.x - d0.x) + (d1.y - d0.y) * (d1.y - d0.y) + (d1.z - d0.z) * (d1.z - d0.z));
        const double eps = std::max(1e-6, r * angle);
        const surface::V3 q[3] = {p, {float(p.x + eps * t1.x), float(p.y + eps * t1.y), float(p.z + eps * t1.z)},
                                  {float(p.x + eps * t2.x), float(p.y + eps * t2.y), float(p.z + eps * t2.z)}};
        double lx[3], ly[3], lw[3];
        for (int k = 0; k < 3; ++k) {
            lx[k] = x, ly[k] = y;
            if (!lift(q[k], lx[k], ly[k], lw[k], true)) return Plane{};
        }
        return planeThrough(lx, ly, lw);
    }

private:
    surface::Camera cam{}, local{};  // local: the camera at the origin, its rays' directions in camera space
    D3 o{0, 0, 0}, ex{0, 0, 0}, ey{0, 0, 0}, fp{0, 0, 0};
    double det = 0, regionX = 0, regionY = 0, K = 1.0;
    unsigned step = 16, gx = 0, gy = 0;
    std::vector<D3> grid;
    std::vector<uint8_t> gridOk;

    // The camera-space direction of the ray through raster (x, y) of the picture (directional cameras).
    bool direction(double x, double y, D3& d) const {
        surface::Ray r;
        if (surface::cameraSampleAt(local, float(x), float(y), 0.0f, 0.0f, r) != surface::CameraResult::Made) return false;
        const double l = std::sqrt(double(r.direction.x) * r.direction.x + double(r.direction.y) * r.direction.y + double(r.direction.z) * r.direction.z);
        if (!(l > 0)) return false;
        d = {r.direction.x / l, r.direction.y / l, r.direction.z / l};
        return true;
    }
    // The grid's ray nearest the direction u: a first guess.
    bool guess(const D3& u, double& x, double& y) const {
        double best = -2;
        size_t at = grid.size();
        for (size_t k = 0; k < grid.size(); ++k) {
            if (!gridOk[k]) continue;
            const double c = grid[k].x * u.x + grid[k].y * u.y + grid[k].z * u.z;
            if (c > best) best = c, at = k;
        }
        if (at == grid.size()) return false;
        x = double(at % gx) * step + 0.5 * step, y = double(at / gx) * step + 0.5 * step;
        return true;
    }
    // Gauss-Newton on the picture's place whose ray is u, from x, y.
    bool solve(const D3& u, double& x, double& y) const {
        const double h = 0.25;
        for (int it = 0; it < 12; ++it) {
            D3 d0, dx, dy;
            if (!direction(x, y, d0)) return false;
            const D3 e{d0.x - u.x, d0.y - u.y, d0.z - u.z};
            const double err = e.x * e.x + e.y * e.y + e.z * e.z;
            if (err < 1e-14) return true;
            if (!direction(x + h, y, dx) || !direction(x, y + h, dy)) return false;
            const D3 jx{(dx.x - d0.x) / h, (dx.y - d0.y) / h, (dx.z - d0.z) / h}, jy{(dy.x - d0.x) / h, (dy.y - d0.y) / h, (dy.z - d0.z) / h};
            const double a = jx.x * jx.x + jx.y * jx.y + jx.z * jx.z, b = jx.x * jy.x + jx.y * jy.y + jx.z * jy.z, c = jy.x * jy.x + jy.y * jy.y + jy.z * jy.z;
            const double gxv = jx.x * e.x + jx.y * e.y + jx.z * e.z, gyv = jy.x * e.x + jy.y * e.y + jy.z * e.z;
            const double dt = a * c - b * b;
            if (!(std::fabs(dt) > 1e-30)) return false;
            double sx = -(c * gxv - b * gyv) / dt, sy = -(a * gyv - b * gxv) / dt;
            const double len = std::sqrt(sx * sx + sy * sy), most = 0.25 * std::max(width, height);
            if (len > most) sx *= most / len, sy *= most / len;
            x += sx, y += sy;
            if (!std::isfinite(x) || !std::isfinite(y)) return false;
        }
        D3 d0;
        if (!direction(x, y, d0)) return false;
        const double err = (d0.x - u.x) * (d0.x - u.x) + (d0.y - u.y) * (d0.y - u.y) + (d0.z - u.z) * (d0.z - u.z);
        return err < 1e-10;
    }
};

}  // namespace rhea
