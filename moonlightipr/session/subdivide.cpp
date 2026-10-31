// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
#include "subdivide.h"

#include <algorithm>
#include <stdexcept>
#include <unordered_map>

namespace moonlightipr {
namespace {

struct Edge {
    uint32_t a, b;                  // vertices, a < b
    uint32_t faces[2] = {0, 0};     // the faces either side
    uint32_t faceCount = 0;
    float sharpness = 0.0f;
};

uint64_t edgeKey(uint32_t a, uint32_t b) {
    return (uint64_t(std::min(a, b)) << 32) | std::max(a, b);
}

void add(float* out, const float* in, float weight = 1.0f) {
    for (int k = 0; k < 3; ++k) out[k] += in[k] * weight;
}

// One round of a texture coordinate set, to the quads' corners: Catmull-Clark over the set's own mesh, where a corner's
// vertex is its mesh vertex and its coordinates together, so that a seam is an open edge of it. As MoonRay's default
// (subd_fvar_linear "corners only", OpenSubdiv's): the coordinates move as the surface does, and only a corner of a
// piece of the map stays put. Carried across each face linearly they stayed as the surface moved inward: a texture
// stretched on a coarse cage, a bottle's cork.
void refineUvs(const Cage& cage, const std::vector<uint32_t>& faceStart, const std::vector<uint32_t>& cornerEdge,
               const std::vector<Edge>& meshEdges, const std::vector<float>& uv, std::vector<float>& out) {
    const size_t faceCount = cage.faceSizes.size(), cornerCount = cage.corners.size();
    // The set's vertices: a mesh vertex's corners with the same coordinates are one.
    const size_t meshVertices = cage.positions.size() / 3;
    std::vector<uint32_t> head(meshVertices, UINT32_MAX), next, vertexOf(cornerCount);
    std::vector<float> values;
    values.reserve(cornerCount);
    next.reserve(cornerCount);
    for (size_t c = 0; c < cornerCount; ++c) {
        const float u = uv[c * 2], v = uv[c * 2 + 1];
        uint32_t found = head[cage.corners[c]];
        while (found != UINT32_MAX && (values[size_t(found) * 2] != u || values[size_t(found) * 2 + 1] != v)) found = next[found];
        if (found == UINT32_MAX) {
            found = uint32_t(next.size());
            next.push_back(head[cage.corners[c]]);
            head[cage.corners[c]] = found;
            values.push_back(u);
            values.push_back(v);
        }
        vertexOf[c] = found;
    }
    const size_t count = next.size();
    // Its edges: a mesh edge whose two faces agree on the coordinates at both ends is one, else one each.
    std::vector<Edge> edges;
    edges.reserve(meshEdges.size());
    std::vector<uint32_t> firstOf(meshEdges.size(), UINT32_MAX), edgeOf(cornerCount);
    for (size_t f = 0; f < faceCount; ++f) {
        const uint32_t size = cage.faceSizes[f], start = faceStart[f];
        for (uint32_t i = 0; i < size; ++i) {
            const uint32_t a = vertexOf[start + i], b = vertexOf[start + (i + 1) % size], low = std::min(a, b), high = std::max(a, b);
            const uint32_t mesh = cornerEdge[start + i];
            uint32_t id = firstOf[mesh];
            if (id == UINT32_MAX || edges[id].a != low || edges[id].b != high) {
                const uint32_t made = uint32_t(edges.size());
                edges.push_back({low, high});
                edges.back().sharpness = meshEdges[mesh].sharpness;
                if (id == UINT32_MAX) firstOf[mesh] = made;
                id = made;
            }
            Edge& edge = edges[id];
            if (edge.faceCount < 2) edge.faces[edge.faceCount] = uint32_t(f);
            ++edge.faceCount;
            edgeOf[start + i] = id;
        }
    }
    // Face points, edge points and moved vertices, by the rule refine has for the positions.
    std::vector<float> facePoints(faceCount * 2, 0.0f), edgePoints(edges.size() * 2, 0.0f), moved(count * 2, 0.0f);
    std::vector<float> faceSum(count * 2, 0.0f), edgeSum(count * 2, 0.0f), sharpSum(count * 2, 0.0f), sharpTotal(count, 0.0f);
    std::vector<uint32_t> faceTouch(count, 0), edgeTouch(count, 0), sharpTouch(count, 0);
    for (size_t f = 0; f < faceCount; ++f) {
        const uint32_t size = cage.faceSizes[f], start = faceStart[f];
        for (uint32_t i = 0; i < size; ++i) {
            const uint32_t w = vertexOf[start + i];
            for (int k = 0; k < 2; ++k) facePoints[f * 2 + k] += values[size_t(w) * 2 + k] / size;
        }
        for (uint32_t i = 0; i < size; ++i) {
            const uint32_t w = vertexOf[start + i];
            for (int k = 0; k < 2; ++k) faceSum[size_t(w) * 2 + k] += facePoints[f * 2 + k];
            ++faceTouch[w];
        }
    }
    for (size_t e = 0; e < edges.size(); ++e) {
        const Edge& edge = edges[e];
        const bool open = edge.faceCount != 2;
        const float sharp = open ? 1.0f : std::min(edge.sharpness, 1.0f);
        for (int k = 0; k < 2; ++k) {
            const float middle = 0.5f * (values[size_t(edge.a) * 2 + k] + values[size_t(edge.b) * 2 + k]);
            const float smooth = open ? 0.0f : 0.5f * middle + 0.25f * (facePoints[size_t(edge.faces[0]) * 2 + k] + facePoints[size_t(edge.faces[1]) * 2 + k]);
            edgePoints[e * 2 + k] = sharp * middle + (1.0f - sharp) * smooth;
            edgeSum[size_t(edge.a) * 2 + k] += middle;
            edgeSum[size_t(edge.b) * 2 + k] += middle;
            if (open || edge.sharpness > 0.0f) {
                sharpSum[size_t(edge.a) * 2 + k] += values[size_t(edge.b) * 2 + k];
                sharpSum[size_t(edge.b) * 2 + k] += values[size_t(edge.a) * 2 + k];
            }
        }
        for (uint32_t w : {edge.a, edge.b}) {
            ++edgeTouch[w];
            if (open || edge.sharpness > 0.0f) {
                ++sharpTouch[w];
                sharpTotal[w] += sharp;
            }
        }
    }
    for (size_t w = 0; w < count; ++w) {
        const float n = float(edgeTouch[w]);
        for (int k = 0; k < 2; ++k) {
            const float p = values[w * 2 + k];
            if (!edgeTouch[w] || !faceTouch[w]) { moved[w * 2 + k] = p; continue; }
            const float smooth = faceSum[w * 2 + k] / (faceTouch[w] * n) + edgeSum[w * 2 + k] * 2.0f / (n * n) + p * (n - 3.0f) / n;
            if (sharpTouch[w] < 2) { moved[w * 2 + k] = smooth; continue; }
            const bool corner = sharpTouch[w] > 2 || (edgeTouch[w] == 2 && faceTouch[w] == 1);
            const float crease = corner ? p : 0.75f * p + 0.125f * sharpSum[w * 2 + k];
            const float sharp = std::min(sharpTotal[w] / sharpTouch[w], 1.0f);
            moved[w * 2 + k] = sharp * crease + (1.0f - sharp) * smooth;
        }
    }
    for (size_t f = 0; f < faceCount; ++f) {
        const uint32_t size = cage.faceSizes[f], start = faceStart[f];
        for (uint32_t i = 0; i < size; ++i) {
            const uint32_t previous = (i + size - 1) % size;
            float* to = &out[(size_t(start) + i) * 8];
            for (int k = 0; k < 2; ++k) {
                to[k] = moved[size_t(vertexOf[start + i]) * 2 + k];
                to[2 + k] = edgePoints[size_t(edgeOf[start + i]) * 2 + k];
                to[4 + k] = facePoints[f * 2 + k];
                to[6 + k] = edgePoints[size_t(edgeOf[start + previous]) * 2 + k];
            }
        }
    }
}

// One round: every face becomes one quad per corner.
Cage refine(const Cage& cage) {
    const size_t vertexCount = cage.positions.size() / 3, faceCount = cage.faceSizes.size();
    std::vector<uint32_t> faceStart(faceCount + 1, 0);
    for (size_t f = 0; f < faceCount; ++f) faceStart[f + 1] = faceStart[f] + cage.faceSizes[f];

    // Edges, the faces beside each, and how sharp each is.
    std::unordered_map<uint64_t, uint32_t> edgeOf;
    edgeOf.reserve(cage.corners.size());
    std::vector<Edge> edges;
    std::vector<uint32_t> cornerEdge(cage.corners.size());
    for (size_t f = 0; f < faceCount; ++f) {
        const uint32_t size = cage.faceSizes[f];
        for (uint32_t i = 0; i < size; ++i) {
            const uint32_t a = cage.corners[faceStart[f] + i], b = cage.corners[faceStart[f] + (i + 1) % size];
            auto found = edgeOf.find(edgeKey(a, b));
            if (found == edgeOf.end()) {
                found = edgeOf.emplace(edgeKey(a, b), uint32_t(edges.size())).first;
                edges.push_back({std::min(a, b), std::max(a, b)});
            }
            Edge& edge = edges[found->second];
            if (edge.faceCount < 2) edge.faces[edge.faceCount] = uint32_t(f);
            ++edge.faceCount;
            cornerEdge[faceStart[f] + i] = found->second;
        }
    }
    for (size_t c = 0; c < cage.creaseSharpness.size(); ++c) {
        const auto found = edgeOf.find(edgeKey(cage.creaseEdges[c * 2], cage.creaseEdges[c * 2 + 1]));
        if (found != edgeOf.end()) edges[found->second].sharpness = std::max(edges[found->second].sharpness, cage.creaseSharpness[c]);
    }

    Cage out;
    const size_t edgeCount = edges.size();
    // New vertices: the old ones moved, then one per edge, then one per face.
    out.positions.assign((vertexCount + edgeCount + faceCount) * 3, 0.0f);
    float* moved = out.positions.data();
    float* edgePoints = moved + vertexCount * 3;
    float* facePoints = edgePoints + edgeCount * 3;
    for (size_t f = 0; f < faceCount; ++f)
        for (uint32_t i = 0; i < cage.faceSizes[f]; ++i)
            add(facePoints + f * 3, &cage.positions[cage.corners[faceStart[f] + i] * 3], 1.0f / cage.faceSizes[f]);

    // What each vertex gathers for its own rule.
    std::vector<float> faceSum(vertexCount * 3, 0.0f), edgeSum(vertexCount * 3, 0.0f), sharpSum(vertexCount * 3, 0.0f);
    std::vector<uint32_t> faceTouch(vertexCount, 0), edgeTouch(vertexCount, 0), sharpTouch(vertexCount, 0);
    std::vector<float> sharpTotal(vertexCount, 0.0f);
    for (size_t f = 0; f < faceCount; ++f)
        for (uint32_t i = 0; i < cage.faceSizes[f]; ++i) {
            const uint32_t v = cage.corners[faceStart[f] + i];
            add(&faceSum[v * 3], facePoints + f * 3);
            ++faceTouch[v];
        }
    for (size_t e = 0; e < edgeCount; ++e) {
        const Edge& edge = edges[e];
        const float* a = &cage.positions[edge.a * 3];
        const float* b = &cage.positions[edge.b * 3];
        float middle[3] = {0, 0, 0}, smooth[3] = {0, 0, 0};
        add(middle, a, 0.5f);
        add(middle, b, 0.5f);
        // An open edge is as sharp as an edge gets.
        const bool open = edge.faceCount != 2;
        const float sharp = open ? 1.0f : std::min(edge.sharpness, 1.0f);
        if (!open) {
            add(smooth, middle, 0.5f);
            add(smooth, facePoints + edge.faces[0] * 3, 0.25f);
            add(smooth, facePoints + edge.faces[1] * 3, 0.25f);
        }
        add(edgePoints + e * 3, middle, sharp);
        add(edgePoints + e * 3, smooth, 1.0f - sharp);
        for (uint32_t v : {edge.a, edge.b}) {
            add(&edgeSum[v * 3], middle);
            ++edgeTouch[v];
            if (open || edge.sharpness > 0.0f) {
                add(&sharpSum[v * 3], v == edge.a ? b : a);
                ++sharpTouch[v];
                sharpTotal[v] += open ? 1.0f : std::min(edge.sharpness, 1.0f);
            }
        }
    }
    for (size_t v = 0; v < vertexCount; ++v) {
        const float* p = &cage.positions[v * 3];
        float* q = moved + v * 3;
        const float n = float(edgeTouch[v]);
        if (!edgeTouch[v] || !faceTouch[v]) { add(q, p); continue; }    // not part of any face
        float smooth[3] = {0, 0, 0};
        add(smooth, &faceSum[v * 3], 1.0f / (faceTouch[v] * n));
        add(smooth, &edgeSum[v * 3], 2.0f / (n * n));
        add(smooth, p, (n - 3.0f) / n);
        if (sharpTouch[v] < 2) { add(q, smooth); continue; }
        // The end of an open mesh's corner, or where three or more sharp edges meet, stays put.
        const bool corner = sharpTouch[v] > 2 || (edgeTouch[v] == 2 && faceTouch[v] == 1);
        float crease[3] = {0, 0, 0};
        if (corner) add(crease, p);
        else {
            add(crease, p, 0.75f);
            add(crease, &sharpSum[v * 3], 0.125f);
        }
        // A crease that is fading blends towards the smooth position.
        const float sharp = std::min(sharpTotal[v] / sharpTouch[v], 1.0f);
        add(q, crease, sharp);
        add(q, smooth, 1.0f - sharp);
    }

    // The new quads, and what rides on their corners.
    out.faceSizes.assign(cage.corners.size(), 4);
    out.corners.resize(cage.corners.size() * 4);
    if (!cage.faceMaterials.empty()) out.faceMaterials.resize(cage.corners.size());
    out.uvSets.assign(cage.uvSets.size(), std::vector<float>(cage.corners.size() * 8));
    for (size_t f = 0; f < faceCount; ++f) {
        const uint32_t size = cage.faceSizes[f], start = faceStart[f];
        for (uint32_t i = 0; i < size; ++i) {
            const uint32_t previous = (i + size - 1) % size, quad = start + i;
            uint32_t* corner = &out.corners[size_t(quad) * 4];
            corner[0] = cage.corners[start + i];
            corner[1] = uint32_t(vertexCount) + cornerEdge[start + i];
            corner[2] = uint32_t(vertexCount + edgeCount + f);
            corner[3] = uint32_t(vertexCount) + cornerEdge[start + previous];
            if (!cage.faceMaterials.empty()) out.faceMaterials[quad] = cage.faceMaterials[f];
        }
    }
    for (size_t s = 0; s < cage.uvSets.size(); ++s) refineUvs(cage, faceStart, cornerEdge, edges, cage.uvSets[s], out.uvSets[s]);
    // Each half of a creased edge is one level less sharp.
    for (size_t e = 0; e < edgeCount; ++e) {
        if (edges[e].sharpness <= 1.0f) continue;
        for (uint32_t end : {edges[e].a, edges[e].b}) {
            out.creaseEdges.push_back(end);
            out.creaseEdges.push_back(uint32_t(vertexCount + e));
            out.creaseSharpness.push_back(edges[e].sharpness - 1.0f);
        }
    }
    return out;
}

}

Triangles subdivide(Cage cage, uint32_t levels) {
    const size_t vertexCount = cage.positions.size() / 3;
    size_t total = 0;
    for (uint32_t size : cage.faceSizes) {
        if (size < 3) throw std::runtime_error("MoonLightIPR subdivision cage has a face with fewer than three corners");
        total += size;
    }
    if (total != cage.corners.size() || cage.creaseEdges.size() != cage.creaseSharpness.size() * 2
        || (!cage.faceMaterials.empty() && cage.faceMaterials.size() != cage.faceSizes.size()))
        throw std::runtime_error("MoonLightIPR subdivision cage lists do not agree");
    for (uint32_t corner : cage.corners)
        if (corner >= vertexCount) throw std::runtime_error("MoonLightIPR subdivision cage index is out of range");
    for (uint32_t end : cage.creaseEdges)
        if (end >= vertexCount) throw std::runtime_error("MoonLightIPR subdivision crease index is out of range");
    for (const std::vector<float>& set : cage.uvSets)
        if (set.size() != cage.corners.size() * 2) throw std::runtime_error("MoonLightIPR subdivision cage coordinates do not match its corners");

    for (uint32_t level = 0; level < levels; ++level) cage = refine(cage);

    // Fans, which for the quads every round leaves are two triangles each.
    Triangles out;
    out.positions = std::move(cage.positions);
    out.uvSets.resize(cage.uvSets.size());
    size_t start = 0;
    for (size_t f = 0; f < cage.faceSizes.size(); ++f) {
        const uint32_t size = cage.faceSizes[f];
        for (uint32_t i = 1; i + 1 < size; ++i) {
            for (uint32_t corner : {uint32_t(0), i, i + 1}) {
                out.indices.push_back(cage.corners[start + corner]);
                for (size_t s = 0; s < cage.uvSets.size(); ++s) {
                    out.uvSets[s].push_back(cage.uvSets[s][(start + corner) * 2]);
                    out.uvSets[s].push_back(cage.uvSets[s][(start + corner) * 2 + 1]);
                }
            }
            if (!cage.faceMaterials.empty()) out.materialIds.push_back(cage.faceMaterials[f]);
        }
        start += size;
    }
    return out;
}

Triangles split(Triangles mesh, uint32_t levels) {
    for (uint32_t level = 0; level < levels; ++level) {
        const size_t triangles = mesh.indices.size() / 3;
        std::unordered_map<uint64_t, uint32_t> middles;
        auto middle = [&](uint32_t a, uint32_t b) {
            const uint64_t key = (uint64_t(std::min(a, b)) << 32) | std::max(a, b);
            auto found = middles.find(key);
            if (found != middles.end()) return found->second;
            const uint32_t made = uint32_t(mesh.positions.size() / 3);
            for (int axis = 0; axis < 3; ++axis)
                mesh.positions.push_back(0.5f * (mesh.positions[size_t(a) * 3 + axis] + mesh.positions[size_t(b) * 3 + axis]));
            middles.emplace(key, made);
            return made;
        };
        std::vector<uint32_t> indices;
        indices.reserve(triangles * 12);
        std::vector<uint32_t> materials;
        if (!mesh.materialIds.empty()) materials.reserve(triangles * 4);
        std::vector<std::vector<float>> sets(mesh.uvSets.size());
        for (std::vector<float>& set : sets) set.reserve(triangles * 24);
        for (size_t t = 0; t < triangles; ++t) {
            const uint32_t a = mesh.indices[t * 3], b = mesh.indices[t * 3 + 1], c = mesh.indices[t * 3 + 2];
            const uint32_t ab = middle(a, b), bc = middle(b, c), ca = middle(c, a);
            const uint32_t children[12] = {a, ab, ca, ab, b, bc, ca, bc, c, ab, bc, ca};
            indices.insert(indices.end(), children, children + 12);
            if (!mesh.materialIds.empty()) materials.insert(materials.end(), 4, mesh.materialIds[t]);
            for (size_t s = 0; s < sets.size(); ++s) {
                const float* uv = &mesh.uvSets[s][t * 6];
                const float ua[2] = {uv[0], uv[1]}, ub[2] = {uv[2], uv[3]}, uc[2] = {uv[4], uv[5]};
                const float uab[2] = {0.5f * (ua[0] + ub[0]), 0.5f * (ua[1] + ub[1])}, ubc[2] = {0.5f * (ub[0] + uc[0]), 0.5f * (ub[1] + uc[1])},
                            uca[2] = {0.5f * (uc[0] + ua[0]), 0.5f * (uc[1] + ua[1])};
                const float* corners[12] = {ua, uab, uca, uab, ub, ubc, uca, ubc, uc, uab, ubc, uca};
                for (const float* corner : corners) sets[s].insert(sets[s].end(), corner, corner + 2);
            }
        }
        mesh.indices = std::move(indices);
        mesh.materialIds = std::move(materials);
        mesh.uvSets = std::move(sets);
    }
    return mesh;
}

}
