// Pictures made ready for the graphics card: smaller copies of each (mip levels) and compression (BC7 for pictures of
// bytes, BC6H for those of floats), by Intel's ISPC Texture Compressor (upstream/ISPCTextureCompressor, MIT; see
// THIRD_PARTY.md), whose kernels build_moonlightipr.py compiles with the toolchain's ISPC for SSE2 up to AVX2. Every step
// is spread over the processor's cores, a band of rows to each.
#include "moonlightipr/moonlightipr.h"

#include "ispc_texcomp.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace moonlightipr {
namespace {

// fn(first, last) over rows [0, count), in bands, on every core.
template <typename Fn>
void inBands(uint32_t count, uint32_t step, Fn fn) {
    const uint32_t cores = std::max(1u, std::thread::hardware_concurrency());
    const uint32_t bands = (count + step - 1) / step;
    if (bands <= 1 || cores == 1) { fn(0u, count); return; }
    std::atomic<uint32_t> next{0};
    std::vector<std::thread> workers;
    for (uint32_t i = 0; i < std::min(cores, bands); ++i)
        workers.emplace_back([&] {
            for (uint32_t band; (band = next++) < bands;) fn(band * step, std::min(count, (band + 1) * step));
        });
    for (std::thread& worker : workers) worker.join();
}

float fromSrgbValue(float c) { return c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f); }
float toSrgbValue(float c) { return c <= 0.0031308f ? c * 12.92f : 1.055f * std::pow(c, 1.0f / 2.4f) - 0.055f; }

struct SrgbTable {
    float linear[256];
    SrgbTable() { for (int i = 0; i < 256; ++i) linear[i] = fromSrgbValue(i / 255.0f); }
};
const SrgbTable& srgbTable() { static const SrgbTable table; return table; }

unsigned char toByte(float v) { return static_cast<unsigned char>(std::lround(std::min(1.0f, std::max(0.0f, v)) * 255.0f)); }

uint16_t half(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, 4);
    const uint32_t sign = (bits >> 16) & 0x8000u;
    int exponent = int((bits >> 23) & 0xff) - 127 + 15;
    uint32_t mantissa = bits & 0x7fffffu;
    if (((bits >> 23) & 0xff) == 0xff) return uint16_t(sign | 0x7c00u | (mantissa ? 0x200u : 0u));
    if (exponent >= 31) return uint16_t(sign | 0x7c00u);
    if (exponent <= 0) {
        if (exponent < -10) return uint16_t(sign);
        mantissa |= 0x800000u;
        const uint32_t shift = uint32_t(14 - exponent);
        uint32_t value16 = mantissa >> shift;
        if ((mantissa >> (shift - 1)) & 1u) ++value16;
        return uint16_t(sign | value16);
    }
    uint32_t value16 = (uint32_t(exponent) << 10) | (mantissa >> 13);
    if (mantissa & 0x1000u) ++value16;      // rounds into the exponent where it must
    return uint16_t(sign | value16);
}

// One level half the size of the one given (each side halved, at least 1), each texel the mean of the two by two
// beneath it, as light: bytes from sRGB where they are sRGB, and back.
std::vector<unsigned char> halvedBytes(const std::vector<unsigned char>& in, uint32_t width, uint32_t height, bool srgb,
                                       uint32_t& w, uint32_t& h) {
    w = std::max(1u, width / 2);
    h = std::max(1u, height / 2);
    std::vector<unsigned char> out(size_t(w) * h * 4);
    const float* table = srgbTable().linear;
    inBands(h, 64, [&](uint32_t first, uint32_t last) {
        for (uint32_t y = first; y < last; ++y)
            for (uint32_t x = 0; x < w; ++x) {
                float sum[4] = {0, 0, 0, 0};
                for (uint32_t dy = 0; dy < 2; ++dy)
                    for (uint32_t dx = 0; dx < 2; ++dx) {
                        const uint32_t sx = std::min(width - 1, x * 2 + dx), sy = std::min(height - 1, y * 2 + dy);
                        const unsigned char* p = &in[(size_t(sy) * width + sx) * 4];
                        for (int c = 0; c < 3; ++c) sum[c] += srgb ? table[p[c]] : p[c] / 255.0f;
                        sum[3] += p[3] / 255.0f;
                    }
                unsigned char* o = &out[(size_t(y) * w + x) * 4];
                for (int c = 0; c < 3; ++c) o[c] = toByte(srgb ? toSrgbValue(sum[c] * 0.25f) : sum[c] * 0.25f);
                o[3] = toByte(sum[3] * 0.25f);
            }
    });
    return out;
}

