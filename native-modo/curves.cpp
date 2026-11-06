// Curves for the plugin's Python, a batch at a time: what extra_geometry.batches works out for each point of its strands
// (how far along its strand it is, its radius down the strand's taper, its UV), and what moonlightipr_curves.segments
// makes of a curve geometry for MoonLightIPR (control points, their radii, each segment's first, how far along, each
// strand's own number). In Python each was a step for each point of each strand (a head of 100,000 strands of 16 points:
// seconds at each). The same arithmetic in doubles in the same order; a strand's length step is math.dist as Modo's
// Python (3.9) works it out, and pow is the C runtime's, as Python's ** calls it.
#include <windows.h>
#include <cmath>
#include <cstdint>

namespace {

using Pow = double (*)(double, double);

Pow runtimePow() {
    static Pow held = [] {
        HMODULE crt = GetModuleHandleW(L"ucrtbase.dll");
        if (!crt) crt = LoadLibraryW(L"ucrtbase.dll");
        Pow found = crt ? reinterpret_cast<Pow>(reinterpret_cast<void*>(GetProcAddress(crt, "pow"))) : nullptr;
        return found ? found : static_cast<Pow>([](double a, double b) { return std::pow(a, b); });
    }();
    return held;
}

// CPython 3.9's math.dist: vector_norm of the differences, each over the largest, with its running correction (checked
// against Modo's own Python on 50,000 pairs, tools/probe_cl_dist_parts.py).
double dist(const double* p, const double* q) {
    double diffs[3], max = 0.0;
    bool nan = false;
    for (int i = 0; i < 3; ++i) {
        const double x = std::fabs(p[i] - q[i]);
        diffs[i] = x;
        nan = nan || std::isnan(x);
        if (x > max) max = x;
    }
    if (std::isinf(max)) return max;
    if (nan) return NAN;
    if (max == 0.0) return max;
    // Each difference over the largest, as Modo's Python (3.9) has it (later Pythons scale by a power of two).
    double csum = 1.0, frac = 0.0;
    for (double x : diffs) {
        x /= max;
        x = x * x;
        const double old = csum;
        csum += x;
        frac += (old - csum) + x;
    }
    return max * std::sqrt(csum - 1.0 + frac);
}

}  // namespace

// extra_geometry.batches for one batch: points (three doubles each) of strandCount strands (counts), scales one for each
// strand or null (1.0). For every point, where tapered, its radius (root + (tip - root) * along ** envelope) * scale into
// radii; where withUv, (across, along) into uvs, across being (strand + .5) / strandCount. Returns 0, -1 for a bad count.
extern "C" __declspec(dllexport) int MR_curve_shape(const double* points, const std::int32_t* counts, long long strandCount,
                                                    const double* scales, double root, double tip, double envelope,
                                                    int tapered, int withUv, double* radii, double* uvs) {
    const Pow power = runtimePow();
    long long at = 0;
    for (long long s = 0; s < strandCount; ++s) {
        const long long count = counts[s];
        if (count < 0) return -1;
        const double* strand = points + 3 * at;
        // The lengths up to each point, then the strand's whole length (or 1 for none).
        double total = 0.0;
        for (long long k = 1; k < count; ++k) total = total + dist(strand + 3 * (k - 1), strand + 3 * k);
        total = total != 0.0 ? total : 1.0;
        const double scale = scales ? scales[s] : 1.0;
        const double across = (double(s) + .5) / double(strandCount);
        double length = 0.0;
        for (long long k = 0; k < count; ++k) {
            if (k) length = length + dist(strand + 3 * (k - 1), strand + 3 * k);
            const double along = length / total;
            if (tapered) radii[at + k] = (root + (tip - root) * power(along, envelope)) * scale;
            if (withUv) { uvs[2 * (at + k)] = across; uvs[2 * (at + k) + 1] = along; }
        }
        at += count;
    }
    return 0;
}

