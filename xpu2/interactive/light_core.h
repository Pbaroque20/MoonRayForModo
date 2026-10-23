// MoonRay's lights for the asynchronous renderer, shared by the CPU and CUDA
// lanes: each light samples a direction toward itself, evaluates its radiance
// and solid-angle pdf, and intersects the rays BSDF samples cast.
//
// Adapted from MoonRay pbr/light (Light.h, LightUtil.h, EnvLight.cc,
// RectLight.cc, DiskLight.cc, SphereLight.cc, DistantLight.cc, SpotLight.cc), pbr/core/Util.h
// and shading/Util.h, Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC;
// see MOONRAY_LICENSE.txt. Without motion blur, image maps, spread, light filters
// or clear radius: scenes with those render by fallback. Render space is world
// space, as in the rest of the prototype; a light's local frame is its node
// transform turned about X by 180 degrees, so it shines down its local -Z.
#pragma once
#include "surface_core.h"

namespace xpu2::interactive::lights {
using surface::V3;
using sample::U32;

enum Type : U32 { Env = 0, Rect = 1, Disk = 2, Sphere = 3, Distant = 4, Spot = 5 };
enum Sidedness : U32 { Regular = 0, Reverse = 1, TwoSided = 2 };

constexpr float Epsilon = 1.1920928955078125e-07f;  // scene_rdl2 sEpsilon (float epsilon)
constexpr float InfiniteDistance = 3.4028234663852886e+38f - 1e32f;
constexpr float EnvDistance = InfiniteDistance * 0.9f;
constexpr float DistantDistance = InfiniteDistance * 0.8f;
constexpr float HitEpsilonEnd = 1.0f - 1e-3f;  // shadow rays stop this far short of the light
constexpr float Pi = 3.14159265358979323846f, TwoPi = 6.28318530717958647692f;
constexpr float OneOverTwoPi = 0.15915494309189533577f, OneOverFourPi = 0.07957747154594766788f;

// One light, in render space. Linear parts are stored as rows, as MoonRay's
// row-vector transforms are: a local vector v maps to v.x row0 + v.y row1 + v.z row2.
struct Light {
    U32 type, sidedness, pad0, pad1;
    V3 radiance;
    V3 position, direction;  // local origin; local +Z, unit (MoonRay getPosition, getDirection)
    V3 local2Render[3];      // with scale
    V3 render2Local[3];      // its inverse
    V3 render2LocalRot[3];   // rotation only
    float scale;             // local to render length scale
    float invArea;
    float planeOffset;       // -dot(direction, position): the light's plane
    float halfWidth, halfHeight;            // rect, local units
    float radius, radiusSq, rcpRadius;      // sphere, render units
    float cosThetaMax, versineThetaMax;     // distant
    // spot: its lens and focal plane, local units, and its falloff between the cones
    float lensRadius, lensRadiusY, rcpLensRadius, rcpLensRadiusY;
    float focalDistance, focalRadius, focalRadiusY, rcpFocalRadius, rcpFocalRadiusY;
    float falloffGradient, crossOverDistance, focalPlanePdfConst;
    U32 falloffType;
};

// Where a light sample or a BSDF ray meets the light (LightIntersection).
struct Hit {
    V3 N;            // the light's normal facing the shading point
    float distance;
    float data0, data1;  // sphere: cos(theta) over sin^2(theta max), and the distance used for its pdf; spot: uv
};

X2_HD inline V3 rows(const V3 m[3], V3 v) {
    return surface::add(surface::add(surface::mul(m[0], v.x), surface::mul(m[1], v.y)), surface::mul(m[2], v.z));
}
X2_HD inline V3 sub(V3 a, V3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
X2_HD inline float lengthSq(V3 a) { return surface::dot(a, a); }
X2_HD inline float powerHeuristic(float f, float g) { return (f * f) / (f * f + g * g); }

// A solid-angle pdf from an area pdf: distance squared over the cosine at the
// light, 0 when that cosine is about 0 (areaToSolidAngleScale).
X2_HD inline float areaToSolidAngleScale(V3 wi, V3 lightNormal, float dist) {
    const float denom = -surface::dot(wi, lightNormal);
    return denom < 0.00001f ? 0.0f : (dist * dist) / denom;
}

// A unit vector at polar angle theta (as its cosine) and azimuth phi, about +Z.
X2_HD inline V3 polar(float cosTheta, float sinTheta, float phi) {
    float s, c;
    surface::sincosSample(phi, s, c);
    return {sinTheta * c, sinTheta * s, cosTheta};
}

// The spot light's lens and focal-plane coordinates (SpotLight.cc).
X2_HD inline void lensToFocal(const Light& l, float lx, float ly, V3 localP, float& fx, float& fy) {
    const float f = l.focalDistance;
    float z = localP.z;
    if (z == 0.0f) z = 1.0e-20f;
    fx = ((z - f) * lx + f * localP.x) / z;
    fy = ((z - f) * ly + f * localP.y) / z;
}
X2_HD inline void focalToLens(const Light& l, float fx, float fy, V3 localP, float& lx, float& ly) {
    const float f = l.focalDistance, z = localP.z;
    float denom = z - f;
    if (denom == 0.0f) denom = 1.0e-20f;
    lx = (z * fx - f * localP.x) / denom;
    ly = (z * fy - f * localP.y) / denom;
}
// MoonRay's FalloffCurve.
X2_HD inline float falloff(U32 type, float t) {
    t = fminf(fmaxf(t, 0.0f), 1.0f);
    switch (type) {
    case 0: return t > 0.0f ? 1.0f : 0.0f;
    case 2: return t * t;
    case 3: return t * (2.0f - t);
    case 4: return t * t * (3.0f - 2.0f * t);
    default: return t;
    }
}

X2_HD inline float planeDistance(const Light& l, V3 p) {
    float d = surface::dot(l.direction, p) + l.planeOffset;
    if (l.sidedness == Reverse) d = -d;
    else if (l.sidedness == TwoSided) d = fabsf(d);
    return d;
}
X2_HD inline bool rejectPosDirSidedness(const Light& l, float pz, float wz) {
    if ((pz < 0.0f) == (wz < 0.0f)) return true;
    return pz < 0.0f ? l.sidedness == Regular : l.sidedness == Reverse;
}

// Draws a direction toward the light from p, given the surface's culling normal
// n (null for a BSDF with transmission) and three uniform numbers. False when
// the light cannot be sampled from there (Light::sample).
X2_HD inline bool sample(const Light& l, V3 p, const V3* n, const float r[3], V3& wi, Hit& h) {
    using namespace surface;
    switch (l.type) {
    case Env: {
        const float cosTheta = 1.0f - 2.0f * r[0];
        wi = polar(cosTheta, sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta)), r[1] * TwoPi);
        if (n && dot(*n, wi) < Epsilon) return false;
        h.N = mul(wi, -1);
        h.distance = EnvDistance;
        return true;
    }
    case Distant: {
        const float versine = fmaxf(r[0] * l.versineThetaMax, 0.0f);
        const float cosTheta = 1.0f - versine;
        const V3 cap = polar(cosTheta, sqrtf(fmaxf(0.0f, versine * (2.0f - versine))), r[1] * TwoPi);
        wi = rows(l.local2Render, mul(cap, -1));  // an orthonormal frame here
        if (n && dot(*n, wi) < Epsilon) return false;
        h.N = mul(wi, -1);
        h.distance = DistantDistance;
        return true;
    }
    case Rect:
    case Disk: {
        const float distance = planeDistance(l, p);
        if (l.sidedness != TwoSided && distance < Epsilon) return false;
        V3 local;
        if (l.type == Rect) {
            local = {(0.5f - r[0]) * (2 * l.halfWidth), (0.5f - r[1]) * (2 * l.halfHeight), 0.0f};
        } else {
            float s, c;
            sincosSample(TwoPi * r[1], s, c);
            const float radius = sqrtf(r[0]);
            local = {radius * c, radius * s, 0.0f};
        }
        wi = sub(add(rows(l.local2Render, local), l.position), p);
        if (l.type == Disk && n && dot(*n, wi) < Epsilon) return false;
        h.distance = sqrtf(lengthSq(wi));
        if (h.distance < Epsilon) return false;
        wi = mul(wi, 1.0f / h.distance);
        if (l.type == Rect && n && dot(*n, wi) < Epsilon) return false;
        h.N = dot(l.direction, wi) < 0.0f ? l.direction : mul(l.direction, -1);
        return true;
    }
    case Spot: {
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        if (localP.z <= 0.0f) return false;
        float s, c, lx, ly;
        sincosSample(TwoPi * r[1], s, c);
        const float dx = sqrtf(r[0]) * c, dy = sqrtf(r[0]) * s;
        if (localP.z > l.crossOverDistance) {
            lx = dx * l.lensRadius;
            ly = dy * l.lensRadiusY;
            float fx, fy;
            lensToFocal(l, lx, ly, localP, fx, fy);
            h.data0 = 0.5f * (fx * l.rcpFocalRadius) + 0.5f;
            h.data1 = -0.5f * (fy * l.rcpFocalRadiusY) + 0.5f;
        } else {
            focalToLens(l, dx * l.focalRadius, dy * l.focalRadiusY, localP, lx, ly);
            const float nx = lx * l.rcpLensRadius, ny = ly * l.rcpLensRadiusY;
            if (nx * nx + ny * ny > 1.0f) return false;
            h.data0 = 0.5f * dx + 0.5f;
            h.data1 = -0.5f * dy + 0.5f;
        }
        wi = sub(add(rows(l.local2Render, V3{lx, ly, 0.0f}), l.position), p);
        if (n && dot(*n, wi) <= 0.0f) return false;
        h.distance = sqrtf(lengthSq(wi));
        h.N = l.direction;
        wi = mul(wi, 1.0f / h.distance);
        return true;
    }
    case Sphere: {
        const V3 v = sub(l.position, p);
        const float v2 = dot(v, v), c = v2 - l.radiusSq;
        float t;
        V3 normal;
        if (c < 0.0f) {
            if (l.sidedness == Regular) return false;
            h.data1 = -1.0f;
            if (n) {
                const float cosTheta = r[0];
                wi = localToGlobal(*n, polar(cosTheta, sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta)), TwoPi * r[1]));
                h.data0 = OneOverTwoPi;
            } else {
                const float cosTheta = 2.0f * r[0] - 1.0f;
                wi = polar(cosTheta, sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta)), TwoPi * r[1]);
                h.data0 = OneOverFourPi;
            }
            const float b = dot(wi, v), s = sqrtf(b * b - c);
            t = b + s;
            normal = mul(sub(mul(wi, t), v), l.rcpRadius);
        } else {
            const float sinThetaMaxSq = c / v2, sinThetaSq = r[0] * sinThetaMaxSq;
            const float sinTheta = sqrtf(sinThetaSq), cosTheta = sqrtf(1.0f - sinThetaSq);
            normal = localToGlobal(mul(v, -1.0f / sqrtf(v2)), polar(cosTheta, sinTheta, TwoPi * r[1]));
            const V3 rayDir = add(v, mul(normal, l.radius));
            t = sqrtf(lengthSq(rayDir));
            if (t < Epsilon) return false;
            wi = mul(rayDir, 1.0f / t);
            if (n && dot(*n, wi) < Epsilon) return false;
            h.data0 = cosTheta / sinThetaMaxSq;
            h.data1 = t;
            if (l.sidedness == Reverse) {
                const float b = dot(wi, v), d = l.radiusSq - lengthSq(sub(v, mul(wi, b)));
                t = b + sqrtf(fmaxf(d, 0.0f));
                normal = mul(sub(mul(wi, t), v), l.rcpRadius);
            }
        }
        h.N = l.sidedness == Regular ? normal : mul(normal, -1);
        h.distance = t;
        return true;
    }
    }
    return false;
}

