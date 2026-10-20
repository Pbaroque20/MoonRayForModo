#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// Layouts shared by the host renderer and the OptiX device programs.
// Device code is compiled by NVRTC without standard headers, so only builtin types appear here.
namespace moonlightipr {

typedef unsigned long long DevicePtr;

// The heavy features a kernel can be made without (ML_FEATURES in kernel.cu): a scene that uses none of them is rendered
// by a kernel without their code, a third faster or more. All of them is FEATURE_ALL, the kernel as it is built.
const unsigned FEATURE_FOG = 1, FEATURE_HAIR = 2, FEATURE_SUBSURFACE = 4, FEATURE_TOON = 8, FEATURE_FUZZ = 16, FEATURE_ALL = 31;

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
// The kinds of ray an instance can be hidden from, as bits of its visibility mask.
const unsigned SEEN_CAMERA = 1, SEEN_DIFFUSE = 2, SEEN_REFLECTED = 4, SEEN_THROUGH = 8, SEEN_SHADOW = 16, SEEN_ALL = 255;
const unsigned LAYER_GROUP_BEGIN = 32, LAYER_GROUP_END = 33, LAYER_MASK_BASE = 40, MASK_REGISTERS = 4, GROUP_DEPTH = 4;
// Thin sheets pass light straight through; the coat of a material stack takes its reflection
// out of the layers beneath; and only materials that can be partly absent need the any-hit test.
const unsigned MATERIAL_THIN = 1, MATERIAL_COAT_DIMS = 2, MATERIAL_HAS_PRESENCE = 4, MATERIAL_HAS_BUMP = 8,
               MATERIAL_BECKMANN = 16,  // the specular lobe is Beckmann, as for material stacks, not GGX
               MATERIAL_CONDUCTOR = 32, // a metal reflects as DwaBaseMaterial's does, not by Schlick's curve
               MATERIAL_HAIR = 64,      // on a curve, the strand scatters light as a hair fibre does
               MATERIAL_VOLUME = 128,   // the surface is only the edge of a fog that fills the shape
               // Two bits: the roughness its layers give is Modo's, of the model 1 Blinn, 2 Ashikhmin, 3 GTR,
               // and is turned into the roughness of the lobe that draws the same highlight.
               MATERIAL_ROUGH_SHIFT = 8, MATERIAL_ROUGH_MASK = 3u << 8,
               // DwaBaseMaterial with its casts_caustics off, as it is unless asked: reached by a path that has left a
               // diffuse lobe, the material has no highlight, coat, metal or glass to it, only what is beneath them.
               MATERIAL_NO_CAUSTICS = 1u << 10,
               // Light beneath the surface is followed step by step through the solid (MoonRay's random walk
               // model), in place of being gathered by a diffusion profile.
               MATERIAL_RANDOM_WALK = 1u << 11,
               // MoonRay's toon material: the diffuse light is banded by a ramp, and so is the highlight.
               MATERIAL_TOON_DIFFUSE = 1u << 12, MATERIAL_TOON_SPECULAR = 1u << 13,
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
    unsigned hair;              // with MATERIAL_HAIR, this material's entry in LaunchParams::hairs; with MATERIAL_VOLUME, in volumes;
                                // with either MATERIAL_TOON flag, in toons
    float back[3];              // diffuse light that passes through to the other side, as a thin ear lets it
    float frontKeep[3];         // what that leaves of the diffuse light on the lit side
    float fuzz;                 // MoonRay's fuzz lobe over the others: how much of it
    float fuzzColor[3];
    float fuzzRoughness;        // 0.05 to 1
    float fuzzDims;             // how much it takes from the lobes beneath: fuzz, by its colour unless its fibres absorb
};

// A fog: how much light it stops in a unit of distance, how much of what it stops is scattered on rather than
// absorbed, what it gives off, and which way it scatters. It is even all through, as MoonRay's BaseVolume with
// constant values, or as thick at each place as a grid of densities says, as a VDB volume: the grid fills the
// unit cube that rows takes a point of the scene into, and what the fog stops is multiplied by its value there.
struct DeviceVolume {
    float extinction[3];
    float anisotropy;           // -1 back the way the light came, 0 evenly, 1 straight on
    float albedo[3];
    float pad0;
    float emission[3];
    float peak;                 // the grid's largest value
    unsigned long long grid;    // a 3D texture of densities, or 0 for an even fog
    float rows[12];             // scene to the grid's unit cube, three rows of (x, y, z, offset)
    unsigned long long glow;    // a 3D texture of how much light the fog gives off, times emission; or 0
    float glowRows[12];         // scene to that grid's own unit cube
};

