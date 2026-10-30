// MoonRay XPU's curve intersection code, for both lanes: from MoonRay's
// lib/rendering/rt/gpu/optix (OptixGPUMath.h's vector and curve functions and
// OptixGPUXform; EmbreeSupport.h, EmbreeRoundlineIntersector.h,
// EmbreeBsplineCurve.h and EmbreeCurveIntersectorSweep.h, which MoonRay took
// from Embree 4). Apache-2.0: Copyright 2009-2021 Intel Corporation; Copyright
// 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt. Written by
// vendor_curves.py: only the device qualifiers (X2_HD), the includes, the
// constants and OptiX's bounding boxes are changed. Included by curve_core.h
// inside its namespace, after the vector types; not a header of its own.

// Extended versions of clamp/min/max

X2_HD inline
float clampf(const float val, const float low, const float high)
{
    return fminf(high, fmaxf(low, val));
}

X2_HD inline
float fmaxf(const float a, const float b, const float c)
{
    return fmaxf(fmaxf(a, b), c);
}

X2_HD inline
float fmaxf(const float a, const float b, const float c, const float d)
{
    return fmaxf(fmaxf(a, b), fmaxf(c, d));
}

X2_HD inline
float fminf(const float a, const float b, const float c)
{
    return fminf(fminf(a, b), c);
}

X2_HD inline
float fminf(const float a, const float b, const float c, const float d)
{
    return fminf(fminf(a, b), fminf(c, d));
}

// Other misc useful functions

X2_HD inline
float lerpf(const float v1, const float v2, const float t)
{
    return (1.f - t) * v1 + t * v2;
}

X2_HD inline
float3 lerp(const float3& v1, const float3& v2, const float t)
{
    return {(1.f - t) * v1.x + t * v2.x,
            (1.f - t) * v1.y + t * v2.y,
            (1.f - t) * v1.z + t * v2.z};
}

X2_HD inline
float4 lerp(const float4& v1, const float4& v2, const float t)
{
    return {(1.f - t) * v1.x + t * v2.x,
            (1.f - t) * v1.y + t * v2.y,
            (1.f - t) * v1.z + t * v2.z,
            (1.f - t) * v1.w + t * v2.w};
}

X2_HD inline
void swapf(float& a, float& b)
{
    float tmp = a;
    a = b;
    b = tmp;
}

// float2 operators and functions

X2_HD inline
float2 operator+(const float2& a, const float2& b)
{
    return {a.x + b.x, a.y + b.y};
}

X2_HD inline
float2 operator-(const float2& a, const float2& b)
{
    return {a.x - b.x, a.y - b.y};
}

X2_HD inline
float2 operator*(const float a, const float2& b)
{
    return {a * b.x, a * b.y};
}

X2_HD inline
float2 operator/(const float2& a, const float b)
{
    return {a.x/b, a.y/b};
}

// float3 operators and functions

X2_HD inline
float3 operator+(const float3& a, const float3& b)
{
    return {a.x + b.x, a.y + b.y, a.z + b.z};
}

X2_HD inline
float3 operator+(const float3& a, const float b)
{
    return {a.x + b, a.y + b, a.z + b};
}

X2_HD inline
float3 operator-(const float3& a, const float3& b)
{
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}

X2_HD inline
float3 operator-(const float3& a, const float b)
{
    return {a.x - b, a.y - b, a.z - b};
}

X2_HD inline
float3 operator*(const float3& v, const float a)
{
    return {v.x * a, v.y * a, v.z * a};
}

X2_HD inline
float3 operator*(const float a, const float3& v)
{
    return {v.x * a, v.y * a, v.z * a};
}

X2_HD inline
float3 operator/(const float3& v, const float a)
{
    return {v.x / a, v.y / a, v.z / a};
}

X2_HD inline
void operator/=(float3& v, const float a)
{
    v.x /= a; v.y /= a; v.z /= a;
}

X2_HD inline
float dot(const float3& a, const float3& b)
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

X2_HD inline
float3 cross(const float3& a, const float3& b)
{
    return {a.y * b.z - a.z * b.y,
            a.z * b.x - a.x * b.z,
            a.x * b.y - a.y * b.x};
}

X2_HD inline
float3 abs(const float3& a)
{
    return {fabsf(a.x), fabsf(a.y), fabsf(a.z)};
}

X2_HD inline
float length(const float3& v)
{
    return sqrtf(dot(v, v));
}

X2_HD inline
float3 normalize(const float3& v)
{
    return v * rsqrtf(dot(v, v));
}

X2_HD inline
void makeCoordSystem(const float3& v1, float3* v2, float3* v3)
{
    // v1 must be normalized
    if (fabs(v1.x) > fabs(v1.y)) {
        // cheaper than full normalize as we know one component is zero
        float s = rsqrtf(v1.x * v1.x + v1.z * v1.z);
        *v2 = {-v1.z * s, 0.f, v1.x * s};
    } else {
        float s = rsqrtf(v1.y * v1.y + v1.z * v1.z);
        *v2 = {0.f, v1.z * s, -v1.y * s};
    }

    *v3 = cross(v1, *v2);
}

X2_HD inline
float maxAbsComponent(const float3& v)
{
    return fmaxf(fabsf(v.x), fabsf(v.y), fabsf(v.z));
}

X2_HD inline
float3 min(const float3& a, const float3& b)
{
    return {fminf(a.x, b.x), fminf(a.y, b.y), fminf(a.z, b.z)};
}

X2_HD inline
float3 max(const float3& a, const float3& b)
{
    return {fmaxf(a.x, b.x), fmaxf(a.y, b.y), fmaxf(a.z, b.z)};
}

X2_HD inline
float sqr(const float3& a)
{
    return dot(a, a);
}

// float4 operators and functions

X2_HD inline
float4 make_float4_zero()
{
    return {0.f, 0.f, 0.f, 0.f};
}

X2_HD inline
float3 make_float3(const float4& v)
{
    return {v.x, v.y, v.z};
}

X2_HD inline
float4 make_float4(const float3& v)
{
    return {v.x, v.y, v.z, 0.f};
}

X2_HD inline
float4 make_float4(const float3& v, const float a)
{
    return {v.x, v.y, v.z, a};
}

X2_HD inline
float4 make_float4(const float4& v, const float a)
{
    return {v.x, v.y, v.z, a};
}

X2_HD inline
float4 operator+(const float4& a, const float4& b)
{
    return {a.x + b.x, a.y + b.y, a.z + b.z, a.w + b.w};
}

X2_HD inline
float4 operator-(const float4& v)
{
    return {-v.x, -v.y, -v.z, -v.w};
}

X2_HD inline
float4 operator-(const float4& a, const float4& b)
{
    return {a.x - b.x, a.y - b.y, a.z - b.z, a.w - b.w};
}

X2_HD inline
float4 operator*(const float4& v, const float a)
{
    return {v.x * a, v.y * a, v.z * a, v.w * a};
}

X2_HD inline
float4 operator*(const float a, const float4& v)
{
    return {v.x * a, v.y * a, v.z * a, v.w * a};
}

X2_HD inline
float4 abs(const float4& a)
{
    return {fabsf(a.x), fabsf(a.y), fabsf(a.z), fabsf(a.w)};
}

X2_HD inline
float4 cross(const float4& a, const float4& b)
{
    float3 cr = cross(make_float3(a), make_float3(b));
    return {cr.x, cr.y, cr.z, 0.f};
}

X2_HD inline
float dot3(const float4& a, const float4& b)
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

X2_HD inline
float length3(const float4& a)
{
    return sqrtf(dot3(a,a));
}

X2_HD inline
float4 min(const float4& a, const float4& b)
{
    return {fminf(a.x, b.x), fminf(a.y, b.y), fminf(a.z, b.z), fminf(a.w, b.w)};
}

X2_HD inline
float4 max(const float4& a, const float4& b)
{
    return {fmaxf(a.x, b.x), fmaxf(a.y, b.y), fmaxf(a.z, b.z), fmaxf(a.w, b.w)};
}

X2_HD inline
float4 max(const float4& a, const float4& b, const float4& c)
{
    return max(a, max(b, c));
}

X2_HD inline
float reduce_max3(const float4& a)
{
    return fmaxf(a.x, a.y, a.z);
}