std::vector<float> halvedFloats(const std::vector<float>& in, uint32_t width, uint32_t height, uint32_t& w, uint32_t& h) {
    w = std::max(1u, width / 2);
    h = std::max(1u, height / 2);
    std::vector<float> out(size_t(w) * h * 4);
    inBands(h, 64, [&](uint32_t first, uint32_t last) {
        for (uint32_t y = first; y < last; ++y)
            for (uint32_t x = 0; x < w; ++x) {
                float sum[4] = {0, 0, 0, 0};
                for (uint32_t dy = 0; dy < 2; ++dy)
                    for (uint32_t dx = 0; dx < 2; ++dx) {
                        const uint32_t sx = std::min(width - 1, x * 2 + dx), sy = std::min(height - 1, y * 2 + dy);
                        const float* p = &in[(size_t(sy) * width + sx) * 4];
                        for (int c = 0; c < 4; ++c) sum[c] += p[c];
                    }
                for (int c = 0; c < 4; ++c) out[(size_t(y) * w + x) * 4 + c] = sum[c] * 0.25f;
            }
    });
    return out;
}

std::vector<unsigned char> halvesOf(const std::vector<float>& rgba, uint32_t width, uint32_t height) {
    std::vector<unsigned char> out(size_t(width) * height * 8);
    uint16_t* to = reinterpret_cast<uint16_t*>(out.data());
    inBands(height, 64, [&](uint32_t first, uint32_t last) {
        for (size_t i = size_t(first) * width * 4; i < size_t(last) * width * 4; ++i) to[i] = half(rgba[i]);
    });
    return out;
}

// Each band of block rows compressed on its own core: 16 bytes a block of 4 x 4, in raster order.
std::vector<unsigned char> compressed(const std::vector<unsigned char>& texels, uint32_t width, uint32_t height, bool floats, bool alpha) {
    std::vector<unsigned char> out(size_t(width / 4) * (height / 4) * 16);
    const uint32_t texel = floats ? 8 : 4;
    bc7_enc_settings bc7;
    bc6h_enc_settings bc6h;
    if (floats) GetProfile_bc6h_veryfast(&bc6h);
    else if (alpha) GetProfile_alpha_veryfast(&bc7);
    else GetProfile_veryfast(&bc7);
    inBands(height, 64, [&](uint32_t first, uint32_t last) {
        rgba_surface surface;
        surface.ptr = const_cast<uint8_t*>(texels.data() + size_t(first) * width * texel);
        surface.width = int32_t(width);
        surface.height = int32_t(last - first);
        surface.stride = int32_t(width * texel);
        uint8_t* to = out.data() + size_t(first / 4) * (width / 4) * 16;
        if (floats) { bc6h_enc_settings own = bc6h; CompressBlocksBC6H(&surface, to, &own); }
        else { bc7_enc_settings own = bc7; CompressBlocksBC7(&surface, to, &own); }
    });
    return out;
}

bool quarters(uint32_t width, uint32_t height) { return width % 4 == 0 && height % 4 == 0; }

}  // namespace

