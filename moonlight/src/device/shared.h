#pragma once
// Layouts shared by the host renderer and the OptiX device programs.
// Device code is compiled by NVRTC without standard headers, so only builtin types appear here.
namespace moonlight {

typedef unsigned long long DevicePtr;

// Material channels a layer can drive; they are the plugin's Shader Tree effects.
const unsigned CHANNEL_COLOR = 0, CHANNEL_COLOR_AMOUNT = 1, CHANNEL_ROUGHNESS = 2, CHANNEL_METALLIC = 3,
               CHANNEL_EMISSION = 4, CHANNEL_EMISSION_AMOUNT = 5, CHANNEL_NORMAL = 6, CHANNEL_TRANSMISSION = 7,
               CHANNEL_TRANSMISSION_COLOR = 8, CHANNEL_TRANSMISSION_ROUGHNESS = 9, CHANNEL_COAT = 10,
               CHANNEL_COAT_ROUGHNESS = 11, CHANNEL_DISSOLVE = 12, CHANNEL_BUMP = 13, CHANNEL_GROUP_MASK = 14,
               CHANNEL_COUNT = 15;
// Rows that are not a channel: the start and end of a group, whose rows are blended as one
// over what was there before it, and a mask written to a register for a later row to use.
const unsigned LAYER_GROUP_BEGIN = 32, LAYER_GROUP_END = 33, LAYER_MASK_BASE = 40, MASK_REGISTERS = 4, GROUP_DEPTH = 4;
// Thin sheets pass light straight through; the coat of a material stack takes its reflection
// out of the layers beneath; and only materials that can be partly absent need the any-hit test.
const unsigned MATERIAL_THIN = 1, MATERIAL_COAT_DIMS = 2, MATERIAL_HAS_PRESENCE = 4, MATERIAL_HAS_BUMP = 8;
const unsigned LAYER_IMAGE = 1, LAYER_INVERT = 2, LAYER_FLIP_RED = 4, LAYER_FLIP_GREEN = 8, LAYER_FLIP_BLUE = 16,
               LAYER_ALPHA_MASK = 32, LAYER_ALPHA_ONLY = 64, LAYER_COVERAGE_U = 128, LAYER_COVERAGE_V = 256,
               LAYER_PICK_SHIFT = 9,    // two bits: 0 keeps RGB, 1 to 3 spread red, green or blue
               LAYER_MASKED = 1 << 11, LAYER_MASK_SHIFT = 12;  // scaled by the mask in that register
const unsigned UV_SLOTS = 8;

// One row of a material's layer stack: a constant or an image blended over what is below it.
struct DeviceLayer {
    unsigned long long texture;     // CUDA texture object, for LAYER_IMAGE
    unsigned channel;
    unsigned blend;                 // the plugin's blend mode numbers; 0 is normal
    unsigned flags;
    unsigned uvSlot;
    float value[3];                 // the constant
    float opacity;
    float gain;                     // contrast and brightness, as value * gain + offset
    float offset;
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
    unsigned pad[3];
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
};

// A uniform spherical cap at infinity, as MoonRay's DistantLight.
struct DeviceDistantLight {
    float direction[3];     // unit vector towards the centre of the cap
    float versine;          // 1 - cos(angular radius)
    float radiance[3];
    float pad;
};

// Sphere, rectangle, disc and spot lights, as MoonRay's lights of the same names.
const unsigned LIGHT_SPHERE = 0, LIGHT_RECT = 1, LIGHT_DISK = 2, LIGHT_SPOT = 3;
struct DeviceLight {
    float position[3];
    unsigned type;
    float u[3];             // rect: half extent along its width; disc and spot: unit axis in the plane
    float radius;
    float v[3];             // the other in-plane axis, as u
    float area;
    float normal[3];        // unit emission direction of the flat lights
    float focalDistance;    // spot: where its falloff is measured
    float radiance[3];
    float rcpFocalRadius;
    float falloffGradient;
    float pick;             // chance of being the light sampled at a bounce, when one is picked
    float cumulative;       // running total of pick up to and including this light
    float pad;
};

struct LaunchParams {
    // Running means over the accumulated samples, float[4] per pixel.
    DevicePtr beauty;
    DevicePtr albedo;
    DevicePtr normal;       // camera space, as the OptiX denoiser expects

    DevicePtr meshes;       // DeviceMesh, indexed by DeviceInstance::mesh
    DevicePtr instances;    // DeviceInstance, indexed by the OptiX instance id
    DevicePtr materials;    // DeviceMaterial
    DevicePtr layers;       // DeviceLayer, indexed from DeviceMaterial::layerStart

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
    unsigned envPad;

    DevicePtr distantLights;    // DeviceDistantLight
    DevicePtr lights;           // DeviceLight
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
};

}
