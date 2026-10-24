// The asynchronous renderer's GPU lane, host side (spec §10, §13).
//
// One CUDA stream carries everything in order: chunk uploads into the mailbox
// ring, launches, readbacks of each launch's state, and tile-cache updates.
// Two launches stay queued so the GPU never waits for the host, and the host
// never waits for the GPU: it polls events (ARC-01).
//
// Texture residency follows the memory rule: host RAM holds every level of
// every texture; VRAM holds each texture's mip levels from 1 up, and a bounded
// cache of fine-detail (level-0) tiles loaded on demand from host RAM and
// evicted least recently used. A sample that needs a tile that is not resident
// parks in the GPU's bounded queue, its tile is requested once, and a later
// launch runs it again on the GPU after the tile has landed (MEM-04, MEM-05).
#pragma once
#include "async_adaptive.h"
#include "async_gpu_abi.h"
#include "gpu_lane.h"
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>

namespace xpu2::interactive::async {

struct GpuOptions {
    bool profileChain = false;         // time the pass chain's stages on the device (a diagnostic)
    size_t fineBudget = 512ull << 20;  // VRAM for fine-detail tiles
    U32 launchThreads = 1u << 16;      // fixed grid size of every render launch
    U32 maxChunksPerLaunch = 16384;
    U32 ringChunks = 1u << 17;         // mailbox ring capacity, in chunks
    // Only programs OptiX's disk cache already holds: a program that would have to be compiled (about an hour
    // the first time) throws NotCompiled instead.
    bool cachedOnly = false;
    // Called as the programs compile: OptiX compile tasks done so far, and those known to remain.
    std::function<void(unsigned done, unsigned waiting)> compileProgress;
};

// A program the GPU lane would have to compile first (GpuOptions::cachedOnly).
struct NotCompiled : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// What the host learns when a launch has finished.
struct Completion {
    U64 chunks = 0, items = 0, parkedRun = 0;
    U32 errors = 0;
    double deviceSeconds = 0;  // the launch's own duration, timed on the GPU
};

// A CUDA event that records time, for measuring launches on the device itself:
// the host's view of a launch includes however late it noticed the completion.
struct TimingEvent {
    gpu::Driver& d;
    CUevent value = nullptr;
    explicit TimingEvent(gpu::Driver& driver) : d(driver) { gpu::Driver::check(d.cuEventCreate_p(&value, CU_EVENT_DEFAULT)); }
    ~TimingEvent() { if (value) d.cuEventDestroy_v2_p(value); }
    TimingEvent(const TimingEvent&) = delete;
};

class GpuLane {
public:
    gpu::Driver driver;

    // ptx renders uniform frames; adaptivePtx, the same source built with
    // XPU2_ADAPTIVE, renders adaptive ones (none: adaptive frames are refused);
    // chainPtx holds the adaptive pass chain's CUDA kernels (async_adaptive.cu;
    // none: adaptive passes are made on the host).
    explicit GpuLane(const std::string& ptx, const std::string& adaptivePtx = {}, const std::string& chainPtx = {},
                     GpuOptions options = {})
        : options_(options) {
        driver.deviceCap = 20ull << 30;
        driver.pinnedCap = 2ull << 30;
        try {
            ox(optixInit());
            OptixDeviceContextOptions context{};
            ox(optixDeviceContextCreate(driver.context, &context, &optix_));
            OptixModule modules[2]{};
            compileModules(ptx, adaptivePtx, modules);
            programs_[0].create(*this, modules[0]);
            if (modules[1]) programs_[1].create(*this, modules[1]);
            program_ = &programs_[0];
            if (!chainPtx.empty()) {
                gpu::Driver::check(driver.cuModuleLoadData_p(&chain_.module, chainPtx.c_str()));
                gpu::Driver::check(driver.cuModuleGetFunction_p(&chain_.errors, chain_.module, "chainErrors"));
                gpu::Driver::check(driver.cuModuleGetFunction_p(&chain_.trees, chain_.module, "chainTrees"));
                gpu::Driver::check(driver.cuModuleGetFunction_p(&chain_.masks, chain_.module, "chainMasks"));
                gpu::Driver::check(driver.cuModuleGetFunction_p(&chain_.compact, chain_.module, "chainCompact"));
            }
            gpu::Driver::check(driver.cuStreamCreate_p(&stream_, CU_STREAM_NON_BLOCKING));

            for (auto& p : params_) {
                p.host = pinned(sizeof(LaunchParams));
                p.device = device(sizeof(LaunchParams));
                p.done = std::make_shared<gpu::Event>(driver);
            }
            for (auto& r : readbacks_) r.state = pinned(sizeof(DeviceState));
            ring_ = device(size_t(options_.ringChunks) * sizeof(Chunk));
            state_ = device(sizeof(DeviceState));
            const size_t maxItems = size_t(options_.maxChunksPerLaunch) * 64 * 64;  // up to 64 samples a chunk
            parkedCapacity_ = U32(std::min<size_t>(4 * maxItems + 1024, 1u << 26));
            parked_ = device(size_t(parkedCapacity_) * sizeof(Parked));
            for (auto& s : staging_) s = pinned(size_t(options_.maxChunksPerLaunch) * sizeof(Chunk));
            driver.drain();  // startup only
        } catch (...) {
            cleanup();
            throw;
        }
    }
    ~GpuLane() { cleanup(); }
    GpuLane(const GpuLane&) = delete;

