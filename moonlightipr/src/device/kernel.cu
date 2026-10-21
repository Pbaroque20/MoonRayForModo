// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// MoonLightIPR device programs: a progressive megakernel path tracer.
// One launch adds one sample per pixel to the running means in LaunchParams.
#include <optix.h>
#include "shared.h"
#include "vec.h"
#include "velvet_tables.h"

using namespace moonlightipr;

extern "C" { __constant__ LaunchParams params; }

// What a radiance ray found: the geometry, and the material resolved at that point.
// The features a kernel is made with: all of them, unless ML_FEATURES says otherwise when it is compiled, so that one
// made for a scene without them can leave their code out.
#ifndef ML_FEATURES
#define ML_FEATURES 0xffffffffu
#endif
#define ML_HAS(feature) ((ML_FEATURES & (feature)) != 0u)

struct Hit {
    float3 p, ng, ns;
    float3 albedo, emission, transmissionColor;
    float roughness, metallic, ior, underRoughness;
    float transmission, transmissionRoughness, transmissionIor, coat, coatRoughness;
    float3 tangent;             // the direction a stretched lobe runs in, when anisotropy is not 0
    float3 subsurfaceRadius;    // mean distance light travels beneath the surface, per channel
    float3 absorption;          // what is left of light after absorptionDistance inside the solid
    float3 back, frontKeep;     // diffuse light passed through to the other side, and what that leaves on this one
    float fuzz, fuzzRoughness, fuzzDims;    // MoonRay's fuzz lobe over the others (DeviceMaterial)
    float3 fuzzColor;
    float anisotropy, subsurface, absorptionDistance, abbe;
    float specular;             // weight of the dielectric's reflection
    float t;
    unsigned flags;
    unsigned instance;
    int light;                  // the mesh light this surface belongs to, or -1
    int valid;
    int curve;                  // the hit is on a curve, which curveTangent runs along
    unsigned hair;              // with MATERIAL_HAIR, the material's entry among the hairs
    float curveCos;             // how squarely the ray met the strand: 1 on its middle, 0 at its edge
    float curveAlong, curveChance;  // how far along its strand the hit is, and the strand's own number
    float3 curveTangent;
    float3 lift;                // a toon surface's way up to the smooth surface its corner normals describe, or 0
};

ML_INLINE Hit* hitPayload() {
    return reinterpret_cast<Hit*>((static_cast<unsigned long long>(optixGetPayload_0()) << 32) | optixGetPayload_1());
}

// seen: the kind of ray this is, which finds only what is visible to its kind.
// With surfaces, the edges of fog are passed through: only what is there to see is found (HIT_SURFACES_ONLY).
const int HIT_SURFACES_ONLY = -2;
ML_INLINE void traceRadiance(float3 origin, float3 direction, Hit& hit, float distance = 1e16f, unsigned seen = SEEN_ALL,
                             bool surfaces = false) {
    const unsigned long long address = reinterpret_cast<unsigned long long>(&hit);
    unsigned p0 = unsigned(address >> 32), p1 = unsigned(address);
    hit.valid = surfaces ? HIT_SURFACES_ONLY : 0;
    optixTrace(params.traversable, origin, direction, 0.0f, distance, 0.0f, OptixVisibilityMask(seen),
               params.presence ? OPTIX_RAY_FLAG_NONE : OPTIX_RAY_FLAG_DISABLE_ANYHIT, 0, 1, 0, p0, p1);
    if (hit.valid == HIT_SURFACES_ONLY) hit.valid = 0;
}

// The second payload word gives the any-hit test of a partly absent surface its own random stream.
// It returns what is left of the light: nothing behind a surface, and behind fog what the fog lets through. The any-hit
// test adds up, in the other six payload words, the fog crossed: the distance to each edge it leaves less the distance
// to each it enters, times how much that fog stops, and how much the fogs entered and not left stop.
// How thick a fog is at a point: 1 all through an even one, the grid's value in one that has a grid.
ML_INLINE float fogDensity(const DeviceVolume& fog, float3 p) {
    if (!fog.grid) return 1.0f;
    return tex3D<float>(fog.grid, dot(vec(fog.rows), p) + fog.rows[3], dot(vec(fog.rows + 4), p) + fog.rows[7], dot(vec(fog.rows + 8), p) + fog.rows[11]);
}

// What the fogs that have grids let through along a ray. Each fills the unit cube its rows take the scene into, so
// where the ray is inside one is worked out from the cube, and any number of them may lie along the ray or overlap.
ML_INLINE float3 gridShadow(float3 origin, float3 direction, float distance, unsigned& seed, float thin) {
    float3 through = vec(1.0f);
    const DeviceVolume* fogs = reinterpret_cast<const DeviceVolume*>(params.volumes);
    for (unsigned i = 0; i < params.volumeCount; ++i) {
        const DeviceVolume& fog = fogs[i];
        if (!fog.grid) continue;
        float from = 0.0f, to = fminf(distance, 1e12f);
        for (int axis = 0; axis < 3 && to > from; ++axis) {
            const float* row = fog.rows + axis * 4;
            const float o = dot(vec(row), origin) + row[3], d = dot(vec(row), direction);
            if (fabsf(d) < 1e-12f) {
                if (o < 0.0f || o > 1.0f) to = -1.0f;
                continue;
            }
            const float a = -o / d, b = (1.0f - o) / d;
            from = fmaxf(from, fminf(a, b));
            to = fminf(to, fmaxf(a, b));
        }
        if (!(to > from)) continue;
        // Twenty-four steps along the stretch, each begun at a different place from ray to ray.
        const int steps = 24;
        const float step = (to - from) / steps;
        float thick = 0.0f, at = from + step * rnd(seed);
        for (int k = 0; k < steps; ++k, at += step) thick += fogDensity(fog, origin + direction * at);
        thick *= step * thin;
        through *= make_float3(expf(-thick * fog.extinction[0]), expf(-thick * fog.extinction[1]), expf(-thick * fog.extinction[2]));
    }
    return through;
}

// Whether a light reaches what is in a light set (LaunchParams::lightSets): bit 0 is the lighting environment, then
// each distant light, then each other light. Set 0 is every light.
ML_INLINE bool reaches(unsigned set, unsigned bit) {
    if (!set || !params.lightSets) return true;
    const unsigned* words = reinterpret_cast<const unsigned*>(params.lightSets) + size_t(set) * params.lightSetWords;
    return (words[bit >> 5] >> (bit & 31)) & 1u;
}

// thin scales what fog stops: MoonRay lets light that has already scattered in fog through more of it (its volume
// attenuation factor), which stands for the light that would have found its way round.
ML_INLINE float3 shadow(float3 origin, float3 direction, unsigned& seed, float distance = 1e16f, float thin = 1.0f) {
    // A fog with a grid is not the same all through, so the any-hit test only notes where the ray goes into it and
    // comes out, and which fog it is; what it stops is added up along that stretch below.
    unsigned unoccluded = 0, stream = seed, d0 = 0, d1 = 0, d2 = 0, e0 = 0, e1 = 0, e2 = 0;
    unsigned entered = __float_as_uint(0.0f), left = __float_as_uint(1e30f), gridded = 0;
    rnd(seed);
    optixTrace(params.traversable, origin, direction, 0.0f, distance, 0.0f, OptixVisibilityMask(SEEN_SHADOW),
               (params.presence ? OPTIX_RAY_FLAG_NONE : OPTIX_RAY_FLAG_DISABLE_ANYHIT)
               | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT | OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT,
               0, 1, 1, unoccluded, stream, d0, d1, d2, e0, e1, e2, entered, left, gridded);
    if (!unoccluded) return vec(0.0f);
    // Asked of every ray where there is any fog at all: one that starts and ends inside a grid crosses no edge of it.
    const float3 through = params.volumeCount ? gridShadow(origin, direction, distance, seed, thin) : vec(1.0f);
    if (!(d0 | d1 | d2 | e0 | e1 | e2)) return through;
    // A fog entered and never left is one the light itself is in: it is crossed from its edge to the ray's end.
    const float3 inside = make_float3(fmaxf(0.0f, __uint_as_float(e0)), fmaxf(0.0f, __uint_as_float(e1)), fmaxf(0.0f, __uint_as_float(e2)));
    const float3 depth = (make_float3(__uint_as_float(d0), __uint_as_float(d1), __uint_as_float(d2)) + inside * fminf(distance, 1e12f)) * thin;
    return through * make_float3(expf(-fmaxf(0.0f, depth.x)), expf(-fmaxf(0.0f, depth.y)), expf(-fmaxf(0.0f, depth.z)));
}

// Moves a ray origin off the surface, towards the side the ray leaves from.
ML_INLINE float3 offsetOrigin(float3 p, float3 ng, float3 direction) {
    const float scale = 1e-4f * (1.0f + fmaxf(fabsf(p.x), fmaxf(fabsf(p.y), fabsf(p.z))));
    return p + ng * (dot(ng, direction) > 0.0f ? scale : -scale);
}

// A toon's shadow ray toward a light near the terminator starts from the smooth surface, not the flat face, whose
// neighbours would otherwise shadow it: fully when the light is at or behind the face, none once it is 0.1 (in cosine)
// above it. As MoonRay patched for it (tools/port_toon_terminator.py).
ML_INLINE float3 shadowStart(float3 p, float3 lift, float3 ng, float3 ns, float3 direction) {
    if (dot(lift, lift) == 0.0f || dot(ns, direction) <= 0.0f || dot(lift, ns) < 0.0f) return p;
    if (dot(ns, ng) < 0.0f) ng = ng * -1.0f;
    return p + lift * clamp(1.0f - dot(ng, direction) / 0.1f, 0.0f, 1.0f);
}

// ---- Environment light -------------------------------------------------------------------------

ML_INLINE float3 envDirection(float u, float v) {
    const float phi = (u - 0.5f) * 2.0f * ML_PI, theta = v * ML_PI;
    const float sinTheta = sinf(theta);
    return make_float3(sinTheta * sinf(phi), cosf(theta), -sinTheta * cosf(phi));
}

ML_INLINE void envCoordinates(float3 direction, float& u, float& v) {
    u = atan2f(direction.x, -direction.z) / (2.0f * ML_PI) + 0.5f;
    v = acosf(clamp(direction.y, -1.0f, 1.0f)) / ML_PI;
}

ML_INLINE float3 envTexel(const float4* pixels, int x, int y) {
    const int w = int(params.envWidth), h = int(params.envHeight);
    x = ((x % w) + w) % w;
    y = y < 0 ? 0 : (y >= h ? h - 1 : y);
    const float4 c = pixels[y * w + x];
    return make_float3(c.x, c.y, c.z);
}

// Between world space and the space a map is indexed in.
ML_INLINE float3 envLocal(const float* rows, float3 d) {
    return make_float3(dot(d, vec(rows)), dot(d, vec(rows + 3)), dot(d, vec(rows + 6)));
}
ML_INLINE float3 envWorld(const float* rows, float3 d) {
    return vec(rows) * d.x + vec(rows + 3) * d.y + vec(rows + 6) * d.z;
}

ML_INLINE float3 envLookup(const float4* pixels, const float* rotation, float3 direction) {
    float u, v;
    envCoordinates(envLocal(rotation, direction), u, v);
    const float x = u * params.envWidth - 0.5f, y = v * params.envHeight - 0.5f;
    const float fx = floorf(x), fy = floorf(y);
    const int ix = int(fx), iy = int(fy);
    return lerp(lerp(envTexel(pixels, ix, iy), envTexel(pixels, ix + 1, iy), x - fx),
                lerp(envTexel(pixels, ix, iy + 1), envTexel(pixels, ix + 1, iy + 1), x - fx), y - fy);
}

ML_INLINE float3 envRadiance(float3 direction) {
    return envLookup(reinterpret_cast<const float4*>(params.envPixels), params.envRotation, direction);
}

// Density per unit (u, v) of the texel at (column, row), converted to solid angle.
ML_INLINE float envTexelPdf(unsigned column, unsigned row, float sinTheta) {
    const float* marginal = reinterpret_cast<const float*>(params.envMarginal);
    const float* conditional = reinterpret_cast<const float*>(params.envConditional) + row * (params.envWidth + 1);
    const float density = (marginal[row + 1] - marginal[row]) * (conditional[column + 1] - conditional[column])
                        * float(params.envWidth) * float(params.envHeight);
    return sinTheta > 1e-6f ? density / (2.0f * ML_PI * ML_PI * sinTheta) : 0.0f;
}

ML_INLINE float envPdf(float3 direction) {
    float u, v;
    direction = envLocal(params.envRotation, direction);
    envCoordinates(direction, u, v);
    const unsigned column = min(unsigned(u * params.envWidth), params.envWidth - 1);
    const unsigned row = min(unsigned(v * params.envHeight), params.envHeight - 1);
    return envTexelPdf(column, row, sqrtf(fmaxf(0.0f, 1.0f - direction.y * direction.y)));
}

// Largest i in [0, count) with cdf[i] <= value.
ML_INLINE unsigned findInterval(const float* cdf, unsigned count, float value) {
    unsigned low = 0, high = count;
    while (low + 1 < high) {
        const unsigned middle = (low + high) / 2;
        if (cdf[middle] <= value) low = middle; else high = middle;
    }
    return low;
}

ML_INLINE float3 sampleEnv(float u1, float u2, float& pdf) {
    const float* marginal = reinterpret_cast<const float*>(params.envMarginal);
    const unsigned row = findInterval(marginal, params.envHeight, u1);
    const float* conditional = reinterpret_cast<const float*>(params.envConditional) + row * (params.envWidth + 1);
    const unsigned column = findInterval(conditional, params.envWidth, u2);
    const float rowSpan = marginal[row + 1] - marginal[row], columnSpan = conditional[column + 1] - conditional[column];
    if (rowSpan <= 0.0f || columnSpan <= 0.0f) { pdf = 0.0f; return make_float3(0.0f, 1.0f, 0.0f); }
    const float u = (column + (u2 - conditional[column]) / columnSpan) / params.envWidth;
    const float v = (row + (u1 - marginal[row]) / rowSpan) / params.envHeight;
    pdf = envTexelPdf(column, row, sinf(v * ML_PI));
    return envWorld(params.envRotation, envDirection(u, v));
}

// ---- Where a light's picture is bright -----------------------------------------------------------
// A point of the unit square drawn in proportion to the picture's brightness there, and how likely that point was.
ML_INLINE float2 sampleGrid(DevicePtr distribution, float u1, float u2, float& density) {
    const float* grid = reinterpret_cast<const float*>(distribution);
    const unsigned width = unsigned(grid[0]), height = unsigned(grid[1]);
    const float* rows = grid + 2;
    const unsigned row = findInterval(rows, height, u1);
    const float* columns = rows + height + 1 + row * (width + 1);
    const unsigned column = findInterval(columns, width, u2);
    const float rowSpan = rows[row + 1] - rows[row], columnSpan = columns[column + 1] - columns[column];
    density = rowSpan * columnSpan * float(width) * float(height);
    if (!(density > 0.0f)) return make_float2(0.5f, 0.5f);
    return make_float2((column + (u2 - columns[column]) / columnSpan) / width, (row + (u1 - rows[row]) / rowSpan) / height);
}
ML_INLINE float gridDensity(DevicePtr distribution, float x, float y) {
    const float* grid = reinterpret_cast<const float*>(distribution);
    const unsigned width = unsigned(grid[0]), height = unsigned(grid[1]);
    if (x < 0.0f || x > 1.0f || y < 0.0f || y > 1.0f) return 0.0f;
    const unsigned column = min(unsigned(x * width), width - 1), row = min(unsigned(y * height), height - 1);
    const float* rows = grid + 2;
    const float* columns = rows + height + 1 + row * (width + 1);
    return (rows[row + 1] - rows[row]) * (columns[column + 1] - columns[column]) * float(width) * float(height);
}

// ---- Distant lights ----------------------------------------------------------------------------

// Where in its picture a distant light is seen along a direction, by MoonRay's equal-area mapping.
ML_INLINE float2 distantCoordinates(const DeviceDistantLight& light, float3 direction) {
    // In the light's frame, which MoonRay turns half way about x: the light stands along -z there.
    const float x = dot(direction, vec(light.u)), y = -dot(direction, vec(light.v)), z = -dot(direction, vec(light.direction));
    const float scale = -light.uvScale / sqrtf(fmaxf(1.0f - z, 1e-20f));
    return make_float2(1.0f - clamp(x * scale + 0.5f, 0.0f, 1.0f), 1.0f - clamp(y * scale + 0.5f, 0.0f, 1.0f));
}
// How likely sampleDistant is to choose a direction inside the disc.
ML_INLINE float distantPdf(const DeviceDistantLight& light, float3 direction) {
    if (!light.distribution) return 1.0f / (2.0f * ML_PI * light.versine);
    const float2 at = distantCoordinates(light, direction);
    // The picture's square covers the disc and its corners; a unit of it is 8 versines of solid angle.
    return gridDensity(light.distribution, at.x, at.y) * 0.125f / light.versine;
}

// A picture across the disc of a distant light, by MoonRay's equal-area mapping of the directions inside it.
ML_INLINE float3 distantRadiance(const DeviceDistantLight& light, float3 direction) {
    float3 radiance = vec(light.radiance);
    if (light.texture) {
        const float2 at = distantCoordinates(light, direction);
        const float4 texel = tex2D<float4>(light.texture, at.x, at.y);
        radiance = radiance * make_float3(texel.x, texel.y, texel.z);
    }
    return radiance;
}

// Uniform over the cap. The versine form stays accurate for the small angles a sun uses.
ML_INLINE float3 sampleDistant(const DeviceDistantLight& light, float u1, float u2) {
    if (light.distribution) {
        // Where the picture is bright, turned back into a direction as MoonRay's own inverse mapping does.
        float density;
        const float2 at = sampleGrid(light.distribution, u1, u2, density);
        const float s = 0.5f - at.x, t = 0.5f - at.y, spread = 4.0f * light.versine;
        const float z = -1.0f + spread * (s * s + t * t), scale = -sqrtf(fmaxf(0.0f, spread * (1.0f - z)));
        return normalize(vec(light.u) * (s * scale) - vec(light.v) * (t * scale) - vec(light.direction) * z);
    }
    const float versine = u1 * light.versine, phi = 2.0f * ML_PI * u2;
    const float sinTheta = sqrtf(versine * (2.0f - versine));
    return Frame(vec(light.direction)).toWorld(make_float3(sinTheta * cosf(phi), sinTheta * sinf(phi), 1.0f - versine));
}

// ---- Sphere, rectangle, disc, spot, cylinder, portal and mesh lights ---------------------------
// They light the scene and appear in reflections, but neither block rays nor show to the camera.
// A portal is a rectangle that shows the lighting environment; a mesh light is the surface of
// an object in the scene, so rays find it by hitting that object.