// A toon material's ramps, each read from 0 to 1 in TOON_STEPS steps. The diffuse ramp is looked up by how far the
// light is from straight on (1 - cosine, over its input scale) and multiplies the surface's colour; the highlight's
// by how far the reflected light is from the eye (MoonRay's BsdfToon).
const unsigned TOON_STEPS = 256;
struct DeviceToon {
    float diffuse[TOON_STEPS * 3];
    float specular[TOON_STEPS];
    float diffuseScale, specularScale;
    float intensity;            // of the highlight
    float blend;                // how much of the highlight follows the surface's Fresnel reflection
    float tint[3];
    float level;                // MoonRay's normalization of the highlight for this ramp
    // MoonRay's HairToonMaterial has up to three highlights: the first entry says how many more follow it in the
    // table. Each is a surface's toon highlight (TOON_SURFACE) or one read off a hair fibre's reflection (TOON_HAIR,
    // MoonRay's Toon_Hair: its ramp looked up by how bright the fibre's first reflection is).
    unsigned model;
    unsigned more;
    float variance;             // TOON_HAIR: how far the fibre's reflection spreads along it
    unsigned plain;             // the highlight's Fresnel is that of glass (index 1.5), as MoonRay gives a hair toon's,
                                // rather than the surface's own reflection's
    float underBlend;           // with plain: how far what it lets through to the layers under it (the hair colour, the
                                // highlights after it) moves to its value straight on, by its roughness (OneMinusRoughFresnel)
    // Each ramp past its end, which only an input scale under 1 reaches: its last point's value. At its very end a
    // ramp is still its last stretch's, which the last step holds.
    float diffuseBeyond[3];
    float specularBeyond;
};
const unsigned TOON_SURFACE = 0, TOON_HAIR = 1;

// A hair fibre, as MoonRay's HairMaterial: light reflected off it (R), passed through it (TT), reflected once
// inside it (TRT), and everything after that (TRRT). The fibre's colour is the material's own.
const unsigned HAIR_R = 1, HAIR_TT = 2, HAIR_TRT = 4, HAIR_TRRT = 8,
               HAIR_GLINT = 16;     // the two bright streaks an elliptical fibre adds to TRT
struct DeviceHair {
    float variance[4];          // how far each of the four spreads along the fibre
    float sinShift[4];          // and how far the fibre's scales tilt it towards the root
    float cosShift[4];
    float tint[9];              // of R, TT and TRT
    float azimuthal;            // how far TT spreads around the fibre
    float absorption;           // what turns the fibre's colour into what it absorbs, from that spread
    float eta;
    float saturation;           // of light passing straight through
    unsigned lobes;             // which of the four are shown, and the glint
    unsigned fresnel;           // 0 by the angle along the fibre; 1 also by how far off its middle the light struck; 2 layered cuticles
    float glintWidth;           // how far a glint spreads around the fibre
    float glintEccentricity;    // how far from round the fibre is
    float glintSaturation;
    float twists[2];            // fewest and most turns the fibre's cross-section makes from root to tip
    float layers;               // cuticle layers, for the layered Fresnel term
};

struct DeviceMesh {
    DevicePtr positions;    // float[3] per vertex; unused for curves, whose control points OptiX hands back
    DevicePtr normals;      // float[3] per vertex, or 0 for faceted shading; for curves, per control point: how far along
                            // its strand it is, its strand's own number from 0 to 1, and nothing
    DevicePtr indices;      // unsigned[3] per triangle; for curves, each segment's first control point
    DevicePtr materialIds;  // unsigned per triangle, or 0 to use the instance material
    DevicePtr uvs;          // float[2] per triangle corner, one run of triangleCount * 3 per set; for curves, one set, per control point
    unsigned triangleCount;
    int uvSet[UV_SLOTS];    // which of this mesh's sets serves each scene-wide slot, or -1
    unsigned curves;        // curves rather than triangles: 1 round cubic B-spline segments, 2 round straight ones;
                            // with 4 added they are lit as flat ribbons facing the ray, MoonRay's default
};

