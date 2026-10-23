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
#include "async_adaptive.h"
#include "async_cpu.h"
#include "async_gpu.h"
#include <functional>
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
    unsigned treeThreads = ~0u;  // adaptive frames: pool threads besides the feeder for the error trees (~0u: one per region)
    // Adaptive frames with a GPU: make every pass on the device (the pass chain),
    // or, false, on the host between the GPU's passes.
    bool deviceChain = true;
};

// When things happened in a frame, in seconds from its start (TEL-01).
struct Timeline {
    double firstLaunch = -1, gridEmpty = -1, lastGpuCompletion = -1, cpuDone = -1, filmLanded = -1;
};

// One GPU launch: when it was queued and collected, in seconds from the frame's
// start, its chunks and parked samples, and its own duration on the device.
struct LaunchTrace {
    double queued = -1, collected = -1, deviceSeconds = 0;
    double claimSeconds = 0, accountSeconds = 0, launchSeconds = 0;  // the feeder's time to claim, account and queue it
    U64 chunks = 0, parked = 0;
};

// One adaptive pass: its samples, and when it went out, completed, and when the
// errors after it were asked for, arrived and became trees (-1: did not happen).
struct PassTrace {
    U64 samples = 0;
    double generated = -1, launched = -1, completed = -1, asked = -1, errors = -1, trees = -1;
};

struct RenderResult {
    std::vector<float> rgba;
    std::vector<U32> counts;  // samples each pixel received
    std::vector<float> odd;   // adaptive frames: odd-index sums over all samples (MoonRay's beauty aux)
    U64 cpuSamples = 0, gpuSamples = 0, parkedRun = 0, launches = 0, cpuSteals = 0, cpuMoves = 0,
        gpuStolenChunks = 0, fineLoaded = 0, fineEvicted = 0;
    double seconds = 0, gpuItemsPerSecond = 0, cpuSamplesPerSecond = 0;
    unsigned cpuWorkers = 0;
    Timeline timeline;
    // Adaptive frames: passes generated, tree updates, and samples a pixel on average.
    U32 adaptivePasses = 0, treeUpdates = 0;
    double meanSamples = 0;
    double treeSeconds = 0, errorSeconds = 0;  // rebuilding the trees; from asking for errors to having them
    U32 chainStalls = 0;  // times the GPU's pass chain waited for texture tiles
    double chainStages[4] = {};  // profiled chains: seconds in errors, trees, masks, renders
    std::vector<double> chainRenders;  // profiled chains: each step's render
    std::vector<PassTrace> passes;
    std::vector<LaunchTrace> launchTrace;
    double cpuBusySeconds = 0, cpuSlowestChunk = 0, cpuFirstClaim = 0, cpuLastClaim = 0;
    bool failed = false;
    std::string error;
};

// Persistent threads for the adaptive error trees: run(n, f) calls f(0) .. f(n - 1)
// across them and the calling thread, and returns once every call has.
class Pool {
public:
    explicit Pool(unsigned threads) {
        for (unsigned i = 0; i < threads; ++i) threads_.emplace_back([this] { loop(); });
    }
    ~Pool() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stop_ = true;
        }
        wake_.notify_all();
        for (auto& t : threads_) t.join();
    }
    unsigned size() const { return unsigned(threads_.size()); }
    void run(unsigned n, const std::function<void(unsigned)>& f) {
        {
            // A worker still inside the last run would take this one's indices.
            std::unique_lock<std::mutex> lock(mutex_);
            left_.wait(lock, [&] { return active_ == 0; });
            task_ = &f;
            count_ = n;
            next_.store(0);
            ++generation_;
        }
        wake_.notify_all();
        work(f, n);
        std::unique_lock<std::mutex> lock(mutex_);
        left_.wait(lock, [&] { return active_ == 0 && finished_ == n; });
        finished_ = 0;
        task_ = nullptr;
    }

