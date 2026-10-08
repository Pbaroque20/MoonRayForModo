#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLight is not affiliated with DreamWorks Animation; see moonlight/NOTICE.md.
// Layouts shared by the host renderer and the OptiX device programs.
// Device code is compiled by NVRTC without standard headers, so only builtin types appear here.
namespace moonlight {

typedef unsigned long long DevicePtr;

// Material channels a layer can drive; they are the plugin's Shader Tree effects.
const unsigned CHANNEL_COLOR = 0, CHANNEL_COLOR_AMOUNT = 1, CHANNEL_ROUGHNESS = 2, CHANNEL_METALLIC = 3,
               CHANNEL_EMISSION = 4, CHANNEL_EMISSION_AMOUNT = 5, CHANNEL_NORMAL = 6, CHANNEL_TRANSMISSION = 7,
               CHANNEL_TRANSMISSION_COLOR = 8, CHANNEL_TRANSMISSION_ROUGHNESS = 9, CHANNEL_COAT = 10,
               CHANNEL_COAT_ROUGHNESS = 11, CHANNEL_DISSOLVE = 12, CHANNEL_BUMP = 13, CHANNEL_GROUP_MASK = 14,
               CHANNEL_ANISOTROPY = 15, CHANNEL_SUBSURFACE = 16, CHANNEL_SUBSURFACE_COLOR = 17,
               CHANNEL_DRIVER = 18,     // four values that only gradient rows read
               CHANNEL_COUNT = 22;
// Rows that are not a channel: the start and end of a group, whose rows are blended as one
// over what was there before it, and a mask written to a register for a later row to use.
const unsigned LAYER_GROUP_BEGIN = 32, LAYER_GROUP_END = 33, LAYER_MASK_BASE = 40, MASK_REGISTERS = 4, GROUP_DEPTH = 4;
// Thin sheets pass light straight through; the coat of a material stack takes its reflection
// out of the layers beneath; and only materials that can be partly absent need the any-hit test.
const unsigned MATERIAL_THIN = 1, MATERIAL_COAT_DIMS = 2, MATERIAL_HAS_PRESENCE = 4, MATERIAL_HAS_BUMP = 8,
               MATERIAL_BECKMANN = 16,  // the specular lobe is Beckmann, as for material stacks, not GGX
               MATERIAL_MATTE = 1u << 30;   // set by the kernel alone, where light leaves from beneath a surface
const unsigned LAYER_IMAGE = 1, LAYER_INVERT = 2, LAYER_FLIP_RED = 4, LAYER_FLIP_GREEN = 8, LAYER_FLIP_BLUE = 16,
               LAYER_ALPHA_MASK = 32, LAYER_ALPHA_ONLY = 64, LAYER_COVERAGE_U = 128, LAYER_COVERAGE_V = 256,
               LAYER_PICK_SHIFT = 9,    // two bits: 0 keeps RGB, 1 to 3 spread red, green or blue
               LAYER_MASKED = 1 << 11, LAYER_MASK_SHIFT = 12,  // scaled by the mask in that register
               // Where the row's value comes from when it is not a constant or one image: a gradient
               // looked up by another channel, a checker or noise pattern, or one image per UDIM tile.
               LAYER_RAMP = 1 << 16, LAYER_CHECKER = 1 << 17, LAYER_NOISE = 1 << 18, LAYER_UDIM = 1 << 19,
               LAYER_CURVES = 1 << 20;  // gamma, bias or gain differ from their neutral values
const unsigned UV_SLOTS = 8;

// One row of a material's layer stack: a constant or an image blended over what is below it.
struct DeviceLayer {
    // CUDA texture object for LAYER_IMAGE and LAYER_RAMP. For LAYER_UDIM, a device array of
    // them: the number of tiles, then one object per tile from 1001 on, 0 where a tile is missing.
    unsigned long long texture;
    unsigned channel;
    unsigned blend;                 // the plugin's blend mode numbers; 0 is normal
    unsigned flags;
    unsigned uvSlot;                // for LAYER_RAMP, the channel whose value looks the gradient up
    float value[3];                 // the constant, or a pattern's first colour
    float opacity;
    float gain;                     // contrast and brightness, as value * gain + offset
    float offset;
    float scale[2];                 // multiplies the texture coordinates
    float gamma;                    // 1 leaves the value alone
    float bias;                     // 0.5 leaves the value alone
    float gainCurve;                // 0.5 leaves the value alone
    float color2[3];                // a pattern's second colour
    float alpha1, alpha2;           // how much of the row a pattern's two colours cover
    float octaves, lacunarity, persistence;     // noise
    float pad;
};

// The fixed uber-shader: starting values for every channel, then the layers that modify them.
struct DeviceMaterial {
    float color[3];
    float colorAmount;
    float emission[3];
    float emissionAmount;
    float roughness;
    float metallic;
    float ior;
    // Roughness MoonRay uses when it dims the diffuse lobe under the specular one: the
    // surface roughness when negative, otherwise this value (0 applies the full Fresnel term).
    float underRoughness;
    float transmissionColor[3];
    float transmission;         // share of the light entering the surface that passes through it
    float transmissionRoughness;
    float transmissionIor;
    float coat;
    float coatRoughness;
    float dissolve;             // 1 - presence
    unsigned flags;
    unsigned layerStart;
    unsigned layerCount;
    float bumpStrength;         // height of a bump map's full range, in scene units
    float anisotropy;           // -1 to 1, as DwaBaseMaterial's
    float tangent[2];           // the direction the lobe is stretched along, as (cos, sin) from texture u
    unsigned tangentSlot;       // the coordinates that give texture u; UV_SLOTS for none
    float subsurface;           // share of the diffuse light that scatters beneath the surface
    float subsurfaceColor[3];   // scales the distance per channel
    float subsurfaceRadius;     // mean distance the light travels beneath the surface
    float absorptionDistance;   // depth of a solid at which light has its transmission colour; 0 for none
    float abbe;                 // Abbe number of a dispersive solid; 0 for none
    float specular;             // weight of the dielectric's reflection
    unsigned pad;
};

struct DeviceMesh {
    DevicePtr positions;    // float[3] per vertex
    DevicePtr normals;      // float[3] per vertex, or 0 for faceted shading
    DevicePtr indices;      // unsigned[3] per triangle
    DevicePtr materialIds;  // unsigned per triangle, or 0 to use the instance material
    DevicePtr uvs;          // float[2] per triangle corner, one run of triangleCount * 3 per set
    unsigned triangleCount;
    int uvSet[UV_SLOTS];    // which of this mesh's sets serves each scene-wide slot, or -1
    unsigned pad;
};

struct DeviceInstance {
    unsigned mesh;
    unsigned material;
    int light;              // the mesh light this instance is the surface of, or -1
    unsigned pad;
};

// A uniform spherical cap at infinity, as MoonRay's DistantLight.
struct DeviceDistantLight {
    float direction[3];     // unit vector towards the centre of the cap
    float versine;          // 1 - cos(angular radius)
    float radiance[3];
    float visible;          // 1 if the camera sees the disc
};

// Sphere, rectangle, disc and spot lights, as MoonRay's lights of the same names.
// A cylinder emits from its side; a portal is a rectangle the environment shines through; a
// mesh light emits from both faces of a list of triangles.
const unsigned LIGHT_SPHERE = 0, LIGHT_RECT = 1, LIGHT_DISK = 2, LIGHT_SPOT = 3, LIGHT_CYLINDER = 4,
               LIGHT_PORTAL = 5, LIGHT_MESH = 6;
struct DeviceLight {
    float position[3];
    unsigned type;
    float u[3];             // rect: half extent along its width; disc and spot: unit axis in the plane
    float radius;
    float v[3];             // the other in-plane axis, as u; cylinder: its unit axis
    float area;
    float normal[3];        // unit emission direction of the flat lights
    float focalDistance;    // spot: where its falloff is measured
    float radiance[3];
    float rcpFocalRadius;
    float falloffGradient;
    float pick;             // chance of being the light sampled at a bounce, when one is picked
    float cumulative;       // running total of pick up to and including this light
    float halfHeight;       // cylinder
    DevicePtr triangles;    // mesh: float[10] per triangle, a corner, two edges and the running share of the area
    unsigned triangleCount;
    unsigned filterStart;   // this light's run in LaunchParams::lightFilters
    unsigned long long texture;     // rect: a picture across the light, or 0
    unsigned filterCount;
    unsigned pad;
};

// What a light filter does to the light arriving at a point, as MoonRay's DecayLightFilter and
// ColorRampLightFilter. A plain intensity filter is folded into the light's radiance instead.
const unsigned FILTER_DECAY = 0, FILTER_RAMP = 1;
const unsigned FILTER_NEAR = 1, FILTER_FAR = 2;     // decay: which ends fall off
const unsigned FILTER_DIRECTIONAL = 1, FILTER_MIRROR = 2, FILTER_PLACED = 4;    // ramp
struct DeviceFilter {
    unsigned type;
    unsigned flags;
    float a[4];             // decay: near start, near end, far start, far end. Ramp: begin, end, intensity, density
    float rows[12];         // ramp with FILTER_PLACED: world to the filter's own space, three rows of (x, y, z, offset)
    unsigned long long texture;     // ramp: its colours from begin to end, 257 across
};

// How much of the light a specular lobe reflects when its Fresnel term is one, tabulated over
// roughness and the cosine of the view angle for GGX and then Beckmann, each followed by its
// average over all angles per roughness. What is missing is light that bounced between facets.
const unsigned ALBEDO_STEPS = 16;
const unsigned ALBEDO_TABLE = ALBEDO_STEPS * ALBEDO_STEPS + ALBEDO_STEPS;

struct LaunchParams {
    // Running means over the accumulated samples, float[4] per pixel.
    DevicePtr beauty;
    DevicePtr albedo;
    DevicePtr normal;       // camera space, as the OptiX denoiser expects

