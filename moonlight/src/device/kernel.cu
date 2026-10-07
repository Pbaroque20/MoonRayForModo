// MoonLightIPR device programs: a progressive megakernel path tracer.
// One launch adds one sample per pixel to the running means in LaunchParams.
#include <optix.h>
#include "shared.h"
#include "vec.h"

using namespace moonlight;

extern "C" { __constant__ LaunchParams params; }

// What a radiance ray found: the geometry, and the material resolved at that point.
struct Hit {
    float3 p, ng, ns;
    float3 albedo, emission, transmissionColor;
    float roughness, metallic, ior, underRoughness;
    float transmission, transmissionRoughness, transmissionIor, coat, coatRoughness;
    float t;
    unsigned flags;
    int valid;
};

ML_INLINE Hit* hitPayload() {
    return reinterpret_cast<Hit*>((static_cast<unsigned long long>(optixGetPayload_0()) << 32) | optixGetPayload_1());
}

ML_INLINE void traceRadiance(float3 origin, float3 direction, Hit& hit) {
    const unsigned long long address = reinterpret_cast<unsigned long long>(&hit);
    unsigned p0 = unsigned(address >> 32), p1 = unsigned(address);
    hit.valid = 0;
    optixTrace(params.traversable, origin, direction, 0.0f, 1e16f, 0.0f, OptixVisibilityMask(255),
               params.presence ? OPTIX_RAY_FLAG_NONE : OPTIX_RAY_FLAG_DISABLE_ANYHIT, 0, 1, 0, p0, p1);
}