    // Bytes of scratch per launch thread: a Bsdf, the pending rays and the DwaBase parameter slots
    // the scene's material trees need (GpuBackend::bsdf, pending, dwaSlots).
    // A glitter scratch (shade_glitter.h) follows when a material has glitter (glitterOffset).
    static size_t scratchStride(unsigned dwaSlots, bool glitter = false) {
        return glitterOffset(dwaSlots) + (glitter ? (sizeof(shade::GlitterScratch) + 15) & ~size_t(15) : 0);
    }
    static size_t glitterOffset(unsigned dwaSlots) {
        return ((sizeof(shade::Bsdf) + 15) & ~size_t(15)) + ((sizeof(paths::Pending) * paths::MaxPending + 15) & ~size_t(15)) +
               dwaSlots * ((sizeof(shade::DwaParams) + 15) & ~size_t(15));
    }
    // Uploads a scene: acceleration structures, geometry, materials, the
    // resident mip levels and an empty fine-detail cache. Startup work.
    void prepare(const cpu::PlanView& plan) {
        cpu::need(plan && cpu::isSpatial(plan->domain), "Asynchronous GPU lane requires a spatial plan");
        cpu::need(plan->paths, "The GPU programs carry the path tracer only");
        plan_ = plan;
        scene_ = {};
        std::vector<OptixInstance> instances(plan->meshes.size());
        std::vector<mixed::Geometry> geometry;
        std::vector<surface::Lambert> materials;
        std::vector<shade::MaterialRecord> meshMaterials;
        std::vector<shade::MeshAttributes> meshAttributes;
        for (unsigned i = 0; i < plan->meshes.size(); ++i) {
            const auto& m = *plan->meshes[i].data;
            if (m.curveBasis) {
                // Curves: a custom primitive a span, its box as OptixGPUCurve::getPrimitiveAabbs makes it; the curve
                // hit group's program (async_gpu.cu) runs MoonRay XPU's curve programs (curve_core.h).
                const curves::Set host = cpu::curveSet(m);
                std::vector<OptixAabb> boxes(host.spanCount);
                for (U32 k = 0; k < host.spanCount; ++k) {
                    float lower[3], upper[3];
                    curves::spanBounds(host, k, lower, upper);
                    boxes[k] = {lower[0], lower[1], lower[2], upper[0], upper[1], upper[2]};
                }
                auto aabbs = upload(boxes.data(), boxes.size() * sizeof(OptixAabb));
                auto points = upload(m.curvePoints.data(), m.curvePoints.size() * sizeof(float));
                auto spans = upload(m.curveSpans.data(), m.curveSpans.size() * sizeof(unsigned));
                auto counts = upload(m.curveSpanCounts.data(), m.curveSpanCounts.size() * sizeof(unsigned));
                OptixBuildInput input{};
                unsigned flag = OPTIX_GEOMETRY_FLAG_DISABLE_ANYHIT;
                input.type = OPTIX_BUILD_INPUT_TYPE_CUSTOM_PRIMITIVES;
                auto& custom = input.customPrimitiveArray;
                custom.aabbBuffers = &aabbs->pointer;
                custom.numPrimitives = host.spanCount;
                custom.strideInBytes = sizeof(OptixAabb);
                custom.flags = &flag;
                custom.numSbtRecords = 1;
                auto gas = build(input);
                auto& inst = instances[i];
                inst.transform[0] = inst.transform[5] = inst.transform[10] = 1;
                inst.instanceId = i;
                inst.sbtOffset = 1;  // the curve hit group
                inst.visibilityMask = 1;  // surfaces
                inst.traversableHandle = gas.second;
                geometry.push_back({nullptr, nullptr, 0, 0});
                materials.push_back(plan->materials.at(plan->meshes[i].material));
                meshMaterials.push_back(plan->materialRecords.at(plan->meshes[i].material));
                shade::MeshAttributes attributes;
                for (int k = 0; k < 12; ++k) attributes.worldToObject[k] = m.worldToObject[k];
                if (!m.prims.empty()) {
                    auto prims = upload(m.prims.data(), m.prims.size() * sizeof(shade::PrimAttr));
                    auto data = upload(m.primData.data(), std::max<size_t>(m.primData.size(), 1) * sizeof(float));
                    attributes.prims = reinterpret_cast<const shade::PrimAttr*>(prims->pointer);
                    attributes.primData = reinterpret_cast<const float*>(data->pointer);
                    attributes.primCount = U32(m.prims.size());
                    scene_.keep.push_back(prims);
                    scene_.keep.push_back(data);
                }
                attributes.curve = host;
                attributes.curve.points = reinterpret_cast<const float*>(points->pointer);
                attributes.curve.spans = reinterpret_cast<const U32*>(spans->pointer);
                attributes.curve.curveSpans = reinterpret_cast<const U32*>(counts->pointer);
                meshAttributes.push_back(attributes);
                scene_.keep.insert(scene_.keep.end(), {aabbs, points, spans, counts, gas.first});
                continue;
            }
            auto vertices = upload(m.positions.data(), m.positions.size() * sizeof(surface::V3));
            auto indices = upload(m.triangles.data(), m.triangles.size() * sizeof(cpu::Tri));
            OptixBuildInput input{};
            unsigned flag = OPTIX_GEOMETRY_FLAG_DISABLE_ANYHIT;
            input.type = OPTIX_BUILD_INPUT_TYPE_TRIANGLES;
            auto& tri = input.triangleArray;
            tri.vertexBuffers = &vertices->pointer;
            tri.numVertices = unsigned(m.positions.size());
            tri.vertexFormat = OPTIX_VERTEX_FORMAT_FLOAT3;
            tri.vertexStrideInBytes = sizeof(surface::V3);
            tri.indexBuffer = indices->pointer;
            tri.numIndexTriplets = unsigned(m.triangles.size());
            tri.indexFormat = OPTIX_INDICES_FORMAT_UNSIGNED_INT3;
            tri.indexStrideInBytes = sizeof(cpu::Tri);
            tri.flags = &flag;
            tri.numSbtRecords = 1;
            auto gas = build(input);
            auto& inst = instances[i];
            inst.transform[0] = inst.transform[5] = inst.transform[10] = 1;
            inst.instanceId = i;
            // Visibility: 1 for a surface (the path tracer's rays), 2 for a volume's bounds (its crossings); a mesh
            // with no material is a volume's bounds alone.
            const bool surface = plan->meshes[i].material != ~0u;
            inst.visibilityMask = (surface ? 1u : 0u) | (plan->meshes[i].volume >= 0 ? 2u : 0u);
            inst.traversableHandle = gas.second;
            geometry.push_back({reinterpret_cast<const surface::V3*>(vertices->pointer),
                                reinterpret_cast<const surface::Triangle*>(indices->pointer),
                                unsigned(m.positions.size()), unsigned(m.triangles.size())});
            materials.push_back(surface ? plan->materials.at(plan->meshes[i].material) : surface::Lambert{});
            meshMaterials.push_back(surface ? plan->materialRecords.at(plan->meshes[i].material) : shade::MaterialRecord{});
            shade::MeshAttributes attributes;
            for (int k = 0; k < 12; ++k) attributes.worldToObject[k] = m.worldToObject[k];
            if (!m.prims.empty()) {
                auto prims = upload(m.prims.data(), m.prims.size() * sizeof(shade::PrimAttr));
                auto data = upload(m.primData.data(), std::max<size_t>(m.primData.size(), 1) * sizeof(float));
                attributes.prims = reinterpret_cast<const shade::PrimAttr*>(prims->pointer);
                attributes.primData = reinterpret_cast<const float*>(data->pointer);
                attributes.primCount = U32(m.prims.size());
                scene_.keep.push_back(prims);
                scene_.keep.push_back(data);
            }
            if (!m.normals.empty()) {
                auto normals = upload(m.normals.data(), m.normals.size() * sizeof(surface::V3));
                attributes.normals = reinterpret_cast<const surface::V3*>(normals->pointer);
                attributes.normalRate = m.normalRate;
                scene_.keep.push_back(normals);
            }
            if (!m.uvs.empty()) {
                auto uvs = upload(m.uvs.data(), m.uvs.size() * sizeof(float));
                attributes.uvs = reinterpret_cast<const float*>(uvs->pointer);
                attributes.uvRate = m.uvRate;
                scene_.keep.push_back(uvs);
            }
            meshAttributes.push_back(attributes);
            scene_.keep.insert(scene_.keep.end(), {vertices, indices, gas.first});
        }
        auto instanceBuffer = upload(instances.data(), instances.size() * sizeof(OptixInstance));
        OptixBuildInput input{};
        input.type = OPTIX_BUILD_INPUT_TYPE_INSTANCES;
        input.instanceArray.instances = instanceBuffer->pointer;
        input.instanceArray.numInstances = unsigned(instances.size());
        auto top = build(input);
        scene_.traversable = top.second;
        scene_.keep.insert(scene_.keep.end(), {instanceBuffer, top.first});
        scene_.geometry = upload(geometry.data(), geometry.size() * sizeof(mixed::Geometry));
        scene_.materials = upload(materials.data(), materials.size() * sizeof(surface::Lambert));
        if (plan->paths) {
            scene_.lights = upload(plan->lights.data(), plan->lights.size() * sizeof(lights::Light));
            scene_.meshLights = upload(plan->meshLights.data(), plan->meshLights.size() * sizeof(U32));
            if (!plan->volumes.empty()) {
                scene_.volumes = upload(plan->volumes.data(), plan->volumes.size() * sizeof(volume::Shader));
                std::vector<int> meshVolumes;
                for (const auto& mesh : plan->meshes) meshVolumes.push_back(mesh.volume);
                scene_.meshVolumes = upload(meshVolumes.data(), meshVolumes.size() * sizeof(int));
            }
            if (plan->walkSequences)
                scene_.walkSequences = upload(plan->walkSequences->data(), plan->walkSequences->size() * sizeof(float));
            scene_.meshMaterials = upload(meshMaterials.data(), meshMaterials.size() * sizeof(shade::MaterialRecord));
            scene_.meshAttributes = upload(meshAttributes.data(), meshAttributes.size() * sizeof(shade::MeshAttributes));
            const std::vector<float> pool = plan->materialPool.empty() ? std::vector<float>{0.0f} : plan->materialPool;
            scene_.materialPool = upload(pool.data(), pool.size() * sizeof(float));
            scene_.scratch = device(size_t(options_.launchThreads) * scratchStride(plan->dwaSlots, plan->glitter));
        }
        const auto config = mixed::config(plan);
        scene_.config = upload(&config, sizeof(config));
        if (cpu::gpuTextures(plan->domain)) prepareTextures(*plan);
        const size_t pixels = size_t(plan->width) * plan->height;
        scene_.sums = device(pixels * 4 * sizeof(double));
        scene_.odd = device(pixels * 4 * sizeof(double));
        scene_.counts = device(pixels * sizeof(U32));
        scene_.hostSums = pinned(pixels * 4 * sizeof(double));
        scene_.hostOdd = pinned(pixels * 4 * sizeof(double));
        scene_.hostCounts = pinned(pixels * sizeof(U32));
        scene_.filmDone = std::make_shared<gpu::Event>(driver);
        scene_.previewDone = std::make_shared<gpu::Event>(driver);
        const U32 tiles = ((plan->width + TileSize - 1) / TileSize) * ((plan->height + TileSize - 1) / TileSize);
        for (U32 s = 0; s < PassSlots; ++s) {
            scene_.passMask[s] = device(size_t(tiles) * sizeof(U64L));
            scene_.passBase[s] = device(pixels * sizeof(U32));
            scene_.passStaging[s] = pinned(size_t(tiles) * sizeof(U64L));
        }
        if (plan->adaptive) {
            scene_.errors = device(pixels * sizeof(float));
            scene_.hostErrors = pinned(pixels * sizeof(float));
            scene_.errorsDone = std::make_shared<gpu::Event>(driver);
        }
        passDone_.assign(MaxPasses, 0u);
        driver.drain();  // startup only: everything above has landed
        uploads_.clear();
    }