private:
    void work(const std::function<void(unsigned)>& f, unsigned n) {
        unsigned done = 0;
        for (unsigned i; (i = next_.fetch_add(1)) < n; ++done) f(i);
        std::lock_guard<std::mutex> lock(mutex_);
        finished_ += done;
        left_.notify_all();
    }
    void loop() {
        SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_ABOVE_NORMAL);
        unsigned seen = 0;
        for (;;) {
            const std::function<void(unsigned)>* task;
            unsigned n;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                wake_.wait(lock, [&] { return stop_ || (task_ && generation_ != seen); });
                if (stop_) return;
                seen = generation_;
                task = task_;
                n = count_;
                ++active_;
            }
            work(*task, n);
            std::lock_guard<std::mutex> lock(mutex_);
            --active_;
            left_.notify_all();
        }
    }
    std::mutex mutex_;
    std::condition_variable wake_, left_;
    const std::function<void(unsigned)>* task_ = nullptr;
    unsigned count_ = 0, generation_ = 0, active_ = 0, finished_ = 0;
    std::atomic<unsigned> next_{0};
    bool stop_ = false;
    std::vector<std::thread> threads_;
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
        const bool adaptive = plan_->adaptive;
        // In an adaptive frame with a GPU, the CPU rebuilds the error trees and the
        // GPU takes every sample: the chain of passes, each waiting on the trees,
        // bounds the frame, and a CPU chunk would sit on that chain.
        const bool useGpu = o.mode != 0, useCpu = o.mode != 1 && !(adaptive && useGpu);
        cpu::need(!useGpu || gpu_, "GPU lane required");
        GridOptions gridOptions = o.grid;
        gridOptions.mode = useCpu ? (useGpu ? 2 : 0) : 1;
        // Ownership carried over from earlier frames of the same grid (GRD-03).
        const U32 cells = ((plan_->width + gridOptions.cellSize - 1) / gridOptions.cellSize) *
                          ((plan_->height + gridOptions.cellSize - 1) / gridOptions.cellSize);
        Grid grid(plan_->width, plan_->height, plan_->spp, gridOptions, ownership_.owners(cells), adaptive);
        HostFilm film(plan_->width, plan_->height);
        RetryQueue retries;
        const U32 itemsPerChunk = gridOptions.samplesPerChunk * TilePixels;
        if (useGpu) gpu_->begin(gridOptions.samplesPerChunk, adaptive);
        Adaptive state(*plan_, gridOptions.samplesPerChunk);
        if (adaptive) {
            const unsigned trees = o.treeThreads != ~0u ? o.treeThreads : std::max(1u, std::min(o.threads, 16u) - 1);
            if (!pool_ || pool_->size() != trees) pool_ = std::make_unique<Pool>(trees);
            state.start = Clock::now();
            if (useGpu && o.deviceChain && gpu_->hasChain()) state.startChain(*gpu_, tileOrder(gridOptions.cellSize));
            else state.generateReady(grid, useGpu ? gpu_ : nullptr);
        }

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
        cpuLane.begin(config, grid, film, retries, adaptive ? &state.tables : nullptr);

        double gpuRate = 0;  // chunk items a second, timed on the device, smoothed
        U64 queuedItems = 0, gpuItems = 0, stalls = 0, lastParked = 0;
        std::vector<Chunk> claim;
        std::vector<U64> cellSamples(grid.cellCount(), 0);  // the GPU's claims, for the ownership accounting
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
                    if (result.launches < result.launchTrace.size()) {
                        auto& l = result.launchTrace[result.launches];
                        l.collected = at();
                        l.deviceSeconds = c.deviceSeconds;
                        l.parked = c.parkedRun;
                    }
                    ++result.launches;
                    result.parkedRun += c.parkedRun;
                }
                while (failure.empty() && gpu_->ready()) {
                    const double claimStart = at();
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
                    const double accountStart = at();
                    // Each chunk's samples: its tile's pixels in the image (an adaptive
                    // pass's mask holds only those) times its sample count.
                    for (U32 i = 0; i < got; ++i) {
                        const Chunk& k = claim[i];
                        const U64 pixels = adaptive ? U64(__builtin_popcountll(state.tables.masks[chunkPass(k) % PassSlots][k.tile]))
                                                    : grid.tilePixels(k.tile);
                        cellSamples[k.cell] += pixels * k.count;
                    }
                    for (U32 c = 0; c < cellSamples.size(); ++c)
                        if (cellSamples[c]) {
                            grid.rendered(c, Device::Gpu, cellSamples[c]);
                            cellSamples[c] = 0;
                        }
                    const double launchStart = at();
                    if (!gpu_->launch(claim.data(), got)) break;
                    if (result.timeline.firstLaunch < 0) result.timeline.firstLaunch = at();
                    result.launchTrace.push_back({at(), -1, 0, accountStart - claimStart, launchStart - accountStart,
                                                  at() - launchStart, got, 0});
                    if (adaptive && got && grid.empty()) state.trace[state.generated - 1].launched = state.at();
                    queuedItems += U64(got) * itemsPerChunk;
                    // A parked queue that does not shrink across many launches means
                    // the cache cannot hold what the samples need.
                    if (!got && gpu_->parkedOutstanding() >= lastParked && ++stalls > 256)
                        failure = "Fine-detail cache cannot hold the working set; use fallback";
                    lastParked = gpu_->parkedOutstanding();
                }
            }
            if (cpuLane.counters.failures.load()) failure = "CPU sample failure; whole epoch must use fallback";
            if (adaptive) {
                const U64 before = useGpu ? gpu_->launchCount() : 0;
                state.advance(grid, film, useGpu ? gpu_ : nullptr, *pool_);
                if (state.chain && gpu_->launchCount() > before) {  // the pass chain went out: one flight
                    if (result.timeline.firstLaunch < 0) result.timeline.firstLaunch = at();
                    result.launchTrace.push_back({at(), -1, 0, 0, 0, 0, 0, 0});
                }
            }
            const bool empty = grid.empty() && (!adaptive || state.finished(useGpu ? gpu_ : nullptr));
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

        // Merge and audit: every pixel has exactly the samples planned for it, spp
        // in a uniform frame (ACC-07).
        const size_t pixels = size_t(plan_->width) * plan_->height;
        result.rgba.resize(pixels * 4);
        result.counts.resize(pixels);
        if (adaptive) result.odd.resize(pixels * 4);
        const auto& hs = film.sums();
        const auto& hc = film.counts();
        U64 planned = 0;
        for (size_t i = 0; i < pixels; ++i) {
            const U32 gc = useGpu ? gpu_->counts()[i] : 0, count = hc[i] + gc;
            const U32 expected = !adaptive ? plan_->spp : state.chain ? gpu_->chainPlanned()[i] : state.planned[i];
            result.counts[i] = count;
            planned += expected;
            if (count != expected || !count) {
                result.failed = true;
                result.error = "Sample audit failure at pixel " + std::to_string(i) + ": " + std::to_string(count);
                return result;
            }
            for (int c = 0; c < 4; ++c) {
                const double sum = hs[i * 4 + c] + (useGpu ? gpu_->sums()[i * 4 + c] : 0.0);
                result.rgba[i * 4 + c] = float(sum / count);
                if (adaptive)
                    result.odd[i * 4 + c] = float((film.odd()[i * 4 + c] + (useGpu ? gpu_->odd()[i * 4 + c] : 0.0)) / count);
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
        result.adaptivePasses = state.generated;
        result.treeUpdates = state.treeUpdates;
        if (state.chain) {
            const auto& s = gpu_->chainState();
            result.adaptivePasses = state.uniformEnd + (s.chainPasses ? s.chainPasses - 1 : 0);
            result.treeUpdates = s.treeUpdates;
            result.chainStalls = state.stalls;
            std::copy(gpu_->chainStages(), gpu_->chainStages() + 4, result.chainStages);
            result.chainRenders = gpu_->chainRenders();
        }
        result.treeSeconds = state.treeSeconds;
        result.passes = state.trace;
        result.errorSeconds = state.errorSeconds;
        result.meanSamples = double(planned) / double(pixels);
        ownership_.finished(grid);
        return result;
    }

private:
    // An adaptive frame's passes (async_adaptive.h). Passes below the minimum sample
    // count render every pixel and go out together, as table slots free. Each
    // later pass goes out once the trees have seen every pass before it, as each of
    // MoonRay's tiles reads trees its region rebuilt on finishing the pass before.
    // With a GPU, the errors are worked out on the device behind its last launch
    // and only they cross to the host; without one, the host works them out from
    // its film. The region trees then rebuild at once on the pool.
    struct Adaptive {
        using Clock = std::chrono::steady_clock;
        const cpu::Plan& plan;
        U32 samplesPerChunk, tiles, tilesX;
        std::vector<adaptive::Pass> passes;
        adaptive::Regions regions;
        PassTables tables;
        std::vector<U32> planned;    // samples each pixel will have once generated passes finish
        std::vector<U64> expected;   // samples of each generated pass
        std::vector<std::uint64_t> inImage;  // the tile positions inside the image
        // generated: passes sent out; retired: leading passes completed (their table
        // slots are free); evaluated: passes the trees have seen.
        U32 generated = 0, retired = 0, evaluated = 0, treeUpdates = 0;
        bool asked = false;  // errors asked of the GPU for every pass generated
        U64 askedLaunch = 0;  // the GPU's launch count when they were
        bool stop = false;   // the trees have converged: no more adaptive passes
        Clock::time_point start, askedAt;
        double treeSeconds = 0, errorSeconds = 0;
        std::vector<PassTrace> trace;
        double at() const { return std::chrono::duration<double>(Clock::now() - start).count(); }
        std::vector<double> sums, odd;  // frames without a GPU: the host film's copy
        std::vector<U32> counts;
        std::vector<float> errors;

        Adaptive(const cpu::Plan& p, U32 spc)
            : plan(p), samplesPerChunk(spc), tiles(((p.width + 7) / 8) * ((p.height + 7) / 8)), tilesX((p.width + 7) / 8),
              passes(p.adaptive ? adaptive::schedule(p.maxSamples) : std::vector<adaptive::Pass>{}),
              regions(int(p.width), int(p.height), p.adaptive ? p.targetError : 1.f),
              planned(p.adaptive ? size_t(p.width) * p.height : 0, 0u) {
            if (!p.adaptive) return;
            cpu::need(passes.size() <= MaxPasses, "Adaptive pass budget");
            inImage.assign(tiles, 0);
            for (U32 tile = 0; tile < tiles; ++tile)
                for (U32 q = 0; q < TilePixels; ++q)
                    if (tilePixel(tile, q, p.width, p.height) != ~0u) inImage[tile] |= 1ull << q;
            for (U32 s = 0; s < PassSlots; ++s) {
                tables.masks[s].assign(tiles, 0);
                tables.bases[s].assign(planned.size(), 0);
            }
        }
        U64 done(U32 pass, GpuLane* gpu) const {
            return tables.cpuDone[pass].load(std::memory_order_relaxed) + (gpu ? gpu->passDone()[pass] : 0);
        }
        bool complete(U32 pass, GpuLane* gpu) const { return done(pass, gpu) == expected[pass]; }

        bool uniformStage(U32 j) const { return passes[j].start < plan.minSamples; }
        // Whether pass j may go out: a free table slot, and either the uniform stage
        // or trees that have seen every pass before it.
        bool ready(U32 j) const {
            return j < passes.size() && j < retired + PassSlots && (uniformStage(j) || (!stop && evaluated == j));
        }
        // One pass at a time, so the feeder launches each as soon as it exists.
        void generateReady(Grid& grid, GpuLane* gpu) {
            if (ready(generated)) generate(grid, gpu);
        }
        void generate(Grid& grid, GpuLane* gpu) {
            const U32 j = generated, slot = j % PassSlots, size = passes[j].end - passes[j].start;
            const bool uniform = uniformStage(j);
            auto& masks = tables.masks[slot];
            auto& bases = tables.bases[slot];
            if (!gpu) bases = planned;  // the CPU lane's; the GPU makes its own
            U64 samples = 0;
            std::vector<std::vector<Chunk>> perCell(grid.cellCount());
            for (U32 tile = 0; tile < tiles; ++tile) {
                std::uint64_t active = inImage[tile];
                if (!uniform && passes[j].start < plan.maxSamples)
                    active &= regions.sampleArea(int(tile % tilesX) * 8, int(tile / tilesX) * 8);
                else if (!uniform)
                    active = 0;
                masks[tile] = active;
                if (!active) continue;
                for (U32 q = 0; q < TilePixels; ++q)
                    if (active >> q & 1) {
                        planned[tilePixel(tile, q, plan.width, plan.height)] += size;
                        samples += size;
                    }
                auto& list = perCell[grid.cellOf(tile)];
                for (U32 off = 0; off < size; off += samplesPerChunk)
                    list.push_back({tile, (j << PassShift) | off, std::min(samplesPerChunk, size - off), grid.cellOf(tile)});
            }
            expected.push_back(samples);
            tables.cpuDone[j].store(0, std::memory_order_relaxed);
            trace.push_back({samples, at()});
            ++generated;
            // A pass with no samples leaves the film, so the trees and every later
            // pass's masks, as they are: the frame has converged.
            if (!samples) {
                stop = true;
                return;
            }
            // On the stream ahead of any launch that reads it; an adaptive pass goes
            // out only once every earlier one has completed.
            if (gpu) gpu->uploadPass(slot, masks, uniform ? passes[j].start : NoSlot);
            for (U32 c = 0; c < perCell.size(); ++c)
                if (!perCell[c].empty()) grid.append(c, perCell[c].data(), U32(perCell[c].size()));
        }

        // The GPU's pass chain (GpuLane::launchChain): the frame's steps, the uniform
        // stage as one, then each adaptive pass; the first step still to queue; and
        // whether the frame is done.
        bool chain = false, chainOut = false, chainDone = false;
        std::vector<GpuLane::ChainStep> steps;
        size_t resume = 0;
        U64 chainsOut = 0;
        U32 uniformEnd = 0, stalls = 0;

        void startChain(GpuLane& gpu, const std::vector<U32>& tileOrder) {
            chain = true;
            while (uniformEnd < passes.size() && uniformStage(uniformEnd)) ++uniformEnd;
            steps.push_back({0, uniformEnd < passes.size() ? passes[uniformEnd].start : passes.back().end, true});
            for (U32 j = uniformEnd; j < passes.size(); ++j) steps.push_back({j, passes[j].end - passes[j].start, false});
            gpu.beginChain(regions, inImage, tileOrder);
        }
        // Queues the chain, and once it has come back either ends the frame or, if
        // a render parked samples, waits for the feeder to rerun them and resumes
        // the chain after that step.
        void advanceChain(GpuLane& gpu) {
            if (chainDone) return;
            if (!chainOut) {
                if (!gpu.ready()) return;
                gpu.launchChain({steps.begin() + std::ptrdiff_t(resume), steps.end()});
                chainOut = true;
                ++chainsOut;
                return;
            }
            if (gpu.chainsCollected() < chainsOut) return;
            const DeviceState& s = gpu.chainState();
            if (!s.chainStall) {
                chainDone = true;
                return;
            }
            if (gpu.inFlight() || gpu.parkedOutstanding()) return;
            size_t k = resume;
            while (k < steps.size() && steps[k].pass != s.chainPass) ++k;
            cpu::need(k < steps.size(), "GPU pass chain stalled outside its steps");
            resume = k + 1;
            ++stalls;
            chainOut = false;
            if (resume == steps.size()) chainDone = true;
        }

        // Moves the frame on: once the next pass needs the trees, gets the errors
        // after every pass sent out and rebuilds the trees, then sends out what that
        // allows. Waits only for the trees, which nothing else needs.
        //
        // The GPU is asked as soon as the last chunk has gone out, so its error
        // launch queues behind the passes. They count only if no launch went out
        // after them (a parked sample's rerun) and every pass has completed;
        // otherwise they are asked for again.
        void advance(Grid& grid, HostFilm& film, GpuLane* gpu, Pool& pool) {
            if (chain) {
                advanceChain(*gpu);
                return;
            }
            while (retired < generated && complete(retired, gpu)) trace[retired++].completed = at();
            const bool needTrees = !stop && generated < passes.size() && !uniformStage(generated) && evaluated < generated;
            if (needTrees && gpu) {
                if (!asked && grid.empty() && !gpu->parkedOutstanding()) {
                    gpu->requestErrors();
                    asked = true;
                    askedLaunch = gpu->launchCount();
                    askedAt = Clock::now();
                    trace[generated - 1].asked = at();
                } else if (asked && gpu->errorsReady()) {
                    if (gpu->launchCount() != askedLaunch) {
                        asked = false;
                    } else if (retired == generated) {  // else its launches are still to be collected
                        errorSeconds += std::chrono::duration<double>(Clock::now() - askedAt).count();
                        trace[generated - 1].errors = at();
                        asked = false;
                        rebuild(gpu->errors(), pool);
                    }
                }
            } else if (needTrees && retired == generated) {  // no GPU: the host film
                film.snapshot(sums, odd, counts);
                errors.resize(counts.size());
                const unsigned n = pool.size() + 1;
                pool.run(n, [&](unsigned part) {
                    for (size_t i = part; i < counts.size(); i += n)
                        errors[i] = pixelError(&sums[i * 4], &odd[i * 4], counts[i]);
                });
                rebuild(errors.data(), pool);
            }
            generateReady(grid, gpu);
        }
        void rebuild(const float* e, Pool& pool) {
            const auto began = Clock::now();
            pool.run(unsigned(regions.count()), [&](unsigned i) { regions.update(i, e); });
            treeSeconds += std::chrono::duration<double>(Clock::now() - began).count();
            trace[generated - 1].trees = at();
            evaluated = generated;
            ++treeUpdates;
            stop = regions.done();
        }
        // Every pass that will run has gone out and completed.
        bool finished(GpuLane* gpu) const {
            if (chain) return chainDone;
            for (U32 j = retired; j < generated; ++j)
                if (!complete(j, gpu)) return false;
            return generated == passes.size() || (!uniformStage(generated) && stop);
        }
    };

    // The image's tiles cell by cell, each cell's row by row, as the work grid holds them.
    std::vector<U32> tileOrder(U32 cellSize) const {
        const U32 tilesX = (plan_->width + TileSize - 1) / TileSize, tilesY = (plan_->height + TileSize - 1) / TileSize;
        const U32 per = cellSize / TileSize;
        std::vector<U32> order;
        order.reserve(size_t(tilesX) * tilesY);
        for (U32 cy = 0; cy * per < tilesY; ++cy)
            for (U32 cx = 0; cx * per < tilesX; ++cx)
                for (U32 ty = cy * per; ty < std::min(tilesY, (cy + 1) * per); ++ty)
                    for (U32 tx = cx * per; tx < std::min(tilesX, (cx + 1) * per); ++tx) order.push_back(ty * tilesX + tx);
        return order;
    }

    // How many chunks the next GPU launch takes: about one window of the GPU's
    // measured work; near the end, the share that lets both devices finish at
    // the same moment, given what the GPU already has queued.
    U32 launchSize(const RenderOptions& o, const Grid& grid, double gpuRate, const CpuLane& cpuLane, U32 itemsPerChunk,
                   U64 queuedItems, std::chrono::steady_clock::time_point start) const {
        U64 remainingChunks = 0;
        for (U32 i = 0; i < grid.cellCount(); ++i) remainingChunks += grid.remaining(i);
        if (!remainingChunks) return 0;
        const U64 cap = gpu_->maxChunksPerLaunch();
        // An adaptive pass is on the frame's critical path: it goes out whole.
        if (plan_->adaptive) return U32(std::min<U64>(cap, remainingChunks));
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
    std::unique_ptr<Pool> pool_;  // the adaptive error trees
};

}  // namespace xpu2::interactive::async
