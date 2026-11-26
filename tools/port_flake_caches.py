"""Dense glitter in Vector and XPU modes: the stochastic flake lobe's reflection caches off the thread's stack.

A DwaBaseMaterial or DwaMetalMaterial with glitter switches, where many flakes fall in a pixel's footprint (fine flakes,
a high density, paint seen from afar), to MoonRay's stochastic flakes lobe (BsdfStochasticFlakes.ispc, the
"many flakes" mode of [Atanasov and Koylazov 2016]). Its sample and eval each build two reflection caches
(FlakeCaches: a direction, weight, colour, CDF value and normal for each of up to StochasticFlakes_sMaxFlakes = 2000
flakes) as local variables. In the vectorized code each is varying, one copy per lane, and the two make a stack frame
of about 2.8 MB (0x2afc00 bytes for sample, 0x2afa28 for eval, probed by __chkstk at the function's entry) whatever the
number of flakes. MoonRay's render threads have the process's default stack, 2 MB on Windows (moonray.exe's
SizeOfStackReserve; Linux's default is 8 MB, where it fits): Vector and XPU renders (XPU shades on the processor too)
ended with a stack overflow (0xC00000FD) the first time such a lobe was sampled or evaluated. Scalar mode's caches
(C++, one copy) are 88 KB and fit; XPU2 and MoonLightIPR have their own flakes.

Unless MoonRay is started with MOONRAY_MODO_FLAKE_CACHES=0 (the plugin's preference off; unset is on), sample and eval
take the two caches from a block of the thread's own on the heap (CPP_modoFlakeCaches: allocated the first time, 64-byte
aligned, kept for the thread's life, freed with it), and run the same code on it: the picture is the one the stack
caches give where the stack is big enough (bit for bit against the unfixed moonray.exe given a 16 MB stack, one thread;
tools/check_flake_caches.py renders a dense glitter ball in each mode against Scalar). The lobe's functions call no other
lobe, so one block per thread serves eval and sample in turn. Off, the caches are on the stack as MoonRay has them, in a
function of their own (noinline), so that the frame of the heap path stays small. That function's frame is 1.4 MB, half
the old one (the compiler no longer keeps two copies), so off a render may now fit a Windows thread's stack where it did
not; nothing else changes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHADING = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/shading'

HEADER = SHADING / 'bsdf/ModoFlakeCaches.h'
HEADER_TEXT = '''// Modo: the stochastic flake lobe's reflection caches off the stack (tools/port_flake_caches.py).
#pragma once

#include <cstdlib>

namespace moonray {
namespace shading {

/// True unless MoonRay was started with MOONRAY_MODO_FLAKE_CACHES=0. Read once.
inline bool modoFlakeCaches()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_FLAKE_CACHES");
        return !value || value[0] != '0';
    }();
    return on;
}

} // namespace shading
} // namespace moonray
'''

ISPC_DECLARATION_OLD = '''#define UNIFORM_SAMPLING 0
'''
ISPC_DECLARATION_NEW = '''#define UNIFORM_SAMPLING 0

// Modo: a block of the calling thread's own, on the heap, of at least the bytes asked for (64-byte aligned, kept for
// the thread's life), or 0 with MOONRAY_MODO_FLAKE_CACHES=0 (bsdf/Bsdf.cc, tools/port_flake_caches.py).
extern "C" uniform intptr_t
CPP_modoFlakeCaches(uniform int64 bytes);
'''

EVAL_OLD = '''varying Color
StochasticFlakesBsdfLobe_eval(const varying BsdfLobe * uniform lobe,
                              const varying BsdfSlice &slice,
                              const Vec3f &wi,
                              varying float * uniform pdf)
{
    varying StochasticFlakesBsdfLobe * uniform sfLobe =
            (varying StochasticFlakesBsdfLobe * uniform) lobe;
    // The bsdf from [2016] is not reciprocal (evaluating reflection cache based on Wo)
    // Using an additional reflection cache computed using Wi and
    // averaging the D term in the bsdf is a cheat we use to make
    // this bsdf reciprocal.
    varying FlakeCaches evalCachesWo, evalCachesWi;
    varying bool validCache'''
EVAL_NEW = '''// Modo: eval with its two reflection caches given (tools/port_flake_caches.py).
static varying Color
StochasticFlakesBsdfLobe_evalWith(const varying BsdfLobe * uniform lobe,
                                  const varying BsdfSlice &slice,
                                  const Vec3f &wi,
                                  varying float * uniform pdf,
                                  varying FlakeCaches &evalCachesWo,
                                  varying FlakeCaches &evalCachesWi)
{
    varying StochasticFlakesBsdfLobe * uniform sfLobe =
            (varying StochasticFlakesBsdfLobe * uniform) lobe;
    // The bsdf from [2016] is not reciprocal (evaluating reflection cache based on Wo)
    // Using an additional reflection cache computed using Wi and
    // averaging the D term in the bsdf is a cheat we use to make
    // this bsdf reciprocal.
    varying bool validCache'''

SAMPLE_OLD = '''varying Color
StochasticFlakesBsdfLobe_sample(const varying BsdfLobe * uniform lobe,
                                const varying BsdfSlice &slice,
                                varying float r1, varying float r2,
                                varying Vec3f &wi, varying float &pdf)
{
    varying StochasticFlakesBsdfLobe * uniform sfLobe =
            (varying StochasticFlakesBsdfLobe * uniform) lobe;

    varying FlakeCaches sampleCachesWo;
'''
SAMPLE_NEW = '''// Modo: eval, its caches on the stack as MoonRay has them: a frame of its own (tools/port_flake_caches.py).
static noinline varying Color
StochasticFlakesBsdfLobe_evalOnStack(const varying BsdfLobe * uniform lobe,
                                     const varying BsdfSlice &slice,
                                     const Vec3f &wi,
                                     varying float * uniform pdf)
{
    varying FlakeCaches evalCachesWo, evalCachesWi;
    return StochasticFlakesBsdfLobe_evalWith(lobe, slice, wi, pdf, evalCachesWo, evalCachesWi);
}

varying Color
StochasticFlakesBsdfLobe_eval(const varying BsdfLobe * uniform lobe,
                              const varying BsdfSlice &slice,
                              const Vec3f &wi,
                              varying float * uniform pdf)
{
    // Modo: the two caches (each one copy per lane, together more than a Windows thread's 2 MB stack) on the heap
    // (tools/port_flake_caches.py).
    const uniform intptr_t held = CPP_modoFlakeCaches(2 * sizeof(varying FlakeCaches));
    if (held != 0) {
        varying FlakeCaches * uniform caches = (varying FlakeCaches * uniform)held;
        return StochasticFlakesBsdfLobe_evalWith(lobe, slice, wi, pdf, caches[0], caches[1]);
    }
    return StochasticFlakesBsdfLobe_evalOnStack(lobe, slice, wi, pdf);
}

// Modo: sample with its two reflection caches given (tools/port_flake_caches.py).
static varying Color
StochasticFlakesBsdfLobe_sampleWith(const varying BsdfLobe * uniform lobe,
                                    const varying BsdfSlice &slice,
                                    varying float r1, varying float r2,
                                    varying Vec3f &wi, varying float &pdf,
                                    varying FlakeCaches &sampleCachesWo,
                                    varying FlakeCaches &sampleCachesWi)
{
    varying StochasticFlakesBsdfLobe * uniform sfLobe =
            (varying StochasticFlakesBsdfLobe * uniform) lobe;

'''

SAMPLE_WI_OLD = '''    // using Wi to enforce reciprocity in bsdf computation
    varying FlakeCaches sampleCachesWi;
'''
SAMPLE_WI_NEW = '''    // using Wi to enforce reciprocity in bsdf computation (Modo: sampleCachesWi given, tools/port_flake_caches.py)
'''

SAMPLE_END_OLD = '''    return StochasticFlakesBsdfLobe_computeBrdf(sfLobe, slice, wi, sampleCachesWo, sampleCachesWi, &pdf);
}
'''
SAMPLE_END_NEW = '''    return StochasticFlakesBsdfLobe_computeBrdf(sfLobe, slice, wi, sampleCachesWo, sampleCachesWi, &pdf);
}

// Modo: sample, its caches on the stack as MoonRay has them: a frame of its own (tools/port_flake_caches.py).
static noinline varying Color
StochasticFlakesBsdfLobe_sampleOnStack(const varying BsdfLobe * uniform lobe,
                                       const varying BsdfSlice &slice,
                                       varying float r1, varying float r2,
                                       varying Vec3f &wi, varying float &pdf)
{
    varying FlakeCaches sampleCachesWo, sampleCachesWi;
    return StochasticFlakesBsdfLobe_sampleWith(lobe, slice, r1, r2, wi, pdf, sampleCachesWo, sampleCachesWi);
}

varying Color
StochasticFlakesBsdfLobe_sample(const varying BsdfLobe * uniform lobe,
                                const varying BsdfSlice &slice,
                                varying float r1, varying float r2,
                                varying Vec3f &wi, varying float &pdf)
{
    // Modo: the two caches on the heap, as eval's (tools/port_flake_caches.py).
    const uniform intptr_t held = CPP_modoFlakeCaches(2 * sizeof(varying FlakeCaches));
    if (held != 0) {
        varying FlakeCaches * uniform caches = (varying FlakeCaches * uniform)held;
        return StochasticFlakesBsdfLobe_sampleWith(lobe, slice, r1, r2, wi, pdf, caches[0], caches[1]);
    }
    return StochasticFlakesBsdfLobe_sampleOnStack(lobe, slice, r1, r2, wi, pdf);
}
'''

CPP_INCLUDE_OLD = '''#include "BsdfSlice.h"
'''
CPP_INCLUDE_NEW = '''#include "BsdfSlice.h"
#include "ModoFlakeCaches.h"

#include <cstdint>
#include <cstdlib>
#ifdef _WIN32
#include <malloc.h>
#endif

// Modo: the stochastic flake lobe's two reflection caches, the calling thread's own, on the heap: as varying locals
// they made a frame (about 2.8 MB) bigger than a Windows thread's stack. Allocated the first time (64-byte aligned),
// grown if more is asked, kept for the thread's life; 0 with MOONRAY_MODO_FLAKE_CACHES=0, or where none could be had
// (tools/port_flake_caches.py).
extern "C" intptr_t
CPP_modoFlakeCaches(int64_t bytes)
{
    struct Held {
        void *block = nullptr;
        int64_t size = 0;
        static void release(void *block)
        {
#ifdef _WIN32
            _aligned_free(block);
#else
            std::free(block);
#endif
        }
        ~Held() { release(block); }
    };
    if (!moonray::shading::modoFlakeCaches() || bytes <= 0) {
        return 0;
    }
    thread_local Held held;
    if (held.size < bytes) {
        Held::release(held.block);
        const size_t size = (static_cast<size_t>(bytes) + 63) & ~static_cast<size_t>(63);
#ifdef _WIN32
        held.block = _aligned_malloc(size, 64);
#else
        held.block = std::aligned_alloc(64, size);
#endif
        held.size = held.block ? bytes : 0;
    }
    return reinterpret_cast<intptr_t>(held.block);
}
'''

EDITS = {
    'ispc/bsdf/BsdfStochasticFlakes.ispc': [(ISPC_DECLARATION_OLD, ISPC_DECLARATION_NEW, 1), (EVAL_OLD, EVAL_NEW, 1),
                                            (SAMPLE_OLD, SAMPLE_NEW, 1), (SAMPLE_WI_OLD, SAMPLE_WI_NEW, 1),
                                            (SAMPLE_END_OLD, SAMPLE_END_NEW, 1)],
    'bsdf/Bsdf.cc': [(CPP_INCLUDE_OLD, CPP_INCLUDE_NEW, 1)],
}


def patch_text(name, text, edits):
    for old, new, count in edits:
        for ending in ('\n', '\r\n'):
            o, n = old.replace('\n', ending), new.replace('\n', ending)
            if n in text:
                break
            if text.count(o) == count:
                text = text.replace(o, n)
                break
        else:
            raise RuntimeError('Flake caches anchor missing or ambiguous in %s: %r' % (name, old[:80]))
    return text


def main():
    header = HEADER_TEXT.replace('\n', '\r\n')
    if not HEADER.exists() or HEADER.read_bytes().decode('utf-8') != header:
        HEADER.write_bytes(header.encode('utf-8'))
        print('wrote', HEADER.relative_to(SHADING))
    for name, edits in EDITS.items():
        source = SHADING / name
        text = source.read_bytes().decode('utf-8')
        patched = patch_text(name, text, edits)
        if patched != text:
            source.write_bytes(patched.encode('utf-8'))
            print('patched', name)
        else:
            print('already in', name)


if __name__ == '__main__':
    main()