struct DeviceInstance {
    unsigned mesh;
    unsigned material;
    int light;              // the mesh light this instance is the surface of, or -1
    unsigned lightSet;      // the lights that reach it (LaunchParams::lightSets), 0 for all of them
};

// A uniform spherical cap at infinity, as MoonRay's DistantLight.
struct DeviceDistantLight {
    float direction[3];     // unit vector towards the centre of the cap
    float versine;          // 1 - cos(angular radius)
    float radiance[3];
    float visible;          // 1 if the camera sees the disc
    float u[3];             // the light's own x and y axes, which a picture across the disc runs along
    float uvScale;          // what MoonRay's equal-area mapping multiplies a direction's x and y by
    float v[3];
    float pad;
    unsigned long long texture;     // a picture across the disc, or 0
    DevicePtr distribution;         // where that picture is bright, to draw directions from; see DeviceLight
    float seen[3];          // the disc the camera sees, which may differ from the one that lights the scene
    float seenVersine;
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
    unsigned long long texture;     // a picture across the light, laid out as MoonRay lays it on each kind; 0 for none
    unsigned filterCount;
    unsigned pad;
    // Rect, disc and cylinder with a picture: where the picture is bright, as a width and a height (floats), a
    // running total over its rows (height + 1), then one over each row's columns (height rows of width + 1), all
    // in the picture's own coordinates. Points on the light are drawn from it. 0 for none.
    DevicePtr distribution;
};

// What a light filter does to the light arriving at a point, as MoonRay's DecayLightFilter, ColorRampLightFilter,
// RodLightFilter, BarnDoorLightFilter and CookieLightFilter_v2. A plain intensity filter is folded into the light's
// radiance instead.
const unsigned FILTER_DECAY = 0, FILTER_RAMP = 1, FILTER_ROD = 2, FILTER_BARN = 3, FILTER_COOKIE = 4, FILTER_VDB = 5;
const unsigned FILTER_INVERT = 1;       // rod, barn door, cookie
const unsigned FILTER_ORTHO = 2, FILTER_PHYSICAL = 4;      // barn door: how it projects, and through the light's own ray
const unsigned FILTER_WHITE = 2, FILTER_EDGELESS = 4;      // cookie: lit outside its picture; its picture read past its edge
const unsigned FILTER_ROUND = 8;        // cookie and VDB: blurred over a disc or a ball, not by the camera's own bell
const unsigned FILTER_NEAR = 1, FILTER_FAR = 2;     // decay: which ends fall off
const unsigned FILTER_DIRECTIONAL = 1, FILTER_MIRROR = 2, FILTER_PLACED = 4;    // ramp
struct DeviceFilter {
    unsigned type;
    unsigned flags;
    float a[4];             // decay: near start, near end, far start, far end. Ramp: begin, end, intensity, density
    float rows[12];         // ramp with FILTER_PLACED: world to the filter's own space, three rows of (x, y, z, offset)
    unsigned long long texture;     // ramp: its colours from begin to end, 257 across. Cookie: its picture
    // Rod: a holds half its width, height and depth and its corner radius; b its edge, density and colour; rows take
    // the scene into its own space. Barn door: a holds the opening's low and high corners; b its corner radius, one
    // over the edge at left, bottom, right and top, its focal distance, colour and density; rows take the scene into
    // the projector's space, which looks along +z. Cookie: rows give a point's place across the picture, up it, and
    // what both are divided by, which is below nothing behind the projector; b holds its density. VDB: texture is a
    // grid of densities, rows take the scene into the grid's unit cube, and b holds the colour light takes where the
    // grid is empty.
    float b[12];
    // Rod: how its edge fades, 257 across from the box out to the edge's end. VDB: what its densities are remapped
    // to, 257 across from a[0] to a[1]. 0 for neither. A cookie's b also holds, after its density, the projector's
    // place and its blur: the near, middle and far distances, then the blur at each. A VDB's b holds, after its
    // tint, its blur and how much of the grid's cube a unit of the filter's own space is along each axis.
    unsigned long long ramp;
};

