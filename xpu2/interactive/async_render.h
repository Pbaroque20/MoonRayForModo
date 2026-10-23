// The asynchronous renderer's coordinator (spec §4, §8, §15 throughput mode).
//
// The CPU lane's workers claim their own chunks from the grid. This thread is
// the GPU lane's feeder and broker: it keeps two launches queued, sizes each
// from the GPU's measured rate (the donation forecast, CA-08), claims the GPU's
// own cells first and then the CPU's hottest (stealing), and near the end
// splits what is left so both devices finish together (the lookahead). It
// never waits on the GPU; it polls. At quiescence (CA-16) the two films merge
// and every pixel's sample count is audited (ACC-07).
#pragma once
#include "async_cpu.h"
#include "async_gpu.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <timeapi.h>

namespace xpu2::interactive::async {

struct RenderOptions {
    unsigned threads = 12;  // CPU lane workers
    int mode = 2;           // 0 CPU only, 1 GPU only, 2 both
    GridOptions grid{};
    double windowMs = 10;   // target duration of one GPU launch (throughput mode, THR-03)
    U32 firstChunks = 2048; // the first launches, before the GPU's rate is known
    // With both devices, one of the threads is the GPU feeder's own core (spec §4
    // reserves cores for the coordinator and feeder): it polls without sleeping.
    bool reserveFeederCore = true;
};

// When things happened in a frame, in seconds from its start (TEL-01).
struct Timeline {
    double firstLaunch = -1, gridEmpty = -1, lastGpuCompletion = -1, cpuDone = -1, filmLanded = -1;
};

struct RenderResult {
    std::vector<float> rgba;
    U64 cpuSamples = 0, gpuSamples = 0, parkedRun = 0, launches = 0, cpuSteals = 0, cpuMoves = 0,
        gpuStolenChunks = 0, fineLoaded = 0, fineEvicted = 0;
    double seconds = 0, gpuItemsPerSecond = 0, cpuSamplesPerSecond = 0;
    unsigned cpuWorkers = 0;
    Timeline timeline;
    double cpuBusySeconds = 0, cpuSlowestChunk = 0, cpuFirstClaim = 0, cpuLastClaim = 0;
    bool failed = false;
    std::string error;
};

class Renderer {
public:
    Renderer(cpu::PlanView plan, const CpuScene& cpuScene, GpuLane* gpu)
        : plan_(std::move(plan)), cpuScene_(cpuScene), gpu_(gpu) {
        timeBeginPeriod(1);  // millisecond sleeps for the feeder's polling
    }
    ~Renderer() { timeEndPeriod(1); }

    RenderResult render(const RenderOptions& o) {
        using Clock = std::chrono::steady_clock;
        RenderResult result;
        const auto config = mixed::config(plan_);
        const bool useGpu = o.mode != 0, useCpu = o.mode != 1;
        cpu::need(!useGpu || gpu_, "GPU lane required");
        GridOptions gridOptions = o.grid;
        gridOptions.mode = o.mode;
        // Ownership carried over from earlier frames of the same grid (GRD-03).
        const U32 cells = ((plan_->width + gridOptions.cellSize - 1) / gridOptions.cellSize) *
                          ((plan_->height + gridOptions.cellSize - 1) / gridOptions.cellSize);
        Grid grid(plan_->width, plan_->height, plan_->spp, gridOptions, ownership_.owners(cells));
        HostFilm film(plan_->width, plan_->height);
        RetryQueue retries;
        const U32 itemsPerChunk = gridOptions.samplesPerChunk * TilePixels;
        if (useGpu) gpu_->begin(gridOptions.samplesPerChunk);

        // The feeder runs above the CPU lane's workers, so a busy CPU never starves
        // the GPU of work (spec §4: the GPU feeder runs at high priority).
        struct Priority {
            int old = GetThreadPriority(GetCurrentThread());
            Priority() { SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST); }
            ~Priority() { SetThreadPriority(GetCurrentThread(), old); }
        } priority;
        // With a reserved core the feeder is pinned to the last logical processor
        // and the workers to the others (spec §4, CPU-01): a spinning high-priority
        // feeder must never sit on a worker's core.
        DWORD_PTR process = 0, system = 0, workerMask = 0;
        struct Pin {
            DWORD_PTR old = 0;
            void to(DWORD_PTR mask) { old = SetThreadAffinityMask(GetCurrentThread(), mask); }
            ~Pin() { if (old) SetThreadAffinityMask(GetCurrentThread(), old); }
        } pin;
        const unsigned workers = !useCpu ? 0 : (useGpu && o.reserveFeederCore && o.threads > 1 ? o.threads - 1 : o.threads);
        result.cpuWorkers = workers;
        if (useGpu && useCpu && o.reserveFeederCore && GetProcessAffinityMask(GetCurrentProcess(), &process, &system) &&
            process && (process & (process - 1))) {
            DWORD_PTR feeder = DWORD_PTR(1) << (8 * sizeof(DWORD_PTR) - 1);  // the highest allowed processor
            while (!(process & feeder)) feeder >>= 1;
            workerMask = process & ~feeder;
            pin.to(feeder);
        }
        if (!cpu_ || cpu_->threads() != workers || cpuAffinity_ != workerMask) {
            cpu_.reset();
            cpu_ = std::make_unique<CpuLane>(cpuScene_, workers, workerMask);
            cpuAffinity_ = workerMask;
        }
        CpuLane& cpuLane = *cpu_;
        const auto start = Clock::now();
        auto at = [&] { return std::chrono::duration<double>(Clock::now() - start).count(); };
        cpuLane.begin(config, grid, film, retries);