// The radiance arriving at p from the light along wi, and the solid-angle pdf of
// sampling it (Light::eval).
X2_HD inline V3 eval(const Light& l, V3 p, V3 wi, const Hit& h, float& pdf) {
    if (l.type == Spot) {
        const float x = 2.0f * h.data0 - 1.0f, y = 2.0f * h.data1 - 1.0f;
        const float shaped = falloff(l.falloffType, (1.0f - sqrtf(x * x + y * y)) * l.falloffGradient);
        const float scale = areaToSolidAngleScale(wi, h.N, h.distance);
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        if (localP.z > l.crossOverDistance) {
            pdf = l.invArea * scale;
        } else {
            const float zRatio = (l.focalDistance - localP.z) / localP.z;
            pdf = l.focalPlanePdfConst * scale * zRatio * zRatio;
        }
        return surface::mul(l.radiance, shaped);
    }
    switch (l.type) {
    case Env:
    case Distant: pdf = l.invArea; break;
    case Rect:
    case Disk: pdf = l.invArea * areaToSolidAngleScale(wi, h.N, h.distance); break;
    case Sphere:
        pdf = h.data1 >= 0.0f ? h.data0 / (Pi * l.radiusSq) * areaToSolidAngleScale(wi, h.N, h.data1) : h.data0;
        break;
    default: pdf = 0.0f;
    }
    return l.radiance;
}

