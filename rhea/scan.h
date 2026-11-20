// The radial topological scan (rhea/DESIGN.md, section 2.3).
//
// A plan mesh (cpu::MeshData) is positions and triangles that share vertices by index, after MoonRay's tessellation and
// displacement. Its topology is built once: vertices welded by position (the tessellation splits a vertex where its
// uv or normal differs, which would cut the rings at every seam) and each triangle's three edge neighbours. A probe's
// scan walks it breadth first from the hit triangle, ring by ring, keeping the triangles that face the camera as the
// hit's does (the projected winding: a flip is a silhouette) and that project into the probe's window.
//
// What a scan gives the geometry index (virtual_surface.h): the patch's triangles (which surface the probe stands on,
// so which probes are connected) and its boundary in the frame: the edges where the surface ends inside the window, at
// a border of the mesh or where it turns away from the camera (a silhouette). Edges where only the window cut the scan
// are not boundaries.
#pragma once
#include "bvd.h"
#include "cpu_scene.h"
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <deque>
#include <unordered_map>

namespace rhea {

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

// A triangle lifted onto the frame.
struct LiftedTri {
    double x[3], y[3], w[3];
};

// A segment of the frame (raster coordinates).
struct Segment {
    double x0, y0, x1, y1;
};

struct Patch {
    uint32_t geom = ~0u, seed = ~0u;
    LiftedTri seedTri{};
    std::vector<uint32_t> prims;  // the patch's triangles, sorted
    std::vector<Segment> bounds;  // where the surface ends inside the window
    uint32_t rings = 0, visited = 0;
    bool truncated = false;  // stopped by the triangle limit, not by the window or the surface's end
    bool behind = false;     // part of the surface crosses the camera's plane: its boundary there is unknown
    bool contains(uint32_t prim) const { return std::binary_search(prims.begin(), prims.end(), prim); }
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
    return true;
}

inline double windingOf(const LiftedTri& t) {
    return (t.x[1] - t.x[0]) * (t.y[2] - t.y[0]) - (t.y[1] - t.y[0]) * (t.x[2] - t.x[0]);
}

// The scan from triangle prim0 of plan mesh geom, kept to the window [x0, x1] x [y0, y1] of the frame, at most
// maxRings rings and maxTriangles triangles.
inline Patch scan(const Frame& f, const cpu::Plan& plan, const Topology& topo, uint32_t geom, uint32_t prim0, double x0, double y0,
                  double x1, double y1, uint32_t maxRings, uint32_t maxTriangles) {
    Patch p;
    p.geom = geom;
    p.seed = prim0;
    const auto& e = plan.meshes[geom];
    const auto& m = *e.data;
    if (!liftTriangle(f, e, m, prim0, p.seedTri)) return p;
    const double facing = windingOf(p.seedTri);
    if (facing == 0) return p;
    // A triangle's state: 1 kept, 2 the surface's end (turned away, or behind the camera), 3 outside the window.
    std::unordered_map<uint32_t, uint8_t> state;
    state.reserve(256);
    auto edgeOf = [&](uint32_t tri, int k, Segment& s) {
        const auto& t = m.triangles[tri];
        const uint32_t v[3] = {t.a, t.b, t.c};
        double w;
        return f.lift(vertexOf(e, m, v[k]), s.x0, s.y0, w) && f.lift(vertexOf(e, m, v[(k + 1) % 3]), s.x1, s.y1, w);
    };
    // The boundary between a kept triangle and a neighbour that ends the surface: their shared edge.
    auto boundary = [&](uint32_t kept, uint32_t other) {
        for (int k = 0; k < 3; ++k)
            if (topo.nbr[size_t(kept) * 3 + k] == other) {
                Segment s;
                if (edgeOf(kept, k, s)) p.bounds.push_back(s);
                else p.behind = true;
            }
    };
    std::deque<std::pair<uint32_t, uint32_t>> queue;  // (triangle, ring)
    queue.emplace_back(prim0, 0u);
    state[prim0] = 0;
    while (!queue.empty()) {
        const auto [tri, ring] = queue.front();
        queue.pop_front();
        ++p.visited;
        LiftedTri lt;
        uint8_t s = 1;
        if (!liftTriangle(f, e, m, tri, lt)) {
            s = 2;
            p.behind = true;
        } else if (tri != prim0) {
            const double bx0 = std::min({lt.x[0], lt.x[1], lt.x[2]}), bx1 = std::max({lt.x[0], lt.x[1], lt.x[2]});
            const double by0 = std::min({lt.y[0], lt.y[1], lt.y[2]}), by1 = std::max({lt.y[0], lt.y[1], lt.y[2]});
            if (bx1 < x0 || bx0 > x1 || by1 < y0 || by0 > y1) s = 3;   // outside the window
            else if (windingOf(lt) * facing <= 0) s = 2;               // turned away from the camera: a silhouette
        }
        state[tri] = s;
        if (s == 2) {
            for (int k = 0; k < 3; ++k) {
                const uint32_t n = topo.nbr[size_t(tri) * 3 + k];
                if (n == ~0u) continue;
                auto it = state.find(n);
                if (it != state.end() && it->second == 1) boundary(n, tri);
            }
            continue;
        }
        if (s == 3) continue;
        if (p.prims.size() >= maxTriangles) {
            p.truncated = true;
            break;
        }
        p.prims.push_back(tri);
        p.rings = std::max(p.rings, ring);
        for (int k = 0; k < 3; ++k) {
            const uint32_t n = topo.nbr[size_t(tri) * 3 + k];
            if (n == ~0u) {
                Segment sg;  // a border of the mesh
                if (edgeOf(tri, k, sg)) p.bounds.push_back(sg);
                else p.behind = true;
                continue;
            }
            auto it = state.find(n);
            if (it != state.end()) {
                if (it->second == 2) boundary(tri, n);
                continue;
            }
            if (ring >= maxRings) {
                p.truncated = true;  // the ring limit cut a surface that goes on in the window
                continue;
            }
            state[n] = 0;
            queue.emplace_back(n, ring + 1);
        }
    }
    std::sort(p.prims.begin(), p.prims.end());
    return p;
}

}  // namespace rhea
