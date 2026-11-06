// coordinates.mesh_corners's locator projections for the plugin's Python, in one call: planar, cubic, cylindrical and
// spherical UVs at every corner of every face, each face on its own (the seam of a wrapped face mended within it), then
// moved by the layer's UV matrix, rotation and scale (coordinates.transform_uv). The same arithmetic in doubles in the
// same order, the corners as 32-bit floats, as rows.uv_transform gives a UV map's. atan2 and asin are taken from the
// C runtime Modo's Python calls (ucrtbase), so that a wrapped face is the same to the last bit. In Python each corner
// was a step of its own (a 324,706-face mesh: seconds of each reading).
#include <windows.h>
#include <cmath>
#include <cstdint>
#include <vector>

namespace {

using Math2 = double (*)(double, double);
using Math1 = double (*)(double);

struct Runtime {
    Math2 atan2 = nullptr;
    Math1 asin = nullptr;
    Runtime() {
        HMODULE crt = GetModuleHandleW(L"ucrtbase.dll");
        if (!crt) crt = LoadLibraryW(L"ucrtbase.dll");
        if (crt) {
            atan2 = reinterpret_cast<Math2>(reinterpret_cast<void*>(GetProcAddress(crt, "atan2")));
            asin = reinterpret_cast<Math1>(reinterpret_cast<void*>(GetProcAddress(crt, "asin")));
        }
        if (!atan2) atan2 = [](double y, double x) { return std::atan2(y, x); };
        if (!asin) asin = [](double v) { return std::asin(v); };
    }
};

const Runtime& runtime() {
    static const Runtime held;
    return held;
}

struct P { double x, y, z; };

// coordinates.transform: sum(point[j] * m[j*4+i] for j in range(3)) + m[12+i], in that order.
P transform(const P& p, const double* m) {
    P out;
    double* o = &out.x;
    for (int i = 0; i < 3; ++i) {
        double total = 0.0;
        total += p.x * m[i];
        total += p.y * m[4 + i];
        total += p.z * m[8 + i];
        o[i] = total + m[12 + i];
    }
    return out;
}

}  // namespace

// points: three doubles each; corners and counts: the faces. inverse: the locator's inverse, world: the mesh's world
// matrix (row-major, as coordinates.py holds them; world unused where objectSpace). axis 0 x, 1 y, 2 z; projection 0
// planar, 1 cubic, 2 cylindrical, 3 spherical. uv: a..f, cos and sin of the rotation, scale x and y. out: two floats a
// corner of each face with corners. Returns 0; -1 where a corner is out of range; -2 where a face cannot be cubic
// (fewer than three corners, or degenerate): coordinates.py then reads it, to say so as it does.
extern "C" __declspec(dllexport) int MR_project(const double* points, long long pointCount, const std::uint32_t* corners,
                                                const std::int32_t* counts, long long faceCount, const double* inverse,
                                                const double* world, int objectSpace, int axis, int projection,
                                                const double* uv, float* out) {
    const Runtime& math = runtime();
    std::vector<P> placed(size_t(pointCount > 0 ? pointCount : 0));
    for (long long i = 0; i < pointCount; ++i) {
        P p{points[3 * i], points[3 * i + 1], points[3 * i + 2]};
        p = objectSpace ? transform(p, inverse) : transform(transform(p, world), inverse);
        placed[size_t(i)] = axis == 0 ? P{p.y, p.z, p.x} : axis == 1 ? P{p.x, p.z, p.y} : p;
    }
    const double a = uv[0], b = uv[1], c = uv[2], d = uv[3], e = uv[4], f = uv[5], cosine = uv[6], sine = uv[7], sx = uv[8], sy = uv[9];
    const double tau = 2 * 3.141592653589793, pi = 3.141592653589793;
    long long at = 0, written = 0;
    std::vector<P> face;
    std::vector<double> own;
    for (long long k = 0; k < faceCount; ++k) {
        const long long size = counts[k];
        if (size < 0) return -1;
        face.resize(size_t(size));
        for (long long j = 0; j < size; ++j) {
            const std::uint32_t v = corners[at + j];
            if ((long long)v >= pointCount) return -1;
            face[size_t(j)] = placed[v];
        }
        at += size;
        if (!size) continue;
        own.resize(size_t(2 * size));
        if (projection == 0) {
            for (long long j = 0; j < size; ++j) { own[2 * j] = face[j].x + .5; own[2 * j + 1] = face[j].y + .5; }
        } else if (projection == 1) {
            if (size < 3) return -2;
            double normal[3] = {0.0, 0.0, 0.0};
            for (long long j = 0; j < size; ++j) {
                const P& p = face[j];
                const P& q = face[(j + 1) % size];
                normal[0] += (p.y - q.y) * (p.z + q.z);
                normal[1] += (p.z - q.z) * (p.x + q.x);
                normal[2] += (p.x - q.x) * (p.y + q.y);
            }
            // max(range(3), key=abs): the first of the largest.
            int dominant = 0;
            for (int i = 1; i < 3; ++i) if (std::fabs(normal[i]) > std::fabs(normal[dominant])) dominant = i;
            if (std::fabs(normal[dominant]) < 1e-12) return -2;
            const double sign = normal[dominant] >= 0 ? 1.0 : -1.0;
            for (long long j = 0; j < size; ++j) {
                const P& p = face[j];
                if (dominant == 0) { own[2 * j] = -sign * p.z + .5; own[2 * j + 1] = p.y + .5; }
                else if (dominant == 1) { own[2 * j] = p.x + .5; own[2 * j + 1] = -sign * p.z + .5; }
                else { own[2 * j] = sign * p.x + .5; own[2 * j + 1] = p.y + .5; }
            }
        } else {
            double lo = 0.0, hi = 0.0;
            for (long long j = 0; j < size; ++j) {
                const P& p = face[j];
                const double u = .5 + math.atan2(p.x, p.z) / tau;
                double v;
                if (projection == 2) v = p.y + .5;
                else {
                    const double root = std::sqrt(p.x * p.x + p.y * p.y + p.z * p.z);
                    const double length = root > 1e-12 ? root : 1e-12;
                    double s = p.y / length;
                    // max(-1, min(1, s)), as Python picks: s only where below 1, then only where above -1.
                    s = s < 1.0 ? s : 1.0;
                    s = s > -1.0 ? s : -1.0;
                    v = .5 + math.asin(s) / pi;
                }
                own[2 * j] = u;
                own[2 * j + 1] = v;
                if (!j || u > hi) hi = u;
                if (!j || u < lo) lo = u;
            }
            if (hi - lo > .5)
                for (long long j = 0; j < size; ++j) if (own[2 * j] < .5) own[2 * j] = own[2 * j] + 1;
        }
        for (long long j = 0; j < size; ++j) {
            const double u = own[2 * j], v = own[2 * j + 1];
            const double x = a * u + b * v + c, y = d * u + e * v + f;
            out[2 * written] = float((x * cosine - y * sine) * sx);
            out[2 * written + 1] = float((x * sine + y * cosine) * sy);
            ++written;
        }
    }
    return 0;
}