// MoonRay measures a spot's falloff where the line from the lens point through the shaded
// point meets the focal plane, with its default ease-in-out curve.
ML_INLINE float spotFalloff(const DeviceLight& light, float3 p, float3 onLens) {
    const float3 n = vec(light.normal), toPoint = p - onLens;
    const float depth = dot(toPoint, n);
    if (depth <= 0.0f) return 0.0f;
    // Only the offset from the axis matters; forming it directly avoids cancelling huge distances.
    const float3 offset = (onLens - vec(light.position)) + (toPoint - n * depth) * (light.focalDistance / depth);
    const float t = clamp((1.0f - length(offset) * light.rcpFocalRadius) * light.falloffGradient, 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

// Solid angle of a sphere seen from outside, as 1 - cos of its angular radius.
ML_INLINE float sphereVersine(float radiusSquared, float distanceSquared) {
    const float sinSquared = radiusSquared / distanceSquared;
    return sinSquared / (1.0f + sqrtf(fmaxf(0.0f, 1.0f - sinSquared)));
}

// Picks a direction from p towards the light; false if the light cannot reach p.
ML_INLINE bool sampleLightShape(const DeviceLight& light, float3 p, float u1, float u2,
                                float3& wi, float& distance, float& pdf, float3& radiance) {
    const float3 centre = vec(light.position);
    radiance = vec(light.radiance);
    if (light.type == LIGHT_SPHERE) {
        const float3 toCentre = centre - p;
        const float distanceSquared = dot(toCentre, toCentre), radiusSquared = light.radius * light.radius;
        if (distanceSquared <= radiusSquared) return false;
        const float capVersine = sphereVersine(radiusSquared, distanceSquared);
        const float versine = u1 * capVersine, phi = 2.0f * ML_PI * u2;
        const float sinTheta = sqrtf(versine * (2.0f - versine));
        wi = Frame(toCentre * (1.0f / sqrtf(distanceSquared))).toWorld(
            make_float3(sinTheta * cosf(phi), sinTheta * sinf(phi), 1.0f - versine));
        const float along = dot(toCentre, wi);
        distance = along - sqrtf(fmaxf(0.0f, radiusSquared - (distanceSquared - along * along)));
        pdf = 1.0f / (2.0f * ML_PI * capVersine);
        return true;
    }
    if (light.type == LIGHT_CYLINDER) {
        // Uniform over the side, as MoonRay samples it, or where its picture is bright; the ends do not emit.
        float phi = 2.0f * ML_PI * u1, along = 2.0f * u2 - 1.0f, density = 1.0f;
        if (light.distribution) {
            const float2 at = sampleGrid(light.distribution, u1, u2, density);
            if (!(density > 0.0f)) return false;
            along = 1.0f - 2.0f * at.x;
            phi = -2.0f * ML_PI * (1.0f - at.y);
        }
        const float3 outward = vec(light.u) * cosf(phi) + vec(light.normal) * sinf(phi);
        const float3 onSide = centre + outward * light.radius + vec(light.v) * (along * light.halfHeight);
        wi = onSide - p;
        distance = length(wi);
        if (distance <= 1e-6f) return false;
        wi = wi * (1.0f / distance);
        const float cosine = -dot(wi, outward);
        if (cosine <= 1e-6f) return false;
        pdf = density * distance * distance / (light.area * cosine);
        return true;
    }
    if (light.type == LIGHT_MESH) {
        // A triangle in proportion to its area, then a point on it.
        const float* triangles = reinterpret_cast<const float*>(light.triangles);
        unsigned low = 0, high = light.triangleCount - 1;
        while (low < high) {
            const unsigned middle = (low + high) / 2;
            if (u1 < triangles[middle * 10 + 9]) high = middle; else low = middle + 1;
        }
        const float* triangle = triangles + low * 10;
        const float before = low ? triangle[-1] : 0.0f, span = triangle[9] - before;
        float a = span > 0.0f ? clamp((u1 - before) / span, 0.0f, 1.0f) : 0.5f, b = u2;
        if (a + b > 1.0f) { a = 1.0f - a; b = 1.0f - b; }
        const float3 e1 = vec(triangle + 3), e2 = vec(triangle + 6);
        const float3 n = cross(e1, e2);
        wi = vec(triangle) + e1 * a + e2 * b - p;
        distance = length(wi);
        const float normalLength = length(n);
        if (distance <= 1e-6f || normalLength <= 0.0f) return false;
        wi = wi * (1.0f / distance);
        const float cosine = fabsf(dot(wi, n)) / normalLength;
        if (cosine <= 1e-6f) return false;
        pdf = distance * distance / (light.area * cosine);
        return true;
    }
    float3 onLight;
    // With a picture, a rectangle and a disc are sampled where it is bright: over the picture's square, which for a
    // disc is the square around it.
    float density = 1.0f, spread = light.area;
    if (light.distribution) {
        const float2 at = sampleGrid(light.distribution, u1, u2, density);
        const float a = 1.0f - 2.0f * at.x, b = 2.0f * at.y - 1.0f;
        if (!(density > 0.0f) || (light.type == LIGHT_DISK && a * a + b * b > 1.0f)) return false;
        const float reach = light.type == LIGHT_DISK ? light.radius : 1.0f;
        onLight = centre + (vec(light.u) * a + vec(light.v) * b) * reach;
        if (light.type == LIGHT_DISK) spread = 4.0f * light.radius * light.radius;
    } else if (light.type == LIGHT_RECT || light.type == LIGHT_PORTAL) {
        onLight = centre + vec(light.u) * (2.0f * u1 - 1.0f) + vec(light.v) * (2.0f * u2 - 1.0f);
    } else {
        const float r = light.radius * sqrtf(u1), phi = 2.0f * ML_PI * u2;
        onLight = centre + (vec(light.u) * cosf(phi) + vec(light.v) * sinf(phi)) * r;
    }
    wi = onLight - p;
    distance = length(wi);
    wi = wi * (1.0f / distance);
    const float cosine = -dot(wi, vec(light.normal));
    if (cosine <= 1e-6f) return false;
    pdf = density * distance * distance / (spread * cosine);
    if (light.type == LIGHT_SPOT) radiance = radiance * spotFalloff(light, p, onLight);
    if (light.type == LIGHT_PORTAL) {
        // The environment seen through the opening, which nothing beyond it may block.
        radiance = radiance * envRadiance(wi);
        distance = 1e16f;
    }
    return true;
}

// For a scattered ray: does it reach the light before maxDistance, and with what sampling density?
ML_INLINE bool hitLightShape(const DeviceLight& light, float3 p, float3 direction, float maxDistance,
                             float& pdf, float3& radiance, float& reached) {
    const float3 centre = vec(light.position);
    radiance = vec(light.radiance);
    if (light.type == LIGHT_SPHERE) {
        const float3 toCentre = centre - p;
        const float distanceSquared = dot(toCentre, toCentre), radiusSquared = light.radius * light.radius;
        const float along = dot(toCentre, direction);
        if (distanceSquared <= radiusSquared || along <= 0.0f) return false;
        const float discriminant = radiusSquared - (distanceSquared - along * along);
        if (discriminant < 0.0f || along - sqrtf(discriminant) >= maxDistance) return false;
        reached = along - sqrtf(discriminant);
        pdf = 1.0f / (2.0f * ML_PI * sphereVersine(radiusSquared, distanceSquared));
        return true;
    }
    if (light.type == LIGHT_MESH) return false;     // found by hitting its object instead
    if (light.type == LIGHT_CYLINDER) {
        // MoonRay's test for a cylinder lit on the outside only.
        const float3 axis = vec(light.v), toCentre = centre - p;
        const float a = dot(toCentre, axis), b = dot(direction, axis);
        if (a * (b < 0.0f ? -1.0f : 1.0f) <= -light.halfHeight) return false;
        const float along = dot(toCentre, direction) - a * b;
        const float outside = dot(toCentre, toCentre) - a * a - light.radius * light.radius;
        if (outside <= 0.0f || along <= 0.0f) return false;
        const float quadratic = 1.0f - b * b, discriminant = along * along - quadratic * outside;
        if (quadratic <= 0.0f || discriminant <= 0.0f) return false;
        const float distance = (along - sqrtf(discriminant)) / quadratic;
        if (distance < 0.0f || distance >= maxDistance) return false;
        const float y = distance * b - a;
        if (fabsf(y) > light.halfHeight) return false;
        const float3 outward = (direction * distance - toCentre - axis * y) * (1.0f / light.radius);
        const float cosine = -dot(direction, outward);
        if (cosine <= 1e-6f) return false;
        reached = distance;
        pdf = distance * distance / (light.area * cosine);
        if (light.distribution) {
            float around = atan2f(-dot(outward, vec(light.normal)), dot(outward, vec(light.u)));
            if (around < 0.0f) around += 2.0f * ML_PI;
            pdf *= gridDensity(light.distribution, 0.5f - 0.5f * y / light.halfHeight, 1.0f - around / (2.0f * ML_PI));
        }
        return true;
    }
    const float3 n = vec(light.normal);
    const float cosine = -dot(direction, n), height = dot(p - centre, n);
    if (cosine <= 1e-6f || height <= 0.0f) return false;
    const float distance = height / cosine;
    // A portal only passes rays that go on to reach the environment.
    if (light.type == LIGHT_PORTAL ? maxDistance < 1e29f : distance >= maxDistance) return false;
    const float3 onLight = p + direction * distance, offset = onLight - centre;
    if (light.type == LIGHT_RECT || light.type == LIGHT_PORTAL) {
        const float3 u = vec(light.u), v = vec(light.v);
        if (fabsf(dot(offset, u)) > dot(u, u) || fabsf(dot(offset, v)) > dot(v, v)) return false;
    } else if (dot(offset, offset) > light.radius * light.radius) return false;
    reached = distance;
    pdf = distance * distance / (light.area * cosine);
    if (light.distribution) {
        // As sampleLightShape chooses it: where the picture is bright, over the picture's square.
        const float3 u = vec(light.u), v = vec(light.v);
        const float across = light.type == LIGHT_DISK ? light.radius : dot(u, u), up = light.type == LIGHT_DISK ? light.radius : dot(v, v);
        const float spread = light.type == LIGHT_DISK ? 4.0f * light.radius * light.radius : light.area;
        pdf = gridDensity(light.distribution, 0.5f - 0.5f * dot(offset, u) / across, 0.5f + 0.5f * dot(offset, v) / up)
            * distance * distance / (spread * cosine);
    }
    if (light.type == LIGHT_SPOT) radiance = radiance * spotFalloff(light, p, onLight);
    if (light.type == LIGHT_PORTAL) radiance = radiance * envRadiance(direction);
    return true;
}

// MoonRay's bell for a blur: the camera's own quadratic B-spline, as a number from -1.5 to 1.5 for one from 0 to 1.
ML_INLINE float bellWarp(float r) {
    if (r < 1.0f / 6.0f) return powf(6.0f * r, 1.0f / 3.0f) - 1.5f;
    if (r >= 5.0f / 6.0f) return 1.5f - powf(6.0f * (1.0f - r), 1.0f / 3.0f);
    float u = (6.0f * r - 3.0f) / 4.0f;
    for (int j = 0; j < 4; ++j) u = (8.0f * u * u * u - 12.0f * r + 6.0f) / (12.0f * u * u - 9.0f);
    return u;
}

// What a light's picture and its filters make of the light travelling from it to p: the point
// on the light is distance along wi.
ML_INLINE float3 lightTint(const DeviceLight& light, float3 p, float3 wi, float distance) {
    float3 tint = vec(1.0f);
    if (light.texture) {
        // Where MoonRay looks its picture up for a point on each kind of light, from that light's own sources.
        const float3 onLight = p + wi * distance, offset = onLight - vec(light.position), u = vec(light.u), v = vec(light.v);
        float s, t;
        if (light.type == LIGHT_SPHERE) {
            // Latitude and longitude about the light's own y axis. MoonRay reads a picture laid round a sphere from
            // its top row down, where one laid flat is read from its bottom row up; hence the turned latitude.
            const float3 n = offset * (1.0f / light.radius);
            const float y = clamp(-dot(n, v), -1.0f, 1.0f);
            s = fabsf(y) >= 1.0f ? 0.0f : atan2f(dot(n, vec(light.normal)), -dot(n, u)) / (2.0f * ML_PI) + 0.5f;
            t = acosf(y) / ML_PI;
        } else if (light.type == LIGHT_CYLINDER) {
            // Along the axis, then around it from the light's own x.
            float around = atan2f(-dot(offset, vec(light.normal)), dot(offset, u));
            if (around < 0.0f) around += 2.0f * ML_PI;
            s = 0.5f + 0.5f * dot(offset, v) / light.halfHeight;
            t = around / (2.0f * ML_PI);
        } else if (light.type == LIGHT_SPOT) {
            // Across the focal plane, where the line from the lens point through p meets it.
            const float3 n = vec(light.normal), toPoint = p - onLight;
            const float depth = fmaxf(dot(toPoint, n), 1e-12f);
            const float3 focal = offset + (toPoint - n * depth) * (light.focalDistance / depth);
            s = 0.5f - 0.5f * dot(focal, u) * light.rcpFocalRadius;
            t = 0.5f + 0.5f * dot(focal, v) * light.rcpFocalRadius;
        } else {
            // A rectangle or a disc: across its width and its height, which for a disc are its diameter.
            const float across = light.type == LIGHT_DISK ? light.radius : dot(u, u), up = light.type == LIGHT_DISK ? light.radius : dot(v, v);
            s = 0.5f + 0.5f * dot(offset, u) / across;
            t = 0.5f - 0.5f * dot(offset, v) / up;
        }
        const float4 texel = tex2D<float4>(light.texture, 1.0f - s, 1.0f - t);
        tint = make_float3(texel.x, texel.y, texel.z);
    }
    const DeviceFilter* filters = reinterpret_cast<const DeviceFilter*>(params.lightFilters) + light.filterStart;
    for (unsigned i = 0; i < light.filterCount; ++i) {
        const DeviceFilter& filter = filters[i];
        if (filter.type == FILTER_DECAY) {
            // Fades in from near start to near end, and out from far start to far end.
            float value = 1.0f;
            if (((filter.flags & FILTER_NEAR) && distance < filter.a[0]) || ((filter.flags & FILTER_FAR) && distance > filter.a[3])) value = 0.0f;
            else if ((filter.flags & FILTER_NEAR) && distance < filter.a[1]) value = (distance - filter.a[0]) / (filter.a[1] - filter.a[0]);
            else if ((filter.flags & FILTER_FAR) && distance > filter.a[2]) value = (filter.a[3] - distance) / (filter.a[3] - filter.a[2]);
            tint = tint * value;
            continue;
        }
        if (filter.type == FILTER_ROD || filter.type == FILTER_BARN || filter.type == FILTER_COOKIE || filter.type == FILTER_VDB) {
            float3 local = make_float3(dot(vec(filter.rows), p) + filter.rows[3], dot(vec(filter.rows + 4), p) + filter.rows[7],
                                       dot(vec(filter.rows + 8), p) + filter.rows[11]);
            // What is random about a blur: its own for each point, each sample and each filter.
            unsigned blur = tea(__float_as_uint(p.x) ^ (__float_as_uint(p.y) * 0x9e3779b9u) ^ (__float_as_uint(p.z) * 0x85ebca6bu), params.sample * 16u + i);
            if (filter.type == FILTER_ROD) {
                // A box with rounded corners: inside it the light takes the rod's colour, and fades back over its edge.
                const float3 q = make_float3(fabsf(local.x) - filter.a[0], fabsf(local.y) - filter.a[1], fabsf(local.z) - filter.a[2]);
                const float r = length(make_float3(fmaxf(q.x, 0.0f), fmaxf(q.y, 0.0f), fmaxf(q.z, 0.0f))) + fminf(fmaxf(q.x, fmaxf(q.y, q.z)), 0.0f) - filter.a[3];
                float scale = r <= 0.0f ? 0.0f : r < filter.b[0] ? r / filter.b[0] : 1.0f;
                // The rod's own way of fading over its edge, where it has one.
                if (filter.ramp && r > 0.0f && r < filter.b[0]) scale = tex2D<float4>(filter.ramp, (scale * 256.0f + 0.5f) / 257.0f, 0.5f).x;
                if (filter.flags & FILTER_INVERT) scale = 1.0f - scale;
                scale = 1.0f + (scale - 1.0f) * filter.b[1];
                const float3 colour = vec(filter.b + 2);
                tint = tint * (colour + (vec(1.0f) - colour) * scale);
                continue;
            }
            if (filter.type == FILTER_VDB) {
                // A grid of densities: where it is full the light passes as it is; where it is empty it takes the tint.
                if (filter.b[3] > 0.0f) {
                    // Blurred: looked up a little way off, by the bell or anywhere in a ball.
                    float3 off;
                    if (filter.flags & FILTER_ROUND) {
                        const float z = 1.0f - 2.0f * rnd(blur), around = 2.0f * ML_PI * rnd(blur), flat = sqrtf(fmaxf(0.0f, 1.0f - z * z));
                        off = make_float3(flat * cosf(around), flat * sinf(around), z) * powf(rnd(blur), 1.0f / 3.0f);
                    } else {
                        off = make_float3(bellWarp(rnd(blur)), bellWarp(rnd(blur)), bellWarp(rnd(blur)));
                    }
                    local = local + make_float3(off.x * filter.b[4], off.y * filter.b[5], off.z * filter.b[6]) * filter.b[3];
                }
                float density = tex3D<float>(filter.texture, local.x, local.y, local.z);
                if (filter.flags & FILTER_INVERT) density = 1.0f - density;
                if (filter.ramp) density = tex2D<float4>(filter.ramp, (clamp((density - filter.a[0]) / (filter.a[1] - filter.a[0]), 0.0f, 1.0f) * 256.0f + 0.5f) / 257.0f, 0.5f).x;
                density = fmaxf(density, 0.0f);
                const float3 colour = vec(filter.b);
                tint = tint * (colour + (vec(1.0f) - colour) * density);
                continue;
            }
            if (filter.type == FILTER_COOKIE) {
                // A picture thrown from a projector: local is the point's place across it, up it, and what divides both.
                const float outside = (filter.flags & FILTER_WHITE) ? 1.0f : 0.0f;
                if (!(local.z > 0.0f)) {
                    tint = tint * outside;
                    continue;
                }
                float s = local.x / local.z, t = local.y / local.z;
                if (filter.b[7] > 0.0f || filter.b[8] > 0.0f || filter.b[9] > 0.0f) {
                    // Blurred by how far the point is from the projector: one blur near, one at the middle, one far.
                    const float far = length(p - vec(filter.b + 1));
                    float wide = filter.b[9];
                    if (far <= filter.b[4]) wide = filter.b[7];
                    else if (far <= filter.b[5]) wide = filter.b[5] > filter.b[4] ? filter.b[7] + (filter.b[8] - filter.b[7]) * (far - filter.b[4]) / (filter.b[5] - filter.b[4]) : filter.b[8];
                    else if (far <= filter.b[6]) wide = filter.b[6] > filter.b[5] ? filter.b[8] + (filter.b[9] - filter.b[8]) * (far - filter.b[5]) / (filter.b[6] - filter.b[5]) : filter.b[9];
                    if (filter.flags & FILTER_ROUND) {
                        const float out = sqrtf(rnd(blur)), around = 2.0f * ML_PI * rnd(blur);
                        s += out * cosf(around) * wide;
                        t += out * sinf(around) * wide;
                    } else {
                        s += bellWarp(rnd(blur)) * wide;
                        t += bellWarp(rnd(blur)) * wide;
                    }
                }
                if ((s < 0.0f || s > 1.0f || t < 0.0f || t > 1.0f) && !(filter.flags & FILTER_EDGELESS)) {
                    tint = tint * outside;
                    continue;
                }
                // MoonRay reads a cookie's picture from its top row down, as it does one laid round a sphere.
                const float4 texel = tex2D<float4>(filter.texture, s, t);
                float3 value = vec(1.0f - filter.b[0]) + make_float3(texel.x, texel.y, texel.z) * filter.b[0];
                if (filter.flags & FILTER_INVERT) value = vec(1.0f) - value;
                tint = tint * value;
                continue;
            }
            // Barn doors: an opening in front of a projector, seen from the point; the light is what comes through.
            if (!(local.z > 0.0f)) {
                tint = vec(0.0f);
                continue;
            }
            float3 at = local;
            if (filter.flags & FILTER_PHYSICAL) {
                // Where the ray to the light crosses the plane the doors stand in.
                const float3 way = make_float3(dot(vec(filter.rows), wi), dot(vec(filter.rows + 4), wi), dot(vec(filter.rows + 8), wi));
                if (fabsf(way.z) > 1e-9f) at = at + way * ((filter.b[5] - at.z) / way.z);
            }
            const float over = (filter.flags & FILTER_ORTHO) ? 1.0f : 1.0f / at.z;
            const float x = at.x * over, y = -at.y * over;
            const float dx = x - clamp(x, filter.a[0], filter.a[2]), dy = y - clamp(y, filter.a[1], filter.a[3]);
            const float sx = dx * filter.b[dx < 0.0f ? 1 : 3], sy = dy * filter.b[dy < 0.0f ? 2 : 4];
            const float r = sqrtf(dx * dx + dy * dy), scaled = sqrtf(sx * sx + sy * sy);
            const float r0 = filter.b[0], r1 = scaled > 0.0f ? r / scaled : 0.0f;
            float scale = 0.0f;
            if (r <= r0) scale = 1.0f;
            else if (r < r1) {
                // The edge falls off as a blurred step does: the bell curve's running total, stretched to reach 0 and 1.
                const float low = 0.5f * (1.0f + erff(-1.0f / sqrtf(0.2f)));
                const float value = 0.5f * (1.0f + erff((1.0f - 2.0f * (r - r0) / (r1 - r0)) / sqrtf(0.2f)));
                scale = value * (1.0f + 2.0f * low) - low;
            }
            if (filter.flags & FILTER_INVERT) scale = 1.0f - scale;
            tint = tint * (vec(1.0f) + (vec(filter.b + 6) * scale - vec(1.0f)) * filter.b[9]);
            continue;
        }
        // A colour by distance: from the light or the filter, or along the way either faces.
        float along = distance;
        if (filter.flags & FILTER_PLACED) {
            const float3 local = make_float3(dot(vec(filter.rows), p) + filter.rows[3], dot(vec(filter.rows + 4), p) + filter.rows[7],
                                             dot(vec(filter.rows + 8), p) + filter.rows[11]);
            along = (filter.flags & FILTER_DIRECTIONAL) ? -local.z : length(local);
        } else if (filter.flags & FILTER_DIRECTIONAL) {
            along = dot(p - vec(light.position), vec(light.normal));
        }
        if (filter.flags & FILTER_DIRECTIONAL) along = (filter.flags & FILTER_MIRROR) ? fabsf(along) : fmaxf(along, 0.0f);
        const float t = clamp((along - filter.a[0]) / (filter.a[1] - filter.a[0]), 0.0f, 1.0f);
        const float4 texel = tex2D<float4>(filter.texture, (t * 256.0f + 0.5f) / 257.0f, 0.5f);
        tint = tint * (vec(1.0f - filter.a[3]) + make_float3(texel.x, texel.y, texel.z) * (filter.a[2] * filter.a[3]));
    }
    return tint;
}

ML_INLINE bool sampleLight(const DeviceLight& light, float3 p, float u1, float u2,
                           float3& wi, float& distance, float& pdf, float3& radiance) {
    if (!sampleLightShape(light, p, u1, u2, wi, distance, pdf, radiance)) return false;
    if (light.texture || light.filterCount) radiance = radiance * lightTint(light, p, wi, distance);
    return true;
}

ML_INLINE bool hitLight(const DeviceLight& light, float3 p, float3 direction, float maxDistance,
                        float& pdf, float3& radiance) {
    float reached = 0.0f;
    if (!hitLightShape(light, p, direction, maxDistance, pdf, radiance, reached)) return false;
    if (light.texture || light.filterCount) radiance = radiance * lightTint(light, p, direction, reached);
    return true;
}

// With many lights, each bounce samples one of them, chosen in proportion to its power.
ML_INLINE unsigned pickLight(const DeviceLight* lights, unsigned count, float u) {
    unsigned low = 0, high = count - 1;
    while (low < high) {
        const unsigned middle = (low + high) / 2;
        if (u < lights[middle].cumulative) high = middle; else low = middle + 1;
    }
    return low;
}

// ---- Uber-shader -------------------------------------------------------------------------------
// A clearcoat over a GGX specular lobe over Lambert diffuse, with the part of the light that
// enters the surface optionally refracted through it instead. The lobes and how they combine
// follow MoonRay's UsdPreviewSurface and, for material stacks, DwaBaseMaterial.

struct Surface {
    float3 albedo;
    float3 transmissionColor;
    float metallic;
    float ior;
    float specular;         // weight of the dielectric's reflection; the coat's is its own
    float alpha;
    float underBlend;       // how far the diffuse attenuation moves to its normal-incidence value
    float transmission;
    float transmissionAlpha;
    float transmissionIor;
    float coat;
    float coatAlpha;
    bool coatDims;          // the coat takes its reflection out of what is beneath it
    bool thin;
    bool beckmann;          // the specular lobe's distribution; the coat is always GGX
    bool conductor;         // a metal's reflection follows DwaBaseMaterial's curve
    bool matte;             // light coming out from beneath the surface: diffuse only
    float roughness;
    float alphaX, alphaY;   // the Beckmann lobe's width along and across the surface tangent
    float diffuseScale;     // 0 while the diffuse light is being gathered beneath the surface instead
    float3 back, frontKeep; // diffuse light passed through to the other side, and what that leaves on this one
    bool passes;            // some does
    // MoonRay's fuzz: how much, its colour, its roughness, the normalization of its lobe and what it takes from beneath.
    float fuzz, fuzzRoughness, fuzzNormalization, fuzzDims;
    float3 fuzzColor;
    float3 diffuseNormal;   // the normal diffuse light falls on, in the shading frame
    // MoonRay's toon material: its ramps, and which of the diffuse light and the highlight they band.
    const DeviceToon* toon;
    bool toonDiffuse, toonSpecular;
    float3 toonAlong;       // the way a strand runs (a surface's u direction), in the shading frame: a hair toon's highlight
    bool smoothToon;        // a toon lit by its smooth normals, not its faces' (params.toonTerminator)
};

ML_INLINE Surface surfaceFrom(const Hit& hit) {
    Surface s;
    s.albedo = hit.albedo;
    s.transmissionColor = hit.transmissionColor;
    s.metallic = hit.metallic;
    s.ior = fmaxf(hit.ior, 1.0001f);
    s.specular = hit.specular;
    s.alpha = fmaxf(hit.roughness * hit.roughness, 0.002f);
    const float smooth = 1.0f - hit.underRoughness * hit.underRoughness;
    s.underBlend = clamp(1.0f - smooth * smooth * smooth, 0.0f, 1.0f);
    s.transmission = hit.transmission;
    s.transmissionAlpha = fmaxf(hit.transmissionRoughness * hit.transmissionRoughness, 0.0f);
    s.transmissionIor = fmaxf(hit.transmissionIor, 1.0001f);
    s.coat = hit.coat;
    s.coatAlpha = fmaxf(hit.coatRoughness * hit.coatRoughness, 0.002f);
    s.coatDims = (hit.flags & MATERIAL_COAT_DIMS) != 0;
    s.thin = (hit.flags & MATERIAL_THIN) != 0;
    s.beckmann = (hit.flags & MATERIAL_BECKMANN) != 0;
    s.conductor = (hit.flags & MATERIAL_CONDUCTOR) != 0;
    s.matte = (hit.flags & MATERIAL_MATTE) != 0;
    s.roughness = sqrtf(s.alpha);
    s.alphaX = s.alphaY = s.alpha;
    if (hit.anisotropy != 0.0f) {
        // DwaBaseMaterial narrows the lobe along the tangent for a positive value, across it for
        // a negative one.
        const float along = hit.anisotropy > 0.0f ? hit.roughness * (1.0f - hit.anisotropy) : hit.roughness;
        const float across = hit.anisotropy < 0.0f ? hit.roughness * (1.0f + hit.anisotropy) : hit.roughness;
        s.alphaX = fmaxf(along * along, 0.001f);
        s.alphaY = fmaxf(across * across, 0.001f);
        s.roughness = sqrtf(sqrtf(s.alphaX * s.alphaY));
    }
    s.diffuseScale = 1.0f;
    s.back = hit.back;
    s.frontKeep = hit.frontKeep;
    s.passes = maxComponent(hit.back) > 0.0f;
    s.fuzz = ML_HAS(FEATURE_FUZZ) ? hit.fuzz : 0.0f;
    s.fuzzColor = hit.fuzzColor;
    s.fuzzRoughness = hit.fuzzRoughness;
    s.fuzzDims = hit.fuzzDims;
    // As MoonRay's FabricVelvetBsdfLobe picks its row of the table.
    s.fuzzNormalization = 1.0f / VELVET_NORMALIZATION[min(max(int(floorf(hit.fuzzRoughness * VELVET_NORMALIZATION_STEPS - 1.0f)), 0),
                                                          int(VELVET_NORMALIZATION_STEPS) - 1)];
    // On a strand as on a surface: MoonRay's own strand is a ribbon facing the ray, which a toon look shades as a surface.
    const bool toon = ML_HAS(FEATURE_TOON) && (hit.flags & (MATERIAL_TOON_DIFFUSE | MATERIAL_TOON_SPECULAR)) && !(hit.flags & (MATERIAL_HAIR | MATERIAL_VOLUME));
    s.toon = toon ? reinterpret_cast<const DeviceToon*>(params.toons) + hit.hair : nullptr;
    s.toonDiffuse = toon && (hit.flags & MATERIAL_TOON_DIFFUSE);
    s.smoothToon = s.toonDiffuse && params.toonTerminator;
    s.toonSpecular = toon && (hit.flags & MATERIAL_TOON_SPECULAR);
    s.toonAlong = make_float3(1.0f, 0.0f, 0.0f);
    return s;
}
// Where along a toon ramp a value falls: past its end, the end.
ML_INLINE unsigned toonStep(float x) {
    return x <= 0.0f ? 0u : min(unsigned(x * float(TOON_STEPS)), TOON_STEPS - 1);
}

// Unpolarized Fresnel reflectance crossing from a medium of index etaI into one of etaT; 1 when
// the light cannot cross.
ML_INLINE float fresnel(float cosine, float etaI, float etaT) {
    cosine = clamp(cosine, 0.0f, 1.0f);
    const float sinSquaredT = (etaI / etaT) * (etaI / etaT) * (1.0f - cosine * cosine);
    if (sinSquaredT >= 1.0f) return 1.0f;
    const float cosT = sqrtf(1.0f - sinSquaredT);
    const float parallel = (etaT * cosine - etaI * cosT) / (etaT * cosine + etaI * cosT);
    const float perpendicular = (etaI * cosine - etaT * cosT) / (etaI * cosine + etaT * cosT);
    return 0.5f * (parallel * parallel + perpendicular * perpendicular);
}
ML_INLINE float dielectricFresnel(float cosine, float ior) { return fresnel(cosine, 1.0f, ior); }
ML_INLINE float3 schlick(float3 f0, float cosine) {
    const float m = clamp(1.0f - cosine, 0.0f, 1.0f);
    return f0 + (vec(1.0f) - f0) * (m * m * m * m * m);
}
// How much a metal reflects at an angle, as MoonRay works it out for DwaBaseMaterial: the colour seen straight on
// and a white edge are turned into a complex index of refraction (Gulbrandsen, "Artist Friendly Metallic
// Fresnel"), which then reflects as a real conductor does. It lightens toward the edge sooner than Schlick's curve.
ML_INLINE float conductorChannel(float reflectance, float cosine) {
    const float r = clamp(reflectance, 0.0f, 0.999f), edge = 0.999f;
    const float root = sqrtf(r);
    const float n = edge * (1.0f - r) / (1.0f + r) + (1.0f - edge) * (1.0f + root) / (1.0f - root);
    const float k2 = fmaxf(0.0f, r * (n + 1.0f) * (n + 1.0f) - (n - 1.0f) * (n - 1.0f)) / (1.0f - r);
    const float c = clamp(cosine, 0.0f, 1.0f), cos2 = c * c, sin2 = 1.0f - cos2, n2 = n * n;
    const float t0 = n2 - k2 - sin2;
    const float both = sqrtf(t0 * t0 + 4.0f * n2 * k2);
    const float t1 = both + cos2;
    const float t2 = 2.0f * sqrtf(fmaxf(0.0f, 0.5f * (both + t0))) * c;
    const float across = (t1 - t2) / fmaxf(t1 + t2, 1e-12f);
    const float t3 = cos2 * both + sin2 * sin2, t4 = t2 * sin2;
    return 0.5f * (across + across * (t3 - t4) / fmaxf(t3 + t4, 1e-12f));
}
ML_INLINE float3 conductorFresnel(float3 reflectance, float cosine) {
    return make_float3(conductorChannel(reflectance.x, cosine), conductorChannel(reflectance.y, cosine), conductorChannel(reflectance.z, cosine));
}
// A conductor of the base colour weighted by metallic, over a dielectric.
ML_INLINE float3 specularFresnel(const Surface& s, float cosine) {
    if (s.metallic <= 0.0f) return vec(s.specular * dielectricFresnel(cosine, s.ior));
    return lerp(vec(s.specular * dielectricFresnel(cosine, s.ior)), s.conductor ? conductorFresnel(s.albedo, cosine) : schlick(s.albedo, cosine), s.metallic);
}
// What reaches the lobes under the coat, and comes out of it again. MoonRay's clearcoat bends light (its
// clearcoat_bending, on unless switched off), and what is under such a coat is dimmed twice: by what the coat reflects
// of the light going in, in proportion to how much coat there is, and by what it turns back of the light coming out,
// which is the whole of a dielectric's reflection as soon as there is any coat at all (UnderClearcoatBsdfLobe).
// A clear coat's index of refraction: DwaBaseMaterial's clearcoat_refractive_index, which the plugin leaves at its
// default. Not the specular's, which a stack sets for the most any of its rows reflects and may be far higher.
#define COAT_IOR 1.5f

ML_INLINE float underCoat(const Surface& s, float3 wo) {
    if (!s.coatDims) return 1.0f;
    const float reflected = dielectricFresnel(wo.z, COAT_IOR);
    return (1.0f - s.coat * reflected) * (s.coat > 0.0f ? 1.0f - reflected : 1.0f);
}
// The light the coat turns back goes down to what is under it again, and some of that comes out at the next try, and
// so on: MoonRay adds the series up, by the share of light the lobe beneath sends back.
ML_INLINE float3 coatBounces(const Surface& s, float3 wo, float3 albedo) {
    if (!s.coatDims || s.coat <= 0.0f) return vec(1.0f);
    const float reflected = dielectricFresnel(wo.z, COAT_IOR);
    return make_float3(1.0f / fmaxf(1.0f - reflected * albedo.x, 0.01f), 1.0f / fmaxf(1.0f - reflected * albedo.y, 0.01f),
                       1.0f / fmaxf(1.0f - reflected * albedo.z, 0.01f));
}
// How much MoonRay's fuzz reflects seen from an angle (VelvetAlbedo::at), read from its table as MoonRay reads it: the
// two rows about the roughness blended by the roughness itself, and the angle's column truncated.
ML_INLINE float velvetAlbedo(float cosine, float roughness) {
    roughness = clamp(roughness, 0.0f, 1.0f);
    const int below = int(floorf(roughness * VELVET_ALBEDO_ROUGHNESS_STEPS - 1.0f)), above = int(ceilf(roughness * VELVET_ALBEDO_ROUGHNESS_STEPS - 1.0f));
    const int column = int(clamp(cosine, 0.0f, 1.0f) * VELVET_ALBEDO_COS_STEPS - 1.0f);
    const int last = int(VELVET_ALBEDO_COS_STEPS * VELVET_ALBEDO_ROUGHNESS_STEPS) - 1;
    const float a = VELVET_ALBEDO[min(max(below * int(VELVET_ALBEDO_COS_STEPS) + column, 0), last)];
    const float b = VELVET_ALBEDO[min(max(above * int(VELVET_ALBEDO_COS_STEPS) + column, 0), last)];
    const float blend = roughness - floorf(roughness);
    return a * (1.0f - blend) + b * blend;
}
// What the fuzz, the topmost lobe, leaves of the light for the lobes beneath it (MoonRay's OneMinusVelvetFresnel).
ML_INLINE float underFuzz(const Surface& s, float3 wo) {
    return s.fuzz > 0.0f ? 1.0f - velvetAlbedo(wo.z, s.fuzzRoughness) * s.fuzzDims : 1.0f;
}
// bsdf * cosine of the fuzz (MoonRay's FabricVelvetBsdfLobe): sin(N, H) to the power of one over its roughness,
// normalized, and softened by one more cosine of the light toward the shadow's edge, as MoonRay does.
ML_INLINE float3 fuzzLobe(const Surface& s, float3 wo, float3 wi) {
    if (s.fuzz <= 0.0f || wi.z <= 1e-6f || wo.z <= 1e-6f) return vec(0.0f);
    const float3 h = normalize(wo + wi);
    const float c = clamp(h.z, -0.99f, 0.99f);
    const float velvet = s.fuzzNormalization * powf(sqrtf(1.0f - c * c), 1.0f / s.fuzzRoughness) * wi.z;
    return s.fuzzColor * (s.fuzz * velvet * wi.z);
}
// What the dielectric lets through to whatever is beneath it. MoonRay evaluates this on the
// view direction and blends towards normal incidence as the lobe above gets rougher.
ML_INLINE float entering(const Surface& s, float3 wo) {
    const float grazing = 1.0f - s.specular * dielectricFresnel(wo.z, s.ior), facing = 1.0f - s.specular * dielectricFresnel(1.0f, s.ior);
    return (1.0f - s.metallic) * (grazing + (facing - grazing) * s.underBlend) * underCoat(s, wo) * underFuzz(s, wo);
}
// What a hair toon's highlight lets through to the layers under it: one less its glass-like reflection, blended towards
// its value straight on as the highlight's roughness grows, as MoonRay's OneMinusRoughFresnel has it.
ML_INLINE float toonPass(const DeviceToon& toon, float cosine) {
    if (!toon.plain) return 1.0f;
    const float grazing = 1.0f - dielectricFresnel(cosine, 1.5f), facing = 1.0f - dielectricFresnel(1.0f, 1.5f);
    return grazing + (facing - grazing) * toon.underBlend;
}
ML_INLINE float3 diffuseColor(const Surface& s, float3 wo) {
    const float3 colour = s.albedo * s.frontKeep;
    return colour * coatBounces(s, wo, colour) * (entering(s, wo) * (1.0f - s.transmission) * s.diffuseScale);
}
// Diffuse light that comes out of the far side of something thin, as DwaBaseMaterial's diffuse transmission.
ML_INLINE float3 backColor(const Surface& s, float3 wo) {
    return s.back * (entering(s, wo) * (1.0f - s.transmission));
}
// The share of the light that is refracted through the surface rather than scattered at it.
ML_INLINE float transmitted(const Surface& s, float3 wo) {
    return entering(s, wo) * s.transmission;
}
ML_INLINE float ggxD(float alpha, float nh) {
    const float a2 = alpha * alpha, d = nh * nh * (a2 - 1.0f) + 1.0f;
    return a2 / (ML_PI * d * d);
}
ML_INLINE float smithG1(float alpha, float nv) {
    const float a2 = alpha * alpha;
    return 2.0f * nv / (nv + sqrtf(a2 + (1.0f - a2) * nv * nv));
}
// The Beckmann distribution and its shadowing, as MoonRay's Cook-Torrance lobe evaluates them
// (Walter et al. 2007, with the rational approximation of the shadowing term).
// Both take a width along each axis of the shading frame, which differ for a stretched lobe.
ML_INLINE float beckmannD(float alphaX, float alphaY, float3 h) {
    const float c2 = h.z * h.z;
    if (c2 <= 0.0f) return 0.0f;
    const float slope = (h.x * h.x / (alphaX * alphaX) + h.y * h.y / (alphaY * alphaY)) / c2;
    return expf(-slope) / (ML_PI * alphaX * alphaY * c2 * c2);
}
ML_INLINE float beckmannG1(float alphaX, float alphaY, float3 v) {
    const float a = v.z / sqrtf(fmaxf(1e-12f, v.x * v.x * alphaX * alphaX + v.y * v.y * alphaY * alphaY));
    return a < 1.6f ? (3.535f * a + 2.181f * a * a) / (1.0f + 2.276f * a + 2.577f * a * a) : 1.0f;
}

// Light that bounces between facets before leaving is missing from a single-scattering lobe.
// MoonRay adds it back as a broad lobe (Kelemen 2001, as in Kulla and Conty 2017), using the
// lobe's tabulated albedo.
ML_INLINE float lobeAlbedo(const Surface& s, float cosine) {
    const float* table = reinterpret_cast<const float*>(params.albedo2) + (s.beckmann ? ALBEDO_TABLE : 0);
    const float x = clamp(s.roughness, 0.0f, 1.0f) * (ALBEDO_STEPS - 1), y = clamp(cosine, 0.0f, 1.0f) * (ALBEDO_STEPS - 1);
    const unsigned x0 = min(unsigned(x), ALBEDO_STEPS - 2), y0 = min(unsigned(y), ALBEDO_STEPS - 2);
    const float fx = x - x0, fy = y - y0;
    const float* row0 = table + x0 * ALBEDO_STEPS;
    const float* row1 = row0 + ALBEDO_STEPS;
    return (row0[y0] * (1.0f - fy) + row0[y0 + 1] * fy) * (1.0f - fx) + (row1[y0] * (1.0f - fy) + row1[y0 + 1] * fy) * fx;
}
ML_INLINE float lobeAverageAlbedo(const Surface& s) {
    const float* table = reinterpret_cast<const float*>(params.albedo2) + (s.beckmann ? ALBEDO_TABLE : 0) + ALBEDO_STEPS * ALBEDO_STEPS;
    const float x = clamp(s.roughness, 0.0f, 1.0f) * (ALBEDO_STEPS - 1);
    const unsigned x0 = min(unsigned(x), ALBEDO_STEPS - 2);
    return table[x0] + (table[x0 + 1] - table[x0]) * (x - x0);
}
// bsdf * cosine of that extra lobe.
ML_INLINE float3 multipleScattering(const Surface& s, float3 wo, float3 wi) {
    // MoonRay only adds it where it also samples it, which is above a roughness of one half.
    if (s.roughness <= 0.5f) return vec(0.0f);
    const float average = lobeAverageAlbedo(s);
    if (average >= 0.9999f) return vec(0.0f);
    // The mean Fresnel reflectance over all angles, for the dielectric and for the metal.
    const float r = (s.ior - 1.0f) / (s.ior + 1.0f);
    const float3 f0 = lerp(vec(s.specular * r * r), s.albedo, s.metallic);
    const float3 mean = f0 + (vec(1.0f) - f0) * (1.0f / 21.0f);
    const float3 tint = make_float3(mean.x * mean.x * average / (1.0f - mean.x * (1.0f - average)),
                                    mean.y * mean.y * average / (1.0f - mean.y * (1.0f - average)),
                                    mean.z * mean.z * average / (1.0f - mean.z * (1.0f - average)));
    return tint * ((1.0f - lobeAlbedo(s, wo.z)) * (1.0f - lobeAlbedo(s, wi.z)) / (ML_PI * (1.0f - average)) * wi.z);
}
// MoonRay gives that lobe a share of the specular samples once the surface is rough.
ML_INLINE float broadShare(const Surface& s) { return fminf(fmaxf(0.0f, s.roughness - 0.5f), 0.5f); }

// How the reflective lobes share the samples: specular against diffuse, and the coat's part
// of the specular samples.
struct Lobes {
    float specular;
    float coat;
    float back;     // the share of the diffuse samples that go through to the far side
    float sheen;    // the share of the others that lean towards the side the view comes from, for the fuzz
};
ML_INLINE Lobes lobeWeights(const Surface& s, float3 wo) {
    const float fuzz = underFuzz(s, wo);
    const float coat = s.coat * dielectricFresnel(wo.z, COAT_IOR) * fuzz;
    const float specular = luminance(specularFresnel(s, wo.z)) * underCoat(s, wo) * fuzz;
    const float sheen = s.fuzz > 0.0f ? luminance(s.fuzzColor) * s.fuzz * velvetAlbedo(wo.z, s.fuzzRoughness) : 0.0f;
    const float front = luminance(diffuseColor(s, wo)) + sheen;
    const float behind = s.passes ? luminance(backColor(s, wo)) : 0.0f;
    const float diffuse = front + behind;
    Lobes lobes;
    lobes.back = behind > 0.0f ? behind / diffuse : 0.0f;
    lobes.sheen = front > 0.0f ? sheen / front : 0.0f;
    lobes.coat = coat + specular > 0.0f ? coat / (coat + specular) : 0.0f;
    lobes.specular = s.matte ? 0.0f : diffuse <= 0.0f ? 1.0f : clamp((coat + specular) / (coat + specular + diffuse), 0.1f, 0.9f);
    if (s.toonSpecular) {
        // A toon highlight is found from the lights alone, as MoonRay finds it: no sample is spent looking for it.
        lobes.coat = coat > 0.0f ? 1.0f : 0.0f;
        lobes.specular = s.matte || coat <= 0.0f ? 0.0f : diffuse <= 0.0f ? 1.0f : clamp(coat / (coat + diffuse), 0.1f, 0.9f);
    }
    return lobes;
}

// bsdf * cosine of the diffuse and of the mirror-like lobes for local directions (z is the
// shading normal), and the density with which each group's own sampling would have chosen wi.
struct BsdfEval {
    float3 diffuse, specular;
    float diffusePdf, specularPdf;
    // A toon highlight, which only the lights' own samples find. MoonRay still gives it a density, as if a sample
    // could have found it, and weighs the lights' samples by that: a broad light then gives it little, a small
    // one nearly all.
    float3 toon;
    float toonPdf;
};
ML_INLINE float powerHeuristic(float a, float b);
ML_INLINE float hairLongitudinal(float variance, float sinI, float cosI, float sinO, float cosO);
// What a light's sample is worth at a surface, over the density it was drawn with: the lobes that a sample of the
// surface could have found as well, and a toon highlight.
ML_INLINE float3 litBy(const BsdfEval& e, float surfacePdf, float lightPdf) {
    float3 found = (e.diffuse + e.specular) * (powerHeuristic(lightPdf, surfacePdf) / lightPdf);
    if (e.toonPdf > 0.0f) found += e.toon * (powerHeuristic(lightPdf, e.toonPdf) / lightPdf);
    // A highlight no sample of the surface could have found (a hair toon's where its fibre reflects nothing): the light's.
    else found += e.toon * (1.0f / lightPdf);
    return found;
}
// How far the fuzz's samples lean (sampleSheen): not at all seen face on, where the fuzz is even all round, and
// more the more the view is from the side.
ML_INLINE float sheenLean(float3 wo) { return 0.9f * sqrtf(fmaxf(0.0f, 1.0f - wo.z * wo.z)); }
ML_INLINE float sheenPdf(float3 wo, float3 wi) {
    const float across = sqrtf((wo.x * wo.x + wo.y * wo.y) * (wi.x * wi.x + wi.y * wi.y));
    const float cosine = across > 1e-12f ? (wo.x * wi.x + wo.y * wi.y) / across : 0.0f;
    return wi.z / ML_PI * (1.0f + sheenLean(wo) * cosine);
}
ML_INLINE BsdfEval evalBsdf(const Surface& s, const Lobes& lobes, float3 wo, float3 wi) {
    BsdfEval e;
    e.diffuse = e.specular = e.toon = vec(0.0f);
    e.diffusePdf = e.specularPdf = e.toonPdf = 0.0f;
    if (wo.z <= 0.0f) return e;
    if (wi.z <= 0.0f) {
        // From behind, only the diffuse light that passes through.
        if (s.passes) {
            e.diffuse = backColor(s, wo) * (-wi.z / ML_PI);
            e.diffusePdf = lobes.back * -wi.z / ML_PI;
        }
        return e;
    }
    const float3 h = normalize(wo + wi);
    const float cosine = dot(wo, h);
    float passed = 1.0f;    // what the highlights let through to what is under them
    if (s.toonSpecular) {
        // MoonRay's toon highlights (BsdfToon.cc): one, or a hair toon's up to three, each found from the lights alone,
        // each under the ones before it.
        for (unsigned k = 0; k <= s.toon->more; ++k) {
            const DeviceToon& toon = s.toon[k];
            const float3 tint = make_float3(toon.tint[0], toon.tint[1], toon.tint[2]) * passed;
            passed *= toonPass(toon, wo.z);
            if (toon.model == TOON_HAIR) {
                // MoonRay's Toon_Hair: a hair fibre's first reflection (R) worked out as MoonRay's hair does it, with no
                // tilt and no Fresnel (MoonRay gives its Fresnel to the highlight around it, not to this reflection), and
                // the ramp read at how bright that is.
                const float3 along = s.toonAlong;
                const float sinO = clamp(dot(wo, along), -1.0f, 1.0f), sinI = clamp(dot(wi, along), -1.0f, 1.0f);
                if (fabsf(sinI) >= 1.0f - 1e-6f) continue;
                const float cosO = sqrtf(fmaxf(0.0f, 1.0f - sinO * sinO)), cosI = sqrtf(fmaxf(0.0f, 1.0f - sinI * sinI));
                const float3 flatO = wo - along * sinO, flatI = wi - along * sinI;
                const float lengths = length(flatO) * length(flatI);
                const float cosPhi = lengths > 1e-12f ? clamp(dot(flatO, flatI) / lengths, -1.0f, 1.0f) : 1.0f;
                const float around = fmaxf(0.0f, 0.25f * sqrtf(fmaxf(0.0f, 0.5f * (1.0f + cosPhi))));
                const float m = hairLongitudinal(toon.variance, sinI, cosI, sinO, cosO);
                const float bright = luminance(tint) * m * around;
                const float ramp = toon.specular[toonStep(bright)];
                e.toon += tint * (ramp * toon.intensity / ML_PI);
                e.toonPdf += m * around;
                continue;
            }
            // A surface's: a ramp over how far the reflected light is from the eye, by an approximation of the angle
            // that MoonRay uses, times the surface's reflection seen from the eye.
            const float toward = clamp(wo.z * wi.z - wo.x * wi.x - wo.y * wi.y, 0.0f, 1.0f);
            const float theta = powf(1.0f - toward, 0.56f);
            if (theta > 0.0f) {
                const float x = theta / toon.specularScale;
                const float ramp = x > 1.0f ? toon.specularBeyond : toon.specular[toonStep(x)];
                const float3 seen = toon.plain ? lerp(vec(1.0f), vec(dielectricFresnel(wo.z, 1.5f) * toon.level), toon.blend)
                                               : lerp(vec(s.specular), specularFresnel(s, wo.z) * toon.level, toon.blend);
                e.toon += tint * seen * (ramp * toon.intensity * underCoat(s, wo) / ML_PI);
                e.toonPdf += ramp / (2.0f * ML_PI);
            }
        }
    } else
    if (s.beckmann) {
        // Sampled from the distribution of facets itself, so its density follows the half vector.
        const float d = beckmannD(s.alphaX, s.alphaY, h);
        e.specular = specularFresnel(s, cosine) * (underCoat(s, wo) * d * beckmannG1(s.alphaX, s.alphaY, wo)
                                                   * beckmannG1(s.alphaX, s.alphaY, wi) / (4.0f * wo.z));
        e.specularPdf = (1.0f - lobes.coat) * d * h.z / (4.0f * fmaxf(cosine, 1e-6f));
    } else {
        const float d = ggxD(s.alpha, h.z), g1o = smithG1(s.alpha, wo.z), g1i = smithG1(s.alpha, wi.z);
        e.specular = specularFresnel(s, cosine) * (underCoat(s, wo) * d * g1o * g1i / (4.0f * wo.z));
        e.specularPdf = (1.0f - lobes.coat) * g1o * d / (4.0f * wo.z);
    }
    if (!s.toonSpecular) {
        const float broad = broadShare(s);
        e.specular += multipleScattering(s, wo, wi) * underCoat(s, wo);
        e.specularPdf = e.specularPdf * (1.0f - broad) + (1.0f - lobes.coat) * broad * wi.z / ML_PI;
    }
    if (s.coat > 0.0f) {
        const float cd = ggxD(s.coatAlpha, h.z), cg1o = smithG1(s.coatAlpha, wo.z), cg1i = smithG1(s.coatAlpha, wi.z);
        e.specular += vec(s.coat * dielectricFresnel(cosine, COAT_IOR) * cd * cg1o * cg1i / (4.0f * wo.z));
        e.specularPdf += lobes.coat * cg1o * cd / (4.0f * wo.z);
    }
    // Diffuse light falls on the surface's own smoothed normal; only reflections use the bent one.
    if (s.toonDiffuse) {
        // MoonRay's toon diffuse: the surface's colour times the ramp's, by how far the light is from straight on,
        // and no falling off with the angle besides. A half of what a white surface would send back at most.
        const float x = (1.0f - dot(s.diffuseNormal, wi)) / s.toon->diffuseScale;
        const unsigned step = toonStep(x);
        const float3 ramp = x > 1.0f ? vec(s.toon->diffuseBeyond)
                                     : make_float3(s.toon->diffuse[step * 3], s.toon->diffuse[step * 3 + 1], s.toon->diffuse[step * 3 + 2]);
        const float3 banded = ramp * s.albedo;
        const float3 colour = make_float3(clamp(banded.x, 0.0f, 1.0f), clamp(banded.y, 0.0f, 1.0f), clamp(banded.z, 0.0f, 1.0f)) * s.frontKeep;
        e.diffuse = colour * coatBounces(s, wo, colour) * (entering(s, wo) * (1.0f - s.transmission) * s.diffuseScale / (2.0f * ML_PI));
    } else
    e.diffuse = diffuseColor(s, wo) * (fmaxf(0.0f, dot(s.diffuseNormal, wi)) / ML_PI);
    e.diffuse = e.diffuse * passed;
    if (s.fuzz > 0.0f) {
        // The fuzz is over everything: the highlights and the coat lose what it reflects (the diffuse already has, in
        // entering), and it is found by the diffuse lobe's samples, which are drawn by the cosine as its own are.
        const float kept = underFuzz(s, wo);
        e.specular = e.specular * kept;
        e.toon = e.toon * kept;
        e.diffuse += fuzzLobe(s, wo, wi);
    }
    e.diffusePdf = (1.0f - lobes.back) * ((1.0f - lobes.sheen) * wi.z / ML_PI + lobes.sheen * sheenPdf(wo, wi));
    return e;
}

ML_INLINE float3 sampleDiffuse(float u1, float u2) {
    const float r = sqrtf(u1), phi = 2.0f * ML_PI * u2;
    return make_float3(r * cosf(phi), r * sinf(phi), sqrtf(fmaxf(0.0f, 1.0f - u1)));
}
// The fuzz's own samples: by the cosine as the diffuse's, but round the normal they lean towards the side the view
// comes from, where MoonRay's fuzz is brightest, by (1 + lean cos(azimuth from the view's)) / 2 pi.
ML_INLINE float3 sampleSheen(float3 wo, float u1, float u2) {
    const float lean = sheenLean(wo), target = 2.0f * ML_PI * u2 - ML_PI;
    // The azimuth's distribution, d + lean sin d, turned round by Newton's method from the even guess.
    float d = target;
    for (int i = 0; i < 8; ++i) d = clamp(d - (d + lean * sinf(d) - target) / (1.0f + lean * cosf(d)), -ML_PI, ML_PI);
    const float azimuth = atan2f(wo.y, wo.x) + d, r = sqrtf(u1);
    return make_float3(r * cosf(azimuth), r * sinf(azimuth), sqrtf(fmaxf(0.0f, 1.0f - u1)));
}

// A microfacet normal seen from wo: visible normal sampling (Heitz 2018).
ML_INLINE float3 sampleFacet(float alpha, float3 wo, float u1, float u2) {
    const float3 vh = normalize(make_float3(alpha * wo.x, alpha * wo.y, wo.z));
    const float lengthSquared = vh.x * vh.x + vh.y * vh.y;
    const float3 t1 = lengthSquared > 0.0f ? make_float3(-vh.y, vh.x, 0.0f) * (1.0f / sqrtf(lengthSquared))
                                           : make_float3(1.0f, 0.0f, 0.0f);
    const float3 t2 = cross(vh, t1);
    const float r = sqrtf(u1), phi = 2.0f * ML_PI * u2, blend = 0.5f * (1.0f + vh.z);
    const float a = r * cosf(phi);
    const float b = (1.0f - blend) * sqrtf(fmaxf(0.0f, 1.0f - a * a)) + blend * r * sinf(phi);
    const float3 nh = t1 * a + t2 * b + vh * sqrtf(fmaxf(0.0f, 1.0f - a * a - b * b));
    return normalize(make_float3(alpha * nh.x, alpha * nh.y, fmaxf(0.0f, nh.z)));
}
// A facet drawn from the Beckmann distribution: a slope of unit width, stretched along each axis.
ML_INLINE float3 sampleBeckmann(float alphaX, float alphaY, float u1, float u2) {
    const float slope = sqrtf(-logf(fmaxf(1e-12f, 1.0f - u1))), phi = 2.0f * ML_PI * u2;
    return normalize(make_float3(alphaX * slope * cosf(phi), alphaY * slope * sinf(phi), 1.0f));
}

// MoonRay's dispersion: each refraction picks red, green or blue, bends by that colour's index
// and carries only that colour. The Abbe number spreads the indices around the green one.
ML_INLINE float spectralIor(float ior, float abbe, float u, float3& tint) {
    tint = vec(1.0f);
    if (abbe <= 0.0f) return ior;
    const float blue = (ior - 1.0f) / (2.0f * abbe) + ior, red = 2.0f * ior - blue;
    if (u < 0.35f) { tint = make_float3(1.0f / 0.35f, 0.0f, 0.0f); return fmaxf(red, 1.0001f); }
    if (u < 0.7f) { tint = make_float3(0.0f, 1.0f / 0.35f, 0.0f); return ior; }
    tint = make_float3(0.0f, 0.0f, 1.0f / 0.3f);
    return fmaxf(blue, 1.0001f);
}
ML_INLINE float3 reflectAbout(float3 wo, float3 h) { return h * (2.0f * dot(wo, h)) - wo; }

// Bends wo through a facet from index etaI into etaT; false when the light is reflected back.
ML_INLINE bool refractThrough(float3 wo, float3 h, float etaI, float etaT, float3& wi) {
    const float eta = etaI / etaT, cosine = dot(wo, h);
    const float cosSquaredT = 1.0f - eta * eta * (1.0f - cosine * cosine);
    if (cosSquaredT <= 0.0f) return false;
    wi = h * (eta * cosine - sqrtf(cosSquaredT)) - wo * eta;
    return true;
}

ML_INLINE float powerHeuristic(float a, float b) {
    return a * a / (a * a + b * b);
}

// MoonRay scales down any single light sample brighter than its clamping value once the path
// has scattered off something rough, which is what keeps caustics from sparkling.
ML_INLINE float3 clampSample(float3 contribution, bool scattered) {
    const float brightest = maxComponent(contribution);
    return scattered && params.sampleClamp > 0.0f && brightest > params.sampleClamp
        ? contribution * (params.sampleClamp / brightest) : contribution;
}

// ---- Programs ----------------------------------------------------------------------------------

// Where a shadow ray starts. A toon lit by its smooth normals starts from the smooth surface, and is moved off it along
// its smooth normal, towards the light: moved off its face towards the side the ray leaves from, as other surfaces are,
// it would start below the face wherever the light is behind the face and the lift is less than that, near a row of
// corners, and the faces beside it would shadow it in a thin line.
ML_INLINE float3 shadowFrom(const Surface& surface, float3 p, float3 lift, float3 ng, float3 ns, float3 direction) {
    if (!surface.smoothToon) return offsetOrigin(p, ng, direction);
    return offsetOrigin(shadowStart(p, lift, ng, ns, direction), ns, direction);
}

// Next event estimation at one surface point: the environment, the distant lights, then the
// local lights. weight is the path's weight on arriving at the surface.
ML_INLINE float3 directLight(const Surface& surface, const Lobes& lobes, float3 wo, const Frame& frame,
                             float3 p, float3 ng, float3 weight, bool lit, unsigned& seed, float3 lift = make_float3(0.0f, 0.0f, 0.0f),
                             unsigned set = 0) {
    const DeviceDistantLight* distantLights = reinterpret_cast<const DeviceDistantLight*>(params.distantLights);
    const DeviceLight* lights = reinterpret_cast<const DeviceLight*>(params.lights);
    float3 radiance = vec(0.0f);
    // With a portal in the scene the environment is sampled through it, as one of the lights.
    if (!params.envPortal && reaches(set, 0)) {
        float lightPdf;
        const float3 toLight = sampleEnv(rnd(seed), rnd(seed), lightPdf);
        if (lightPdf > 0.0f && (surface.passes || surface.smoothToon || dot(ng, toLight) > 0.0f)) {
            const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toLight));
            const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
            const float3 found = litBy(e, pdf, lightPdf);
            if (maxComponent(found) > 0.0f)
                radiance += clampSample(weight * found * envRadiance(toLight) * shadow(shadowFrom(surface, p, lift, ng, frame.n, toLight), toLight, seed), lit);
        }
    }
    for (unsigned i = 0; i < params.distantLightCount; ++i) {
        if (!reaches(set, 1 + i)) continue;
        const DeviceDistantLight& light = distantLights[i];
        const float3 toSun = sampleDistant(light, rnd(seed), rnd(seed));
        if (!surface.passes && !surface.smoothToon && dot(ng, toSun) <= 0.0f) continue;
        const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toSun));
        const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
        const float3 found = litBy(e, pdf, distantPdf(light, toSun));
        if (maxComponent(found) > 0.0f)
            radiance += clampSample(weight * found * distantRadiance(light, toSun) * shadow(shadowFrom(surface, p, lift, ng, frame.n, toSun), toSun, seed), lit);
    }
    const unsigned firstLight = params.lightPick ? pickLight(lights, params.lightCount, rnd(seed)) : 0;
    const unsigned lastLight = params.lightPick ? firstLight + 1 : params.lightCount;
    for (unsigned i = firstLight; i < lastLight; ++i) {
        if (!reaches(set, 1 + params.distantLightCount + i)) continue;
        float3 toLamp, emitted;
        float distance, lampPdf;
        if (!sampleLight(lights[i], p, rnd(seed), rnd(seed), toLamp, distance, lampPdf, emitted)) continue;
        if (!surface.passes && !surface.smoothToon && dot(ng, toLamp) <= 0.0f) continue;
        if (params.lightPick) lampPdf *= lights[i].pick;
        const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toLamp));
        const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
        const float3 found = litBy(e, pdf, lampPdf);
        if (maxComponent(found) > 0.0f)
            radiance += clampSample(weight * found * emitted * shadow(shadowFrom(surface, p, lift, ng, frame.n, toLamp), toLamp, seed, distance * 0.999f), lit);
    }
    return radiance;
}

