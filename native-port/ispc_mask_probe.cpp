#include <immintrin.h>
#include <cstdio>
#include "ispc_mask_probe.h"
using MaskedSum = int (*)(int, int, int, int, int, int, const __m256i*);
int main() {
    auto function = reinterpret_cast<MaskedSum>(ispc::getMaskedSum());
    alignas(32) const __m256i fullMask = _mm256_set1_epi32(-1);
    alignas(32) const __m256i halfMask = _mm256_setr_epi32(-1, -1, -1, -1, 0, 0, 0, 0);
    const int all = function(1, 2, 3, 4, 5, 6, &fullMask);
    const int half = function(1, 2, 3, 4, 5, 6, &halfMask);
    std::printf("ISPC mask results: all=%d half=%d\n", all, half);
    return all == 56 && half == 30 ? 0 : 1;
}