    // Starts a frame: an empty film and empty queues.
    void begin(U32 samplesPerChunk, bool adaptive = false) {
        cpu::need(plan_ && inFlight_.empty(), "GPU frame overlap");
        cpu::need(!adaptive || programs_[1].pipeline, "No adaptive GPU program");
        program_ = &programs_[adaptive ? 1 : 0];
        itemsPerChunk_ = samplesPerChunk * TilePixels;
        adaptive_ = adaptive;
        const size_t pixels = size_t(plan_->width) * plan_->height;
        memset32(scene_.sums->pointer, 0, pixels * 8);
        memset32(scene_.odd->pointer, 0, pixels * 8);
        std::fill(passDone_.begin(), passDone_.end(), 0u);
        memset32(scene_.counts->pointer, 0, pixels);
        memset32(state_->pointer, 0, sizeof(DeviceState) / 4);
        published_ = 0;
        parkedTail_ = parkedIssued_ = 0;
        // The device's request ring restarts with its state; requested tiles not
        // yet loaded stay pending, and resident ones stay resident across frames.
        fine_.requestHead = 0;
        launches_ = 0;
        completed_ = {};
    }

    // Whether another launch may be queued now (at most two in flight).
    bool ready() const { return inFlight_.size() < 2 && paramsFree(); }
    unsigned inFlight() const { return unsigned(inFlight_.size()); }
    U64 parkedOutstanding() const { return parkedTail_ - parkedIssued_; }
    U64 maxChunksPerLaunch() const { return options_.maxChunksPerLaunch; }

    // Publishes chunks through the mailbox ring and queues a launch that runs
    // them, after any parked samples whose tiles have landed. Returns false when
    // there is nothing to run.
    bool launch(const Chunk* chunks, U32 count) {
        cpu::need(ready() && count <= options_.maxChunksPerLaunch, "GPU launch backpressure");
        // Tiles asked for so far land first, so every sample parked up to the last
        // readback may run again; one whose tile is still waiting parks again.
        commitTiles();
        const U64 parkedBegin = parkedIssued_, parkedEnd = parkedTail_;
        if (!count && parkedBegin == parkedEnd) return false;
        // The bounded queue: whatever this launch runs could park again, on top of
        // every launch still in flight (the host sizes launches, MEM-05).
        const U64 items = U64(count) * itemsPerChunk_ + (parkedEnd - parkedBegin);
        cpu::need(parkedBound() - parkedBegin + items <= parkedCapacity_, "Parked-sample queue would overflow");
        // The ring may not overwrite chunks a queued launch still reads.
        cpu::need(published_ + count - oldestChunk() <= options_.ringChunks, "Mailbox ring full");
        const unsigned s = U32(launches_ % Slots);
        auto& staging = staging_[launches_ % staging_.size()];
        std::memcpy(staging->host(), chunks, size_t(count) * sizeof(Chunk));
        for (U32 done = 0; done < count;) {  // the ring wraps
            const U64 at = (published_ + done) % options_.ringChunks;
            const U32 n = U32(std::min<U64>(count - done, options_.ringChunks - at));
            gpu::Driver::check(driver.cuMemcpyHtoDAsync_v2_p(ring_->pointer + at * sizeof(Chunk),
                                                             static_cast<char*>(staging->host()) + size_t(done) * sizeof(Chunk),
                                                             size_t(n) * sizeof(Chunk), stream_));
            done += n;
        }
        memset32(state_->pointer + offsetof(DeviceState, claimed) + s * sizeof(U32), 0, 1);
        memset32(state_->pointer + offsetof(DeviceState, unparked) + s * sizeof(U32), 0, 1);

        LaunchParams p = baseParams();
        p.slot = s;
        p.itemBegin = published_ * itemsPerChunk_;
        p.itemEnd = (published_ + count) * itemsPerChunk_;
        p.parkedBegin = parkedBegin;
        p.parkedEnd = parkedEnd;
        p.mode = 0;
        auto& slot = takeParams(p);
        auto& r = readbacks_[launches_ % readbacks_.size()];
        if (!r.begun) {
            r.begun = std::make_shared<TimingEvent>(driver);
            r.ended = std::make_shared<TimingEvent>(driver);
        }
        gpu::Driver::check(driver.cuEventRecord_p(r.begun->value, stream_));
        ox(optixLaunch(program_->pipeline, stream_, slot.device->pointer, sizeof(LaunchParams), &program_->sbt,
                       options_.launchThreads, 1, 1));
        gpu::Driver::check(driver.cuEventRecord_p(r.ended->value, stream_));

        readBack(r);
        slot.done = r.done;
        inFlight_.push_back({launches_, published_, count, parkedEnd - parkedBegin, items, gpu::StartClock::now(), &r});
        published_ += count;
        parkedIssued_ = parkedEnd;
        ++launches_;
        return true;
    }

    // Collects the oldest launch if it has finished; never waits.
    bool poll(Completion& out) {
        if (inFlight_.empty() || !inFlight_.front().readback->done->ready()) return false;
        const auto f = inFlight_.front();
        inFlight_.pop_front();
        const auto& state = *static_cast<const DeviceState*>(f.readback->state->host());
        out.chunks = f.chunks;
        out.items = U64(f.chunks) * itemsPerChunk_;
        out.parkedRun = f.parked;
        out.errors = state.errors;
        float ms = 0;
        gpu::Driver::check(driver.cuEventElapsedTime_p(&ms, f.readback->begun->value, f.readback->ended->value));
        out.deviceSeconds = ms / 1000.0;
        parkedTail_ = state.parkedTail;
        if (adaptive_) std::copy(state.passDone, state.passDone + MaxPasses, passDone_.begin());
        if (f.chain) {
            chainState_ = state;
            ++chainsCollected_;
            // Seconds in each stage of the chain, summed over its steps.
            for (size_t i = 1; i < chain_.marks.size(); ++i) {
                float stage = 0;
                gpu::Driver::check(driver.cuEventElapsedTime_p(&stage, chain_.marks[i - 1]->value, chain_.marks[i]->value));
                chainStages_[(i - 1) % 4] += stage / 1000.0;
                if ((i - 1) % 4 == 3) chainRenders_.push_back(stage / 1000.0);
            }
        }
        // Samples parked by this launch may run once their tiles are committed,
        // which the next launch does before it starts (commitTiles).
        if (fine_.tiles) {
            const auto* requests = static_cast<const U32*>(f.readback->requests->host());
            for (U64 i = fine_.requestHead; i < state.requestTail; ++i)
                fine_.pending.push_back(requests[i % fine_.requestCapacity]);
            fine_.requestHead = state.requestTail;
            const auto* touched = static_cast<const unsigned char*>(f.readback->touched->host());
            for (U32 t = 1; t <= fine_.tiles; ++t)
                if (touched[t]) fine_.lastUse[t] = f.launch + 1;
        }
        completed_ = out;
        return true;
    }

    // Queues the device film's download; filmReady() says when it has landed.
    void downloadFilm() {
        cpu::need(inFlight_.empty(), "Film download before the last launch was collected");
        const size_t pixels = size_t(plan_->width) * plan_->height;
        copyOut(scene_.hostSums, scene_.sums, pixels * 4 * sizeof(double));
        copyOut(scene_.hostCounts, scene_.counts, pixels * sizeof(U32));
        if (adaptive_) copyOut(scene_.hostOdd, scene_.odd, pixels * 4 * sizeof(double));
        if (chainsLaunched_) copyOut(chain_.hostPlanned, chain_.planned, pixels * sizeof(U32));
        gpu::Driver::check(driver.cuEventRecord_p(scene_.filmDone->value, stream_));
    }
    bool filmReady() { return scene_.filmDone->ready(); }
    // A copy of the device film as it will stand once the launches queued so far have finished, for a progressive
    // picture; previewReady() says when it has landed. Read through sums() and counts(); the frame's own download
    // (downloadFilm) writes the same copy.
    void downloadPreview() {
        const size_t pixels = size_t(plan_->width) * plan_->height;
        copyOut(scene_.hostSums, scene_.sums, pixels * 4 * sizeof(double));
        copyOut(scene_.hostCounts, scene_.counts, pixels * sizeof(U32));
        gpu::Driver::check(driver.cuEventRecord_p(scene_.previewDone->value, stream_));
    }
    bool previewReady() { return scene_.previewDone->ready(); }
    const double* sums() const { return static_cast<const double*>(scene_.hostSums->host()); }
    const double* odd() const { return static_cast<const double*>(scene_.hostOdd->host()); }
    const U32* counts() const { return static_cast<const U32*>(scene_.hostCounts->host()); }

