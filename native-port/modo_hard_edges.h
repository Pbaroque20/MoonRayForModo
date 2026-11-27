// Displaced hard edges (MOONRAY_MODO_DISPLACED_HARD_EDGES, tools/port_displaced_hard_edges.py).
//
// MoonRay's PolyMesh drops a displaced polygon mesh's own normals: it displaces each point once along the smooth normal
// of its faces (so the surface stays closed) and then smooths the shading normals over the displaced shape, so an edge
// the mesh had hard (Modo's smoothing angle, its corner normals) shades round. Modo keeps it hard. With the switch on
// (unset: on), the displacement is the same, and afterwards each face corner gets a shading normal of its own: where
// every face at a point agreed in the mesh as given, the point's normal as MoonRay makes it (bit for bit); where they
// did not, the normalized sum of the displaced faces' normals (PolyMeshCalcNv's, in its order) of the faces that
// agreed with this corner's. The edges shade sharp and stay closed.
//
// One copy of the rule for every engine that has it: MoonRay (geom/prim/ModoHardEdges.h, written from this file by the
// port tool) and XPU2's geometry library (xpu2/interactive/xpu2_geom.cc includes this file), so that the two make the
// same normals from the same faces.
#pragma once

#include <scene_rdl2/common/math/Vec2.h>
#include <scene_rdl2/common/math/Vec3.h>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace modo_hard_edges {

using V3 = scene_rdl2::math::Vec3f;
using V2 = scene_rdl2::math::Vec2f;

// Whether the switch is on: unless MOONRAY_MODO_DISPLACED_HARD_EDGES=0.
inline bool on()
{
    static const bool value = [] {
        const char* v = std::getenv("MOONRAY_MODO_DISPLACED_HARD_EDGES");
        return !v || v[0] != '0';
    }();
    return value;
}

// Two corners at a point belong to one smooth patch when their normals in the mesh as given are this close (under a
// degree apart): a smooth edge's two faces share the normals at its ends, a hard one's differ by the smoothing angle.
constexpr float Agree = 0.9999f;

// Each corner of the hit faces (faceCount of them, fvc corners each), its normal as given, from the base faces' corner
// normals (baseCorners, nb a base face): a tessellated face's corner at its place in its base face (faceVaryingUv),
// bilinear in a quad, (1 - u - v, u, v) in a triangle; an untessellated face's its own.
inline std::vector<V3> givenAtCorners(size_t faceCount, size_t fvc, bool tessellated, bool quadBase, const int* tessToBase,
                                      const V2* faceVaryingUv, const V3* baseCorners, size_t nb)
{
    std::vector<V3> keys(faceCount * fvc);
    for (size_t f = 0; f < faceCount; ++f) {
        const size_t b = tessellated ? size_t(tessToBase[f]) : f;
        const V3* n = baseCorners + b * nb;
        for (size_t c = 0; c < fvc; ++c) {
            V3 k;
            if (!tessellated) {
                k = n[c < nb ? c : nb - 1];
            } else {
                const V2 uv = faceVaryingUv[4 * f + c];
                if (quadBase) {
                    k = (1.0f - uv[0]) * (1.0f - uv[1]) * n[0] + uv[0] * (1.0f - uv[1]) * n[1] + uv[0] * uv[1] * n[2] +
                        (1.0f - uv[0]) * uv[1] * n[3];
                } else {
                    k = (1.0f - uv[0] - uv[1]) * n[0] + uv[0] * n[1] + uv[1] * n[2];
                }
            }
            const float l = scene_rdl2::math::dot(k, k);
            keys[f * fvc + c] = l > 0.0f && scene_rdl2::math::isfinite(l) ? k * (1.0f / scene_rdl2::math::sqrt(l)) : V3(0.0f);
        }
    }
    return keys;
}

