// Scheduler invariants of the asynchronous renderer's work grid (spec VER-5).
// Prints one JSON line; exits non-zero on the first failed check.
#include "async_grid.h"
#include <cstdio>
#include <set>
#include <thread>
using namespace xpu2::interactive::async;

static int failures = 0;
static void check(bool ok, const char* what) {
    if (!ok) {
        std::fprintf(stderr, "FAILED: %s\n", what);
        ++failures;
    }
}

// Every (pixel, sample index) of the image is covered by exactly one claimed chunk.
static void exactlyOnce(U32 width, U32 height, U32 spp, GridOptions options, unsigned workers) {
    Grid grid(width, height, spp, options);
    std::vector<std::vector<Chunk>> claimed(workers + 1);
    std::vector<std::thread> threads;
    for (unsigned w = 0; w < workers; ++w)
        threads.emplace_back([&, w] {
            U32 cell = grid.seed(Device::Cpu, w, workers);
            for (;;) {
                cell = grid.choose(Device::Cpu, cell, w);
                if (cell == ~0u) break;
                Chunk c;
                if (grid.claim(cell, 1, &c)) claimed[w].push_back(c);
            }
        });
    // The broker claims in bulk from its own cells first, then steals.
    std::vector<Chunk> buffer(97);
    while (!grid.empty())
        for (U32 cell : grid.brokerOrder(Device::Gpu)) {
            const U32 n = grid.claim(cell, U32(buffer.size()), buffer.data());
            claimed[workers].insert(claimed[workers].end(), buffer.begin(), buffer.begin() + n);
        }
    for (auto& t : threads) t.join();
    std::vector<U32> samples(size_t(width) * height, 0);
    std::set<std::pair<U32, U32>> seen;
    U64 chunks = 0;
    bool unique = true;
    for (auto& list : claimed)
        for (const Chunk& c : list) {
            ++chunks;
            unique &= seen.insert({c.tile, c.first}).second;
            for (U32 p = 0; p < TilePixels; ++p) {
                const U32 pixel = tilePixel(c.tile, p, width, height);
                if (pixel != ~0u) samples[pixel] += c.count;
            }
        }
    check(unique, "no chunk is claimed twice");
    check(chunks == grid.totalChunks(), "every chunk is claimed");
    bool full = true;
    for (U32 s : samples) full &= s == spp;
    check(full, "every pixel gets exactly spp samples");
}

int main() {
    exactlyOnce(384, 288, 64, {}, 12);
    exactlyOnce(1920, 1080, 16, {64, 4, 2}, 12);
    exactlyOnce(100, 37, 9, {32, 4, 2}, 5);  // ragged edges, a partial last chunk
    exactlyOnce(64, 64, 7, {64, 3, 0}, 3);   // CPU only

    // Checkerboard seeding (GRD-02) and the cellular rules (CA rules, spec §8).
    Grid grid(256, 256, 4, {64, 4, 2});
    check(grid.owner(0) == Device::Gpu && grid.owner(1) == Device::Cpu && grid.owner(4) == Device::Cpu &&
              grid.owner(5) == Device::Gpu,
          "checkerboard seeding");
    const U32 start = 1;  // a CPU cell
    check(grid.choose(Device::Cpu, start, 0) == start, "finish the current cell first");
    std::vector<Chunk> drain(grid.remaining(start));
    grid.claim(start, U32(drain.size()), drain.data());
    const U32 next = grid.choose(Device::Cpu, start, 0);
    check(next != start && grid.owner(next) == Device::Cpu, "then a same-owner neighbour");
    // Empty every CPU cell: the CPU then steals from a GPU neighbour.
    for (U32 i = 0; i < grid.cellCount(); ++i)
        if (grid.owner(i) == Device::Cpu) {
            std::vector<Chunk> rest(grid.remaining(i) + 1);
            grid.claim(i, U32(rest.size()), rest.data());
        }
    const U32 stolen = grid.choose(Device::Cpu, start, 0);
    check(stolen != ~0u && grid.owner(stolen) == Device::Gpu, "then steal from the other device");
    const auto order = grid.brokerOrder(Device::Gpu);
    check(!order.empty() && grid.owner(order.front()) == Device::Gpu, "broker takes its own cells first");

    // Ownership flips towards the device that rendered most of a cell (CA-10),
    // at most 8 a frame, never more than 10% of cells at once (CA-12).
    Ownership ownership;
    for (int frame = 0; frame < 12; ++frame) {
        Grid g(1024, 1024, 4, {64, 4, 2}, ownership.owners(256));
        for (U32 i = 0; i < g.cellCount(); ++i) g.rendered(i, Device::Gpu, 100);  // the GPU did everything
        ownership.finished(g);
    }
    Grid after(1024, 1024, 4, {64, 4, 2}, ownership.owners(256));
    U32 cpuCells = 0;
    for (U32 i = 0; i < after.cellCount(); ++i) cpuCells += after.owner(i) == Device::Cpu;
    check(cpuCells < 128 && cpuCells >= 128 - 8 * 5, "flips move cells to the GPU, at most 8 a frame");

    std::printf("{\"status\":\"%s\",\"failures\":%d}\n", failures ? "failed" : "passed", failures);
    return failures ? 1 : 0;
}
