// Private XPU2 shared CPU/CUDA sampling. Address layout v1, not MoonRay's RNG.
// Philox4x32-10 algorithm: D. E. Shaw Research Random123 (see RANDOM123_LICENSE.txt).
#pragma once
#if defined(__CUDACC__)
#define X2_HD __host__ __device__
#else
#define X2_HD
#endif
// A helper too big to copy into each of its callers: on the GPU one call (shade_math.h says why).
#ifndef X2_CALL
#if defined(__CUDACC__)
#define X2_CALL __host__ __device__ __noinline__ inline
#else
#define X2_CALL inline
#endif
#endif
// One set of elementary functions for both lanes. The CUDA lane's expf, logf, powf, sinf, cosf, tanf, atan2f, asinf,
// acosf, erff and cbrtf (libdevice's) and the host's (the C runtime's) are different approximations: the same argument
// gave the lanes results an ulp or more apart, and as either lane may render a sample (the work split changes from run
// to run) a picture rendered by both lanes differed from run to run. These take their place in every XPU2 namespace
// (an unqualified call inside namespace xpu2 finds them before the global ones), each a fixed sequence of IEEE single and
// double operations, rounded alike on the host (built without contraction) and on the card (built with --fmad=false).
// The single precision kernels are Cephes's (Stephen L. Moshier, Cephes Math Library 2.2, sinf.c, tanf.c, atanf.c,
// asinf.c, expf.c, logf.c: free to use, see THIRD_PARTY_NOTICES.md); powf and cbrtf are worked out in float-float
// (pairs of floats, below), erff in double.
// Each is X2_CALL: one copy in each GPU module, not one at every call site (about 230 of them, many in inline helpers,
// made the path tracer's module 60% larger, and the whole compile take twice the memory).
#if !defined(__CUDACC_RTC__)
#include <math.h>
#endif
namespace xpu2 {
namespace x2math {
X2_HD inline unsigned bitsOf(float f) {
#if defined(__CUDACC__)
    return __float_as_uint(f);
#else
    unsigned u;
    __builtin_memcpy(&u, &f, 4);
    return u;
#endif
}
X2_HD inline float fromBits(unsigned u) {
#if defined(__CUDACC__)
    return __uint_as_float(u);
#else
    float f;
    __builtin_memcpy(&f, &u, 4);
    return f;
#endif
}
X2_HD inline unsigned long long bitsOf(double f) {
#if defined(__CUDACC__)
    return (unsigned long long)__double_as_longlong(f);
#else
    unsigned long long u;
    __builtin_memcpy(&u, &f, 8);
    return u;
#endif
}
X2_HD inline double fromBits(unsigned long long u) {
#if defined(__CUDACC__)
    return __longlong_as_double((long long)u);
#else
    double f;
    __builtin_memcpy(&f, &u, 8);
    return f;
#endif
}
X2_HD inline float nanf_() { return fromBits(0x7fc00000u); }
X2_HD inline float inff_() { return fromBits(0x7f800000u); }
X2_HD inline bool isnan_(float x) { return !(x == x); }
// 2^n, n in [-126, 127].
X2_HD inline float pow2(int n) { return fromBits(unsigned(n + 127) << 23); }
// p 2^n for p near one, n in [-150, 128]: in steps that stay in range.
X2_HD inline float scaled(float p, int n) {
    if (n > 127) return p * pow2(127) * pow2(n - 127);
    if (n < -126) return p * pow2(n + 100) * pow2(-100);
    return p * pow2(n);
}
// The double helpers: log of a positive finite double, and 2^t.
X2_HD inline double logPositive(double x) {
    unsigned long long u = bitsOf(x);
    int e = int((u >> 52) & 0x7ff);
    if (e == 0) {  // subnormal
        x *= 18014398509481984.0;  // 2^54
        u = bitsOf(x);
        e = int((u >> 52) & 0x7ff) - 54;
    }
    e -= 1023;
    double m = fromBits((u & 0x000fffffffffffffull) | 0x3ff0000000000000ull);  // [1, 2)
    if (m > 1.4142135623730951) {
        m *= 0.5;
        ++e;
    }
    // log m = 2 atanh(s), s = (m - 1) / (m + 1), |s| < 0.1716.
    const double s = (m - 1.0) / (m + 1.0), s2 = s * s;
    double sum = 1.0 / 25.0;
    for (int k = 11; k >= 0; --k) sum = sum * s2 + 1.0 / double(2 * k + 1);
    return 2.0 * s * sum + double(e) * 0.69314718055994530942;
}
X2_HD inline double exp2Of(double t) {
    if (!(t == t)) return t;
    if (t > 1100.0) return fromBits(0x7ff0000000000000ull);
    if (t < -1100.0) return 0.0;
    const double n = floor(t + 0.5);
    const double f = (t - n) * 0.69314718055994530942;  // |f| <= 0.3466: e^f by its series to the 13th power
    double r = 1.0 / 6227020800.0;
    r = r * f + 1.0 / 479001600.0;
    r = r * f + 1.0 / 39916800.0;
    r = r * f + 1.0 / 3628800.0;
    r = r * f + 1.0 / 362880.0;
    r = r * f + 1.0 / 40320.0;
    r = r * f + 1.0 / 5040.0;
    r = r * f + 1.0 / 720.0;
    r = r * f + 1.0 / 120.0;
    r = r * f + 1.0 / 24.0;
    r = r * f + 1.0 / 6.0;
    r = r * f + 0.5;
    r = r * f + 1.0;
    r = r * f + 1.0;
    int ni = int(n);
    // r 2^n, in steps that stay in range.
    while (ni > 1000) {
        r *= fromBits(0x7e70000000000000ull);  // 2^1000
        ni -= 1000;
    }
    while (ni < -1000) {
        r *= fromBits(0x0170000000000000ull);  // 2^-1000
        ni += 1000;
    }
    return r * fromBits((unsigned long long)(ni + 1023) << 52);
}
// Float-float: a value as the unevaluated sum hi + lo of two floats, |lo| <= ulp(hi) / 2, from error-free transformations
// (T. J. Dekker, "A floating-point technique for extending the available precision", 1971): only IEEE single additions,
// subtractions and products, each rounded once (no fused multiply-add on either lane), so both lanes get the same bits.
// About 44 bits of precision, without the card's slow double instructions.
struct FF {
    float hi, lo;
};
X2_HD inline FF twoSum(float a, float b) {  // a + b exactly
    const float s = a + b, bb = s - a;
    return {s, (a - (s - bb)) + (b - bb)};
}
X2_HD inline FF fastTwoSum(float a, float b) {  // a + b exactly, |a| >= |b| (or a zero)
    const float s = a + b;
    return {s, b - (s - a)};
}
X2_HD inline FF twoProduct(float a, float b) {  // a b exactly, |a|, |b| < 2^115
    const float p = a * b, ca = 4097.0f * a, cb = 4097.0f * b;  // Veltkamp's split into 12-bit halves
    const float ah = ca - (ca - a), al = a - ah, bh = cb - (cb - b), bl = b - bh;
    return {p, (((ah * bh - p) + ah * bl) + al * bh) + al * bl};
}
X2_HD inline FF ffMul(FF a, FF b) {
    FF p = twoProduct(a.hi, b.hi);
    p.lo += a.hi * b.lo + a.lo * b.hi;
    return fastTwoSum(p.hi, p.lo);
}
X2_HD inline FF ffMul(FF a, float b) {
    FF p = twoProduct(a.hi, b);
    p.lo += a.lo * b;
    return fastTwoSum(p.hi, p.lo);
}
X2_HD inline FF ffAdd(FF a, FF b) {  // a and b of one sign, or one at most half the other: no cancellation to speak of
    FF s = twoSum(a.hi, b.hi);
    s.lo += a.lo + b.lo;
    return fastTwoSum(s.hi, s.lo);
}
// log2 of a positive finite float, in float-float (relative error below 2^-43).
X2_HD inline FF log2Of(float x) {
    int e = 0;
    if (x < 1.17549435e-38f) {  // subnormal
        x *= 8388608.0f;
        e = -23;
    }
    const unsigned u = bitsOf(x);
    e += int((u >> 23) & 0xff) - 127;
    float m = fromBits((u & 0x007fffffu) | 0x3f800000u);  // [1, 2)
    if (m > 1.41421356f) {
        m *= 0.5f;
        ++e;
    }
    // log2 m = 2 / ln2 atanh(s) = s (d0 + d1 s^2 + d2 s^4 + ...), s = (m - 1) / (m + 1), |s| < 0.1716, d_k = 2 / ((2k + 1) ln2).
    const float a = m - 1.0f;  // exact
    const FF b = twoSum(m, 1.0f);
    const float sh = a / b.hi;
    const FF q = twoProduct(sh, b.hi);
    const FF s = fastTwoSum(sh, (((a - q.hi) - q.lo) - sh * b.lo) / b.hi);  // a - q.hi is exact
    const FF s2 = ffMul(s, s);
    // d3 s^6 on is below 2^-18 of the sum: single precision does for it.
    const float z = s2.hi;
    float t = 0x1.3703c2p-3f;
    t = t * z + 0x1.5b9acap-3f;
    t = t * z + 0x1.89f3b2p-3f;
    t = t * z + 0x1.c68f56p-3f;
    t = t * z + 0x1.0c9a84p-2f;
    t = t * z + 0x1.484b14p-2f;
    t = t * z + 0x1.a61762p-2f;
    FF r = ffAdd(FF{0x1.2776c6p-1f, -0x1.e20c8p-26f}, ffMul(s2, t));
    r = ffAdd(FF{0x1.ec709ep-1f, -0x1.e2fe02p-28f}, ffMul(s2, r));
    r = ffAdd(FF{0x1.715476p+1f, 0x1.4ae0cp-25f}, ffMul(s2, r));
    r = ffMul(s, r);
    // e + log2 m: twoSum exact, then the low part.
    FF l = twoSum(float(e), r.hi);
    l.lo += r.lo;
    return fastTwoSum(l.hi, l.lo);
}
// v + d rounded to odd (Boldo and Melquiond): v, d from twoSum. A sum rounded to odd, then to nearest with two bits or
// more fewer, rounds as the exact sum would: a tie of the rounded parts (1 - 2^-25 of 1 - 2^-25 - 2^-51, (1 - 2^-24)^0.5)
// is no tie of the whole.
X2_HD inline float toOdd(float v, float d) {
    if (d == 0.0f || v == 0.0f || (bitsOf(v) & 1u)) return v;
    return fromBits((d > 0.0f) == (v > 0.0f) ? bitsOf(v) + 1u : bitsOf(v) - 1u);
}
// 2^f - 1 for a float-float |f| <= 0.5 (a little more is fine), in float-float (relative error below 2^-42 of 2^f).
X2_HD inline FF exp2Minus1(FF f) {
    // sum c_k f^k, c_k = ln2^k / k!: c6 f^6 on is below 2^-18 of the sum, in single precision.
    const float z = f.hi;
    float t = 0x1.e8cac8p-32f;
    t = t * z + 0x1.e4cf52p-28f;
    t = t * z + 0x1.b5253ep-24f;
    t = t * z + 0x1.62c022p-20f;
    t = t * z + 0x1.ffcbfcp-17f;
    t = t * z + 0x1.430912p-13f;
    FF r = ffAdd(FF{0x1.5d87fep-10f, 0x1.e299ccp-36f}, ffMul(f, t));
    r = ffAdd(FF{0x1.3b2ab6p-7f, 0x1.f749cep-32f}, ffMul(f, r));
    r = ffAdd(FF{0x1.c6b08ep-5f, -0x1.1f6be8p-30f}, ffMul(f, r));
    r = ffAdd(FF{0x1.ebfbe0p-3f, -0x1.f4e9c6p-33f}, ffMul(f, r));
    r = ffAdd(FF{0x1.62e430p-1f, -0x1.05c61p-29f}, ffMul(f, r));
    return ffMul(f, r);
}
}  // namespace x2math

X2_CALL float expf(float x) {
    using namespace x2math;
    if (isnan_(x)) return x + x;
    if (x > 88.72283172607421875f) return inff_();
    if (x < -103.97208404541015625f) return 0.0f;
    const float fn = floorf(x * 1.44269504088896341f + 0.5f);
    float r = x - fn * 0.693359375f;
    r = r - fn * -2.12194440e-4f;
    const float z = r * r;
    const float p = (((((1.9875691500E-4f * r + 1.3981999507E-3f) * r + 8.3334519073E-3f) * r + 4.1665795894E-2f) * r + 1.6666665459E-1f) * r +
                     5.0000001201E-1f) * z + r + 1.0f;
    return scaled(p, int(fn));
}
X2_CALL float logf(float x) {
    using namespace x2math;
    if (isnan_(x)) return x + x;
    if (x < 0.0f) return nanf_();
    if (x == 0.0f) return -inff_();
    if (x == inff_()) return x;
    int e = 0;
    if (x < 1.17549435e-38f) {
        x *= 8388608.0f;
        e = -23;
    }
    const unsigned u = bitsOf(x);
    e += int((u >> 23) & 0xff) - 126;
    x = fromBits((u & 0x807fffffu) | 0x3f000000u);  // [0.5, 1)
    if (x < 0.707106781186547524f) {
        e -= 1;
        x = x + x - 1.0f;
    } else {
        x = x - 1.0f;
    }
    float z = x * x;
    float y = ((((((((7.0376836292E-2f * x - 1.1514610310E-1f) * x + 1.1676998740E-1f) * x - 1.2420140846E-1f) * x + 1.4249322787E-1f) * x -
                   1.6668057665E-1f) * x + 2.0000714765E-1f) * x - 2.4999993993E-1f) * x + 3.3333331174E-1f) * x * z;
    const float fe = float(e);
    y += -2.12194440e-4f * fe;
    y += -0.5f * z;
    z = x + y;
    z += 0.693359375f * fe;
    return z;
}
namespace x2math {
// Cephes's octant reduction for sinf, cosf and tanf: x >= 0, finite; the octant j (even) and the reduced argument.
X2_HD inline float octant(float x, int& j) {
    if (x > 8192.0f) x = float(fmod(double(x), 6.283185307179586476925));  // beyond Cephes's range: a whole turn off, exactly
    j = int(x * 1.27323954473516f);
    float y = float(j);
    if (j & 1) {
        j += 1;
        y += 1.0f;
    }
    return ((x - y * 0.78515625f) - y * 2.4187564849853515625e-4f) - y * 3.77489497744594108e-8f;
}
X2_HD inline float sinPoly(float x, float z) { return ((-1.9515295891E-4f * z + 8.3321608736E-3f) * z - 1.6666654611E-1f) * z * x + x; }
X2_HD inline float cosPoly(float z) {
    float y = ((2.443315711809948E-005f * z - 1.388731625493765E-003f) * z + 4.166664568298827E-002f) * z * z;
    y -= 0.5f * z;
    return y + 1.0f;
}
}  // namespace x2math
X2_CALL float sinf(float xx) {
    using namespace x2math;
    if (!(xx - xx == 0.0f)) return xx - xx;  // NaN, infinity
    bool negative = xx < 0.0f;
    int j;
    const float x = octant(negative ? -xx : xx, j);
    j &= 7;
    if (j > 3) {
        negative = !negative;
        j -= 4;
    }
    const float z = x * x;
    const float y = (j == 1 || j == 2) ? cosPoly(z) : sinPoly(x, z);
    return negative ? -y : y;
}
X2_CALL float cosf(float xx) {
    using namespace x2math;
    if (!(xx - xx == 0.0f)) return xx - xx;
    bool negative = false;
    int j;
    const float x = octant(xx < 0.0f ? -xx : xx, j);
    j &= 7;
    if (j > 3) {
        j -= 4;
        negative = !negative;
    }
    if (j > 1) negative = !negative;
    const float z = x * x;
    const float y = (j == 1 || j == 2) ? sinPoly(x, z) : cosPoly(z);
    return negative ? -y : y;
}
X2_HD inline void sincosf(float x, float* s, float* c) {
    *s = sinf(x);
    *c = cosf(x);
}
X2_CALL float tanf(float xx) {
    using namespace x2math;
    if (!(xx - xx == 0.0f)) return xx - xx;
    const bool negative = xx < 0.0f;
    const float x = negative ? -xx : xx;
    int j;
    const float z = octant(x, j);
    const float zz = z * z;
    float y = x > 1.0e-4f ? ((((((9.38540185543E-3f * zz + 3.11992232697E-3f) * zz + 2.44301354525E-2f) * zz + 5.34112807005E-2f) * zz +
                               1.33387994085E-1f) * zz + 3.33331568548E-1f) * zz * z + z)
                          : z;
    if (j & 2) y = -1.0f / y;
    return negative ? -y : y;
}
X2_CALL float atanf(float xx) {
    if (!(xx == xx)) return xx + xx;
    const bool negative = xx < 0.0f;
    float x = negative ? -xx : xx, y;
    if (x > 2.414213562373095f) {
        y = 1.5707963267948966192f;
        x = -(1.0f / x);
    } else if (x > 0.4142135623730950f) {
        y = 0.7853981633974483096f;
        x = (x - 1.0f) / (x + 1.0f);
    } else {
        y = 0.0f;
    }
    const float z = x * x;
    y += (((8.05374449538e-2f * z - 1.38776856032E-1f) * z + 1.99777106478E-1f) * z - 3.33329491539E-1f) * z * x + x;
    return negative ? -y : y;
}
X2_CALL float atan2f(float y, float x) {
    using namespace x2math;
    if (isnan_(x) || isnan_(y)) return x + y;
    const float pi = 3.14159265358979323846f, halfPi = 1.5707963267948966192f;
    const bool yNegative = (bitsOf(y) >> 31) != 0, xNegative = (bitsOf(x) >> 31) != 0;
    if (y == 0.0f) return xNegative ? (yNegative ? -pi : pi) : y;  // the sign of zero as C's atan2 keeps it
    if (x == 0.0f) return yNegative ? -halfPi : halfPi;
    const bool xInf = x == inff_() || x == -inff_(), yInf = y == inff_() || y == -inff_();
    if (xInf && yInf) {
        const float q = xNegative ? 2.35619449019234492885f : 0.78539816339744830962f;
        return yNegative ? -q : q;
    }
    if (xInf) return xNegative ? (yNegative ? -pi : pi) : (yNegative ? -0.0f : 0.0f);
    if (yInf) return yNegative ? -halfPi : halfPi;
    const float w = x < 0.0f ? (yNegative ? -pi : pi) : 0.0f;
    return w + atanf(y / x);
}
X2_CALL float asinf(float xx) {
    using namespace x2math;
    if (isnan_(xx)) return xx + xx;
    const bool negative = xx < 0.0f;
    const float a = negative ? -xx : xx;
    if (a > 1.0f) return nanf_();
    float z;
    if (a < 1.0e-4f) {
        z = a;
    } else {
        float x;
        bool flag;
        if (a > 0.5f) {
            z = 0.5f * (1.0f - a);
            x = sqrtf(z);
            flag = true;
        } else {
            x = a;
            z = x * x;
            flag = false;
        }
        z = ((((4.2163199048E-2f * z + 2.4181311049E-2f) * z + 4.5470025998E-2f) * z + 7.4953002686E-2f) * z + 1.6666752422E-1f) * z * x + x;
        if (flag) {
            z = z + z;
            z = 1.5707963267948966192f - z;
        }
    }
    return negative ? -z : z;
}
X2_CALL float acosf(float x) {
    using namespace x2math;
    if (isnan_(x)) return x + x;
    if (x < -1.0f || x > 1.0f) return nanf_();
    if (x < -0.5f) return 3.14159265358979323846f - 2.0f * asinf(sqrtf(0.5f * (1.0f + x)));
    if (x > 0.5f) return 2.0f * asinf(sqrtf(0.5f * (1.0f - x)));
    return 1.5707963267948966192f - asinf(x);
}
X2_CALL float powf(float x, float y) {
    using namespace x2math;
    if (y == 0.0f || x == 1.0f) return 1.0f;
    if (isnan_(x) || isnan_(y)) return x + y;
    const float ay = y < 0.0f ? -y : y;
    const bool yInteger = ay >= 16777216.0f || floorf(ay) == ay, yOdd = yInteger && ay < 16777216.0f && fmodf(ay, 2.0f) == 1.0f;
    const bool xNegative = (bitsOf(x) >> 31) != 0;
    const float ax = xNegative ? -x : x;
    if (ay == inff_()) {
        if (ax == 1.0f) return 1.0f;
        return (ax < 1.0f) == (y > 0.0f) ? 0.0f : inff_();
    }
    if (ax == 0.0f || ax == inff_()) {
        const bool big = (ax == 0.0f) == (y < 0.0f);  // 0^-y and inf^y are infinite
        const float r = big ? inff_() : 0.0f;
        return xNegative && yOdd ? -r : r;
    }
    if (xNegative && !yInteger) return nanf_();
    // 2^(y log2 x), in float-float: within about 2^-38 of x^y, rounded once from the exact sum of its parts, so the
    // correctly rounded result but in about one case in a million (the double version's, before, likewise).
    const FF l = log2Of(ax);
    const float rough = y * l.hi;
    float r;
    if (l.hi == 0.0f) {  // x = -1 (and |y| even, or as large as 2^24)
        r = 1.0f;
    } else if (rough > 160.0f) {
        r = inff_();
    } else if (rough < -160.0f) {
        r = 0.0f;
    } else {
        const FF t = ffMul(l, y);  // |y| < 2^31 here: |l| >= 2^-24 for any x but +-1
        const float n = floorf(t.hi + 0.5f);
        const FF q = exp2Minus1(twoSum(t.hi - n, t.lo));  // t.hi - n is exact
        // 1 + q = s.hi + w.hi + w.lo exactly; w rounded to odd, then the sum to nearest: correct rounding of 1 + q.
        const FF s = twoSum(1.0f, q.hi), w = twoSum(s.lo, q.lo);
        const FF p = twoSum(s.hi, toOdd(w.hi, w.lo));
        // Scaled by 2^n: exact for a normal result (an overflow is infinity). A subnormal one: p.hi + p.lo rounded once
        // to the subnormals' grid (2^-149), in units of it (a, b exactly), half to even, not p.hi rounded again.
        const int ni = int(n);
        if (ni < -126 || (ni == -126 && p.hi < 1.0f)) {
            const float a = scaled(p.hi, ni + 149), b = scaled(p.lo, ni + 149), whole = floorf(a), part = a - whole;
            const bool up = part > 0.5f || (part == 0.5f && (b > 0.0f || (b == 0.0f && fmodf(whole, 2.0f) == 1.0f)));
            r = scaled(up ? whole + 1.0f : whole, -149);
        } else {
            r = scaled(p.hi, ni);
        }
    }
    return xNegative && yOdd ? -r : r;
}
X2_CALL double pow(double x, double y) {  // a positive finite x (MoonRay's cube roots before: shade_mapnodes_more.h has cbrtf)
    using namespace x2math;
    if (y == 0.0 || x == 1.0) return 1.0;
    if (!(x > 0.0) || !(x - x == 0.0) || !(y - y == 0.0)) return fromBits(0x7ff8000000000000ull);
    return exp2Of(y * (logPositive(x) * 1.44269504088896340736));
}
// The texture filter's ellipse (texture_core.h): sqrt(x^2 + y^2) without overflow, alike on both lanes.
X2_CALL double hypot(double x, double y) {
    double a = x < 0.0 ? -x : x, b = y < 0.0 ? -y : y;
    const double inf = x2math::fromBits(0x7ff0000000000000ull);
    if (a == inf || b == inf) return inf;
    if (!(a == a) || !(b == b)) return a + b;
    if (a < b) {
        const double t = a;
        a = b;
        b = t;
    }
    if (a == 0.0) return 0.0;
    const double r = b / a;
    return a * sqrt(1.0 + r * r);
}
// The curves' (curve_embree.h): the card's own rsqrtf is an approximation; the host's is 1 / sqrtf.
X2_HD inline float rsqrtf(float x) { return 1.0f / sqrtf(x); }
X2_CALL float erff(float x) {
    if (!(x == x)) return x + x;
    const double a = x < 0.0f ? -double(x) : double(x);
    if (a >= 4.0) return x < 0.0f ? -1.0f : 1.0f;
    // 2/sqrt(pi) sum (-1)^n a^(2n+1) / (n! (2n + 1)), until the terms no longer count.
    const double a2 = a * a;
    double term = a, sum = a;
    for (int n = 1; n < 80; ++n) {
        term *= -a2 / double(n);
        const double add = term / double(2 * n + 1);
        sum += add;
        if ((add < 0.0 ? -add : add) < 1e-17 * sum) break;
    }
    const float r = float(sum * 1.12837916709551257390);
    return x < 0.0f ? -r : r;
}
X2_CALL float cbrtf(float x) {
    using namespace x2math;
    if (!(x - x == 0.0f) || x == 0.0f) return x + x == x ? x : x + x;  // zero and infinity themselves, NaN
    float a = x < 0.0f ? -x : x;
    int k = 0;
    if (a < 1.17549435e-38f) {  // subnormal: a 2^24, its root 2^8
        a *= 16777216.0f;
        k = -8;
    }
    // a = b 2^(3q), b in [1, 8): the root of b, times 2^q.
    const unsigned u = bitsOf(a);
    const int e = int(u >> 23) - 127, q = (e >= 0 ? e : e - 2) / 3;
    const float b = fromBits((u & 0x007fffffu) | (unsigned(e - 3 * q + 127) << 23));
    // A first guess from the exponent (within 4%), Newton's steps in single precision (to an ulp or two), then one in
    // float-float: b - y^3 worked out to about 2^-46 (y^2 exactly, y^3 nearly), so y + its correction rounds as the root.
    float y = fromBits(bitsOf(b) / 3u + 0x2a5137a0u);
    for (int i = 0; i < 3; ++i) y = y - (y * y * y - b) / (3.0f * y * y);
    const FF y3 = ffMul(twoProduct(y, y), y);
    const float residue = (b - y3.hi) - y3.lo;  // b - y3.hi is exact
    const float r = (y + residue / (3.0f * y * y)) * pow2(q + k);  // q + k in [-50, 42]: exact
    return x < 0.0f ? -r : r;
}
}  // namespace xpu2
namespace xpu2 { namespace interactive { namespace sample {
using U32=unsigned int;
using U64=unsigned long long;
static_assert(sizeof(U32)==4 && sizeof(U64)==8,"Sampling word width");
struct Words { U32 v[4]; };
struct Key { U32 a,b; };
X2_HD inline Words philox(Words c,Key k) {
    for(int round=0;round<10;++round) {
        const U64 a=U64(c.v[0])*0xd2511f53u, b=U64(c.v[2])*0xcd9e8d57u;
        c={{U32(b>>32)^c.v[1]^k.a,U32(b),U32(a>>32)^c.v[3]^k.b,U32(a)}};
        k.a+=0x9e3779b9u;k.b+=0xbb67ae85u;
    }
    return c;
}
// Stream is supplied by scene/frame seed policy, not worker/device identity.
// Branch IDs must be deterministic tree addresses, never queue/pop order.
// 32-bit pixel, 64-bit sample, 32-bit dimension, 64-bit branch and stream.
struct Identity { U32 pixel; U64 index,stream,branch; };
X2_HD inline Key key(const Identity& id) {
    // A bijection of branch ID for a fixed stream. Not a collision-free promise
    // across independently keyed frames, nor a replacement for RNG quality tests.
    U64 k=id.stream ^ (id.branch*0x9e3779b97f4a7c15ull);
    return {U32(k),U32(k>>32)};
}
X2_HD inline Words block(const Identity& id,U32 dimensionGroup) {
    return philox({{id.pixel,U32(id.index),U32(id.index>>32),dimensionGroup}},key(id));
}
X2_HD inline U32 word(const Identity& id,U32 dimension) {
    return block(id,dimension>>2).v[dimension&3];
}
// Every conversion is exact: 24-bit integer times a power of two, in [0,1).
X2_HD inline float unit(U32 bits) { return float(bits>>8)*0x1p-24f; }

// Private sampling policy v3: Owen-scrambled Sobol net (owenScramble, below).
// Camera is dimensions 0/1; first diffuse direction is dimensions 2/3.
// Later bounces retain Philox. The scramble is keyed by pixel, frame, branch and
// high sample-index bits; work order, device and target spp never enter it.
// Every coordinate is uniform on the same 24-bit grid as Philox. The scramble
// preserves the net's stratification (v2 was a digital shift: see owenScramble).
// Direction numbers are generated by the documented polynomial recurrence,
// not copied from an external table. Plain Philox remains policy 0 for ablation.
// One immutable direction table on the GPU, rather than a local copy per call.
#if defined(__CUDACC__)
#define X2_SOBOL_STORAGE static __device__ __constant__ const
#else
#define X2_SOBOL_STORAGE inline constexpr
#endif
// Policy bit 4 (the asynchronous path tracer): its first-hit light samples are
// dimensions 18/19, Sobol dimensions 4/5 (Joe-Kuo dimensions 5 and 6), so they
// are stratified apart from the BSDF samples rather than coupled to them.
// Policy bit 8 (the path tracer's subsurface scattering at its first hit, which MoonRay draws from one sequence a
// pixel): dimensions 20 to 27, Sobol dimensions 6 to 13 (Joe-Kuo 7 to 14): 20/21 the local profile samples, 22/23
// their exits' light samples, 24/25 the forward scattering samples, 26/27 the exits' Lambertian samples.
// The camera's lens (policy bit 1, with the pixel's): dimensions 2/3, Sobol dimensions 0 and 1 in a sample order of
// their own (samplingWord), stratified on their own as MoonRay's partitioned lens samples, not with the pixel position.
// The shutter time (policy bit 1, with motion blur): dimension 4, Sobol dimension 0 in an order of its own likewise.
// (Sobol dimensions 14 to 16 of the table served them before, drawn with the pixel position's order.)
X2_SOBOL_STORAGE U32 directions[17][32]={
    {0x80000000u, 0x40000000u, 0x20000000u, 0x10000000u, 0x08000000u, 0x04000000u, 0x02000000u, 0x01000000u, 0x00800000u, 0x00400000u, 0x00200000u, 0x00100000u, 0x00080000u, 0x00040000u, 0x00020000u, 0x00010000u, 0x00008000u, 0x00004000u, 0x00002000u, 0x00001000u, 0x00000800u, 0x00000400u, 0x00000200u, 0x00000100u, 0x00000080u, 0x00000040u, 0x00000020u, 0x00000010u, 0x00000008u, 0x00000004u, 0x00000002u, 0x00000001u},
    {0x80000000u, 0xc0000000u, 0xa0000000u, 0xf0000000u, 0x88000000u, 0xcc000000u, 0xaa000000u, 0xff000000u, 0x80800000u, 0xc0c00000u, 0xa0a00000u, 0xf0f00000u, 0x88880000u, 0xcccc0000u, 0xaaaa0000u, 0xffff0000u, 0x80008000u, 0xc000c000u, 0xa000a000u, 0xf000f000u, 0x88008800u, 0xcc00cc00u, 0xaa00aa00u, 0xff00ff00u, 0x80808080u, 0xc0c0c0c0u, 0xa0a0a0a0u, 0xf0f0f0f0u, 0x88888888u, 0xccccccccu, 0xaaaaaaaau, 0xffffffffu},
    {0x80000000u, 0xc0000000u, 0x60000000u, 0x90000000u, 0xe8000000u, 0x5c000000u, 0x8e000000u, 0xc5000000u, 0x68800000u, 0x9cc00000u, 0xee600000u, 0x55900000u, 0x80680000u, 0xc09c0000u, 0x60ee0000u, 0x90550000u, 0xe8808000u, 0x5cc0c000u, 0x8e606000u, 0xc5909000u, 0x6868e800u, 0x9c9c5c00u, 0xeeee8e00u, 0x5555c500u, 0x8000e880u, 0xc0005cc0u, 0x60008e60u, 0x9000c590u, 0xe8006868u, 0x5c009c9cu, 0x8e00eeeeu, 0xc5005555u},
    {0x80000000u, 0xc0000000u, 0x20000000u, 0x50000000u, 0xf8000000u, 0x74000000u, 0xa2000000u, 0x93000000u, 0xd8800000u, 0x25400000u, 0x59e00000u, 0xe6d00000u, 0x78080000u, 0xb40c0000u, 0x82020000u, 0xc3050000u, 0x208f8000u, 0x51474000u, 0xfbea2000u, 0x75d93000u, 0xa0858800u, 0x914e5400u, 0xdbe79e00u, 0x25db6d00u, 0x58800080u, 0xe54000c0u, 0x79e00020u, 0xb6d00050u, 0x800800f8u, 0xc00c0074u, 0x200200a2u, 0x50050093u},
    {0x80000000u, 0x40000000u, 0x20000000u, 0xb0000000u, 0xf8000000u, 0xdc000000u, 0x7a000000u, 0x9d000000u, 0x5a800000u, 0x2fc00000u, 0xa1600000u, 0xf0b00000u, 0xda880000u, 0x6fc40000u, 0x81620000u, 0x40bb0000u, 0x22878000u, 0xb3c9c000u, 0xfb65a000u, 0xddb2d000u, 0x78022800u, 0x9c0b3c00u, 0x5a0fb600u, 0x2d0ddb00u, 0xa2878080u, 0xf3c9c040u, 0xdb65a020u, 0x6db2d0b0u, 0x800228f8u, 0x400b3cdcu, 0x200fb67au, 0xb00ddb9du},
    {0x80000000u, 0x40000000u, 0x60000000u, 0x30000000u, 0xc8000000u, 0x24000000u, 0x56000000u, 0xfb000000u, 0xe0800000u, 0x70400000u, 0xa8600000u, 0x14300000u, 0x9ec80000u, 0xdf240000u, 0xb6d60000u, 0x8bbb0000u, 0x48008000u, 0x64004000u, 0x36006000u, 0xcb003000u, 0x2880c800u, 0x54402400u, 0xfe605600u, 0xef30fb00u, 0x7e48e080u, 0xaf647040u, 0x1eb6a860u, 0x9f8b1430u, 0xd6c81ec8u, 0xbb249f24u, 0x80d6d6d6u, 0x40bbbbbbu},
    {0x80000000u, 0xc0000000u, 0xa0000000u, 0xd0000000u, 0x58000000u, 0x94000000u, 0x3e000000u, 0xe3000000u, 0xbe800000u, 0x23c00000u, 0x1e200000u, 0xf3100000u, 0x46780000u, 0x67840000u, 0x78460000u, 0x84670000u, 0xc6788000u, 0xa784c000u, 0xd846a000u, 0x5467d000u, 0x9e78d800u, 0x33845400u, 0xe6469e00u, 0xb7673300u, 0x20f86680u, 0x104477c0u, 0xf8668020u, 0x4477c010u, 0x668020f8u, 0x77c01044u, 0x8020f866u, 0xc0104477u},
    {0x80000000u, 0x40000000u, 0xa0000000u, 0x50000000u, 0x88000000u, 0x24000000u, 0x12000000u, 0x2d000000u, 0x76800000u, 0x9e400000u, 0x08200000u, 0x64100000u, 0xb2280000u, 0x7d140000u, 0xfea20000u, 0xba490000u, 0x1a248000u, 0x491b4000u, 0xc4b5a000u, 0xe3739000u, 0xf6800800u, 0xde400400u, 0xa8200a00u, 0x34100500u, 0x3a280880u, 0x59140240u, 0xeca20120u, 0x974902d0u, 0x6ca48768u, 0xd75b49e4u, 0xcc95a082u, 0x87639641u},
    {0x80000000u, 0x40000000u, 0xa0000000u, 0x50000000u, 0x28000000u, 0xd4000000u, 0x6a000000u, 0x71000000u, 0x38800000u, 0x58400000u, 0xea200000u, 0x31100000u, 0x98a80000u, 0x08540000u, 0xc22a0000u, 0xe5250000u, 0xf2b28000u, 0x79484000u, 0xfaa42000u, 0xbd731000u, 0x18a80800u, 0x48540400u, 0x622a0a00u, 0xb5250500u, 0xdab28280u, 0xad484d40u, 0x90a426a0u, 0xcc731710u, 0x20280b88u, 0x10140184u, 0x880a04a2u, 0x84350611u},
    {0x80000000u, 0x40000000u, 0xe0000000u, 0xb0000000u, 0x98000000u, 0x94000000u, 0x8a000000u, 0x5b000000u, 0x33800000u, 0xd9c00000u, 0x72200000u, 0x3f100000u, 0xc1b80000u, 0xa6ec0000u, 0x53860000u, 0x29f50000u, 0x0a3a8000u, 0x1b2ac000u, 0xd392e000u, 0x69ff7000u, 0xea380800u, 0xab2c0400u, 0x4ba60e00u, 0xfde50b00u, 0x60028980u, 0xf006c940u, 0x7834e8a0u, 0x241a75b0u, 0x123a8b38u, 0xcf2ac99cu, 0xb992e922u, 0x82ff78f1u},
    {0x80000000u, 0x40000000u, 0xa0000000u, 0x10000000u, 0x08000000u, 0x6c000000u, 0x9e000000u, 0x23000000u, 0x57800000u, 0xadc00000u, 0x7fa00000u, 0x91d00000u, 0x49880000u, 0xced40000u, 0x880a0000u, 0x2c0f0000u, 0x3e0d8000u, 0x3317c000u, 0x5fb06000u, 0xc1f8b000u, 0xe18d8800u, 0xb2d7c400u, 0x1e106a00u, 0x6328b100u, 0xf7858880u, 0xbdc3c2c0u, 0x77ba63e0u, 0xfdf7b330u, 0xd7800df8u, 0xedc0081cu, 0xdfa0041au, 0x81d00a2du},
    {0x80000000u, 0x40000000u, 0x20000000u, 0x30000000u, 0x58000000u, 0xac000000u, 0x96000000u, 0x2b000000u, 0xd4800000u, 0x09400000u, 0xe2a00000u, 0x52500000u, 0x4e280000u, 0xc71c0000u, 0x629e0000u, 0x12670000u, 0x6e138000u, 0xf731c000u, 0x3a98a000u, 0xbe449000u, 0xf83b8800u, 0xdc2dc400u, 0xee06a200u, 0xb7239300u, 0x1aa80d80u, 0x8e5c0ec0u, 0xa03e0b60u, 0x703701b0u, 0x783b88c8u, 0x9c2dca54u, 0xce06a74au, 0x87239795u},
    {0x80000000u, 0xc0000000u, 0xa0000000u, 0x50000000u, 0xf8000000u, 0x8c000000u, 0xe2000000u, 0x33000000u, 0x0f800000u, 0x21400000u, 0x95a00000u, 0x5e700000u, 0xd8080000u, 0x1c240000u, 0xba160000u, 0xef370000u, 0x15868000u, 0x9e6fc000u, 0x781b6000u, 0x4c349000u, 0x420e8800u, 0x630bcc00u, 0xf7ad6a00u, 0xad739500u, 0x77800780u, 0x6d4004c0u, 0xd7a00420u, 0x3d700630u, 0x2f880f78u, 0xb1640ad4u, 0xcdb6077au, 0x824706d7u},
    {0x80000000u, 0xc0000000u, 0x60000000u, 0x90000000u, 0x38000000u, 0xc4000000u, 0x42000000u, 0xa3000000u, 0xf1800000u, 0xaa400000u, 0xfce00000u, 0x85100000u, 0xe0080000u, 0x500c0000u, 0x58060000u, 0x54090000u, 0x7a038000u, 0x670c4000u, 0xb3842000u, 0x094a3000u, 0x0d6f1800u, 0x2f5aa400u, 0x1ce7ce00u, 0xd5145100u, 0xb8000080u, 0x040000c0u, 0x22000060u, 0x33000090u, 0xc9800038u, 0x6e4000c4u, 0xbee00042u, 0x261000a3u},
    {0x80000000u, 0x40000000u, 0x20000000u, 0xf0000000u, 0xa8000000u, 0x54000000u, 0x9a000000u, 0x9d000000u, 0x1e800000u, 0x5cc00000u, 0x7d200000u, 0x8d100000u, 0x24880000u, 0x71c40000u, 0xeba20000u, 0x75df0000u, 0x6ba28000u, 0x35d14000u, 0x4ba3a000u, 0xc5d2d000u, 0xe3a16800u, 0x91db8c00u, 0x79aef200u, 0x0cdf4100u, 0x672a8080u, 0x50154040u, 0x1a01a020u, 0xdd0dd0f0u, 0x3e83e8a8u, 0xaccacc54u, 0xd52d529au, 0xd91d919du},
    {0x80000000u, 0xc0000000u, 0x20000000u, 0xd0000000u, 0xd8000000u, 0xc4000000u, 0x46000000u, 0x85000000u, 0xa5800000u, 0x76c00000u, 0xada00000u, 0x6ab00000u, 0x2da80000u, 0xaabc0000u, 0x0daa0000u, 0x7ab10000u, 0xd5a78000u, 0xbebd4000u, 0x93a3e000u, 0x3bb51000u, 0x3629b800u, 0x4d727c00u, 0x9b836200u, 0x27c4d700u, 0xb629b880u, 0x8d727cc0u, 0xbb836220u, 0xf7c4d7d0u, 0x6e29b858u, 0x49727c04u, 0xfd836266u, 0x72c4d755u},
    {0x80000000u, 0x40000000u, 0x20000000u, 0xf0000000u, 0x38000000u, 0x14000000u, 0xf6000000u, 0x67000000u, 0x8f800000u, 0x50400000u, 0x8aa00000u, 0x0ff00000u, 0x12a80000u, 0xabf40000u, 0xfcaa0000u, 0x28fb0000u, 0xbd298000u, 0x0bba4000u, 0x4e06e000u, 0x330c3000u, 0x59861800u, 0xc74d3400u, 0x3d2cb200u, 0x4bb2cb00u, 0x6e061880u, 0xc30d3440u, 0x618cb220u, 0xd342cbf0u, 0xcb2e18b8u, 0x2cb93454u, 0xe186b2d6u, 0x9349cb97u}
    };
#undef X2_SOBOL_STORAGE
X2_HD inline U32 sobol(U32 index,U32 dimension) {

    U32 gray=index^(index>>1),result=0,bit=0;
    while(gray){if(gray&1)result^=directions[dimension][bit];gray>>=1;++bit;}
    return result;
}
X2_HD inline U32 reverseBits(U32 x) {
#if defined(__CUDA_ARCH__)
    return __brev(x);
#else
    x=((x>>1)&0x55555555u)|((x&0x55555555u)<<1);x=((x>>2)&0x33333333u)|((x&0x33333333u)<<2);
    x=((x>>4)&0x0f0f0f0fu)|((x&0x0f0f0f0fu)<<4);x=((x>>8)&0x00ff00ffu)|((x&0x00ff00ffu)<<8);
    return (x>>16)|(x<<16);
#endif
}
// Nested uniform (Owen) scrambling by hash, B. Burley, "Practical Hash-based Owen Scrambling" (JCGT 2020): each bit
// flipped by a hash of the bits above it, so every elementary interval of the net keeps one point but the points' places
// inside them differ from pixel to pixel. A digital shift (one XOR for every point) kept each pixel's set the same net
// moved, so a small window on the lens (a light far out of focus) counted points by where it sat on the net's grid: the
// same lattice inside every bokeh disc.
X2_HD inline U32 owenScramble(U32 x,U32 seed) {
    x=reverseBits(x);
    x+=seed;x^=x*0x6c50b47cu;x^=x*0xb82f1e52u;x^=x*0xc7afe638u;x^=x*0x8d22f6e6u;
    return reverseBits(x);
}
X2_HD inline U32 samplingWord(const Identity& id,U32 dimension,U32 policy) {
    const bool camera=dimension<5, diffuse=dimension==16||dimension==17, light=dimension==18||dimension==19,
               subsurface=dimension>=20&&dimension<=27;
    if((!camera||!(policy&1))&&(!diffuse||!(policy&2))&&(!light||!(policy&4))&&(!subsurface||!(policy&8)))return word(id,dimension);
    U32 d=camera?(dimension<2?dimension:dimension<4?dimension+12:16):dimension-14;
    Identity shift=id;shift.index=id.index>>32;
    // The lens (2/3) and the shutter time (4) as Burley's padding: Sobol's first dimensions (its best two-dimensional
    // net) in a sample order of their own, the index scrambled per pixel (blocks of 2^k samples stay blocks, so every
    // power-of-two prefix is still a net). Drawn with the pixel position's own index (Sobol dimensions 14/15 and 16, as
    // before), a lens point moved with the sample's place in the pixel, and a light far out of focus showed it.
    if(camera&&dimension>=2){
        // One Philox block each ("PADD", "PADE"): the order's seed, then each coordinate's.
        const Words seeds=block(shift,dimension<4?0x50414444u:0x50414445u);
        return owenScramble(sobol(owenScramble(U32(id.index),seeds.v[0]),dimension<4?dimension-2:0u),seeds.v[dimension<4?dimension-1:1]);
    }
    // Each four Sobol dimensions take their scrambles' seeds from one Philox block (0x534f424f for 0 to 3, then on).
    return owenScramble(sobol(U32(id.index),d),block(shift,0x534f424fu+(d>>2)).v[d&3]);
}
X2_HD inline float draw(const Identity& id,U32 dimension,U32 policy) {
    return unit(samplingWord(id,dimension,policy));
}

constexpr U32 CameraDimensions=16,DimensionsPerBounce=256,MaxBounces=4096;
// The bounds are capabilities, not silent modulo wrap. More complex estimators
// must extend the versioned layout or route to fallback before starting samples.
struct Cursor { U32 bounce=0,offset=0; };
X2_HD inline bool next(const Identity& id,Cursor& c,float& value) {
    if(c.bounce>=MaxBounces || c.offset>=DimensionsPerBounce)return false;
    value=unit(word(id,CameraDimensions+c.bounce*DimensionsPerBounce+c.offset));
    ++c.offset;return true;
}
X2_HD inline bool child(U64 parent,U32 slot,U64& address) {
    // Radix-16 tree, root 0. 15 children per node. Overflow rejects, never aliases.
    if(slot>=15 || parent>(~U64(0)-U64(slot+1))/16)return false;
    address=parent*16+slot+1;return true;
}
}}}