X2_HD inline
float4 remove_w(const float4& a)
{
    return {a.x, a.y, a.z, 0.f};
}

// Point/line functions

X2_HD inline
float sqr_point_to_line_distance(const float3& PmQ0, const float3& Q1mQ0)
{
    const float3 N = cross(PmQ0,Q1mQ0);
    const float3 D = Q1mQ0;
    return dot(N,N) / dot(D,D);
}

// OptixAabb functions




// Curve functions

// https://en.wikipedia.org/wiki/B%C3%A9zier_curve
X2_HD inline
float4 getBezierBasis(const float t)
{
    const float t1 = 1.f - t;
    return {t1 * t1 * t1,
            3.f * t1 * t1 * t,
            3.f * t1 * t * t,
            t * t * t};
}

X2_HD inline
float4 getBezierBasisDerivative(const float t)
{
    const float t1 = 1.f - t;
    return {-3.f * t1 * t1,
            -6.f * t1 * t + 3.f * t1 * t1,
            -3.f * t * t + 6.f * t1 * t,
             3.f * t * t};
}

X2_HD inline
float4 evalBezier(const float4 cp[4], const float t)
{
    float4 basis = getBezierBasis(t);
    return basis.x * cp[0] + basis.y * cp[1] + basis.z * cp[2] + basis.w * cp[3];
}

X2_HD inline
float3 evalBezierDerivative(const float4 cp[4], const float t)
{
    float4 basis = getBezierBasisDerivative(t);
    return make_float3(basis.x * cp[0] + basis.y * cp[1] + basis.z * cp[2] + basis.w * cp[3]);
}

// From embree bspline_curve.h
X2_HD inline
float4 getBsplineBasis(const float t)
{
    const float t1 = 1.0f - t;
    return {(1.f / 6.f) * t1 * t1 * t1,
            (1.f / 6.f) * ((4.0f*(t1*t1*t1) + (t*t*t)) + (12.0f*((t1*t)*t1) + 6.0f*((t*t1)*t))),
            (1.f / 6.f) * ((4.0f*(t*t*t) + (t1*t1*t1)) + (12.0f*((t*t1)*t) + 6.0f*((t1*t)*t1))),
            (1.f / 6.f) * t * t * t};
}

X2_HD inline
float4 getBsplineBasisDerivative(const float t)
{
    const float t1 = 1.0f - t;
    return {0.5f * -t1 * t1,
            0.5f * (-t * t - 4.0f * (t * t1)),
            0.5f * (t1 * t1 + 4.0f * (t1 * t)),
            0.5f * (t * t)};
}

X2_HD inline
float4 evalBspline(const float4 cp[4], const float t)
{
    float4 basis = getBsplineBasis(t);
    return basis.x * cp[0] + basis.y * cp[1] + basis.z * cp[2] + basis.w * cp[3];
}

X2_HD inline
float3 evalBsplineDerivative(const float4 cp[4], const float t)
{
    float4 basis = getBsplineBasisDerivative(t);
    return make_float3(basis.x * cp[0] + basis.y * cp[1] + basis.z * cp[2] + basis.w * cp[3]);
}


struct OptixGPUXform
{
    OptixGPUXform() = default;

    X2_HD inline
    static OptixGPUXform identityXform()
    {
        return {1.f, 0.f, 0.f, 0.f,
                0.f, 1.f, 0.f, 0.f,
                0.f, 0.f, 1.f, 0.f};
    }

    X2_HD inline
    static OptixGPUXform rotateToZAxisXform(const float3& dir)
    {
        // transform to space where dir.z is the +Z axis
        float3 vz = normalize(dir);
        float3 vx, vy;
        makeCoordSystem(vz, &vx, &vy);
        // form the matrix:
        // [ vx.x, vy.x, vz.x, 0 ]
        // [ vx.y, vy.y, vz.y, 0 ]
        // [ vx.z, vy.z, vz.z, 0 ]
        // take the transpose to invert it
        return {vx.x, vx.y, vx.z, 0.f,
                vy.x, vy.y, vy.z, 0.f,
                vz.x, vz.y, vz.z, 0.f};
    }

    X2_HD inline
    float3 transformVector(const float3& v) const
    {
        return {m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z,
                m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z,
                m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z};
    }

    X2_HD inline
    float3 transformPoint(const float3& p) const
    {
        return {m[0][0] * p.x + m[0][1] * p.y + m[0][2] * p.z + m[0][3],
                m[1][0] * p.x + m[1][1] * p.y + m[1][2] * p.z + m[1][3],
                m[2][0] * p.x + m[2][1] * p.y + m[2][2] * p.z + m[2][3]};
    }

    X2_HD inline
    void toOptixTransform(float transform[12]) const
    {
        transform[0] = m[0][0]; transform[1] = m[0][1];  transform[2] = m[0][2];  transform[3] = m[0][3];
        transform[4] = m[1][0]; transform[5] = m[1][1];  transform[6] = m[1][2];  transform[7] = m[1][3];
        transform[8] = m[2][0]; transform[9] = m[2][1]; transform[10] = m[2][2]; transform[11] = m[2][3];
    }

    float m[3][4];
    // This is an affine 4x4 transformation matrix so the last row is always 0 0 0 1
    // and we don't need to store it.  This convention is opposite to what we use
    // in scene_rdl2 where an affine matrix has the translation in the last row and
    // 0 0 0 1 in the last column.  We use a different convention than scene_rdl2 to match
    // up with what Optix is expecting.
};


// Copyright 2009-2021 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Copyright 2023-2024 DreamWorks Animation LLC
// SPDX-License-Identifier: Apache-2.0

// Embree code common to the different Embree intersectors.



X2_HD inline
float rcp(const float x)
{
    return 1.f / x;
}

X2_HD inline
float select(const bool s, const float t, const float f)
{
    return s ? t : f;
}

X2_HD inline
float3 select(const bool s, const float3& t, const float3& f)
{
    return s ? t : f;
}

X2_HD inline
float sqr(const float a)
{
    return a * a;
}

X2_HD inline
float clamp(const float x, const float lower = 0.f, const float upper = 1.f)
{
    return fmaxf(fminf(x, upper), lower);
}

// Calling this normalize() causes compiler confusion in some code as it
// can't figure out which one to use.
X2_HD inline
float4 normalize4(const float4& a)
{
    return a*rsqrtf(dot3(a,a));
}

// differentiated normalization
X2_HD inline
float4 dnormalize(const float4& p, const float4& dp)
{
    const float pp  = dot3(p,p);
    const float pdp = dot3(p,dp);
    return (pp*dp-pdp*p)*rcp(pp)*rsqrtf(pp);
}

X2_HD inline
unsigned int bsf(unsigned int v)
{
    // Count trailing zero bits.  Embree calls _tzcnt_u32() here but that's not available in CUDA.
    if (v == 0) {
        return 32;
    }
    unsigned int count = 0;
    while ((v & 1) == 0) {
        count += 1;
        v >>= 1;
    }
    return count;
}

// (pos_inf, inf, neg_inf, ulp and min_rcp_input: curve_core.h's macros, undefined after this file)

struct EmbreeRayHit
{
    float3 org;
    float3 dir;
    float tnear;
    float tfar;
    float3 Ng;
    float u;
    float v;
};

struct BBox
{
    float4 lower, upper;

    X2_HD inline
    BBox() {}

    X2_HD inline
    BBox(const float4& v) : lower(v), upper(v) {}

    X2_HD inline
    BBox(const float4& lower, const float4& upper) : lower(lower), upper(upper) {}
};

X2_HD inline
BBox merge(const BBox& a, const BBox& b)
{
    return BBox(min(a.lower, b.lower), max(a.upper, b.upper));
}

X2_HD inline
BBox merge(const BBox& a, const BBox& b, const BBox& c, const BBox& d)
{
    return merge(merge(a,b), merge(c,d));
}

struct BBox1
{
    float lower, upper;

    X2_HD inline
    BBox1() {}

    X2_HD inline
    BBox1(const float& v) : lower(v), upper(v) {}

    X2_HD inline
    BBox1(const float& lower, const float& upper) : lower(lower), upper(upper) {}
};

X2_HD inline
BBox1 intersect(const BBox1& a, const BBox1& b)
{
    return BBox1(fmaxf(a.lower, b.lower), fminf(a.upper, b.upper));
}

