// Checks of the outlines' rectangles (outline_blocks.h): where the GPU's handed-on samples wait, as the kit is told of
// it. The rectangles must cover exactly the tiles given where they fit in a line, and hold them all, in at most 512,
// where they do not.
//
// Built and run from the MoonRayForModo tree (MSYS2 UCRT64 toolchain on PATH):
//   g++ -std=c++20 -O2 -o outline_blocks_test.exe xpu2/interactive/outline_blocks_test.cc
//   outline_blocks_test.exe
// Prints a line a check and a summary; exits non-zero on a failure.
#include "outline_blocks.h"
#include <cstdio>
#include <random>
#include <set>
#include <string>

using namespace xpu2::interactive;
using U32 = std::uint32_t;

static int failures = 0, checks = 0;
static void check(bool ok, const std::string& what) {
    ++checks;
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what.c_str());
    if (!ok) ++failures;
}

// The image's pixels the rectangles cover, a count each.
static std::vector<int> painted(const std::vector<outline::Rect>& rects, U32 width, U32 height) {
    std::vector<int> p(size_t(width) * height, 0);
    for (const auto& r : rects)
        for (U32 y = r.y0; y < r.y1 && y < height; ++y)
            for (U32 x = r.x0; x < r.x1 && x < width; ++x) ++p[size_t(y) * width + x];
    return p;
}
// The pixels the tiles hold.
static std::vector<int> tilePixels(const std::vector<U32>& tiles, U32 width, U32 height) {
    std::vector<int> p(size_t(width) * height, 0);
    const U32 tilesX = (width + 7) / 8;
    for (U32 t : tiles)
        for (U32 y = t / tilesX * 8; y < std::min(t / tilesX * 8 + 8, height); ++y)
            for (U32 x = t % tilesX * 8; x < std::min(t % tilesX * 8 + 8, width); ++x) p[size_t(y) * width + x] = 1;
    return p;
}
static bool inside(const std::vector<outline::Rect>& rects, U32 width, U32 height) {
    for (const auto& r : rects)
        if (!(r.x0 < r.x1 && r.y0 < r.y1 && r.x1 <= width && r.y1 <= height)) return false;
    return true;
}

int main() {
    // Nothing: no rectangle.
    check(outline::tileBlocks({}, 100, 60).empty(), "no tiles, no rectangles");
    check(outline::tileBlocks({0}, 0, 60).empty(), "an image of no size, no rectangles");

    // One tile, at the image's edge: cut to the image.
    {
        // 20 x 10: tiles 3 a row; tile 5 is row 1, column 2: x 16..20, y 8..10.
        const auto r = outline::tileBlocks({5}, 20, 10);
        check(r.size() == 1 && r[0] == outline::Rect{16, 8, 20, 10}, "an edge tile is cut to the image");
    }

    // A run along a row is one rectangle; a block of rows of the same span is one.
    {
        const U32 width = 64, height = 64;  // 8 tiles a row
        std::vector<U32> tiles;
        for (U32 y = 2; y < 5; ++y)
            for (U32 x = 1; x < 4; ++x) tiles.push_back(y * 8 + x);
        const auto r = outline::tileBlocks(tiles, width, height);
        check(r.size() == 1 && r[0] == outline::Rect{8, 16, 32, 40}, "a 3 x 3 block of tiles is one rectangle");
        check(painted(r, width, height) == tilePixels(tiles, width, height), "the block covers its tiles exactly");
    }

    // Two runs on a row stay two; a gap of a row breaks the join.
    {
        // 4 tiles a row (32 px): rows 0 and 1 hold columns 0-1 and 3, row 2 none, row 3 columns 0-1.
        const std::vector<U32> tiles = {0, 1, 3, 4, 5, 7, 12, 13};
        const auto r = outline::tileBlocks(tiles, 32, 64);
        check(r.size() == 3 && r[0] == outline::Rect{0, 0, 16, 16} && r[1] == outline::Rect{24, 0, 32, 16} &&
                  r[2] == outline::Rect{0, 24, 16, 32},
              "runs: two spans joined down two rows, one after a gap row (" + std::to_string(r.size()) + ")");
        check(painted(r, 32, 64) == tilePixels(tiles, 32, 64), "they cover their tiles exactly, once each");
    }

    // Random sets that fit: covered exactly, never twice, inside the image.
    {
        std::mt19937 rng(7);
        bool exact = true, within = true;
        for (int round = 0; round < 200; ++round) {
            const U32 width = 8 + rng() % 300, height = 8 + rng() % 200, tilesX = (width + 7) / 8, tilesY = (height + 7) / 8;
            std::set<U32> pick;
            const U32 n = rng() % (tilesX * tilesY + 1);
            for (U32 k = 0; k < n; ++k) pick.insert(rng() % (tilesX * tilesY));
            const std::vector<U32> tiles(pick.begin(), pick.end());
            const auto r = outline::tileBlocks(tiles, width, height, 1u << 30);
            exact = exact && painted(r, width, height) == tilePixels(tiles, width, height);
            within = within && inside(r, width, height);
        }
        check(exact, "200 random sets: every tile's pixels covered once, no other pixel");
        check(within, "200 random sets: every rectangle inside its image");
    }

    // Too many for a line (a checkerboard of a 4K frame's tiles): at most 512, still holding every tile.
    {
        const U32 width = 3840, height = 2160, tilesX = 480, tilesY = 270;
        std::vector<U32> tiles;
        for (U32 y = 0; y < tilesY; ++y)
            for (U32 x = 0; x < tilesX; ++x)
                if ((x + y) % 2 == 0) tiles.push_back(y * tilesX + x);
        const auto r = outline::tileBlocks(tiles, width, height);
        check(r.size() <= 512, "a 4K checkerboard fits a line (" + std::to_string(r.size()) + " rectangles)");
        const auto p = painted(r, width, height), t = tilePixels(tiles, width, height);
        bool holds = true, once = true;
        for (size_t i = 0; i < p.size(); ++i) {
            if (t[i] && !p[i]) holds = false;
            if (p[i] > 1) once = false;
        }
        check(holds, "the coarser squares hold every tile");
        check(once, "the coarser squares never overlap");
        check(inside(r, width, height), "the coarser squares stay inside the image");
    }

    // Scattered tiles over a large frame, few enough: kept as tiles (not coarsened).
    {
        std::vector<U32> tiles;
        for (U32 k = 0; k < 300; ++k) tiles.push_back(k * 431);
        std::sort(tiles.begin(), tiles.end());
        const auto r = outline::tileBlocks(tiles, 3840, 2160);
        check(r.size() == 300, "300 lone tiles stay 300 rectangles of 8 pixels");
        bool small = true;
        for (const auto& q : r) small = small && q.x1 - q.x0 <= 8 && q.y1 - q.y0 <= 8;
        check(small, "each of them a tile's size");
    }

    std::printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}
