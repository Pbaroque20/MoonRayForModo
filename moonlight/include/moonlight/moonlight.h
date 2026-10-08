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
    // Stretches the Beckmann lobe, as DwaBaseMaterial's anisotropy: -1 to 1, along a tangent
    // given as (cos, sin) of its angle from texture u in the coordinates of tangentSlot.
    float anisotropy = 0.0f;
    float tangent[2] = {1.0f, 0.0f};
    uint32_t tangentSlot = 8;       // UV_SLOT_COUNT for none
    // The share of the diffuse light that scatters beneath the surface, and how far it goes:
    // a distance, scaled per channel by a colour.
    float subsurface = 0.0f;
    float subsurfaceColor[3] = {1.0f, 1.0f, 1.0f};
    float subsurfaceRadius = 0.0f;
    // A solid whose inside absorbs light: at this depth what is left is the transmission
    // colour, and the surface itself no longer tints. 0 for none.
    float absorptionDistance = 0.0f;
    float abbe = 0.0f;              // Abbe number of a dispersive solid; 0 for none
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
    float scale[2] = {1.0f, 1.0f};  // multiplies the texture coordinates
    float gamma = 1.0f;             // MoonRay's ColorCorrectGammaMap, before gain and offset
    float bias = 0.5f;              // MoonRay's RemapMap bias, after them
    float gainCurve = 0.5f;         // the plugin's gain curve, after bias
    // For the checker and noise flags: the second colour (value is the first), how much of the
    // row each colour covers, and the noise's shape.
    float color2[3] = {1, 1, 1};
    float alpha1 = 1.0f, alpha2 = 1.0f;
    float octaves = 4.0f, lacunarity = 2.0f, persistence = 0.5f;
    // With the gradient flag, texture is a 257 x 1 image of the gradient from 0 to 1 and uvSlot
    // the channel whose value looks it up. With the UDIM flag, texture is instead where this
    // row's run starts in the tile list given to setMaterials: a count, then that many textures
    // for tiles 1001 onwards, -1 where a tile is missing.
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
    // Where the vertices are when the shutter closes, for a mesh that changes shape; null if it
    // does not. Shading normals stay as given.
    const float* closePositions = nullptr;
};

const uint32_t UV_SLOT_COUNT = 8;

struct Instance {
    uint32_t mesh = 0;
    uint32_t material = 0;
    // Row-major 3x4 object-to-world transform.
    float transform[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    int32_t light = -1;     // the mesh light whose triangles are this instance's surface
    // Where the instance is when the shutter closes, if it moves.
    bool moves = false;
    float closeTransform[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
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

// What a light filter does to a light's radiance on its way to a point, as MoonRay's
// DecayLightFilter and ColorRampLightFilter. Scale a light's radiance directly for a plain
// intensity filter.
struct LightFilter {
    enum Kind : uint32_t { Decay = 0, Ramp = 1 };
    Kind kind = Decay;
    // Decay: 1 falls off near, 2 falls off far. Ramp: 1 measures along the light's direction
    // rather than from it, 2 mirrors behind the light, 4 measures in the filter's own space.
    uint32_t flags = 0;
    // Decay: near start, near end, far start, far end. Ramp: begin and end distance, intensity, density.
    float values[4] = {0, 0, 0, 0};
    // Ramp with flag 4: world to the filter's space, three rows of (x, y, z, offset).
    float rows[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    int32_t texture = -1;   // ramp: a 257 x 1 image of its colours from begin to end
};

// A sphere, rectangle, disc, spot, cylinder, portal or mesh light, as MoonRay's lights of the
// same names. The flat kinds emit from one side, along direction. A cylinder stands along axisY
// and emits from its side. A portal is a rectangle that shows the lighting environment, which
// then reaches the scene only through portals; its radiance multiplies the environment's. A
// mesh light emits from both faces of its triangles, which must also be an instance in the
// scene that names this light. Sizes are in world units, after any scale.
struct Light {
    enum Kind : uint32_t { Sphere = 0, Rect = 1, Disk = 2, Spot = 3, Cylinder = 4, Portal = 5, Mesh = 6 };
    Kind kind = Sphere;
    float position[3] = {0, 0, 0};
    float axisX[3] = {1, 0, 0};         // in-plane direction of a rect's width
    float axisY[3] = {0, 1, 0};         // in-plane direction of a rect's height
    float direction[3] = {0, 0, -1};
    float width = 1.0f, height = 1.0f;  // rect and portal; height is also a cylinder's length
    float radius = 1.0f;                // sphere, disc, cylinder, and a spot's lens
    float radiance[3] = {1, 1, 1};      // of the surface, after any normalization
    float outerConeDegrees = 60.0f;     // spot: full angle where the light ends
    float innerConeDegrees = 30.0f;     // spot: full angle where the falloff begins
    const float* triangles = nullptr;   // mesh: three world-space corners, 9 floats per triangle
    size_t triangleCount = 0;
    int32_t texture = -1;               // rect: a picture across the light, from addTexture
    const LightFilter* filters = nullptr;
    size_t filterCount = 0;
};

struct Camera {
    float eye[3] = {0, 0, 5};
    float target[3] = {0, 0, 0};
    float up[3] = {0, 1, 0};
    float verticalFovDegrees = 40.0f;
    // Depth of field, as MoonRay's: rays leave a lens of this radius and meet on the plane at
    // focusDistance in front of the camera. 0 is a pinhole. The lens is a disc, or a polygon of
    // three or more blades turned by bladeAngle radians.
    float lensRadius = 0.0f;
    float focusDistance = 1.0f;
    uint32_t blades = 0;
    float bladeAngle = 0.0f;
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
    void setMaterials(const Material* materials, size_t count, const Layer* layers = nullptr, size_t layerCount = 0,
                      const int32_t* tiles = nullptr, size_t tileCount = 0);
    // Rewrites one entry in place.
    void setMaterial(uint32_t index, const Material& material);
    void setEnvironment(const Environment& environment);
    void setDistantLights(const DistantLight* lights, size_t count);
    void setLights(const Light* lights, size_t count);
    void setCamera(const Camera& camera);
    // Motion blur: the camera as it is when the shutter closes, or null if it holds still.
    // Each sample renders the whole scene at one moment between open and close, a different
    // moment per sample, so the accumulated image is blurred; moving instances and meshes that
    // change shape say so themselves. Lights hold still.
    void setCameraMotion(const Camera* close);
    // Nine numbers, the rows of the matrix that takes material colours from Rec.709 to the
    // space the scene is lit in; null when they are the same.
    void setWorkingSpace(const float* matrix);
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