X2_HD inline
void subtract(const BBox1& a, const BBox1& b, BBox1& c, BBox1& d)
{
    c.lower = a.lower;
    c.upper = fminf(a.upper,b.lower);
    d.lower = fmaxf(a.lower,b.upper);
    d.upper = a.upper;
}

struct HalfPlane
{
    const float4 P;  //!< plane origin
    const float4 N;  //!< plane normal

    X2_HD inline HalfPlane(const float4& P, const float4& N)
      : P(P), N(N) {}

    X2_HD inline
    BBox1 intersect(const float4& ray_org, const float4& ray_dir) const
    {
        float4 O = ray_org - P;
        float4 D = ray_dir;
        float ON = dot3(O,N);
        float DN = dot3(D,N);
        bool eps = abs(DN) < min_rcp_input;
        float t = -ON*rcp(DN);
        float lower = select(eps || DN < 0.0f, float(neg_inf), t);
        float upper = select(eps || DN > 0.0f, float(pos_inf), t);
        return BBox1(lower,upper);
    }
};

////////////////////////////////////////////////////////////////////////////////
/// 2D Linear Transform (2x2 Matrix)
////////////////////////////////////////////////////////////////////////////////
struct LinearSpace2
{
    /*! default matrix constructor */
    X2_HD inline
    LinearSpace2() {}

    /*! matrix construction from column vectors */
    X2_HD inline
    LinearSpace2(const float2& vx, const float2& vy)
      : vx(vx), vy(vy) {}

    /*! matrix construction from row major data */
    X2_HD inline
    LinearSpace2(const float m00, const float m01,
                 const float m10, const float m11)
    {
        vx.x = m00;
        vx.y = m10;
        vy.x = m01;
        vy.y = m11;
    }

    /*! compute the determinant of the matrix */
    X2_HD inline
    float det() const { return vx.x*vy.y - vx.y*vy.x; }

    /*! compute adjoint matrix */
    X2_HD inline
    LinearSpace2 adjoint() const { return LinearSpace2(vy.y,-vy.x,-vx.y,vx.x); }

    /*! compute inverse matrix */
    X2_HD inline
    LinearSpace2 inverse() const;

    /*! the column vectors of the matrix */
    float2 vx,vy;
};

X2_HD inline
LinearSpace2 rcp(const LinearSpace2& a)
{
    return a.inverse();
}

X2_HD inline
float2 operator*(const LinearSpace2& a, const float2& b)
{
    return b.x*a.vx + b.y*a.vy;
}

X2_HD inline
LinearSpace2 operator/(const LinearSpace2& a, const float b)
{
    return LinearSpace2(a.vx/b, a.vy/b);
}

X2_HD inline
LinearSpace2 LinearSpace2::inverse() const
{
    return adjoint()/det();
}

struct Cylinder
{
    const float4 p0;  //!< start location
    const float4 p1;  //!< end position
    const float rr;   //!< squared radius of cylinder

    X2_HD inline Cylinder(const float4& p0, const float4& p1, const float r)
        : p0(p0), p1(p1), rr(sqr(r)) {}

    X2_HD inline
    bool intersect(const float4& org,
                   const float4& dir,
                   BBox1& t_o,
                   float& u0_o, float4& Ng0_o,
                   float& u1_o, float4& Ng1_o) const
    {
        /* calculate quadratic equation to solve */
        const float rl = 1.f/length3(p1-p0);
        const float4 P0 = p0, dP = (p1-p0)*rl;
        const float4 O = org-P0, dO = dir;

        const float dOdO = dot3(dO,dO);
        const float OdO = dot3(dO,O);
        const float OO = dot3(O,O);
        const float dOz = dot3(dP,dO);
        const float Oz = dot3(dP,O);

        const float A = dOdO - sqr(dOz);
        const float B = 2.0f * (OdO - dOz*Oz);
        const float C = OO - sqr(Oz) - rr;

        /* we miss the cylinder if determinant is smaller than zero */
        const float D = B*B - 4.0f*A*C;
        if (D < 0.0f) {
            t_o = BBox1(pos_inf,neg_inf);
            return false;
        }

        /* special case for rays that are parallel to the cylinder */
        const float eps = 16.0f*float(ulp)*max(abs(dOdO),abs(sqr(dOz)));
        if (fabsf(A) < eps)
        {
            if (C <= 0.0f) {
                t_o = BBox1(neg_inf,pos_inf);
                return true;
            } else {
                t_o = BBox1(pos_inf,neg_inf);
                return false;
            }
        }

        /* standard case for rays that are not parallel to the cylinder */
        const float Q = sqrt(D);
        const float rcp_2A = rcp(2.0f*A);
        const float t0 = (-B-Q)*rcp_2A;
        const float t1 = (-B+Q)*rcp_2A;

        /* calculates u and Ng for near hit */
        {
            u0_o = (t0*dOz+Oz)*rl;
            const float4 Pr = t0*dir;
            const float4 Pl = u0_o*(p1-p0)+p0;
            Ng0_o = Pr-Pl;
        }

        /* calculates u and Ng for far hit */
        {
            u1_o = (t1*dOz+Oz)*rl;
            const float4 Pr = t1*dir;
            const float4 Pl = u1_o*(p1-p0)+p0;
            Ng1_o = Pr-Pl;
        }

        t_o.lower = t0;
        t_o.upper = t1;
        return true;
    }
};

// Copyright 2009-2021 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Copyright 2023-2024 DreamWorks Animation LLC
// SPDX-License-Identifier: Apache-2.0

// This is pulled from Embree 4 almost verbatim so we match Embree's round
// linear curves behavior.  There are things in here that can be simplified
// or cleaned up, but we don't want to do that because we want to remain 1:1 with
// the original Embree code for 100% matching behavior.




/*

  This file implements the intersection of a ray with a round linear
  curve segment. We define the geometry of such a round linear curve
  segment from point p0 with radius r0 to point p1 with radius r1
  using the cone that touches spheres p0/r0 and p1/r1 tangentially
  plus the sphere p1/r1. We denote the tangentially touching cone from
  p0/r0 to p1/r1 with cone(p0,r0,p1,r1) and the cone plus the ending
  sphere with cone_sphere(p0,r0,p1,r1).

  For multiple connected round linear curve segments this construction
  yield a proper shape when viewed from the outside. Using the
  following CSG we can also handle the interior in most common cases:

     round_linear_curve(pl,rl,p0,r0,p1,r1,pr,rr) =
       cone_sphere(p0,r0,p1,r1) - cone(pl,rl,p0,r0) - cone(p1,r1,pr,rr)

  Thus by subtracting the neighboring cone geometries, we cut away
  parts of the center cone_sphere surface which lie inside the
  combined curve. This approach works as long as geometry of the
  current cone_sphere penetrates into direct neighbor segments only,
  and not into segments further away.

  To construct a cone that touches two spheres at p0 and p1 with r0
  and r1, one has to increase the cone radius at r0 and r1 to obtain
  larger radii w0 and w1, such that the infinite cone properly touches
  the spheres.  From the paper "Ray Tracing Generalized Tube
  Primitives: Method and Applications"
  (https://www.researchgate.net/publication/334378683_Ray_Tracing_Generalized_Tube_Primitives_Method_and_Applications)
  one can derive the following equations for these increased
  radii:

     sr = 1.0f / sqrt(1-sqr(dr)/sqr(p1-p0))
     w0 = sr*r0
     w1 = sr*r1

  Further, we want the cone to start where it touches the sphere at p0
  and to end where it touches sphere at p1.  Therefore, we need to
  construct clipping locations y0 and y1 for the start and end of the
  cone. These start and end clipping location of the cone can get
  calculated as:

     Y0 =               - r0 * (r1-r0) / length(p1-p0)
     Y1 = length(p1-p0) - r1 * (r1-r0) / length(p1-p0)

  Where the cone starts a distance Y0 and ends a distance Y1 away of
  point p0 along the cone center. The distance between Y1-Y0 can get
  calculated as:

    dY = length(p1-p0) - (r1-r0)^2 / length(p1-p0)

  In the code below, Y will always be scaled by length(p1-p0) to
  obtain y and you will find the terms r0*(r1-r0) and
  (p1-p0)^2-(r1-r0)^2.

 */

