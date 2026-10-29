#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// MoonLightIPR: an approximate GPU preview path tracer for interactive rendering.
// It reads the scene MoonRay renders, flattened to triangle buffers, and shades it with one
// fixed uber-shader. Final frames always come from MoonRay.
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace moonlightipr {

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
    bool randomWalk = false;        // light beneath the surface is followed through the solid, MoonRay's random walk model
    // MoonRay's toon material: the diffuse light banded by a ramp, the highlight by another. toon holds the diffuse
    // ramp's 256 colours from 0 to 1, the highlight ramp's 256 values, then the diffuse ramp's input scale, the
    // highlight's input scale, intensity and Fresnel blend, its tint, and its normalization.
    bool toonDiffuse = false, toonSpecular = false;
    std::vector<float> toon;
    unsigned toonMore = 0;      // highlights after the first (a hair toon's second and third), each TOON_EXTRA more numbers
    bool noCaustics = false;        // DwaBaseMaterial with casts_caustics off: plain diffuse once a path has left a diffuse lobe
    int roughnessCurve = 0;         // the roughness the layers give is Modo's: 1 Blinn, 2 Ashikhmin, 3 GTR; 0 as it is
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
    // How much of the dielectric's reflection there is, as DwaBaseMaterial's specular: 1 is all of it.
    // The coat and a metal are not weighted.
    float specularWeight = 1.0f;
    // Diffuse light that passes through to the far side, as DwaBaseMaterial's diffuse transmission lets an ear glow,
    // and what that leaves of the diffuse light on the lit side.
    float diffuseTransmission[3] = {0, 0, 0};
    float diffuseKept[3] = {1, 1, 1};
    // MoonRay's fuzz, the sheen of velvet (DwaVelvetMaterial, and DwaBaseMaterial's fuzz): a lobe over all the others,
    // brightest at grazing angles. How much of it, its colour, its roughness as the lobe takes it (0.05 to 1), and
    // whether its fibres absorb the light they do not reflect (or pass it on in proportion to their colour).
    float fuzz = 0.0f;
    float fuzzColor[3] = {1, 1, 1};
    float fuzzRoughness = 0.3f;
    bool fuzzAbsorbs = false;
    float clearcoatBump = 1.0f;     // how much of the bump and normal maps the coat takes: Modo's Clearcoat Bump Strength
    // On curves, a hair fibre as MoonRay's HairMaterial, in place of all the above but baseColor (the hair's colour),
    // its layers, emission and ior. The four lobes are light reflected off the fibre, passed through it, reflected
    // once inside it, and the rest: each has a roughness along the fibre and an offset in degrees from the tilt of
    // its scales, and the first three a tint. hairLobes has a bit for each that is shown, from 1.
    bool hair = false;
    float hairRoughness[4] = {0.5f, 0.25f, 1.0f, 1.0f};
    float hairOffset[4] = {-3.0f, -1.5f, -4.5f, 0.0f};
    float hairTint[9] = {1, 1, 1, 1, 1, 1, 1, 1, 1};
    float hairAzimuthalRoughness = 1.0f;    // how far light passing through spreads around the fibre
    float hairSaturation = 1.0f;
    uint32_t hairLobes = 15;
    uint32_t hairFresnel = 1;               // 0 by the angle along the fibre alone; 1 as a cylinder; 2 layered cuticles
    float hairCuticle = 0.1f;               // for 2: how thick the cuticle is, 0 to 1
    // An elliptical fibre's glints: two streaks beside its reflection from inside. The fibre's cross-section turns
    // between hairTwists[0] and [1] times from root to tip, a number of its own for each strand.
    bool hairGlint = false;
    float hairGlintRoughness = 0.5f, hairGlintEccentricity = 0.85f, hairGlintSaturation = 0.5f;
    float hairTwists[2] = {1.5f, 2.5f};
    // An even fog filling a closed mesh, as MoonRay's BaseVolume with constant values, in place of a surface: the
    // mesh itself is not seen. How much light the fog stops in a unit of distance, how much of that is scattered
    // on, what it gives off, and which way it scatters (-1 back, 0 evenly, 1 on). Light scatters in it once. A
    // camera inside the fog does not see it.
    bool volume = false;
    float volumeExtinction[3] = {1, 1, 1};
    float volumeAlbedo[3] = {1, 1, 1};
    float volumeEmission[3] = {0, 0, 0};
    float volumeAnisotropy = 0.0f;
    // A fog that is not the same all through, as a VDB volume: a grid from addGrid whose values multiply what the fog
    // stops, and the rows that take a point of the scene into the unit cube the grid fills. -1 for an even fog.
    int32_t volumeGrid = -1;
    float volumeRows[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    // A grid of how much light such a fog gives off at each place, which volumeEmission multiplies, and the rows
    // into its own unit cube: the grid of a fire need not cover what the grid of its smoke does. -1 for none.
    int32_t volumeGlowGrid = -1;
    float volumeGlowRows[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
};

// A block of numbers on the GPU, x fastest, read between its cells.
struct GridDesc {
    const float* values = nullptr;
    uint32_t counts[3] = {0, 0, 0};
    float peak = 0.0f;      // the largest of the values
    uint32_t channels = 1;  // 1 for a grid of numbers, 4 for a grid of colours
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
    // The most texels across a side the card is given: a larger picture is halved, each texel the mean of four, until
    // it is no larger. 0 for no limit. A picture of high dynamic range is kept on the card as halves whatever its size.
    uint32_t maxSize = 0;
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
    // With the procedural flag: Modo's pattern and its Type, its six settings then its bias and gain, and rows that
    // take a point of the world into the texture locator's space.
    uint32_t pattern = 0;
    float settings[24] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.5f, 0.5f};
    float rows[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
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

// Curves, as round segments: tubes whose middle follows a cubic B-spline, or runs straight from point to point,
// and whose radius is that of the control points, blended the same way. Each segment names its first control
// point; the three after it complete a cubic one and the one after it a straight one, so the segments of one
// strand share their points. Straight pieces meet in a rounded joint. Buffers are copied.
struct CurveDesc {
    const float* positions = nullptr;       // 3 floats per control point
    const float* radii = nullptr;           // 1 per control point
    size_t pointCount = 0;
    const uint32_t* segments = nullptr;     // 1 per segment
    size_t segmentCount = 0;
    const float* uvs = nullptr;             // 2 floats per control point, or null; a segment takes its first point's
    // 3 floats per control point, or null: how far along its strand it is from 0 to 1, a number from 0 to 1 that is
    // its strand's own, and nothing. Hair glints turn with them.
    const float* strands = nullptr;
    // Where the control points are when the shutter closes, for curves that change shape; null if they do not.
    const float* closePositions = nullptr;
    bool ribbon = false;                    // lit as a flat ribbon that faces each ray, as MoonRay's default strand is
    bool linear = false;                    // straight segments rather than cubic ones
};

const uint32_t UV_SLOT_COUNT = 8;

struct Instance {
    uint32_t mesh = 0;
    uint32_t material = 0;
    // Row-major 3x4 object-to-world transform.
    float transform[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    int32_t light = -1;     // the mesh light whose triangles are this instance's surface
    // Which rays find the instance, a bit for each kind: 1 the camera's, 2 light scattered diffusely, 4 reflections,
    // 8 light passing through a surface, 16 shadows. Above those eight bits, the light set that lights it
    // (setLightSets), 0 for every light.
    uint32_t visibility = 255;
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
    bool visibleInCamera = false;       // whether the camera sees the disc, as a sun in the sky
    // What the camera then sees: a disc of this radiance and this full angle, which may differ from what lights the
    // scene, as the disc of a physical sky does.
    float seenRadiance[3] = {1, 1, 1};
    float seenExtentDegrees = 0.5f;
    // A picture across the disc, from addTexture, laid out along the light's own x and y axes as MoonRay lays it.
    int32_t texture = -1;
    float axisX[3] = {1, 0, 0};
    float axisY[3] = {0, 1, 0};
};

// What a light filter does to a light's radiance on its way to a point, as MoonRay's
// DecayLightFilter and ColorRampLightFilter. Scale a light's radiance directly for a plain
// intensity filter.
struct LightFilter {
    // Intensity: inside a Combine, its colour times its strength in more. Group: MoonRay's Combine; flags hold its mode and,
    // from bit 8, how many of the filters after it it joins.
    enum Kind : uint32_t { Decay = 0, Ramp = 1, Rod = 2, BarnDoor = 3, Cookie = 4, Vdb = 5, Intensity = 6, Group = 7 };
    Kind kind = Decay;
    // Decay: 1 falls off near, 2 falls off far. Ramp: 1 measures along the light's direction
    // rather than from it, 2 mirrors behind the light, 4 measures in the filter's own space.
    uint32_t flags = 0;
    // Decay: near start, near end, far start, far end. Ramp: begin and end distance, intensity, density.
    float values[4] = {0, 0, 0, 0};
    // Ramp with flag 4: world to the filter's space, three rows of (x, y, z, offset).
    float rows[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    int32_t texture = -1;   // ramp: a 257 x 1 image of its colours from begin to end. Cookie: its picture. VDB: a grid from addGrid
    // Rod, barn door and cookie: the rest of what they are, as shared.h says of DeviceFilter::b.
    float more[12] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
    int32_t ramp = -1;      // rod: a 257 x 1 image of how its edge fades. VDB: of what its densities are remapped to
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
    int32_t texture = -1;               // a picture across the light, from addTexture; not for a portal or a mesh
    bool visibleInCamera = false;       // whether the camera sees it shining where it stands; never a portal
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
    // How a point of the picture becomes a direction: 0 through a pinhole or lens, as above;
    // 1 MoonRay's FisheyeCamera, with projectionValues its mapping, format, zoom and half field
    // of view in radians; 2 MoonRay's SphericalCamera, with projectionValues the latitude and
    // then the longitude as scale and offset over the picture's height and width.
    // 3 orthographic, with projectionValues[0] the width of its window in scene units.
    uint32_t projection = 0;
    float projectionValues[4] = {0, 0, 0, 0};
    // The part of the picture to render, as fractions of it: left, top, right, bottom. The rest is black.
    float region[4] = {0, 0, 1, 1};
    // Draft: 0 for none; 1 draws what is outside the region as lines, in place of black; 2 draws the whole picture
    // so. The lines are where one surface ends against another or turns a corner, as the camera sees them: white
    // on black, for whoever shows the picture to ink as it likes.
    uint32_t draft = 0;
    // A perspective camera's film offset: how far the middle of the picture moves, right and up, in halves of the
    // film's width, as MoonRay's window moves it. A stereo eye's convergence is one.
    float filmShift[2] = {0, 0};
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
    // Curves are instanced, moved and removed as meshes are, and take the instance's material.
    uint32_t addCurves(const CurveDesc& curves);
    // Frees a mesh no instance uses; its index may be handed out again.
    void removeMesh(uint32_t mesh);
    // Rebuilds only the instance layer, which is all a transform edit costs.
    void setInstances(const Instance* instances, size_t count);
    // Says which of a mesh's coordinate sets serves each scene-wide slot (-1 for none).
    void setMeshUvSlots(uint32_t mesh, const int32_t slots[UV_SLOT_COUNT]);
    uint32_t addTexture(const TextureDesc& texture);
    // A grid of densities for a fog; returns its index for Material::volumeGrid.
    uint32_t addGrid(const GridDesc& grid);
    // Frees a grid no current material uses; its index may be handed out again.
    void removeGrid(uint32_t grid);
    // Frees a texture no current material layer uses; its index may be handed out again.
    void removeTexture(uint32_t texture);
    void setMaterials(const Material* materials, size_t count, const Layer* layers = nullptr, size_t layerCount = 0,
                      const int32_t* tiles = nullptr, size_t tileCount = 0);
    // Rewrites one entry in place.
    void setMaterial(uint32_t index, const Material& material);
    void setEnvironment(const Environment& environment);
    void setDistantLights(const DistantLight* lights, size_t count);
    void setLights(const Light* lights, size_t count);
    // Which lights reach which instances: count sets of words each, a bit for the lighting environment, then each
    // distant light and each other light in the order they were set. Set 0 is every light, whatever its words say.
    void setLightSets(const uint32_t* sets, uint32_t words, size_t count);
    // Displacement. What a mesh's materials' displacement layers give at each of count places on it, each a triangle and
    // a place on it as OptiX's barycentrics (primitive, b1, b2 in turn), by the material of that triangle, or material
    // where the mesh names none per triangle: for each place, its four displacement channels' colours (12 floats). Call
    // once the materials and the mesh's coordinate slots are set.
    void displacementValues(uint32_t mesh, uint32_t material, const uint32_t* primitives, const float* barycentrics,
                            size_t count, float* values);
    // A mesh's vertices moved where they now are, and its normals (or none, for faceted shading), and where they are as
    // the shutter closes for a mesh that changes shape (or null); its structure is rebuilt.
    void reshapeMesh(uint32_t mesh, const float* positions, const float* normals, const float* closePositions = nullptr);
    void setCamera(const Camera& camera);
    // Motion blur: the camera as it is when the shutter closes, or null if it holds still.
    // Each sample renders the whole scene at one moment between open and close, a different
    // moment per sample, so the accumulated image is blurred; moving instances and meshes that
    // change shape say so themselves. Lights hold still.
    void setCameraMotion(const Camera* close);
    // The lights where they are when the shutter closes, after setDistantLights and setLights and as many of each;
    // only where they are and which way they face is read. Counts of 0 hold every light still.
    void setLightMotion(const DistantLight* distantClose, size_t distantCount, const Light* close, size_t count);
    // Nine numbers, the rows of the matrix that takes material colours from Rec.709 to the
    // space the scene is lit in; null when they are the same.
    void setWorkingSpace(const float* matrix);
    void resize(uint32_t width, uint32_t height);
    // Total bounces, and of those how many may leave a diffuse and a specular lobe, as
    // MoonRay's max_depth, max_diffuse_depth and max_glossy_depth.
    // The most one light sample may add once the path has scattered off `depth` rough things; 0 is no limit. MoonRay's
    // sample_clamping_value and sample_clamping_depth.
    void setSampleClamp(float value, uint32_t depth = 1);
    // How each further bounce of light in fog counts for less, as MoonRay's volume_attenuation_factor,
    // volume_contribution_factor and volume_phase_attenuation_factor: raised to the bounce's number.
    void setVolumeScattering(float attenuation, float contribution, float phaseAttenuation);
    // presenceShadows: whether a surface that is partly absent casts a lighter shadow, or a whole one as MoonRay's does unless asked.
    void setMaxDepth(uint32_t bounces, uint32_t diffuseBounces = 2, uint32_t glossyBounces = 2, uint32_t volumeBounces = 1, bool presenceShadows = true);

    // Adds one sample per pixel to the accumulated image, except where the picture is already clean.
    void render();
    // Stop once clean: a part of the picture whose noise, as it shows on the screen, is under this takes no more
    // samples, and converged() says when all of it is. 0 renders every sample everywhere. Read as a render starts.
    void setConvergence(float noise);
    bool converged() const;
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
    // How much of the graphics card's memory is free, in bytes.
    size_t freeMemory() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

}
