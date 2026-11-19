// The radial topological scan (bregman/DESIGN.md, section 2.3).
//
// A plan mesh (cpu::MeshData) is positions and triangles that share vertices by index, after MoonRay's tessellation and
// displacement. Its topology is built once: vertices welded by position (the tessellation splits a vertex where its
// uv or normal differs, which would cut the rings at every seam) and each triangle's three edge neighbours. A probe's
// scan walks it breadth first from the hit triangle, ring by ring, keeping the triangles that face the camera as the
// hit's does (the projected winding: a flip is a silhouette) and that project into the probe's window. The kept
// triangles, lifted onto the camera frame (bvd.h), are the probe's patch: exact pieces of the visible surface's graph,
// whose depths make the region buffer (bregman_engine.cc).
#pragma once
#include "bvd.h"
#include "cpu_scene.h"
#include <cstdint>
#include <cstring>
#include <deque>
#include <unordered_map>
#include <unordered_set>

namespace bregman {

namespace cpu = xpu2::interactive::cpu;

struct Topology {
    std::vector<uint32_t> nbr;  // three a triangle: the triangle across edge ab, bc, ca (~0u: a border)
    uint32_t welded = 0, borders = 0, nonManifold = 0;
};

inline Topology buildTopology(const cpu::MeshData& m) {
    Topology t;
    const size_t nv = m.positions.size(), nt = m.triangles.size();
    std::vector<uint32_t> weld(nv);
    struct Key {
        uint32_t a, b, c;
        bool operator==(const Key& o) const { return a == o.a && b == o.b && c == o.c; }
    };
    struct Hash {
        size_t operator()(const Key& k) const { return (size_t(k.a) * 73856093u) ^ (size_t(k.b) * 19349663u) ^ (size_t(k.c) * 83492791u); }
    };
    std::unordered_map<Key, uint32_t, Hash> byPosition;
    byPosition.reserve(nv);
    for (size_t i = 0; i < nv; ++i) {
        Key k;
        std::memcpy(&k.a, &m.positions[i].x, 4);
        std::memcpy(&k.b, &m.positions[i].y, 4);
        std::memcpy(&k.c, &m.positions[i].z, 4);
        auto it = byPosition.emplace(k, uint32_t(byPosition.size())).first;
        weld[i] = it->second;
    }
    t.welded = uint32_t(nv - byPosition.size());
    t.nbr.assign(nt * 3, ~0u);
    std::unordered_map<uint64_t, uint32_t> open;  // an edge (welded ends) to the triangle side waiting for its pair
    open.reserve(nt * 2);
    for (size_t f = 0; f < nt; ++f) {
        const uint32_t v[3] = {weld[m.triangles[f].a], weld[m.triangles[f].b], weld[m.triangles[f].c]};
        for (int e = 0; e < 3; ++e) {
            const uint32_t p = v[e], q = v[(e + 1) % 3];
            if (p == q) continue;  // a degenerate edge
            const uint64_t key = (uint64_t(std::min(p, q)) << 32) | std::max(p, q);
            auto it = open.find(key);
            if (it == open.end()) {
                open.emplace(key, uint32_t(f * 3 + e));
            } else if (it->second != ~0u) {
                const uint32_t side = it->second;
                t.nbr[f * 3 + e] = side / 3;
                t.nbr[side] = uint32_t(f);
                it->second = ~0u;  // paired: a third triangle on this edge stays unjoined
            } else {
                ++t.nonManifold;
            }
        }
    }
    for (uint32_t n : t.nbr) t.borders += n == ~0u;
    return t;
}

// A patch triangle lifted onto the frame.
struct LiftedTri {
    double x[3], y[3], w[3];
    uint32_t prim;
};

struct Patch {
    uint32_t geom = ~0u;
    std::vector<LiftedTri> tris;
    uint32_t rings = 0;
    bool truncated = false;  // stopped by the triangle limit, not by the window or the surface's end
};

// A mesh's vertex in trace space (an instance's placed by its transform), as the CPU lane's CpuBackend::vertexOf.
inline surface::V3 vertexOf(const cpu::Mesh& e, const cpu::MeshData& m, uint32_t i) {
    const surface::V3 p = m.positions[i];
    if (!e.instance) return p;
    const float* x = e.objectToWorld;
    return {p.x * x[0] + p.y * x[3] + p.z * x[6] + x[9], p.x * x[1] + p.y * x[4] + p.z * x[7] + x[10], p.x * x[2] + p.y * x[5] + p.z * x[8] + x[11]};
}

inline bool liftTriangle(const Frame& f, const cpu::Mesh& e, const cpu::MeshData& m, uint32_t prim, LiftedTri& out) {
    const auto& t = m.triangles[prim];
    const uint32_t v[3] = {t.a, t.b, t.c};
    for (int k = 0; k < 3; ++k)
        if (!f.lift(vertexOf(e, m, v[k]), out.x[k], out.y[k], out.w[k])) return false;
    out.prim = prim;
    return true;
}

inline double windingOf(const LiftedTri& t) {
    return (t.x[1] - t.x[0]) * (t.y[2] - t.y[0]) - (t.y[1] - t.y[0]) * (t.x[2] - t.x[0]);
}

// The scan from triangle prim0 of plan mesh geom, kept to the window [x0, x1) x [y0, y1) of the frame, at most
// maxRings rings and maxTriangles triangles.
inline Patch scan(const Frame& f, const cpu::Plan& plan, const Topology& topo, uint32_t geom, uint32_t prim0, double x0, double y0,
                  double x1, double y1, uint32_t maxRings, uint32_t maxTriangles) {
    Patch p;
    p.geom = geom;
    const auto& e = plan.meshes[geom];
    const auto& m = *e.data;
    LiftedTri seed;
    if (!liftTriangle(f, e, m, prim0, seed)) return p;
    const double facing = windingOf(seed);
    if (facing == 0) return p;
    std::unordered_set<uint32_t> seen;
    seen.insert(prim0);
    std::deque<std::pair<uint32_t, uint32_t>> queue;  // (triangle, ring)
    queue.emplace_back(prim0, 0u);
    while (!queue.empty()) {
        const auto [tri, ring] = queue.front();
        queue.pop_front();
        LiftedTri lt;
        if (!liftTriangle(f, e, m, tri, lt)) continue;
        if (tri != prim0) {
            if (windingOf(lt) * facing <= 0) continue;  // turned away from the camera: the silhouette
            const double bx0 = std::min({lt.x[0], lt.x[1], lt.x[2]}), bx1 = std::max({lt.x[0], lt.x[1], lt.x[2]});
            const double by0 = std::min({lt.y[0], lt.y[1], lt.y[2]}), by1 = std::max({lt.y[0], lt.y[1], lt.y[2]});
            if (bx1 < x0 || bx0 > x1 || by1 < y0 || by0 > y1) continue;  // outside the window
        }
        if (p.tris.size() >= maxTriangles) {
            p.truncated = true;
            break;
        }
        p.tris.push_back(lt);
        p.rings = std::max(p.rings, ring);
        if (ring >= maxRings) continue;
        for (int k = 0; k < 3; ++k) {
            const uint32_t n = topo.nbr[size_t(tri) * 3 + k];
            if (n != ~0u && seen.insert(n).second) queue.emplace_back(n, ring + 1);
        }
    }
    return p;
}

// The patch's depth over its window: for each pixel of the window whose centre a patch triangle covers, the largest
// lifted w there (the nearest) and that triangle. w is affine over a lifted triangle, so the barycentric blend is exact.
struct DepthTile {
    int x0 = 0, y0 = 0, width = 0, height = 0;
    std::vector<double> w;        // 0: not covered
    std::vector<uint32_t> prim;
};

inline DepthTile rasterize(const Patch& p, int x0, int y0, int x1, int y1) {
    DepthTile d;
    d.x0 = x0, d.y0 = y0, d.width = std::max(0, x1 - x0), d.height = std::max(0, y1 - y0);
    d.w.assign(size_t(d.width) * d.height, 0.0);
    d.prim.assign(size_t(d.width) * d.height, ~0u);
    for (const auto& t : p.tris) {
        const int ix0 = std::max(x0, int(std::floor(std::min({t.x[0], t.x[1], t.x[2]}) - 0.5)));
        const int ix1 = std::min(x1 - 1, int(std::ceil(std::max({t.x[0], t.x[1], t.x[2]}) - 0.5)));
        const int iy0 = std::max(y0, int(std::floor(std::min({t.y[0], t.y[1], t.y[2]}) - 0.5)));
        const int iy1 = std::min(y1 - 1, int(std::ceil(std::max({t.y[0], t.y[1], t.y[2]}) - 0.5)));
        for (int y = iy0; y <= iy1; ++y)
            for (int x = ix0; x <= ix1; ++x) {
                double b[3];
                if (!barycentric(x + 0.5, y + 0.5, t.x, t.y, b, 1e-7)) continue;
                const double w = b[0] * t.w[0] + b[1] * t.w[1] + b[2] * t.w[2];
                const size_t i = size_t(y - y0) * d.width + (x - x0);
                if (w > d.w[i]) {
                    d.w[i] = w;
                    d.prim[i] = t.prim;
                }
            }
    }
    return d;
}

}  // namespace bregman