struct RoundLineIntersectorHit
{
    X2_HD inline
    RoundLineIntersectorHit() {}

    X2_HD inline
    RoundLineIntersectorHit(const float u, const float v, const float t, const float3& Ng)
      : u(u), v(v), t(t), Ng(Ng) {}

public:
    float u;
    float v;
    float t;
    float3 Ng;
};

struct ConeGeometry
{
    X2_HD inline
    ConeGeometry (const float4& a, const float4& b) :
        p0{make_float3(a)},
        p1{make_float3(b)},
        dP(p1-p0),
        dPdP(dot(dP,dP)),
        r0(a.w),
        sqr_r0(sqr(r0)),
        r1(b.w),
        dr(r1-r0),
        drdr(dr*dr),
        r0dr(r0*dr),
        g(dPdP - drdr) {}

/*
    This function tests if a point is accepted by first cone
    clipping plane.

    First, we need to project the point onto the line p0->p1:

        Y = (p-p0)*(p1-p0)/length(p1-p0)

    This value y is the distance to the projection point from
    p0. The clip distances are calculated as:

        Y0 =               - r0 * (r1-r0) / length(p1-p0)
        Y1 = length(p1-p0) - r1 * (r1-r0) / length(p1-p0)

    Thus to test if the point p is accepted by the first
    clipping plane we need to test Y > Y0 and to test if it
    is accepted by the second clipping plane we need to test
    Y < Y1.

    By multiplying the calculations with length(p1-p0) these
    calculation can get simplied to:

        y = (p-p0)*(p1-p0)
        y0 =           - r0 * (r1-r0)
        y1 = (p1-p0)^2 - r1 * (r1-r0)

    and the test y > y0 and y < y1.
*/
    X2_HD
    bool isClippedByPlane (const bool valid_i, const float3& p) const
    {
        const float3 p0p = p - p0;
        const float y = dot(p0p, dP);
        const float cap0 = -r0dr;
        const bool inside_cone = y > cap0;
        return valid_i & (p0.x != inf) & (p1.x != inf) & inside_cone;
    }

/*
    This function tests whether a point lies inside the capped cone
    tangential to its ending spheres.

    Therefore one has to check if the point is inside the
    region defined by the cone clipping planes, which is
    performed similar as in the previous function.

    To perform the inside cone test we need to project the
    point onto the line p0->p1:

        dP = p1-p0
        Y = (p-p0)*dP/length(dP)

    This value Y is the distance to the projection point from
    p0. To obtain a parameter value u going from 0 to 1 along
    the line p0->p1 we calculate:

        U = Y/length(dP)

    The radii to use at points p0 and p1 are:

        w0 = sr * r0
        w1 = sr * r1
        dw = w1-w0

    Using these radii and u one can directly test if the point
    lies inside the cone using the formula dP*dP < wy*wy with:

        wy = w0 + u*dw
        py = p0 + u*dP - p

    By multiplying the calculations with length(p1-p0) and
    inserting the definition of w can obtain simpler equations:

        y = (p-p0)*dP
        ry = r0 + y/dP^2 * dr
        wy = sr*ry
        py = p0 + y/dP^2*dP - p
        y0 =      - r0 * dr
        y1 = dP^2 - r1 * dr

    Thus for the in-cone test we get:

        py^2 < wy^2
        <=>  py^2 < sr^2 * ry^2
        <=>  py^2 * ( dP^2 - dr^2 ) < dP^2 * ry^2

    This can further get simplified to:

        (p0-p)^2 * (dP^2 - dr^2) - y^2 < dP^2 * r0^2 + 2.0f*r0*dr*y;
*/
    X2_HD
    bool isInsideCappedCone (const bool valid_i, const float3& p) const
    {
        const float3 p0p = p - p0;
        const float y = dot(p0p, dP);
        const float cap0 = -r0dr + ulp;
        const float cap1 = -r1 * dr + dPdP;

        bool inside_cone = valid_i & (p0.x != inf) & (p1.x != inf);
        inside_cone &= y > cap0;  // start clipping plane
        inside_cone &= y < cap1;  // end clipping plane
        inside_cone &= sqr(p0p) * g - sqr(y) < dPdP * sqr_r0 + 2.0f * r0dr * y; // in cone test
        return inside_cone;
    }

protected:
    float3 p0;
    float3 p1;
    float3 dP;
    float dPdP;
    float r0;
    float sqr_r0;
    float r1;
    float dr;
    float drdr;
    float r0dr;
    float g;
};

struct ConeGeometryIntersector : public ConeGeometry
{
    using ConeGeometry::p0;
    using ConeGeometry::p1;
    using ConeGeometry::dP;
    using ConeGeometry::dPdP;
    using ConeGeometry::r0;
    using ConeGeometry::sqr_r0;
    using ConeGeometry::r1;
    using ConeGeometry::dr;
    using ConeGeometry::r0dr;
    using ConeGeometry::g;