    // Adaptive frames. Every pixel's error, worked out on the device behind the
    // launches already queued (they finish first, on the same stream); only the
    // errors cross to the host, for its error trees.
    void requestErrors() {
        LaunchParams p = baseParams();
        p.mode = 2;
        auto& slot = takeParams(p);
        ox(optixLaunch(program_->pipeline, stream_, slot.device->pointer, sizeof(LaunchParams), &program_->sbt, p.pixels, 1, 1));
        copyOut(scene_.hostErrors, scene_.errors, size_t(p.pixels) * sizeof(float));
        gpu::Driver::check(driver.cuEventRecord_p(scene_.errorsDone->value, stream_));
        slot.done = scene_.errorsDone;
    }
    bool errorsReady() { return scene_.errorsDone->ready(); }
    const float* errors() const { return static_cast<const float*>(scene_.hostErrors->host()); }
    // A pass's tables, ahead of any launch that reads them: its tile masks, and
    // each pixel's sample-index base, made on the device. A pass of the uniform
    // stage gives every pixel the same base (NoSlot: none); a later pass starts
    // from the device's counts, which hold every earlier pass once they have all
    // completed. A slot's staging is reused only once its earlier pass has
    // completed, so its upload has.
    void uploadPass(U32 slot, const std::vector<std::uint64_t>& masks, U32 uniformBase) {
        void* staging = scene_.passStaging[slot]->host();
        const size_t maskBytes = masks.size() * sizeof(U64L), pixels = size_t(plan_->width) * plan_->height;
        std::memcpy(staging, masks.data(), maskBytes);
        copyIn(scene_.passMask[slot], staging, maskBytes);
        if (uniformBase != NoSlot) memset32(scene_.passBase[slot]->pointer, uniformBase, pixels);
        else gpu::Driver::check(driver.cuMemcpyDtoDAsync_v2_p(scene_.passBase[slot]->pointer, scene_.counts->pointer,
                                                               pixels * sizeof(U32), stream_));
    }
    // Launches queued so far, render or otherwise.
    U64 launchCount() const { return launches_; }

    // The adaptive pass chain (async_adaptive.cu): a frame's passes queued at
    // once, each made on the device from the trees of the passes before it.
    struct ChainStep {
        U32 pass, size;  // the pass's index in the schedule and its samples a pixel
        bool uniform;    // every pixel, no trees: the passes below the minimum sample count
    };
    bool hasChain() const { return chain_.module != nullptr; }
    // Sets up a frame's chain: the region trees' bounds and room, the tiles in the
    // work grid's cell order, and empty planned counts. After begin().
    void beginChain(const adaptive::Regions& regions, const std::vector<std::uint64_t>& inImage,
                    const std::vector<U32>& tileOrder) {
        cpu::need(hasChain() && programs_[1].pipeline, "No GPU pass chain");
        const size_t pixels = size_t(plan_->width) * plan_->height, tiles = inImage.size(), n = regions.count();
        std::vector<adaptive::IBox> bounds(n);
        std::vector<U32> nodeOffset(n), nodeCapacity(n);
        std::vector<U64L> satOffset(n);
        U64 nodes = 0, sat = 0;
        for (size_t r = 0; r < n; ++r) {
            const auto b = regions.tree(r).root();
            bounds[r] = b;
            nodeOffset[r] = U32(nodes);
            nodeCapacity[r] = U32(std::max(1, adaptive::maxNodes(b)));
            satOffset[r] = sat;
            nodes += nodeCapacity[r];
            sat += U64(b.x1 - b.x0 + 1) * U64(b.y1 - b.y0 + 1);
        }
        auto fit = [&](B& b, size_t bytes) {
            if (!b || b->bytes < bytes) b = device(std::max<size_t>(bytes, 16));
        };
        fit(chain_.regions, n * sizeof(adaptive::IBox));
        fit(chain_.nodes, nodes * sizeof(adaptive::Node));
        fit(chain_.nodeOffset, n * sizeof(U32));
        fit(chain_.nodeCapacity, n * sizeof(U32));
        fit(chain_.sat, sat * sizeof(double));
        fit(chain_.satOffset, n * sizeof(U64L));
        fit(chain_.regionDone, n * sizeof(U32));
        fit(chain_.tileMask, tiles * sizeof(U64L));
        fit(chain_.inImage, tiles * sizeof(U64L));
        fit(chain_.tileOrder, tiles * sizeof(U32));
        fit(chain_.activeTiles, tiles * sizeof(U32));
        fit(chain_.activeMasks, tiles * sizeof(U64L));
        fit(chain_.planned, pixels * sizeof(U32));
        fit(chain_.base, pixels * sizeof(U32));
        fit(chain_.params, MaxPasses * sizeof(LaunchParams));
        if (!chain_.hostPlanned || chain_.hostPlanned->bytes < pixels * sizeof(U32)) chain_.hostPlanned = pinned(pixels * sizeof(U32));
        if (!chain_.params_staging) chain_.params_staging = pinned(MaxPasses * sizeof(LaunchParams));
        // The frame's small tables, staged together; the last frame's chain has
        // completed, so its staging is free.
        const size_t layout = n * (sizeof(adaptive::IBox) + 2 * sizeof(U32) + sizeof(U64L)) + tiles * (sizeof(U64L) + sizeof(U32));
        if (!chain_.staging || chain_.staging->bytes < layout) chain_.staging = pinned(layout);
        char* at = static_cast<char*>(chain_.staging->host());
        auto stage = [&](const B& to, const void* from, size_t bytes) {
            std::memcpy(at, from, bytes);
            copyIn(to, at, bytes);
            at += bytes;
        };
        stage(chain_.regions, bounds.data(), n * sizeof(adaptive::IBox));
        stage(chain_.nodeOffset, nodeOffset.data(), n * sizeof(U32));
        stage(chain_.nodeCapacity, nodeCapacity.data(), n * sizeof(U32));
        stage(chain_.satOffset, satOffset.data(), n * sizeof(U64L));
        stage(chain_.inImage, inImage.data(), tiles * sizeof(U64L));
        stage(chain_.tileOrder, tileOrder.data(), tiles * sizeof(U32));
        memset32(chain_.planned->pointer, 0, pixels);
        memset32(chain_.regionDone->pointer, 0, n);
        memset32(state_->pointer + offsetof(DeviceState, chainPass), NoPass, 1);

        ChainArgs& a = chain_.args;
        a = {};
        a.state = reinterpret_cast<DeviceState*>(state_->pointer);
        a.sums = reinterpret_cast<const double*>(scene_.sums->pointer);
        a.odd = reinterpret_cast<const double*>(scene_.odd->pointer);
        a.counts = reinterpret_cast<const U32*>(scene_.counts->pointer);
        a.errors = reinterpret_cast<float*>(scene_.errors->pointer);
        a.regions = reinterpret_cast<const adaptive::IBox*>(chain_.regions->pointer);
        a.nodes = reinterpret_cast<adaptive::Node*>(chain_.nodes->pointer);
        a.nodeOffset = reinterpret_cast<const U32*>(chain_.nodeOffset->pointer);
        a.nodeCapacity = reinterpret_cast<const U32*>(chain_.nodeCapacity->pointer);
        a.sat = reinterpret_cast<double*>(chain_.sat->pointer);
        a.satOffset = reinterpret_cast<const U64L*>(chain_.satOffset->pointer);
        a.regionDone = reinterpret_cast<U32*>(chain_.regionDone->pointer);
        a.tileMask = reinterpret_cast<U64L*>(chain_.tileMask->pointer);
        a.inImage = reinterpret_cast<const U64L*>(chain_.inImage->pointer);
        a.tileOrder = reinterpret_cast<const U32*>(chain_.tileOrder->pointer);
        a.activeTiles = reinterpret_cast<U32*>(chain_.activeTiles->pointer);
        a.activeMasks = reinterpret_cast<U64L*>(chain_.activeMasks->pointer);
        a.planned = reinterpret_cast<U32*>(chain_.planned->pointer);
        a.base = reinterpret_cast<U32*>(chain_.base->pointer);
        a.width = plan_->width;
        a.height = plan_->height;
        a.tiles = U32(tiles);
        a.tilesX = (plan_->width + TileSize - 1) / TileSize;
        a.regionCount = U32(n);
        a.target = regions.target();
        a.layout = regions.layout();
        chain_.maxStep = 0;
        for (double& s : chainStages_) s = 0;
        chainRenders_.clear();
        chainsLaunched_ = 0;
        chainsCollected_ = 0;
        chainState_ = {};
    }
    // Queues steps of the chain, then one readback: the whole lot is one flight.
    // A step's render that parks a sample stalls the chain; the host lands the
    // tiles, reruns the parked samples by ordinary launches, then resumes the chain
    // after that step.
    bool launchChain(const std::vector<ChainStep>& steps) {
        cpu::need(ready() && !steps.empty() && steps.size() <= MaxPasses, "GPU chain backpressure");
        commitTiles();  // tiles asked for so far land first
        U64 most = 0;  // the most samples one step could park; a stall stops the chain after it
        for (const auto& s : steps) most = std::max<U64>(most, U64(s.size) * TilePixels * chain_.args.tiles);
        cpu::need(parkedBound() - parkedIssued_ + most <= parkedCapacity_, "Parked-sample queue would overflow");
        memset32(state_->pointer + offsetof(DeviceState, chainStall), 0, 1);
        auto* staged = static_cast<LaunchParams*>(chain_.params_staging->host());
        for (size_t k = 0; k < steps.size(); ++k) {
            LaunchParams p = baseParams();
            p.mode = 3;
            p.chainPass = steps[k].pass;
            p.chainSize = steps[k].size;
            p.activeTiles = reinterpret_cast<const U32*>(chain_.activeTiles->pointer);
            p.activeMasks = reinterpret_cast<const U64L*>(chain_.activeMasks->pointer);
            p.chainBase = reinterpret_cast<const U32*>(chain_.base->pointer);
            staged[k] = p;
        }
        copyIn(chain_.params, staged, steps.size() * sizeof(LaunchParams));
        auto& r = readbacks_[launches_ % readbacks_.size()];
        if (!r.begun) {
            r.begun = std::make_shared<TimingEvent>(driver);
            r.ended = std::make_shared<TimingEvent>(driver);
        }
        const U32 pixels = plan_->width * plan_->height;
        gpu::Driver::check(driver.cuEventRecord_p(r.begun->value, stream_));
        // With profiling, an event after each stage: errors, trees, masks with
        // compaction, render.
        auto mark = [&] {
            if (!options_.profileChain) return;
            chain_.marks.push_back(std::make_shared<TimingEvent>(driver));
            gpu::Driver::check(driver.cuEventRecord_p(chain_.marks.back()->value, stream_));
        };
        chain_.marks.clear();
        mark();
        for (size_t k = 0; k < steps.size(); ++k) {
            const auto& s = steps[k];
            if (!s.uniform) kernel(chain_.errors, (pixels + 255) / 256, 256);
            mark();
            if (!s.uniform) kernel(chain_.trees, chain_.args.regionCount, 512);
            mark();
            U32 uniform = s.uniform ? 1u : 0u, size = s.size, pass = s.pass;
            kernel(chain_.masks, (chain_.args.tiles + 255) / 256, 256, uniform, size);
            kernel(chain_.compact, 1, 1024, pass, size);
            mark();
            ox(optixLaunch(program_->pipeline, stream_, chain_.params->pointer + k * sizeof(LaunchParams),
                           sizeof(LaunchParams), &program_->sbt, options_.launchThreads, 1, 1));
            mark();
        }
        gpu::Driver::check(driver.cuEventRecord_p(r.ended->value, stream_));
        readBack(r);
        inFlight_.push_back({launches_, published_, 0, 0, most, gpu::StartClock::now(), &r, true});
        ++launches_;
        ++chainsLaunched_;
        return true;
    }
    // With GpuOptions::profileChain: the frame's seconds in the chain's errors,
    // trees, masks (with compaction) and renders.
    const double* chainStages() const { return chainStages_; }
    const std::vector<double>& chainRenders() const { return chainRenders_; }  // each step's render
    // Chains collected so far this frame, and the device's state after the last.
    U64 chainsCollected() const { return chainsCollected_; }
    const DeviceState& chainState() const { return chainState_; }
    // Each pixel's planned samples after the frame's chain, once the film has landed.
    const U32* chainPlanned() const { return static_cast<const U32*>(chain_.hostPlanned->host()); }
    // Samples each pass has completed on the GPU, as of the last collected launch.
    const std::vector<U32>& passDone() const { return passDone_; }

