#pragma once
// Applies packed scene files (written by moonray_modo/moonlight_scene.py) to a Renderer.
#include "moonlight/moonlight.h"

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace moonlight {

struct SceneSettings {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t targetSamples = 0;
    bool denoise = false;
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
    // The environment is rebuilt only when its part of the scene changes; its image is kept
    // decoded because an intensity or rotation edit reuses it.
    uint64_t environmentHash = 0;
    // One image for what lights the scene and one for what the camera sees behind it.
    uint64_t environmentImageKey[2] = {0, 0};
    uint32_t environmentImageWidth[2] = {0, 0}, environmentImageHeight[2] = {0, 0};
    std::vector<float> environmentImage[2];     // RGB, top row first, centre column facing -Z
    uint64_t generation = 0;
};

}