    X2_HD inline
    ConeGeometryIntersector(const float3& ray_org, const float3& ray_dir, const float& dOdO, const float& rcp_dOdO, const float4& a, const float4& b)
        : ConeGeometry(a,b),
        org(ray_org),
        O(ray_org-p0),
        dO(ray_dir),
        dOdO(dOdO),
        rcp_dOdO(rcp_dOdO),
        OdP(dot(dP,O)),
        dOdP(dot(dP,dO)),
        yp(OdP + r0dr) {}

/*
    This function intersects a ray with a cone that touches a
    start sphere p0/r0 and end sphere p1/r1.

    To find this ray/cone intersections one could just
    calculate radii w0 and w1 as described above and use a
    standard ray/cone intersection routine with these
    radii. However, it turns out that calculations can get
    simplified when deriving a specialized ray/cone
    intersection for this special case. We perform
    calculations relative to the cone origin p0 and define:

        O  = ray_org - p0
        dO = ray_dir
        dP = p1-p0
        dr = r1-r0
        dw = w1-w0

    For some t we can compute the potential hit point h = O + t*dO and
    project it onto the cone vector dP to obtain u = (h*dP)/(dP*dP). In
    case of an intersection, the squared distance from the hit point
    projected onto the cone center line to the hit point should be equal
    to the squared cone radius at u:

        (u*dP - h)^2 = (w0 + u*dw)^2

    Inserting the definition of h, u, w0, and dw into this formula, then
    factoring out all terms, and sorting by t^2, t^1, and t^0 terms
    yields a quadratic equation to solve.

    Inserting u:
        ( (h*dP)*dP/dP^2 - h )^2 = ( w0 + (h*dP)*dw/dP^2 )^2

    Multiplying by dP^4:
        ( (h*dP)*dP - h*dP^2 )^2 = ( w0*dP^2 + (h*dP)*dw )^2

    Inserting w0 and dw:
        ( (h*dP)*dP - h*dP^2 )^2 = ( r0*dP^2 + (h*dP)*dr )^2 / (1-dr^2/dP^2)
        ( (h*dP)*dP - h*dP^2 )^2 *(dP^2 - dr^2) = dP^2 * ( r0*dP^2 + (h*dP)*dr )^2

    Now one can insert the definition of h, factor out, and presort by t:
        ( ((O + t*dO)*dP)*dP - (O + t*dO)*dP^2 )^2 *(dP^2 - dr^2) = dP^2 * ( r0*dP^2 + ((O + t*dO)*dP)*dr )^2
        ( (O*dP)*dP-O*dP^2 + t*( (dO*dP)*dP - dO*dP^2 ) )^2 *(dP^2 - dr^2) = dP^2 * ( r0*dP^2 + (O*dP)*dr + t*(dO*dP)*dr )^2

    Factoring out further and sorting by t^2, t^1 and t^0 yields:

        0 =   t^2 * [ ((dO*dP)*dP - dO-dP^2)^2 * (dP^2 - dr^2) - dP^2*(dO*dP)^2*dr^2 ]
          + 2*t^1 * [ ((O*dP)*dP - O*dP^2) * ((dO*dP)*dP - dO*dP^2) * (dP^2 - dr^2) - dP^2*(r0*dP^2 + (O*dP)*dr)*(dO*dP)*dr ]
          +   t^0 * [ ( (O*dP)*dP - O*dP^2)^2 * (dP^2-dr^2) - dP^2*(r0*dP^2 + (O*dP)*dr)^2 ]

    This can be simplified to:

        0 =   t^2 * [ (dP^2 - dr^2)*dO^2 - (dO*dP)^2 ]
          + 2*t^1 * [ (dP^2 - dr^2)*(O*dO) - (dO*dP)*(O*dP + r0*dr) ]
          +   t^0 * [ (dP^2 - dr^2)*O^2 - (O*dP)^2 - r0^2*dP^2 - 2.0f*r0*dr*(O*dP) ]

    Solving this quadratic equation yields the values for t at which the
    ray intersects the cone.
*/
    X2_HD
    bool intersectCone(bool& valid, float& lower, float& upper)
    {
        /* return no hit by default */
        lower = pos_inf;
        upper = neg_inf;

        /* compute quadratic equation A*t^2 + B*t + C = 0 */
        const float OO = dot(O,O);
        const float OdO = dot(dO,O);
        const float A = g * dOdO - sqr(dOdP);
        const float B = 2.0f * (g*OdO - dOdP*yp);
        const float C = g*OO - sqr(OdP) - sqr_r0*dPdP - 2.0f*r0dr*OdP;

        /* we miss the cone if determinant is smaller than zero */
        const float D = B*B - 4.0f*A*C;
        valid &= (D >= 0.0f & g > 0.0f);  // if g <= 0 then the cone is inside a sphere end

        /* When rays are parallel to the cone surface, then the
         * ray may be inside or outside the cone. We just assume a
         * miss in that case, which is fine as rays inside the
         * cone would anyway hit the ending spheres in that
         * case. */
        valid &= abs(A) > min_rcp_input;
        if (!valid) {
            return false;
        }

        /* compute distance to front and back hit */
        const float Q = sqrt(D);
        const float rcp_2A = rcp(2.0f*A);
        t_cone_front = (-B-Q)*rcp_2A;
        y_cone_front = yp + t_cone_front*dOdP;
        lower = select( (y_cone_front > -ulp) & (y_cone_front <= g) & (g > 0.0f), t_cone_front, pos_inf);
#if !defined (EMBREE_BACKFACE_CULLING_CURVES)
        t_cone_back = (-B+Q)*rcp_2A;
        y_cone_back  = yp + t_cone_back *dOdP;
        upper = select( (y_cone_back  > -ulp) & (y_cone_back  <= g) & (g > 0.0f), t_cone_back , neg_inf);
#endif
        return true;
    }

/*
    This function intersects the ray with the end sphere at
    p1. We already clip away hits that are inside the
    neighboring cone segment.
*/
    X2_HD
    void intersectEndSphere(bool& valid,
                            const ConeGeometry& coneR,
                            float& lower, float& upper)
    {
        /* calculate front and back hit with end sphere */
        const float3 O1 = org - p1;
        const float O1dO = dot(O1,dO);
        const float h2 = sqr(O1dO) - dOdO*(sqr(O1) - sqr(r1));
        const float rhs1 = select( h2 >= 0.0f, sqrt(h2), neg_inf );

        /* clip away front hit if it is inside next cone segment */
        t_sph1_front = (-O1dO - rhs1)*rcp_dOdO;
        const float3 hit_front = org + t_sph1_front*dO;
        bool valid_sph1_front = h2 >= 0.0f & yp + t_sph1_front*dOdP > g & !coneR.isClippedByPlane(valid, hit_front);
        lower = select(valid_sph1_front, t_sph1_front, pos_inf);

#if !defined(EMBREE_BACKFACE_CULLING_CURVES)
        /* clip away back hit if it is inside next cone segment */
        t_sph1_back = (-O1dO + rhs1)*rcp_dOdO;
        const float3 hit_back = org + t_sph1_back*dO;
        bool valid_sph1_back = h2 >= 0.0f & yp + t_sph1_back*dOdP > g & !coneR.isClippedByPlane(valid, hit_back);
        upper = select(valid_sph1_back, t_sph1_back, neg_inf);
#else
        upper = neg_inf;
#endif
    }

    X2_HD
    void intersectBeginSphere(const bool valid,
                              float& lower, float& upper)
    {
        /* calculate front and back hit with end sphere */
        const float3 O1 = org - p0;
        const float O1dO = dot(O1,dO);
        const float h2 = sqr(O1dO) - dOdO*(sqr(O1) - sqr(r0));
        const float rhs1 = select(h2 >= 0.0f, sqrt(h2), neg_inf);

        /* clip away front hit if it is inside next cone segment */
        t_sph0_front = (-O1dO - rhs1)*rcp_dOdO;
        bool valid_sph1_front = valid & h2 >= 0.0f & yp + t_sph0_front*dOdP < 0;
        lower = select(valid_sph1_front, t_sph0_front, pos_inf);

#if !defined(EMBREE_BACKFACE_CULLING_CURVES)
        /* clip away back hit if it is inside next cone segment */
        t_sph0_back = (-O1dO + rhs1)*rcp_dOdO;
        bool valid_sph1_back  = valid & h2 >= 0.0f & yp + t_sph0_back*dOdP < 0;
        upper = select(valid_sph1_back, t_sph0_back, neg_inf);
#else
        upper = neg_inf;
#endif
    }

/*
    This function calculates the geometry normal of some cone hit.

    For a given hit point h (relative to p0) with a cone
    starting at p0 with radius w0 and ending at p1 with
    radius w1 one normally calculates the geometry normal by
    first calculating the parmetric u hit location along the
    cone:

        u = dot(h,dP)/dP^2

    Using this value one can now directly calculate the
    geometry normal by bending the connection vector (h-u*dP)
    from hit to projected hit with some cone dependent value
    dw/sqrt(dP^2) * normalize(dP):

        Ng = normalize(h-u*dP) - dw/length(dP) * normalize(dP)

    The length of the vector (h-u*dP) can also get calculated
    by interpolating the radii as w0+u*dw which yields:

        Ng = (h-u*dP)/(w0+u*dw) - dw/dP^2 * dP

    Multiplying with (w0+u*dw) yield a scaled Ng':

        Ng' = (h-u*dP) - (w0+u*dw)*dw/dP^2*dP

    Inserting the definition of w0 and dw and refactoring
    yield a further scaled Ng'':

        Ng'' = (dP^2 - dr^2) (h-q) - (r0+u*dr)*dr*dP

    Now inserting the definition of u gives and multiplying
    with the denominator yields:

        Ng''' = (dP^2-dr^2)*(dP^2*h-dot(h,dP)*dP) - (dP^2*r0+dot(h,dP)*dr)*dr*dP

    Factoring out, cancelling terms, dividing by dP^2, and
    factoring again yields finally:

        Ng'''' = (dP^2-dr^2)*h - dP*(dot(h,dP) + r0*dr)
*/
    X2_HD
    float3 Ng_cone(const bool front_hit) const
    {
#if !defined(EMBREE_BACKFACE_CULLING_CURVES)
        const float y = select(front_hit, y_cone_front, y_cone_back);
        const float t = select(front_hit, t_cone_front, t_cone_back);
        const float3 h = O + t*dO;
        return g*h-dP*y;
#else
        const float3 h = O + t_cone_front*dO;
        return g*h-dP*y_cone_front;
#endif
    }

    /* compute geometry normal of sphere hit as the difference
     * vector from hit point to sphere center */
    X2_HD
    float3 Ng_sphere1(const bool front_hit) const
    {
#if !defined(EMBREE_BACKFACE_CULLING_CURVES)
        const float t_sph1 = select(front_hit, t_sph1_front, t_sph1_back);
        return org+t_sph1*dO-p1;
#else
        return org+t_sph1_front*dO-p1;
#endif
    }

    X2_HD
    float3 Ng_sphere0(const bool front_hit) const
    {
#if !defined(EMBREE_BACKFACE_CULLING_CURVES)
        const float t_sph0 = select(front_hit, t_sph0_front, t_sph0_back);
        return org+t_sph0*dO-p0;
#else
        return org+t_sph0_front*dO-p0;
#endif
    }

/*
    This function calculates the u coordinate of a
    hit. Therefore we use the hit distance y (which is zero
    at the first cone clipping plane) and divide by distance
    g between the clipping planes.
*/
    X2_HD
    float u_cone(const bool front_hit) const
    {
#if !defined(EMBREE_BACKFACE_CULLING_CURVES)
        const float y = select(front_hit, y_cone_front, y_cone_back);
        return clamp(y*rcp(g));
#else
        return clamp(y_cone_front*rcp(g));
#endif
    }

private:
    float3 org;
    float3 O;
    float3 dO;
    float dOdO;
    float rcp_dOdO;
    float OdP;
    float dOdP;

