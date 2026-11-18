// The outlines of the work as few rectangles, for the kit's lines (xpu2_session.cc's Outlines): where the GPU has handed
// samples on and they still wait (async_cpu.h HandoffTiles), as @@MODO_DEFERRED_TILES and @@MODO_PROVISIONAL_TILES. A line
// holds at most 512 rectangles (the kit's buckets.parse), so the 8-pixel tiles are joined: runs along each row of tiles,
// and a run joined to the same span in the row before it. Where that is still too many, squares of 64, 256, ... pixels
// holding them stand for them. No Modo, MoonRay or GPU code: checked by outline_blocks_test.cc.
#pragma once
#include <algorithm>
#include <cstdint>
#include <map>
#include <tuple>
#include <utility>
#include <vector>

namespace xpu2::interactive::outline {

// In the film's coordinates, which are MoonRay's (rows from the bottom), half open.
struct Rect {
    std::uint32_t x0, y0, x1, y1;
    bool operator<(const Rect& o) const { return std::tie(x0, y0, x1, y1) < std::tie(o.x0, o.y0, o.x1, o.y1); }
    bool operator==(const Rect& o) const { return x0 == o.x0 && y0 == o.y0 && x1 == o.x1 && y1 == o.y1; }
};

// Squares `side` pixels a side, perRow of them a row, numbered row by row and given in ascending order, as rectangles:
// each run along a row, joined to a run of the same span in the row just before it.
inline std::vector<Rect> blocks(const std::vector<std::uint32_t>& units, std::uint32_t perRow, std::uint32_t side,
                                std::uint32_t width, std::uint32_t height) {
    std::vector<Rect> out;
    if (!perRow || !side) return out;
    // The rectangles that end at the row before (by their span) and at this row.
    std::map<std::pair<std::uint32_t, std::uint32_t>, size_t> before, here;
    std::uint32_t row = ~0u;
    for (size_t i = 0; i < units.size();) {
        size_t j = i + 1;
        while (j < units.size() && units[j] == units[j - 1] + 1 && units[j] / perRow == units[i] / perRow) ++j;
        const std::uint32_t r = units[i] / perRow;
        if (r != row) {
            if (row != ~0u && r == row + 1) before.swap(here);
            else before.clear();
            here.clear();
            row = r;
        }
        const std::uint32_t x0 = units[i] % perRow * side, x1 = std::min((units[j - 1] % perRow + 1) * side, width);
        const std::uint32_t y0 = r * side, y1 = std::min(y0 + side, height);
        if (x0 < x1 && y0 < y1) {
            const auto span = std::make_pair(x0, x1);
            const auto k = before.find(span);
            if (k != before.end()) {
                out[k->second].y1 = y1;
                here[span] = k->second;
                before.erase(k);
            } else {
                here[span] = out.size();
                out.push_back({x0, y0, x1, y1});
            }
        }
        i = j;
    }
    return out;
}

// An image's 8-pixel tiles (numbered row by row, ascending) as at most `most` rectangles: themselves joined where that
// many hold them, else the squares of 64, 256, ... pixels that hold any of them; cut at `most` where even the largest
// do not fit.
inline std::vector<Rect> tileBlocks(const std::vector<std::uint32_t>& tiles, std::uint32_t width, std::uint32_t height,
                                    size_t most = 512) {
    constexpr std::uint32_t Tile = 8;
    if (!width || !height) return {};
    const std::uint32_t tilesX = (width + Tile - 1) / Tile;
    std::vector<Rect> out = blocks(tiles, tilesX, Tile, width, height);
    for (std::uint32_t side = 64; out.size() > most; side *= 4) {
        const std::uint32_t perRow = (width + side - 1) / side;
        std::vector<std::uint32_t> units;
        units.reserve(tiles.size());
        for (std::uint32_t t : tiles) units.push_back((t / tilesX * Tile / side) * perRow + t % tilesX * Tile / side);
        std::sort(units.begin(), units.end());
        units.erase(std::unique(units.begin(), units.end()), units.end());
        out = blocks(units, perRow, side, width, height);
        if (side >= std::max(width, height)) break;
    }
    if (out.size() > most) out.resize(most);
    return out;
}

}  // namespace xpu2::interactive::outline
