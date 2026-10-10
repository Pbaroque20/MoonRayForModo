#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// Catmull-Clark subdivision of a control cage, for meshes MoonRay renders as subdivision surfaces.
#include <cstdint>
#include <vector>

namespace moonlightipr {

// A polygon mesh: faces of any size, with data per face corner in face order.
struct Cage {
    std::vector<float> positions;                   // 3 per vertex
    std::vector<uint32_t> faceSizes;                // corners per face
    std::vector<uint32_t> corners;                  // vertex index per face corner
    std::vector<uint32_t> faceMaterials;            // per face, or empty
    std::vector<std::vector<float>> uvSets;         // each 2 per face corner
    // Creased edges: two vertex indices and a sharpness per crease. An edge stays sharp for as
    // many levels as its sharpness.
    std::vector<uint32_t> creaseEdges;
    std::vector<float> creaseSharpness;
};

// Triangles ready for the renderer.
struct Triangles {
    std::vector<float> positions;
    std::vector<uint32_t> indices;
    std::vector<uint32_t> materialIds;              // per triangle, or empty
    std::vector<std::vector<float>> uvSets;         // each 6 per triangle
};

// Subdivides levels times and splits the resulting quads. Open edges stay where they are and
// corners of an open mesh stay sharp, as MoonRay's default boundary rule has them. Texture
// coordinates are carried across each face linearly. Throws std::runtime_error on a cage whose
// lists do not agree.
Triangles subdivide(Cage cage, uint32_t levels);

}