// ---- Hair --------------------------------------------------------------------------------------
// A fibre's four ways of scattering light, as MoonRay's HairMaterial has them: its formulas are those of d'Eon et
// al. 2011 and Chiang et al. 2016, taken here from MoonRay's HairUtil, HairState and BsdfHairLobes.

ML_INLINE float besselI0(float x) {
    float sum = 0.0f, x2i = 1.0f, factorial = 1.0f, fours = 1.0f;
    for (int i = 0; i < 10; ++i) {
        if (i > 1) factorial *= float(i);
        sum += x2i / fours / factorial / factorial;
        x2i *= x * x;
        fours *= 4.0f;
    }
    return sum;
}
ML_INLINE float logBesselI0(float x) {
    if (x > 12.0f) {
        const float inverse = 1.0f / x;
        return x + 0.5f * (-logf(2.0f * ML_PI) + logf(inverse + 0.125f * inverse));
    }
    return logf(besselI0(x));
}
// How light spreads along the fibre.
ML_INLINE float hairLongitudinal(float variance, float sinI, float cosI, float sinO, float cosO) {
    if (variance < 1e-6f) return 0.0f;
    const float inverse = 1.0f / variance, b = sinI * sinO * inverse, x = cosI * cosO * inverse;
    if (variance <= 0.1f) return expf(logBesselI0(x) - b - inverse + 0.6931f + logf(0.5f * inverse));
    return 0.5f * inverse * expf(-b) * besselI0(x) / sinhf(inverse);
}
ML_INLINE float logisticCdf(float x, float s) { return 1.0f / (1.0f + expf(-x / s)); }
// A logistic curve cut off at half a turn either side, which is how light passing through spreads around the fibre.
ML_INLINE float trimmedLogistic(float x, float s) {
    const float r = expf(-fabsf(x) / s);
    return r / (s * (1.0f + r) * (1.0f + r)) / (logisticCdf(ML_PI, s) - logisticCdf(-ML_PI, s));
}
ML_INLINE float sampleTrimmedLogistic(float u, float s) {
    const float low = logisticCdf(-ML_PI, s), value = u * (logisticCdf(ML_PI, s) - low) + low;
    return value > 0.0f ? clamp(-s * logf(1.0f / value - 1.0f), -ML_PI, ML_PI) : -ML_PI;
}

