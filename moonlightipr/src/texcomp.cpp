// ISPC Texture Compressor's C++ side (upstream/ISPCTextureCompressor, Copyright 2016-2019 Intel Corporation, MIT; see
// THIRD_PARTY.md), over the kernel objects build_moonlightipr.py makes with the toolchain's ISPC, for SSE2 (which every
// 64-bit processor has) up to AVX2, the best the processor has chosen as it runs. As XPU2 builds it (xpu2_bc6h.cc).
#include "ispc_texcomp.cpp"

// ISPC's code probes a large stack by MSVC's name; MinGW has the same routine under its own.
__asm__(".globl __chkstk; __chkstk: jmp ___chkstk_ms");
