// The coarse first pass's geometry (the session's coarse plan, cpu::Limits::coarse; INDEXER.md section 18). A standard
// render's first samples are rendered on lighter geometry while its full geometry is prepared, shown in its pictures and
// never in its film: MoonRay's tessellation at a quarter of a mesh's resolution or four times its screen error
// (coarseTessellation, read where the tessellation is asked for), and a dense mesh simplified by meshoptimizer (MIT,
// upstream/meshoptimizer, v0.22; xpu2_meshopt.cc) to about two pixels an edge on screen, its normals and texture
// coordinates kept where they part and its open edges where they are. Coarse meshes say so (MeshData::coarse): no later
// plan takes one over, and the tessellation cache keeps none.
#pragma once
#include <meshoptimizer.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

namespace xpu2::interactive::cpu {

// coarseTessellation, coarseResolution and coarseError: cpu_scene.h, beside Limits.

// The angle a pixel at the middle of the picture covers, through a perspective camera; 0 for another.
inline float pixelAngle(const surface::Camera& c, unsigned width, unsigned height) {
    if (c.type != surface::CameraPerspective || !width || !height) return 0.0f;
    const surface::V3 r{float(width) * 0.5f, float(height) * 0.5f, 0.0f};
    const surface::V3 a = surface::camNormalize(surface::camSub(surface::transformH(c.rasterToCamera, r), c.focalPoint));
    const surface::V3 b = surface::camNormalize(surface::camSub(surface::transformH(c.rasterToCamera, {r.x + 1.0f, r.y, 0.0f}), c.focalPoint));
    const float d = std::clamp(a.x * b.x + a.y * b.y + a.z * b.z, -1.0f, 1.0f);
    return std::acos(d);
}

// A mesh lighter for the coarse pass, or null where it is left as it is: one of at least 20,000 triangles whose edges
// are under two pixels on screen, with nothing a simplified triangle list would lose (no points or curves, no motion,
// no subdivision derivatives, no polyvertices, primitive attributes only constant ones, not an instancer's shared mesh).
// eye: the camera in render space; angle: pixelAngle.
inline std::shared_ptr<const MeshData> coarseMesh(const MeshData& m, surface::V3 eye, float angle) {
    // XPU2_SESSION_COARSE_SIMPLIFY=0: the coarse pass's tessellation alone, no mesh simplified.
    static const bool simplify = [] { const char* v = std::getenv("XPU2_SESSION_COARSE_SIMPLIFY"); return !(v && v[0] == '0'); }();
    const size_t count = m.triangles.size();
    if (!simplify || count < 20000 || angle <= 0.0f || m.points || m.curveBasis || !m.steps.empty() || !m.stepNormals.empty() || !m.dpds.empty() ||
        !m.polyVertices.empty() || m.instanced || m.gate || m.positions.empty())
        return nullptr;
    for (const auto& p : m.prims)
        if (p.rate != shade::PrimConstant) return nullptr;
    // How large it is on screen: its edges (from 256 triangles spread over it) and its size across, at its nearest.
    surface::V3 lo = m.positions[0], hi = lo;
    for (const auto& p : m.positions) {
        lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
        hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
    }
    const surface::V3 centre{(lo.x + hi.x) * 0.5f, (lo.y + hi.y) * 0.5f, (lo.z + hi.z) * 0.5f};
    const float radius = 0.5f * std::sqrt((hi.x - lo.x) * (hi.x - lo.x) + (hi.y - lo.y) * (hi.y - lo.y) + (hi.z - lo.z) * (hi.z - lo.z));
    double edges = 0;
    size_t sampled = 0;
    auto length = [&](unsigned a, unsigned b) {
        const auto &p = m.positions[a], &q = m.positions[b];
        return std::sqrt(double(p.x - q.x) * (p.x - q.x) + double(p.y - q.y) * (p.y - q.y) + double(p.z - q.z) * (p.z - q.z));
    };
    for (size_t t = 0; t < count; t += std::max<size_t>(1, count / 256), ++sampled) {
        const auto& tri = m.triangles[t];
        edges += (length(tri.a, tri.b) + length(tri.b, tri.c) + length(tri.c, tri.a)) / 3.0;
    }
    const float distance = std::max(std::sqrt((centre.x - eye.x) * (centre.x - eye.x) + (centre.y - eye.y) * (centre.y - eye.y) +
                                              (centre.z - eye.z) * (centre.z - eye.z)) - radius,
                                    std::max(radius * 0.01f, 1e-6f));
    const double pixel = double(distance) * angle;
    const double edgePixels = (edges / double(std::max<size_t>(sampled, 1))) / pixel;
    // As many quarterings of its triangles as its edges are halvings under two pixels.
    const int quarters = int(std::floor(std::log2(2.0 / std::max(edgePixels, 1e-9))));
    if (quarters < 1) return nullptr;
    const size_t target = std::max<size_t>(256, count >> (2 * std::min(quarters, 20)));
    const float error = float(std::min(1.0, 2.0 / std::max(2.0 * radius / pixel, 1e-9)));
    // Each triangle corner a vertex, the same ones made one: a vertex parts where its normal or texture coordinates part.
    const bool normals = m.normalRate != shade::RateNone && !m.normals.empty(), uvs = m.uvRate != shade::RateNone && !m.uvs.empty();
    const size_t corners = count * 3;
    struct Corner {
        float p[3], n[3], uv[2];
    };
    std::vector<Corner> corner(corners);
    for (size_t t = 0; t < count; ++t) {
        const unsigned v[3] = {m.triangles[t].a, m.triangles[t].b, m.triangles[t].c};
        for (int k = 0; k < 3; ++k) {
            Corner& c = corner[t * 3 + k];
            const auto& p = m.positions[v[k]];
            c.p[0] = p.x, c.p[1] = p.y, c.p[2] = p.z;
            const size_t ni = m.normalRate == shade::RateVertex ? v[k] : t * 3 + k;
            if (normals && ni < m.normals.size()) c.n[0] = m.normals[ni].x, c.n[1] = m.normals[ni].y, c.n[2] = m.normals[ni].z;
            else c.n[0] = c.n[1] = c.n[2] = 0.0f;
            const size_t ui = m.uvRate == shade::RateVertex ? v[k] : t * 3 + k;
            if (uvs && 2 * ui + 1 < m.uvs.size()) c.uv[0] = m.uvs[2 * ui], c.uv[1] = m.uvs[2 * ui + 1];
            else c.uv[0] = c.uv[1] = 0.0f;
        }
    }
    std::vector<unsigned> remap(corners);
    const size_t unique = meshopt_generateVertexRemap(remap.data(), nullptr, corners, corner.data(), corners, sizeof(Corner));
    std::vector<Corner> vertex(unique);
    for (size_t c = 0; c < corners; ++c) vertex[remap[c]] = corner[c];
    std::vector<float> position(unique * 3), attribute(unique * 5);
    for (size_t u = 0; u < unique; ++u) {
        std::memcpy(&position[u * 3], vertex[u].p, 12);
        std::memcpy(&attribute[u * 5], vertex[u].n, 12);
        std::memcpy(&attribute[u * 5 + 3], vertex[u].uv, 8);
    }
    const float weights[5] = {normals ? 0.5f : 0.0f, normals ? 0.5f : 0.0f, normals ? 0.5f : 0.0f, uvs ? 1.0f : 0.0f, uvs ? 1.0f : 0.0f};
    std::vector<unsigned> kept(corners);
    float reached = 0.0f;
    const size_t made = meshopt_simplifyWithAttributes(kept.data(), remap.data(), corners, position.data(), unique, 12, attribute.data(), 20,
                                                       weights, 5, nullptr, target * 3, error, meshopt_SimplifyLockBorder, &reached);
    if (!made || made >= corners) return nullptr;
    auto out = std::make_shared<MeshData>(m);
    std::vector<unsigned> placed(unique, ~0u);
    out->positions.clear();
    out->normals.clear();
    out->uvs.clear();
    out->triangles.resize(made / 3);
    for (size_t c = 0; c < made; ++c) {
        unsigned& to = placed[kept[c]];
        if (to == ~0u) {
            to = unsigned(out->positions.size());
            const Corner& v = vertex[kept[c]];
            out->positions.push_back({v.p[0], v.p[1], v.p[2]});
            if (normals) out->normals.push_back({v.n[0], v.n[1], v.n[2]});
            if (uvs) out->uvs.insert(out->uvs.end(), {v.uv[0], v.uv[1]});
        }
        unsigned* corners3 = &out->triangles[c / 3].a;
        corners3[c % 3] = to;
    }
    out->normalRate = normals ? shade::RateVertex : shade::RateNone;
    out->uvRate = uvs ? shade::RateVertex : shade::RateNone;
    out->normals1.clear();
    out->coarse = true;
    return out;
}

}  // namespace xpu2::interactive::cpu
