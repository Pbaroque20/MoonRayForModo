// MoonRay's cameras for the path tracer, shared by the CPU and CUDA lanes: the perspective and orthographic cameras
// with their depth of field and bokeh (ProjectiveCamera, PerspectiveCamera, OrthographicCamera, LensDistribution),
// and the spherical, fisheye, DomeMaster3D and bake cameras.
//
// Adapted from MoonRay pbr/camera/*.cc and pbr/core/Util.h (toUnitDisk), Apache-2.0, copyright 2023-2024
// DreamWorks Animation LLC; see MOONRAY_LICENSE.txt.
//
// XPU2 renders in world space: Camera::cameraToRender is the camera's node transform, where MoonRay's render space is
// the camera's own space at the shutter's open (Scene::updateActiveCamera). The rays are the same; where MoonRay
// transforms a direction as a point (OrthographicCamera::createDOFRay's transformH of a direction), its camera to
// render matrix is the identity without motion blur, so a direction's transform is what it does.
#pragma once
#include "surface_core.h"
#include "light_image.h"

namespace xpu2::interactive::surface {
using sample::U32;

// A camera ray's outcome: a ray; none (MoonRay's invalid ray, tnear = tfar = sMaxValue: vector mode's
// queuePrimaryRay does not queue its sample, which adds nothing to the pixel, not even its weight); or a failure.
enum class CameraResult : unsigned { Made = 0, None = 1, Fail = 2 };

// Per type settings in Camera::k, flags and mode.
enum : unsigned {
    // SphericalCamera
    SphThetaScale = 0, SphThetaOffset = 1, SphPhiScale = 2, SphPhiOffset = 3, SphOffsetRadius = 4,
    // FisheyeCamera (mode: its mapping)
    FishRadialScale = 0, FishHalfFov = 1,
    // DomeMaster3DCamera (mode: its stereo view)
    DomeInterocular = 0, DomeFovH = 1, DomeFovV = 2, DomeParallax = 3, DomeWidthRecip = 4, DomeHeightRecip = 5,
    // BakeCamera (mode: its mode)
    BakeBias = 0,
};
enum : unsigned { SphInsideOut = 1u, DomeZenith = 1u, DomeFlipX = 2u, DomeFlipY = 4u, BakeRelativeBias = 1u };
enum : int { FisheyeStereographic = 0, FisheyeEquidistant = 1, FisheyeEquisolid = 2, FisheyeOrthographic = 3 };
enum : int { BakeFromCamera = 0, BakeAlongNormal = 1, BakeAlongReflection = 2, BakeAboveReverseNormal = 3 };

// A bake camera's position map (BakeCamera::mPosMap, w nonzero where a face covers the texel) and normal map (mNrmMap,
// or none), both posWidth x posHeight, and its normal map texture (normal_map, read bilinearly with clamped edges:
// three floats a texel, its rows from the top as OIIO reads them). A DomeMaster3D camera's interocular distance map
// is never read: MoonRay's lookup asks for mImageSpec.nchannels channels, a spec it never fills (0), so its distance
// scale stays 1.
struct CameraMap {
    const float* positions = nullptr;  // four floats a texel
    const float* normals = nullptr;    // three floats a texel
    U32 posWidth = 0, posHeight = 0;
    const float* normalMap = nullptr;  // three floats a texel
    U32 normalWidth = 0, normalHeight = 0, normalSpace = 0, needNormals = 0;
    // World to MoonRay's render space (3x4 rows): the relative bias scales with the point's place there.
    float worldToRender[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
};

X2_HD inline V3 camSub(V3 a, V3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
X2_HD inline V3 camNormalize(V3 a) {
    V3 n{0, 0, 0};
    normalize(a, n);
    return n;
}
// scene_rdl2 transformH: the point (p, 1) times m, over its w (zero when w is zero).
X2_HD inline V3 transformH(const Matrix& m, V3 p) {
    const V3 v = add(vector(m, p), {m.m[3][0], m.m[3][1], m.m[3][2]});
    const float w = ((p.x * m.m[0][3] + p.y * m.m[1][3]) + p.z * m.m[2][3]) + m.m[3][3];
    if (w == 0.0f) return {0, 0, 0};
    return {v.x / w, v.y / w, v.z / w};
}
// scene_rdl2 transformPoint: the point (p, 1) times m, w dropped.
X2_HD inline V3 transformPoint(const Matrix& m, V3 p) { return add(vector(m, p), {m.m[3][0], m.m[3][1], m.m[3][2]}); }

// Motion blur. scene_rdl2's slerp of the identity quaternion toward q (Quaternion.h slerp), its rotation and a
// translation as a matrix (Mat4(Quaternion, Vector); its last diagonal term in double, as Mat4.h writes it), the
// row-vector product a * b, and lerp.
X2_HD inline void slerpFromIdentity(const float q[4], float t, float out[4]) {
    float angle = 0.0f, sineAngle = 0.0f;
    const float cosAngle = q[0];
    if (fabsf(cosAngle) < 1.0f) {
        angle = acosf(cosAngle);
        sineAngle = sinf(angle);
    }
    if (fabsf(sineAngle) < 0.00001f) {
        const float a = 1.0f - t;
        out[0] = a * 1.0f + t * q[0];
        out[1] = a * 0.0f + t * q[1];
        out[2] = a * 0.0f + t * q[2];
        out[3] = a * 0.0f + t * q[3];
        return;
    }
    const float rcpSine = 1.0f / sineAngle, rA = sinf((1.0f - t) * angle) * rcpSine, rB = sinf(t * angle) * rcpSine;
    out[0] = 1.0f * rA + q[0] * rB;
    out[1] = 0.0f * rA + q[1] * rB;
    out[2] = 0.0f * rA + q[2] * rB;
    out[3] = 0.0f * rA + q[3] * rB;
}
X2_HD inline Matrix quaternionMatrix(const float q[4], V3 tr) {
    const float r = q[0], i = q[1], j = q[2], k = q[3];
    Matrix m{};
    m.m[0][0] = 1.0f - 2.0f * (j * j + k * k);
    m.m[0][1] = 2.0f * (i * j + r * k);
    m.m[0][2] = 2.0f * (i * k - r * j);
    m.m[1][0] = 2.0f * (i * j - r * k);
    m.m[1][1] = 1.0f - 2.0f * (i * i + k * k);
    m.m[1][2] = 2.0f * (j * k + r * i);
    m.m[2][0] = 2.0f * (i * k + r * j);
    m.m[2][1] = 2.0f * (j * k - r * i);
    m.m[2][2] = float(1.0 - double(2.0f * (i * i + j * j)));
    m.m[3][0] = tr.x;
    m.m[3][1] = tr.y;
    m.m[3][2] = tr.z;
    m.m[3][3] = 1.0f;
    return m;
}
X2_HD inline Matrix matrixProduct(const Matrix& a, const Matrix& b) {
    Matrix m{};
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j)
            m.m[i][j] = ((a.m[i][0] * b.m[0][j] + a.m[i][1] * b.m[1][j]) + a.m[i][2] * b.m[2][j]) + a.m[i][3] * b.m[3][j];
    return m;
}
X2_HD inline Matrix matrixLerp(const Matrix& a, const Matrix& b, float t) {
    Matrix m{};
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) m.m[i][j] = (1.0f - t) * a.m[i][j] + t * b.m[i][j];
    return m;
}
// Camera::computeCamera2Render's camera at ray time to camera at the shutter's open (cameraTime2CameraOpen), and
// computeRender2Camera's camera at the open to camera at ray time (cameraOpen2CameraTime).
X2_HD inline Matrix cameraTimeToOpen(const Camera& c, float time) {
    float q[4];
    slerpFromIdentity(c.closeToOpenRot, time, q);
    return quaternionMatrix(q, mul(c.closeToOpenTrans, time));
}
X2_HD inline Matrix cameraOpenToTime(const Camera& c, float time) {
    float q[4];
    slerpFromIdentity(c.openToCloseRot, time, q);
    return quaternionMatrix(q, mul(c.openToCloseTrans, time));
}
// The camera at the ray's time (getMotionBlur): its camera to render (world) space, cameraTime2CameraOpen times the
// camera at the open; a projective camera's raster to camera lerped between the open's and the close's.
X2_HD inline Camera cameraAtTime(const Camera& c, float time) {
    Camera m = c;
    if (!c.motion) return m;
    m.timeToOpen = cameraTimeToOpen(c, time);
    m.cameraToRender = matrixProduct(m.timeToOpen, c.cameraToRender);
    if (c.type == CameraPerspective || c.type == CameraOrthographic) m.rasterToCamera = matrixLerp(c.rasterToCamera, c.rasterToCamera1, time);
    return m;
}

X2_HD inline void camSincos(float a, float* s, float* c) {
#if defined(__CUDACC__)
    sincosf(a, s, c);
#else
    *s = sinf(a);
    *c = cosf(a);
#endif
}

// pbr/core/Util.h toUnitDisk: Shirley's concentric map of [0, 1)^2 onto the unit disk.
X2_HD inline void toUnitDisk(float& u, float& v) {
    if (u == 0.5f && v == 0.5f) {
        u = 0.0f;
        v = 0.0f;
        return;
    }
    const float a = 2.0f * u - 1.0f, b = 2.0f * v - 1.0f;
    float phi, r;
    if (fabsf(a) > fabsf(b)) {
        r = a;
        phi = (Pi / 4.0f) * (b / a);
    } else {
        r = b;
        phi = (Pi / 2.0f) - (Pi / 4.0f) * (a / b);
    }
    float s, c;
    camSincos(phi, &s, &c);
    u = r * c;
    v = r * s;
}

// LensDistribution::sampleLens: the lens sample on [-1, 1]^2 (its weight, which createRayImpl discards, left out).
X2_HD inline void sampleLens(const Camera& c, float& u, float& v) {
    if (c.bokeh == 2 && c.bokehImage) {
        // Image mode: the image's distribution, nearest texel, mip level 0.
        float su, sv;
        lights::imageSample(*static_cast<const lights::Image*>(c.bokehImage), u, v, 0.0f, lights::FilterNearest, su, sv);
        u = 2.0f * su - 1.0f;
        v = 2.0f * sv - 1.0f;
        return;
    }
    if (c.bokeh == 1 && c.bokehSides >= 3) {
        // Polygon mode (Graphics Gems I p. 650): the sub-triangle of the polygon's fan the sample falls in. The
        // vertices (bokehPolygonBuilder) at the angle stepped from bokeh_angle as MoonRay sums it.
        const int sides = c.bokehSides;
        int cur = int(u * float(sides));
        cur = cur < sides - 1 ? cur : sides - 1;  // MoonRay clamps to sides, a vertex past its table
        const int next = (cur + 1) % sides;
        const float step = (2.0f * Pi) / float(sides);
        float angle = c.bokehAngle, angleCur = 0.0f, angleNext = 0.0f;
        for (int i = 0; i <= cur + 1 && i < sides; ++i) {
            if (i == cur) angleCur = angle;
            if (i == next) angleNext = angle;
            angle += step;
        }
        if (next == 0) angleNext = c.bokehAngle;
        float by, bx, cy, cx;
        camSincos(angleCur, &by, &bx);
        camSincos(angleNext, &cy, &cx);
        const float lu = u * float(sides) - float(cur), lv = sqrtf(v);
        const float a = 1.0f - lv, b = (1.0f - lu) * lv, w = lu * lv;
        u = a * 0.0f + b * bx + w * cx;
        v = a * 0.0f + b * by + w * cy;
        return;
    }
    // Disk mode: bokeh off, or a shape that could not be made.
    toUnitDisk(u, v);
}

// PerspectiveCamera::createSimpleRay and createDOFRay.
X2_HD inline CameraResult perspectiveRay(const Camera& c, V3 raster, float lensX, float lensY, Ray& out) {
    const V3 fp = c.focalPoint;
    Ray v{};
    V3 dir, dirX, dirY;
    if (!c.dof) {
        dir = camSub(transformH(c.rasterToCamera, raster), fp);
        dirX = camSub(transformH(c.rasterToCamera, add(raster, {1, 0, 0})), fp);
        dirY = camSub(transformH(c.rasterToCamera, add(raster, {0, 1, 0})), fp);
        v.origin = transformPoint(c.cameraToRender, fp);
    } else {
        // getFocusPlaneHitPoint: each ray through the pinhole meets the focus plane.
        auto focus = [&](V3 r) {
            const V3 d = camNormalize(camSub(transformH(c.rasterToCamera, r), fp));
            const float t = -c.focusDistance / d.z;
            return add(fp, mul(d, t));
        };
        const V3 hit = focus(raster), hitX = focus(add(raster, {1, 0, 0})), hitY = focus(add(raster, {0, 1, 0}));
        const V3 lens = add(fp, {lensX, lensY, 0.0f});
        v.origin = transformPoint(c.cameraToRender, lens);
        dir = camSub(hit, lens);
        dirX = camSub(hitX, lens);
        dirY = camSub(hitY, lens);
    }
    V3 n;
    if (!normalize(dir, n) || n.z >= 0) return CameraResult::Fail;
    // getClipPlaneT from the focal point along the primary direction.
    v.nearT = (-c.nearClip - fp.z) / n.z;
    v.farT = (-c.farClip - fp.z) / n.z;
    if (!normalize(vector(c.cameraToRender, dir), v.direction) || !normalize(vector(c.cameraToRender, dirX), v.dx) ||
        !normalize(vector(c.cameraToRender, dirY), v.dy) || !finite(v.origin) || !finite(v.nearT) || !finite(v.farT))
        return CameraResult::Fail;
    out = v;
    return CameraResult::Made;
}

// OrthographicCamera's modifyForDofOrtho: the ray from the camera plane, its point moved by the lens sample, toward
// its focus point, started back on the near plane.
X2_HD inline void orthoDof(V3& org, V3& dir, float focusDistance, float lensX, float lensY) {
    V3 plane = org;
    plane.z = 0.0f;
    const V3 pfocus = camSub(plane, {0, 0, focusDistance});
    plane = add(plane, {lensX, lensY, 0.0f});
    dir = camNormalize(camSub(pfocus, plane));
    const float s = dir.z * org.z;
    org = add(plane, mul(dir, s));
}
// OrthographicCamera::createSimpleRay and createDOFRay: from the near plane (raster z -1), near 0 and far the clip
// planes' distance.
X2_HD inline CameraResult orthographicRay(const Camera& c, V3 raster, float lensX, float lensY, Ray& out) {
    Ray v{};
    V3 o = transformH(c.rasterToCamera, raster), ox = transformH(c.rasterToCamera, add(raster, {1, 0, 0})),
       oy = transformH(c.rasterToCamera, add(raster, {0, 1, 0}));
    V3 d{0, 0, -1}, dx{0, 0, -1}, dy{0, 0, -1};
    if (c.dof) {
        orthoDof(o, d, c.focusDistance, lensX, lensY);
        orthoDof(ox, dx, c.focusDistance, lensX, lensY);
        orthoDof(oy, dy, c.focusDistance, lensX, lensY);
    }
    v.origin = transformPoint(c.cameraToRender, o);
    const V3 originX = transformPoint(c.cameraToRender, ox), originY = transformPoint(c.cameraToRender, oy);
    v.ox = camSub(originX, v.origin);
    v.oy = camSub(originY, v.origin);
    // MoonRay transforms the directions as points (transformH) by the camera at ray time to render space
    // (computeCamera2Render), so they lean by that matrix's translation: the camera's travel since the shutter's open
    // under motion blur, and the open's place in render space (the camera at the first motion step) where the two
    // differ. render2World takes render space's direction to world space.
    auto direction = [&](V3 a) {
        const Matrix ct2r = c.motion ? matrixProduct(c.timeToOpen, c.camera2Render) : c.camera2Render;
        V3 r;
        if (!normalize(transformH(ct2r, a), r)) r = V3{0, 0, 0};
        return vector(c.render2World, r);
    };
    if (!normalize(direction(d), v.direction) || !normalize(direction(dx), v.dx) || !normalize(direction(dy), v.dy))
        return CameraResult::Fail;
    v.nearT = 0.0f;
    v.farT = c.farClip - c.nearClip;
    if (!finite(v.origin) || !finite(v.ox) || !finite(v.oy) || !(v.farT > 0.0f)) return CameraResult::Fail;
    out = v;
    return CameraResult::Made;
}

// SphericalCamera::createDirection.
X2_HD inline V3 sphericalDirection(const Camera& c, float x, float y) {
    const float theta = c.k[SphThetaScale] * y + c.k[SphThetaOffset];
    const float phi = c.k[SphPhiScale] * x + c.k[SphPhiOffset];
    float st, ct, sp, cp;
    camSincos(theta, &st, &ct);
    camSincos(phi, &sp, &cp);
    return {ct * sp, st, ct * -cp};
}
X2_HD inline CameraResult sphericalRay(const Camera& c, float x, float y, Ray& out) {
    Ray v{};
    const V3 org = transformPoint(c.cameraToRender, {0, 0, 0});
    const V3 dir = vector(c.cameraToRender, sphericalDirection(c, x, y));
    const V3 dx = vector(c.cameraToRender, sphericalDirection(c, x + 1.0f, y));
    const V3 dy = vector(c.cameraToRender, sphericalDirection(c, x, y + 1.0f));
    if (c.flags & SphInsideOut) {
        v.origin = add(org, mul(dir, c.k[SphOffsetRadius]));
        v.direction = mul(dir, -1.0f);
        v.dx = mul(dx, -1.0f);
        v.dy = mul(dy, -1.0f);
    } else {
        v.origin = org;
        v.direction = dir;
        v.dx = dx;
        v.dy = dy;
    }
    v.nearT = c.nearClip;
    v.farT = c.farClip;
    if (!finite(v.origin) || !finite(v.direction)) return CameraResult::Fail;
    out = v;
    return CameraResult::Made;
}

// FisheyeCamera::createDirection: false outside the field of view.
X2_HD inline bool fisheyeDirection(const Camera& c, V3& dir, float X, float Y) {
    X -= 0.5f * c.apertureWidth;
    Y -= 0.5f * c.apertureHeight;
    const float D = sqrtf(X * X + Y * Y);
    const float R = D * c.k[FishRadialScale];
    float sinTheta = 0.0f, cosTheta = 1.0f;
    switch (c.mode) {
    case FisheyeStereographic: {
        const float Q = 1.0f / (1.0f + R * R);
        sinTheta = 2.0f * R * Q;
        cosTheta = (1.0f - R * R) * Q;
        break;
    }
    case FisheyeEquidistant: camSincos((Pi / 2.0f) * R, &sinTheta, &cosTheta); break;
    case FisheyeEquisolid:
        sinTheta = R * sqrtf(2.0f - R * R);
        cosTheta = 1.0f - R * R;
        break;
    default: {  // orthographic
        const float R2 = R * R;
        if (R2 > 1.0f) return false;
        sinTheta = R;
        cosTheta = sqrtf(1.0f - R2);
        break;
    }
    }
    const float cosPhi = D != 0.0f ? X / D : 1.0f, sinPhi = D != 0.0f ? Y / D : 0.0f;
    dir = {sinTheta * cosPhi, sinTheta * sinPhi, -cosTheta};
    return atan2f(sinTheta, cosTheta) <= c.k[FishHalfFov];
}
X2_HD inline CameraResult fisheyeRay(const Camera& c, float x, float y, Ray& out) {
    V3 dir, dx, dy;
    if (!fisheyeDirection(c, dir, x, y)) return CameraResult::None;
    if (!fisheyeDirection(c, dx, x + 1.0f, y)) dx = dir;
    if (!fisheyeDirection(c, dy, x, y + 1.0f)) dy = dir;
    Ray v{};
    v.origin = transformPoint(c.cameraToRender, {0, 0, 0});
    v.direction = vector(c.cameraToRender, dir);
    v.dx = vector(c.cameraToRender, dx);
    v.dy = vector(c.cameraToRender, dy);
    v.nearT = c.nearClip;
    v.farT = c.farClip;
    if (!finite(v.origin) || !finite(v.direction)) return CameraResult::Fail;
    out = v;
    return CameraResult::Made;
}

// DomeMaster3DCamera::computePhiAndTheta (its remap in double, as MoonRay's).
X2_HD inline void domeAngles(const Camera& c, float x, float y, float& sinPhi, float& cosPhi, float& sinTheta, float& cosTheta) {
    x = float(2.0 * double(x) * double(c.k[DomeWidthRecip]) - 1.0);
    y = float(2.0 * double(y) * double(c.k[DomeHeightRecip]) - 1.0);
    const double phi = double(x) * (double(c.k[DomeFovH]) / 2.0);
    const double theta = (c.flags & DomeZenith) ? 1.5707963267948966 - double(y) * (double(c.k[DomeFovV]) / 2.0)
                                                : double(y) * (double(c.k[DomeFovV]) / 2.0);
    camSincos(float(phi), &sinPhi, &cosPhi);
    camSincos(float(theta), &sinTheta, &cosTheta);
}
X2_HD inline void domeFlip(const Camera& c, V3& v) {
    if (c.flags & DomeFlipX) v.x = -v.x;
    if (c.flags & DomeFlipY) {
        if (c.flags & DomeZenith)
            v.z = -v.z;
        else
            v.y = -v.y;
    }
}
// DomeMaster3DCamera::createDirection.
X2_HD inline V3 domeDirection(const Camera& c, V3 eye, float x, float y) {
    float sp, cp, st, ct;
    domeAngles(c, x, y, sp, cp, st, ct);
    V3 d = (c.flags & DomeZenith) ? V3{sp * st, -cp * st, -ct} : V3{sp * ct, st, -cp * ct};
    if (c.mode != 0 && c.k[DomeParallax] > 0.0f) d = mul(d, c.k[DomeParallax]);
    domeFlip(c, d);
    return camNormalize(camSub(d, eye));
}
X2_HD inline CameraResult domeRay(const Camera& c, float x, float y, Ray& out) {
    float sp, cp, st, ct;
    domeAngles(c, x, y, sp, cp, st, ct);
    V3 eye{c.k[DomeInterocular] * 1.0f, 0.0f, 0.0f};  // the interocular map's scale, which stays 1 (CameraMap)
    if (c.mode != 0) {
        // The eyes turn about the up axis with the longitude.
        if (c.flags & DomeZenith) {
            const float tmp = eye.x * cp - eye.y * sp;
            eye.y = eye.y * cp + eye.x * sp;
            eye.x = tmp;
        } else {
            const float tmp = eye.x * cp - eye.z * sp;
            eye.z = eye.z * cp + eye.x * sp;
            eye.x = tmp;
        }
    }
    domeFlip(c, eye);
    Ray v{};
    v.origin = transformPoint(c.cameraToRender, eye);
    v.direction = vector(c.cameraToRender, domeDirection(c, eye, x, y));
    v.dx = vector(c.cameraToRender, domeDirection(c, eye, x + 1.0f, y));
    v.dy = vector(c.cameraToRender, domeDirection(c, eye, x, y + 1.0f));
    v.nearT = c.nearClip;
    v.farT = c.farClip;
    if (!finite(v.origin) || !finite(v.direction)) return CameraResult::Fail;
    out = v;
    return CameraResult::Made;
}

// ---- BakeCamera

X2_HD inline V3 bakeLerp(V3 a, V3 b, float t) { return {(b.x - a.x) * t + a.x, (b.y - a.y) * t + a.y, (b.z - a.z) * t + a.z}; }
// BakeCamera::interpolatePosMap: the position (and normal) at uv from the texels about it that hold data, each side
// taken only where it is the nearer.
X2_HD inline bool bakeInterpolate(const CameraMap& m, float u, float v, V3& pos, V3& nrm) {
    const float xf = fminf(fmaxf(u, 0.0f), 1.0f) * float(m.posWidth - 1);
    const float yf = fminf(fmaxf(v, 0.0f), 1.0f) * float(m.posHeight - 1);
    const int lx = int(floorf(xf)), ly = int(floorf(yf)), ux = int(ceilf(xf)), uy = int(ceilf(yf));
    auto P = [&](int x, int y) { return m.positions + (size_t(y) * m.posWidth + x) * 4; };
    auto N = [&](int x, int y) {
        const float* n = m.normals + (size_t(y) * m.posWidth + x) * 3;
        return V3{n[0], n[1], n[2]};
    };
    auto p3 = [](const float* p) { return V3{p[0], p[1], p[2]}; };
    const float ty = yf - float(ly), tx = xf - float(lx);
    auto side = [&](int x, V3& ps, V3& ns) {
        const float *lo = P(x, ly), *hi = P(x, uy);
        if (lo[3] != 0.0f) {
            if (hi[3] != 0.0f) {
                ps = bakeLerp(p3(lo), p3(hi), ty);
                if (m.normals) ns = bakeLerp(N(x, ly), N(x, uy), ty);
                return true;
            }
            if (ty < 0.5f) {
                ps = p3(lo);
                if (m.normals) ns = N(x, ly);
                return true;
            }
            return false;
        }
        if (hi[3] != 0.0f && ty >= 0.5f) {
            ps = p3(hi);
            if (m.normals) ns = N(x, uy);
            return true;
        }
        return false;
    };
    V3 pl{0, 0, 0}, nl{0, 0, 0}, pr{0, 0, 0}, nr{0, 0, 0};
    const bool left = side(lx, pl, nl), right = side(ux, pr, nr);
    bool has = false;
    if (left) {
        if (right) {
            pos = bakeLerp(pl, pr, tx);
            if (m.normals) nrm = bakeLerp(nl, nr, tx);
            has = true;
        } else if (tx < 0.5f) {
            pos = pl;
            if (m.normals) nrm = nl;
            has = true;
        }
    } else if (right && tx >= 0.5f) {
        pos = pr;
        if (m.normals) nrm = nr;
        has = true;
    }
    if (has && m.normals) nrm = camNormalize(nrm);
    return has;
}
// BakeCamera::computeDpdu: a unit vector along dP/du from the texels beside uv.
X2_HD inline bool bakeDpdu(const CameraMap& m, V3 P, float u, float v, V3& dpdu) {
    const float du = 1.0f / (float(m.posWidth) - 1.0f);
    V3 rgt{0, 0, 0}, lft{0, 0, 0}, unused;
    const bool hasR = u + du <= 1.0f && bakeInterpolate(m, u + du, v, rgt, unused);
    const bool hasL = u - du >= 0.0f && bakeInterpolate(m, u - du, v, lft, unused);
    auto unit = [&](V3 d) {
        const float l = dot(d, d);
        if (fabsf(l) < 1e-6f) return false;  // scene_rdl2 isZero
        dpdu = camNormalize(d);
        return true;
    };
    if (hasR && hasL && unit(camSub(rgt, lft))) return true;
    if (hasR && unit(camSub(rgt, P))) return true;
    if (hasL && unit(camSub(P, lft))) return true;
    return false;
}
// The normal map at (s, t): OIIO's bilinear lookup with clamped edges and no footprint, level 0.
X2_HD inline V3 bakeNormalMapAt(const CameraMap& m, float s, float t) {
    const float fx = s * float(m.normalWidth) - 0.5f, fy = t * float(m.normalHeight) - 0.5f;
    const float x0f = floorf(fx), y0f = floorf(fy);
    const float ax = fx - x0f, ay = fy - y0f;
    auto texel = [&](int x, int y) {
        x = x < 0 ? 0 : x >= int(m.normalWidth) ? int(m.normalWidth) - 1 : x;
        y = y < 0 ? 0 : y >= int(m.normalHeight) ? int(m.normalHeight) - 1 : y;
        const float* p = m.normalMap + (size_t(y) * m.normalWidth + x) * 3;
        return V3{p[0], p[1], p[2]};
    };
    const int x0 = int(x0f), y0 = int(y0f);
    const V3 top = bakeLerp(texel(x0, y0), texel(x0 + 1, y0), ax), bottom = bakeLerp(texel(x0, y0 + 1), texel(x0 + 1, y0 + 1), ax);
    return bakeLerp(top, bottom, ay);
}
// scene_rdl2 ReferenceFrame(N, T)::localToGlobal: Z = N, Y = normalize(N x T), X = Y x Z.
X2_HD inline V3 frameLocalToGlobal(V3 n, V3 t, V3 l) {
    const V3 y = camNormalize(cross(n, t)), x = cross(y, n);
    return add(add(mul(x, l.x), mul(y, l.y)), mul(n, l.z));
}
X2_HD inline CameraResult bakeRay(const Camera& c, float x, float y, Ray& out) {
    if (!c.map) return CameraResult::Fail;
    const CameraMap& m = *static_cast<const CameraMap*>(c.map);
    const float width = c.apertureWidth, height = c.apertureHeight;
    const float u = x / width, v = y / height;
    V3 P{0, 0, 0}, N{0, 0, 0};
    if (!bakeInterpolate(m, u, v, P, N)) return CameraResult::None;
    const float uX = fminf(u + 1.0f / width, 1.0f), vY = fminf(v + 1.0f / height, 1.0f);
    V3 Px, Nx, Py, Ny;
    if (!bakeInterpolate(m, uX, v, Px, Nx)) {
        Px = P;
        Nx = N;
    }
    if (!bakeInterpolate(m, u, vY, Py, Ny)) {
        Py = P;
        Ny = N;
    }
    if (m.needNormals && m.normalMap) {
        V3 nMap = bakeNormalMapAt(m, u, 1.0f - v);
        if (m.normalSpace == 0) {
            N = nMap;
        } else {
            V3 dpdu;
            nMap = camSub(mul(nMap, 2.0f), {1, 1, 1});
            if (bakeDpdu(m, P, u, v, dpdu)) {
                N = camNormalize(frameLocalToGlobal(N, dpdu, nMap));
            } else {
                // ReferenceFrame(N): MoonRay's frame about N alone (shade_math's localToGlobal frame).
                const float sign = copysignf(1.0f, N.z), a = -1.0f / (sign + N.z), b = N.x * N.y * a;
                const V3 fx{1.0f + sign * N.x * N.x * a, sign * b, -sign * N.x}, fy{b, sign + N.y * N.y * a, -N.y};
                N = camNormalize(add(add(mul(fx, nMap.x), mul(fy, nMap.y)), mul(N, nMap.z)));
            }
        }
    }
    float bias = c.k[BakeBias];
    if (c.flags & BakeRelativeBias) {
        // The point in MoonRay's render space (the camera's), where MoonRay measures it.
        const float* w = m.worldToRender;
        const V3 r{w[0] * P.x + w[1] * P.y + w[2] * P.z + w[3], w[4] * P.x + w[5] * P.y + w[6] * P.z + w[7],
                   w[8] * P.x + w[9] * P.y + w[10] * P.z + w[11]};
        bias *= fmaxf(fmaxf(fabsf(r.x), fabsf(r.y)), fmaxf(fabsf(r.z), 1.0f));
    }
    float nearT = c.nearClip;
    const V3 cam = transformPoint(c.cameraToRender, {0, 0, 0});
    auto make = [&](V3 p, V3 n, V3& org, V3& dir) {
        switch (c.mode) {
        case BakeFromCamera:
            dir = camNormalize(camSub(p, cam));
            org = camSub(p, mul(dir, bias));
            break;
        case BakeAlongNormal:
            dir = camNormalize(n);
            org = add(p, mul(dir, bias));
            break;
        case BakeAlongReflection: {
            // shading::computeReflectionDirection(N, wo): 2 (N.wo) N - wo.
            const V3 wo = camNormalize(camSub(cam, p));
            dir = camSub(mul(n, 2.0f * dot(n, wo)), wo);
            org = add(p, mul(dir, bias));
            break;
        }
        default:
            dir = mul(camNormalize(n), -1.0f);
            org = camSub(p, mul(dir, bias));
            break;
        }
    };
    V3 o, d, oX, dX, oY, dY;
    make(P, N, o, d);
    make(Px, Nx, oX, dX);
    make(Py, Ny, oY, dY);
    if ((c.mode == BakeFromCamera || c.mode == BakeAboveReverseNormal) && bias > 0.0f) nearT = bias / 2.0f;
    Ray r{};
    r.origin = o;
    r.direction = d;
    r.dx = dX;
    r.dy = dY;
    r.ox = camSub(oX, o);
    r.oy = camSub(oY, o);
    r.nearT = nearT;
    r.farT = c.farClip;
    if (!finite(r.origin) || !finite(r.direction) || !(dot(d, d) > 0.0f)) return CameraResult::Fail;
    out = r;
    return CameraResult::Made;
}

// Camera::createRay at raster (x, y) of the region window, with the lens sample (lensU, lensV) on [0, 1)^2.
X2_HD inline CameraResult cameraSampleAt(const Camera& c, float x, float y, float lensU, float lensV, Ray& out) {
    x += c.regionX;
    y += c.regionY;
    switch (c.type) {
    case CameraPerspective:
    case CameraOrthographic: {
        float u = 0.0f, v = 0.0f;
        if (c.dof) {
            u = lensU;
            v = lensV;
            sampleLens(c, u, v);
        }
        const float lx = u * c.lensRadius, ly = v * c.lensRadius;
        return c.type == CameraPerspective ? perspectiveRay(c, {x, y, -1.0f}, lx, ly, out) : orthographicRay(c, {x, y, -1.0f}, lx, ly, out);
    }
    case CameraSpherical: return sphericalRay(c, x, y, out);
    case CameraFisheye: return fisheyeRay(c, x, y, out);
    case CameraDome: return domeRay(c, x, y, out);
    case CameraBake: return bakeRay(c, x, y, out);
    default: return CameraResult::Fail;
    }
}
// Camera::createRay at the sample's time (shutter open 0, close 1): a still camera as it is, a moving one at that time.
X2_HD inline CameraResult cameraSample(const Camera& c, float x, float y, float lensU, float lensV, float time, Ray& out) {
    if (!c.motion) return cameraSampleAt(c, x, y, lensU, lensV, out);
    const Camera m = cameraAtTime(c, time);
    return cameraSampleAt(m, x, y, lensU, lensV, out);
}

}  // namespace xpu2::interactive::surface