    /* for ray/cone intersection */
private:
    float yp;
    float y_cone_front;
    float t_cone_front;
#if !defined (EMBREE_BACKFACE_CULLING_CURVES)
    float y_cone_back;
    float t_cone_back;
#endif

    /* for ray/sphere intersection */
private:
    float t_sph1_front;
    float t_sph0_front;
#if !defined (EMBREE_BACKFACE_CULLING_CURVES)
    float t_sph1_back;
    float t_sph0_back;
#endif
};


struct RoundLinearCurveEpilog
{
    X2_HD inline
    RoundLinearCurveEpilog(EmbreeRayHit* ray) : ray(ray) {}

    X2_HD
    bool operator() (const bool valid_i, RoundLineIntersectorHit& hit) const
    {
        if (!valid_i) {
            return false;
        }

        ray->tfar = hit.t;
        ray->Ng.x = hit.Ng.x;
        ray->Ng.y = hit.Ng.y;
        ray->Ng.z = hit.Ng.z;
        ray->u = hit.u;
        ray->v = hit.v;
        return true;
    }

    EmbreeRayHit* ray;
};

X2_HD inline
bool intersectConeSphere(const bool valid_i,
                         const float3& ray_org_in, const float3& ray_dir,
                         const float ray_tnear, const float& ray_tfar,
                         const float4& v0, const float4& v1,
                         const float4& vL, const float4& vR,
                         const RoundLinearCurveEpilog& epilog)
{
    bool valid = valid_i;

    /* move ray origin closer to make calculations numerically stable */
    const float dOdO = sqr(ray_dir);
    const float rcp_dOdO = rcp(dOdO);
    const float3 center = float(0.5f)*(make_float3(v0)+make_float3(v1));
    const float dt = dot(center-ray_org_in,ray_dir)*rcp_dOdO;
    const float3 ray_org = ray_org_in + dt*ray_dir;

    /* intersect with cone from v0 to v1 */
    float t_cone_lower, t_cone_upper;
    ConeGeometryIntersector cone(ray_org, ray_dir, dOdO, rcp_dOdO, v0, v1);
    bool validCone = valid;
    cone.intersectCone(validCone, t_cone_lower, t_cone_upper);

    valid &= (validCone | (cone.g <= 0.0f));  // if cone is entirely in sphere end - check sphere
    if (!valid) {
        return false;
    }

    /* cone hits inside the neighboring capped cones are inside the geometry and thus ignored */
    const ConeGeometry coneL(v0, vL);
    const ConeGeometry coneR(v1, vR);
#if !defined(EMBREE_BACKFACE_CULLING_CURVES)
    const float3 hit_lower = ray_org + t_cone_lower*ray_dir;
    const float3 hit_upper = ray_org + t_cone_upper*ray_dir;
    t_cone_lower = select(!coneL.isInsideCappedCone(validCone, hit_lower) & !coneR.isInsideCappedCone(validCone, hit_lower), t_cone_lower, float(pos_inf));
    t_cone_upper = select(!coneL.isInsideCappedCone(validCone, hit_upper) & !coneR.isInsideCappedCone(validCone, hit_upper), t_cone_upper, float(neg_inf));
#endif

    /* intersect ending sphere */
    float t_sph1_lower, t_sph1_upper;
    float t_sph0_lower = float(pos_inf);
    float t_sph0_upper = float(neg_inf);
    cone.intersectEndSphere(valid, coneR, t_sph1_lower, t_sph1_upper);

    const bool isBeginPoint = valid & (vL.x == float(pos_inf));
    if (isBeginPoint) {
        cone.intersectBeginSphere (isBeginPoint, t_sph0_lower, t_sph0_upper);
    }

    /* CSG union of cone and end sphere */
    float t_sph_lower = fminf(t_sph0_lower, t_sph1_lower);
    float t_cone_sphere_lower = fminf(t_cone_lower, t_sph_lower);
#if !defined (EMBREE_BACKFACE_CULLING_CURVES)
    float t_sph_upper = fmaxf(t_sph0_upper, t_sph1_upper);
    float t_cone_sphere_upper = fmaxf(t_cone_upper, t_sph_upper);

    /* filter out hits that are not in tnear/tfar range */
    const bool valid_lower = valid & ray_tnear <= dt+t_cone_sphere_lower & dt+t_cone_sphere_lower <= ray_tfar & t_cone_sphere_lower != float(pos_inf);
    const bool valid_upper = valid & ray_tnear <= dt+t_cone_sphere_upper & dt+t_cone_sphere_upper <= ray_tfar & t_cone_sphere_upper != float(neg_inf);

    /* check if there is a first hit */
    const bool valid_first = valid_lower | valid_upper;
    if (!valid_first) {
        return false;
    }

    /* construct first hit */
    const float t_first = select(valid_lower, t_cone_sphere_lower, t_cone_sphere_upper);
    const bool cone_hit_first = t_first == t_cone_lower | t_first == t_cone_upper;
    const bool sph0_hit_first = t_first == t_sph0_lower | t_first == t_sph0_upper;
    const float3 Ng_first = select(cone_hit_first, cone.Ng_cone(valid_lower), select(sph0_hit_first, cone.Ng_sphere0(valid_lower), cone.Ng_sphere1(valid_lower)));
    const float u_first  = select(cone_hit_first, cone.u_cone(valid_lower), select(sph0_hit_first, 0.f, 1.f));

    /* invoke intersection filter for first hit */
    RoundLineIntersectorHit hit(u_first,0.f,dt+t_first,Ng_first);
    const bool is_hit_first = epilog(valid_first, hit);

    /* check for possible second hits before potentially accepted hit */
    const float t_second = t_cone_sphere_upper;
    const bool valid_second = valid_lower & valid_upper & (dt+t_cone_sphere_upper <= ray_tfar);
    if (!valid_second) {
        return is_hit_first;
    }

    /* invoke intersection filter for second hit */
    const bool cone_hit_second = t_second == t_cone_lower | t_second == t_cone_upper;
    const bool sph0_hit_second = t_second == t_sph0_lower | t_second == t_sph0_upper;
    const float3 Ng_second = select(cone_hit_second, cone.Ng_cone(false), select(sph0_hit_second, cone.Ng_sphere0(false), cone.Ng_sphere1(false)));
    const float u_second  = select(cone_hit_second, cone.u_cone(false), select(sph0_hit_second, 0.f, 1.f));

    hit = RoundLineIntersectorHit(u_second,0.f,dt+t_second,Ng_second);
    const bool is_hit_second = epilog(valid_second, hit);

    return is_hit_first | is_hit_second;
#else
    /* filter out hits that are not in tnear/tfar range */
    const bool valid_lower = valid & ray_tnear <= dt+t_cone_sphere_lower & dt+t_cone_sphere_lower <= ray_tfar & t_cone_sphere_lower != float(pos_inf);

    /* check if there is a valid hit */
    if (!valid_lower) {
        return false;
    }

    /* construct first hit */
    const bool cone_hit_first = t_cone_sphere_lower == t_cone_lower | t_cone_sphere_lower == t_cone_upper;
    const bool sph0_hit_first = t_cone_sphere_lower == t_sph0_lower | t_cone_sphere_lower == t_sph0_upper;
    const float3 Ng_first = select(cone_hit_first, cone.Ng_cone(valid_lower), select (sph0_hit_first, cone.Ng_sphere0(valid_lower), cone.Ng_sphere1(valid_lower)));
    const float u_first  = select(cone_hit_first, cone.u_cone(valid_lower), select (sph0_hit_first, float(zero), float(one)));

    /* invoke intersection filter for first hit */
    RoundLineIntersectorHit hit(u_first,zero,dt+t_cone_sphere_lower,Ng_first);
    const bool is_hit_first = epilog(valid_lower, hit);

    return is_hit_first;
#endif
}

