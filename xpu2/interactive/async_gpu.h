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
#include "async_gpu_abi.h"
#include "gpu_lane.h"
#include <deque>
#include <unordered_map>

namespace xpu2::interactive::async {

struct GpuOptions {
    size_t fineBudget = 512ull << 20;  // VRAM for fine-detail tiles
    U32 launchThreads = 1u << 16;      // fixed grid size of every render launch
    U32 maxChunksPerLaunch = 16384;
    U32 ringChunks = 1u << 17;         // mailbox ring capacity, in chunks
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
    // XPU2_ADAPTIVE, renders adaptive ones (none: adaptive frames are refused).
    explicit GpuLane(const std::string& ptx, const std::string& adaptivePtx = {}, GpuOptions options = {})
        : options_(options) {
        driver.deviceCap = 20ull << 30;
        driver.pinnedCap = 2ull << 30;
        try {
            ox(optixInit());
            OptixDeviceContextOptions context{};
            ox(optixDeviceContextCreate(driver.context, &context, &optix_));
            programs_[0].create(*this, ptx);
            if (!adaptivePtx.empty()) programs_[1].create(*this, adaptivePtx);
            program_ = &programs_[0];
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

    // Uploads a scene: acceleration structures, geometry, materials, the
    // resident mip levels and an empty fine-detail cache. Startup work.
    void prepare(const cpu::PlanView& plan) {
        cpu::need(plan && cpu::isSpatial(plan->domain), "Asynchronous GPU lane requires a spatial plan");
        plan_ = plan;
        scene_ = {};
        std::vector<OptixInstance> instances(plan->meshes.size());
        std::vector<mixed::Geometry> geometry;
        std::vector<surface::Lambert> materials;
        for (unsigned i = 0; i < plan->meshes.size(); ++i) {
            const auto& m = *plan->meshes[i].data;
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
            inst.visibilityMask = 255;
            inst.traversableHandle = gas.second;
            geometry.push_back({reinterpret_cast<const surface::V3*>(vertices->pointer),
                                reinterpret_cast<const surface::Triangle*>(indices->pointer),
                                unsigned(m.positions.size()), unsigned(m.triangles.size())});
            materials.push_back(plan->materials.at(plan->meshes[i].material));
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

        // Read back what the host needs, then clear the touch marks.
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
        gpu::Driver::check(driver.cuEventRecord_p(scene_.filmDone->value, stream_));
    }
    bool filmReady() { return scene_.filmDone->ready(); }
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
    // Samples each pass has completed on the GPU, as of the last collected launch.
    const std::vector<U32>& passDone() const { return passDone_; }

    size_t fineTiles() const { return fine_.tiles; }
    size_t fineLoaded() const { return fine_.loaded; }
    size_t fineEvicted() const { return fine_.evicted; }
    size_t residentMipBytes() const { return scene_.mipBytes; }

private:
    using B = gpu::B;
    struct alignas(OPTIX_SBT_RECORD_ALIGNMENT) Record { char header[OPTIX_SBT_RECORD_HEADER_SIZE]; };
    // One OptiX program: its module, programs, pipeline and binding table.
    struct Program {
        OptixModule module = nullptr;
        OptixProgramGroup groups[4]{};
        OptixPipeline pipeline = nullptr;
        B records;
        OptixShaderBindingTable sbt{};

        void create(GpuLane& lane, const std::string& ptx) {
            OptixModuleCompileOptions mo{};
            mo.maxRegisterCount = OPTIX_COMPILE_DEFAULT_MAX_REGISTER_COUNT;
            mo.optLevel = OPTIX_COMPILE_OPTIMIZATION_DEFAULT;
            mo.debugLevel = OPTIX_COMPILE_DEBUG_LEVEL_NONE;
            OptixPipelineCompileOptions po{};
            po.traversableGraphFlags = OPTIX_TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_LEVEL_INSTANCING;
            po.numPayloadValues = 2;
            po.numAttributeValues = 2;
            po.pipelineLaunchParamsVariableName = "params";
            po.usesPrimitiveTypeFlags = OPTIX_PRIMITIVE_TYPE_FLAGS_TRIANGLE;
            char log[8192];
            size_t length = sizeof(log);
            if (optixModuleCreateFromPTX(lane.optix_, &mo, &po, ptx.data(), ptx.size(), log, &length, &module) !=
                OPTIX_SUCCESS)
                throw std::runtime_error("OptiX module: " + std::string(log, std::min(length, sizeof(log))));
            OptixProgramGroupDesc desc[4] = {};
            desc[0].kind = OPTIX_PROGRAM_GROUP_KIND_RAYGEN;
            desc[0].raygen = {module, "__raygen__async"};
            desc[1].kind = OPTIX_PROGRAM_GROUP_KIND_MISS;
            desc[1].miss = {module, "__miss__radiance"};
            desc[2].kind = OPTIX_PROGRAM_GROUP_KIND_MISS;
            desc[2].miss = {module, "__miss__shadow"};
            desc[3].kind = OPTIX_PROGRAM_GROUP_KIND_HITGROUP;
            desc[3].hitgroup.moduleCH = module;
            desc[3].hitgroup.entryFunctionNameCH = "__closesthit__triangle";
            OptixProgramGroupOptions options{};
            length = sizeof(log);
            ox(optixProgramGroupCreate(lane.optix_, desc, 4, &options, log, &length, groups));
            OptixPipelineLinkOptions link{};
            link.maxTraceDepth = 1;
            link.debugLevel = OPTIX_COMPILE_DEBUG_LEVEL_NONE;
            length = sizeof(log);
            ox(optixPipelineCreate(lane.optix_, &po, &link, groups, 4, log, &length, &pipeline));
            OptixStackSizes stacks{};
            for (auto g : groups) ox(optixUtilAccumulateStackSizes(g, &stacks));
            unsigned a, b, c;
            ox(optixUtilComputeStackSizes(&stacks, 1, 0, 0, &a, &b, &c));
            ox(optixPipelineSetStackSize(pipeline, a, b, c, 2));
            auto host = lane.pinned(sizeof(Record) * 4);
            for (int i = 0; i < 4; ++i) ox(optixSbtRecordPackHeader(groups[i], static_cast<Record*>(host->host()) + i));
            records = lane.device(sizeof(Record) * 4);
            gpu::Driver::check(lane.driver.cuMemcpyHtoDAsync_v2_p(records->pointer, host->host(), host->bytes, nullptr));
            lane.driver.drain();
            sbt.raygenRecord = records->pointer;
            sbt.missRecordBase = records->pointer + sizeof(Record);
            sbt.missRecordStrideInBytes = sizeof(Record);
            sbt.missRecordCount = 2;
            sbt.hitgroupRecordBase = records->pointer + 3 * sizeof(Record);
            sbt.hitgroupRecordStrideInBytes = sizeof(Record);
            sbt.hitgroupRecordCount = 1;
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
    };
    struct Scene {
        std::vector<B> keep;
        U64 traversable = 0;
        B geometry, materials, config, maps, sums, odd, counts, hostSums, hostOdd, hostCounts;
        B passMask[PassSlots], passBase[PassSlots], passStaging[PassSlots], errors, hostErrors;
        std::shared_ptr<gpu::Event> filmDone, errorsDone;
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
        fine_.slots = U32(std::min<size_t>(options_.fineBudget / tileBytes, fine_.tiles));
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
        p.traversable = scene_.traversable;
        p.geometry = reinterpret_cast<const mixed::Geometry*>(scene_.geometry->pointer);
        p.maps = scene_.maps ? reinterpret_cast<const tex::Maps*>(scene_.maps->pointer) : nullptr;
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
        for (auto& p : programs_) p.destroy();
        if (optix_) optixDeviceContextDestroy(optix_);
        optix_ = nullptr;
    }

    GpuOptions options_;
    OptixDeviceContext optix_ = nullptr;
    Program programs_[2];  // uniform, adaptive
    Program* program_ = &programs_[0];
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