    size_t fineTiles() const { return fine_.tiles; }
    size_t fineLoaded() const { return fine_.loaded; }
    size_t fineEvicted() const { return fine_.evicted; }
    size_t residentMipBytes() const { return scene_.mipBytes; }

private:
    using B = gpu::B;
    struct alignas(OPTIX_SBT_RECORD_ALIGNMENT) Record { char header[OPTIX_SBT_RECORD_HEADER_SIZE]; };
    static OptixPipelineCompileOptions pipelineOptions() {
        OptixPipelineCompileOptions po{};
        po.traversableGraphFlags = OPTIX_TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_LEVEL_INSTANCING;
        po.numPayloadValues = 2;
        po.numAttributeValues = 2;
        po.pipelineLaunchParamsVariableName = "params";
        po.usesPrimitiveTypeFlags = OPTIX_PRIMITIVE_TYPE_FLAGS_TRIANGLE | OPTIX_PRIMITIVE_TYPE_FLAGS_CUSTOM;
        return po;
    }
    // The program modules (the adaptive one if any), compiled together on a pool of threads through OptiX's
    // compile tasks: one thread compiling the shading library took minutes. OptiX's disk cache still serves
    // a module it has compiled before (no tasks then).
    void compileModules(const std::string& ptx, const std::string& adaptivePtx, OptixModule (&modules)[2]) {
        OptixModuleCompileOptions mo{};
        mo.maxRegisterCount = OPTIX_COMPILE_DEFAULT_MAX_REGISTER_COUNT;
        mo.optLevel = OPTIX_COMPILE_OPTIMIZATION_DEFAULT;
        mo.debugLevel = OPTIX_COMPILE_DEBUG_LEVEL_NONE;
        const OptixPipelineCompileOptions po = pipelineOptions();
        std::mutex mutex;
        std::condition_variable wake;
        std::deque<OptixTask> tasks;
        const std::string* sources[2] = {&ptx, &adaptivePtx};
        // The tasks write their feedback here until the modules complete or fail.
        static thread_local char logs[2][8192];
        size_t lengths[2] = {sizeof(logs[0]), sizeof(logs[1])};
        for (int i = 0; i < 2; ++i) {
            if (sources[i]->empty()) continue;
            OptixTask first = nullptr;
            if (optixModuleCreateFromPTXWithTasks(optix_, &mo, &po, sources[i]->data(), sources[i]->size(), logs[i], &lengths[i],
                                                  &modules[i], &first) != OPTIX_SUCCESS)
                throw std::runtime_error("OptiX module: " + std::string(logs[i], std::min(lengths[i], sizeof(logs[i]))));
            if (first) tasks.push_back(first);
        }
        if (options_.cachedOnly && !tasks.empty()) {
            for (auto& m : modules)
                if (m) {
                    optixModuleDestroy(m);
                    m = nullptr;
                }
            throw NotCompiled("The XPU2 GPU programs are not compiled yet");
        }
        unsigned finished = 0;
        unsigned active = 0;
        bool done = tasks.empty();
        OptixResult error = OPTIX_SUCCESS;
        auto work = [&] {
            for (;;) {
                OptixTask task;
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    wake.wait(lock, [&] { return done || !tasks.empty(); });
                    if (done) return;
                    task = tasks.front();
                    tasks.pop_front();
                    ++active;
                }
                OptixTask additional[16]{};
                unsigned count = 0;
                const OptixResult status = optixTaskExecute(task, additional, 16, &count);
                std::lock_guard<std::mutex> lock(mutex);
                --active;
                if (status != OPTIX_SUCCESS && error == OPTIX_SUCCESS) error = status;
                if (error == OPTIX_SUCCESS)
                    for (unsigned i = 0; i < count; ++i) tasks.push_back(additional[i]);
                else
                    tasks.clear();
                ++finished;
                if (options_.compileProgress) options_.compileProgress(finished, unsigned(tasks.size()) + active);
                if (tasks.empty() && active == 0) done = true;
                wake.notify_all();
            }
        };
        const unsigned threads = std::max(1u, std::min(16u, std::thread::hardware_concurrency()));
        std::vector<std::thread> workers;
        try {
            for (unsigned i = 1; i < threads; ++i) workers.emplace_back(work);
            work();
        } catch (...) {
            {
                std::lock_guard<std::mutex> lock(mutex);
                done = true;
                wake.notify_all();
            }
            for (auto& w : workers) w.join();
            throw;
        }
        for (auto& w : workers) w.join();
        // A module the tasks did not complete is compiled again on one thread, for OptiX's log.
        for (int i = 0; i < 2; ++i) {
            if (!modules[i]) continue;
            OptixModuleCompileState state = OPTIX_MODULE_COMPILE_STATE_FAILED;
            if (optixModuleGetCompilationState(modules[i], &state) == OPTIX_SUCCESS && state == OPTIX_MODULE_COMPILE_STATE_COMPLETED &&
                error == OPTIX_SUCCESS)
                continue;
            std::fprintf(stderr, "OptiX compile tasks: module %d state %x, result %d; compiling on one thread\n%.*s\n", i,
                         unsigned(state), int(error), int(std::min(lengths[i], sizeof(logs[i]))), logs[i]);
            optixModuleDestroy(modules[i]);
            modules[i] = nullptr;
            char log[8192];
            size_t length = sizeof(log);
            if (optixModuleCreateFromPTX(optix_, &mo, &po, sources[i]->data(), sources[i]->size(), log, &length, &modules[i]) !=
                OPTIX_SUCCESS)
                throw std::runtime_error("OptiX module: " + std::string(log, std::min(length, sizeof(log))));
        }
    }
    // One OptiX program: its module, programs, pipeline and binding table.
    struct Program {
        OptixModule module = nullptr;
        OptixProgramGroup groups[5]{};
        OptixPipeline pipeline = nullptr;
        B records;
        OptixShaderBindingTable sbt{};

