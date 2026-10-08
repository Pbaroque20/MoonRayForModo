// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLight is not affiliated with DreamWorks Animation; see moonlight/NOTICE.md.
#include "subdivide.h"

#include <algorithm>
#include <stdexcept>
#include <unordered_map>

namespace moonlight {
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
            for (size_t s = 0; s < cage.uvSets.size(); ++s) {
                const float* uv = &cage.uvSets[s][size_t(start) * 2];
                float centre[2] = {0, 0};
                for (uint32_t k = 0; k < size; ++k) { centre[0] += uv[k * 2] / size; centre[1] += uv[k * 2 + 1] / size; }
                const uint32_t next = (i + 1) % size;
                float* to = &out.uvSets[s][size_t(quad) * 8];
                for (int k = 0; k < 2; ++k) {
                    to[k] = uv[i * 2 + k];
                    to[2 + k] = 0.5f * (uv[i * 2 + k] + uv[next * 2 + k]);
                    to[4 + k] = centre[k];
                    to[6 + k] = 0.5f * (uv[i * 2 + k] + uv[previous * 2 + k]);
                }
            }
        }
    }
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

}
