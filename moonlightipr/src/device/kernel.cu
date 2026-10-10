// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// MoonLightIPR device programs: a progressive megakernel path tracer.
// One launch adds one sample per pixel to the running means in LaunchParams.
#include <optix.h>
#include "shared.h"
#include "vec.h"

using namespace moonlightipr;

extern "C" { __constant__ LaunchParams params; }

// What a radiance ray found: the geometry, and the material resolved at that point.
struct Hit {
    float3 p, ng, ns;
    float3 albedo, emission, transmissionColor;
    float roughness, metallic, ior, underRoughness;
    float transmission, transmissionRoughness, transmissionIor, coat, coatRoughness;
    float3 tangent;             // the direction a stretched lobe runs in, when anisotropy is not 0
    float3 subsurfaceRadius;    // mean distance light travels beneath the surface, per channel
    float3 absorption;          // what is left of light after absorptionDistance inside the solid
    float3 back, frontKeep;     // diffuse light passed through to the other side, and what that leaves on this one
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
};

ML_INLINE Hit* hitPayload() {
    return reinterpret_cast<Hit*>((static_cast<unsigned long long>(optixGetPayload_0()) << 32) | optixGetPayload_1());
}

ML_INLINE void traceRadiance(float3 origin, float3 direction, Hit& hit, float distance = 1e16f) {
    const unsigned long long address = reinterpret_cast<unsigned long long>(&hit);
    unsigned p0 = unsigned(address >> 32), p1 = unsigned(address);
    hit.valid = 0;
    optixTrace(params.traversable, origin, direction, 0.0f, distance, 0.0f, OptixVisibilityMask(255),
               params.presence ? OPTIX_RAY_FLAG_NONE : OPTIX_RAY_FLAG_DISABLE_ANYHIT, 0, 1, 0, p0, p1);
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
ML_INLINE float3 gridShadow(float3 origin, float3 direction, float distance, unsigned& seed) {
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
        thick *= step;
        through *= make_float3(expf(-thick * fog.extinction[0]), expf(-thick * fog.extinction[1]), expf(-thick * fog.extinction[2]));
    }
    return through;
}

ML_INLINE float3 shadow(float3 origin, float3 direction, unsigned& seed, float distance = 1e16f) {
    // A fog with a grid is not the same all through, so the any-hit test only notes where the ray goes into it and
    // comes out, and which fog it is; what it stops is added up along that stretch below.
    unsigned unoccluded = 0, stream = seed, d0 = 0, d1 = 0, d2 = 0, e0 = 0, e1 = 0, e2 = 0;
    unsigned entered = __float_as_uint(0.0f), left = __float_as_uint(1e30f), gridded = 0;
    rnd(seed);
    optixTrace(params.traversable, origin, direction, 0.0f, distance, 0.0f, OptixVisibilityMask(255),
               (params.presence ? OPTIX_RAY_FLAG_NONE : OPTIX_RAY_FLAG_DISABLE_ANYHIT)
               | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT | OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT,
               0, 1, 1, unoccluded, stream, d0, d1, d2, e0, e1, e2, entered, left, gridded);
    if (!unoccluded) return vec(0.0f);
    // Asked of every ray where there is any fog at all: one that starts and ends inside a grid crosses no edge of it.
    const float3 through = params.volumeCount ? gridShadow(origin, direction, distance, seed) : vec(1.0f);
    if (!(d0 | d1 | d2 | e0 | e1 | e2)) return through;
    // A fog entered and never left is one the light itself is in: it is crossed from its edge to the ray's end.
    const float3 inside = make_float3(fmaxf(0.0f, __uint_as_float(e0)), fmaxf(0.0f, __uint_as_float(e1)), fmaxf(0.0f, __uint_as_float(e2)));
    const float3 depth = make_float3(__uint_as_float(d0), __uint_as_float(d1), __uint_as_float(d2)) + inside * fminf(distance, 1e12f);
    return through * make_float3(expf(-fmaxf(0.0f, depth.x)), expf(-fmaxf(0.0f, depth.y)), expf(-fmaxf(0.0f, depth.z)));
}