// The fibre at a hit, seen from wo: its frame, how far off its middle the ray struck, what a pass through it
// absorbs, and how the four lobes share the samples.
struct Fibre {
    float3 along, facing, across;
    float sinO, cosO, thetaO, cosGamma;
    float3 through, absorbs;
    float turned;               // how far round the fibre the viewer is from the long axis of its cross-section
    float share[4];
    const DeviceHair* hair;
};

ML_INLINE float fibreFresnel(const Fibre& fibre, float cosine) {
    const DeviceHair& hair = *fibre.hair;
    if (hair.fresnel != 2) return fresnel(hair.fresnel ? cosine * fibre.cosGamma : cosine, 1.0f, hair.eta);
    // Layered cuticles (Yan et al. 2015, as MoonRay's LayeredDielectricFresnel): each layer a slab with air on both
    // sides, with the indices Marschner gives the two polarizations for the angle along the fibre.
    const float root = sqrtf(fmaxf(hair.eta * hair.eta - (1.0f - cosine * cosine), 1e-12f));
    const float etaPerp = root / fmaxf(cosine, 1e-6f), etaParallel = hair.eta * hair.eta * cosine / root;
    const float cosI = clamp(fibre.cosGamma, 0.0f, 1.0f), sinSquaredT = (1.0f - cosI * cosI) / (hair.eta * hair.eta);
    if (sinSquaredT >= 1.0f) return 1.0f;
    const float cosT = sqrtf(1.0f - sinSquaredT);
    float s = (cosI - etaPerp * cosT) / (cosI + etaPerp * cosT), p = (etaParallel * cosI - cosT) / (etaParallel * cosI + cosT);
    s = fminf(s * s, 0.9999f);
    p = fminf(p * p, 0.9999f);
    const float one = 0.5f * (s + (1.0f - s) * (1.0f - s) * s / (1.0f - s * s)) + 0.5f * (p + (1.0f - p) * (1.0f - p) * p / (1.0f - p * p));
    return clamp(hair.layers * one / (1.0f + (hair.layers - 1.0f) * one), 0.0f, 1.0f);
}
// What one pass through the fibre leaves, for light that struck it h off its middle and bends by eta inside.
ML_INLINE float3 fibrePass(const Fibre& fibre, float h, float eta, float etaP) {
    const float sinGammaT = h / etaP, cosGammaT = fibre.cosO > 1e-6f ? sqrtf(fmaxf(0.0f, 1.0f - sinGammaT * sinGammaT)) : 0.0f;
    const float sinT = fibre.sinO / eta, cosT = sqrtf(fmaxf(0.0f, 1.0f - sinT * sinT));
    if (cosT <= 1e-6f) return vec(1.0f);
    const float path = 2.0f * cosGammaT / cosT;
    return make_float3(expf(-fibre.absorbs.x * path), expf(-fibre.absorbs.y * path), expf(-fibre.absorbs.z * path));
}
ML_INLINE float turnOf(float angle) { return angle - 2.0f * ML_PI * floorf((angle + ML_PI) / (2.0f * ML_PI)); }
// What is left of the light on each of the four ways out, before its spread: Fresnel and absorption.
ML_INLINE void fibreAttenuation(const Fibre& fibre, float f, float3* out) {
    const DeviceHair& hair = *fibre.hair;
    const float3 t = fibre.through;
    const float pass = (1.0f - f) * (1.0f - f);
    out[0] = (hair.lobes & HAIR_R) ? vec(hair.tint) * f : vec(0.0f);
    out[1] = (hair.lobes & HAIR_TT) ? vec(hair.tint + 3) * t * pass : vec(0.0f);
    out[2] = (hair.lobes & HAIR_TRT) ? vec(hair.tint + 6) * t * t * (pass * f) : vec(0.0f);
    const float3 rest = make_float3(clamp(1.0f - f * t.x, 1e-6f, 1.0f), clamp(1.0f - f * t.y, 1e-6f, 1.0f), clamp(1.0f - f * t.z, 1e-6f, 1.0f));
    out[3] = (hair.lobes & HAIR_TRRT) ? make_float3(t.x * t.x * t.x / rest.x, t.y * t.y * t.y / rest.y, t.z * t.z * t.z / rest.z) * (pass * f * f) : vec(0.0f);
}

ML_INLINE Fibre fibreFrom(const Hit& hit, const DeviceHair& hair, float3 wo) {
    Fibre fibre;
    fibre.hair = &hair;
    fibre.along = hit.curveTangent;
    fibre.sinO = clamp(dot(wo, fibre.along), -1.0f, 1.0f);
    fibre.cosO = sqrtf(fmaxf(0.0f, 1.0f - fibre.sinO * fibre.sinO));
    fibre.thetaO = asinf(fibre.sinO);
    // The fibre's normal is turned to face the viewer, as MoonRay turns it.
    const float3 facing = wo - fibre.along * fibre.sinO;
    fibre.facing = dot(facing, facing) > 1e-12f ? normalize(facing) : Frame(fibre.along).t;
    fibre.across = cross(fibre.facing, fibre.along);
    // How far off the fibre's middle the ray struck.
    fibre.cosGamma = clamp(hit.curveCos, 0.0f, 1.0f);
    const float h = sqrtf(fmaxf(0.0f, 1.0f - fibre.cosGamma * fibre.cosGamma));
    // The fibre's colour as what it absorbs (Chiang et al. 2016), and what one pass through it leaves.
    const float3 colour = hit.albedo;
    const float3 logs = make_float3(logf(clamp(colour.x, 1e-6f, 1.0f)), logf(clamp(colour.y, 1e-6f, 1.0f)), logf(clamp(colour.z, 1e-6f, 1.0f))) * (1.0f / hair.absorption);
    fibre.absorbs = logs * logs;
    fibre.through = fibrePass(fibre, h, hair.eta, sqrtf(fmaxf(0.0f, hair.eta * hair.eta - fibre.sinO * fibre.sinO)) / fmaxf(fibre.cosO, 1e-6f));
    // An elliptical fibre turns as it grows, by its own number of turns, and glints where its long axis faces.
    fibre.turned = 0.0f;
    if (hair.lobes & HAIR_GLINT) {
        const Frame fixed(fibre.along);
        const float turn = 2.0f * ML_PI * (hair.twists[0] + (hair.twists[1] - hair.twists[0]) * hit.curveChance) * hit.curveAlong;
        const float3 axis = fixed.t * cosf(turn) + fixed.b * sinf(turn);
        fibre.turned = atan2f(dot(fibre.facing, cross(axis, fibre.along)), dot(fibre.facing, axis));
    }
    float3 left[4];
    fibreAttenuation(fibre, fibreFresnel(fibre, fibre.cosO), left);
    float total = 0.0f;
    for (int i = 0; i < 4; ++i) total += fibre.share[i] = luminance(left[i]);
    for (int i = 0; i < 4; ++i) fibre.share[i] = total > 0.0f ? fibre.share[i] / total : ((hair.lobes >> i) & 1) ? 1.0f : 0.0f;
    if (!(total > 0.0f)) {
        float shown = 0.0f;
        for (int i = 0; i < 4; ++i) shown += fibre.share[i];
        for (int i = 0; i < 4; ++i) fibre.share[i] = shown > 0.0f ? fibre.share[i] / shown : 0.0f;
    }
    return fibre;
}

// bsdf * cosine towards wi, and the density with which fibreSample would have chosen it.
ML_INLINE float3 fibreEval(const Fibre& fibre, float3 wi, float& pdf) {
    const DeviceHair& hair = *fibre.hair;
    pdf = 0.0f;
    const float sinI = dot(wi, fibre.along);
    if (fabsf(sinI) >= 1.0f - 1e-6f) return vec(0.0f);
    const float cosI = sqrtf(fmaxf(0.0f, 1.0f - sinI * sinI));
    const float3 flat = wi - fibre.along * sinI;
    const float phi = acosf(clamp(dot(flat, fibre.facing) / fmaxf(length(flat), 1e-12f), -1.0f, 1.0f));
    const float f = fibreFresnel(fibre, cosf(0.5f * fabsf(fibre.thetaO - asinf(sinI))));
    float3 left[4];
    fibreAttenuation(fibre, f, left);
    if (hair.saturation != 1.0f && (hair.lobes & HAIR_TT) && phi > 0.8f * ML_PI) {
        // MoonRay's control over the colour of light passing straight through: within a narrow band about straight
        // on, what the fibre lets through is moved towards or away from grey.
        float band = clamp((phi / ML_PI - 0.8f) / 0.2f, 0.0f, 1.0f);
        band = band * band * (3.0f - 2.0f * band);
        const float amount = 1.0f + (hair.saturation - 1.0f) * band, grey = luminance(fibre.through);
        const float3 kept = vec(grey) + (fibre.through - vec(grey)) * amount;
        left[1] = vec(hair.tint + 3) * make_float3(clamp(kept.x, 0.0f, 1.0f), clamp(kept.y, 0.0f, 1.0f), clamp(kept.z, 0.0f, 1.0f)) * ((1.0f - f) * (1.0f - f));
    }
    // The glints of an elliptical fibre (Marschner et al. 2003, as MoonRay has them): two streaks either side of
    // straight back, which take their share from the reflection inside the fibre.
    float3 glint = vec(0.0f);
    float plain = 1.0f;
    if ((hair.lobes & HAIR_GLINT) && (hair.lobes & HAIR_TRT)) {
        const float cosD = cosf(0.5f * fabsf(fibre.thetaO - asinf(sinI))), sinD = sqrtf(fmaxf(0.0f, 1.0f - cosD * cosD));
        const float e2 = hair.glintEccentricity * hair.glintEccentricity;
        const float narrow = 2.0f * (hair.eta - 1.0f) * e2 - hair.eta + 2.0f, wide = 2.0f * (hair.eta - 1.0f) / e2 - hair.eta + 2.0f;
        // Half way round between the viewer and the light, from the long axis of the cross-section.
        const float between = fibre.turned + 0.5f * (dot(flat, fibre.across) < 0.0f ? -phi : phi);
        const float etaStar = 0.5f * ((narrow + wide) + cosf(2.0f * between) * (narrow - wide));
        const float etaP = sqrtf(fmaxf(0.0f, etaStar * etaStar - sinD * sinD)) / fmaxf(cosD, 1e-6f);
        const float caustic = sqrtf(fmaxf(0.0f, (4.0f - etaP * etaP) / 3.0f));
        const float where = etaP < 2.0f ? turnOf(4.0f * asinf(clamp(caustic / etaP, -1.0f, 1.0f)) - 2.0f * asinf(clamp(caustic, -1.0f, 1.0f)) + 2.0f * ML_PI) : 0.0f;
        const float peak = trimmedLogistic(0.0f, hair.glintWidth);
        const float one = trimmedLogistic(turnOf(phi - where), hair.glintWidth), other = trimmedLogistic(turnOf(phi + where), hair.glintWidth);
        plain = 1.0f - (one + other) / peak;
        float3 passed = fibrePass(fibre, sqrtf(fmaxf(0.0f, 1.0f - fibre.cosGamma * fibre.cosGamma)), fmaxf(etaStar, 1.0001f), fmaxf(etaP, 1e-6f));
        const float brightest = maxComponent(passed);
        passed = vec(brightest) + (passed - vec(brightest)) * hair.glintSaturation;
        glint = vec(hair.tint + 6) * passed * passed * ((1.0f - f) * (1.0f - f) * f * (one * one + other * other) / peak);
    }
    // Around the fibre: reflections spread as a quarter of the cosine of half the angle, light passing through as a
    // logistic curve about straight on, and what is left evenly.
    const float spread[4] = {fmaxf(0.0f, 0.25f * cosf(0.5f * phi)), trimmedLogistic(ML_PI - phi, hair.azimuthal),
                             fmaxf(0.0f, 0.25f * cosf(0.5f * phi)), 1.0f / (2.0f * ML_PI)};
    float3 value = vec(0.0f);
    for (int i = 0; i < 4; ++i) {
        if (!((hair.lobes >> i) & 1)) continue;
        const float sinShifted = sinI * hair.cosShift[i] + cosI * hair.sinShift[i];
        const float cosShifted = fabsf(cosI * hair.cosShift[i] - sinI * hair.sinShift[i]);
        const float m = hairLongitudinal(hair.variance[i], sinShifted, cosShifted, fibre.sinO, fibre.cosO);
        value += (i == 2 ? left[i] * (plain * spread[i]) + glint : left[i] * spread[i]) * m;
        pdf += fibre.share[i] * m * spread[i];
    }
    return value;
}

// A direction drawn from one of the four lobes; false if none can be.
ML_INLINE bool fibreSample(const Fibre& fibre, unsigned& seed, float3& wi) {
    const DeviceHair& hair = *fibre.hair;
    const float pick = rnd(seed);
    int lobe = 0;
    float running = fibre.share[0];
    while (lobe < 3 && pick >= running) running += fibre.share[++lobe];
    if (fibre.share[lobe] <= 0.0f) return false;
    // Along the fibre (the derivation of pbrt, steadier where the lobe is narrow), then tilted back by the scales.
    const float u = fmaxf(rnd(seed), 1e-5f), variance = hair.variance[lobe];
    const float cosine = 1.0f + variance * logf(u + (1.0f - u) * expf(-2.0f / variance));
    const float sine = sqrtf(fmaxf(0.0f, 1.0f - cosine * cosine));
    float sinI = -cosine * fibre.sinO + sine * cosf(2.0f * ML_PI * rnd(seed)) * fibre.cosO;
    float cosI = sqrtf(fmaxf(0.0f, 1.0f - sinI * sinI));
    const float sinShifted = clamp(sinI * hair.cosShift[lobe] - cosI * hair.sinShift[lobe], -1.0f, 1.0f);
    cosI = fabsf(cosI * hair.cosShift[lobe] + sinI * hair.sinShift[lobe]);
    sinI = sinShifted;
    // Around it.
    const float v = rnd(seed);
    const float phi = lobe == 1 ? sampleTrimmedLogistic(v, hair.azimuthal) + ML_PI
                    : lobe == 3 ? ML_PI * (2.0f * v - 1.0f) : 2.0f * asinf(clamp(2.0f * v - 1.0f, -1.0f, 1.0f));
    wi = normalize(fibre.along * sinI + (fibre.facing * cosf(phi) + fibre.across * sinf(phi)) * cosI);
    return true;
}

// Next event estimation on a fibre, which light reaches from every side.
ML_INLINE float3 fibreLight(const Fibre& fibre, float3 p, float3 ng, float3 weight, bool lit, unsigned& seed, unsigned set = 0) {
    const DeviceDistantLight* distantLights = reinterpret_cast<const DeviceDistantLight*>(params.distantLights);
    const DeviceLight* lights = reinterpret_cast<const DeviceLight*>(params.lights);
    float3 radiance = vec(0.0f);
    float pdf;
    if (!params.envPortal && reaches(set, 0)) {
        float lightPdf;
        const float3 toLight = sampleEnv(rnd(seed), rnd(seed), lightPdf);
        if (lightPdf > 0.0f) {
            const float3 f = fibreEval(fibre, toLight, pdf);
            if (maxComponent(f) > 0.0f)
                radiance += clampSample(weight * f * envRadiance(toLight) * shadow(offsetOrigin(p, ng, toLight), toLight, seed)
                                        * (powerHeuristic(lightPdf, pdf) / lightPdf), lit);
        }
    }
    for (unsigned i = 0; i < params.distantLightCount; ++i) {
        if (!reaches(set, 1 + i)) continue;
        const DeviceDistantLight& light = distantLights[i];
        const float3 toSun = sampleDistant(light, rnd(seed), rnd(seed));
        const float3 f = fibreEval(fibre, toSun, pdf);
        if (maxComponent(f) > 0.0f)
            radiance += clampSample(weight * f * distantRadiance(light, toSun) * shadow(offsetOrigin(p, ng, toSun), toSun, seed)
                                    * (powerHeuristic(distantPdf(light, toSun), pdf) / distantPdf(light, toSun)), lit);
    }
    const unsigned firstLight = params.lightPick ? pickLight(lights, params.lightCount, rnd(seed)) : 0;
    const unsigned lastLight = params.lightPick ? firstLight + 1 : params.lightCount;
    for (unsigned i = firstLight; i < lastLight; ++i) {
        if (!reaches(set, 1 + params.distantLightCount + i)) continue;
        float3 toLamp, emitted;
        float distance, lampPdf;
        if (!sampleLight(lights[i], p, rnd(seed), rnd(seed), toLamp, distance, lampPdf, emitted)) continue;
        if (params.lightPick) lampPdf *= lights[i].pick;
        const float3 f = fibreEval(fibre, toLamp, pdf);
        if (maxComponent(f) > 0.0f)
            radiance += clampSample(weight * f * emitted * shadow(offsetOrigin(p, ng, toLamp), toLamp, seed, distance * 0.999f)
                                    * (powerHeuristic(lampPdf, pdf) / lampPdf), lit);
    }
    return radiance;
}

ML_INLINE float average(float3 c) { return (c.x + c.y + c.z) * (1.0f / 3.0f); }