// Whether a ray from p along wi meets the light within maxDistance
// (Light::intersect), for MIS of BSDF samples. n is the culling normal, as in sample().
X2_HD inline bool intersect(const Light& l, V3 p, const V3* n, V3 wi, float maxDistance, Hit& h) {
    using namespace surface;
    switch (l.type) {
    case Env:
        if (EnvDistance > maxDistance) return false;
        h.N = mul(wi, -1);
        h.distance = EnvDistance;
        return true;
    case Distant:
        if (dot(wi, l.direction) > -l.cosThetaMax || DistantDistance > maxDistance) return false;
        h.N = mul(wi, -1);
        h.distance = DistantDistance;
        return true;
    case Rect:
    case Disk: {
        const V3 localWi = rows(l.render2LocalRot, wi), localP = rows(l.render2Local, sub(p, l.position));
        if (rejectPosDirSidedness(l, localP.z, localWi.z)) return false;
        const float localDistance = -localP.z / localWi.z, renderDistance = l.scale * localDistance;
        if (renderDistance > maxDistance) return false;
        const V3 hit = add(localP, mul(localWi, localDistance));
        if (l.type == Rect ? (fabsf(hit.x) >= l.halfWidth || fabsf(hit.y) >= l.halfHeight)
                           : (hit.x * hit.x + hit.y * hit.y > 1.0f))
            return false;
        h.N = localWi.z < 0.0f ? l.direction : mul(l.direction, -1);
        h.distance = renderDistance;
        return true;
    }
    case Spot: {
        const V3 localWi = rows(l.render2LocalRot, wi);
        if (localWi.z >= 0.0f) return false;
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        if (localP.z <= 0.0f) return false;
        const float localDistance = -localP.z / localWi.z, renderDistance = l.scale * localDistance;
        if (renderDistance > maxDistance) return false;
        const float lx = localP.x + localDistance * localWi.x, ly = localP.y + localDistance * localWi.y;
        const float nx = lx * l.rcpLensRadius, ny = ly * l.rcpLensRadiusY;
        if (nx * nx + ny * ny > 1.0f) return false;
        h.N = l.direction;
        h.distance = renderDistance;
        float fx, fy;
        lensToFocal(l, lx, ly, localP, fx, fy);
        h.data0 = 0.5f * (fx * l.rcpFocalRadius) + 0.5f;
        h.data1 = -0.5f * (fy * l.rcpFocalRadiusY) + 0.5f;
        return true;
    }
    case Sphere: {
        const V3 v = sub(l.position, p);
        const float b = dot(wi, v), v2 = dot(v, v), c = v2 - l.radiusSq;
        if (c > 0.0f ? b <= 0.0f : l.sidedness == Regular) return false;
        const float d = l.radiusSq - lengthSq(sub(v, mul(wi, b)));
        if (d <= 0.0f) return false;
        const float s = sqrtf(d), t = l.sidedness == Regular ? b - s : b + s;
        if (t > maxDistance) return false;
        const V3 normal = mul(sub(mul(wi, t), v), l.rcpRadius);
        h.N = l.sidedness == Regular ? normal : mul(normal, -1);
        h.distance = t;
        if (c < 0.0f) {
            h.data1 = -1.0f;
            h.data0 = n ? OneOverTwoPi : OneOverFourPi;
        } else {
            const float sinThetaMaxSq = c / v2;
            float cosTheta;
            if (l.sidedness == Reverse) {
                const float front = b - s;
                cosTheta = -dot(v, mul(sub(mul(wi, front), v), l.rcpRadius)) / sqrtf(v2);
                h.data1 = front;
            } else {
                cosTheta = -dot(v, normal) / sqrtf(v2);
                h.data1 = t;
            }
            h.data0 = cosTheta / sinThetaMaxSq;
        }
        return true;
    }
    }
    return false;
}

}  // namespace xpu2::interactive::lights