struct RoundLinearCurveIntersector
{
    X2_HD inline
    bool intersect(const bool valid_i,
                   const EmbreeRayHit& ray,
                   const float4& v0i, const float4& v1i,
                   const float4& vLi, const float4& vRi,
                   const RoundLinearCurveEpilog& epilog)
    {
        return intersectConeSphere(valid_i,ray.org,ray.dir,ray.tnear,ray.tfar,v0i,v1i,vLi,vRi,epilog);
    }
};

// Copyright 2009-2021 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Copyright 2023-2024 DreamWorks Animation LLC
// SPDX-License-Identifier: Apache-2.0

// This is pulled from Embree 4 almost verbatim so we match Embree's round
// bspline curves behavior.  There are things in here that can be simplified
// or cleaned up, but we don't want to do that because we want to remain 1:1 with
// the original Embree code for 100% matching behavior.




class BSplineBasis
{
public:
    static X2_HD inline
    float4 eval(const float u)
    {
        const float t  = u;
        const float s  = 1.0f - u;
        const float n0 = s*s*s;
        const float n1 = (4.0f*(s*s*s)+(t*t*t)) + (12.0f*((s*t)*s) + 6.0f*((t*s)*t));
        const float n2 = (4.0f*(t*t*t)+(s*s*s)) + (12.0f*((t*s)*t) + 6.0f*((s*t)*s));
        const float n3 = t*t*t;
        const float4 n = {n0,n1,n2,n3};
        return (1.0f/6.0f)*n;
    }

    static X2_HD inline
    float4 derivative(const float u)
    {
        const float t  =  u;
        const float s  =  1.0f - u;
        const float n0 = -s*s;
        const float n1 = -t*t - 4.0f*(t*s);
        const float n2 =  s*s + 4.0f*(s*t);
        const float n3 =  t*t;
        const float4 n = {n0,n1,n2,n3};
        return (0.5f)*n;
    }

    static X2_HD inline
    float4 derivative2(const float u)
    {
        const float t  =  u;
        const float s  =  1.0f - u;
        const float n0 = s;
        const float n1 = t - 2.0f*s;
        const float n2 = s - 2.0f*t;
        const float n3 = t;
        const float4 n = {n0,n1,n2,n3};
        return n;
    }
};

struct BSplineCurveT
{
    float4 v0, v1, v2, v3;

    X2_HD inline
    BSplineCurveT(const float4& v0, const float4& v1, const float4& v2, const float4& v3)
        : v0(v0), v1(v1), v2(v2), v3(v3) {}

    X2_HD inline
    BBox bounds() const
    {
        return merge(BBox(v0), BBox(v1), BBox(v2), BBox(v3));
    }

    X2_HD inline float4 center() const
    {
        return 0.25f*(v0+v1+v2+v3);
    }

    X2_HD inline
    float4 eval(const float t) const
    {
        const float4 b = BSplineBasis::eval(t);
        return b.x*v0+b.y*v1+b.z*v2+b.w*v3;
    }

    X2_HD inline
    float4 eval_du(const float t) const
    {
        const float4 b = BSplineBasis::derivative(t);
        return b.x*v0+b.y*v1+b.z*v2+b.w*v3;
    }

    X2_HD inline
    float4 eval_dudu(const float t) const
    {
        const float4 b = BSplineBasis::derivative2(t);
        return b.x*v0+b.y*v1+b.z*v2+b.w*v3;
    }

    X2_HD inline
    void eval(const float t, float4& p, float4& dp) const
    {
        p = eval(t);
        dp = eval_du(t);
    }

    X2_HD inline
    void eval(const float t, float4& p, float4& dp, float4& ddp) const
    {
        p = eval(t);
        dp = eval_du(t);
        ddp = eval_dudu(t);
    }

    X2_HD inline
    BSplineCurveT friend operator -(const BSplineCurveT& a, const float4& b)
    {
        return BSplineCurveT(a.v0-b,a.v1-b,a.v2-b,a.v3-b);
    }
};

// Copyright 2009-2021 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Copyright 2023-2024 DreamWorks Animation LLC
// SPDX-License-Identifier: Apache-2.0

// This is pulled from Embree 4 almost verbatim so we match Embree's round
// bspline curves behavior.  There are things in here that can be simplified
// or cleaned up, but we don't want to do that because we want to remain 1:1 with
// the original Embree code for 100% matching behavior.




static const size_t numBezierSubdivisions = 3;
static const size_t numJacobianIterations = 5;

struct BezierCurveHit
{
    X2_HD inline
    BezierCurveHit() {}

    X2_HD inline
    BezierCurveHit(const float t, const float u, const float4& Ng)
        : t(t), u(u), v(0.0f), Ng(Ng) {}

    X2_HD inline
    BezierCurveHit(const float t, const float u, const float v, const float4& Ng)
        : t(t), u(u), v(v), Ng(Ng) {}

public:
    float t;
    float u;
    float v;
    float4 Ng;
};

struct RoundBezierCurveEpilog
{
    X2_HD inline
    RoundBezierCurveEpilog(EmbreeRayHit* ray) : ray(ray) {}

    X2_HD inline
    bool operator() (BezierCurveHit& hit) const
    {
        ray->tfar = hit.t;
        ray->Ng.x = hit.Ng.x;
        ray->Ng.y = hit.Ng.y;
        ray->Ng.z = hit.Ng.z;
        ray->u = hit.u;
        ray->v = hit.v;
        return true;
    }

    EmbreeRayHit* ray;
};

X2_HD inline
bool intersect_bezier_iterative_jacobian(const EmbreeRayHit& ray,
                                         const float dt,
                                         const BSplineCurveT& curve,
                                         float u,
                                         float t,
                                         const RoundBezierCurveEpilog& epilog)
{
    const float4 org = {0.f, 0.f, 0.f, 0.f};
    const float4 dir = {ray.dir.x, ray.dir.y, ray.dir.z, 0.f}; // does ray.dir need to be float4?
    const float length_ray_dir = length3(dir);

    /* error of curve evaluations is proportional to largest coordinate */
    const BBox box = curve.bounds();
    const float P_err = 16.0f*float(ulp)*reduce_max3(max(abs(box.lower),abs(box.upper)));

    for (size_t i=0; i<numJacobianIterations; i++)
    {
        const float4 Q = dir * t + org;
        //const float3 dQdu = zero;
        const float4 dQdt = dir;
        const float Q_err = 16.0f*float(ulp)*length_ray_dir*t; // works as org=zero here

        float4 P,dPdu,ddPdu; curve.eval(u,P,dPdu,ddPdu);
        //const Vec3fa dPdt = zero;

        const float4 R = Q-P;
        const float len_R = length3(R); //reduce_max(abs(R));
        const float R_err = max(Q_err,P_err);
        const float4 dRdu = /*dQdu*/make_float4(-dPdu.x, -dPdu.y, -dPdu.z, -dPdu.w);
        const float4 dRdt = dQdt;//-dPdt;

        const float4 T = normalize4(dPdu);
        const float4 dTdu = dnormalize(dPdu,ddPdu);
        //const Vec3fa dTdt = zero;
        const float cos_err = P_err/length3(dPdu);

        /* Error estimate for dot(R,T):

           dot(R,T) = cos(R,T) |R| |T|
                    = (cos(R,T) +- cos_error) * (|R| +- |R|_err) * (|T| +- |T|_err)
                    = cos(R,T)*|R|*|T| 
                      +- cos(R,T)*(|R|*|T|_err + |T|*|R|_err)
                      +- cos_error*(|R| + |T|)
                      +- lower order terms
           with cos(R,T) being in [0,1] and |T| = 1 we get:
             dot(R,T)_err = |R|*|T|_err + |R|_err = cos_error*(|R|+1)
        */

        const float f = dot3(R,T);
        const float f_err = len_R*P_err + R_err + cos_err*(1.0f+len_R);
        const float dfdu = dot3(dRdu,T) + dot3(R,dTdu);
        const float dfdt = dot3(dRdt,T);// + dot(R,dTdt);

        const float K = dot3(R,R)-sqr(f);
        const float dKdu = /*2.0f*/(dot3(R,dRdu)-f*dfdu);
        const float dKdt = /*2.0f*/(dot3(R,dRdt)-f*dfdt);
        const float rsqrt_K = rsqrtf(K);

        const float g = sqrt(K)-P.w;
        const float g_err = R_err + f_err + 16.0f*float(ulp)*box.upper.w;
        const float dgdu = /*0.5f*/dKdu*rsqrt_K-dPdu.w;
        const float dgdt = /*0.5f*/dKdt*rsqrt_K;//-dPdt.w;

        const LinearSpace2 J = LinearSpace2(dfdu,dfdt,dgdu,dgdt);
        const float2 dut = rcp(J)*make_float2(f, g);
        const float2 ut = make_float2(u,t) - dut;
        u = ut.x; t = ut.y;

        if (fabsf(f) < f_err && fabsf(g) < g_err)
        {
            t+=dt;
            if (!(ray.tnear <= t && t <= ray.tfar)) return false; // rejects NaNs
            if (!(u >= 0.0f && u <= 1.0f)) return false; // rejects NaNs
            const float4 R = normalize4(Q-P);
            const float4 U = dPdu.w*R+dPdu;
            const float4 V = cross(dPdu,R);
            BezierCurveHit hit(t,u,cross(V,U));
            return epilog(hit);
        }
    }
    return false;
}

