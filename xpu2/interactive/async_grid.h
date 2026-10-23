// The work grid and its cellular rules (spec §7-8), host side.
//
// The image is cut into square cells (64 px by default). Each cell holds its
// unstarted work as a queue of chunks, ordered by sample range and then tile, so
// a cell converges evenly. Cells start owned in a CPU/GPU checkerboard. Every
// claim is one atomic on a cursor in host memory: a chunk is claimed exactly
// once (CA-06), and nothing is ever shared across PCIe. The GPU lane's broker
// (async_render.h) claims here on the GPU's behalf and hands the chunks to the
// device through its mailbox ring, so stealing in either direction needs no
// cross-device atomics (MBX-03).
//
// CPU workers move by the cellular rules: finish the cell they are in, step to
// the same-owner neighbour under the most pressure, steal from the hottest
// opposite-owner neighbour, then drift to the hottest cell anywhere. Pressure
// is the cell's unclaimed work. Ownership persists across frames and flips
// towards the device that rendered most of a cell (CA-10, CA-12).
#pragma once
#include "async_integrator.h"
#include <algorithm>
#include <atomic>
#include <memory>
#include <stdexcept>
#include <vector>

namespace xpu2::interactive::async {

enum class Device : U32 { Cpu = 0, Gpu = 1 };

struct GridOptions {
    U32 cellSize = 64;        // pixels; a multiple of 8 (GRD-01)
    U32 samplesPerChunk = 4;  // sample indices per chunk
    int mode = 2;             // 0 CPU only, 1 GPU only, 2 both
};

class Grid {
public:
    struct Cell {
        U32 x = 0, y = 0;
        Device owner = Device::Cpu;
        std::vector<Chunk> chunks;
        alignas(64) std::atomic<U32> next{0};
        std::atomic<U64> samples[2] = {};  // rendered per device, for ownership flips
    };

    Grid(U32 width, U32 height, U32 spp, GridOptions options, const std::vector<Device>* owners = nullptr)
        : width_(width), height_(height), spp_(spp), options_(options) {
        if (!width || !height || !spp || !options.cellSize || options.cellSize % TileSize ||
            !options.samplesPerChunk || options.mode < 0 || options.mode > 2)
            throw std::invalid_argument("Invalid work grid");
        cellsX_ = (width + options.cellSize - 1) / options.cellSize;
        cellsY_ = (height + options.cellSize - 1) / options.cellSize;
        const U32 tilesX = (width + TileSize - 1) / TileSize, tilesY = (height + TileSize - 1) / TileSize;
        const U32 tilesPerCell = options.cellSize / TileSize;
        cells_ = std::vector<Cell>(cellsX_ * cellsY_);
        if (owners && owners->size() != cells_.size()) owners = nullptr;
        for (U32 cy = 0; cy < cellsY_; ++cy)
            for (U32 cx = 0; cx < cellsX_; ++cx) {
                Cell& cell = cells_[cy * cellsX_ + cx];
                const U32 index = cy * cellsX_ + cx;
                cell.x = cx;
                cell.y = cy;
                cell.owner = options.mode == 0   ? Device::Cpu
                             : options.mode == 1 ? Device::Gpu
                             : owners            ? (*owners)[index]
                                                 : ((cx + cy) % 2 == 0 ? Device::Gpu : Device::Cpu);  // GRD-02
                for (U32 first = 0; first < spp; first += options.samplesPerChunk)
                    for (U32 ty = cy * tilesPerCell; ty < std::min(tilesY, (cy + 1) * tilesPerCell); ++ty)
                        for (U32 tx = cx * tilesPerCell; tx < std::min(tilesX, (cx + 1) * tilesPerCell); ++tx)
                            cell.chunks.push_back({ty * tilesX + tx, first,
                                                   std::min(options.samplesPerChunk, spp - first), index});
                total_ += cell.chunks.size();
            }
    }
    Grid(const Grid&) = delete;

    U32 width() const { return width_; }
    U32 height() const { return height_; }
    U32 spp() const { return spp_; }
    U32 cellCount() const { return U32(cells_.size()); }
    U64 totalChunks() const { return total_; }
    const Cell& cell(U32 index) const { return cells_[index]; }
    Device owner(U32 index) const { return cells_[index].owner; }

    U32 remaining(U32 index) const {
        const Cell& c = cells_[index];
        const U32 taken = c.next.load(std::memory_order_acquire);
        return taken >= c.chunks.size() ? 0 : U32(c.chunks.size()) - taken;
    }
    bool empty() const {
        for (U32 i = 0; i < cells_.size(); ++i)
            if (remaining(i)) return false;
        return true;
    }

    // Claims up to n chunks of one cell. Returns how many were claimed.
    U32 claim(U32 index, U32 n, Chunk* out) {
        Cell& c = cells_[index];
        const U32 size = U32(c.chunks.size());
        U32 start = c.next.load(std::memory_order_relaxed);
        do {
            if (start >= size) return 0;
        } while (!c.next.compare_exchange_weak(start, std::min(size, start + n), std::memory_order_acq_rel,
                                               std::memory_order_relaxed));
        const U32 got = std::min(size, start + n) - start;
        std::copy_n(c.chunks.begin() + start, got, out);
        return got;
    }

    void rendered(U32 index, Device device, U64 samples) {
        cells_[index].samples[U32(device)].fetch_add(samples, std::memory_order_relaxed);
    }

