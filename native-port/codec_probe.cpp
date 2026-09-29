#include <scene_rdl2/render/cache/ValueContainerUtils.h>
#include <scene_rdl2/scene/rdl2/ValueContainerUtil.h>
#include <array>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <limits>
#include <vector>

template<class Codec> bool check()
{
    struct Case { std::uint64_t value; std::vector<unsigned char> bytes; };
    const Case cases[] = {
        {0, {0}}, {127, {127}}, {128, {128, 1}},
        {5368709120ULL, {128, 128, 128, 128, 20}},
        {std::numeric_limits<std::uint64_t>::max(), {255,255,255,255,255,255,255,255,255,1}}
    };
    for (const auto& sample : cases) {
        std::array<unsigned char, 16> buffer{};
        auto count = Codec::variableLengthEncoding(sample.value, buffer.data());
        if (count != sample.bytes.size() || std::memcmp(buffer.data(), sample.bytes.data(), count)) return false;
        std::uint64_t decoded = 0;
        if (Codec::variableLengthDecoding(buffer.data(), decoded) != count || decoded != sample.value) return false;
    }
    const std::int64_t signedCases[] = {0, -1, 1, -5368709120LL, 5368709120LL,
        std::numeric_limits<std::int64_t>::min(), std::numeric_limits<std::int64_t>::max()};
    for (auto sample : signedCases) {
        std::array<unsigned char, 16> buffer{};
        auto count = Codec::variableLengthEncoding(sample, buffer.data());
        std::int64_t decoded = 0;
        if (Codec::variableLengthDecoding(buffer.data(), decoded) != count || decoded != sample) return false;
        if (sample == -1 && (count != 1 || buffer[0] != 1)) return false;
        if (sample == std::numeric_limits<std::int64_t>::min() && (count != 10 || buffer[9] != 1)) return false;
    }
    return true;
}
int main()
{
    if (!check<scene_rdl2::cache::ValueContainerUtil>() || !check<scene_rdl2::rdl2::ValueContainerUtil>()) {
        std::fputs("FAIL: incompatible 64-bit scene/cache encoding\n", stderr);
        return 1;
    }
    std::puts("PASS: both MoonRay codecs preserve 64-bit values and expected wire bytes on Windows.");
}
