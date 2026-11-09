#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
//
// Where a path's random numbers come from.
//
// The camera's draws and those of the first ML_QMC_BOUNCES bounces come from OpenQMC's Owen-scrambled Sobol
// sequence (third_party/openqmc), so that a pixel's samples spread over each choice evenly instead of by chance:
// for the same noise a picture needs about half the samples where the light comes from lamps, an environment or
// fog. Each bounce is a domain of its own, and within it each part of the work (the lights a surface is lit by,
// its BSDF, a scattering in fog, a try through a solid) starts a domain of its own with seedPhase, so that the same
// choice is drawn from the same dimensions in every sample however many draws came before it. A domain gives two
// dimensions at a time, up to the budget it is started with; draws past the budget, and past the structured
// bounces, come from the hashed LCG stream of vec.h, as all of them did before. The draws are taken in the order
// the path asks for them, so a path that branches stays unbiased, only less evenly spread.
//
// ML_QMC=0 builds the kernel with the LCG stream alone, exactly as it was before OpenQMC.
#include "vec.h"

#ifndef ML_QMC
#define ML_QMC 1
#endif
#ifndef ML_QMC_BOUNCES
#define ML_QMC_BOUNCES 4
#endif

#if ML_QMC
#include <oqmc/sobol.h>
#endif

// The parts of a bounce that start a domain of their own (keys, never 0).
enum QmcPhase : int {
    QMC_LIGHTS = 1,         // the lights a surface is lit by
    QMC_BSDF = 2,           // which way the light leaves the surface, and the choices on the way there
    QMC_FOG_STEP = 3,       // a step through a fog with a grid (index: the step)
    QMC_FOG_SCATTER = 4,    // a scattering in fog: the lamps' light there and the way on (index: the order)
    QMC_MEDIUM = 5,         // how far light gets in an even fog
    QMC_WALK_START = 6,     // a random walk's first step into the solid (index: the try)
    QMC_DIFFUSION = 8,      // a diffusion profile's tries (index: the try)
    QMC_DIFFUSION_FAR = 9,  // the tries through the solid (index: the try)
    QMC_NEXT_BOUNCE = 10,
};

struct Seed {
    unsigned lcg;                   // the old stream: past the structured draws, and the shadow rays' presence
#if ML_QMC
    // Kept small, as it lives through the whole path: the bounce's domain; the second of the two dimensions taken
    // last; and the part being drawn, packed: bits 0-4 how many structured draws it has left, 5-9 how many it has
    // taken, 10-13 its key, 14-30 its index, and bit 31 whether this bounce draws from OpenQMC at all. A part's
    // domain is made again from the bounce's at each pair of draws, which costs less than carrying it.
    oqmc::SobolSampler bounce;
    float held;
    unsigned part;
#endif
};

#if ML_QMC
constexpr unsigned QMC_STRUCTURED = 1u << 31;
ML_INLINE unsigned qmcPart(int key, int index, int dims) {
    return QMC_STRUCTURED | (unsigned(key) << 10) | (unsigned(index) << 14) | unsigned(dims);
}
#endif

ML_INLINE float rnd(Seed& s) {
#if ML_QMC
    if (s.part & 31u) {
        const unsigned taken = (s.part >> 5) & 31u;
        s.part += 32u - 1u;     // one more taken, one fewer left
        if (taken & 1u) return s.held;
        float pair[2];
        s.bounce.newDomainChain(int((s.part >> 10) & 15u), int((s.part >> 14) & 0x1ffffu)).newDomain(int(taken >> 1)).drawSample<2>(pair);
        s.held = pair[1];
        return pair[0];
    }
#endif
    return rnd(s.lcg);
}

// The draws for one pixel's sample: the camera's first (a place in the pixel, and one on the lens).
ML_INLINE Seed startSeed(unsigned x, unsigned y, unsigned pixel, unsigned sample) {
    Seed s;
    s.lcg = tea(pixel, sample);
#if ML_QMC
    s.bounce = oqmc::SobolSampler(int(x), int(y), 0, int(sample), nullptr);
    s.held = 0.0f;
    s.part = qmcPart(0, 0, 4);
#endif
    return s;
}

// A part of the bounce that draws from a domain of its own: up to dims (at most 31) structured draws.
ML_INLINE void seedPhase(Seed& s, QmcPhase key, int index, int dims) {
#if ML_QMC
    if (s.part & QMC_STRUCTURED) s.part = qmcPart(key, index, dims);
#endif
}

// Draws from the old stream until the next part: for long loops of steps where a domain for every step costs more
// than the evenness gains (a random walk's steps; fog's are worth it).
ML_INLINE void seedPlain(Seed& s) {
#if ML_QMC
    s.part &= ~31u;
#endif
}

// A new bounce: a domain of its own while the structured bounces last, the old stream after.
ML_INLINE void bounceSeed(Seed& s, unsigned depth) {
#if ML_QMC
    s.part = 0;
    if (depth < ML_QMC_BOUNCES) {
        s.bounce = s.bounce.newDomain(QMC_NEXT_BOUNCE);
        s.part = qmcPart(0, 0, 8);
    }
#endif
}