    // The CPU worker decision loop (CA rules, spec §8). Returns the cell to work
    // in next, or ~0u when no unclaimed work is left anywhere.
    U32 choose(Device device, U32 current, U32 salt) const {
        if (current < cells_.size() && remaining(current)) return current;  // Finish
        U32 best = ~0u, bestWork = 0;
        auto consider = [&](U32 index, bool sameOwner) {
            if ((owner(index) == device) != sameOwner) return;
            const U32 work = remaining(index);
            // Ties break by a hash of (cell, salt), so workers spread out (CA-07).
            if (work > bestWork || (work == bestWork && work && hash(index, salt) > hash(best, salt))) {
                best = index;
                bestWork = work;
            }
        };
        if (current < cells_.size()) {
            for (bool sameOwner : {true, false}) {  // Neighbour, then steal from a neighbour
                forNeighbours(current, [&](U32 n) { consider(n, sameOwner); });
                if (best != ~0u) return best;
            }
        }
        for (bool sameOwner : {true, false}) {  // Drift to the hottest cell anywhere
            for (U32 i = 0; i < cells_.size(); ++i) consider(i, sameOwner);
            if (best != ~0u) return best;
        }
        return ~0u;
    }

    // Cells for the GPU broker, hottest first: its own cells, then the CPU's.
    std::vector<U32> brokerOrder(Device device) const {
        std::vector<U32> order;
        for (U32 i = 0; i < cells_.size(); ++i)
            if (remaining(i)) order.push_back(i);
        std::sort(order.begin(), order.end(), [&](U32 a, U32 b) {
            const bool ownA = owner(a) == device, ownB = owner(b) == device;
            if (ownA != ownB) return ownA;
            return remaining(a) > remaining(b);
        });
        return order;
    }

    // Starting cell for the w-th of n workers on a device: spread over its cells.
    U32 seed(Device device, U32 worker, U32 workers) const {
        std::vector<U32> own;
        for (U32 i = 0; i < cells_.size(); ++i)
            if (owner(i) == device) own.push_back(i);
        if (own.empty()) return choose(device, ~0u, worker);
        return own[(size_t(worker) * own.size()) / std::max(1u, workers)];
    }

private:
    template <class F>
    void forNeighbours(U32 index, F f) const {
        const int x = int(index % cellsX_), y = int(index / cellsX_);
        for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx) {
                const int nx = x + dx, ny = y + dy;
                if ((dx || dy) && nx >= 0 && ny >= 0 && nx < int(cellsX_) && ny < int(cellsY_))
                    f(U32(ny) * cellsX_ + U32(nx));
            }
    }
    static U32 hash(U32 a, U32 b) {
        U32 h = a * 0x9e3779b1u ^ (b + 0x7f4a7c15u + (a << 6) + (a >> 2));
        h ^= h >> 16;
        h *= 0x85ebca6bu;
        h ^= h >> 13;
        return h;
    }

    U32 width_, height_, spp_, cellsX_ = 0, cellsY_ = 0;
    GridOptions options_;
    std::vector<Cell> cells_;
    U64 total_ = 0;
};

// Cell ownership that persists from frame to frame (GRD-03) and flips towards
// the device that rendered most of a cell (CA-10), with the supervisor's
// limits: at most 8 flips a frame, a 16-frame cooldown, and a 64-frame freeze
// after thrashing (CA-12).
class Ownership {
public:
    // The owners for a new frame of a grid with `cells` cells; empty for the
    // checkerboard.
    const std::vector<Device>* owners(U32 cells) const {
        return owners_.size() == cells ? &owners_ : nullptr;
    }

    // Records a finished frame and decides the flips for the next one.
    void finished(const Grid& grid) {
        const U32 n = grid.cellCount();
        if (owners_.size() != n) {
            owners_.resize(n);
            history_.assign(size_t(n) * Window, 0.f);
            lastFlip_.assign(n, -1000000);
            for (U32 i = 0; i < n; ++i) owners_[i] = grid.owner(i);
        }
        for (U32 i = 0; i < n; ++i) {
            const double cpu = double(grid.cell(i).samples[0].load()), gpu = double(grid.cell(i).samples[1].load());
            history_[size_t(i) * Window + frame_ % Window] = cpu + gpu > 0 ? float(gpu / (cpu + gpu)) : 0.5f;
        }
        ++frame_;
        if (frame_ < frozenUntil_ || frame_ < Window) return;
        struct Candidate { U32 cell; float share; };
        std::vector<Candidate> flips;
        for (U32 i = 0; i < n; ++i) {
            if (frame_ - lastFlip_[i] < 16) continue;  // cooldown
            float gpuShare = 0;
            for (U32 k = 0; k < Window; ++k) gpuShare += history_[size_t(i) * Window + k];
            gpuShare /= Window;
            const float other = owners_[i] == Device::Cpu ? gpuShare : 1 - gpuShare;
            if (other > 0.6f) flips.push_back({i, other});
        }
        std::sort(flips.begin(), flips.end(), [](auto a, auto b) { return a.share > b.share; });
        // At most 8 flips a frame (CA-10), and never more than 10% of the cells, so
        // the first thrash rule of CA-12 holds by construction; the second (a cell
        // flipping back within 32 frames) freezes ownership for 64 frames.
        const size_t limit = std::min<size_t>(8, std::max<size_t>(1, n / 10));
        for (size_t k = 0; k < flips.size() && k < limit; ++k) {
            const U32 i = flips[k].cell;
            if (frame_ - lastFlip_[i] < 32) {
                frozenUntil_ = frame_ + 64;
                return;
            }
            owners_[i] = owners_[i] == Device::Cpu ? Device::Gpu : Device::Cpu;
            lastFlip_[i] = frame_;
        }
    }

private:
    static constexpr U32 Window = 8;
    std::vector<Device> owners_;
    std::vector<float> history_;
    std::vector<long long> lastFlip_;
    long long frame_ = 0, frozenUntil_ = 0;
};

}  // namespace xpu2::interactive::async