        double gpuRate = 0;  // chunk items a second, timed on the device, smoothed
        U64 queuedItems = 0, gpuItems = 0, stalls = 0, lastParked = 0;
        std::vector<Chunk> claim;
        std::string failure;
        while (failure.empty()) {
            if (useGpu) {
                Completion c;
                while (gpu_->poll(c)) {
                    queuedItems -= c.items;
                    gpuItems += c.items;
                    // Launches too small to keep the GPU full understate its rate.
                    if (c.deviceSeconds > 0 && c.items >= U64(o.firstChunks) * itemsPerChunk / 2) {
                        const double rate = double(c.items + c.parkedRun) / c.deviceSeconds;
                        gpuRate = gpuRate ? 0.7 * gpuRate + 0.3 * rate : rate;
                    }
                    if (c.errors) failure = "GPU sample failure; whole epoch must use fallback";
                    result.timeline.lastGpuCompletion = at();
                    ++result.launches;
                    result.parkedRun += c.parkedRun;
                }
                while (failure.empty() && gpu_->ready()) {
                    const U32 want = launchSize(o, grid, gpuRate, cpuLane, itemsPerChunk, queuedItems, start);
                    claim.resize(want);
                    U32 got = 0;
                    if (want) {
                        const auto order = grid.brokerOrder(Device::Gpu);
                        // Spread a launch over the hottest cells, so the image converges evenly.
                        const U32 quota = std::max<U32>(1, want / std::max<size_t>(1, order.size()));
                        for (int pass = 0; pass < 2 && got < want; ++pass)
                            for (U32 cell : order) {
                                if (got >= want) break;
                                const U32 n = grid.claim(cell, pass ? want - got : std::min(quota, want - got), claim.data() + got);
                                if (n && grid.owner(cell) != Device::Gpu) result.gpuStolenChunks += n;
                                got += n;
                            }
                    }
                    for (U32 i = 0; i < got; ++i) {
                        U64 samples = 0;
                        for (U32 p = 0; p < TilePixels; ++p)
                            samples += tilePixel(claim[i].tile, p, config.width, config.height) != ~0u ? claim[i].count : 0;
                        grid.rendered(claim[i].cell, Device::Gpu, samples);
                    }
                    if (!gpu_->launch(claim.data(), got)) break;
                    if (result.timeline.firstLaunch < 0) result.timeline.firstLaunch = at();
                    queuedItems += U64(got) * itemsPerChunk;
                    // A parked queue that does not shrink across many launches means
                    // the cache cannot hold what the samples need.
                    if (!got && gpu_->parkedOutstanding() >= lastParked && ++stalls > 256)
                        failure = "Fine-detail cache cannot hold the working set; use fallback";
                    lastParked = gpu_->parkedOutstanding();
                }
            }
            if (cpuLane.counters.failures.load()) failure = "CPU sample failure; whole epoch must use fallback";
            const bool empty = grid.empty();
            if (empty && result.timeline.gridEmpty < 0) result.timeline.gridEmpty = at();
            const bool cpuQuiet = cpuLane.idle() == cpuLane.threads() && !retries.size();
            if (empty && cpuQuiet && result.timeline.cpuDone < 0) result.timeline.cpuDone = at();
            const bool gpuQuiet = !useGpu || (gpu_->inFlight() == 0 && gpu_->parkedOutstanding() == 0);
            if (empty && gpuQuiet && cpuQuiet) break;
            // The feeder polls: on its own core it never sleeps; otherwise a short sleep.
            if (useGpu && (o.reserveFeederCore || !useCpu)) std::this_thread::yield();
            else Sleep(1);
        }
        if (!failure.empty()) cpuLane.cancel();
        cpuLane.finish();
        cpuLane.waitParked();  // the frame's grid and film outlive every worker's use
        if (!failure.empty()) {
            result.failed = true;
            result.error = failure;
            return result;
        }
        if (useGpu) {
            gpu_->downloadFilm();
            while (!gpu_->filmReady()) std::this_thread::yield();
            result.timeline.filmLanded = at();
        }
        result.seconds = std::chrono::duration<double>(Clock::now() - start).count();