        // Takes the compiled module (compileModules) and makes its programs and pipeline.
        void create(GpuLane& lane, OptixModule compiled) {
            module = compiled;
            const OptixPipelineCompileOptions po = pipelineOptions();
            char log[8192];
            size_t length = sizeof(log);
            OptixProgramGroupDesc desc[5] = {};
            desc[0].kind = OPTIX_PROGRAM_GROUP_KIND_RAYGEN;
            desc[0].raygen = {module, "__raygen__async"};
            desc[1].kind = OPTIX_PROGRAM_GROUP_KIND_MISS;
            desc[1].miss = {module, "__miss__radiance"};
            desc[2].kind = OPTIX_PROGRAM_GROUP_KIND_MISS;
            desc[2].miss = {module, "__miss__shadow"};
            desc[3].kind = OPTIX_PROGRAM_GROUP_KIND_HITGROUP;
            desc[3].hitgroup.moduleCH = module;
            desc[3].hitgroup.entryFunctionNameCH = "__closesthit__triangle";
            // Curves: their spans' own intersection program, the same closest hit.
            desc[4].kind = OPTIX_PROGRAM_GROUP_KIND_HITGROUP;
            desc[4].hitgroup.moduleCH = module;
            desc[4].hitgroup.entryFunctionNameCH = "__closesthit__triangle";
            desc[4].hitgroup.moduleIS = module;
            desc[4].hitgroup.entryFunctionNameIS = "__intersection__curve";
            OptixProgramGroupOptions options{};
            length = sizeof(log);
            ox(optixProgramGroupCreate(lane.optix_, desc, 5, &options, log, &length, groups));
            OptixPipelineLinkOptions link{};
            link.maxTraceDepth = 1;
            link.debugLevel = OPTIX_COMPILE_DEBUG_LEVEL_NONE;
            length = sizeof(log);
            ox(optixPipelineCreate(lane.optix_, &po, &link, groups, 5, log, &length, &pipeline));
            OptixStackSizes stacks{};
            for (auto g : groups) ox(optixUtilAccumulateStackSizes(g, &stacks));
            if (std::getenv("XPU2_ASYNC_STACKS"))  // a diagnostic: the raygen's stack shows state spilled across traces
                std::fprintf(stderr, "stacks: cssRG %u cssMS %u cssCH %u dssDC %u\n", stacks.cssRG, stacks.cssMS, stacks.cssCH, stacks.dssDC);
            unsigned a, b, c;
            ox(optixUtilComputeStackSizes(&stacks, 1, 0, 0, &a, &b, &c));
            ox(optixPipelineSetStackSize(pipeline, a, b, c, 2));
            auto host = lane.pinned(sizeof(Record) * 5);
            for (int i = 0; i < 5; ++i) ox(optixSbtRecordPackHeader(groups[i], static_cast<Record*>(host->host()) + i));
            records = lane.device(sizeof(Record) * 5);
            gpu::Driver::check(lane.driver.cuMemcpyHtoDAsync_v2_p(records->pointer, host->host(), host->bytes, nullptr));
            lane.driver.drain();
            sbt.raygenRecord = records->pointer;
            sbt.missRecordBase = records->pointer + sizeof(Record);
            sbt.missRecordStrideInBytes = sizeof(Record);
            sbt.missRecordCount = 2;
            sbt.hitgroupRecordBase = records->pointer + 3 * sizeof(Record);
            sbt.hitgroupRecordStrideInBytes = sizeof(Record);
            sbt.hitgroupRecordCount = 2;
        }
        void destroy() noexcept {
            if (pipeline) optixPipelineDestroy(pipeline);
            for (auto& g : groups)
                if (g) optixProgramGroupDestroy(g);
            if (module) optixModuleDestroy(module);
            pipeline = nullptr;
            module = nullptr;
            for (auto& g : groups) g = nullptr;
            records.reset();
        }
    };
    struct ParamSlot { B host, device; std::shared_ptr<gpu::Event> done; };
    struct Readback { B state, requests, touched; std::shared_ptr<gpu::Event> done; std::shared_ptr<TimingEvent> begun, ended; };
    struct Flight {
        U64 launch, firstChunk;
        U32 chunks;
        U64 parked, mayPark;
        gpu::StartClock::time_point started;
        Readback* readback;
        bool chain = false;
    };
    // The pass chain's kernels and buffers (beginChain).
    struct Chain {
        CUmodule module = nullptr;
        CUfunction errors = nullptr, trees = nullptr, masks = nullptr, compact = nullptr;
        B regions, nodes, nodeOffset, nodeCapacity, sat, satOffset, regionDone, tileMask, inImage, tileOrder,
            activeTiles, activeMasks, planned, base, params, hostPlanned, params_staging, staging;
        ChainArgs args{};
        U32 maxStep = 0;
        std::vector<std::shared_ptr<TimingEvent>> marks;
    };
    // Queues one of the chain's CUDA kernels with the chain's arguments first.
    template <class... A>
    void kernel(CUfunction f, U32 blocks, U32 threads, A&... extra) {
        void* args[] = {&chain_.args, &extra...};
        gpu::Driver::check(driver.cuLaunchKernel_p(f, blocks, 1, 1, threads, 1, 1, 0, stream_, args, nullptr));
    }
    // Reads back what the host needs after a launch, then clears the touch marks.
    void readBack(Readback& r) {
        copyOut(r.state, state_, sizeof(DeviceState));
        if (fine_.tiles) {
            ensure(r.requests, fine_.requestBytes());
            ensure(r.touched, fine_.tiles + 1);
            copyOut(r.requests, fine_.requests, fine_.requestBytes());
            copyOut(r.touched, fine_.touched, fine_.tiles + 1);
            gpu::Driver::check(driver.cuMemsetD8Async_p(fine_.touched->pointer, 0, fine_.tiles + 1, stream_));
        }
        if (!r.done) r.done = std::make_shared<gpu::Event>(driver);
        gpu::Driver::check(driver.cuEventRecord_p(r.done->value, stream_));
    }
    struct Scene {
        std::vector<B> keep;
        U64 traversable = 0;
        B geometry, materials, lights, meshLights, volumes, meshVolumes, walkSequences, meshMaterials, meshAttributes, materialPool, scratch, config, maps, textures, sums, odd, counts,
            hostSums,
            hostOdd, hostCounts;
        B passMask[PassSlots], passBase[PassSlots], passStaging[PassSlots], errors, hostErrors;
        std::shared_ptr<gpu::Event> filmDone, errorsDone, previewDone;
        size_t mipBytes = 0;
    };
    // The fine-detail cache: every level-0 tile of the scene's textures has an
    // id; resident ones occupy a slot of the slab.
    struct Fine {
        U32 tiles = 0, slots = 0, requestCapacity = 0;
        U64 requestHead = 0;
        size_t loaded = 0, evicted = 0;
        B tileState, requests, touched, pageEntry, slab;
        struct Source { const surface::V3* texels; U32 count; };
        std::vector<Source> sources;      // host texels of each tile id
        std::vector<U32> slotTile, tileSlot;
        std::vector<U64> lastUse;
        std::vector<U32> freeSlots, pending;
        size_t requestBytes() const { return size_t(requestCapacity) * sizeof(U32); }
    };

    static void ox(OptixResult e) { gpu::ox(e); }
    B device(size_t bytes) { return std::make_shared<gpu::Buffer>(driver, bytes); }
    B pinned(size_t bytes) { return std::make_shared<gpu::Buffer>(driver, bytes, true); }
    void ensure(B& b, size_t bytes) {
        if (!b || b->bytes < bytes) b = pinned(bytes);
    }
    void copyIn(const B& d, const void* host, size_t bytes) {
        gpu::Driver::check(driver.cuMemcpyHtoDAsync_v2_p(d->pointer, host, bytes, stream_));
    }
    void copyOut(const B& h, const B& d, size_t bytes) {
        gpu::Driver::check(driver.cuMemcpyDtoHAsync_v2_p(h->host(), d->pointer, bytes, stream_));
    }
    void memset32(CUdeviceptr p, unsigned value, size_t words) {
        if (words) gpu::Driver::check(driver.cuMemsetD32Async_p(p, value, words, stream_));
    }
    B upload(const void* data, size_t bytes) {
        auto h = pinned(std::max<size_t>(bytes, 4)), d = device(std::max<size_t>(bytes, 4));
        std::memcpy(h->host(), data, bytes);
        copyIn(d, h->host(), bytes);
        uploads_.push_back(h);
        return d;
    }
    std::pair<B, OptixTraversableHandle> build(const OptixBuildInput& input) {
        OptixAccelBuildOptions options{};
        options.buildFlags = OPTIX_BUILD_FLAG_PREFER_FAST_TRACE;
        options.operation = OPTIX_BUILD_OPERATION_BUILD;
        OptixAccelBufferSizes sizes{};
        ox(optixAccelComputeMemoryUsage(optix_, &options, &input, 1, &sizes));
        auto temporary = device(std::max<size_t>(sizes.tempSizeInBytes, 16));
        auto output = device(std::max<size_t>(sizes.outputSizeInBytes, 16));
        uploads_.push_back(temporary);
        OptixTraversableHandle handle = 0;
        ox(optixAccelBuild(optix_, stream_, &options, &input, 1, temporary->pointer, temporary->bytes, output->pointer,
                           output->bytes, &handle, nullptr, 0));
        return {output, handle};
    }