// How much of the light a specular lobe reflects when its Fresnel term is one, tabulated over
// roughness and the cosine of the view angle for GGX and then Beckmann, each followed by its
// average over all angles per roughness. What is missing is light that bounced between facets.
const unsigned ALBEDO_STEPS = 16;
const unsigned ALBEDO_TABLE = ALBEDO_STEPS * ALBEDO_STEPS + ALBEDO_STEPS;

// The side of the square parts of the picture each judged clean on its own, in pixels.
const unsigned CLEAN_TILE = 8;

struct LaunchParams {
    // Running means over the accumulated samples, float[4] per pixel.
    DevicePtr beauty;
    DevicePtr albedo;
    DevicePtr normal;       // camera space, as the OptiX denoiser expects
    // While the render stops once clean: the running mean of the even samples alone, float[4] per pixel, and a byte
    // for each CLEAN_TILE square, doneColumns to a row, set once that square is clean. Both 0 otherwise.
    DevicePtr half;
    DevicePtr done;
    unsigned doneColumns;
    unsigned donePad;
    // Light links: each set lightSetWords words, a bit for the lighting environment, then each distant light, then
    // each other light. An instance names its set (DeviceInstance::lightSet); set 0 is every light.
    DevicePtr lightSets;
    unsigned lightSetWords;
    unsigned lightSetPad;

    DevicePtr meshes;       // DeviceMesh, indexed by DeviceInstance::mesh
    DevicePtr instances;    // DeviceInstance, indexed by the OptiX instance id
    DevicePtr materials;    // DeviceMaterial
    DevicePtr layers;       // DeviceLayer, indexed from DeviceMaterial::layerStart
    DevicePtr albedo2;      // float, two ALBEDO_TABLE runs: GGX, then Beckmann
    DevicePtr hairs;        // DeviceHair, indexed by DeviceMaterial::hair
    DevicePtr volumes;      // DeviceVolume, likewise
    DevicePtr toons;        // DeviceToon, likewise
    unsigned volumeCount;
    unsigned volumePad;

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
    unsigned maxVolumeDepth;    // how many times light may scatter in fog along one path; MoonRay's max_volume_depth
    unsigned opaqueShadows; // a surface that is partly absent casts a whole shadow all the same: MoonRay with its presence shadows off
    unsigned sampleClampDepth;  // how many rough things: MoonRay's sample_clamping_depth, 1 leaving alone what the camera sees directly
    float sampleClamp;      // largest value of one light sample once the path has scattered off enough rough things; 0 is unlimited
    // MoonRay's volume_attenuation_factor, volume_contribution_factor and volume_phase_attenuation_factor.
    float volumeAttenuation, volumeContribution, volumePhaseAttenuation;
    unsigned presence;      // some material can be partly absent or is a fog's edge, so rays must run the any-hit test
    // A toon material lit by its smooth normals on a coarse mesh, not cut into steps along its faces: MoonRay patched
    // for it, under the same MOONRAY_MODO_TOON_TERMINATOR (tools/port_toon_terminator.py).
    unsigned toonTerminator;

    unsigned long long traversable;

    float cameraOrigin[3];
    float cameraU[3];       // half-width of the image plane
    float cameraV[3];       // half-height of the image plane
    float cameraW[3];       // view direction to the image plane
    float lensRadius;       // 0 for a pinhole
    float focusDistance;    // along the view direction
    unsigned lensBlades;    // 0 for a disc
    float lensAngle;
    unsigned cameraProjection;      // 0 perspective, 1 fisheye, 2 spherical, 3 orthographic
    float cameraProjectionValues[4];
    float cameraShift[2];           // a perspective camera's film offset, in halves of the picture across and up
    unsigned region[4];     // the pixels to render: from column, from row, to column, to row; the rest are black
    unsigned draft;         // 0 none, 1 lines outside the region, 2 lines everywhere
    unsigned mixedVisibility;   // some instance is hidden from one kind of ray and not from another
};

}