// moonlightipr_curves.segments for one curve geometry: points (three doubles each), counts, radii (radiusCount of them:
// one, one a strand or one a point), kind (0 the line through the points, 1 Bezier, 2 B-spline; the caller has made it
// 0 where the strands are too short for it). Out, for each control point: its position (three floats), radius (a float,
// not below 0), its strand and how far along it is (the last two as the strand's number from chances, its along, 0:
// three floats), and its strand's UV from strandUvs (two doubles a strand) into coordinates where given; each segment's
// first control point into firsts. made: control points and segments written. Returns 0, -1 where the room is short.
extern "C" __declspec(dllexport) int MR_curve_segments(const double* points, const std::int32_t* counts, long long strandCount,
                                                       const double* radiiIn, long long radiusCount, long long pointCount, int kind,
                                                       const double* chances, const double* strandUvs,
                                                       float* positions, float* widths, float* strandValues, float* coordinates,
                                                       std::uint32_t* firsts, long long controlRoom, long long segmentRoom,
                                                       long long* made) {
    const bool perPoint = radiusCount == pointCount;
    const bool perStrand = radiusCount == strandCount && !perPoint;
    long long controls = 0, segments = 0, start = 0;
    auto put = [&](const double p[3], double width, long long strand, double along) -> bool {
        if (controls >= controlRoom) return false;
        for (int i = 0; i < 3; ++i) positions[3 * controls + i] = float(p[i]);
        widths[controls] = float(width);
        strandValues[3 * controls] = float(along);
        strandValues[3 * controls + 1] = float(chances[strand]);
        strandValues[3 * controls + 2] = 0.0f;
        if (coordinates) { coordinates[2 * controls] = float(strandUvs[2 * strand]); coordinates[2 * controls + 1] = float(strandUvs[2 * strand + 1]); }
        ++controls;
        return true;
    };
    for (long long s = 0; s < strandCount; ++s) {
        const long long count = counts[s];
        if (count < 0) return -1;
        const double* here = points + 3 * start;
        auto wide = [&](long long k) { return perPoint ? radiiIn[start + k] : perStrand ? radiiIn[s] : radiiIn[0]; };
        if (count >= 2) {
            if (kind == 1) {
                // The B-spline control points of the cubic each four Bezier points make.
                static const int mix[4][4] = {{6, -7, 2, 0}, {0, 2, -1, 0}, {0, -1, 2, 0}, {0, 2, -7, 6}};
                const long long pieces = (count - 1) / 3;
                long long piece = 0;
                for (long long i = 0; i < count - 1; i += 3, ++piece) {
                    if (segments >= segmentRoom) return -1;
                    firsts[segments++] = std::uint32_t(controls);
                    const double ends[4] = {double(piece) / double(pieces), double(piece) / double(pieces),
                                            double(piece + 1) / double(pieces), double(piece + 1) / double(pieces)};
                    for (int row = 0; row < 4; ++row) {
                        double p[3];
                        for (int axis = 0; axis < 3; ++axis) {
                            double total = 0.0;
                            for (int m = 0; m < 4 && i + m < count; ++m) total += mix[row][m] * here[3 * (i + m) + axis];
                            p[axis] = total;
                        }
                        double width = 0.0;
                        for (int m = 0; m < 4 && i + m < count; ++m) width += mix[row][m] * wide(i + m);
                        if (!put(p, width > 0.0 ? width : 0.0, s, ends[row])) return -1;
                    }
                }
            } else {
                const long long first = controls;
                for (long long k = 0; k < count; ++k) {
                    const double w = wide(k);
                    if (!put(here + 3 * k, w > 0.0 ? w : 0.0, s, double(k) / double(count - 1))) return -1;
                }
                for (long long k = 0; k < count - (kind == 2 ? 3 : 1); ++k) {
                    if (segments >= segmentRoom) return -1;
                    firsts[segments++] = std::uint32_t(first + k);
                }
            }
        }
        start += count;
    }
    made[0] = controls;
    made[1] = segments;
    return 0;
}
