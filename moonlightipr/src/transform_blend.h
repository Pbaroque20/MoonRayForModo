// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// Where a moving transform stands between the shutter's two ends: its place and its scale and shear blended, its turn
// followed along the arc between them (a quaternion's slerp), as MoonRay places a moving item. Blending the matrices'
// numbers shrank whatever turns: a car's wheels, turning a third of a turn while the shutter was open, came out half
// their size halfway through it (cos 60 degrees), where the preview holds the frame's own moment.
#pragma once

#include <algorithm>
#include <cmath>

namespace moonlightipr {

// A row-major 3x4 transform's 3x3 part as its turn and its stretch, L = R S (polar decomposition): R a rotation, as a
// unit quaternion (w, x, y, z), S its scale and shear, symmetric (negative where the transform mirrors).
struct Polar {
    double turn[4] = {1, 0, 0, 0};
    double stretch[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    bool mirrored = false;
    bool ok = false;
};

inline double determinant3(const double* r) {
    return r[0] * (r[4] * r[8] - r[5] * r[7]) - r[1] * (r[3] * r[8] - r[5] * r[6]) + r[2] * (r[3] * r[7] - r[4] * r[6]);
}

inline Polar polar(const float* m) {
    Polar out;
    const double a[9] = {m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]};
    const double det = determinant3(a);
    if (!std::isfinite(det) || std::fabs(det) < 1e-24) return out;
    out.mirrored = det < 0.0;
    double r[9];
    for (int i = 0; i < 9; ++i) r[i] = out.mirrored ? -a[i] : a[i];
    // Higham's iteration, R = (R + R^-T) / 2, settles on the rotation nearest the matrix.
    for (int iteration = 0; iteration < 40; ++iteration) {
        const double d = determinant3(r);
        if (!std::isfinite(d) || std::fabs(d) < 1e-30) return out;
        const double inverseTranspose[9] = {
            (r[4] * r[8] - r[5] * r[7]) / d, -(r[3] * r[8] - r[5] * r[6]) / d, (r[3] * r[7] - r[4] * r[6]) / d,
            -(r[1] * r[8] - r[2] * r[7]) / d, (r[0] * r[8] - r[2] * r[6]) / d, -(r[0] * r[7] - r[1] * r[6]) / d,
            (r[1] * r[5] - r[2] * r[4]) / d, -(r[0] * r[5] - r[2] * r[3]) / d, (r[0] * r[4] - r[1] * r[3]) / d};
        double change = 0.0;
        for (int i = 0; i < 9; ++i) {
            const double next = 0.5 * (r[i] + inverseTranspose[i]);
            change = std::max(change, std::fabs(next - r[i]));
            r[i] = next;
        }
        if (change < 1e-13) break;
    }
    // S = R^T L, so that L = R S (S negative where L mirrors).
    for (int row = 0; row < 3; ++row)
        for (int col = 0; col < 3; ++col)
            out.stretch[row * 3 + col] = r[0 * 3 + row] * a[0 * 3 + col] + r[1 * 3 + row] * a[1 * 3 + col] + r[2 * 3 + row] * a[2 * 3 + col];
    double* q = out.turn;
    const double trace = r[0] + r[4] + r[8];
    if (trace > 0.0) {
        const double s = std::sqrt(trace + 1.0) * 2.0;
        q[0] = 0.25 * s; q[1] = (r[7] - r[5]) / s; q[2] = (r[2] - r[6]) / s; q[3] = (r[3] - r[1]) / s;
    } else if (r[0] > r[4] && r[0] > r[8]) {
        const double s = std::sqrt(1.0 + r[0] - r[4] - r[8]) * 2.0;
        q[0] = (r[7] - r[5]) / s; q[1] = 0.25 * s; q[2] = (r[1] + r[3]) / s; q[3] = (r[2] + r[6]) / s;
    } else if (r[4] > r[8]) {
        const double s = std::sqrt(1.0 + r[4] - r[0] - r[8]) * 2.0;
        q[0] = (r[2] - r[6]) / s; q[1] = (r[1] + r[3]) / s; q[2] = 0.25 * s; q[3] = (r[5] + r[7]) / s;
    } else {
        const double s = std::sqrt(1.0 + r[8] - r[0] - r[4]) * 2.0;
        q[0] = (r[3] - r[1]) / s; q[1] = (r[2] + r[6]) / s; q[2] = (r[5] + r[7]) / s; q[3] = 0.25 * s;
    }
    const double length = std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
    if (!(length > 0.0) || !std::isfinite(length)) return out;
    for (int i = 0; i < 4; ++i) q[i] /= length;
    out.ok = true;
    return out;
}

// The transform at time (0 the opening, 1 the closing) between open and close, both row-major 3x4: written to out.
// Moved only (the same 3x3 part at both ends), or where a turn cannot be told (a part that collapses, or mirrors at one
// end alone), blended number by number as before.
inline void blendTransform(const float* open, const float* close, float time, float* out) {
    if (time <= 0.0f) { std::copy(open, open + 12, out); return; }
    if (time >= 1.0f) { std::copy(close, close + 12, out); return; }
    bool turned = false;
    for (int row = 0; row < 3; ++row)
        for (int col = 0; col < 3; ++col) turned = turned || open[row * 4 + col] != close[row * 4 + col];
    const Polar a = turned ? polar(open) : Polar(), b = turned ? polar(close) : Polar();
    if (!turned || !a.ok || !b.ok || a.mirrored != b.mirrored) {
        for (int k = 0; k < 12; ++k) out[k] = open[k] + (close[k] - open[k]) * time;
        return;
    }
    const double t = time;
    double qb[4] = {b.turn[0], b.turn[1], b.turn[2], b.turn[3]};
    double cosine = a.turn[0] * qb[0] + a.turn[1] * qb[1] + a.turn[2] * qb[2] + a.turn[3] * qb[3];
    if (cosine < 0.0) {
        for (double& v : qb) v = -v;
        cosine = -cosine;
    }
    double wa = 1.0 - t, wb = t;
    if (cosine < 0.9999) {
        const double angle = std::acos(std::min(1.0, cosine));
        wa = std::sin((1.0 - t) * angle) / std::sin(angle);
        wb = std::sin(t * angle) / std::sin(angle);
    }
    double q[4];
    for (int i = 0; i < 4; ++i) q[i] = wa * a.turn[i] + wb * qb[i];
    const double length = std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
    for (double& v : q) v /= length;
    const double w = q[0], x = q[1], y = q[2], z = q[3];
    const double rotation[9] = {1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
                                2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
                                2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)};
    double stretch[9];
    for (int i = 0; i < 9; ++i) stretch[i] = a.stretch[i] + (b.stretch[i] - a.stretch[i]) * t;
    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col)
            out[row * 4 + col] = float(rotation[row * 3 + 0] * stretch[0 * 3 + col] + rotation[row * 3 + 1] * stretch[1 * 3 + col]
                                       + rotation[row * 3 + 2] * stretch[2 * 3 + col]);
        out[row * 4 + 3] = open[row * 4 + 3] + (close[row * 4 + 3] - open[row * 4 + 3]) * time;
    }
}

}  // namespace moonlightipr
