#pragma once
// MoonLightIPR: an approximate GPU preview path tracer for interactive rendering.
// It reads the scene MoonRay renders, flattened to triangle buffers, and shades it with one
// fixed uber-shader. Final frames always come from MoonRay.
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace moonlight {

// Parameters follow MoonRay's UsdPreviewSurface metallic workflow. These are the values each
// channel starts from; the material's layers then modify them.
struct Material {
    float baseColor[3] = {0.8f, 0.8f, 0.8f};
    float metallic = 0.0f;
    float roughness = 0.5f;
    float ior = 1.5f;
    float emission[3] = {0.0f, 0.0f, 0.0f};
    // Roughness used when dimming diffuse under the specular lobe: the surface roughness when
    // negative (UsdPreviewSurface), or a fixed value (DwaBaseMaterial's transmission roughness).
    float underRoughness = -1.0f;
    // The share of the light entering the surface that is refracted through it, its tint, the
    // roughness and index it is refracted with, and whether it is a thin sheet with no inside.
    float transmission = 0.0f;
    float transmissionColor[3] = {1.0f, 1.0f, 1.0f};
    float transmissionRoughness = 0.0f;
    float transmissionIor = 1.5f;
    bool thin = false;
    float clearcoat = 0.0f;
    float clearcoatRoughness = 0.01f;
    bool clearcoatDims = false;     // the coat takes its reflection out of the layers beneath
    float dissolve = 0.0f;          // 1 - presence: how much of the surface is absent
    float bumpStrength = 0.0f;      // height of a bump layer's full range, in scene units
    bool beckmann = false;          // Beckmann specular lobe (DwaBaseMaterial as the plugin sets it up) rather than GGX
    float baseColorAmount = 1.0f;   // multiplies the colour after its layers
    float emissionAmount = 1.0f;
    uint32_t layerStart = 0;        // this material's run in the layer list given to setMaterials
    uint32_t layerCount = 0;
};

// An image on the GPU. Pixels are RGBA, top row first: bytes, or floats when floatData is set.
struct TextureDesc {
    enum Wrap : uint32_t { Repeat = 0, Clamp = 1, Mirror = 2, Border = 3 };
    const void* pixels = nullptr;
    uint32_t width = 0;
    uint32_t height = 0;
    bool floatData = false;
    bool srgb = false;              // decode bytes from sRGB when sampling
    Wrap wrapU = Repeat;
    Wrap wrapV = Repeat;
};

// One row of a material's layer stack, blended over the rows before it. The channel, blend and
// flag numbers are those of the plugin's Shader Tree translation (see src/device/shared.h).
struct Layer {
    uint32_t channel = 0;
    uint32_t blend = 0;
    uint32_t flags = 0;
    int32_t texture = -1;           // from addTexture, or -1 for the constant
    uint32_t uvSlot = 0;            // which scene-wide set of texture coordinates the image uses
    float value[3] = {0, 0, 0};
    float opacity = 1.0f;
    float gain = 1.0f;              // applied to the value as value * gain + offset
    float offset = 0.0f;
};

// Buffers are copied; they need not outlive the call.
struct MeshDesc {
    const float* positions = nullptr;       // 3 floats per vertex
    const float* normals = nullptr;         // 3 floats per vertex, or null for faceted shading
    size_t vertexCount = 0;
    const uint32_t* indices = nullptr;      // 3 per triangle
    const uint32_t* materialIds = nullptr;  // 1 per triangle, or null to use the instance material
    size_t triangleCount = 0;
    // Sets of texture coordinates, each 2 floats per triangle corner (6 per triangle).
    const float* const* uvSets = nullptr;
    size_t uvSetCount = 0;
};

const uint32_t UV_SLOT_COUNT = 8;

struct Instance {
    uint32_t mesh = 0;
    uint32_t material = 0;
    // Row-major 3x4 object-to-world transform.
    float transform[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
};

// Latitude-longitude map, +Y up, first row at the zenith, with the centre column facing -Z.
struct Environment {
    const float* pixels = nullptr;  // 3 floats per pixel; null for a constant colour
    // What the camera sees behind the scene, same size as pixels; null to show the lighting.
    const float* background = nullptr;
    uint32_t width = 0;
    uint32_t height = 0;
    float color[3] = {1.0f, 1.0f, 1.0f};    // multiplies the map, or is the constant colour
    // The map's own axes in world space, as rows, for the lighting and for the background.
    float rotation[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    float backgroundRotation[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
};

// A uniform disc at infinity, as MoonRay's DistantLight.
struct DistantLight {
    float direction[3] = {0, 1, 0};     // from the scene towards the light
    float radiance[3] = {1, 1, 1};      // radiance of the disc, after any normalization
    float angularExtentDegrees = 0.5f;  // full angle of the disc
};

// A sphere, rectangle, disc or spot light, as MoonRay's lights of the same names. The flat
// kinds emit from one side, along direction. Sizes are in world units, after any scale.
struct Light {
    enum Kind : uint32_t { Sphere = 0, Rect = 1, Disk = 2, Spot = 3 };
    Kind kind = Sphere;
    float position[3] = {0, 0, 0};
    float axisX[3] = {1, 0, 0};         // in-plane direction of a rect's width
    float axisY[3] = {0, 1, 0};         // in-plane direction of a rect's height
    float direction[3] = {0, 0, -1};
    float width = 1.0f, height = 1.0f;  // rect
    float radius = 1.0f;                // sphere, disc, and a spot's lens
    float radiance[3] = {1, 1, 1};      // of the surface, after any normalization
    float outerConeDegrees = 60.0f;     // spot: full angle where the light ends
    float innerConeDegrees = 30.0f;     // spot: full angle where the falloff begins
};

struct Camera {
    float eye[3] = {0, 0, 5};
    float target[3] = {0, 0, 0};
    float up[3] = {0, 1, 0};
    float verticalFovDegrees = 40.0f;
};

// Every setter restarts accumulation. Errors are reported as std::runtime_error.
class Renderer {
public:
    // ptxPath is the device program built from src/device/kernel.cu.
    explicit Renderer(const std::string& ptxPath);
    ~Renderer();
    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;

    // Builds one acceleration structure per mesh; returns its index for Instance::mesh.
    uint32_t addMesh(const MeshDesc& mesh);
    // Frees a mesh no instance uses; its index may be handed out again.
    void removeMesh(uint32_t mesh);
    // Rebuilds only the instance layer, which is all a transform edit costs.
    void setInstances(const Instance* instances, size_t count);
    // Says which of a mesh's coordinate sets serves each scene-wide slot (-1 for none).
    void setMeshUvSlots(uint32_t mesh, const int32_t slots[UV_SLOT_COUNT]);
    uint32_t addTexture(const TextureDesc& texture);
    // Frees a texture no current material layer uses; its index may be handed out again.
    void removeTexture(uint32_t texture);
    void setMaterials(const Material* materials, size_t count, const Layer* layers = nullptr, size_t layerCount = 0);
    // Rewrites one entry in place.
    void setMaterial(uint32_t index, const Material& material);
    void setEnvironment(const Environment& environment);
    void setDistantLights(const DistantLight* lights, size_t count);
    void setLights(const Light* lights, size_t count);
    void setCamera(const Camera& camera);
    void resize(uint32_t width, uint32_t height);
    // Total bounces, and of those how many may leave a diffuse and a specular lobe, as
    // MoonRay's max_depth, max_diffuse_depth and max_glossy_depth.
    void setMaxDepth(uint32_t bounces, uint32_t diffuseBounces = 2, uint32_t glossyBounces = 2);

    // Adds one sample per pixel to the accumulated image.
    void render();
    uint32_t sampleCount() const;
    uint32_t width() const;
    uint32_t height() const;

    // Copies width * height linear RGB floats, first row at the bottom of the image.
    void readBeauty(float* rgb);
    // Same, after the OptiX denoiser guided by the albedo and normal buffers.
    void readDenoised(float* rgb);

    // Blocks until queued GPU work has finished; for timing.
    void synchronize();
    std::string deviceName() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

}
