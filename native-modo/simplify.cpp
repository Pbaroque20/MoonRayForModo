// A dense mesh made lighter for a realtime preview (the plugin's simplify.py), by meshoptimizer's simplifier: fewer
// triangles where the mesh is small on screen, within an error the preview cannot show. Its normals, texture
// coordinates and materials are kept as they are where they part (seams), its open edges where they are (so that parts
// which meet do not open), and its shading normals are the full mesh's: as far as the preview shows, the same surface.
#include <meshoptimizer.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

namespace {
struct Corner {
    float position[3], normal[3], moved[3];
};
}

// positions: vertexCount points (3 floats); indices: 3 a triangle; normals: a normal a vertex (3 floats), or none, when a
// smooth mesh's are worked out here from its faces (area-weighted, as the session works them out); moved: where each
// vertex is as the shutter closes, or none; uvs: uvSets sets one after another, each 2 floats a triangle corner;
// materials: one a triangle, or none. targetTriangles and targetError (relative to the mesh's size, meshoptimizer's
// measure) bound the simplification. The outputs are as large as the inputs could make them: at most 3 vertices a
// triangle and triangleCount triangles; outUvs holds each set at a stride of 3 * triangleCount corners. Returns the
// triangles made, -1 where the mesh cannot be read; outVertexCount the vertices, outError the error reached. outNormals
// is written where the mesh has normals or is smooth.
extern "C" __declspec(dllexport) int MR_simplify(const float* positions, uint32_t vertexCount, const uint32_t* indices, uint32_t triangleCount,
                                                 const float* normals, const float* moved, const float* uvs, uint32_t uvSets,
                                                 const uint32_t* materials, int smooth, uint32_t targetTriangles, float targetError,
                                                 float* outPositions, float* outNormals, float* outMoved, uint32_t* outIndices,
                                                 float* outUvs, uint32_t* outMaterials, uint32_t* outVertexCount, float* outError) {
    if (!positions || !indices || !triangleCount || uvSets > 8) return -1;
    const size_t corners = size_t(triangleCount) * 3;
    for (size_t c = 0; c < corners; ++c)
        if (indices[c] >= vertexCount) return -1;
    // A smooth mesh with no normals of its own: its vertices' normals, from the faces around them, weighted by area.
    std::vector<float> smoothNormals;
    const bool withNormals = normals || smooth;
    if (!normals && smooth) {
        smoothNormals.assign(size_t(vertexCount) * 3, 0.0f);
        for (size_t t = 0; t < triangleCount; ++t) {
            const float* a = positions + 3 * indices[3 * t];
            const float* b = positions + 3 * indices[3 * t + 1];
            const float* c = positions + 3 * indices[3 * t + 2];
            const float e[3] = {b[0] - a[0], b[1] - a[1], b[2] - a[2]}, f[3] = {c[0] - a[0], c[1] - a[1], c[2] - a[2]};
            const float n[3] = {e[1] * f[2] - e[2] * f[1], e[2] * f[0] - e[0] * f[2], e[0] * f[1] - e[1] * f[0]};
            for (int k = 0; k < 3; ++k)
                for (int i = 0; i < 3; ++i) smoothNormals[3 * indices[3 * t + k] + i] += n[i];
        }
        for (size_t v = 0; v < vertexCount; ++v) {
            float* n = &smoothNormals[3 * v];
            const float length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
            if (length > 0) for (int i = 0; i < 3; ++i) n[i] /= length;
        }
        normals = smoothNormals.data();
    }
    // Each corner as a vertex of its own, then the same ones made one (meshoptimizer's remap): a vertex parts where its
    // normal, texture coordinates or material part.
    std::vector<Corner> corner(corners);
    std::vector<float> cornerUvs(corners * uvSets * 2);
    std::vector<uint32_t> cornerMaterial(corners, 0);
    for (size_t c = 0; c < corners; ++c) {
        const uint32_t v = indices[c];
        std::memcpy(corner[c].position, positions + 3 * size_t(v), 12);
        if (normals) std::memcpy(corner[c].normal, normals + 3 * size_t(v), 12);
        else std::memset(corner[c].normal, 0, 12);
        if (moved) std::memcpy(corner[c].moved, moved + 3 * size_t(v), 12);
        else std::memset(corner[c].moved, 0, 12);
        for (uint32_t s = 0; s < uvSets; ++s) {
            cornerUvs[c * uvSets * 2 + s * 2] = uvs[size_t(s) * corners * 2 + c * 2];
            cornerUvs[c * uvSets * 2 + s * 2 + 1] = uvs[size_t(s) * corners * 2 + c * 2 + 1];
        }
        if (materials) cornerMaterial[c] = materials[c / 3];
    }
    std::vector<meshopt_Stream> streams = {{corner.data(), sizeof(Corner), sizeof(Corner)},
                                           {cornerMaterial.data(), 4, 4}};
    if (uvSets) streams.push_back({cornerUvs.data(), uvSets * 8, uvSets * 8});
    std::vector<uint32_t> remap(corners);
    const size_t unique = meshopt_generateVertexRemapMulti(remap.data(), nullptr, corners, corners, streams.data(), streams.size());
    std::vector<float> position(unique * 3);
    const size_t attributes = (normals ? 3 : 0) + size_t(uvSets) * 2;
    std::vector<float> attribute(std::max<size_t>(1, unique * attributes));
    std::vector<Corner> held(unique);
    std::vector<uint32_t> material(unique);
    std::vector<uint32_t> welded(corners);
    for (size_t c = 0; c < corners; ++c) {
        const uint32_t u = remap[c];
        welded[c] = u;
        held[u] = corner[c];
        material[u] = cornerMaterial[c];
        std::memcpy(&position[3 * size_t(u)], corner[c].position, 12);
        float* to = &attribute[size_t(u) * attributes];
        if (normals) std::memcpy(to, corner[c].normal, 12), to += 3;
        for (uint32_t s = 0; s < uvSets * 2; ++s) to[s] = cornerUvs[c * uvSets * 2 + s];
    }
    // Normals a little less than texture coordinates: a normal's change shows as shading, a coordinate's as the texture moving.
    std::vector<float> weights(std::max<size_t>(1, attributes), 1.0f);
    if (normals) weights[0] = weights[1] = weights[2] = 0.5f;
    std::vector<uint32_t> simplified(corners);
    float error = 0.0f;
    const size_t kept = attributes
        ? meshopt_simplifyWithAttributes(simplified.data(), welded.data(), corners, position.data(), unique, 12, attribute.data(),
                                         attributes * 4, weights.data(), attributes, nullptr, size_t(targetTriangles) * 3, targetError,
                                         meshopt_SimplifyLockBorder, &error)
        : meshopt_simplify(simplified.data(), welded.data(), corners, position.data(), unique, 12, size_t(targetTriangles) * 3, targetError,
                           meshopt_SimplifyLockBorder, &error);
    // Only the vertices the triangles left use, in the order they are first used.
    std::vector<uint32_t> placed(unique, ~0u);
    uint32_t count = 0;
    const size_t triangles = kept / 3;
    for (size_t c = 0; c < kept; ++c) {
        const uint32_t u = simplified[c];
        if (placed[u] == ~0u) {
            placed[u] = count;
            std::memcpy(outPositions + 3 * size_t(count), held[u].position, 12);
            if (withNormals && outNormals) std::memcpy(outNormals + 3 * size_t(count), held[u].normal, 12);
            if (moved && outMoved) std::memcpy(outMoved + 3 * size_t(count), held[u].moved, 12);
            ++count;
        }
        outIndices[c] = placed[u];
    }
    // Each triangle corner's texture coordinates, and each triangle's material (its first corner's: a triangle's corners
    // share it, materials parting the mesh where they change).
    for (size_t c = 0; c < kept; ++c) {
        const float* from = &attribute[size_t(simplified[c]) * attributes + (normals ? 3 : 0)];
        for (uint32_t s = 0; s < uvSets; ++s) {
            outUvs[size_t(s) * corners * 2 + c * 2] = from[s * 2];
            outUvs[size_t(s) * corners * 2 + c * 2 + 1] = from[s * 2 + 1];
        }
    }
    if (materials && outMaterials)
        for (size_t t = 0; t < triangles; ++t) outMaterials[t] = material[simplified[3 * t]];
    if (outVertexCount) *outVertexCount = count;
    if (outError) *outError = error;
    return int(triangles);
}