PreparedTexture prepareTexture(const TextureDesc& desc, bool mips, bool compress) {
    if (!desc.pixels || !desc.width || !desc.height || desc.width > 16384 || desc.height > 16384)
        throw std::runtime_error("MoonLightIPR texture has no pixels or is too large");
    PreparedTexture made;
    // The brightness grid from the picture as given, as the card's light sampling has always had it.
    made.gridWidth = std::min<uint32_t>(desc.width, 64);
    made.gridHeight = std::min<uint32_t>(desc.height, 64);
    made.brightness.assign(size_t(made.gridWidth) * made.gridHeight, 0.0f);
    {
        // A band of grid rows to each core, so that no two add to the same cell.
        inBands(made.gridHeight, 1, [&](uint32_t first, uint32_t last) {
            const uint32_t from = uint32_t(uint64_t(first) * desc.height / made.gridHeight);
            const uint32_t to = uint32_t(uint64_t(last) * desc.height / made.gridHeight);
            for (uint32_t y = from; y < to; ++y)
                for (uint32_t x = 0; x < desc.width; ++x) {
                    const size_t i = (size_t(y) * desc.width + x) * 4;
                    float rgb[3];
                    for (int c = 0; c < 3; ++c)
                        rgb[c] = desc.floatData ? static_cast<const float*>(desc.pixels)[i + c] : static_cast<const unsigned char*>(desc.pixels)[i + c] / 255.0f;
                    const float value = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
                    const size_t cell = size_t(uint64_t(y) * made.gridHeight / desc.height) * made.gridWidth + size_t(uint64_t(x) * made.gridWidth / desc.width);
                    if (std::isfinite(value) && value > 0.0f) made.brightness[cell] += value;
                }
        });
    }
    made.srgb = desc.srgb && !desc.floatData;
    uint32_t width = desc.width, height = desc.height;
    const size_t count = size_t(width) * height;
    if (desc.floatData) {
        std::vector<float> rgba(static_cast<const float*>(desc.pixels), static_cast<const float*>(desc.pixels) + count * 4);
        while (desc.maxSize && std::max(width, height) > desc.maxSize) rgba = halvedFloats(rgba, width, height, width, height);
        // BC6H holds no alpha, nothing below 0 and nothing past a half's range.
        std::atomic<bool> fits{compress && quarters(width, height)};
        if (fits) inBands(height, 64, [&](uint32_t first, uint32_t last) {
            for (size_t i = size_t(first) * width; i < size_t(last) * width && fits; ++i) {
                const float* p = &rgba[i * 4];
                if (!(p[0] >= 0.0f && p[0] <= 65504.0f && p[1] >= 0.0f && p[1] <= 65504.0f && p[2] >= 0.0f && p[2] <= 65504.0f) || p[3] != 1.0f) fits = false;
            }
        });
        made.format = fits ? PreparedTexture::BC6H : PreparedTexture::Halves;
        made.width = width;
        made.height = height;
        for (;;) {
            const std::vector<unsigned char> halves = halvesOf(rgba, width, height);
            made.levels.push_back(fits ? compressed(halves, width, height, true, false) : halves);
            if (!mips || (width == 1 && height == 1)) break;
            uint32_t w, h;
            std::vector<float> next = halvedFloats(rgba, width, height, w, h);
            if (fits && !quarters(w, h)) break;
            rgba.swap(next);
            width = w;
            height = h;
        }
        return made;
    }
    std::vector<unsigned char> bytes(static_cast<const unsigned char*>(desc.pixels), static_cast<const unsigned char*>(desc.pixels) + count * 4);
    while (desc.maxSize && std::max(width, height) > desc.maxSize) bytes = halvedBytes(bytes, width, height, made.srgb, width, height);
    const bool fits = compress && quarters(width, height);
    bool alpha = false;
    if (fits) for (size_t i = 3; i < bytes.size(); i += 4) if (bytes[i] != 255) { alpha = true; break; }
    made.format = fits ? PreparedTexture::BC7 : PreparedTexture::Bytes;
    made.width = width;
    made.height = height;
    for (;;) {
        if (!mips || (width == 1 && height == 1)) { made.levels.push_back(fits ? compressed(bytes, width, height, false, alpha) : std::move(bytes)); break; }
        uint32_t w, h;
        std::vector<unsigned char> next = halvedBytes(bytes, width, height, made.srgb, w, h);
        made.levels.push_back(fits ? compressed(bytes, width, height, false, alpha) : std::move(bytes));
        if (fits && !quarters(w, h)) break;
        bytes.swap(next);
        width = w;
        height = h;
    }
    return made;
}