    void prepareTextures(const cpu::Plan& plan) {
        std::vector<std::shared_ptr<texture::File>> files;
        for (auto* bindings : {&plan.diffuseMaps, &plan.emissionMaps})
            for (auto& pair : *bindings)
                if (std::find(files.begin(), files.end(), pair.second.file) == files.end()) files.push_back(pair.second.file);
        for (auto& file : plan.textures)
            if (std::find(files.begin(), files.end(), file) == files.end()) files.push_back(file);
        fine_ = {};
        fine_.sources.push_back({nullptr, 0});  // id 0 is untracked
        std::vector<std::pair<std::shared_ptr<texture::File>, B>> images;
        std::vector<std::pair<B, std::vector<U32>>> levelZeroPages;  // per file: page array and its tile ids
        for (auto& file : files) {
            cpu::need(bool(file->pyramid), "Missing host mip pyramid");
            const auto& host = file->pyramid->image;
            tex::Image descriptor{};
            descriptor.count = host.count;
            // Levels 1 and up are resident for the whole session.
            std::vector<surface::V3> packed;
            std::vector<std::vector<size_t>> offsets(host.count);
            for (unsigned level = 1; level < host.count; ++level) {
                const auto m = host.levels[level];
                const unsigned nx = (m.width + tex::Tile - 1) / tex::Tile, ny = (m.height + tex::Tile - 1) / tex::Tile;
                for (unsigned i = 0; i < nx * ny; ++i) {
                    const unsigned tx = i % nx, ty = i / nx;
                    const size_t count = size_t(std::min(tex::Tile, m.width - tx * tex::Tile)) *
                                         std::min(tex::Tile, m.height - ty * tex::Tile);
                    offsets[level].push_back(packed.size());
                    packed.insert(packed.end(), m.pages[i], m.pages[i] + count);
                }
            }
            B pixels = packed.empty() ? B() : upload(packed.data(), packed.size() * sizeof(surface::V3));
            scene_.mipBytes += packed.size() * sizeof(surface::V3);
            for (unsigned level = 1; level < host.count; ++level) {
                std::vector<const surface::V3*> pages;
                for (size_t o : offsets[level]) pages.push_back(reinterpret_cast<const surface::V3*>(pixels->pointer) + o);
                auto table = upload(pages.data(), pages.size() * sizeof(pages[0]));
                descriptor.levels[level] = {host.levels[level].width, host.levels[level].height,
                                            reinterpret_cast<const surface::V3* const*>(table->pointer), 0};
                scene_.keep.push_back(table);
            }
            // Level 0 starts empty; its tiles are numbered for the cache.
            const auto m = host.levels[0];
            const unsigned nx = (m.width + tex::Tile - 1) / tex::Tile, ny = (m.height + tex::Tile - 1) / tex::Tile;
            std::vector<const surface::V3*> none(size_t(nx) * ny, nullptr);
            auto table = upload(none.data(), none.size() * sizeof(none[0]));
            const U32 base = U32(fine_.sources.size());
            std::vector<U32> ids;
            for (unsigned i = 0; i < nx * ny; ++i) {
                const unsigned tx = i % nx, ty = i / nx;
                const U32 count = std::min(tex::Tile, m.width - tx * tex::Tile) * std::min(tex::Tile, m.height - ty * tex::Tile);
                fine_.sources.push_back({m.pages[i], count});
                ids.push_back(base + i);
            }
            descriptor.levels[0] = {m.width, m.height, reinterpret_cast<const surface::V3* const*>(table->pointer), base};
            levelZeroPages.push_back({table, ids});
            scene_.keep.push_back(table);
            if (pixels) scene_.keep.push_back(pixels);
            images.push_back({file, upload(&descriptor, sizeof(descriptor))});
        }
        fine_.tiles = U32(fine_.sources.size() - 1);
        fine_.requestCapacity = fine_.tiles + 1;
        const size_t tileBytes = size_t(tex::Tile) * tex::Tile * sizeof(surface::V3);
        // A scene without textures keeps one unused slot, so the buffers below are never empty.
        fine_.slots = U32(std::min<size_t>(options_.fineBudget / tileBytes, std::max<U32>(fine_.tiles, 1)));
        cpu::need(fine_.slots > 0, "Fine-detail cache budget");
        fine_.tileState = device((fine_.tiles + 1) * sizeof(U32));
        fine_.touched = device(fine_.tiles + 1);
        fine_.requests = device(fine_.requestBytes());
        fine_.slab = device(size_t(fine_.slots) * tileBytes);
        memset32(fine_.tileState->pointer, 0, fine_.tiles + 1);
        gpu::Driver::check(driver.cuMemsetD8Async_p(fine_.touched->pointer, 0, fine_.tiles + 1, stream_));
        std::vector<U64L> entries(fine_.tiles + 1, 0);
        for (auto& [table, ids] : levelZeroPages)
            for (size_t i = 0; i < ids.size(); ++i) entries[ids[i]] = table->pointer + i * sizeof(void*);
        fine_.pageEntry = upload(entries.data(), entries.size() * sizeof(U64L));
        fine_.slotTile.assign(fine_.slots, 0);
        fine_.tileSlot.assign(fine_.tiles + 1, NoSlot);
        fine_.lastUse.assign(fine_.tiles + 1, 0);
        for (U32 s = fine_.slots; s-- > 0;) fine_.freeSlots.push_back(s);

        std::vector<tex::Maps> maps;
        for (const auto& mesh : plan.meshes) {
            tex::Maps pair;
            auto fill = [&](tex::Binding& b, const auto& bindings) {
                auto it = bindings.find(mesh.material);
                if (it == bindings.end()) return;
                b = it->second.descriptor();
                for (auto& image : images)
                    if (image.first == it->second.file) {
                        b.image = reinterpret_cast<const tex::Image*>(image.second->pointer);
                        return;
                    }
                throw std::runtime_error("Unmapped texture residency");
            };
            fill(pair.diffuse, plan.diffuseMaps);
            fill(pair.emission, plan.emissionMaps);
            maps.push_back(pair);
        }
        scene_.maps = upload(maps.data(), maps.size() * sizeof(tex::Maps));
        // The maps' texture table, in the plan's order (shade_mapnodes.h).
        if (!plan.textures.empty()) {
            std::vector<const tex::Image*> table;
            for (auto& file : plan.textures) {
                const tex::Image* image = nullptr;
                for (auto& entry : images)
                    if (entry.first == file) image = reinterpret_cast<const tex::Image*>(entry.second->pointer);
                if (!image) throw std::runtime_error("Unmapped texture residency");
                table.push_back(image);
            }
            scene_.textures = upload(table.data(), table.size() * sizeof(table[0]));
        }
        for (auto& image : images) scene_.keep.push_back(image.second);
    }