// The shading normal of each corner (faceCount faces of fvc corners; steps time samples each, corner-major), or nothing
// where no point has faces that disagree (the mesh's shading is then the point normals as MoonRay made them).
// position(v, t): a vertex at a time step, as PolyMeshCalcNv reads it; pointNormal(v, t): the normal MoonRay gave it.
template <typename Position, typename PointNormal>
std::vector<V3> cornerNormals(size_t faceCount, size_t fvc, const uint32_t* indices, size_t vertexCount, size_t steps,
                              const std::vector<V3>& keys, Position position, PointNormal pointNormal)
{
    std::vector<V3> corners;
    if (keys.size() != faceCount * fvc || steps == 0) return corners;
    // Each point's corners, faces in order and each face's corners in order: PolyMeshCalcNv's vertex-to-face links.
    std::vector<uint32_t> first(vertexCount + 1, 0);
    for (size_t i = 0; i < faceCount * fvc; ++i)
        if (indices[i] < vertexCount) ++first[indices[i] + 1];
    for (size_t v = 0; v < vertexCount; ++v) first[v + 1] += first[v];
    std::vector<uint32_t> at(first.begin(), first.end() - 1), entries(first[vertexCount]);
    for (size_t i = 0; i < faceCount * fvc; ++i)
        if (indices[i] < vertexCount) entries[at[indices[i]]++] = uint32_t(i);
    // The faces' normals as PolyMeshCalcNv computes them: a quad's diagonals crossed, a triangle's edges.
    auto faceNormal = [&](size_t f, size_t t) {
        const uint32_t* q = indices + f * fvc;
        const V3 p0 = position(q[0], t), p1 = position(q[1], t), p2 = position(q[2], t);
        if (fvc == 4) return scene_rdl2::math::cross(p2 - p0, position(q[3], t) - p1);
        return scene_rdl2::math::cross(p1 - p0, p2 - p0);
    };
    std::vector<uint32_t> label;
    for (size_t v = 0; v < vertexCount; ++v) {
        const uint32_t begin = first[v], end = first[v + 1];
        if (end - begin < 2) continue;
        // The corners' patches: each the first earlier corner's it agrees with, else a new one.
        label.assign(end - begin, 0);
        uint32_t patches = 0;
        for (uint32_t j = begin; j < end; ++j) {
            uint32_t found = ~0u;
            for (uint32_t i = begin; i < j && found == ~0u; ++i)
                if (scene_rdl2::math::dot(keys[entries[i]], keys[entries[j]]) >= Agree) found = label[i - begin];
            label[j - begin] = found == ~0u ? patches++ : found;
        }
        if (patches < 2) continue;
        if (corners.empty()) {
            corners.resize(faceCount * fvc * steps);
            for (size_t i = 0; i < faceCount * fvc; ++i)
                for (size_t t = 0; t < steps; ++t) corners[i * steps + t] = pointNormal(indices[i], t);
        }
        for (uint32_t j = begin; j < end; ++j)
            for (size_t t = 0; t < steps; ++t) {
                V3 sum(0.0f, 0.0f, 0.0f);
                for (uint32_t i = begin; i < end; ++i)
                    if (label[i - begin] == label[j - begin]) sum += faceNormal(entries[i] / fvc, t);
                V3 n = scene_rdl2::math::normalize(sum);
                // PolyMeshCalcNv's fixInvalid: a degenerate patch a valid normal.
                if (!scene_rdl2::math::isFinite(n)) n = V3(0, 0, 1);
                corners[size_t(entries[j]) * steps + t] = n;
            }
    }
    return corners;
}

// A face's corners turned over (Mesh::reverseOrientation reverses each face's corners), with their normals.
inline void reverseCorners(std::vector<V3>& corners, size_t fvc, size_t steps)
{
    if (corners.empty()) return;
    const size_t faces = corners.size() / (fvc * steps);
    for (size_t f = 0; f < faces; ++f)
        for (size_t c = 0; c < fvc / 2; ++c)
            for (size_t t = 0; t < steps; ++t) std::swap(corners[(f * fvc + c) * steps + t], corners[(f * fvc + fvc - 1 - c) * steps + t]);
}

// A corner's normal at a time (MoonRay's two-sample attribute rule: (1 - time) * first + time * second).
inline V3 at(const std::vector<V3>& corners, size_t corner, size_t steps, float time)
{
    if (steps < 2) return corners[corner * steps];
    return (1.0f - time) * corners[corner * steps] + time * corners[corner * steps + 1];
}

} // namespace modo_hard_edges