size_t preparedBytes(uint32_t width, uint32_t height, bool floatData, bool mips, bool compress) {
    const bool fits = compress && quarters(width, height);
    size_t total = 0;
    for (;;) {
        total += fits ? size_t(width / 4) * (height / 4) * 16 : size_t(width) * height * (floatData ? 8 : 4);
        if (!mips || (width == 1 && height == 1)) break;
        width = std::max(1u, width / 2);
        height = std::max(1u, height / 2);
        if (fits && !quarters(width, height)) break;
    }
    return total;
}

namespace {
const char MAGIC[4] = {'M', 'L', 'T', '1'};
const uint32_t VERSION = 1;
}

bool writePreparedTexture(const std::string& path, const PreparedTexture& texture) {
    const std::string staged = path + ".part";
    {
        std::ofstream out(staged, std::ios::binary | std::ios::trunc);
        if (!out) return false;
        const uint32_t head[8] = {VERSION, texture.width, texture.height, uint32_t(texture.format), texture.srgb ? 1u : 0u,
                                  uint32_t(texture.levels.size()), texture.gridWidth, texture.gridHeight};
        out.write(MAGIC, 4);
        out.write(reinterpret_cast<const char*>(head), sizeof(head));
        out.write(reinterpret_cast<const char*>(texture.brightness.data()), std::streamsize(texture.brightness.size() * sizeof(float)));
        for (const auto& level : texture.levels) {
            const uint64_t size = level.size();
            out.write(reinterpret_cast<const char*>(&size), 8);
            out.write(reinterpret_cast<const char*>(level.data()), std::streamsize(level.size()));
        }
        if (!out) return false;
    }
    std::remove(path.c_str());
    return std::rename(staged.c_str(), path.c_str()) == 0;
}

bool readPreparedTexture(const std::string& path, PreparedTexture& texture) {
    std::ifstream in(path, std::ios::binary);
    char magic[4] = {};
    uint32_t head[8] = {};
    if (!in.read(magic, 4) || std::memcmp(magic, MAGIC, 4) != 0 || !in.read(reinterpret_cast<char*>(head), sizeof(head)) || head[0] != VERSION)
        return false;
    if (head[3] > PreparedTexture::BC6H || !head[1] || !head[2] || head[1] > 16384 || head[2] > 16384 || !head[5] || head[5] > 16
        || head[6] > 64 || head[7] > 64)
        return false;
    texture = PreparedTexture();
    texture.width = head[1];
    texture.height = head[2];
    texture.format = PreparedTexture::Format(head[3]);
    texture.srgb = head[4] != 0;
    texture.gridWidth = head[6];
    texture.gridHeight = head[7];
    texture.brightness.resize(size_t(head[6]) * head[7]);
    if (!in.read(reinterpret_cast<char*>(texture.brightness.data()), std::streamsize(texture.brightness.size() * sizeof(float)))) return false;
    uint32_t width = texture.width, height = texture.height;
    const bool blocks = texture.format == PreparedTexture::BC7 || texture.format == PreparedTexture::BC6H;
    for (uint32_t i = 0; i < head[5]; ++i) {
        uint64_t size = 0;
        if (!in.read(reinterpret_cast<char*>(&size), 8)) return false;
        const size_t expected = blocks ? size_t(width / 4) * (height / 4) * 16
                                       : size_t(width) * height * (texture.format == PreparedTexture::Halves ? 8 : 4);
        if (size != expected) return false;
        texture.levels.emplace_back(size_t(size));
        if (!in.read(reinterpret_cast<char*>(texture.levels.back().data()), std::streamsize(size))) return false;
        width = std::max(1u, width / 2);
        height = std::max(1u, height / 2);
    }
    return true;
}

}  // namespace moonlightipr
