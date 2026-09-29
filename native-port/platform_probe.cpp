#include <scene_rdl2/common/platform/Platform.h>
#include <scene_rdl2/common/platform/WindowsEndian.h>
#include <scene_rdl2/render/util/Files.h>
#include <scene_rdl2/common/rec_time/RecTime.h>
#include <scene_rdl2/common/fb_util/PixelBuffer.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <windows.h>

int main()
{
    {
        scene_rdl2::fb_util::PixelBuffer<float> pixels;
        pixels.init(64, 64);
        pixels.clear(0.25f);
        auto shared = pixels;
        pixels.init(128, 128);
        if (shared.getPixel(5, 5) != 0.25f) return 11;
        pixels.cleanUp();
        shared.cleanUp();
    }
    for (std::size_t alignment : {16u, 32u, 64u, 128u}) {
        void* memory = scene_rdl2::util::alignedMalloc(4097, alignment);
        if (!memory || reinterpret_cast<std::uintptr_t>(memory) % alignment) return 1;
        std::memset(memory, 0xa5, 4097);
        if (static_cast<unsigned char*>(memory)[4096] != 0xa5) return 2;
        scene_rdl2::util::alignedFree(memory);
    }
    std::uint64_t be = htobe64(UINT64_C(0x0102030405060708));
    const unsigned char expected[] = {1,2,3,4,5,6,7,8};
    if (std::memcmp(&be, expected, 8) || be64toh(be) != UINT64_C(0x0102030405060708)) return 3;
    if (be16toh(htobe16(0x1234)) != 0x1234 || be32toh(htobe32(0x12345678)) != 0x12345678) return 4;
    const char* absolutePaths[] = {"C:\\render\\image.exr", "\\\\server\\share\\image.exr", "C:/render/image.exr"};
    for (const auto* path : absolutePaths) {
        if (!scene_rdl2::util::isAbsolute(path)) {
            std::fprintf(stderr, "Absolute path rejected: %s\n", path);
            return 5;
        }
    }
    const char* relativePaths[] = {"relative/image.exr", "C:image.exr", "", "\\image.exr"};
    for (const auto* path : relativePaths) if (scene_rdl2::util::isAbsolute(path)) return 7;
    const auto t0 = scene_rdl2::rec_time::RecTimeVDSO::getCurrentNanoSec();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if (scene_rdl2::rec_time::RecTimeVDSO::getCurrentNanoSec() <= t0) return 6;
    const auto testDir = std::filesystem::temp_directory_path() /
        ("moonray-write-probe-" + std::to_string(GetCurrentProcessId()));
    const auto file = testDir / "sub folder" / "render.png";
    if (!scene_rdl2::util::writeTest(file.u8string(), true) || std::filesystem::exists(file)) return 8;
    { std::ofstream stream(file, std::ios::binary); stream << "preserve existing content"; }
    if (!scene_rdl2::util::writeTest(file.u8string(), true)) return 9;
    std::ifstream stream(file, std::ios::binary);
    std::string contents((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    stream.close();
    if (contents != "preserve existing content") return 10;
    std::filesystem::remove(file);
    std::filesystem::remove(file.parent_path());
    std::filesystem::remove(testDir);
    std::puts("PASS: native allocation, endian encoding, paths, and non-destructive output write checks.");
}
