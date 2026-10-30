// Private XPU2 shading library, shared CPU/CUDA: MoonRay's colour corrections
// (shading/ispc/ColorCorrect.isph), used by DwaBase's colour corrections, the
// DwaColorCorrect material and the colour-correct maps. Derived from MoonRay
// Apache-2.0, Copyright 2023-2024 DreamWorks Animation LLC. See
// MOONRAY_LICENSE.txt.
#pragma once
#include "shade_color.h"
namespace xpu2 { namespace interactive { namespace shade {

// lerpOpt: (v1 - v0) * t + v0, MoonRay's three-instruction lerp.
X2_HD inline float lerpOpt(float v0, float v1, float t) { return (v1 - v0) * t + v0; }
X2_HD inline Color lerpOpt(Color v0, Color v1, float t) { return (v1 - v0) * t + v0; }

X2_HD inline void applyContrast(float contrast, float& result) {
    if (isZero(contrast)) return;
    contrast = clampf(contrast, -1.0f, 1.0f);
    if (contrast < 0) {
        contrast *= -1.0f;
        result = lerpf(result, 0.5f, contrast);
    } else {
        if (isEqual(contrast, 1.0f)) contrast = 0.999f;
        contrast = 1.0f / (1.0f - contrast);
        result = ((result - 0.5f) * contrast) + 0.5f;
    }
}
X2_HD inline void applyContrast(Color contrast, Color& result) {
    applyContrast(contrast.x, result.x);
    applyContrast(contrast.y, result.y);
    applyContrast(contrast.z, result.z);
}
// Nuke's ColorCorrect contrast, pivoting about 18%.
X2_HD inline void applyNukeContrast(float cx, float cy, float cz, float& r, float& g, float& b) {
    const float pivot = 0.18f, invPivot = 1.0f / pivot;
    r = r > 0 ? powf(r * invPivot, cx) * pivot : r * powf(invPivot, cx) * pivot;
    g = g > 0 ? powf(g * invPivot, cy) * pivot : g * powf(invPivot, cy) * pivot;
    b = b > 0 ? powf(b * invPivot, cz) * pivot : b * powf(invPivot, cz) * pivot;
}
X2_HD inline float computeLuminance(float r, float g, float b) { return r * 0.212671f + g * 0.715160f + b * 0.072169f; }
X2_HD inline void applyHueShift(float hueShift, Color& result) {
    Color hsv = rgbToHsv(result);
    hsv.x = fmodf(hsv.x + hueShift, 1.f);
    result = hsvToRgb(hsv);
}
X2_HD inline void applySaturation(float sat, float& r, float& g, float& b) {
    const float y = computeLuminance(r, g, b);
    r = lerpOpt(y, r, sat);
    g = lerpOpt(y, g, sat);
    b = lerpOpt(y, b, sat);
}
X2_HD inline void applySaturation(float sr, float sg, float sb, float& r, float& g, float& b) {
    const float y = computeLuminance(r, g, b);
    r = lerpOpt(y, r, sr);
    g = lerpOpt(y, g, sg);
    b = lerpOpt(y, b, sb);
}
X2_HD inline void applySaturationWithoutPreservingLuminance(float sat, float& r, float& g, float& b) {
    const float m = fmaxf(r, fmaxf(g, b));
    r = lerpOpt(m, r, sat);
    g = lerpOpt(m, g, sat);
    b = lerpOpt(m, b, sat);
}
// Negative channels keep their value (no imaginary numbers), as in Nuke.
X2_HD inline void applyGamma(float gr, float gg, float gb, float& r, float& g, float& b) {
    if (r > 0) r = powf(r, gr);
    if (g > 0) g = powf(g, gg);
    if (b > 0) b = powf(b, gb);
}
X2_HD inline void applyGainAndOffset(float gr, float gg, float gb, float orr, float og, float ob, float& r, float& g, float& b) {
    r = r * gr + orr;
    g = g * gg + og;
    b = b * gb + ob;
}
// TMI: temperature (yellow/blue), magenta/green, and intensity in stops.
X2_HD inline void applyTMI(float kT, float kM, float kI, float& r, float& g, float& b) {
    const float oneOverSix = float(1.0 / 6.0), oneOverThree = float(1.0 / 3.0);
    const float expScale = powf(2.0f, kI);
    const float rScale = (6.0f * expScale + 2.0f * kM - 3.0f * kT) * oneOverSix;
    const float gScale = (3.0f * expScale - 2.0f * kM) * oneOverThree;
    const float bScale = rScale + kT;
    r = r * rScale;
    g = g * gScale;
    b = b * bScale;
}
}}}