// ---- Fog ---------------------------------------------------------------------------------------
// How much of the light arriving along one direction a fog sends on along another (Henyey and Greenstein).
ML_INLINE float phase(float cosine, float g) {
    const float denominator = 1.0f + g * g - 2.0f * g * cosine;
    return (1.0f - g * g) / (4.0f * ML_PI * denominator * sqrtf(fmaxf(denominator, 1e-12f)));
}
// A way for light to go on from a point in fog, drawn as the fog sends it: mostly straight on where g is near 1.
ML_INLINE float3 samplePhase(float3 forward, float g, float u1, float u2) {
    float cosine;
    if (fabsf(g) < 1e-3f) cosine = 1.0f - 2.0f * u1;
    else {
        const float part = (1.0f - g * g) / (1.0f - g + 2.0f * g * u1);
        cosine = (1.0f + g * g - part * part) / (2.0f * g);
    }
    const float sine = sqrtf(fmaxf(0.0f, 1.0f - cosine * cosine)), phi = 2.0f * ML_PI * u2;
    return normalize(Frame(forward).toWorld(make_float3(sine * cosf(phi), sine * sinf(phi), cosine)));
}
// The light every lamp sends to a point in fog and on along wo, the way back to the viewer.
ML_INLINE float3 fogLight(float3 p, float3 wo, float g, float3 weight, bool lit, unsigned& seed, float thin = 1.0f) {
    const DeviceDistantLight* distantLights = reinterpret_cast<const DeviceDistantLight*>(params.distantLights);
    const DeviceLight* lights = reinterpret_cast<const DeviceLight*>(params.lights);
    float3 radiance = vec(0.0f);
    if (!params.envPortal) {
        float lightPdf;
        const float3 toLight = sampleEnv(rnd(seed), rnd(seed), lightPdf);
        if (lightPdf > 0.0f)
            radiance += clampSample(weight * envRadiance(toLight) * shadow(p, toLight, seed, 1e16f, thin) * (phase(-dot(wo, toLight), g) / lightPdf), lit);
    }
    for (unsigned i = 0; i < params.distantLightCount; ++i) {
        const DeviceDistantLight& light = distantLights[i];
        const float3 toSun = sampleDistant(light, rnd(seed), rnd(seed));
        radiance += clampSample(weight * distantRadiance(light, toSun) * shadow(p, toSun, seed, 1e16f, thin) * (phase(-dot(wo, toSun), g) / distantPdf(light, toSun)), lit);
    }
    const unsigned firstLight = params.lightPick ? pickLight(lights, params.lightCount, rnd(seed)) : 0;
    const unsigned lastLight = params.lightPick ? firstLight + 1 : params.lightCount;
    for (unsigned i = firstLight; i < lastLight; ++i) {
        float3 toLamp, emitted;
        float distance, lampPdf;
        if (!sampleLight(lights[i], p, rnd(seed), rnd(seed), toLamp, distance, lampPdf, emitted)) continue;
        if (params.lightPick) lampPdf *= lights[i].pick;
        radiance += clampSample(weight * emitted * shadow(p, toLamp, seed, distance * 0.999f, thin) * (phase(-dot(wo, toLamp), g) / lampPdf), lit);
    }
    return radiance;
}

// Burley's normalized diffusion, MoonRay's default subsurface model: how wide the profile of a
// channel is for its albedo and mean free path, and the profile's shape at a distance.
ML_INLINE float profileWidth(float albedo, float radius) {
    const float offset = albedo - 0.33f, squared = offset * offset;
    return fmaxf(radius, 0.001f) / (3.5f + 100.0f * squared * squared);
}
ML_INLINE float profileShape(float r, float width) {
    return (expf(-r / width) + expf(-r / (3.0f * width))) / width;
}

// Whether two neighbouring rays of a draft found things that an outline runs between: one of them nothing, two
// different objects, a corner, or one part of an object in front of another.
ML_INLINE bool draftEdge(const Hit& a, const Hit& b) {
    if (a.valid != b.valid) return true;
    if (!a.valid) return false;
    if (a.instance != b.instance) return true;
    if (a.curve || b.curve) return false;
    if (fabsf(dot(a.ng, b.ng)) < 0.82f) return true;
    return fabsf(dot(b.p - a.p, a.ng)) > 0.03f * fminf(a.t, b.t);
}

// The way a camera ray goes for a place on the picture, from -1 to 1 across and up, by the camera's own lens;
// outside is set where the lens sees nothing.
ML_INLINE float3 cameraDirection(float sx, float sy, bool& outside) {
    float3 direction = normalize(vec(params.cameraU) * (sx + params.cameraShift[0])
                                 + vec(params.cameraV) * (sy + params.cameraShift[1]) + vec(params.cameraW));
    outside = false;
    if (params.cameraProjection == 3) return normalize(vec(params.cameraW));
    if (params.cameraProjection != 0) {
        // MoonRay's fisheye and spherical cameras, by its own formulas. Their directions are in
        // the camera's frame: right, up, and back along the view.
        const float3 right = normalize(vec(params.cameraU)), up = normalize(vec(params.cameraV)), forward = normalize(vec(params.cameraW));
        const float* lens = params.cameraProjectionValues;
        if (params.cameraProjection == 1) {
            const float w = float(params.width), h = float(params.height);
            const float x = 0.5f * sx * w, y = 0.5f * sy * h;
            const unsigned format = unsigned(lens[1]);
            const float diameter = format == 0 ? fminf(w, h) : format == 1 ? fmaxf(w, h) : sqrtf(w * w + h * h);
            const float distance = sqrtf(x * x + y * y);
            const float r = distance * 2.0f / (diameter * fmaxf(lens[2], 1e-6f));
            float sine, cosine;
            const unsigned mapping = unsigned(lens[0]);
            if (mapping == 0) {             // stereographic
                const float q = 1.0f / (1.0f + r * r);
                sine = 2.0f * r * q; cosine = (1.0f - r * r) * q;
            } else if (mapping == 1) {      // equidistant
                sine = sinf(0.5f * ML_PI * r); cosine = cosf(0.5f * ML_PI * r);
            } else if (mapping == 2) {      // equisolid angle
                sine = r * sqrtf(fmaxf(0.0f, 2.0f - r * r)); cosine = 1.0f - r * r;
            } else {                        // orthographic
                outside = r * r > 1.0f;
                sine = r; cosine = sqrtf(fmaxf(0.0f, 1.0f - r * r));
            }
            const float across = distance > 0.0f ? x / distance : 1.0f, along = distance > 0.0f ? y / distance : 0.0f;
            direction = normalize(right * (sine * across) + up * (sine * along) + forward * cosine);
            outside = outside || atan2f(sine, cosine) > lens[3];
        } else {
            const float latitude = lens[0] * (0.5f * sy + 0.5f) + lens[1], longitude = lens[2] * (0.5f * sx + 0.5f) + lens[3];
            direction = normalize(right * (cosf(latitude) * sinf(longitude)) + up * sinf(latitude)
                                  + forward * (cosf(latitude) * cosf(longitude)));
        }
    }
    return direction;
}

// Where a camera ray starts for a place on the picture: the eye, or for an orthographic camera the place on its window.
ML_INLINE float3 cameraStart(float sx, float sy) {
    const float3 eye = vec(params.cameraOrigin);
    if (params.cameraProjection != 3) return eye;
    const float half = 0.5f * params.cameraProjectionValues[0];
    return eye + normalize(vec(params.cameraU)) * (sx * half) + normalize(vec(params.cameraV)) * (sy * half * float(params.height) / float(params.width));
}

