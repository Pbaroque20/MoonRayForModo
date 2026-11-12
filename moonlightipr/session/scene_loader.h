#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// Applies packed scene files (written by moonray_modo/moonlightipr_scene.py) to a Renderer.
#include "moonlightipr/moonlightipr.h"

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace moonlightipr {

struct SceneSettings {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t targetSamples = 0;
    bool denoise = false;
    bool flatOut = false;   // every sample everywhere, as fast as the graphics card can: not paced, no rest once clean
};

class SceneLoader {
public:
    explicit SceneLoader(Renderer& renderer) : renderer(renderer) {}

    // Meshes are keyed by content, so a file may omit the data of one already loaded and
    // an unchanged mesh keeps its acceleration structure. Images are named by path and
    // read once. Throws std::runtime_error.
    SceneSettings apply(const std::string& path);

private:
    struct CachedMesh {
        uint32_t index;
        uint64_t lastUsed;
    };
    Renderer& renderer;
    std::unordered_map<uint64_t, CachedMesh> meshes;
    std::unordered_map<uint64_t, CachedMesh> textures;  // the same bookkeeping, for images
    std::unordered_map<uint64_t, CachedMesh> grids;     // and for the grids of densities fogs have
    // The environment is rebuilt only when its part of the scene changes; its image is kept
    // decoded because an intensity or rotation edit reuses it.
    uint64_t environmentHash = 0;
    // An image for what diffuse light sees, what the camera sees behind the scene, what reflections see and what
    // refractions see; parts showing the same image share it.
    static const int ENVIRONMENT_PARTS = 4;
    uint64_t environmentImageKey[ENVIRONMENT_PARTS] = {};
    uint32_t environmentImageWidth[ENVIRONMENT_PARTS] = {}, environmentImageHeight[ENVIRONMENT_PARTS] = {};
    std::shared_ptr<std::vector<float>> environmentImage[ENVIRONMENT_PARTS];   // RGB, top row first, centre column facing -Z
    uint64_t generation = 0;
};

}
