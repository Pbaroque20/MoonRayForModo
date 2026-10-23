// The CPU lane of the asynchronous renderer: an Embree scene of native triangles,
// the CPU backend of the shared integrator, the host film, and workers that
// claim their own work from the grid by the cellular rules (async_grid.h).
//
// Native triangles with Embree's robust flag replace the parity pipeline's
// double-precision user-geometry test. Traversal differences between Embree
// and OptiX are expected and measured statistically (spec CPU-12, VER-3); the
// parity pipeline (deadline_pipeline.h) keeps the exact shared test.
#pragma once
#include "async_grid.h"
#include "cpu_jobs.h"
#include <condition_variable>
#include <deque>
#include <mutex>
#include <thread>

namespace xpu2::interactive::async {

// Embree scene for the fast lanes. Mesh i is geometry i, as in the plan.
struct CpuScene {
    std::shared_ptr<cpu::Device> device;
    RTCScene scene = nullptr;
    cpu::PlanView plan;
    explicit CpuScene(cpu::PlanView p) : device(std::make_shared<cpu::Device>()), plan(std::move(p)) {
        cpu::need(plan && cpu::isSpatial(plan->domain), "Asynchronous renderer requires a spatial plan");
        scene = rtcNewScene(device->handle);
        cpu::need(scene, "Embree scene failure");
        rtcSetSceneFlags(scene, RTC_SCENE_FLAG_ROBUST);
        rtcSetSceneBuildQuality(scene, RTC_BUILD_QUALITY_HIGH);
        for (unsigned i = 0; i < plan->meshes.size(); ++i) {
            const auto& m = *plan->meshes[i].data;
            RTCGeometry g = rtcNewGeometry(device->handle, RTC_GEOMETRY_TYPE_TRIANGLE);
            cpu::need(g, "Embree geometry failure");
            auto* v = rtcSetNewGeometryBuffer(g, RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3, sizeof(surface::V3),
                                              m.positions.size());
            auto* t = rtcSetNewGeometryBuffer(g, RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3, sizeof(cpu::Tri),
                                              m.triangles.size());
            if (!v || !t) {
                rtcReleaseGeometry(g);
                throw cpu::Unsupported("Embree allocation failure");
            }
            std::memcpy(v, m.positions.data(), m.positions.size() * sizeof(surface::V3));
            std::memcpy(t, m.triangles.data(), m.triangles.size() * sizeof(cpu::Tri));
            rtcSetGeometryBuildQuality(g, RTC_BUILD_QUALITY_HIGH);
            rtcCommitGeometry(g);
            rtcAttachGeometryByID(scene, g, i);
            rtcReleaseGeometry(g);
        }
        rtcCommitScene(scene);
        device->check();
    }
    ~CpuScene() {
        if (scene) rtcReleaseScene(scene);
    }
    CpuScene(const CpuScene&) = delete;
};

struct CpuBackend {
    const CpuScene& s;
    resume::Hit trace(const surface::Ray& ray) const {
        RTCRayHit h{};
        h.ray.org_x = ray.origin.x;
        h.ray.org_y = ray.origin.y;
        h.ray.org_z = ray.origin.z;
        h.ray.dir_x = ray.direction.x;
        h.ray.dir_y = ray.direction.y;
        h.ray.dir_z = ray.direction.z;
        h.ray.tnear = ray.nearT;
        h.ray.tfar = ray.farT;
        h.ray.mask = ~0u;
        h.hit.geomID = RTC_INVALID_GEOMETRY_ID;
        RTCIntersectArguments args;
        rtcInitIntersectArguments(&args);
        rtcIntersect1(s.scene, &h, &args);
        resume::Hit out;
        if (h.hit.geomID == RTC_INVALID_GEOMETRY_ID) return out;
        out.geom = h.hit.geomID;
        out.prim = h.hit.primID;
        const auto& mesh = *s.plan->meshes[out.geom].data;
        const auto t = mesh.triangles[out.prim];
        // Shared reconstruction of distance, coordinates and the offset origin.
        if (!resume::geometryHit(out, ray, mesh.positions[t.a], mesh.positions[t.b], mesh.positions[t.c]))
            out.normal = {};
        return out;
    }
    unsigned material(const resume::Hit& h, const surface::Ray& ray, surface::Lambert& out) const {
        RTCRayHit hit{};
        hit.hit.geomID = h.geom;
        hit.hit.primID = h.prim;
        hit.hit.u = h.u;
        hit.hit.v = h.v;
        // Host RAM holds every level of every texture, so the CPU never misses.
        out = mixed::material(s.plan, hit, ray);
        return tex::Ready;
    }
    bool visible(surface::V3 o, surface::V3 d) const {
        RTCRay ray{};
        ray.org_x = o.x;
        ray.org_y = o.y;
        ray.org_z = o.z;
        ray.dir_x = d.x;
        ray.dir_y = d.y;
        ray.dir_z = d.z;
        ray.tfar = INFINITY;
        ray.mask = ~0u;
        RTCOccludedArguments args;
        rtcInitOccludedArguments(&args);
        rtcOccluded1(s.scene, &ray, &args);
        return ray.tfar >= 0;
    }
};

// Per-pixel sums and sample counts in double precision (ACC-06). A chunk covers
// one tile, so a lock per tile serialises only workers on the same tile.
class HostFilm {
public:
    HostFilm(U32 width, U32 height)
        : width_(width), height_(height), sums_(size_t(width) * height * 4, 0.0), counts_(size_t(width) * height, 0),
          locks_(((width + TileSize - 1) / TileSize) * ((height + TileSize - 1) / TileSize)) {}
    void add(U32 tile, const U32* pixels, const double (*sums)[4], const U32* counts) {
        auto& lock = locks_[tile].flag;
        while (lock.test_and_set(std::memory_order_acquire)) std::this_thread::yield();
        for (U32 i = 0; i < TilePixels; ++i) {
            if (pixels[i] == ~0u || !counts[i]) continue;
            for (int c = 0; c < 4; ++c) sums_[size_t(pixels[i]) * 4 + c] += sums[i][c];
            counts_[pixels[i]] += counts[i];
        }
        lock.clear(std::memory_order_release);
    }
    void addOne(U32 pixel, const Radiance& r) {
        const U32 tilesX = (width_ + TileSize - 1) / TileSize;
        const U32 tile = (pixel / width_ / TileSize) * tilesX + (pixel % width_) / TileSize;
        auto& lock = locks_[tile].flag;
        while (lock.test_and_set(std::memory_order_acquire)) std::this_thread::yield();
        for (int c = 0; c < 3; ++c) sums_[size_t(pixel) * 4 + c] += r.rgb[c];
        sums_[size_t(pixel) * 4 + 3] += r.alpha;
        ++counts_[pixel];
        lock.clear(std::memory_order_release);
    }
    const std::vector<double>& sums() const { return sums_; }
    const std::vector<U32>& counts() const { return counts_; }

private:
    struct Lock { std::atomic_flag flag = ATOMIC_FLAG_INIT; };
    U32 width_, height_;
    std::vector<double> sums_;
    std::vector<U32> counts_;
    std::vector<Lock> locks_;
};

// One sample handed back by the GPU after a texture miss (spec MEM-05, M1).
struct Retry {
    U32 pixel, index;
};

// Samples migrated to the CPU lane. They are rendered before new chunks, since
// they were started first.
class RetryQueue {
public:
    void push(const Retry* items, size_t n) {
        std::lock_guard<std::mutex> lock(mutex_);
        items_.insert(items_.end(), items, items + n);
        size_.store(items_.size(), std::memory_order_release);
    }
    size_t pop(Retry* out, size_t n) {
        if (!size_.load(std::memory_order_acquire)) return 0;
        std::lock_guard<std::mutex> lock(mutex_);
        const size_t got = std::min(n, items_.size());
        std::copy_n(items_.begin(), got, out);
        items_.erase(items_.begin(), items_.begin() + got);
        size_.store(items_.size(), std::memory_order_release);
        return got;
    }
    size_t size() const { return size_.load(std::memory_order_acquire); }

private:
    std::mutex mutex_;
    std::deque<Retry> items_;
    std::atomic<size_t> size_{0};
};

struct CpuCounters {
    std::atomic<U64> samples{0}, chunks{0}, retried{0}, steals{0}, moves{0}, idleSpins{0};
    std::atomic<U32> failures{0};
    // Telemetry (TEL-01), microseconds from the lane's start.
    std::atomic<U64> busyMicros{0}, slowestChunkMicros{0}, firstClaimMicros{~0ull}, lastClaimMicros{0};
};

// Renders one claimed chunk on the CPU into the host film.
inline void renderChunk(const CpuScene& scene, const mixed::Config& config, const Chunk& chunk, HostFilm& film,
                        CpuCounters& counters) {
    CpuBackend backend{scene};
    U32 pixels[TilePixels], counts[TilePixels] = {};
    double sums[TilePixels][4] = {};
    for (U32 p = 0; p < TilePixels; ++p) pixels[p] = tilePixel(chunk.tile, p, config.width, config.height);
    for (U32 s = 0; s < chunk.count; ++s)
        for (U32 p = 0; p < TilePixels; ++p) {
            if (pixels[p] == ~0u) continue;
            Radiance r;
            if (integrate(config, pixels[p], chunk.first + s, backend, r) != SampleStatus::Done) {
                counters.failures.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            for (int c = 0; c < 3; ++c) sums[p][c] += r.rgb[c];
            sums[p][3] += r.alpha;
            ++counts[p];
        }
    film.add(chunk.tile, pixels, sums, counts);
    U64 done = 0;
    for (U32 p = 0; p < TilePixels; ++p) done += counts[p];
    counters.samples.fetch_add(done, std::memory_order_relaxed);
    counters.chunks.fetch_add(1, std::memory_order_relaxed);
}

// CPU lane workers. They persist across frames (created and pinned once) and
// wait between frames. In a frame each moves through the grid by the cellular
// rules and claims one chunk at a time. A worker counts as idle until it has
// claimed work, so a worker that wakes late never holds a frame open; an idle
// worker holds no work, so a frame may end without waiting for workers to sleep.
class CpuLane {
public:
    // affinity: the logical processors the workers may run on (0 for any).
    CpuLane(const CpuScene& scene, unsigned threads, DWORD_PTR affinity = 0) : scene_(scene) {
        workers_.reserve(threads);
        for (unsigned w = 0; w < threads; ++w)
            workers_.emplace_back([this, w, threads, affinity] {
                if (affinity) SetThreadAffinityMask(GetCurrentThread(), affinity);
                loop(w, threads);
            });
    }
    ~CpuLane() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stop_ = true;
            closing_.store(true, std::memory_order_release);
        }
        wake_.notify_all();
        for (auto& t : workers_)
            if (t.joinable()) t.join();
    }
    CpuLane(const CpuLane&) = delete;