extern "C" __global__ void __raygen__moonlightipr() {
    const uint3 index = optixGetLaunchIndex();
    const unsigned pixel = index.y * params.width + index.x;
    const bool beyond = index.x < params.region[0] || index.x >= params.region[2] || index.y < params.region[1] || index.y >= params.region[3];
    if (params.draft == 2 || (params.draft == 1 && beyond)) {
        // Draft: three rays, to here and to the pixels beside and above, and a line where what they find parts.
        // Nothing is lit or shaded, so it costs next to nothing however heavy the scene, and what is behind the
        // nearest surface is not drawn.
        unsigned seed = tea(pixel, params.sample);
        const float sx = 2.0f * (index.x + rnd(seed)) / params.width - 1.0f;
        const float sy = 2.0f * (index.y + rnd(seed)) / params.height - 1.0f;
        const float3 from = cameraStart(sx, sy);
        Hit here, beside, above;
        // Through the camera's own lens, so that the lines lie where a fisheye or spherical camera's picture does.
        bool unseen = false, unseenBeside = false, unseenAbove = false;
        const float3 through = cameraDirection(sx, sy, unseen);
        traceRadiance(from, through, here, 1e16f, SEEN_CAMERA);
        // A line is as wide on the picture whatever its size: about a thousandth of its width, a pixel at least.
        const float apart = 2.0f * fmaxf(1.0f, float(params.width) / 1100.0f);
        traceRadiance(cameraStart(sx + apart / params.width, sy), cameraDirection(sx + apart / params.width, sy, unseenBeside), beside, 1e16f, SEEN_CAMERA);
        traceRadiance(cameraStart(sx, sy + apart / params.height), cameraDirection(sx, sy + apart / params.height, unseenAbove), above, 1e16f, SEEN_CAMERA);
        // Where the lens sees nothing there is no line; nor between two places it does not both see.
        const float line = !unseen && ((!unseenBeside && draftEdge(here, beside)) || (!unseenAbove && draftEdge(here, above))) ? 1.0f : 0.0f;
        const float weight = 1.0f / float(params.sample + 1);
        float4* beauty = reinterpret_cast<float4*>(params.beauty) + pixel;
        const float kept = beauty->x + (line - beauty->x) * weight;
        *beauty = make_float4(kept, kept, kept, 1.0f);
        // The denoiser is shown the lines as they are, so that it leaves them alone.
        reinterpret_cast<float4*>(params.albedo)[pixel] = make_float4(kept, kept, kept, 1.0f);
        reinterpret_cast<float4*>(params.normal)[pixel] = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
        return;
    }
    // A part of the picture already clean takes no more samples: it is left as it is (see Renderer::converge).
    if (params.done && reinterpret_cast<const unsigned char*>(params.done)[(index.y / CLEAN_TILE) * params.doneColumns + index.x / CLEAN_TILE])
        return;
    if (beyond) {
        // Outside the region being rendered there is no picture: black, as MoonRay leaves it.
        reinterpret_cast<float4*>(params.beauty)[pixel] = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
        if (params.half) reinterpret_cast<float4*>(params.half)[pixel] = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
        reinterpret_cast<float4*>(params.albedo)[pixel] = make_float4(0.0f, 0.0f, 0.0f, 1.0f);
        reinterpret_cast<float4*>(params.normal)[pixel] = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
        return;
    }
    unsigned seed = tea(pixel, params.sample);

    const float sx = 2.0f * (index.x + rnd(seed)) / params.width - 1.0f;
    const float sy = 2.0f * (index.y + rnd(seed)) / params.height - 1.0f;
    float3 origin = cameraStart(sx, sy);
    bool outside = false;
    float3 direction = cameraDirection(sx, sy, outside);
    if (outside) {
        // Beyond the lens's field of view there is no picture.
        const float weight = 1.0f / float(params.sample + 1);
        float4* buffers[3] = {reinterpret_cast<float4*>(params.beauty) + pixel, reinterpret_cast<float4*>(params.albedo) + pixel,
                              reinterpret_cast<float4*>(params.normal) + pixel};
        for (int i = 0; i < 3; ++i) {
            const float3 kept = lerp(make_float3(buffers[i]->x, buffers[i]->y, buffers[i]->z), vec(0.0f), weight);
            *buffers[i] = make_float4(kept.x, kept.y, kept.z, i < 2 ? 1.0f : 0.0f);
        }
        if (params.half) reinterpret_cast<float4*>(params.half)[pixel] = make_float4(0.0f, 0.0f, 0.0f, 1.0f);
        return;
    }
    if (params.lensRadius > 0.0f && params.cameraProjection == 0) {
        // Depth of field: the ray leaves a point on the lens and still passes through where the
        // pinhole ray meets the plane in focus.
        float lensX, lensY;
        const float u = rnd(seed), v = rnd(seed);
        if (params.lensBlades) {
            // A polygon, as MoonRay's: one of its triangles, then a point spread evenly over it.
            const float scaled = u * params.lensBlades;
            const unsigned blade = min(unsigned(scaled), params.lensBlades - 1);
            const float along = scaled - blade, out = sqrtf(v), step = 2.0f * ML_PI / params.lensBlades;
            const float a0 = params.lensAngle + step * blade, a1 = a0 + step;
            lensX = out * (cosf(a0) + (cosf(a1) - cosf(a0)) * along);
            lensY = out * (sinf(a0) + (sinf(a1) - sinf(a0)) * along);
        } else {
            const float r = sqrtf(u), phi = 2.0f * ML_PI * v;
            lensX = r * cosf(phi);
            lensY = r * sinf(phi);
        }
        const float3 forward = normalize(vec(params.cameraW));
        const float3 focus = origin + direction * (params.focusDistance / dot(direction, forward));
        origin = origin + (normalize(vec(params.cameraU)) * lensX + normalize(vec(params.cameraV)) * lensY) * params.lensRadius;
        direction = normalize(focus - origin);
    }

    const DeviceDistantLight* distantLights = reinterpret_cast<const DeviceDistantLight*>(params.distantLights);
    const DeviceLight* lights = reinterpret_cast<const DeviceLight*>(params.lights);
    float3 radiance = vec(0.0f);
    float3 guideAlbedo = vec(0.0f), guideNormal = vec(0.0f);
    // The path's weight up to the last surface, then that surface's two weights for the ray
    // leaving it: all lobes for light found along the ray, and only the lobes that may bounce on.
    float3 throughput = vec(1.0f), lightWeight = vec(1.0f), bounceWeight = vec(1.0f);
    float bsdfPdf = 0.0f;
    unsigned diffuseDepth = 0, glossyDepth = 0, roughDepth = 0;
    bool bounces = true;
    bool sharp = true;          // the ray left a mirror-like event, which light sampling cannot find
    bool clampFound = false;    // whether light found along the ray is subject to the sample clamp
    // Light that scatters beneath a surface: the next ray only looks for where it comes out,
    // within reach of where it went in, and that point is then shaded as plain diffuse.
    bool probing = false;
    float reach = 1e16f;
    unsigned entryInstance = 0;
    // Whether the probe is the last step of a random walk, which meets the surface from inside the solid.
    bool walked = false;
    // The kind of ray being followed, which finds only what is visible to its kind.
    unsigned seen = SEEN_CAMERA;
    // The fog the ray is in, as its entry among the volumes, and how many edges of fog the path has crossed.
    int medium = -1;
    unsigned crossings = 0;

    // The light set of the surface the ray last left, which the lights it comes upon are held to.
    unsigned fromSet = 0;
    for (unsigned depth = 0;; ++depth) {
        Hit hit;
        traceRadiance(origin, direction, hit, reach, seen);
        if (ML_HAS(FEATURE_FOG) && params.volumeCount && !probing) {
            // Fogs as thick as their grids say. Each fills the unit cube its rows take the scene into, so the stretch of
            // the ray inside each is worked out from the cube, and they may overlap. Steps are drawn as if the fog were
            // everywhere as thick as all of them at their thickest together, each of which is a real stop only as often
            // as the fog there is that thick (Woodcock tracking). A fog is taken to stop every colour alike, by the
            // mean of what it stops.
            const DeviceVolume* fogs = reinterpret_cast<const DeviceVolume*>(params.volumes);
            const float limit = hit.valid ? hit.t : 1e30f;
            float from = 1e30f, to = 0.0f, most = 0.0f;
            for (unsigned i = 0; i < params.volumeCount; ++i) {
                const DeviceVolume& fog = fogs[i];
                if (!fog.grid) continue;
                float a = 0.0f, b = limit;
                for (int axis = 0; axis < 3 && b > a; ++axis) {
                    const float* row = fog.rows + axis * 4;
                    const float o = dot(vec(row), origin) + row[3], d = dot(vec(row), direction);
                    if (fabsf(d) < 1e-12f) {
                        if (o < 0.0f || o > 1.0f) b = -1.0f;
                        continue;
                    }
                    const float near = -o / d, far = (1.0f - o) / d;
                    a = fmaxf(a, fminf(near, far));
                    b = fminf(b, fmaxf(near, far));
                }
                if (!(b > a)) continue;
                from = fminf(from, a);
                to = fmaxf(to, b);
                most += (fog.extinction[0] + fog.extinction[1] + fog.extinction[2]) * (1.0f / 3.0f) * fog.peak;
            }
            if (most > 0.0f && to > from) {
                bool stopped = false;
                float at = from, anisotropy = 0.0f, stops = 0.0f;
                float3 albedo = vec(0.0f);
                for (int k = 0; k < 1024; ++k) {
                    at += -logf(fmaxf(1e-12f, 1.0f - rnd(seed))) / most;
                    if (at >= to) break;
                    const float3 p = origin + direction * at;
                    float thick = 0.0f;
                    float3 given = vec(0.0f);
                    albedo = vec(0.0f);
                    anisotropy = 0.0f;
                    for (unsigned i = 0; i < params.volumeCount; ++i) {
                        const DeviceVolume& fog = fogs[i];
                        if (!fog.grid) continue;
                        const float here = (fog.extinction[0] + fog.extinction[1] + fog.extinction[2]) * (1.0f / 3.0f) * fogDensity(fog, p);
                        thick += here;
                        albedo += vec(fog.albedo) * here;
                        anisotropy += fog.anisotropy * here;
                        if (fog.glow) {
                            const float4 lit = tex3D<float4>(fog.glow, dot(vec(fog.glowRows), p) + fog.glowRows[3], dot(vec(fog.glowRows + 4), p) + fog.glowRows[7],
                                                             dot(vec(fog.glowRows + 8), p) + fog.glowRows[11]);
                            given += vec(fog.emission) * make_float3(lit.x, lit.y, lit.z);
                        }
                    }
                    // The fog's own light, gathered at every step drawn, real stop or not, which is what makes the
                    // steps add up to all the light given off along the way.
                    if (given.x + given.y + given.z > 0.0f) radiance += clampSample(throughput * lightWeight * given * (1.0f / most), clampFound);
                    if (rnd(seed) * most < thick) {
                        stopped = true;
                        stops = thick;
                        albedo = albedo * (1.0f / thick);
                        anisotropy /= thick;
                        break;
                    }
                }
                if (stopped) {
                    // What the lamps send here goes on towards the viewer.
                    float3 here = origin + direction * at;
                    if (bounces)
                        radiance += fogLight(here, -direction, anisotropy, throughput * bounceWeight * albedo, roughDepth >= params.sampleClampDepth, seed);
                    // And, for as many times as the scene allows, so does what other fog sends here, as MoonRay works it
                    // out (after Wrenninge): from here the light is followed a step at a time through the fog, each step
                    // as long as the fog where it starts makes likely, and ended where a step lands outside the fog.
                    // Each time the light has scattered before, it counts for less, fog stops less of it on its way
                    // from the lamps, and it is thrown more evenly.
                    float3 carried = throughput * bounceWeight * albedo, way = samplePhase(direction, anisotropy, rnd(seed), rnd(seed));
                    for (unsigned order = 1; bounces && order < params.maxVolumeDepth; ++order) {
                        here = here + way * (-logf(fmaxf(1e-12f, 1.0f - rnd(seed))) / stops);
                        float thick = 0.0f, turned = 0.0f;
                        float3 kept = vec(0.0f);
                        for (unsigned i = 0; i < params.volumeCount; ++i) {
                            const DeviceVolume& fog = fogs[i];
                            if (!fog.grid) continue;
                            const float there = (fog.extinction[0] + fog.extinction[1] + fog.extinction[2]) * (1.0f / 3.0f) * fogDensity(fog, here);
                            thick += there;
                            kept += vec(fog.albedo) * there;
                            turned += fog.anisotropy * there;
                        }
                        if (!(thick > 0.0f)) break;
                        carried = carried * kept * (1.0f / thick);
                        // The scene's volume factors (MoonRay's defaults 0.65, 0.65 and 0.5), raised to the bounce's number.
                        const float less = powf(params.volumeAttenuation, float(order)), sent = powf(params.volumeContribution, float(order));
                        const float even = turned / thick * powf(params.volumePhaseAttenuation, float(order));
                        radiance += fogLight(here, -way, even, carried * sent, true, seed, less);
                        way = samplePhase(way, even, rnd(seed), rnd(seed));
                        stops = thick;
                    }
                    break;
                }
            }
        }
        if (medium >= 0 && !probing) {
            // In fog: how far the light gets before the fog stops it, drawn for one colour chosen evenly.
            const DeviceVolume& fog = reinterpret_cast<const DeviceVolume*>(params.volumes)[medium];
            {
            const float3 stops = vec(fog.extinction);
            const float limit = hit.valid ? hit.t : 1e30f, choice = rnd(seed);
            const float chosen = choice < 1.0f / 3.0f ? stops.x : choice < 2.0f / 3.0f ? stops.y : stops.z;
            const float reached = chosen > 0.0f ? -logf(fmaxf(1e-12f, 1.0f - rnd(seed))) / chosen : 1e30f;
            const float far = fminf(reached, limit);
            const float3 left = make_float3(expf(-stops.x * far), expf(-stops.y * far), expf(-stops.z * far));
            if (reached < limit) {
                // Stopped: here the fog gives off its own light and sends the lamps' on towards the viewer. As in
                // MoonRay by default, light scatters in fog once, so the path ends here.
                const float density = average(stops * left);
                if (!(density > 0.0f)) break;
                radiance += clampSample(throughput * lightWeight * vec(fog.emission) * left * (1.0f / density), clampFound);
                const float3 on = throughput * bounceWeight * stops * vec(fog.albedo) * left * (1.0f / density);
                float3 here = origin + direction * reached;
                if (bounces) radiance += fogLight(here, -direction, fog.anisotropy, on, roughDepth >= params.sampleClampDepth, seed);
                // And what other fog sends here, as MoonRay works it out: the light is followed a step at a time, each
                // as long as the fog makes likely, and ended where a step leaves the fog or meets something in it.
                // Each time the light has scattered before, it counts for less, fog stops less of it on its way from
                // the lamps, and it is thrown more evenly.
                const float thickness = average(stops);
                float3 carried = on, way = samplePhase(direction, fog.anisotropy, rnd(seed), rnd(seed));
                for (unsigned order = 1; bounces && thickness > 0.0f && order < params.maxVolumeDepth; ++order) {
                    const float step = -logf(fmaxf(1e-12f, 1.0f - rnd(seed))) / thickness;
                    Hit met;
                    traceRadiance(here, way, met, step, SEEN_DIFFUSE);
                    if (met.valid) break;
                    here = here + way * step;
                    carried = carried * stops * vec(fog.albedo) * (1.0f / thickness);
                    const float less = powf(params.volumeAttenuation, float(order)), sent = powf(params.volumeContribution, float(order));
                    const float even = fog.anisotropy * powf(params.volumePhaseAttenuation, float(order));
                    radiance += fogLight(here, -way, even, carried * sent, true, seed, less);
                    way = samplePhase(way, even, rnd(seed), rnd(seed));
                }
                break;
            }
            // Not stopped before the next surface: what the other colours make of having got this far.
            const float chance = average(left);
            if (!(chance > 0.0f)) break;
            lightWeight *= left * (1.0f / chance);
            bounceWeight *= left * (1.0f / chance);
            }
        }
        const bool emerged = probing;
        if (emerged) {
            // The probe looked straight down the normal of where the light went in. Failing to find
            // the same object, the light comes out level with that point.
            const bool found = hit.valid && hit.instance == entryInstance;
            // A probe looks down onto the surface, and the side it sees is the outside. A walk comes up under the
            // surface, and the outside is the side it is heading for.
            const float3 away = walked ? direction : -direction;
            const float3 ng = found ? (dot(hit.ng, away) < 0.0f ? -hit.ng : hit.ng) : away;
            const float3 ns = found ? (dot(hit.ns, ng) < 0.0f ? -hit.ns : hit.ns) : away;
            hit.p = found ? hit.p : origin + direction * ((walked ? 0.99f : 0.5f) * reach);
            walked = false;
            hit.ng = ng;
            hit.ns = ns;
            hit.albedo = vec(1.0f);     // its colour is already in the path's weight
            hit.emission = hit.tangent = hit.subsurfaceRadius = vec(0.0f);
            hit.transmissionColor = hit.absorption = hit.frontKeep = vec(1.0f);
            hit.back = vec(0.0f);
            hit.roughness = 0.5f;
            hit.ior = 1.0001f;      // nothing is reflected on the way out
            hit.specular = 1.0f;
            hit.metallic = hit.underRoughness = hit.transmission = hit.transmissionRoughness = hit.coat = hit.coatRoughness = 0.0f;
            hit.transmissionIor = 1.5f;
            hit.anisotropy = hit.subsurface = hit.absorptionDistance = hit.abbe = 0.0f;
            hit.flags = MATERIAL_MATTE;
            hit.light = -1;
            hit.valid = 1;
            hit.curve = 0;
            direction = -ns;        // seen from straight above, as far as the diffuse lobe cares
            probing = false;
            reach = 1e16f;
        }
        const bool camera = depth == 0 && !emerged;
        // How far light is found along a scattered ray. Light that a scattered ray comes upon is light sampled a
        // second way, and what stands between is a shadow: so it is what casts shadows that stops it, which may
        // not be what the ray itself goes on to meet. MoonRay draws the same line.
        bool lightBlocked = hit.valid != 0;
        float lightReach = hit.valid ? hit.t : 1e30f;
        if (params.mixedVisibility && !camera && !emerged && !sharp) {
            Hit blocker;
            traceRadiance(origin, direction, blocker, 1e16f, SEEN_SHADOW);
            if ((blocker.valid != 0) != (hit.valid != 0) || (blocker.valid && blocker.instance != hit.instance)) {
                lightBlocked = blocker.valid != 0;
                lightReach = blocker.valid ? blocker.t : 1e30f;
            }
        }
        for (unsigned i = 0; !camera && !emerged && i < params.lightCount; ++i) {
            if (!reaches(fromSet, 1 + params.distantLightCount + i)) continue;
            float pdf;
            float3 emitted;
            if (hitLight(lights[i], origin, direction, lightReach, pdf, emitted))
                radiance += clampSample(throughput * lightWeight * emitted
                                        * (sharp ? 1.0f : powerHeuristic(bsdfPdf, params.lightPick ? pdf * lights[i].pick : pdf)), clampFound);
        }
        if (!lightBlocked) {
            // Camera rays see the background, which may differ from what lights the scene;
            // later bounces share the lighting environment with light sampling.
            const float3 sky = camera ? envLookup(reinterpret_cast<const float4*>(params.envBackground), params.envBackgroundRotation, direction)
                             : params.envPortal ? vec(0.0f) : envRadiance(direction);
            if (camera || reaches(fromSet, 0))
                radiance += clampSample(throughput * lightWeight * sky * (sharp ? 1.0f : powerHeuristic(bsdfPdf, envPdf(direction))), clampFound);
            if (camera) guideAlbedo = make_float3(fminf(sky.x, 1.0f), fminf(sky.y, 1.0f), fminf(sky.z, 1.0f));
            // Distant lights are found by scattered rays; the camera sees only the discs that ask to be seen, as a sun does.
            for (unsigned i = 0; i < params.distantLightCount; ++i) {
                if (!camera && !reaches(fromSet, 1 + i)) continue;
                const DeviceDistantLight& light = distantLights[i];
                if (camera || (sharp && light.visible > 0.0f)) {
                    // The camera, and a mirror, see the disc they are told to: for a sun in a physical sky, not the one that
                    // lights the scene.
                    if (light.visible > 0.0f && dot(direction, vec(light.direction)) >= 1.0f - light.seenVersine)
                        radiance += clampSample(throughput * lightWeight * vec(light.seen), clampFound);
                    continue;
                }
                if (dot(direction, vec(light.direction)) >= 1.0f - light.versine)
                    radiance += clampSample(throughput * lightWeight * distantRadiance(light, direction)
                                            * ((sharp || camera) ? 1.0f : powerHeuristic(bsdfPdf, distantPdf(light, direction))), clampFound);
            }
        }
        if (!hit.valid) break;
        if (ML_HAS(FEATURE_FOG) && (hit.flags & MATERIAL_VOLUME) && !emerged) {
            // A surface in the plane of the fog's edge, as the floor under a box of fog standing on it, is met as far
            // off as the edge, and which of the two the trace returns is chance; going on past the edge would miss the
            // surface, in stripes. So a surface there, or a hair beyond, is the hit, met before the edge is crossed,
            // as when the trace returns it first.
            Hit surface;
            const float slack = 2e-4f * (1.0f + fmaxf(fabsf(hit.p.x), fmaxf(fabsf(hit.p.y), fabsf(hit.p.z))));
            traceRadiance(origin, direction, surface, hit.t + slack, seen, true);
            if (surface.valid) {
                hit = surface;
            } else {
                // The edge of a fog: nothing is there to see. The ray goes on, into the fog through a face that looks
                // outwards and out of it through one that looks inwards.
                if (++crossings > 64) break;
                medium = dot(hit.ng, direction) < 0.0f ? int(hit.hair) : -1;
                origin = offsetOrigin(hit.p, hit.ng, direction);
                --depth;    // crossing an edge is not a bounce
                continue;
            }
        }
        // A mesh light is the surface just hit; it emits from both faces.
        if (camera && !emerged && hit.light >= 0 && lights[hit.light].pad) {
            // Seen by the camera, it is the light itself that is seen, as MoonRay shows a light it is told to show.
            const float3 shining = vec(lights[hit.light].radiance);
            radiance += throughput * shining;
            guideAlbedo = make_float3(fminf(shining.x, 1.0f), fminf(shining.y, 1.0f), fminf(shining.z, 1.0f));
            guideNormal = -direction;
            break;
        }
        if (!camera && !emerged && hit.light >= 0 && reaches(fromSet, 1 + params.distantLightCount + unsigned(hit.light))) {
            const DeviceLight& light = lights[hit.light];
            const float cosine = fabsf(dot(direction, hit.ng));
            if (cosine > 1e-6f) {
                const float pdf = hit.t * hit.t / (light.area * cosine);
                radiance += clampSample(throughput * lightWeight * vec(light.radiance)
                                        * (sharp ? 1.0f : powerHeuristic(bsdfPdf, params.lightPick ? pdf * light.pick : pdf)), clampFound);
            }
        }

        fromSet = reinterpret_cast<const DeviceInstance*>(params.instances)[hit.instance].lightSet;
        Surface surface = surfaceFrom(hit);
        if ((hit.flags & MATERIAL_NO_CAUSTICS) && diffuseDepth > 0) {
            // MoonRay's DwaBaseMaterial leaves its specular, outer specular, metallic and transmission parts out
            // altogether on what it calls a caustic path, one that has already left a diffuse lobe; what is beneath
            // them is then not dimmed by them either. Seen by bounced light such a surface is plain diffuse.
            surface.specular = 0.0f;
            surface.coat = 0.0f;
            surface.metallic = 0.0f;
            surface.transmission = 0.0f;
        }
        if (!emerged) {
            radiance += clampSample(throughput * lightWeight * hit.emission, clampFound);
            if (!bounces) break;
            throughput *= bounceWeight;
            if (maxComponent(throughput) <= 0.0f) break;
        }

        // Russian roulette, once the path has had a chance to gather the main bounces.
        if (depth >= 3 && !emerged) {
            const float survive = clamp(maxComponent(throughput), 0.05f, 0.95f);
            if (rnd(seed) >= survive) break;
            throughput *= vec(1.0f / survive);
        }

        if (ML_HAS(FEATURE_HAIR) && hit.curve && (hit.flags & MATERIAL_HAIR)) {
            // A hair fibre scatters light all round itself, so nothing here asks which side the light is on.
            const Fibre fibre = fibreFrom(hit, reinterpret_cast<const DeviceHair*>(params.hairs)[hit.hair], -direction);
            if (camera) {
                guideAlbedo = hit.albedo;
                guideNormal = make_float3(dot(hit.ns, normalize(vec(params.cameraU))), dot(hit.ns, normalize(vec(params.cameraV))),
                                          -dot(hit.ns, normalize(vec(params.cameraW))));
            }
            radiance += fibreLight(fibre, hit.p, hit.ng, throughput, roughDepth >= params.sampleClampDepth, seed, fromSet);
            float3 wi;
            if (depth >= params.maxDepth || !fibreSample(fibre, seed, wi)) break;
            const float3 f = fibreEval(fibre, wi, bsdfPdf);
            if (bsdfPdf <= 0.0f || maxComponent(f) <= 0.0f) break;
            direction = wi;
            seen = SEEN_DIFFUSE;
            lightWeight = bounceWeight = f * (1.0f / bsdfPdf);
            bounces = true;
            sharp = false;
            clampFound = roughDepth >= params.sampleClampDepth;
            ++roughDepth;
            origin = offsetOrigin(hit.p, hit.ng, direction);
            continue;
        }

        // Shade the side the ray arrived on, and keep the shading normal on that side.
        const float3 toViewer = -direction;
        const bool inside = dot(hit.ng, toViewer) < 0.0f;
        const float3 ng = inside ? -hit.ng : hit.ng;
        float3 ns = dot(hit.ns, ng) < 0.0f ? -hit.ns : hit.ns;
        const float3 smoothed = ns;
        {
            // A smoothed normal can face so far from the surface that the mirror direction of
            // the view dips below it. MoonRay bends such a normal back just far enough for its
            // reflections (the local shading normal adaption of the Iray light transport
            // paper); switching to the face normal instead drew a hard curve across smoothed faces.
            const float3 mirrored = ns * (2.0f * dot(ns, toViewer)) - toViewer;
            const float above = dot(mirrored, ng);
            const float margin = 0.001f;
            if (above < margin) ns = normalize(toViewer + normalize(mirrored + ng * (margin - above)));
        }
        Frame frame(ns);
        if (hit.anisotropy != 0.0f) {
            // A stretched lobe needs its axes: the tangent, then across it.
            const float3 across = hit.tangent - ns * dot(hit.tangent, ns);
            if (dot(across, across) > 1e-8f) frame = Frame(ns, hit.tangent);
        }
        const float3 wo = frame.toLocal(toViewer);
        surface.diffuseNormal = frame.toLocal(smoothed);
        if (surface.toonSpecular) {
            // The way the strand runs, or the surface's tangent, for a hair toon's highlight.
            const float3 along = hit.curve ? hit.curveTangent : hit.tangent - ns * dot(hit.tangent, ns);
            surface.toonAlong = dot(along, along) > 1e-12f ? frame.toLocal(normalize(along)) : make_float3(1.0f, 0.0f, 0.0f);
        }

        if (camera) {
            guideAlbedo = lerp(surface.albedo, vec(1.0f), surface.transmission * (1.0f - surface.metallic));
            guideNormal = make_float3(dot(ns, normalize(vec(params.cameraU))), dot(ns, normalize(vec(params.cameraV))),
                                      -dot(ns, normalize(vec(params.cameraW))));
        }
        const bool mayBounce = depth < params.maxDepth;

        if (inside && surface.transmission > 0.0f && !surface.thin) {
            // The solid absorbs along the stretch just crossed: its transmission colour is what
            // is left after absorptionDistance.
            if (hit.absorptionDistance > 0.0f) {
                const float depths = hit.t / hit.absorptionDistance;
                throughput *= make_float3(powf(clamp(hit.absorption.x, 1e-6f, 1.0f), depths),
                                          powf(clamp(hit.absorption.y, 1e-6f, 1.0f), depths),
                                          powf(clamp(hit.absorption.z, 1e-6f, 1.0f), depths));
            }
            // Leaving a solid the light entered: a plain interface, mirrored back or bent out.
            if (!mayBounce) break;
            float3 tint;
            const float ior = spectralIor(surface.transmissionIor, hit.abbe, rnd(seed), tint);
            const float3 h = surface.transmissionAlpha > 0.0f ? sampleFacet(surface.transmissionAlpha, wo, rnd(seed), rnd(seed))
                                                              : make_float3(0.0f, 0.0f, 1.0f);
            float3 wi;
            const bool mirrored = rnd(seed) < fresnel(dot(wo, h), surface.transmissionIor, 1.0f);
            if (mirrored) tint = vec(1.0f);
            const bool kept = mirrored || !refractThrough(wo, h, ior, 1.0f, wi);   // thrown back inside
            if (kept) wi = reflectAbout(wo, h);
            direction = frame.toWorld(wi);
            seen = kept ? SEEN_REFLECTED : SEEN_THROUGH;
            // MoonRay's material tints the light at every crossing of the surface, in as out: its transmission colour
            // is the colour of the lobe itself. Light thrown back inside is not tinted.
            lightWeight = bounceWeight = kept ? tint : tint * surface.transmissionColor;
            sharp = true;
            clampFound = roughDepth >= params.sampleClampDepth;
            origin = offsetOrigin(hit.p, ng, direction);
            continue;
        }

        // Which lobes may send the path on. MoonRay counts diffuse and glossy bounces apart.
        const bool diffuseBounces = mayBounce && diffuseDepth < params.maxDiffuseDepth;
        const bool glossyBounces = mayBounce && glossyDepth < params.maxGlossyDepth;
        Lobes lobes = lobeWeights(surface, wo);
        // Light that scatters beneath the surface is gathered where it comes out again, so at
        // this point only the mirror-like lobes are lit. The share that scatters is chosen by
        // chance, as is whether this path follows it.
        const bool scatters = ML_HAS(FEATURE_SUBSURFACE) && !inside && hit.subsurface > 0.0f && maxComponent(hit.subsurfaceRadius) > 0.0f
                              && lobes.specular < 1.0f && rnd(seed) < hit.subsurface;
        const float beneath = scatters ? 1.0f - lobes.specular : 0.0f;
        if (scatters) {
            surface.diffuseScale = 0.0f;
            lobes = lobeWeights(surface, wo);
        } else if (diffuseBounces != glossyBounces && !surface.matte) {
            // Sample only what may bounce on; with nothing left, the ray still looks for lights.
            lobes.specular = glossyBounces ? 1.0f : 0.0f;
        }
        const bool lit = roughDepth >= params.sampleClampDepth;   // this surface was reached by scattering off something rough
        radiance += directLight(surface, lobes, wo, frame, hit.p, ng, throughput, lit, seed, hit.lift, fromSet);

        // The light that enters a transmissive surface goes through it rather than scattering.
        const float through = mayBounce ? transmitted(surface, wo) : 0.0f;
        const float u1 = rnd(seed), u2 = rnd(seed);
        if (rnd(seed) < through) {
            float3 wi = -wo;    // thin sheets and missing facets pass the light straight on
            float3 tint = vec(1.0f);
            if (!surface.thin) {
                const float ior = spectralIor(surface.transmissionIor, hit.abbe, rnd(seed), tint);
                const float3 h = surface.transmissionAlpha > 0.0f ? sampleFacet(surface.transmissionAlpha, wo, u1, u2)
                                                                  : make_float3(0.0f, 0.0f, 1.0f);
                if (!refractThrough(wo, h, 1.0f, ior, wi)) wi = reflectAbout(wo, h);
            }
            direction = frame.toWorld(wi);
            seen = SEEN_THROUGH;
            // Chosen in proportion to its share of the light, so only the tint remains.
            lightWeight = bounceWeight = surface.transmissionColor * tint;
            sharp = true;
            clampFound = roughDepth >= params.sampleClampDepth;
            bounces = true;
            origin = offsetOrigin(hit.p, ng, direction);
            continue;
        }

        if (scatters && (hit.flags & MATERIAL_RANDOM_WALK) && rnd(seed) < beneath) {
            // MoonRay's random walk: the light is followed through the solid, from where it goes in to where it
            // comes out. How far it goes between scatterings, and how much of it each scattering keeps, come
            // from the surface's colour and its scattering radius by MoonRay's own fit (VolumeSubsurface.cc,
            // after Chiang and others, Practical and Controllable Subsurface Scattering).
            const float3 a = make_float3(fmaxf(surface.albedo.x, 0.001f), fmaxf(surface.albedo.y, 0.001f), fmaxf(surface.albedo.z, 0.001f));
            const float3 d = make_float3(fmaxf(hit.subsurfaceRadius.x * 0.3333f, 0.001f), fmaxf(hit.subsurfaceRadius.y * 0.3333f, 0.001f),
                                         fmaxf(hit.subsurfaceRadius.z * 0.3333f, 0.001f));
            const float3 kept = make_float3(1.0f - expf(-3.25172f * a.x * a.x * a.x + 1.2166f * a.x * a.x - 4.75914f * a.x),
                                            1.0f - expf(-3.25172f * a.y * a.y * a.y + 1.2166f * a.y * a.y - 4.75914f * a.y),
                                            1.0f - expf(-3.25172f * a.z * a.z * a.z + 1.2166f * a.z * a.z - 4.75914f * a.z));
            const float3 sigmaT = make_float3(1.0f / (d.x * (1.9f - a.x + 3.5f * (a.x - 0.8f) * (a.x - 0.8f))),
                                              1.0f / (d.y * (1.9f - a.y + 3.5f * (a.y - 0.8f) * (a.y - 0.8f))),
                                              1.0f / (d.z * (1.9f - a.z + 3.5f * (a.z - 0.8f) * (a.z - 0.8f))));
            const float3 sigmaS = sigmaT * kept;
            // What MoonRay steers the walk by: the greatest eigenvalue of how light spreads in such a medium.
            const float3 rest = vec(1.0f) - kept;
            const float3 kappa = make_float3(sqrtf(3.0f * rest.x) * (1.0f - rest.x * (0.4f + rest.x * (12.0f / 175.0f + rest.x * (2.0f / 125.0f + rest.x * 166.0f / 67375.0f)))),
                                             sqrtf(3.0f * rest.y) * (1.0f - rest.y * (0.4f + rest.y * (12.0f / 175.0f + rest.y * (2.0f / 125.0f + rest.y * 166.0f / 67375.0f)))),
                                             sqrtf(3.0f * rest.z) * (1.0f - rest.z * (0.4f + rest.z * (12.0f / 175.0f + rest.z * (2.0f / 125.0f + rest.z * 166.0f / 67375.0f)))));
            const float3 v0 = make_float3(1.0f / fmaxf(kappa.x, 1e-6f), 1.0f / fmaxf(kappa.y, 1e-6f), 1.0f / fmaxf(kappa.z, 1e-6f));
            const float3 norm = make_float3(1.0f / logf((v0.x + 1.0f) / (v0.x - 1.0f)), 1.0f / logf((v0.y + 1.0f) / (v0.y - 1.0f)),
                                            1.0f / logf((v0.z + 1.0f) / (v0.z - 1.0f)));
            // Straight through with no scattering at all, which a thin part lets happen: plain absorption.
            const float3 straight = make_float3(-logf(fmaxf(a.x - 1e-6f, 1e-6f)) / d.x, -logf(fmaxf(a.y - 1e-6f, 1e-6f)) / d.y,
                                                -logf(fmaxf(a.z - 1e-6f, 1e-6f)) / d.z);
            // What goes in is what the surface did not reflect; its colour comes from the walk.
            const float3 entered = surface.frontKeep * (entering(surface, wo) * (1.0f - surface.transmission) / ((1.0f - through) * beneath));
            float3 weight = entered, from = hit.p, along = -ns;
            float far = 0.0f;
            bool out = false, lost = false;
            // A try that leaves without scattering after the first step is not counted, as MoonRay does not count
            // it: it is taken again, as often as MoonRay has tries to spare, which is its subsurface samples (four,
            // as the scene has them unless told) where the camera or a mirror sees the surface, and one after that.
            // Where none of them counts, at a thin edge, nothing comes of it there, as in MoonRay.
            const int tries = roughDepth == 0 ? 4 : 1;
            for (int attempt = 0; attempt < tries && !out && !lost; ++attempt) {
                weight = entered;
                const float3 local = sampleDiffuse(rnd(seed), rnd(seed));
                along = -(frame.t * local.x + frame.b * local.y + ns * local.z);
                from = offsetOrigin(hit.p, ng, along);
                Hit wall;
                {
                    const float sum = weight.x + weight.y + weight.z, pick = rnd(seed) * sum;
                    const float rate = pick < weight.x ? straight.x : pick < weight.x + weight.y ? straight.y : straight.z;
                    const float step = -logf(fmaxf(1e-7f, 1.0f - rnd(seed))) / rate;
                    traceRadiance(from, along, wall, step, SEEN_ALL);
                    if (wall.valid && wall.instance == hit.instance) {
                        const float3 tr = make_float3(expf(-straight.x * wall.t), expf(-straight.y * wall.t), expf(-straight.z * wall.t));
                        const float chance = (weight.x * tr.x + weight.y * tr.y + weight.z * tr.z) / sum;
                        weight = weight * tr * (1.0f / fmaxf(chance, 1e-20f));
                        far = wall.t;
                        out = true;
                        break;
                    }
                }
                // From here on the walk is MoonRay's own, step for step (PathIntegratorSubsurface.cc): after two
                // scatterings nine steps in ten are steered back toward the surface (Dwivedi sampling), and each
                // step is weighed by the one density MoonRay gives it. That weighing is part of how MoonRay's
                // random walk looks; a walk weighed by the book comes out brighter than MoonRay's.
                bool scattered = false, steered = false;
                for (int event = 0; event < 256; ++event) {
                    const float sum = weight.x + weight.y + weight.z;
                    if (!(sum > 0.0f)) { lost = true; break; }
                    const float plain = event > 1 ? 0.1f : 1.0f;
                    const float3 share = weight * (1.0f / sum);
                    const float pick = rnd(seed);
                    const int channel = pick < share.x ? 0 : pick < share.x + share.y ? 1 : 2;
                    float cosine = dot(along, ns);
                    const float3 sigmaP = make_float3(sigmaT.x * (1.0f - cosine / v0.x), sigmaT.y * (1.0f - cosine / v0.y), sigmaT.z * (1.0f - cosine / v0.z));
                    const float3 rates = steered ? sigmaP : sigmaT;
                    const float rate = channel == 0 ? rates.x : channel == 1 ? rates.y : rates.z;
                    const float step = -logf(fmaxf(1e-7f, 1.0f - rnd(seed))) / fmaxf(rate, 1e-20f);
                    traceRadiance(from, along, wall, step, SEEN_ALL);
                    if (wall.valid && wall.instance == hit.instance) {
                        if (!scattered) break;     // not counted: taken again
                        const float3 tr = make_float3(expf(-sigmaT.x * wall.t), expf(-sigmaT.y * wall.t), expf(-sigmaT.z * wall.t));
                        const float3 trp = make_float3(expf(-sigmaP.x * wall.t), expf(-sigmaP.y * wall.t), expf(-sigmaP.z * wall.t));
                        const float chance = share.x * (plain * tr.x + (1.0f - plain) * trp.x) + share.y * (plain * tr.y + (1.0f - plain) * trp.y)
                                           + share.z * (plain * tr.z + (1.0f - plain) * trp.z);
                        weight = weight * tr * (1.0f / fmaxf(chance, 1e-20f));
                        far = wall.t;
                        out = true;
                        break;
                    }
                    // A scattering: on from there.
                    scattered = true;
                    from = from + along * step;
                    const float3 tr = make_float3(expf(-sigmaT.x * step), expf(-sigmaT.y * step), expf(-sigmaT.z * step));
                    const float3 dense = sigmaT * tr;
                    const float3 denseP = make_float3(sigmaP.x * expf(-sigmaP.x * step), sigmaP.y * expf(-sigmaP.y * step), sigmaP.z * expf(-sigmaP.z * step));
                    weight = weight * tr * sigmaS * (0.25f / ML_PI);
                    const float u = rnd(seed), turn = 2.0f * ML_PI * rnd(seed);
                    const bool back = rnd(seed) < 0.9f;
                    float3 local;
                    if (u < plain) {
                        // Any way at all.
                        steered = false;
                        const float z = 1.0f - 2.0f * (u / plain), ring = sqrtf(fmaxf(0.0f, 1.0f - z * z));
                        local = make_float3(ring * cosf(turn), ring * sinf(turn), z);
                        along = frame.t * local.x + frame.b * local.y + ns * local.z;
                        cosine = back ? local.z : -local.z;
                    } else {
                        // Steered: mostly back toward the surface the light came in by.
                        steered = true;
                        const float r = (u - plain) / (1.0f - plain);
                        const float v = channel == 0 ? v0.x : channel == 1 ? v0.y : v0.z;
                        cosine = v - (v + 1.0f) * powf((v - 1.0f) / (v + 1.0f), r);
                        const float ring = sqrtf(fmaxf(0.0f, 1.0f - cosine * cosine));
                        local = make_float3(ring * cosf(turn), ring * sinf(turn), cosine);
                        along = normalize(frame.t * local.x + frame.b * local.y + ns * local.z);
                        if (!back) along = -along;
                    }
                    const float3 steer = make_float3(norm.x / (v0.x - cosine), norm.y / (v0.y - cosine), norm.z / (v0.z - cosine)) * (0.5f / ML_PI);
                    const float density = share.x * (plain * (0.25f / ML_PI) * dense.x + (1.0f - plain) * steer.x * denseP.x)
                                        + share.y * (plain * (0.25f / ML_PI) * dense.y + (1.0f - plain) * steer.y * denseP.y)
                                        + share.z * (plain * (0.25f / ML_PI) * dense.z + (1.0f - plain) * steer.z * denseP.z);
                    weight = weight * (1.0f / fmaxf(density, 1e-20f));
                    if (event == 255) lost = true;     // never came out: counted, as nothing
                }
                if (scattered && !out) lost = true;
            }
            if (!out || !finite(weight)) break;
            throughput *= weight;
            // The last step again, as the probe that finds where the light comes out.
            entryInstance = hit.instance;
            origin = from;
            direction = along;
            seen = SEEN_ALL;
            reach = far * 1.01f + 1e-5f;
            probing = true;
            walked = true;
            --depth;    // coming out again is not a bounce
            continue;
        }

        if (scatters && rnd(seed) < beneath) {
            // MoonRay's diffusion, as its integrator works it out (PathIntegratorSubsurface.cc). Where the light
            // comes out is looked for from several points drawn from the profile, each projected onto the surface
            // along the normal (three times in four) or along one of the two directions across it, so that a
            // surface that turns away, an edge or a thin part is found as well as a flat one; each find is
            // weighed by how likely every one of those ways was to make it. What those finds add up to is set
            // against what a flat, endless surface would give, and made up to it: a small or thin shape loses
            // none of its light for being small. And light is looked for through the solid, on a far side that
            // faces away, as it comes through an ear or a leaf.
            const float3 albedo = make_float3(fmaxf(surface.albedo.x, 0.001f), fmaxf(surface.albedo.y, 0.001f),
                                              fmaxf(surface.albedo.z, 0.001f));
            const float3 width = make_float3(profileWidth(albedo.x, hit.subsurfaceRadius.x), profileWidth(albedo.y, hit.subsurfaceRadius.y),
                                             profileWidth(albedo.z, hit.subsurfaceRadius.z));
            const float total = albedo.x + albedo.y + albedo.z;
            const float3 share = albedo * (1.0f / total);
            // No further than where all but a two-hundredth of the widest channel's light has come out.
            const float furthest = 15.03f * fmaxf(width.x, fmaxf(width.y, width.z)), nearest = 0.1f * furthest;
            const int tries = roughDepth == 0 ? 4 : 2;
            float3 found[8], from[8], way[8];
            float span[8], heavy[8];
            bool through_[8];
            int count = 0;
            float3 measured = vec(0.0f);
            for (int i = 0; i < tries; ++i) {
                // A colour channel by its albedo, and a distance from that channel's profile.
                const float pick = rnd(seed) * total;
                const float chosen = pick < albedo.x ? width.x : pick < albedo.x + albedo.y ? width.y : width.z;
                const float r = (rnd(seed) < 0.25f ? chosen : 3.0f * chosen) * -logf(fmaxf(1e-6f, 1.0f - rnd(seed)));
                const float phi = 2.0f * ML_PI * rnd(seed), lx = r * cosf(phi), ly = r * sinf(phi);
                const float axis = rnd(seed);
                float3 down, offset;
                if (axis < 0.75f) { down = -ns; offset = frame.t * lx + frame.b * ly; }
                else if (axis < 0.8125f) { down = -frame.t; offset = frame.b * lx + ns * ly; }
                else if (axis < 0.875f) { down = frame.t; offset = frame.b * lx + ns * ly; }
                else if (axis < 0.9375f) { down = -frame.b; offset = ns * lx + frame.t * ly; }
                else { down = frame.b; offset = ns * lx + frame.t * ly; }
                const float search = fmaxf(fminf(r, furthest), nearest);
                const float3 above = hit.p + offset - down * search;
                Hit under;
                traceRadiance(above, down, under, 2.0f * search, SEEN_ALL);
                if (!under.valid || under.instance != hit.instance) continue;
                // Only a face turned toward where the look came from counts.
                if (-dot(under.ns, down) < 1e-5f) continue;
                const float3 apart = hit.p - under.p;
                const float gone = length(apart);
                if (gone > furthest) continue;
                const float ax = dot(apart, frame.t), ay = dot(apart, frame.b), an = dot(apart, ns);
                const float rn = fmaxf(sqrtf(ax * ax + ay * ay), 0.001f), rx = fmaxf(sqrtf(ay * ay + an * an), 0.001f), ry = fmaxf(sqrtf(an * an + ax * ax), 0.001f);
                // A profile's density over the surface at a distance: its shape there, over eight pi times the distance.
                const float dn = (share.x * profileShape(rn, width.x) + share.y * profileShape(rn, width.y) + share.z * profileShape(rn, width.z)) / (8.0f * ML_PI * rn);
                const float dx = (share.x * profileShape(rx, width.x) + share.y * profileShape(rx, width.y) + share.z * profileShape(rx, width.z)) / (8.0f * ML_PI * rx);
                const float dy = (share.x * profileShape(ry, width.x) + share.y * profileShape(ry, width.y) + share.z * profileShape(ry, width.z)) / (8.0f * ML_PI * ry);
                const float every = 0.75f * dn * fabsf(dot(ns, under.ns)) + 0.125f * dx * fabsf(dot(frame.t, under.ns)) + 0.125f * dy * fabsf(dot(frame.b, under.ns));
                if (!(every > 0.0f)) continue;
                const float at = fmaxf(gone, 0.001f);
                const float3 given = albedo * make_float3(profileShape(at, width.x), profileShape(at, width.y), profileShape(at, width.z))
                                   * (1.0f / (8.0f * ML_PI * at * every));
                if (!finite(given)) continue;
                measured += given;
                found[count] = given; from[count] = above; way[count] = down; span[count] = 2.0f * search; through_[count] = false;
                ++count;
            }
            // Made up to what a flat, endless surface gives, channel by channel, where enough was found to go by.
            measured = measured * (1.0f / float(tries));
            const float3 made = make_float3(measured.x > 0.01f ? albedo.x / measured.x : 1.0f, measured.y > 0.01f ? albedo.y / measured.y : 1.0f,
                                            measured.z > 0.01f ? albedo.z / measured.z : 1.0f);
            for (int i = 0; i < count; ++i) found[i] = found[i] * made;
            // Through the solid: a way in, anywhere within 85 degrees of straight down, to a far side that faces away.
            for (int i = 0; i < tries && count < 8; ++i) {
                const float lowest = 0.0871557f;   // cos 85 degrees
                const float z = 1.0f - rnd(seed) * (1.0f - lowest), ring = sqrtf(fmaxf(0.0f, 1.0f - z * z)), turn = 2.0f * ML_PI * rnd(seed);
                const float3 in = -(frame.t * (ring * cosf(turn)) + frame.b * (ring * sinf(turn)) + ns * z);
                const float3 start = offsetOrigin(hit.p, ng, in);
                Hit far;
                traceRadiance(start, in, far, furthest, SEEN_ALL);
                if (!far.valid || far.instance != hit.instance) continue;
                // Its outside is the side the look is heading for; it must face away from where the light went in.
                const float3 outside = dot(far.ns, in) < 0.0f ? -far.ns : far.ns;
                if (dot(outside, ns) > -1e-5f) continue;
                const float gone = fmaxf(far.t, 0.001f);
                const float3 given = albedo * make_float3(profileShape(gone, width.x), profileShape(gone, width.y), profileShape(gone, width.z))
                                   * (gone * gone / (8.0f * ML_PI * gone * fmaxf(fabsf(dot(outside, in)), 0.05f)) * (2.0f * ML_PI * (1.0f - lowest)));
                if (!finite(given)) continue;
                found[count] = given; from[count] = start; way[count] = in; span[count] = far.t * 1.01f + 1e-5f; through_[count] = true;
                ++count;
            }
            // One of them is followed, the likelier the more light it carries, and stands for them all.
            float whole = 0.0f;
            for (int i = 0; i < count; ++i) { heavy[i] = found[i].x + found[i].y + found[i].z; whole += heavy[i]; }
            if (!(whole > 0.0f)) break;
            int taken = count - 1;
            float left = rnd(seed) * whole;
            for (int i = 0; i < count; ++i) { if (left < heavy[i]) { taken = i; break; } left -= heavy[i]; }
            if (!(heavy[taken] > 0.0f)) break;
            // What comes out is diffuse light, already dimmed by what the surface reflected.
            throughput *= surface.frontKeep * (entering(surface, wo) * (1.0f - surface.transmission) / ((1.0f - through) * beneath))
                        * found[taken] * (whole / (heavy[taken] * float(tries)));
            entryInstance = hit.instance;
            origin = from[taken];
            direction = way[taken];
            seen = SEEN_ALL;
            reach = span[taken];
            probing = true;
            walked = through_[taken];
            --depth;    // coming out again is not a bounce
            continue;
        }

        const bool glossy = rnd(seed) < lobes.specular;
        float3 wi;
        if (!glossy) {
            if (lobes.back > 0.0f && rnd(seed) < lobes.back) {
                wi = sampleDiffuse(u1, u2);
                wi.z = -wi.z;
            }
            else wi = lobes.sheen > 0.0f && rnd(seed) < lobes.sheen ? sampleSheen(wo, u1, u2) : sampleDiffuse(u1, u2);
        }
        else if (rnd(seed) < lobes.coat) wi = reflectAbout(wo, sampleFacet(surface.coatAlpha, wo, u1, u2));
        else if (rnd(seed) < broadShare(surface)) wi = sampleDiffuse(u1, u2);
        else wi = reflectAbout(wo, surface.beckmann ? sampleBeckmann(surface.alphaX, surface.alphaY, u1, u2) : sampleFacet(surface.alpha, wo, u1, u2));
        const BsdfEval e = evalBsdf(surface, lobes, wo, wi);
        bsdfPdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
        direction = frame.toWorld(wi);
        // A direction through the surface is good only as light passing through it, and one off it only as a reflection.
        if (bsdfPdf <= 0.0f || (dot(ng, direction) <= 0.0f) != (wi.z < 0.0f)) break;
        // The reflective lobes were reached by taking neither the transmission branch nor the
        // one beneath the surface.
        const float scale = 1.0f / (bsdfPdf * (1.0f - through) * (1.0f - beneath));
        lightWeight = (e.diffuse + e.specular) * scale;
        bounceWeight = ((diffuseBounces ? e.diffuse : vec(0.0f)) + (glossyBounces ? e.specular : vec(0.0f))) * scale;
        bounces = diffuseBounces || glossyBounces;
        sharp = false;
        clampFound = roughDepth >= params.sampleClampDepth;
        ++roughDepth;
        if (glossy) ++glossyDepth; else ++diffuseDepth;
        // Light through a rough surface is diffuse light; off its shine, a reflection.
        seen = glossy ? SEEN_REFLECTED : SEEN_DIFFUSE;
        origin = offsetOrigin(hit.p, ng, direction);
    }
    if (!finite(radiance)) radiance = vec(0.0f);

    // Sample 0 overwrites, so a reset needs no clear.
    const float weight = 1.0f / float(params.sample + 1);
    float4* beauty = reinterpret_cast<float4*>(params.beauty) + pixel;
    float4* albedo = reinterpret_cast<float4*>(params.albedo) + pixel;
    float4* normal = reinterpret_cast<float4*>(params.normal) + pixel;
    const float3 b = lerp(make_float3(beauty->x, beauty->y, beauty->z), radiance, weight);
    const float3 a = lerp(make_float3(albedo->x, albedo->y, albedo->z), guideAlbedo, weight);
    const float3 n = lerp(make_float3(normal->x, normal->y, normal->z), guideNormal, weight);
    *beauty = make_float4(b.x, b.y, b.z, 1.0f);
    *albedo = make_float4(a.x, a.y, a.z, 1.0f);
    *normal = make_float4(n.x, n.y, n.z, 0.0f);
    if (params.half && !(params.sample & 1)) {
        // The mean of the even samples alone: how far it is from the mean of them all tells how noisy that still is.
        float4* half = reinterpret_cast<float4*>(params.half) + pixel;
        const float3 h = lerp(make_float3(half->x, half->y, half->z), radiance, 1.0f / float(params.sample / 2 + 1));
        *half = make_float4(h.x, h.y, h.z, 1.0f);
    }
}