// The second payload word gives the any-hit test of a partly absent surface its own random stream.
ML_INLINE bool visible(float3 origin, float3 direction, unsigned& seed, float distance = 1e16f) {
    unsigned unoccluded = 0, stream = seed;
    rnd(seed);
    optixTrace(params.traversable, origin, direction, 0.0f, distance, 0.0f, OptixVisibilityMask(255),
               (params.presence ? OPTIX_RAY_FLAG_NONE : OPTIX_RAY_FLAG_DISABLE_ANYHIT)
               | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT | OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT,
               0, 1, 1, unoccluded, stream);
    return unoccluded != 0;
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

// ---- Distant lights ----------------------------------------------------------------------------

ML_INLINE float distantPdf(const DeviceDistantLight& light) {
    return 1.0f / (2.0f * ML_PI * light.versine);
}

// Uniform over the cap. The versine form stays accurate for the small angles a sun uses.
ML_INLINE float3 sampleDistant(const DeviceDistantLight& light, float u1, float u2) {
    const float versine = u1 * light.versine, phi = 2.0f * ML_PI * u2;
    const float sinTheta = sqrtf(versine * (2.0f - versine));
    return Frame(vec(light.direction)).toWorld(make_float3(sinTheta * cosf(phi), sinTheta * sinf(phi), 1.0f - versine));
}

// ---- Sphere, rectangle, disc and spot lights ---------------------------------------------------
// They light the scene and appear in reflections, but neither block rays nor show to the camera.

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
ML_INLINE bool sampleLight(const DeviceLight& light, float3 p, float u1, float u2,
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
    float3 onLight;
    if (light.type == LIGHT_RECT) {
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
    pdf = distance * distance / (light.area * cosine);
    if (light.type == LIGHT_SPOT) radiance = radiance * spotFalloff(light, p, onLight);
    return true;
}

// For a scattered ray: does it reach the light before maxDistance, and with what sampling density?
ML_INLINE bool hitLight(const DeviceLight& light, float3 p, float3 direction, float maxDistance,
                        float& pdf, float3& radiance) {
    const float3 centre = vec(light.position);
    radiance = vec(light.radiance);
    if (light.type == LIGHT_SPHERE) {
        const float3 toCentre = centre - p;
        const float distanceSquared = dot(toCentre, toCentre), radiusSquared = light.radius * light.radius;
        const float along = dot(toCentre, direction);
        if (distanceSquared <= radiusSquared || along <= 0.0f) return false;
        const float discriminant = radiusSquared - (distanceSquared - along * along);
        if (discriminant < 0.0f || along - sqrtf(discriminant) >= maxDistance) return false;
        pdf = 1.0f / (2.0f * ML_PI * sphereVersine(radiusSquared, distanceSquared));
        return true;
    }
    const float3 n = vec(light.normal);
    const float cosine = -dot(direction, n), height = dot(p - centre, n);
    if (cosine <= 1e-6f || height <= 0.0f) return false;
    const float distance = height / cosine;
    if (distance >= maxDistance) return false;
    const float3 onLight = p + direction * distance, offset = onLight - centre;
    if (light.type == LIGHT_RECT) {
        const float3 u = vec(light.u), v = vec(light.v);
        if (fabsf(dot(offset, u)) > dot(u, u) || fabsf(dot(offset, v)) > dot(v, v)) return false;
    } else if (dot(offset, offset) > light.radius * light.radius) return false;
    pdf = distance * distance / (light.area * cosine);
    if (light.type == LIGHT_SPOT) radiance = radiance * spotFalloff(light, p, onLight);
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
    float roughness;
};

ML_INLINE Surface surfaceFrom(const Hit& hit) {
    Surface s;
    s.albedo = hit.albedo;
    s.transmissionColor = hit.transmissionColor;
    s.metallic = hit.metallic;
    s.ior = fmaxf(hit.ior, 1.0001f);
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
    s.roughness = sqrtf(s.alpha);
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
// A conductor of the base colour weighted by metallic, over a dielectric.
ML_INLINE float3 specularFresnel(const Surface& s, float cosine) {
    return lerp(vec(dielectricFresnel(cosine, s.ior)), schlick(s.albedo, cosine), s.metallic);
}
// What reaches the lobes under the coat.
ML_INLINE float underCoat(const Surface& s, float3 wo) {
    return s.coatDims ? 1.0f - s.coat * dielectricFresnel(wo.z, s.ior) : 1.0f;
}
// What the dielectric lets through to whatever is beneath it. MoonRay evaluates this on the
// view direction and blends towards normal incidence as the lobe above gets rougher.
ML_INLINE float entering(const Surface& s, float3 wo) {
    const float grazing = 1.0f - dielectricFresnel(wo.z, s.ior), facing = 1.0f - dielectricFresnel(1.0f, s.ior);
    return (1.0f - s.metallic) * (grazing + (facing - grazing) * s.underBlend) * underCoat(s, wo);
}
ML_INLINE float3 diffuseColor(const Surface& s, float3 wo) {
    return s.albedo * (entering(s, wo) * (1.0f - s.transmission));
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
ML_INLINE float beckmannD(float alpha, float nh) {
    const float a2 = alpha * alpha, c2 = nh * nh;
    return c2 > 0.0f ? expf((c2 - 1.0f) / (c2 * a2)) / (ML_PI * a2 * c2 * c2) : 0.0f;
}
ML_INLINE float beckmannG1(float alpha, float nv) {
    const float a = nv / (alpha * sqrtf(fmaxf(1e-12f, 1.0f - nv * nv)));
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
    const float3 f0 = lerp(vec(r * r), s.albedo, s.metallic);
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
};
ML_INLINE Lobes lobeWeights(const Surface& s, float3 wo) {
    const float coat = s.coat * dielectricFresnel(wo.z, s.ior);
    const float specular = luminance(specularFresnel(s, wo.z)) * underCoat(s, wo);
    const float diffuse = luminance(diffuseColor(s, wo));
    Lobes lobes;
    lobes.coat = coat + specular > 0.0f ? coat / (coat + specular) : 0.0f;
    lobes.specular = diffuse <= 0.0f ? 1.0f : clamp((coat + specular) / (coat + specular + diffuse), 0.1f, 0.9f);
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
    if (wo.z <= 0.0f || wi.z <= 0.0f) return e;
    const float3 h = normalize(wo + wi);
    const float cosine = dot(wo, h);
    if (s.beckmann) {
        // Sampled from the distribution of facets itself, so its density follows the half vector.
        const float d = beckmannD(s.alpha, h.z);
        e.specular = specularFresnel(s, cosine) * (underCoat(s, wo) * d * beckmannG1(s.alpha, wo.z) * beckmannG1(s.alpha, wi.z) / (4.0f * wo.z));
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
    e.diffuse = diffuseColor(s, wo) * (wi.z / ML_PI);
    e.diffusePdf = wi.z / ML_PI;
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
// A facet drawn from the Beckmann distribution.
ML_INLINE float3 sampleBeckmann(float alpha, float u1, float u2) {
    const float tanSquared = -alpha * alpha * logf(fmaxf(1e-12f, 1.0f - u1)), phi = 2.0f * ML_PI * u2;
    const float cosTheta = 1.0f / sqrtf(1.0f + tanSquared), sinTheta = cosTheta * sqrtf(tanSquared);
    return make_float3(sinTheta * cosf(phi), sinTheta * sinf(phi), cosTheta);
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

extern "C" __global__ void __raygen__moonlight() {
    const uint3 index = optixGetLaunchIndex();
    const unsigned pixel = index.y * params.width + index.x;
    unsigned seed = tea(pixel, params.sample);

    const float sx = 2.0f * (index.x + rnd(seed)) / params.width - 1.0f;
    const float sy = 2.0f * (index.y + rnd(seed)) / params.height - 1.0f;
    float3 origin = vec(params.cameraOrigin);
    float3 direction = normalize(vec(params.cameraU) * sx + vec(params.cameraV) * sy + vec(params.cameraW));

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

    for (unsigned depth = 0;; ++depth) {
        Hit hit;
        traceRadiance(origin, direction, hit);
        const bool camera = depth == 0;
        for (unsigned i = 0; !camera && i < params.lightCount; ++i) {
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
                                      : envRadiance(direction);
            radiance += clampSample(throughput * lightWeight * sky * (sharp ? 1.0f : powerHeuristic(bsdfPdf, envPdf(direction))), clampFound);
            if (camera) guideAlbedo = make_float3(fminf(sky.x, 1.0f), fminf(sky.y, 1.0f), fminf(sky.z, 1.0f));
            // Distant lights are found by scattered rays only; the camera does not see their discs.
            for (unsigned i = 0; !camera && i < params.distantLightCount; ++i) {
                const DeviceDistantLight& light = distantLights[i];
                if (dot(direction, vec(light.direction)) >= 1.0f - light.versine)
                    radiance += clampSample(throughput * lightWeight * vec(light.radiance)
                                            * (sharp ? 1.0f : powerHeuristic(bsdfPdf, distantPdf(light))), clampFound);
            }
            break;
        }

        const Surface surface = surfaceFrom(hit);
        radiance += clampSample(throughput * lightWeight * hit.emission, clampFound);
        if (!bounces) break;
        throughput *= bounceWeight;

        // Russian roulette, once the path has had a chance to gather the main bounces.
        if (depth >= 3) {
            const float survive = clamp(maxComponent(throughput), 0.05f, 0.95f);
            if (rnd(seed) >= survive) break;
            throughput *= vec(1.0f / survive);
        }

        // Shade the side the ray arrived on, and keep the shading normal on that side.
        const float3 toViewer = -direction;
        const bool inside = dot(hit.ng, toViewer) < 0.0f;
        const float3 ng = inside ? -hit.ng : hit.ng;
        float3 ns = dot(hit.ns, ng) < 0.0f ? -hit.ns : hit.ns;
        if (dot(ns, toViewer) <= 0.0f) ns = ng;
        const Frame frame(ns);
        const float3 wo = frame.toLocal(toViewer);

        if (camera) {
            guideAlbedo = lerp(surface.albedo, vec(1.0f), surface.transmission * (1.0f - surface.metallic));
            guideNormal = make_float3(dot(ns, normalize(vec(params.cameraU))), dot(ns, normalize(vec(params.cameraV))),
                                      -dot(ns, normalize(vec(params.cameraW))));
        }
        const bool mayBounce = depth < params.maxDepth;

        if (inside && surface.transmission > 0.0f && !surface.thin) {
            // Leaving a solid the light entered: a plain interface, mirrored back or bent out.
            if (!mayBounce) break;
            const float3 h = surface.transmissionAlpha > 0.0f ? sampleFacet(surface.transmissionAlpha, wo, rnd(seed), rnd(seed))
                                                              : make_float3(0.0f, 0.0f, 1.0f);
            float3 wi;
            const float reflected = fresnel(dot(wo, h), surface.transmissionIor, 1.0f);
            if (rnd(seed) < reflected || !refractThrough(wo, h, surface.transmissionIor, 1.0f, wi)) wi = reflectAbout(wo, h);
            direction = frame.toWorld(wi);
            lightWeight = bounceWeight = vec(1.0f);
            sharp = true;
            clampFound = roughDepth >= 1;
            origin = offsetOrigin(hit.p, ng, direction);
            continue;
        }

        // Which lobes may send the path on. MoonRay counts diffuse and glossy bounces apart.
        const bool diffuseBounces = mayBounce && diffuseDepth < params.maxDiffuseDepth;
        const bool glossyBounces = mayBounce && glossyDepth < params.maxGlossyDepth;
        // Sample only what may bounce on; with nothing left, the ray still looks for lights.
        Lobes lobes = lobeWeights(surface, wo);
        if (diffuseBounces != glossyBounces) lobes.specular = glossyBounces ? 1.0f : 0.0f;
        const bool lit = roughDepth >= 1;   // this surface was reached by scattering off something rough

        // Next event estimation: the environment, then every light.
        float lightPdf;
        const float3 toLight = sampleEnv(rnd(seed), rnd(seed), lightPdf);
        if (lightPdf > 0.0f && dot(ng, toLight) > 0.0f) {
            const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toLight));
            const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
            if (maxComponent(e.diffuse + e.specular) > 0.0f && visible(offsetOrigin(hit.p, ng, toLight), toLight, seed))
                radiance += clampSample(throughput * (e.diffuse + e.specular) * envRadiance(toLight)
                                        * (powerHeuristic(lightPdf, pdf) / lightPdf), lit);
        }
        for (unsigned i = 0; i < params.distantLightCount; ++i) {
            const DeviceDistantLight& light = distantLights[i];
            const float3 toSun = sampleDistant(light, rnd(seed), rnd(seed));
            if (dot(ng, toSun) <= 0.0f) continue;
            const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toSun));
            const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
            if (maxComponent(e.diffuse + e.specular) > 0.0f && visible(offsetOrigin(hit.p, ng, toSun), toSun, seed))
                radiance += clampSample(throughput * (e.diffuse + e.specular) * vec(light.radiance)
                                        * (powerHeuristic(distantPdf(light), pdf) / distantPdf(light)), lit);
        }
        const unsigned firstLight = params.lightPick ? pickLight(lights, params.lightCount, rnd(seed)) : 0;
        const unsigned lastLight = params.lightPick ? firstLight + 1 : params.lightCount;
        for (unsigned i = firstLight; i < lastLight; ++i) {
            float3 toLamp, emitted;
            float distance, lampPdf;
            if (!sampleLight(lights[i], hit.p, rnd(seed), rnd(seed), toLamp, distance, lampPdf, emitted)) continue;
            if (dot(ng, toLamp) <= 0.0f) continue;
            if (params.lightPick) lampPdf *= lights[i].pick;
            const BsdfEval e = evalBsdf(surface, lobes, wo, frame.toLocal(toLamp));
            const float pdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
            if (maxComponent(e.diffuse + e.specular) > 0.0f && visible(offsetOrigin(hit.p, ng, toLamp), toLamp, seed, distance * 0.999f))
                radiance += clampSample(throughput * (e.diffuse + e.specular) * emitted
                                        * (powerHeuristic(lampPdf, pdf) / lampPdf), lit);
        }

        // The light that enters a transmissive surface goes through it rather than scattering.
        const float through = mayBounce ? transmitted(surface, wo) : 0.0f;
        const float u1 = rnd(seed), u2 = rnd(seed);
        if (rnd(seed) < through) {
            float3 wi = -wo;    // thin sheets and missing facets pass the light straight on
            if (!surface.thin) {
                const float3 h = surface.transmissionAlpha > 0.0f ? sampleFacet(surface.transmissionAlpha, wo, u1, u2)
                                                                  : make_float3(0.0f, 0.0f, 1.0f);
                if (!refractThrough(wo, h, 1.0f, surface.transmissionIor, wi)) wi = reflectAbout(wo, h);
            }
            direction = frame.toWorld(wi);
            // Chosen in proportion to its share of the light, so only the tint remains.
            lightWeight = bounceWeight = surface.transmissionColor;
            sharp = true;
            clampFound = roughDepth >= 1;
            bounces = true;
            origin = offsetOrigin(hit.p, ng, direction);
            continue;
        }

        const bool glossy = rnd(seed) < lobes.specular;
        float3 wi;
        if (!glossy) wi = sampleDiffuse(u1, u2);
        else if (rnd(seed) < lobes.coat) wi = reflectAbout(wo, sampleFacet(surface.coatAlpha, wo, u1, u2));
        else if (rnd(seed) < broadShare(surface)) wi = sampleDiffuse(u1, u2);
        else wi = reflectAbout(wo, surface.beckmann ? sampleBeckmann(surface.alpha, u1, u2) : sampleFacet(surface.alpha, wo, u1, u2));
        const BsdfEval e = evalBsdf(surface, lobes, wo, wi);
        bsdfPdf = lobes.specular * e.specularPdf + (1.0f - lobes.specular) * e.diffusePdf;
        direction = frame.toWorld(wi);
        if (bsdfPdf <= 0.0f || dot(ng, direction) <= 0.0f) break;
        // The reflective lobes were reached by not taking the transmission branch.
        const float scale = 1.0f / (bsdfPdf * (1.0f - through));
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
    const float3 mixed = make_float3(blendValue(below.x, value.x, mode), blendValue(below.y, value.y, mode),
                                     blendValue(below.z, value.z, mode));
    return lerp(below, mixed, clamp(alpha, 0.0f, 1.0f));
}
ML_INLINE float average(float3 c) { return (c.x + c.y + c.z) * (1.0f / 3.0f); }

struct Corners {
    float2 a, b, c;
};

// The three texture coordinates of a triangle in one scene-wide slot; false if the mesh has none.
ML_INLINE bool triangleUvs(const DeviceMesh& mesh, unsigned slot, unsigned primitive, Corners& uv) {
    if (!mesh.uvs || slot >= UV_SLOTS || mesh.uvSet[slot] < 0) return false;
    const float2* values = reinterpret_cast<const float2*>(mesh.uvs) + ((unsigned long long)(mesh.uvSet[slot]) * mesh.triangleCount + primitive) * 3;
    uv.a = values[0];
    uv.b = values[1];
    uv.c = values[2];
    return true;
}

// Which coordinate slots the last normal map and the last bump image used; UV_SLOTS for none.
struct MappedSlots {
    unsigned normal, bump;
};

// Runs a material's layer stack at a point, bottom row first, as the plugin's texture graph does:
// rows blend over the rows beneath them, a group blends what its rows produced over what was
// there before it, and a mask row scales how strongly its target is applied. shift moves every
// image lookup, which is how a bump map's slope is measured.
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
    MappedSlots slots;
    slots.normal = slots.bump = UV_SLOTS;

    float3 saved[GROUP_DEPTH][CHANNEL_COUNT];
    unsigned savedUsed[GROUP_DEPTH];
    unsigned level = 0, used = 0;
    float masks[MASK_REGISTERS] = {1.0f, 1.0f, 1.0f, 1.0f};
    const unsigned colours = (1u << CHANNEL_COLOR) | (1u << CHANNEL_EMISSION) | (1u << CHANNEL_TRANSMISSION_COLOR);

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
        if (layer.flags & LAYER_IMAGE) {
            Corners uv;
            if (!triangleUvs(mesh, layer.uvSlot, primitive, uv)) continue;     // nothing to look the image up with
            const float w = 1.0f - barycentrics.x - barycentrics.y;
            const float u = uv.a.x * w + uv.b.x * barycentrics.x + uv.c.x * barycentrics.y + shift.x;
            const float v = uv.a.y * w + uv.b.y * barycentrics.x + uv.c.y * barycentrics.y + shift.y;
            // Images are stored top row first; texture v runs upwards.
            const float4 texel = tex2D<float4>(layer.texture, u, 1.0f - v);
            value = (layer.flags & LAYER_ALPHA_ONLY) ? vec(texel.w) : make_float3(texel.x, texel.y, texel.z);
            if (layer.flags & LAYER_ALPHA_MASK) mask *= texel.w;
            if (((layer.flags & LAYER_COVERAGE_U) && (u < 0.0f || u > 1.0f)) || ((layer.flags & LAYER_COVERAGE_V) && (v < 0.0f || v > 1.0f)))
                mask = 0.0f;
            if (layer.channel == CHANNEL_NORMAL) slots.normal = layer.uvSlot;
            if (layer.channel == CHANNEL_BUMP) slots.bump = layer.uvSlot;
        }
        if (layer.flags & LAYER_FLIP_RED) value.x = 1.0f - value.x;
        if (layer.flags & LAYER_FLIP_GREEN) value.y = 1.0f - value.y;
        if (layer.flags & LAYER_FLIP_BLUE) value.z = 1.0f - value.z;
        const unsigned pick = (layer.flags >> LAYER_PICK_SHIFT) & 3;
        if (pick) value = vec(pick == 1 ? value.x : pick == 2 ? value.y : value.z);
        value = value * layer.gain + vec(layer.offset);
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
extern "C" __global__ void __anyhit__presence() {
    const DeviceInstance& instance = reinterpret_cast<const DeviceInstance*>(params.instances)[optixGetInstanceId()];
    const DeviceMesh& mesh = reinterpret_cast<const DeviceMesh*>(params.meshes)[instance.mesh];
    const unsigned primitive = optixGetPrimitiveIndex();
    const unsigned materialIndex = mesh.materialIds ? reinterpret_cast<const unsigned*>(mesh.materialIds)[primitive] : instance.material;
    const DeviceMaterial& material = reinterpret_cast<const DeviceMaterial*>(params.materials)[materialIndex];
    if (!(material.flags & MATERIAL_HAS_PRESENCE)) return;
    float3 channel[CHANNEL_COUNT];
    evalLayers(material, mesh, primitive, optixGetTriangleBarycentrics(), channel, make_float2(0.0f, 0.0f));
    // The payload differs from ray to ray and the sample index from pass to pass.
    unsigned state = tea(optixGetPayload_1() ^ (primitive * 0x9e3779b9u) ^ (optixGetInstanceId() * 0x85ebca6bu),
                         optixGetPayload_0() ^ params.sample);
    if (rnd(state) < clamp(average(channel[CHANNEL_DISSOLVE]), 0.0f, 1.0f)) optixIgnoreIntersection();
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
    hit->valid = 1;

    const unsigned materialIndex = mesh.materialIds ? reinterpret_cast<const unsigned*>(mesh.materialIds)[primitive] : instance.material;
    const DeviceMaterial& material = reinterpret_cast<const DeviceMaterial*>(params.materials)[materialIndex];
    float3 channel[CHANNEL_COUNT];
    const MappedSlots slots = evalLayers(material, mesh, primitive, uv, channel, make_float2(0.0f, 0.0f));
    // Scalars take the mean of a colour, as MoonRay does for a map bound to a float attribute.
    hit->albedo = channel[CHANNEL_COLOR] * channel[CHANNEL_COLOR_AMOUNT];
    hit->emission = channel[CHANNEL_EMISSION] * channel[CHANNEL_EMISSION_AMOUNT];
    hit->roughness = clamp(average(channel[CHANNEL_ROUGHNESS]), 0.0f, 1.0f);
    hit->metallic = clamp(average(channel[CHANNEL_METALLIC]), 0.0f, 1.0f);
    hit->ior = material.ior;
    hit->transmission = clamp(average(channel[CHANNEL_TRANSMISSION]), 0.0f, 1.0f);
    hit->transmissionColor = channel[CHANNEL_TRANSMISSION_COLOR];
    hit->transmissionRoughness = clamp(average(channel[CHANNEL_TRANSMISSION_ROUGHNESS]), 0.0f, 1.0f);
    hit->transmissionIor = material.transmissionIor;
    hit->coat = clamp(average(channel[CHANNEL_COAT]), 0.0f, 1.0f);
    hit->coatRoughness = clamp(average(channel[CHANNEL_COAT_ROUGHNESS]), 0.0f, 1.0f);
    hit->flags = material.flags;
    hit->underRoughness = material.underRoughness < 0.0f ? hit->roughness : material.underRoughness;

    // Normal and bump maps tilt the shading normal in the frame the plugin's ModoTextureMap and
    // ModoNormalMap use: the direction texture u runs across the surface, the normal, and their
    // cross product.
    const bool bumped = (material.flags & MATERIAL_HAS_BUMP) && slots.bump < UV_SLOTS;
    const unsigned slot = bumped ? slots.bump : slots.normal;
    Corners corners;
    if (slot >= UV_SLOTS || !triangleUvs(mesh, slot, primitive, corners)) return;
    const float2 d1 = make_float2(corners.b.x - corners.a.x, corners.b.y - corners.a.y);
    const float2 d2 = make_float2(corners.c.x - corners.a.x, corners.c.y - corners.a.y);
    const float determinant = d1.x * d2.y - d1.y * d2.x;
    if (fabsf(determinant) <= 1e-20f) return;
    const float3 e1 = optixTransformVectorFromObjectToWorldSpace(p1 - p0), e2 = optixTransformVectorFromObjectToWorldSpace(p2 - p0);
    const float3 alongU = (e1 * d2.y - e2 * d1.y) * (1.0f / determinant);
    const float3 alongV = (e2 * d1.x - e1 * d2.x) * (1.0f / determinant);
    const float3 n = hit->ns;
    const float3 tangent = alongU - n * dot(alongU, n);
    const float lengthT = length(tangent);
    if (lengthT <= 1e-9f) return;
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