    // Starts a frame. Workers from the last frame are parked first.
    void begin(const mixed::Config& config, Grid& grid, HostFilm& film, RetryQueue& retries) {
        while (parked_.load(std::memory_order_acquire) != workers_.size()) std::this_thread::yield();
        counters.samples = counters.chunks = counters.retried = counters.steals = counters.moves = counters.idleSpins = 0;
        counters.failures = 0;
        counters.busyMicros = counters.slowestChunkMicros = counters.lastClaimMicros = 0;
        counters.firstClaimMicros = ~0ull;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            config_ = config;
            grid_ = &grid;
            film_ = &film;
            retries_ = &retries;
            idle_.store(unsigned(workers_.size()), std::memory_order_release);
            closing_.store(false, std::memory_order_release);
            cancelled_.store(false, std::memory_order_release);
            started_ = std::chrono::steady_clock::now();
            parked_.store(0, std::memory_order_release);
            ++frame_;
        }
        wake_.notify_all();
    }
    // Ends the frame once its work is gone, and wakes idle workers to park.
    void finish() {
        {
            std::lock_guard<std::mutex> lock(idleMutex_);
            closing_.store(true, std::memory_order_release);
        }
        idleWake_.notify_all();
    }
    // Returns once every worker has left the frame: its grid and film may go.
    void waitParked() const {
        while (parked_.load(std::memory_order_acquire) != workers_.size()) std::this_thread::yield();
    }
    void cancel() {
        cancelled_.store(true, std::memory_order_release);
        finish();
    }
    unsigned idle() const { return idle_.load(std::memory_order_acquire); }
    unsigned threads() const { return unsigned(workers_.size()); }
    CpuCounters counters;

