// Test real MoonRay SIMD code on the AVX-only host; this is not a renderer.
#include <scene_rdl2/common/math/avx.h>
#include "avx_probe_ispc.h"
#include <cstdint>
#include <cstdio>
#include <limits>

#if !defined(__AVX__) || defined(__AVX2__) || defined(__FMA__)
#error This probe must be compiled for AVX without AVX2 or FMA
#endif
static_assert(VLEN == 8, "C++ and ISPC must retain eight lanes");

int main()
{
    alignas(32) int values[8] = {0, 1, -1, 8388608, -8388608,
        std::numeric_limits<int>::min(), std::numeric_limits<int>::max(), -123456789};
    int ispcShift[8] = {};
    ispc::moonray_probe_shift(values, ispcShift, 8);
    const simd::avxi input(values);
    const simd::avxi shifted = simd::sra(input, 23);
    const simd::avxi product = input * simd::avxi(3);
    for (int i = 0; i < 8; ++i) {
        const int expected = values[i] >= 0 ? values[i] / 8388608 :
            static_cast<int>(-((-static_cast<std::int64_t>(values[i]) + 8388607) / 8388608));
        const auto expectedProduct = static_cast<std::uint32_t>(values[i]) * 3u;
        if (shifted[i] != expected || ispcShift[i] != expected ||
            static_cast<std::uint32_t>(product[i]) != expectedProduct) {
            std::fprintf(stderr, "AVX result mismatch in lane %d\n", i);
            return 1;
        }
    }
    std::puts("PASS: MoonRay AVX1 integer fallback and eight-lane ISPC execute natively on Windows.");
    return 0;
}