// Moves a ray origin off the surface, towards the side the ray leaves from.
ML_INLINE float3 offsetOrigin(float3 p, float3 ng, float3 direction) {
    const float scale = 1e-4f * (1.0f + fmaxf(fabsf(p.x), fmaxf(fabsf(p.y), fabsf(p.z))));
    return p + ng * (dot(ng, direction) > 0.0f ? scale : -scale);
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
        if (filter.type == FILTER_ROD || filter.type == FILTER_BARN || filter.type == FILTER_COOKIE) {
            const float3 local = make_float3(dot(vec(filter.rows), p) + filter.rows[3], dot(vec(filter.rows + 4), p) + filter.rows[7],
                                             dot(vec(filter.rows + 8), p) + filter.rows[11]);
            if (filter.type == FILTER_ROD) {
                // A box with rounded corners: inside it the light takes the rod's colour, and fades back over its edge.
                const float3 q = make_float3(fabsf(local.x) - filter.a[0], fabsf(local.y) - filter.a[1], fabsf(local.z) - filter.a[2]);
                const float r = length(make_float3(fmaxf(q.x, 0.0f), fmaxf(q.y, 0.0f), fmaxf(q.z, 0.0f))) + fminf(fmaxf(q.x, fmaxf(q.y, q.z)), 0.0f) - filter.a[3];
                float scale = r <= 0.0f ? 0.0f : r < filter.b[0] ? r / filter.b[0] : 1.0f;
                if (filter.flags & FILTER_INVERT) scale = 1.0f - scale;
                scale = 1.0f + (scale - 1.0f) * filter.b[1];
                const float3 colour = vec(filter.b + 2);
                tint = tint * (colour + (vec(1.0f) - colour) * scale);
                continue;
            }
            if (filter.type == FILTER_COOKIE) {
                // A picture thrown from a projector: local is the point's place across it, up it, and what divides both.
                const float outside = (filter.flags & FILTER_WHITE) ? 1.0f : 0.0f;
                if (!(local.z > 0.0f)) {
                    tint = tint * outside;
                    continue;
                }
                const float s = local.x / local.z, t = local.y / local.z;
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
    float3 diffuseNormal;   // the normal diffuse light falls on, in the shading frame
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
    return s;
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
// What reaches the lobes under the coat.
ML_INLINE float underCoat(const Surface& s, float3 wo) {
    return s.coatDims ? 1.0f - s.coat * dielectricFresnel(wo.z, s.ior) : 1.0f;
}
// What the dielectric lets through to whatever is beneath it. MoonRay evaluates this on the
// view direction and blends towards normal incidence as the lobe above gets rougher.
ML_INLINE float entering(const Surface& s, float3 wo) {
    const float grazing = 1.0f - s.specular * dielectricFresnel(wo.z, s.ior), facing = 1.0f - s.specular * dielectricFresnel(1.0f, s.ior);
    return (1.0f - s.metallic) * (grazing + (facing - grazing) * s.underBlend) * underCoat(s, wo);
}
ML_INLINE float3 diffuseColor(const Surface& s, float3 wo) {
    return s.albedo * s.frontKeep * (entering(s, wo) * (1.0f - s.transmission) * s.diffuseScale);
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
};
ML_INLINE Lobes lobeWeights(const Surface& s, float3 wo) {
    const float coat = s.coat * dielectricFresnel(wo.z, s.ior);
    const float specular = luminance(specularFresnel(s, wo.z)) * underCoat(s, wo);
    const float front = luminance(diffuseColor(s, wo)), behind = s.passes ? luminance(backColor(s, wo)) : 0.0f;
    const float diffuse = front + behind;
    Lobes lobes;
    lobes.back = behind > 0.0f ? behind / diffuse : 0.0f;
    lobes.coat = coat + specular > 0.0f ? coat / (coat + specular) : 0.0f;
    lobes.specular = s.matte ? 0.0f : diffuse <= 0.0f ? 1.0f : clamp((coat + specular) / (coat + specular + diffuse), 0.1f, 0.9f);
    return lobes;
}

// bsdf * cosine of the diffuse and of the mirror-like lobes for local directions (z is the
// shading normal), and the density with which each group's own sampling would have chosen wi.
struct BsdfEval {
    float3 diffuse, specular;
    float diffusePdf, specularPdf;
};
ML_INLINE BsdfEval evalBsdf(const Surface& s, const Lobes& lobes, float3 wo, float3 wi) {
    BsdfEval e;
    e.diffuse = e.specular = vec(0.0f);
    e.diffusePdf = e.specularPdf = 0.0f;
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
    const float broad = broadShare(s);
    e.specular += multipleScattering(s, wo, wi) * underCoat(s, wo);
    e.specularPdf = e.specularPdf * (1.0f - broad) + (1.0f - lobes.coat) * broad * wi.z / ML_PI;
    if (s.coat > 0.0f) {
        const float cd = ggxD(s.coatAlpha, h.z), cg1o = smithG1(s.coatAlpha, wo.z), cg1i = smithG1(s.coatAlpha, wi.z);
        e.specular += vec(s.coat * dielectricFresnel(cosine, s.ior) * cd * cg1o * cg1i / (4.0f * wo.z));
        e.specularPdf += lobes.coat * cg1o * cd / (4.0f * wo.z);
    }
    // Diffuse light falls on the surface's own smoothed normal; only reflections use the bent one.
    e.diffuse = diffuseColor(s, wo) * (fmaxf(0.0f, dot(s.diffuseNormal, wi)) / ML_PI);
    e.diffusePdf = (1.0f - lobes.back) * wi.z / ML_PI;
    return e;
}

ML_INLINE float3 sampleDiffuse(float u1, float u2) {
    const float r = sqrtf(u1), phi = 2.0f * ML_PI * u2;
    return make_float3(r * cosf(phi), r * sinf(phi), sqrtf(fmaxf(0.0f, 1.0f - u1)));
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

// Next event estimation at one surface point: the environment, the distant lights, then the
// local lights. weight is the path's weight on arriving at the surface.
ML_INLINE float3 directLight(const Surface& surface, const Lobes& lobes, float3 wo, const Frame& frame,
                             float3 p, float3 ng, float3 weight, bool lit, unsigned& seed) {
    const DeviceDistantLight* distantLights = reinterpret_cast<const DeviceDistantLight*>(params.distantLights);
    const DeviceLight* lights = reinterpret_cast<const DeviceLight*>(params.lights);
    float3 radiance = vec(0.0f);
    // With a portal in the scene the environment is sampled through it, as one of the lights.
    if (!params.envPortal) {
        float lightPdf;
        const float3 toLight = sampleEnv(rnd(seed), rnd(seed), lightPdf);
        if (lightPdf > 0.0f && (surface.passes || dot(ng, toLight) > 0.0f)) {
            const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toLight));
            const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
            if (maxComponent(e.diffuse + e.specular) > 0.0f)
                radiance += clampSample(weight * (e.diffuse + e.specular) * envRadiance(toLight) * shadow(offsetOrigin(p, ng, toLight), toLight, seed)
                                        * (powerHeuristic(lightPdf, pdf) / lightPdf), lit);
        }
    }
    for (unsigned i = 0; i < params.distantLightCount; ++i) {
        const DeviceDistantLight& light = distantLights[i];
        const float3 toSun = sampleDistant(light, rnd(seed), rnd(seed));
        if (!surface.passes && dot(ng, toSun) <= 0.0f) continue;
        const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toSun));
        const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
        if (maxComponent(e.diffuse + e.specular) > 0.0f)
            radiance += clampSample(weight * (e.diffuse + e.specular) * distantRadiance(light, toSun) * shadow(offsetOrigin(p, ng, toSun), toSun, seed)
                                    * (powerHeuristic(distantPdf(light, toSun), pdf) / distantPdf(light, toSun)), lit);
    }
    const unsigned firstLight = params.lightPick ? pickLight(lights, params.lightCount, rnd(seed)) : 0;
    const unsigned lastLight = params.lightPick ? firstLight + 1 : params.lightCount;
    for (unsigned i = firstLight; i < lastLight; ++i) {
        float3 toLamp, emitted;
        float distance, lampPdf;
        if (!sampleLight(lights[i], p, rnd(seed), rnd(seed), toLamp, distance, lampPdf, emitted)) continue;
        if (!surface.passes && dot(ng, toLamp) <= 0.0f) continue;
        if (params.lightPick) lampPdf *= lights[i].pick;
        const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toLamp));
        const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
        if (maxComponent(e.diffuse + e.specular) > 0.0f)
            radiance += clampSample(weight * (e.diffuse + e.specular) * emitted * shadow(offsetOrigin(p, ng, toLamp), toLamp, seed, distance * 0.999f)
                                    * (powerHeuristic(lampPdf, pdf) / lampPdf), lit);
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
ML_INLINE float3 fibreLight(const Fibre& fibre, float3 p, float3 ng, float3 weight, bool lit, unsigned& seed) {
    const DeviceDistantLight* distantLights = reinterpret_cast<const DeviceDistantLight*>(params.distantLights);
    const DeviceLight* lights = reinterpret_cast<const DeviceLight*>(params.lights);
    float3 radiance = vec(0.0f);
    float pdf;
    if (!params.envPortal) {
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
// The light every lamp sends to a point in fog and on along wo, the way back to the viewer.
ML_INLINE float3 fogLight(float3 p, float3 wo, float g, float3 weight, bool lit, unsigned& seed) {
    const DeviceDistantLight* distantLights = reinterpret_cast<const DeviceDistantLight*>(params.distantLights);
    const DeviceLight* lights = reinterpret_cast<const DeviceLight*>(params.lights);
    float3 radiance = vec(0.0f);
    if (!params.envPortal) {
        float lightPdf;
        const float3 toLight = sampleEnv(rnd(seed), rnd(seed), lightPdf);
        if (lightPdf > 0.0f)
            radiance += clampSample(weight * envRadiance(toLight) * shadow(p, toLight, seed) * (phase(-dot(wo, toLight), g) / lightPdf), lit);
    }
    for (unsigned i = 0; i < params.distantLightCount; ++i) {
        const DeviceDistantLight& light = distantLights[i];
        const float3 toSun = sampleDistant(light, rnd(seed), rnd(seed));
        radiance += clampSample(weight * distantRadiance(light, toSun) * shadow(p, toSun, seed) * (phase(-dot(wo, toSun), g) / distantPdf(light, toSun)), lit);
    }
    const unsigned firstLight = params.lightPick ? pickLight(lights, params.lightCount, rnd(seed)) : 0;
    const unsigned lastLight = params.lightPick ? firstLight + 1 : params.lightCount;
    for (unsigned i = firstLight; i < lastLight; ++i) {
        float3 toLamp, emitted;
        float distance, lampPdf;
        if (!sampleLight(lights[i], p, rnd(seed), rnd(seed), toLamp, distance, lampPdf, emitted)) continue;
        if (params.lightPick) lampPdf *= lights[i].pick;
        radiance += clampSample(weight * emitted * shadow(p, toLamp, seed, distance * 0.999f) * (phase(-dot(wo, toLamp), g) / lampPdf), lit);
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

extern "C" __global__ void __raygen__moonlightipr() {
    const uint3 index = optixGetLaunchIndex();
    const unsigned pixel = index.y * params.width + index.x;
    unsigned seed = tea(pixel, params.sample);

    const float sx = 2.0f * (index.x + rnd(seed)) / params.width - 1.0f;
    const float sy = 2.0f * (index.y + rnd(seed)) / params.height - 1.0f;
    float3 origin = vec(params.cameraOrigin);
    float3 direction = normalize(vec(params.cameraU) * sx + vec(params.cameraV) * sy + vec(params.cameraW));
    bool outside = false;
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
    if (outside) {
        // Beyond the lens's field of view there is no picture.
        const float weight = 1.0f / float(params.sample + 1);
        float4* buffers[3] = {reinterpret_cast<float4*>(params.beauty) + pixel, reinterpret_cast<float4*>(params.albedo) + pixel,
                              reinterpret_cast<float4*>(params.normal) + pixel};
        for (int i = 0; i < 3; ++i) {
            const float3 kept = lerp(make_float3(buffers[i]->x, buffers[i]->y, buffers[i]->z), vec(0.0f), weight);
            *buffers[i] = make_float4(kept.x, kept.y, kept.z, i < 2 ? 1.0f : 0.0f);
        }
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
    // The fog the ray is in, as its entry among the volumes, and how many edges of fog the path has crossed.
    int medium = -1;
    unsigned crossings = 0;

    for (unsigned depth = 0;; ++depth) {
        Hit hit;
        traceRadiance(origin, direction, hit, reach);
        if (params.volumeCount && !probing) {
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
                float at = from, anisotropy = 0.0f;
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
                        albedo = albedo * (1.0f / thick);
                        anisotropy /= thick;
                        break;
                    }
                }
                if (stopped) {
                    // Light scatters in fog once: what the lamps send here goes on towards the viewer.
                    if (bounces)
                        radiance += fogLight(origin + direction * at, -direction, anisotropy, throughput * bounceWeight * albedo, roughDepth >= 1, seed);
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
                if (bounces)
                    radiance += fogLight(origin + direction * reached, -direction, fog.anisotropy,
                                         throughput * bounceWeight * stops * vec(fog.albedo) * left * (1.0f / density), roughDepth >= 1, seed);
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
            const float3 ng = found ? (dot(hit.ng, direction) > 0.0f ? -hit.ng : hit.ng) : -direction;
            const float3 ns = found ? (dot(hit.ns, ng) < 0.0f ? -hit.ns : hit.ns) : -direction;
            hit.p = found ? hit.p : origin + direction * (0.5f * reach);
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
        for (unsigned i = 0; !camera && !emerged && i < params.lightCount; ++i) {
            float pdf;
            float3 emitted;
            if (hitLight(lights[i], origin, direction, hit.valid ? hit.t : 1e30f, pdf, emitted))
                radiance += clampSample(throughput * lightWeight * emitted
                                        * (sharp ? 1.0f : powerHeuristic(bsdfPdf, params.lightPick ? pdf * lights[i].pick : pdf)), clampFound);
        }
        if (!hit.valid) {
            // Camera rays see the background, which may differ from what lights the scene;
            // later bounces share the lighting environment with light sampling.
            const float3 sky = camera ? envLookup(reinterpret_cast<const float4*>(params.envBackground), params.envBackgroundRotation, direction)
                             : params.envPortal ? vec(0.0f) : envRadiance(direction);
            radiance += clampSample(throughput * lightWeight * sky * (sharp ? 1.0f : powerHeuristic(bsdfPdf, envPdf(direction))), clampFound);
            if (camera) guideAlbedo = make_float3(fminf(sky.x, 1.0f), fminf(sky.y, 1.0f), fminf(sky.z, 1.0f));
            // Distant lights are found by scattered rays; the camera sees only the discs that ask to be seen, as a sun does.
            for (unsigned i = 0; i < params.distantLightCount; ++i) {
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
            break;
        }
        if ((hit.flags & MATERIAL_VOLUME) && !emerged) {
            // The edge of a fog: nothing is there to see. The ray goes on, into the fog through a face that looks
            // outwards and out of it through one that looks inwards.
            if (++crossings > 64) break;
            medium = dot(hit.ng, direction) < 0.0f ? int(hit.hair) : -1;
            origin = offsetOrigin(hit.p, hit.ng, direction);
            --depth;    // crossing an edge is not a bounce
            continue;
        }
        // A mesh light is the surface just hit; it emits from both faces.
        if (!camera && !emerged && hit.light >= 0) {
            const DeviceLight& light = lights[hit.light];
            const float cosine = fabsf(dot(direction, hit.ng));
            if (cosine > 1e-6f) {
                const float pdf = hit.t * hit.t / (light.area * cosine);
                radiance += clampSample(throughput * lightWeight * vec(light.radiance)
                                        * (sharp ? 1.0f : powerHeuristic(bsdfPdf, params.lightPick ? pdf * light.pick : pdf)), clampFound);
            }
        }

        Surface surface = surfaceFrom(hit);
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

        if (hit.curve && (hit.flags & MATERIAL_HAIR)) {
            // A hair fibre scatters light all round itself, so nothing here asks which side the light is on.
            const Fibre fibre = fibreFrom(hit, reinterpret_cast<const DeviceHair*>(params.hairs)[hit.hair], -direction);
            if (camera) {
                guideAlbedo = hit.albedo;
                guideNormal = make_float3(dot(hit.ns, normalize(vec(params.cameraU))), dot(hit.ns, normalize(vec(params.cameraV))),
                                          -dot(hit.ns, normalize(vec(params.cameraW))));
            }
            radiance += fibreLight(fibre, hit.p, hit.ng, throughput, roughDepth >= 1, seed);
            float3 wi;
            if (depth >= params.maxDepth || !fibreSample(fibre, seed, wi)) break;
            const float3 f = fibreEval(fibre, wi, bsdfPdf);
            if (bsdfPdf <= 0.0f || maxComponent(f) <= 0.0f) break;
            direction = wi;
            lightWeight = bounceWeight = f * (1.0f / bsdfPdf);
            bounces = true;
            sharp = false;
            clampFound = roughDepth >= 1;
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
            if (mirrored || !refractThrough(wo, h, ior, 1.0f, wi)) wi = reflectAbout(wo, h);
            direction = frame.toWorld(wi);
            lightWeight = bounceWeight = tint;
            sharp = true;
            clampFound = roughDepth >= 1;
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
        const bool scatters = !inside && hit.subsurface > 0.0f && maxComponent(hit.subsurfaceRadius) > 0.0f
                              && lobes.specular < 1.0f && rnd(seed) < hit.subsurface;
        const float beneath = scatters ? 1.0f - lobes.specular : 0.0f;
        if (scatters) {
            surface.diffuseScale = 0.0f;
            lobes = lobeWeights(surface, wo);
        } else if (diffuseBounces != glossyBounces && !surface.matte) {
            // Sample only what may bounce on; with nothing left, the ray still looks for lights.
            lobes.specular = glossyBounces ? 1.0f : 0.0f;
        }
        const bool lit = roughDepth >= 1;   // this surface was reached by scattering off something rough
        radiance += directLight(surface, lobes, wo, frame, hit.p, ng, throughput, lit, seed);

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
            // Chosen in proportion to its share of the light, so only the tint remains.
            lightWeight = bounceWeight = surface.transmissionColor * tint;
            sharp = true;
            clampFound = roughDepth >= 1;
            bounces = true;
            origin = offsetOrigin(hit.p, ng, direction);
            continue;
        }

        if (scatters && rnd(seed) < beneath) {
            // Pick a colour channel by its albedo and a distance from that channel's profile; the
            // other channels are weighted by how likely they were to give the same distance.
            const float3 albedo = make_float3(fmaxf(surface.albedo.x, 0.001f), fmaxf(surface.albedo.y, 0.001f),
                                              fmaxf(surface.albedo.z, 0.001f));
            const float3 width = make_float3(profileWidth(albedo.x, hit.subsurfaceRadius.x), profileWidth(albedo.y, hit.subsurfaceRadius.y),
                                             profileWidth(albedo.z, hit.subsurfaceRadius.z));
            const float total = albedo.x + albedo.y + albedo.z, pick = rnd(seed) * total;
            const float chosen = pick < albedo.x ? width.x : pick < albedo.x + albedo.y ? width.y : width.z;
            const float r = (rnd(seed) < 0.25f ? chosen : 3.0f * chosen) * -logf(fmaxf(1e-6f, 1.0f - rnd(seed)));
            const float3 shape = make_float3(profileShape(r, width.x), profileShape(r, width.y), profileShape(r, width.z));
            const float mixture = (albedo.x * shape.x + albedo.y * shape.y + albedo.z * shape.z) / total;
            // What comes out is diffuse light, already dimmed by what the surface reflected.
            throughput *= surface.albedo * surface.frontKeep * (entering(surface, wo) * (1.0f - surface.transmission) / ((1.0f - through) * beneath))
                        * (mixture > 0.0f ? shape * (1.0f / mixture) : vec(1.0f));
            // Look down onto the surface from that far to one side.
            const float phi = 2.0f * ML_PI * rnd(seed);
            entryInstance = hit.instance;
            origin = hit.p + (frame.t * cosf(phi) + frame.b * sinf(phi)) * r + ns * r;
            direction = -ns;
            reach = 2.0f * r;
            probing = true;
            --depth;    // coming out again is not a bounce
            continue;
        }

        const bool glossy = rnd(seed) < lobes.specular;
        float3 wi;
        if (!glossy) {
            wi = sampleDiffuse(u1, u2);
            if (lobes.back > 0.0f && rnd(seed) < lobes.back) wi.z = -wi.z;
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
        clampFound = roughDepth >= 1;
        ++roughDepth;
        if (glossy) ++glossyDepth; else ++diffuseDepth;
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
    for (unsigned c = CHANNEL_DRIVER; c < CHANNEL_COUNT; ++c) channel[c] = vec(0.0f);
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
// camera, bounce and shadow rays alike.
ML_INLINE void absent(const DeviceMaterial& material, const DeviceMesh& mesh, unsigned primitive, float2 barycentrics) {
    if (!(material.flags & MATERIAL_HAS_PRESENCE)) return;
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
        // looking for what is there to see takes the edge as its hit, to know it is in fog from there.
        if (!(optixGetRayFlags() & OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT)) return;
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
        // Scalars take the mean of a colour, as MoonRay does for a map bound to a float attribute.
        hit->albedo = channel[CHANNEL_COLOR] * channel[CHANNEL_COLOR_AMOUNT];
        hit->emission = channel[CHANNEL_EMISSION] * channel[CHANNEL_EMISSION_AMOUNT];
        hit->roughness = clamp(average(channel[CHANNEL_ROUGHNESS]), 0.0f, 1.0f);
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