private:
    void loop(unsigned w, unsigned threads) {
        U64 seen = 0;
        for (;;) {
            {
                std::unique_lock<std::mutex> lock(mutex_);
                parked_.fetch_add(1, std::memory_order_acq_rel);
                wake_.wait(lock, [&] { return stop_ || frame_ != seen; });
                if (stop_) return;
                seen = frame_;
            }
            run(w, threads);
        }
    }
    void run(unsigned w, unsigned threads) {
        Grid& grid = *grid_;
        HostFilm& film = *film_;
        RetryQueue& retries = *retries_;
        U32 cell = grid.seed(Device::Cpu, w, threads);
        Retry retry[64];
        bool idle = true;  // counted idle until it claims work
        auto setIdle = [&](bool v) {
            if (v != idle) {
                idle = v;
                idle_.fetch_add(v ? 1 : unsigned(-1), std::memory_order_acq_rel);
            }
        };
        while (!cancelled_.load(std::memory_order_acquire)) {
            if (retries.size()) {
                setIdle(false);
                if (size_t n = retries.pop(retry, 64)) {
                    CpuBackend backend{scene_};
                    for (size_t i = 0; i < n; ++i) {
                        Radiance r;
                        if (integrate(config_, retry[i].pixel, retry[i].index, backend, r) != SampleStatus::Done) {
                            counters.failures.fetch_add(1, std::memory_order_relaxed);
                            continue;
                        }
                        film.addOne(retry[i].pixel, r);
                    }
                    counters.samples.fetch_add(n, std::memory_order_relaxed);
                    counters.retried.fetch_add(n, std::memory_order_relaxed);
                }
                continue;
            }
            const U32 next = grid.choose(Device::Cpu, cell, w);
            if (next == ~0u) {
                setIdle(true);
                if (closing_.load(std::memory_order_acquire)) break;
                // No unclaimed work anywhere: only migrated samples could still come.
                counters.idleSpins.fetch_add(1, std::memory_order_relaxed);
                std::unique_lock<std::mutex> lock(idleMutex_);
                idleWake_.wait_for(lock, std::chrono::milliseconds(1), [&] {
                    return closing_.load(std::memory_order_acquire) || retries.size();
                });
                continue;
            }
            if (next != cell) {
                counters.moves.fetch_add(1, std::memory_order_relaxed);
                if (grid.owner(next) != Device::Cpu) counters.steals.fetch_add(1, std::memory_order_relaxed);
                cell = next;
            }
            // Busy before claiming: the coordinator must never see an empty grid
            // and every worker idle while a claimed chunk is still unrendered.
            setIdle(false);
            Chunk chunk;
            if (!grid.claim(cell, 1, &chunk)) continue;
            const auto begun = std::chrono::steady_clock::now();
            const U64 claimed = U64(std::chrono::duration_cast<std::chrono::microseconds>(begun - started_).count());
            for (U64 v = counters.firstClaimMicros.load(); claimed < v && !counters.firstClaimMicros.compare_exchange_weak(v, claimed);) {}
            for (U64 v = counters.lastClaimMicros.load(); claimed > v && !counters.lastClaimMicros.compare_exchange_weak(v, claimed);) {}
            renderChunk(scene_, config_, chunk, film, counters);
            const U64 took = U64(std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - begun).count());
            counters.busyMicros.fetch_add(took, std::memory_order_relaxed);
            for (U64 v = counters.slowestChunkMicros.load(); took > v && !counters.slowestChunkMicros.compare_exchange_weak(v, took);) {}
            U64 samples = 0;
            for (U32 p = 0; p < TilePixels; ++p)
                samples += tilePixel(chunk.tile, p, config_.width, config_.height) != ~0u ? chunk.count : 0;
            grid.rendered(chunk.cell, Device::Cpu, samples);
        }
        setIdle(true);
    }

    const CpuScene& scene_;
    std::vector<std::thread> workers_;
    std::mutex mutex_, idleMutex_;
    std::condition_variable wake_, idleWake_;
    bool stop_ = false;
    U64 frame_ = 0;
    mixed::Config config_{};
    Grid* grid_ = nullptr;
    HostFilm* film_ = nullptr;
    RetryQueue* retries_ = nullptr;
    std::chrono::steady_clock::time_point started_ = std::chrono::steady_clock::now();
    std::atomic<bool> closing_{false}, cancelled_{false};
    std::atomic<unsigned> idle_{0}, parked_{0};
};

}  // namespace xpu2::interactive::async