X2_HD inline
bool intersect_bezier_recursive_jacobian(const EmbreeRayHit& ray,
                                         const float dt,
                                         const BSplineCurveT& curve,
                                         const RoundBezierCurveEpilog& epilog)
{
    // This is the "scalar" SYCL version of this function

    const float4 org = {0.f, 0.f, 0.f, 0.f};
    const float4 dir = {ray.dir.x, ray.dir.y, ray.dir.z, 0.f}; // does ray.dir need to be float4?
    const unsigned int max_depth = 7;

    bool found = false;

    struct ShortStack
    {
        /* pushes both children */
        X2_HD inline void push() {
          depth++;
        }

        /* pops next node */
        X2_HD inline void pop() {
          short_stack += (1<<(31-depth));
          depth = 31-bsf(short_stack);
        }

        unsigned int depth = 0;
        unsigned int short_stack = 0;
    };

    ShortStack stack;

    do
    {
        const float u0 = (stack.short_stack+0*(1<<(31-stack.depth)))/float(0x80000000);
        const float u1 = (stack.short_stack+1*(1<<(31-stack.depth)))/float(0x80000000);

        /* subdivide bezier curve */
        float4 P0, dP0du; curve.eval(u0,P0,dP0du); dP0du = dP0du * (u1-u0);
        float4 P3, dP3du; curve.eval(u1,P3,dP3du); dP3du = dP3du * (u1-u0);
        const float4 P1 = P0 + dP0du*(1.0f/3.0f);
        const float4 P2 = P3 - dP3du*(1.0f/3.0f);

        /* check if curve is well behaved, by checking deviation of tangents from straight line */
        const float4 W = make_float4(P3-P0,0.0f);
        const float4 dQ0 = abs(3.0f*(P1-P0) - W);
        const float4 dQ1 = abs(3.0f*(P2-P1) - W);
        const float4 dQ2 = abs(3.0f*(P3-P2) - W);
        const float4 max_dQ = max(dQ0,dQ1,dQ2);
        const float m = fmaxf(max_dQ.x,max_dQ.y,max_dQ.z); //,max_dQ.w);
        const float l = length(make_float3(W));
        const bool well_behaved = m < 0.2f*l;

        if (!well_behaved && stack.depth < max_depth) {
            stack.push();
            continue;
        }

        /* calculate bounding cylinders */
        const float rr1 = sqr_point_to_line_distance(make_float3(dP0du),make_float3(P3-P0));
        const float rr2 = sqr_point_to_line_distance(make_float3(dP3du),make_float3(P3-P0));
        const float maxr12 = sqrt(max(rr1,rr2));
        const float one_plus_ulp  = 1.0f+2.0f*float(ulp);
        const float one_minus_ulp = 1.0f-2.0f*float(ulp);
        float r_outer = fmaxf(P0.w,P1.w,P2.w,P3.w)+maxr12;
        float r_inner = fminf(P0.w,P1.w,P2.w,P3.w)-maxr12;
        r_outer = one_plus_ulp*r_outer;
        r_inner = max(0.0f,one_minus_ulp*r_inner);
        const Cylinder cylinder_outer(P0,P3,r_outer);
        const Cylinder cylinder_inner(P0,P3,r_inner);

        /* intersect with outer cylinder */
        BBox1 tc_outer; float u_outer0; float4 Ng_outer0; float u_outer1; float4 Ng_outer1;
        if (!cylinder_outer.intersect(org,dir,tc_outer,u_outer0,Ng_outer0,u_outer1,Ng_outer1))
        {
            stack.pop();
            continue;
        }

        /* intersect with cap-planes */
        BBox1 tp(ray.tnear-dt,ray.tfar-dt);
        tp = intersect(tp,tc_outer);
        BBox1 h0 = HalfPlane(remove_w(P0),remove_w(dP0du)).intersect(org,dir);
        tp = intersect(tp,h0);
        BBox1 h1 = HalfPlane(remove_w(P3),-remove_w(dP3du)).intersect(org,dir);
        tp = intersect(tp,h1);
        if (tp.lower > tp.upper)
        {
            stack.pop();
            continue;
        }

        bool valid = true;

        /* clamp and correct u parameter */
        u_outer0 = clamp(u_outer0,0.0f,1.0f);
        u_outer1 = clamp(u_outer1,0.0f,1.0f);
        u_outer0 = lerpf(u0,u1,u_outer0);
        u_outer1 = lerpf(u0,u1,u_outer1);

        /* intersect with inner cylinder */
        BBox1 tc_inner;
        float u_inner0 = 0.f; float4 Ng_inner0 = make_float4_zero();
        float u_inner1 = 0.f; float4 Ng_inner1 = make_float4_zero();
        const bool valid_inner = cylinder_inner.intersect(org,dir,tc_inner,u_inner0,Ng_inner0,u_inner1,Ng_inner1);

        /* subtract the inner interval from the current hit interval */
        BBox1 tp0, tp1;
        subtract(tp,tc_inner,tp0,tp1);
        bool valid0 = valid & (tp0.lower <= tp0.upper);
        bool valid1 = valid & (tp1.lower <= tp1.upper);
        if (!(valid0 | valid1))
        {
            stack.pop();
            continue;
        }

        /* at the unstable area we subdivide deeper */
        const bool unstable0 = valid0 && ((!valid_inner) | (abs(dot3(make_float4(ray.dir),Ng_inner0)) < 0.3f));
        const bool unstable1 = valid1 && ((!valid_inner) | (abs(dot3(make_float4(ray.dir),Ng_inner1)) < 0.3f));
    
        if ((unstable0 | unstable1) && (stack.depth < max_depth)) {
            stack.push();
            continue;
        }

        if (valid0)
            found |= intersect_bezier_iterative_jacobian(ray,dt,curve,u_outer0,tp0.lower,epilog);
          
        /* the far hit cannot be closer, thus skip if we hit entry already */
        valid1 &= tp1.lower+dt <= ray.tfar;
        
        /* iterate over second hit */
        if (valid1)
            found |= intersect_bezier_iterative_jacobian(ray,dt,curve,u_outer1,tp1.upper,epilog);

        stack.pop();
        
    } while (stack.short_stack != 0x80000000);

    return found;
}

struct SweepCurveIntersector
{
    X2_HD inline
    bool intersect(const EmbreeRayHit& ray,
                   const float4& v0, const float4& v1,
                   const float4& v2, const float4& v3,
                   const RoundBezierCurveEpilog& epilog)
    {
        /* move ray closer to make intersection stable */
        BSplineCurveT curve0(v0,v1,v2,v3);
        // curve0 = enlargeRadiusToMinWidth(context,geom,ray.org,curve0); // need this?
        const float dt = dot(make_float3(curve0.center())-ray.org,ray.dir)*rcp(dot(ray.dir,ray.dir));
        const float4 ref = make_float4(ray.dir * dt + ray.org, 0.0f);
        const BSplineCurveT curve1 = curve0-ref;
        return intersect_bezier_recursive_jacobian(ray,dt,curve1,epilog);
    }
};