    // Loads every requested tile from host RAM into a slot, evicting the least
    // recently used where the slab is full, and queues the page-table updates
    // ahead of the next launch on the same stream.
    void commitTiles() {
        if (fine_.pending.empty()) return;
        std::vector<TileUpdate> updates;
        std::vector<U32> victims;
        if (fine_.pending.size() > fine_.freeSlots.size()) {
            // Least recently used resident tiles, not the ones asked for now.
            std::vector<U32> resident;
            for (U32 s = 0; s < fine_.slots; ++s)
                if (fine_.slotTile[s]) resident.push_back(fine_.slotTile[s]);
            std::sort(resident.begin(), resident.end(), [&](U32 a, U32 b) { return fine_.lastUse[a] < fine_.lastUse[b]; });
            const size_t need = fine_.pending.size() - fine_.freeSlots.size();
            for (size_t i = 0; i < resident.size() && victims.size() < need; ++i) victims.push_back(resident[i]);
        }
        for (U32 tile : victims) {
            const U32 s = fine_.tileSlot[tile];
            fine_.tileSlot[tile] = NoSlot;
            fine_.slotTile[s] = 0;
            fine_.freeSlots.push_back(s);
            updates.push_back({tile, NoSlot});
            ++fine_.evicted;
        }
        const size_t tileBytes = size_t(tex::Tile) * tex::Tile * sizeof(surface::V3);
        auto staging = pinned(std::max<size_t>(fine_.pending.size(), 1) * tileBytes);
        size_t n = 0;
        std::vector<U32> deferred;
        for (U32 tile : fine_.pending) {
            if (fine_.freeSlots.empty()) {  // more asked for than the cache holds: next time
                deferred.push_back(tile);
                continue;
            }
            const U32 s = fine_.freeSlots.back();
            fine_.freeSlots.pop_back();
            const auto& source = fine_.sources[tile];
            char* at = static_cast<char*>(staging->host()) + n * tileBytes;
            std::memcpy(at, source.texels, size_t(source.count) * sizeof(surface::V3));
            gpu::Driver::check(driver.cuMemcpyHtoDAsync_v2_p(fine_.slab->pointer + size_t(s) * tileBytes, at,
                                                             size_t(source.count) * sizeof(surface::V3), stream_));
            fine_.tileSlot[tile] = s;
            fine_.slotTile[s] = tile;
            fine_.lastUse[tile] = launches_ + 1;
            updates.push_back({tile, s});
            ++fine_.loaded;
            ++n;
        }
        fine_.pending = std::move(deferred);
        if (!updates.empty()) {
            auto list = pinned(updates.size() * sizeof(TileUpdate));
            std::memcpy(list->host(), updates.data(), updates.size() * sizeof(TileUpdate));
            auto deviceList = device(updates.size() * sizeof(TileUpdate));
            copyIn(deviceList, list->host(), list->bytes);
            LaunchParams p = baseParams();
            p.mode = 1;
            p.updates = reinterpret_cast<const TileUpdate*>(deviceList->pointer);
            p.updateCount = U32(updates.size());
            auto& slot = takeParams(p);
            ox(optixLaunch(program_->pipeline, stream_, slot.device->pointer, sizeof(LaunchParams), &program_->sbt,
                           p.updateCount, 1, 1));
            auto done = std::make_shared<gpu::Event>(driver);
            gpu::Driver::check(driver.cuEventRecord_p(done->value, stream_));
            slot.done = done;
            retire_.push_back({done, {staging, list, deviceList}});
        }
        while (!retire_.empty() && retire_.front().first->ready()) retire_.pop_front();
    }

    LaunchParams baseParams() const {
        LaunchParams p{};
        p.config = reinterpret_cast<const mixed::Config*>(scene_.config->pointer);
        p.materials = reinterpret_cast<const surface::Lambert*>(scene_.materials->pointer);
        p.lights = scene_.lights ? reinterpret_cast<const lights::Light*>(scene_.lights->pointer) : nullptr;
        p.meshLights = scene_.meshLights ? reinterpret_cast<const U32*>(scene_.meshLights->pointer) : nullptr;
        p.volumes = scene_.volumes ? reinterpret_cast<const volume::Shader*>(scene_.volumes->pointer) : nullptr;
        p.meshVolumes = scene_.meshVolumes ? reinterpret_cast<const int*>(scene_.meshVolumes->pointer) : nullptr;
        p.walkSequences = scene_.walkSequences ? reinterpret_cast<const float*>(scene_.walkSequences->pointer) : nullptr;
        p.meshMaterials = scene_.meshMaterials ? reinterpret_cast<const shade::MaterialRecord*>(scene_.meshMaterials->pointer) : nullptr;
        p.meshAttributes = scene_.meshAttributes ? reinterpret_cast<const shade::MeshAttributes*>(scene_.meshAttributes->pointer) : nullptr;
        p.materialPool = scene_.materialPool ? reinterpret_cast<const float*>(scene_.materialPool->pointer) : nullptr;
        p.scratch = scene_.scratch ? reinterpret_cast<unsigned char*>(scene_.scratch->pointer) : nullptr;
        p.scratchStride = scratchStride(plan_->dwaSlots, plan_->glitter);
        p.glitterOffset = plan_->glitter ? glitterOffset(plan_->dwaSlots) : 0;
        p.traversable = scene_.traversable;
        p.geometry = reinterpret_cast<const mixed::Geometry*>(scene_.geometry->pointer);
        p.maps = scene_.maps ? reinterpret_cast<const tex::Maps*>(scene_.maps->pointer) : nullptr;
        p.textures = scene_.textures ? reinterpret_cast<const tex::Image* const*>(scene_.textures->pointer) : nullptr;
        p.textureCount = scene_.textures ? U32(plan_->textures.size()) : 0;
        p.ring = reinterpret_cast<const Chunk*>(ring_->pointer);
        p.ringCapacity = options_.ringChunks;
        p.itemsPerChunk = itemsPerChunk_;
        p.maxTries = 8;
        p.parked = reinterpret_cast<Parked*>(parked_->pointer);
        p.parkedCapacity = parkedCapacity_;
        p.state = reinterpret_cast<DeviceState*>(state_->pointer);
        p.sums = reinterpret_cast<double*>(scene_.sums->pointer);
        p.counts = reinterpret_cast<U32*>(scene_.counts->pointer);
        p.adaptive = adaptive_ ? 1u : 0u;
        p.pixels = plan_->width * plan_->height;
        p.odd = reinterpret_cast<double*>(scene_.odd->pointer);
        p.errors = scene_.errors ? reinterpret_cast<float*>(scene_.errors->pointer) : nullptr;
        for (U32 s = 0; s < PassSlots; ++s) {
            p.passMask[s] = reinterpret_cast<const U64L*>(scene_.passMask[s]->pointer);
            p.passBase[s] = reinterpret_cast<const U32*>(scene_.passBase[s]->pointer);
        }
        if (fine_.tiles) {
            p.tileState = reinterpret_cast<U32*>(fine_.tileState->pointer);
            p.requests = reinterpret_cast<U32*>(fine_.requests->pointer);
            p.requestCapacity = fine_.requestCapacity;
            p.touched = reinterpret_cast<unsigned char*>(fine_.touched->pointer);
            p.pageEntry = reinterpret_cast<const U64L*>(fine_.pageEntry->pointer);
            p.slab = reinterpret_cast<const surface::V3*>(fine_.slab->pointer);
            p.slabTileTexels = tex::Tile * tex::Tile;
        }
        return p;
    }
    bool paramsFree() const {
        for (auto& p : params_)
            if (!p.done || p.done->ready()) return true;
        return false;
    }
    ParamSlot& takeParams(const LaunchParams& p) {
        for (auto& slot : params_)
            if (!slot.done || slot.done->ready()) {
                std::memcpy(slot.host->host(), &p, sizeof(p));
                copyIn(slot.device, slot.host->host(), sizeof(p));
                slot.done.reset();
                return slot;
            }
        throw std::runtime_error("No free launch parameter slot");
    }
    // The highest the parked queue can have reached: the last readback plus
    // everything the launches still in flight could park.
    U64 parkedBound() const {
        U64 bound = parkedTail_;
        for (auto& f : inFlight_) bound += f.mayPark;
        return bound;
    }
    U64 oldestChunk() const { return inFlight_.empty() ? published_ : inFlight_.front().firstChunk; }

    void cleanup() noexcept {
        try {
            if (driver.context) driver.drain();
        } catch (...) {
        }
        inFlight_.clear();
        retire_.clear();
        uploads_.clear();
        scene_ = {};
        fine_ = {};
        for (auto& p : params_) p = {};
        for (auto& r : readbacks_) r = {};
        for (auto& s : staging_) s.reset();
        ring_.reset();
        state_.reset();
        parked_.reset();
        if (stream_) driver.cuStreamDestroy_v2_p(stream_);
        stream_ = nullptr;
        if (chain_.module) driver.cuModuleUnload_p(chain_.module);
        chain_ = {};
        for (auto& p : programs_) p.destroy();
        if (optix_) optixDeviceContextDestroy(optix_);
        optix_ = nullptr;
    }

    GpuOptions options_;
    OptixDeviceContext optix_ = nullptr;
    Program programs_[2];  // uniform, adaptive
    Program* program_ = &programs_[0];
    Chain chain_;
    DeviceState chainState_{};
    double chainStages_[4] = {};
    std::vector<double> chainRenders_;
    U64 chainsLaunched_ = 0, chainsCollected_ = 0;
    CUstream stream_ = nullptr;
    B ring_, state_, parked_;
    std::array<ParamSlot, 8> params_;
    std::array<Readback, 4> readbacks_;
    std::array<B, 4> staging_;
    std::vector<B> uploads_;
    std::deque<std::pair<std::shared_ptr<gpu::Event>, std::vector<B>>> retire_;
    std::deque<Flight> inFlight_;
    cpu::PlanView plan_;
    Scene scene_;
    Fine fine_;
    U32 itemsPerChunk_ = 0, parkedCapacity_ = 0;
    bool adaptive_ = false;
    std::vector<U32> passDone_;
    U64 published_ = 0, launches_ = 0;
    U64 parkedTail_ = 0, parkedIssued_ = 0;
    Completion completed_;
};

}  // namespace xpu2::interactive::async