    DevicePtr meshes;       // DeviceMesh, indexed by DeviceInstance::mesh
    DevicePtr instances;    // DeviceInstance, indexed by the OptiX instance id
    DevicePtr materials;    // DeviceMaterial
    DevicePtr layers;       // DeviceLayer, indexed from DeviceMaterial::layerStart
    DevicePtr albedo2;      // float, two ALBEDO_TABLE runs: GGX, then Beckmann

    // Latitude-longitude environment with a piecewise-constant sampling distribution.
    DevicePtr envPixels;        // float[4], envWidth * envHeight; what lights the scene
    DevicePtr envBackground;    // same layout; what the camera sees behind the scene
    DevicePtr envMarginal;      // float, envHeight + 1 (CDF over rows)
    DevicePtr envConditional;   // float, envHeight * (envWidth + 1) (CDF within each row)
    unsigned envWidth;
    unsigned envHeight;

    // Rows are the map's axes in world space; a world direction dotted with each gives the
    // direction the map is indexed by.
    float envRotation[9];
    float envBackgroundRotation[9];
    unsigned lightPick;     // sample one light per bounce, chosen by power, instead of all of them
    unsigned envPortal;     // the lighting environment reaches the scene only through portal lights
    // Material colours are worked out in Rec.709 and then taken to the working space by these rows.
    float workingMatrix[9];
    unsigned working;

    DevicePtr distantLights;    // DeviceDistantLight
    DevicePtr lights;           // DeviceLight
    DevicePtr lightFilters;     // DeviceFilter, indexed from DeviceLight::filterStart
    unsigned distantLightCount;
    unsigned lightCount;

    unsigned width;
    unsigned height;
    unsigned sample;        // index of the sample being added
    unsigned maxDepth;      // bounces after the camera ray
    unsigned maxDiffuseDepth;   // of those, how many may leave a diffuse lobe
    unsigned maxGlossyDepth;    // and how many a specular lobe
    float sampleClamp;      // largest value of one light sample after the first bounce; 0 is unlimited
    unsigned presence;      // some material can be partly absent, so rays must run the any-hit test

    unsigned long long traversable;

    float cameraOrigin[3];
    float cameraU[3];       // half-width of the image plane
    float cameraV[3];       // half-height of the image plane
    float cameraW[3];       // view direction to the image plane
    float lensRadius;       // 0 for a pinhole
    float focusDistance;    // along the view direction
    unsigned lensBlades;    // 0 for a disc
    float lensAngle;
    unsigned cameraProjection;      // 0 perspective, 1 fisheye, 2 spherical
    float cameraProjectionValues[4];
};

}
