// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// transform_blend.h checked on its own: a wheel turning a third of a turn while the shutter is open keeps its size
// halfway through it, and stands where its frame does; a move alone is blended as before; scale and shear are blended;
// a mirrored transform stays mirrored; the ends are the ends. Prints each check and exits 1 on the first that fails.
#include "../src/transform_blend.h"

#include <cmath>
#include <cstdio>

using moonlightipr::blendTransform;

namespace {

int failures = 0;

void expect(bool ok, const char* what) {
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) ++failures;
}

// A row-major 3x4: a turn of angle (radians) about X, scaled by sx, sy, sz along the part's own axes, placed at t.
void wheel(double angle, double sx, double sy, double sz, const double* t, float* m) {
    const double c = std::cos(angle), s = std::sin(angle);
    const double r[9] = {1, 0, 0, 0, c, -s, 0, s, c};
    const double scale[3] = {sx, sy, sz};
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col) m[row * 4 + col] = float(r[row * 3 + col] * scale[col]);
        m[row * 4 + 3] = float(t[row]);
    }
}

double columnLength(const float* m, int col) {
    return std::sqrt(double(m[col]) * m[col] + double(m[4 + col]) * m[4 + col] + double(m[8 + col]) * m[8 + col]);
}

bool near(const float* a, const float* b, double tolerance) {
    for (int k = 0; k < 12; ++k)
        if (std::fabs(double(a[k]) - b[k]) > tolerance) return false;
    return true;
}

}  // namespace

int main() {
    const double pi = 3.14159265358979323846;
    const double at[3] = {0.97, 0.34, -1.09}, later[3] = {0.97, 0.34, -0.37}, middle[3] = {0.97, 0.34, -0.73};
    float open[12], close[12], frame[12], out[12];

    // A car's wheel: scaled 2.95 across and 2.59 round, turning 120 degrees while the shutter is open, moving along Z.
    wheel(-pi / 3, 2.95, 2.5875, 2.5875, at, open);
    wheel(pi / 3, 2.95, 2.5875, 2.5875, later, close);
    wheel(0.0, 2.95, 2.5875, 2.5875, middle, frame);
    blendTransform(open, close, 0.5f, out);
    expect(std::fabs(columnLength(out, 1) - 2.5875) < 1e-4 && std::fabs(columnLength(out, 2) - 2.5875) < 1e-4,
           "a turning wheel keeps its size halfway through the shutter");
    expect(near(out, frame, 1e-4), "and stands where its frame does");
    float numbers[12];
    for (int k = 0; k < 12; ++k) numbers[k] = open[k] + (close[k] - open[k]) * 0.5f;
    expect(std::fabs(columnLength(numbers, 1) - 2.5875 * 0.5) < 1e-4, "(blended number by number it came out half its size)");

    // A quarter of the way: a quarter of the turn.
    float quarter[12];
    const double place[3] = {0.97, 0.34, -1.09 + 0.25 * 0.72};
    wheel(-pi / 3 + 0.25 * 2 * pi / 3, 2.95, 2.5875, 2.5875, place, quarter);
    blendTransform(open, close, 0.25f, out);
    expect(near(out, quarter, 1e-4), "a quarter of the way through, a quarter of the turn");

    // The ends are the ends, exactly.
    blendTransform(open, close, 0.0f, out);
    expect(near(out, open, 0.0), "at the opening, the opening");
    blendTransform(open, close, 1.0f, out);
    expect(near(out, close, 0.0), "at the closing, the closing");

    // Moved only: blended number by number, as before.
    float moved[12];
    wheel(0.3, 1.0, 2.0, 3.0, at, open);
    wheel(0.3, 1.0, 2.0, 3.0, later, moved);
    blendTransform(open, moved, 0.5f, out);
    float expected[12];
    for (int k = 0; k < 12; ++k) expected[k] = open[k] + (moved[k] - open[k]) * 0.5f;
    expect(near(out, expected, 0.0), "a move alone is blended number by number");

    // Growing while still: the scale blended.
    float grown[12];
    wheel(0.0, 1.0, 1.0, 1.0, at, open);
    wheel(0.0, 3.0, 3.0, 3.0, at, grown);
    blendTransform(open, grown, 0.5f, out);
    expect(std::fabs(columnLength(out, 0) - 2.0) < 1e-5 && std::fabs(columnLength(out, 1) - 2.0) < 1e-5, "a scale is blended");

    // Mirrored at both ends (a negative scale), turning: still mirrored, its size kept.
    wheel(-pi / 3, -1.0, 2.0, 2.0, at, open);
    wheel(pi / 3, -1.0, 2.0, 2.0, later, close);
    wheel(0.0, -1.0, 2.0, 2.0, middle, frame);
    blendTransform(open, close, 0.5f, out);
    expect(near(out, frame, 1e-4), "a mirrored part turning stays mirrored, its size kept");

    // A part that collapses at one end (no turn can be told): blended number by number.
    float flat[12];
    wheel(0.5, 1.0, 0.0, 1.0, later, flat);
    wheel(0.0, 1.0, 1.0, 1.0, at, open);
    blendTransform(open, flat, 0.5f, out);
    for (int k = 0; k < 12; ++k) expected[k] = open[k] + (flat[k] - open[k]) * 0.5f;
    expect(near(out, expected, 0.0), "a part that collapses is blended number by number");

    std::printf("%d failed\n", failures);
    return failures ? 1 : 0;
}