        // Merge and audit: every pixel has exactly spp samples (ACC-07).
        const size_t pixels = size_t(plan_->width) * plan_->height;
        result.rgba.resize(pixels * 4);
        const auto& hs = film.sums();
        const auto& hc = film.counts();
        for (size_t i = 0; i < pixels; ++i) {
            const U32 gc = useGpu ? gpu_->counts()[i] : 0, count = hc[i] + gc;
            if (count != plan_->spp) {
                result.failed = true;
                result.error = "Sample audit failure at pixel " + std::to_string(i) + ": " + std::to_string(count);
                return result;
            }
            for (int c = 0; c < 4; ++c) {
                const double sum = hs[i * 4 + c] + (useGpu ? gpu_->sums()[i * 4 + c] : 0.0);
                result.rgba[i * 4 + c] = float(sum / count);
            }
            result.cpuSamples += hc[i];
            result.gpuSamples += gc;
        }
        result.cpuSteals = cpuLane.counters.steals.load();
        result.cpuBusySeconds = cpuLane.counters.busyMicros.load() * 1e-6;
        result.cpuSlowestChunk = cpuLane.counters.slowestChunkMicros.load() * 1e-6;
        result.cpuFirstClaim = cpuLane.counters.firstClaimMicros.load() == ~0ull ? -1 : cpuLane.counters.firstClaimMicros.load() * 1e-6;
        result.cpuLastClaim = cpuLane.counters.lastClaimMicros.load() * 1e-6;
        result.cpuMoves = cpuLane.counters.moves.load();
        result.gpuItemsPerSecond = gpuRate;
        result.cpuSamplesPerSecond = result.seconds > 0 ? double(result.cpuSamples) / result.seconds : 0;
        if (useGpu) {
            result.fineLoaded = gpu_->fineLoaded();
            result.fineEvicted = gpu_->fineEvicted();
        }
        ownership_.finished(grid);
        return result;
    }

private:
    // How many chunks the next GPU launch takes: about one window of the GPU's
    // measured work; near the end, the share that lets both devices finish at
    // the same moment, given what the GPU already has queued.
    U32 launchSize(const RenderOptions& o, const Grid& grid, double gpuRate, const CpuLane& cpuLane, U32 itemsPerChunk,
                   U64 queuedItems, std::chrono::steady_clock::time_point start) const {
        U64 remainingChunks = 0;
        for (U32 i = 0; i < grid.cellCount(); ++i) remainingChunks += grid.remaining(i);
        if (!remainingChunks) return 0;
        const U64 cap = gpu_->maxChunksPerLaunch();
        if (!gpuRate) return U32(std::min<U64>({cap, remainingChunks, o.firstChunks}));
        U64 want = U64(gpuRate * o.windowMs / 1000.0 / itemsPerChunk);
        want = std::max<U64>(want, 16);
        if (cpuLane.threads()) {
            const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
            const double cpuRate = elapsed > 0.01 ? double(cpuLane.counters.samples.load()) / elapsed : 0;
            const double remainingItems = double(remainingChunks) * itemsPerChunk;
            // GPU share L so that (queued + L) / gpuRate == (remaining - L) / cpuRate.
            const double share = (remainingItems * gpuRate - double(queuedItems) * cpuRate) / (gpuRate + cpuRate);
            if (share <= 0) return 0;
            want = std::min<U64>(want, U64(share / itemsPerChunk) + 1);
        }
        return U32(std::min<U64>({want, cap, remainingChunks}));
    }

    cpu::PlanView plan_;
    const CpuScene& cpuScene_;
    GpuLane* gpu_;
    Ownership ownership_;
    std::unique_ptr<CpuLane> cpu_;  // persistent workers (spec §4)
    DWORD_PTR cpuAffinity_ = 0;
};

}  // namespace xpu2::interactive::async