extern "C" __global__ void __miss__radiance() {}

extern "C" __global__ void __miss__shadow() {
    optixSetPayload_0(1);
}

// ---- Material layers ---------------------------------------------------------------------------

// The plugin's ModoTextureMap blend modes, numbered as in its BLENDS table.
ML_INLINE float blendValue(float a, float b, unsigned mode) {
    switch (mode) {
    case 1: return a * b;
    case 2: return a + b;
    case 3: return a - b;
    case 4: return 1.0f - (1.0f - a) * (1.0f - b);
    case 5: return a / fmaxf(1e-6f, b);
    case 6: return fabsf(a - b);
    case 7: return fminf(a, b);
    case 8: return fmaxf(a, b);
    case 9: return a < 0.5f ? 2.0f * a * b : 1.0f - 2.0f * (1.0f - a) * (1.0f - b);
    case 10: return b < 0.5f ? 2.0f * a * b : 1.0f - 2.0f * (1.0f - a) * (1.0f - b);
    case 11: return a + b - 2.0f * a * b;
    case 12: return b <= 0.5f ? a - (1.0f - 2.0f * b) * a * (1.0f - a)
                              : a + (2.0f * b - 1.0f) * ((a <= 0.25f ? ((16.0f * a - 12.0f) * a + 4.0f) * a : sqrtf(fmaxf(0.0f, a))) - a);
    case 13: return b >= 1.0f ? 1.0f : fminf(1.0f, a / fmaxf(1e-6f, 1.0f - b));
    case 14: return b <= 0.0f ? 0.0f : 1.0f - fminf(1.0f, (1.0f - a) / fmaxf(1e-6f, b));
    default: return b;
    }
}
ML_INLINE float3 blendColor(float3 below, float3 value, unsigned mode, float alpha) {
    float3 mixed = make_float3(blendValue(below.x, value.x, mode), blendValue(below.y, value.y, mode),
                               blendValue(below.z, value.z, mode));
    if (mode == 15) {
        // Two normal maps combined so that each keeps its own tilt (reoriented normal mapping).
        const float3 t = below * 2.0f + make_float3(-1.0f, -1.0f, 0.0f);
        const float3 u = value * make_float3(-2.0f, -2.0f, 2.0f) + make_float3(1.0f, 1.0f, -1.0f);
        const float3 n = t * (dot(t, u) / fmaxf(1e-6f, t.z)) - u;
        mixed = dot(n, n) > 1e-12f ? normalize(n) * 0.5f + vec(0.5f) : below;
    }
    return lerp(below, mixed, clamp(alpha, 0.0f, 1.0f));
}

// The curves the plugin puts on a layer's value. Gamma is MoonRay's ColorCorrectGammaMap, bias its
// RemapMap (which also clamps), and gain the plugin's own ModoTextureMap curve.
ML_INLINE float gammaCurve(float value, float gamma) {
    return value > 0.0f ? powf(value, 1.0f / fmaxf(gamma, 1e-6f)) : value;
}
ML_INLINE float biasCurve(float value, float bias) {
    if (bias != 0.5f && value > 0.0f && value < 1.0f) value = bias <= 0.0f ? 0.0f : powf(value, logf(bias) / logf(0.5f));
    return clamp(value, 0.0f, 1.0f);
}
ML_INLINE float gainCurve(float value, float gain) {
    const float x = clamp(value, 0.0f, 1.0f), g = clamp(gain, 0.00001f, 0.99999f);
    const float y = x < 0.5f ? 2.0f * x : 2.0f - 2.0f * x;
    const float b = y / ((1.0f / (1.0f - g) - 2.0f) * (1.0f - y) + 1.0f);
    return x < 0.5f ? 0.5f * b : 1.0f - 0.5f * b;
}
ML_INLINE float3 applyCurves(const DeviceLayer& layer, float3 value) {
    if (layer.bias != 0.5f) value = make_float3(biasCurve(value.x, layer.bias), biasCurve(value.y, layer.bias), biasCurve(value.z, layer.bias));
    if (layer.gainCurve != 0.5f)
        value = make_float3(gainCurve(value.x, layer.gainCurve), gainCurve(value.y, layer.gainCurve), gainCurve(value.z, layer.gainCurve));
    return value;
}

// The plugin's checker and value noise, as its ModoTextureMap computes them.
ML_INLINE float latticeValue(int x, int y) {
    unsigned h = unsigned(x) * 73856093u ^ unsigned(y) * 19349663u;
    h ^= h >> 16; h *= 0x7feb352du; h ^= h >> 15; h *= 0x846ca68bu; h ^= h >> 16;
    return float(h & 0xffffffu) / 16777215.0f;
}
ML_INLINE float valueNoise(float x, float y) {
    const float fx = floorf(x), fy = floorf(y);
    const int ix = int(fx), iy = int(fy);
    float u = x - fx, v = y - fy;
    u = u * u * (3.0f - 2.0f * u);
    v = v * v * (3.0f - 2.0f * v);
    return (1.0f - v) * ((1.0f - u) * latticeValue(ix, iy) + u * latticeValue(ix + 1, iy))
         + v * ((1.0f - u) * latticeValue(ix, iy + 1) + u * latticeValue(ix + 1, iy + 1));
}
ML_INLINE float pattern(const DeviceLayer& layer, float u, float v) {
    if (layer.flags & LAYER_CHECKER) return float((int(floorf(u * 2.0f)) + int(floorf(v * 2.0f))) & 1);
    const int octaves = min(12, max(1, int(layer.octaves)));
    const float lacunarity = fmaxf(0.01f, layer.lacunarity), persistence = clamp(layer.persistence, 0.0f, 1.0f);
    float value = 0.0f, amplitude = 1.0f, total = 0.0f;
    for (int i = 0; i < octaves; ++i) {
        value += amplitude * valueNoise(u, v);
        total += amplitude;
        u *= lacunarity;
        v *= lacunarity;
        amplitude *= persistence;
    }
    return value / total;
}

struct Corners {
    float2 a, b, c;
};

// The three texture coordinates of a triangle in one scene-wide slot; false if the mesh has none.
ML_INLINE bool triangleUvs(const DeviceMesh& mesh, unsigned slot, unsigned primitive, Corners& uv) {
    if (!mesh.uvs || slot >= UV_SLOTS || mesh.uvSet[slot] < 0) return false;
    if (mesh.curves) {
        // A strand has one coordinate, where it grows from; the whole of it is that colour.
        uv.a = uv.b = uv.c = reinterpret_cast<const float2*>(mesh.uvs)[reinterpret_cast<const unsigned*>(mesh.indices)[primitive]];
        return true;
    }
    const float2* values = reinterpret_cast<const float2*>(mesh.uvs) + ((unsigned long long)(mesh.uvSet[slot]) * mesh.triangleCount + primitive) * 3;
    uv.a = values[0];
    uv.b = values[1];
    uv.c = values[2];
    return true;
}

// Which coordinate slots the last normal map and the last bump row used; UV_SLOTS for none.
struct MappedSlots {
    unsigned normal, bump;
};

// Runs a material's layer stack at a point, bottom row first, as the plugin's texture graph does:
// rows blend over the rows beneath them, a group blends what its rows produced over what was
// there before it, and a mask row scales how strongly its target is applied. shift moves every
// coordinate lookup, which is how a bump map's slope is measured.
// Modo's roughness as the roughness of the lobe that draws the same highlight, for its Blinn (1), Ashikhmin (2)
// and GTR (3) models: read along straight lines between what was measured. Keep in step with shading_models.py.
ML_INLINE float modoRoughness(unsigned model, float roughness, float& strength) {
    const float from[8] = {0.0f, 0.1f, 0.2f, 0.35f, 0.5f, 0.7f, 0.9f, 1.0f};
    // What the highlight's strength is multiplied by at each of those roughnesses.
    const float blinnStrength[8] = {0.301f, 0.301f, 0.363f, 0.520f, 0.590f, 0.598f, 0.730f, 0.730f};
    const float ashikhminStrength[8] = {1.0f, 1.0f, 1.0f, 0.855f, 0.809f, 0.785f, 0.770f, 0.770f};
    const float gtrStrength[8] = {1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 0.848f, 0.762f, 0.762f};
    const float* strong = model == 1 ? blinnStrength : model == 2 ? ashikhminStrength : gtrStrength;
    const float blinn[8] = {0.0f, 0.20f, 0.28f, 0.36f, 0.36f, 0.38f, 0.50f, 0.50f};
    const float ashikhmin[8] = {0.0f, 0.22f, 0.28f, 0.38f, 0.44f, 0.48f, 0.50f, 0.50f};
    const float gtr[8] = {0.0f, 0.16f, 0.22f, 0.36f, 0.50f, 0.70f, 0.90f, 0.90f};
    const float* to = model == 1 ? blinn : model == 2 ? ashikhmin : gtr;
    for (int i = 1; i < 8; ++i)
        if (roughness <= from[i]) {
            const float t = (roughness - from[i - 1]) / (from[i] - from[i - 1]);
            strength = strong[i - 1] + (strong[i] - strong[i - 1]) * t;
            return to[i - 1] + (to[i] - to[i - 1]) * t;
        }
    strength = strong[7];
    return to[7];
}

ML_INLINE MappedSlots evalLayers(const DeviceMaterial& material, const DeviceMesh& mesh, unsigned primitive,
                                 float2 barycentrics, float3* channel, float2 shift) {
    channel[CHANNEL_COLOR] = vec(material.color);
    channel[CHANNEL_COLOR_AMOUNT] = vec(material.colorAmount);
    channel[CHANNEL_ROUGHNESS] = vec(material.roughness);
    channel[CHANNEL_METALLIC] = vec(material.metallic);
    channel[CHANNEL_EMISSION] = vec(material.emission);
    channel[CHANNEL_EMISSION_AMOUNT] = vec(material.emissionAmount);
    channel[CHANNEL_NORMAL] = make_float3(0.5f, 0.5f, 1.0f);
    channel[CHANNEL_TRANSMISSION] = vec(material.transmission);
    channel[CHANNEL_TRANSMISSION_COLOR] = vec(material.transmissionColor);
    channel[CHANNEL_TRANSMISSION_ROUGHNESS] = vec(material.transmissionRoughness);
    channel[CHANNEL_COAT] = vec(material.coat);
    channel[CHANNEL_COAT_ROUGHNESS] = vec(material.coatRoughness);
    channel[CHANNEL_DISSOLVE] = vec(material.dissolve);
    channel[CHANNEL_BUMP] = vec(0.0f);
    channel[CHANNEL_GROUP_MASK] = vec(1.0f);
    channel[CHANNEL_ANISOTROPY] = vec(material.anisotropy);
    channel[CHANNEL_SUBSURFACE] = vec(material.subsurface);
    channel[CHANNEL_SUBSURFACE_COLOR] = vec(material.subsurfaceColor);
    for (unsigned c = CHANNEL_DRIVER; c < CHANNEL_DRIVER + 4; ++c) channel[c] = vec(0.0f);
    channel[CHANNEL_SPECULAR] = vec(1.0f);
    for (unsigned slot = 0; slot < DISPLACE_SLOTS; ++slot) channel[CHANNEL_DISPLACE + slot] = vec(0.0f);
    MappedSlots slots;
    slots.normal = slots.bump = UV_SLOTS;

    float3 saved[GROUP_DEPTH][CHANNEL_COUNT];
    unsigned savedUsed[GROUP_DEPTH];
    unsigned level = 0, used = 0;
    float masks[MASK_REGISTERS] = {1.0f, 1.0f, 1.0f, 1.0f};
    const unsigned colours = (1u << CHANNEL_COLOR) | (1u << CHANNEL_EMISSION) | (1u << CHANNEL_TRANSMISSION_COLOR)
                           | (1u << CHANNEL_SUBSURFACE_COLOR);

    const DeviceLayer* layers = reinterpret_cast<const DeviceLayer*>(params.layers) + material.layerStart;
    for (unsigned i = 0; i < material.layerCount; ++i) {
        const DeviceLayer& layer = layers[i];
        const float masked = (layer.flags & LAYER_MASKED) ? masks[(layer.flags >> LAYER_MASK_SHIFT) & (MASK_REGISTERS - 1)] : 1.0f;
        if (layer.channel == LAYER_GROUP_BEGIN) {
            if (level < GROUP_DEPTH) {
                for (unsigned c = 0; c < CHANNEL_COUNT; ++c) saved[level][c] = channel[c];
                savedUsed[level] = used;
                used = 0;
                channel[CHANNEL_GROUP_MASK] = vec(1.0f);
                ++level;
            }
            continue;
        }
        if (layer.channel == LAYER_GROUP_END) {
            if (level) {
                --level;
                const float groupMask = (used >> CHANNEL_GROUP_MASK) & 1 ? average(channel[CHANNEL_GROUP_MASK]) : 1.0f;
                for (unsigned c = 0; c < CHANNEL_COUNT; ++c) {
                    if (c == CHANNEL_GROUP_MASK || !((used >> c) & 1)) continue;
                    const float3 value = ((layer.flags & LAYER_INVERT) && ((colours >> c) & 1)) ? vec(1.0f) - channel[c] : channel[c];
                    channel[c] = blendColor(saved[level][c], value, layer.blend, layer.opacity * groupMask * masked);
                }
                channel[CHANNEL_GROUP_MASK] = saved[level][CHANNEL_GROUP_MASK];
                used = savedUsed[level] | (used & ~(1u << CHANNEL_GROUP_MASK));
            }
            continue;
        }
        const bool writesMask = layer.channel >= LAYER_MASK_BASE && layer.channel < LAYER_MASK_BASE + MASK_REGISTERS;
        if (layer.channel >= CHANNEL_COUNT && !writesMask) continue;

        float3 value = vec(layer.value);
        float mask = masked;
        const bool patterned = (layer.flags & (LAYER_CHECKER | LAYER_NOISE)) != 0;
        if (layer.flags & (LAYER_IMAGE | LAYER_UDIM | LAYER_CHECKER | LAYER_NOISE)) {
            Corners uv;
            if (!triangleUvs(mesh, layer.uvSlot, primitive, uv)) continue;     // nothing to look the row up with
            const float w = 1.0f - barycentrics.x - barycentrics.y;
            const float u = (uv.a.x * w + uv.b.x * barycentrics.x + uv.c.x * barycentrics.y + shift.x) * layer.scale[0];
            const float v = (uv.a.y * w + uv.b.y * barycentrics.x + uv.c.y * barycentrics.y + shift.y) * layer.scale[1];
            if (patterned) {
                // The pattern mixes the row's two colours, and how much of the row each covers.
                const float t = applyCurves(layer, vec(pattern(layer, u, v))).x;
                value = lerp(value, vec(layer.color2), t);
                mask *= layer.alpha1 + (layer.alpha2 - layer.alpha1) * t;
            } else {
                unsigned long long texture = layer.texture;
                float tu = u, tv = v;
                if (layer.flags & LAYER_UDIM) {
                    // One image per unit square of the coordinates, ten squares to a row.
                    const unsigned long long* tiles = reinterpret_cast<const unsigned long long*>(layer.texture);
                    const float column = floorf(u), row = floorf(v);
                    if (column < 0.0f || column >= 10.0f || row < 0.0f) continue;
                    const unsigned long long tile = (unsigned long long)(column) + 10ull * (unsigned long long)(row);
                    if (tile >= tiles[0] || !tiles[1 + tile]) continue;
                    texture = tiles[1 + tile];
                    tu = u - column;
                    tv = v - row;
                }
                // Images are stored top row first; texture v runs upwards.
                const float4 texel = tex2D<float4>(texture, tu, 1.0f - tv);
                value = (layer.flags & LAYER_ALPHA_ONLY) ? vec(texel.w) : make_float3(texel.x, texel.y, texel.z);
                if (layer.flags & LAYER_ALPHA_MASK) mask *= texel.w;
                if (((layer.flags & LAYER_COVERAGE_U) && (u < 0.0f || u > 1.0f)) || ((layer.flags & LAYER_COVERAGE_V) && (v < 0.0f || v > 1.0f)))
                    mask = 0.0f;
            }
            if (layer.channel == CHANNEL_NORMAL) slots.normal = layer.uvSlot;
            if (layer.channel == CHANNEL_BUMP) slots.bump = layer.uvSlot;
        } else if (layer.flags & LAYER_RAMP) {
            // A gradient: 257 colours from 0 to 1, looked up by the first component of another channel.
            if (layer.uvSlot >= CHANNEL_COUNT) continue;
            const float4 texel = tex2D<float4>(layer.texture, (clamp(channel[layer.uvSlot].x, 0.0f, 1.0f) * 256.0f + 0.5f) / 257.0f, 0.5f);
            value = make_float3(texel.x, texel.y, texel.z);
            mask *= texel.w;
        }
        if (layer.flags & LAYER_FLIP_RED) value.x = 1.0f - value.x;
        if (layer.flags & LAYER_FLIP_GREEN) value.y = 1.0f - value.y;
        if (layer.flags & LAYER_FLIP_BLUE) value.z = 1.0f - value.z;
        const unsigned pick = (layer.flags >> LAYER_PICK_SHIFT) & 3;
        if (pick) value = vec(pick == 1 ? value.x : pick == 2 ? value.y : value.z);
        if ((layer.flags & LAYER_CURVES) && layer.gamma != 1.0f)
            value = make_float3(gammaCurve(value.x, layer.gamma), gammaCurve(value.y, layer.gamma), gammaCurve(value.z, layer.gamma));
        value = value * layer.gain + vec(layer.offset);
        if ((layer.flags & LAYER_CURVES) && !patterned) value = applyCurves(layer, value);
        if (layer.flags & LAYER_INVERT) value = vec(1.0f) - value;
        if (writesMask) {
            // A mask starts fully open and is blended like any other row.
            masks[layer.channel - LAYER_MASK_BASE] = average(blendColor(vec(1.0f), value, layer.blend, layer.opacity * mask));
            continue;
        }
        channel[layer.channel] = blendColor(channel[layer.channel], value, layer.blend, layer.opacity * mask);
        used |= 1u << layer.channel;
    }
    return slots;
}

// Presence: a surface that is partly absent lets each ray through with that probability, for
// camera and bounce rays, and for shadow rays where presence shadows are on. With them off, as MoonRay has them
// unless asked, a ray looking for a light is stopped by such a surface as by any other.
ML_INLINE void absent(const DeviceMaterial& material, const DeviceMesh& mesh, unsigned primitive, float2 barycentrics) {
    if (!(material.flags & MATERIAL_HAS_PRESENCE)) return;
    if (params.opaqueShadows && (optixGetRayFlags() & OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT)) return;
    float3 channel[CHANNEL_COUNT];
    channel[CHANNEL_DISSOLVE] = vec(material.dissolve);
    if (material.layerCount) evalLayers(material, mesh, primitive, barycentrics, channel, make_float2(0.0f, 0.0f));
    // The payload differs from ray to ray and the sample index from pass to pass.
    unsigned state = tea(optixGetPayload_1() ^ (primitive * 0x9e3779b9u) ^ (optixGetInstanceId() * 0x85ebca6bu),
                         optixGetPayload_0() ^ params.sample);
    if (rnd(state) < clamp(average(channel[CHANNEL_DISSOLVE]), 0.0f, 1.0f)) optixIgnoreIntersection();
}
extern "C" __global__ void __anyhit__presence() {
    const DeviceInstance& instance = reinterpret_cast<const DeviceInstance*>(params.instances)[optixGetInstanceId()];
    const DeviceMesh& mesh = reinterpret_cast<const DeviceMesh*>(params.meshes)[instance.mesh];
    const unsigned primitive = optixGetPrimitiveIndex();
    const unsigned materialIndex = mesh.materialIds ? reinterpret_cast<const unsigned*>(mesh.materialIds)[primitive] : instance.material;
    const DeviceMaterial& material = reinterpret_cast<const DeviceMaterial*>(params.materials)[materialIndex];
    if (material.flags & MATERIAL_VOLUME) {
        // A fog with a grid has no edge to meet: every ray works out for itself where it runs through the grid's cube.
        if (reinterpret_cast<const DeviceVolume*>(params.volumes)[material.hair].grid) {
            optixIgnoreIntersection();
            return;
        }
        // The edge of a fog stops no light itself. A ray looking for a light notes the fog it crosses and goes on; a ray
        // looking for what is there to see takes the edge as its hit, to know it is in fog from there, unless it looks
        // for surfaces only.
        if (!(optixGetRayFlags() & OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT)) {
            if (hitPayload()->valid == HIT_SURFACES_ONLY) optixIgnoreIntersection();
            return;
        }
        const DeviceVolume& fog = reinterpret_cast<const DeviceVolume*>(params.volumes)[material.hair];
        const float sign = optixIsBackFaceHit() ? 1.0f : -1.0f, crossed = sign * optixGetRayTmax();
        optixSetPayload_2(__float_as_uint(__uint_as_float(optixGetPayload_2()) + crossed * fog.extinction[0]));
        optixSetPayload_3(__float_as_uint(__uint_as_float(optixGetPayload_3()) + crossed * fog.extinction[1]));
        optixSetPayload_4(__float_as_uint(__uint_as_float(optixGetPayload_4()) + crossed * fog.extinction[2]));
        optixSetPayload_5(__float_as_uint(__uint_as_float(optixGetPayload_5()) - sign * fog.extinction[0]));
        optixSetPayload_6(__float_as_uint(__uint_as_float(optixGetPayload_6()) - sign * fog.extinction[1]));
        optixSetPayload_7(__float_as_uint(__uint_as_float(optixGetPayload_7()) - sign * fog.extinction[2]));
        optixIgnoreIntersection();
        return;
    }
    absent(material, mesh, primitive, optixGetTriangleBarycentrics());
}

// The same for a strand, which is as absent as its material says.
extern "C" __global__ void __anyhit__curve() {
    const DeviceInstance& instance = reinterpret_cast<const DeviceInstance*>(params.instances)[optixGetInstanceId()];
    const DeviceMaterial& material = reinterpret_cast<const DeviceMaterial*>(params.materials)[instance.material];
    if (material.flags & MATERIAL_VOLUME) return;
    const DeviceMesh& mesh = reinterpret_cast<const DeviceMesh*>(params.meshes)[instance.mesh];
    if ((material.flags & MATERIAL_HAS_PRESENCE) && (mesh.curves & 2) && mesh.normals) {
        // Straight pieces meet in a ball, half of which is inside the strand. Through a strand that is partly absent
        // it would show, so along a strand only the pieces' sides count; its two ends keep their caps.
        const float u = optixGetCurveParameter();
        if (u <= 0.0f || u >= 1.0f) {
            const float along = reinterpret_cast<const float3*>(mesh.normals)[reinterpret_cast<const unsigned*>(mesh.indices)[optixGetPrimitiveIndex()] + (u >= 1.0f ? 1 : 0)].x;
            if (along > 0.0f && along < 1.0f) { optixIgnoreIntersection(); return; }
        }
    }
    absent(material, mesh, optixGetPrimitiveIndex(), make_float2(0.0f, 0.0f));
}

// How the surface runs along texture u and v in one coordinate slot, in world space; false
// without usable coordinates.
ML_INLINE bool surfaceAxes(const DeviceMesh& mesh, unsigned slot, unsigned primitive, float3 e1, float3 e2,
                           float3& alongU, float3& alongV) {
    Corners corners;
    if (slot >= UV_SLOTS || !triangleUvs(mesh, slot, primitive, corners)) return false;
    const float2 d1 = make_float2(corners.b.x - corners.a.x, corners.b.y - corners.a.y);
    const float2 d2 = make_float2(corners.c.x - corners.a.x, corners.c.y - corners.a.y);
    const float determinant = d1.x * d2.y - d1.y * d2.x;
    if (fabsf(determinant) <= 1e-20f) return false;
    alongU = (e1 * d2.y - e2 * d1.y) * (1.0f / determinant);
    alongV = (e2 * d1.x - e1 * d2.x) * (1.0f / determinant);
    return true;
}

// Material colours are worked out in Rec.709 and shaded in the working space.
ML_INLINE float3 working(float3 c) {
    if (!params.working) return c;
    const float* m = params.workingMatrix;
    return make_float3(dot(vec(m), c), dot(vec(m + 3), c), dot(vec(m + 6), c));
}

// The material at a hit, with its layers run: everything about the surface that does not depend on how the
// geometry lies. channel is left holding the layers' results, and anisotropy what the material asks for.
ML_INLINE MappedSlots resolveMaterial(Hit* hit, const DeviceMaterial& material, const DeviceMesh& mesh, unsigned primitive, float2 uv,
                                    float3* channel, float& anisotropy) {
    MappedSlots slots;
    float3 reach;
    float subsurface;
    hit->ior = material.ior;
    hit->specular = material.specular;
    hit->transmissionIor = material.transmissionIor;
    hit->flags = material.flags;
    hit->hair = material.hair;
    hit->abbe = material.abbe;
    hit->absorptionDistance = material.absorptionDistance;
    slots.normal = slots.bump = UV_SLOTS;
    if (material.layerCount) {
        slots = evalLayers(material, mesh, primitive, uv, channel, make_float2(0.0f, 0.0f));
        // A stack's highlight: the lobe set for the most any of its rows reflects, weighted by this point's share.
        hit->specular = material.specular * clamp(average(channel[CHANNEL_SPECULAR]), 0.0f, 1.0f);
        // Scalars take the mean of a colour, as MoonRay does for a map bound to a float attribute.
        hit->albedo = channel[CHANNEL_COLOR] * channel[CHANNEL_COLOR_AMOUNT];
        hit->emission = channel[CHANNEL_EMISSION] * channel[CHANNEL_EMISSION_AMOUNT];
        hit->roughness = clamp(average(channel[CHANNEL_ROUGHNESS]), 0.0f, 1.0f);
        if (material.flags & MATERIAL_ROUGH_MASK) {
            // The highlight's strength goes with the roughness, as it does for a roughness that is one value.
            float strength = 1.0f;
            hit->roughness = modoRoughness((material.flags & MATERIAL_ROUGH_MASK) >> MATERIAL_ROUGH_SHIFT, hit->roughness, strength);
            hit->specular = fminf(hit->specular * strength, 1.0f);
        }
        hit->metallic = clamp(average(channel[CHANNEL_METALLIC]), 0.0f, 1.0f);
        hit->transmission = clamp(average(channel[CHANNEL_TRANSMISSION]), 0.0f, 1.0f);
        hit->transmissionColor = channel[CHANNEL_TRANSMISSION_COLOR];
        hit->transmissionRoughness = clamp(average(channel[CHANNEL_TRANSMISSION_ROUGHNESS]), 0.0f, 1.0f);
        hit->coat = clamp(average(channel[CHANNEL_COAT]), 0.0f, 1.0f);
        hit->coatRoughness = clamp(average(channel[CHANNEL_COAT_ROUGHNESS]), 0.0f, 1.0f);
        subsurface = clamp(average(channel[CHANNEL_SUBSURFACE]), 0.0f, 1.0f);
        reach = channel[CHANNEL_SUBSURFACE_COLOR];
        anisotropy = clamp(average(channel[CHANNEL_ANISOTROPY]), -1.0f, 1.0f);
    } else {
        // Most materials have no layers left once the packer has folded their constant rows.
        hit->albedo = vec(material.color) * material.colorAmount;
        hit->emission = vec(material.emission) * material.emissionAmount;
        hit->roughness = material.roughness;
        hit->metallic = material.metallic;
        hit->transmission = material.transmission;
        hit->transmissionColor = vec(material.transmissionColor);
        hit->transmissionRoughness = material.transmissionRoughness;
        hit->coat = material.coat;
        hit->coatRoughness = material.coatRoughness;
        subsurface = material.subsurface;
        reach = vec(material.subsurfaceColor);
        anisotropy = material.anisotropy;
    }
    hit->albedo = working(hit->albedo);
    hit->emission = working(hit->emission);
    hit->transmissionColor = working(hit->transmissionColor);
    hit->underRoughness = material.underRoughness < 0.0f ? hit->roughness : material.underRoughness;
    // A solid that absorbs takes its colour from the distance crossed, not from the surface.
    hit->absorption = hit->transmissionColor;
    if (material.absorptionDistance > 0.0f) hit->transmissionColor = vec(1.0f);
    hit->subsurface = material.subsurfaceRadius > 0.0f ? subsurface : 0.0f;
    reach = working(reach);
    hit->subsurfaceRadius = make_float3(clamp(reach.x, 0.0f, 1.0f), clamp(reach.y, 0.0f, 1.0f), clamp(reach.z, 0.0f, 1.0f))
                          * material.subsurfaceRadius;
    hit->anisotropy = 0.0f;
    hit->tangent = vec(0.0f);
    hit->back = working(vec(material.back));
    hit->frontKeep = vec(material.frontKeep);
    hit->fuzz = material.fuzz;
    hit->fuzzColor = working(vec(material.fuzzColor));
    hit->fuzzRoughness = material.fuzzRoughness;
    hit->fuzzDims = material.fuzzDims;
    return slots;
}

extern "C" __global__ void __closesthit__radiance() {
    Hit* hit = hitPayload();
    const DeviceInstance& instance = reinterpret_cast<const DeviceInstance*>(params.instances)[optixGetInstanceId()];
    const DeviceMesh& mesh = reinterpret_cast<const DeviceMesh*>(params.meshes)[instance.mesh];
    const unsigned primitive = optixGetPrimitiveIndex();
    const uint3 triangle = reinterpret_cast<const uint3*>(mesh.indices)[primitive];
    const float3* positions = reinterpret_cast<const float3*>(mesh.positions);
    const float3 p0 = positions[triangle.x], p1 = positions[triangle.y], p2 = positions[triangle.z];
    const float2 uv = optixGetTriangleBarycentrics();
    const float w = 1.0f - uv.x - uv.y;

    const float3 ng = cross(p1 - p0, p2 - p0);
    float3 ns = ng;
    if (mesh.normals) {
        const float3* normals = reinterpret_cast<const float3*>(mesh.normals);
        ns = normals[triangle.x] * w + normals[triangle.y] * uv.x + normals[triangle.z] * uv.y;
    }
    hit->p = optixTransformPointFromObjectToWorldSpace(p0 * w + p1 * uv.x + p2 * uv.y);
    hit->ng = normalize(optixTransformNormalFromObjectToWorldSpace(ng));
    hit->ns = normalize(optixTransformNormalFromObjectToWorldSpace(ns));
    hit->t = optixGetRayTmax();
    hit->instance = optixGetInstanceId();
    hit->light = instance.light;
    hit->valid = 1;
    hit->curve = 0;

    const unsigned materialIndex = mesh.materialIds ? reinterpret_cast<const unsigned*>(mesh.materialIds)[primitive] : instance.material;
    const DeviceMaterial& material = reinterpret_cast<const DeviceMaterial*>(params.materials)[materialIndex];
    // A toon's way up to the smooth surface: the point moved up to the tangent planes at the triangle's corners,
    // weighted as the point is (Hanika, "Hacking the Shadow Terminator", 2021).
    hit->lift = vec(0.0f);
    if (params.toonTerminator && mesh.normals && (material.flags & MATERIAL_TOON_DIFFUSE) && !(material.flags & (MATERIAL_HAIR | MATERIAL_VOLUME))) {
        const float3* normals = reinterpret_cast<const float3*>(mesh.normals);
        const float3 at = p0 * w + p1 * uv.x + p2 * uv.y;
        const float3 corners[3] = {p0, p1, p2};
        const float3 cornerNormals[3] = {normals[triangle.x], normals[triangle.y], normals[triangle.z]};
        const float weights[3] = {w, uv.x, uv.y};
        float3 lift = vec(0.0f);
        for (int k = 0; k < 3; ++k) {
            const float3 n = normalize(cornerNormals[k]);
            const float below = dot(at - corners[k], n);
            if (below < 0.0f) lift = lift - n * (weights[k] * below);
        }
        hit->lift = optixTransformVectorFromObjectToWorldSpace(lift);
    }
    float3 channel[CHANNEL_COUNT];
    float anisotropy;
    const MappedSlots slots = resolveMaterial(hit, material, mesh, primitive, uv, channel, anisotropy);

    const float3 e1 = optixTransformVectorFromObjectToWorldSpace(p1 - p0), e2 = optixTransformVectorFromObjectToWorldSpace(p2 - p0);
    float3 alongU, alongV;

    // Normal and bump maps tilt the shading normal in the frame the plugin's ModoTextureMap and
    // ModoNormalMap use: the direction texture u runs across the surface, the normal, and their
    // cross product.
    const bool bumped = (material.flags & MATERIAL_HAS_BUMP) && slots.bump < UV_SLOTS;
    if ((bumped || slots.normal < UV_SLOTS) && surfaceAxes(mesh, bumped ? slots.bump : slots.normal, primitive, e1, e2, alongU, alongV)) {
        const float3 n = hit->ns;
        const float3 tangent = alongU - n * dot(alongU, n);
        const float lengthT = length(tangent);
        if (lengthT > 1e-9f) {
            const float3 t = tangent * (1.0f / lengthT), b = cross(n, t);
            // Slopes of the mapped normal, then of the height field on top of them.
            const float3 encoded = channel[CHANNEL_NORMAL] * 2.0f - vec(1.0f);
            const float nz = fmaxf(0.001f, encoded.z);
            float sx = encoded.x / nz, sy = encoded.y / nz;
            if (bumped) {
                const float step = 0.001f;
                float3 other[CHANNEL_COUNT];
                evalLayers(material, mesh, primitive, uv, other, make_float2(step, 0.0f));
                const float right = average(other[CHANNEL_BUMP]);
                evalLayers(material, mesh, primitive, uv, other, make_float2(-step, 0.0f));
                const float left = average(other[CHANNEL_BUMP]);
                evalLayers(material, mesh, primitive, uv, other, make_float2(0.0f, step));
                const float up = average(other[CHANNEL_BUMP]);
                evalLayers(material, mesh, primitive, uv, other, make_float2(0.0f, -step));
                const float down = average(other[CHANNEL_BUMP]);
                const float dx = (right - left) / (2.0f * step * lengthT), dy = (up - down) / (2.0f * step);
                const float crossT = dot(alongV, t), crossB = dot(alongV, b);
                sx -= material.bumpStrength * dx;
                if (fabsf(crossB) > 1e-9f) sy -= material.bumpStrength * (dy - dx * crossT) / crossB;
            }
            const float3 bent = t * sx + b * sy + n;
            if (dot(bent, bent) > 1e-12f) hit->ns = normalize(bent);
        }
    }

    // A stretched specular lobe runs along the material's tangent, an angle from texture u.
    if (anisotropy != 0.0f && surfaceAxes(mesh, material.tangentSlot, primitive, e1, e2, alongU, alongV)) {
        const float3 n = hit->ns;
        const float3 tangent = alongU - n * dot(alongU, n);
        const float lengthT = length(tangent);
        if (lengthT > 1e-9f) {
            const float3 t = tangent * (1.0f / lengthT);
            hit->tangent = t * material.tangent[0] + cross(n, t) * material.tangent[1];
            hit->anisotropy = anisotropy;
        }
    }
}

// A hit on a curve: a round segment, straight or a cubic B-spline, whose control points OptiX hands back.
extern "C" __global__ void __closesthit__curve() {
    Hit* hit = hitPayload();
    hit->lift = vec(0.0f);
    const DeviceInstance& instance = reinterpret_cast<const DeviceInstance*>(params.instances)[optixGetInstanceId()];
    const DeviceMesh& mesh = reinterpret_cast<const DeviceMesh*>(params.meshes)[instance.mesh];
    const unsigned primitive = optixGetPrimitiveIndex();
    float4 control[4];
    // Where along the segment, then the middle of the strand there and the way it runs.
    const float u = optixGetCurveParameter(), v = 1.0f - u;
    float3 centre, along;
    if (mesh.curves & 2) {
        optixGetLinearCurveVertexData(optixGetGASTraversableHandle(), primitive, optixGetSbtGASIndex(), 0.0f, control);
        const float3 q0 = make_float3(control[0].x, control[0].y, control[0].z), q1 = make_float3(control[1].x, control[1].y, control[1].z);
        centre = q0 * v + q1 * u;
        along = q1 - q0;
    } else {
        optixGetCubicBSplineVertexData(optixGetGASTraversableHandle(), primitive, optixGetSbtGASIndex(), 0.0f, control);
        const float3 q0 = make_float3(control[0].x, control[0].y, control[0].z), q1 = make_float3(control[1].x, control[1].y, control[1].z);
        const float3 q2 = make_float3(control[2].x, control[2].y, control[2].z), q3 = make_float3(control[3].x, control[3].y, control[3].z);
        centre = (q0 * (v * v * v) + q1 * (3.0f * u * u * u - 6.0f * u * u + 4.0f) + q2 * (-3.0f * u * u * u + 3.0f * u * u + 3.0f * u + 1.0f)
                  + q3 * (u * u * u)) * (1.0f / 6.0f);
        along = (q0 * (-v * v) + q1 * (3.0f * u * u - 4.0f * u) + q2 * (-3.0f * u * u + 2.0f * u + 1.0f) + q3 * (u * u)) * 0.5f;
        if (dot(along, along) <= 1e-24f) along = q2 - q1;
    }
    if (dot(along, along) <= 1e-24f) along = make_float3(0.0f, 1.0f, 0.0f);
    along = normalize(along);

    const float3 world = optixGetWorldRayOrigin() + optixGetWorldRayDirection() * optixGetRayTmax();
    // Out from the strand's middle: at right angles to it, except on the rounded end and joints of straight
    // pieces, which are parts of spheres. On a flat end cap that leaves nothing, and the cap faces the ray.
    float3 out = optixTransformPointFromWorldToObjectSpace(world) - centre;
    const bool side = !(mesh.curves & 2) || (u > 0.0f && u < 1.0f);
    if (side) out = out - along * dot(out, along);
    if (dot(out, out) <= 1e-24f) {
        const float3 arriving = optixTransformVectorFromWorldToObjectSpace(optixGetWorldRayDirection());
        out = dot(arriving, along) > 0.0f ? -along : along;
    }
    hit->p = world;
    hit->ng = hit->ns = normalize(optixTransformNormalFromObjectToWorldSpace(out));
    // The strand as the ray sees it: the way across it that faces the ray, and how squarely the ray met it.
    const float3 tangent = normalize(optixTransformVectorFromObjectToWorldSpace(along)), back = -optixGetWorldRayDirection();
    const float3 facing = back - tangent * dot(back, tangent);
    const bool edgeOn = dot(facing, facing) <= 1e-12f;
    hit->curveCos = edgeOn ? 1.0f : fabsf(dot(hit->ns, normalize(facing)));
    // MoonRay's default strand is a flat ribbon turned to face each ray, so it is lit as one.
    if ((mesh.curves & 4) && side && !edgeOn) hit->ng = hit->ns = normalize(facing);
    hit->curveAlong = 0.0f;
    hit->curveChance = 0.0f;
    if (mesh.normals) {
        const unsigned first = reinterpret_cast<const unsigned*>(mesh.indices)[primitive] + ((mesh.curves & 2) ? 0 : 1);
        const float3* strand = reinterpret_cast<const float3*>(mesh.normals);
        hit->curveAlong = strand[first].x + (strand[first + 1].x - strand[first].x) * u;
        hit->curveChance = strand[first].y;
    }
    hit->t = optixGetRayTmax();
    hit->instance = optixGetInstanceId();
    hit->light = -1;
    hit->valid = 1;
    hit->curve = 1;
    hit->curveTangent = tangent;

    const DeviceMaterial& material = reinterpret_cast<const DeviceMaterial*>(params.materials)[instance.material];
    float3 channel[CHANNEL_COUNT];
    float anisotropy;
    resolveMaterial(hit, material, mesh, primitive, make_float2(0.0f, 0.0f), channel, anisotropy);
}

// What a displaced mesh's layers give at each of its vertices (Renderer::displacementValues): each displacement channel,
// looked up on one triangle that has the vertex, by the layers of that triangle's material, as they are for shading.
extern "C" __global__ void __raygen__displace() {
    const unsigned i = optixGetLaunchIndex().x;
    const DeviceDisplacePoint point = reinterpret_cast<const DeviceDisplacePoint*>(params.displacePoints)[i];
    const DeviceMesh& mesh = reinterpret_cast<const DeviceMesh*>(params.meshes)[params.displaceMesh];
    const unsigned materialIndex = mesh.materialIds ? reinterpret_cast<const unsigned*>(mesh.materialIds)[point.primitive] : params.displaceMaterial;
    const DeviceMaterial& material = reinterpret_cast<const DeviceMaterial*>(params.materials)[materialIndex];
    float* found = reinterpret_cast<float*>(params.displaceHeights) + size_t(i) * DISPLACE_SLOTS * 3;
    float3 channel[CHANNEL_COUNT];
    for (unsigned slot = 0; slot < DISPLACE_SLOTS; ++slot) channel[CHANNEL_DISPLACE + slot] = vec(0.0f);
    if (material.layerCount)
        evalLayers(material, mesh, point.primitive, make_float2(point.b1, point.b2), channel, make_float2(0.0f, 0.0f));
    for (unsigned slot = 0; slot < DISPLACE_SLOTS; ++slot) {
        found[slot * 3] = channel[CHANNEL_DISPLACE + slot].x;
        found[slot * 3 + 1] = channel[CHANNEL_DISPLACE + slot].y;
        found[slot * 3 + 2] = channel[CHANNEL_DISPLACE + slot].z;
    }
}
