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

// Curves on the CPU: an Embree user geometry whose spans run MoonRay XPU's GPU programs (curve_core.h), so the CPU
// finds what the GPU finds.
inline void curveBounds(const RTCBoundsFunctionArguments* args) {
    const auto& c = *static_cast<const curves::Set*>(args->geometryUserPtr);
    float lower[3], upper[3];
    curves::spanBounds(c, args->primID, lower, upper);
    args->bounds_o->lower_x = lower[0];
    args->bounds_o->lower_y = lower[1];
    args->bounds_o->lower_z = lower[2];
    args->bounds_o->upper_x = upper[0];
    args->bounds_o->upper_y = upper[1];
    args->bounds_o->upper_z = upper[2];
}
inline void curveIntersect(const RTCIntersectFunctionNArguments* args) {
    if (args->N != 1 || !args->valid[0]) return;
    const auto& c = *static_cast<const curves::Set*>(args->geometryUserPtr);
    auto* rh = reinterpret_cast<RTCRayHit*>(args->rayhit);
    curves::Hit h;
    if (!curves::intersectSpan(c, args->primID, {rh->ray.org_x, rh->ray.org_y, rh->ray.org_z}, {rh->ray.dir_x, rh->ray.dir_y, rh->ray.dir_z},
                               rh->ray.tnear, rh->ray.tfar, h))
        return;
    rh->ray.tfar = h.t;
    rh->hit.u = h.u;
    rh->hit.v = h.v;
    rh->hit.Ng_x = h.Ng.x;
    rh->hit.Ng_y = h.Ng.y;
    rh->hit.Ng_z = h.Ng.z;
    rh->hit.primID = args->primID;
    rh->hit.geomID = args->geomID;
    rh->hit.instID[0] = RTC_INVALID_GEOMETRY_ID;
}
inline void curveOccluded(const RTCOccludedFunctionNArguments* args) {
    if (args->N != 1 || !args->valid[0]) return;
    const auto& c = *static_cast<const curves::Set*>(args->geometryUserPtr);
    auto* ray = reinterpret_cast<RTCRay*>(args->ray);
    curves::Hit h;
    if (curves::intersectSpan(c, args->primID, {ray->org_x, ray->org_y, ray->org_z}, {ray->dir_x, ray->dir_y, ray->dir_z}, ray->tnear,
                              ray->tfar, h))
        ray->tfar = -INFINITY;
}
// A curve hit worked out again from its span, as the GPU lane does: its distance, coordinates and normal, the
// point rays leave from, and the epsilon they skip (LineSegments and CubicSpline: 1.5 times the radius there).
inline bool curveHit(const curves::Set& c, const surface::Ray& ray, resume::Hit& out) {
    curves::Hit h;
    if (!curves::intersectSpan(c, out.prim, ray.origin, ray.direction, ray.nearT, ray.farT, h)) return false;
    out.t = h.t;
    out.u = h.u;
    out.v = h.v;
    out.point = shade::V3{ray.origin.x + ray.direction.x * h.t, ray.origin.y + ray.direction.y * h.t, ray.origin.z + ray.direction.z * h.t};
    out.origin = out.below = out.point;
    const bool roundCubic = c.round && c.basis == curves::BasisBspline;
    out.normal = roundCubic ? h.Ng : shade::normalize(-ray.direction);
    const U32 first = curves::spanVertex(c, out.prim);
    float radius;
    if (c.basis == curves::BasisLinear) {
        radius = curves::point(c, first).w * (1.0f - h.u) + curves::point(c, first + 1).w * h.u;
    } else {
        float w[4];
        curves::cubicWeights(c.basis, h.u, w);
        radius = w[0] * curves::point(c, first).w + w[1] * curves::point(c, first + 1).w + w[2] * curves::point(c, first + 2).w +
                 w[3] * curves::point(c, first + 3).w;
    }
    out.epsilon = 1.5f * radius;
    return shade::finite3(out.point) && out.epsilon > 0.0f;
}

// Embree scene for the fast lanes. Mesh i is geometry i, as in the plan.
struct CpuScene {
    std::shared_ptr<cpu::Device> device;
    RTCScene scene = nullptr;
    RTCScene volumes = nullptr;  // the meshes that bound volumes (volume_core.h), for their crossings
    cpu::PlanView plan;
    std::vector<curves::Set> curveSets;  // a set a mesh (the user geometries' data)
    explicit CpuScene(cpu::PlanView p) : device(std::make_shared<cpu::Device>()), plan(std::move(p)) {
        cpu::need(plan && cpu::isSpatial(plan->domain), "Asynchronous renderer requires a spatial plan");
        scene = rtcNewScene(device->handle);
        cpu::need(scene, "Embree scene failure");
        rtcSetSceneFlags(scene, RTC_SCENE_FLAG_ROBUST);
        rtcSetSceneBuildQuality(scene, RTC_BUILD_QUALITY_HIGH);
        curveSets.resize(plan->meshes.size());
        for (unsigned i = 0; i < plan->meshes.size(); ++i) {
            const auto& m = *plan->meshes[i].data;
            if (m.curveBasis) {
                curveSets[i] = cpu::curveSet(m);
                RTCGeometry g = rtcNewGeometry(device->handle, RTC_GEOMETRY_TYPE_USER);
                cpu::need(g, "Embree geometry failure");
                rtcSetGeometryUserPrimitiveCount(g, curveSets[i].spanCount);
                rtcSetGeometryUserData(g, &curveSets[i]);
                rtcSetGeometryBoundsFunction(g, curveBounds, nullptr);
                rtcSetGeometryIntersectFunction(g, curveIntersect);
                rtcSetGeometryOccludedFunction(g, curveOccluded);
                rtcSetGeometryBuildQuality(g, RTC_BUILD_QUALITY_HIGH);
                rtcCommitGeometry(g);
                rtcAttachGeometryByID(scene, g, i);
                rtcReleaseGeometry(g);
                continue;
            }
            // A mesh with no material bounds a volume only: it is in the volumes' scene, not the surfaces'.
            const bool surface = plan->meshes[i].material != ~0u, bounds = plan->meshes[i].volume >= 0;
            for (int pass = 0; pass < 2; ++pass) {
                if (pass == 0 ? !surface : !bounds) continue;
                if (pass == 1 && !volumes) {
                    volumes = rtcNewScene(device->handle);
                    cpu::need(volumes, "Embree scene failure");
                    rtcSetSceneFlags(volumes, RTC_SCENE_FLAG_ROBUST);
                }
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
                rtcAttachGeometryByID(pass == 0 ? scene : volumes, g, i);
                rtcReleaseGeometry(g);
            }
        }
        rtcCommitScene(scene);
        if (volumes) rtcCommitScene(volumes);
        device->check();
    }
    ~CpuScene() {
        if (scene) rtcReleaseScene(scene);
        if (volumes) rtcReleaseScene(volumes);
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
        if (mesh.curveBasis) {
            if (!curveHit(s.curveSets[out.geom], ray, out)) return resume::Hit{};
            return out;
        }
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
    // A mesh's material identity (its record's pool offset).
    U32 materialId(U32 geom) const {
        const auto& plan = *s.plan;
        const U32 m = plan.meshes[geom].material;
        return m < plan.materialRecords.size() ? plan.materialRecords[m].offset : ~0u;
    }
    // The first hit on a mesh of the given material (MoonRay's subsurface probe rays skip the others).
    resume::Hit traceMaterial(surface::Ray ray, U32 material) const {
        for (int k = 0; k < 64; ++k) {
            const resume::Hit h = trace(ray);
            if (h.geom == ~0u || materialId(h.geom) == material) return h;
            ray.nearT = h.t + fmaxf(1e-6f, h.t * 1e-6f);
            if (!(ray.nearT < ray.farT)) break;
        }
        return resume::Hit{};
    }
    // A hit's geometric shading state and differentials, its material not run.
    bool surfaceState(const resume::Hit& h, const surface::Ray& ray, shade::State& st) const {
        const auto& plan = *s.plan;
        const auto& data = *plan.meshes[h.geom].data;
        if (data.curveBasis) {
            const shade::MeshAttributes attributes = curveAttributes(data, h.geom);
            if (!shade::curveState(attributes, h.prim, h.u, h.v, h.normal, h.point, ray.direction, st)) return false;
            st.geom = h.geom;
            shade::curveDifferentials(attributes, ray, plan.spp, st);
            return true;
        }
        const auto t = data.triangles[h.prim];
        shade::MeshAttributes attributes;
        attributes.normals = data.normals.empty() ? nullptr : data.normals.data();
        attributes.uvs = data.uvs.empty() ? nullptr : data.uvs.data();
        attributes.normalRate = data.normalRate;
        attributes.uvRate = data.uvRate;
        if (!shade::hitState(attributes, h.prim, t.a, t.b, t.c, data.positions[t.a], data.positions[t.b], data.positions[t.c], h.u,
                             h.v, h.point, ray.direction, st))
            return false;
        st.geom = h.geom;
        shade::hitDifferentials(attributes, h.prim, t.a, t.b, t.c, data.positions[t.a], data.positions[t.b], data.positions[t.c], ray,
                                plan.spp, st);
        return true;
    }
    // The path tracer's hit: its shading state, and its material's Bsdf (shade_material.h).
    // A curve mesh's shading attributes (its primitive attributes and curve set).
    shade::MeshAttributes curveAttributes(const cpu::MeshData& data, U32 geom) const {
        shade::MeshAttributes attributes;
        for (int k = 0; k < 12; ++k) attributes.worldToObject[k] = data.worldToObject[k];
        attributes.prims = data.prims.empty() ? nullptr : data.prims.data();
        attributes.primData = data.primData.empty() ? nullptr : data.primData.data();
        attributes.primCount = unsigned(data.prims.size());
        attributes.curve = s.curveSets[geom];
        return attributes;
    }
    unsigned shade(const resume::Hit& h, const surface::Ray& ray, shade::State& st, shade::Bsdf& bsdf, float& presence) const {
        const auto& plan = *s.plan;
        const auto& mesh = plan.meshes[h.geom];
        const auto& data = *mesh.data;
        if (data.curveBasis) {
            const shade::MeshAttributes attributes = curveAttributes(data, h.geom);
            if (!shade::curveState(attributes, h.prim, h.u, h.v, h.normal, h.point, ray.direction, st)) return tex::Invalid;
            st.geom = h.geom;
            st.worldToRender = plan.worldToRender;
            st.worldToObject = data.worldToObject;
            if (mesh.material >= plan.materialRecords.size()) return tex::Invalid;
            shade::curveDifferentials(attributes, ray, plan.spp, st);
            const HostTextures textures{plan.textureImages.data(), unsigned(plan.textureImages.size())};
            return shade::shadeMaterial(plan.materialRecords[mesh.material], plan.materialPool.data(), st, textures, bsdf, presence,
                                        scratch().dwaSlots, &scratch().glitter);
        }
        const auto t = data.triangles[h.prim];
        shade::MeshAttributes attributes;
        attributes.normals = data.normals.empty() ? nullptr : data.normals.data();
        attributes.uvs = data.uvs.empty() ? nullptr : data.uvs.data();
        attributes.normalRate = data.normalRate;
        attributes.uvRate = data.uvRate;
        for (int k = 0; k < 12; ++k) attributes.worldToObject[k] = data.worldToObject[k];
        attributes.prims = data.prims.empty() ? nullptr : data.prims.data();
        attributes.primData = data.primData.empty() ? nullptr : data.primData.data();
        attributes.primCount = unsigned(data.prims.size());
        if (!shade::hitState(attributes, h.prim, t.a, t.b, t.c, data.positions[t.a], data.positions[t.b], data.positions[t.c], h.u,
                             h.v, h.point, ray.direction, st))
            return tex::Invalid;
        st.geom = h.geom;
        st.worldToRender = plan.worldToRender;
        st.worldToObject = data.worldToObject;
        if (mesh.material >= plan.materialRecords.size()) return tex::Invalid;
        const auto& record = plan.materialRecords[mesh.material];
        shade::hitDifferentials(attributes, h.prim, t.a, t.b, t.c, data.positions[t.a], data.positions[t.b], data.positions[t.c], ray,
                                plan.spp, st);
        // Host RAM holds every level of every texture, so the CPU never misses.
        const HostTextures textures{plan.textureImages.data(), unsigned(plan.textureImages.size())};
        return shade::shadeMaterial(record, plan.materialPool.data(), st, textures, bsdf, presence, scratch().dwaSlots,
                                    &scratch().glitter);
    }
    // The scene's textures for the maps (shade_mapnodes.h).
    struct HostTextures {
        const tex::Image* const* images;
        unsigned count;
        unsigned lookup(unsigned texture, tex::Binding b, const tex::Footprint& f, surface::V3& out) const {
            if (texture >= count || !images[texture]) return tex::Invalid;
            b.image = images[texture];
            b.swapCross = b.mode != 3 ? 1u : 0u;  // as XPU's vector shading looks up (displacement: in order)
            return tex::lookup(b, f, out);
        }
    };
    bool visible(surface::V3 o, surface::V3 d) const { return visible(o, d, INFINITY); }
    // Unoccluded up to distance (a shadow ray toward a light).
    bool visible(surface::V3 o, surface::V3 d, float distance) const { return visible(o, d, 0.0f, distance); }
    // Unoccluded between near and far (a shadow ray from a curve skips its epsilon).
    bool visible(surface::V3 o, surface::V3 d, float near, float distance) const {
        RTCRay ray{};
        ray.org_x = o.x;
        ray.org_y = o.y;
        ray.org_z = o.z;
        ray.dir_x = d.x;
        ray.dir_y = d.y;
        ray.dir_z = d.z;
        ray.tnear = near;
        ray.tfar = distance;
        ray.mask = ~0u;
        RTCOccludedArguments args;
        rtcInitOccludedArguments(&args);
        rtcOccluded1(s.scene, &ray, &args);
        return ray.tfar >= 0;
    }
    // The path tracer's Bsdf and pending rays, one set per worker thread.
    struct Scratch {
        shade::Bsdf bsdf;
        paths::Pending pending[paths::MaxPending];
        shade::DwaParams dwaSlots[shade::DwaMaxSlots];
        shade::GlitterScratch glitter;
    };
    static Scratch& scratch() {
        static thread_local std::unique_ptr<Scratch> s;
        if (!s) s = std::make_unique<Scratch>();
        return *s;
    }
    shade::Bsdf& bsdf() const { return scratch().bsdf; }
    paths::Pending* pending() const { return scratch().pending; }
    const lights::Light& light(U32 i) const { return s.plan->lights[i]; }
    U32 lightMask(U32 geom) const { return s.plan->meshLights[geom]; }
    // The volumes (volume_core.h), and a ray's crossings of their meshes past tnear, nearest first (Scene::
    // intersectVolumes over the whole ray): whether each enters (the ray against the mesh's geometric normal) or
    // leaves; repeats at the same distance dropped, as MoonRay's interval filter drops Embree's.
    const volume::Shader* volumes() const { return s.plan->volumes.data(); }
    // MoonRay's integrator sequences for the random walk (cpu_scene.h walkSequences), null when not loaded.
    const float* walkSequences() const { return s.plan->walkSequences ? s.plan->walkSequences->data() : nullptr; }
    U32 volumeCrossings(surface::V3 o, surface::V3 d, float tnear, volume::Crossing* x, U32 max) const {
        if (!s.volumes) return 0;
        U32 n = 0;
        float t = tnear;
        for (U32 k = 0; k < 4 * max && n < max; ++k) {
            RTCRayHit h{};
            h.ray.org_x = o.x;
            h.ray.org_y = o.y;
            h.ray.org_z = o.z;
            h.ray.dir_x = d.x;
            h.ray.dir_y = d.y;
            h.ray.dir_z = d.z;
            h.ray.tnear = t;
            h.ray.tfar = INFINITY;
            h.ray.mask = ~0u;
            h.hit.geomID = RTC_INVALID_GEOMETRY_ID;
            RTCIntersectArguments args;
            rtcInitIntersectArguments(&args);
            rtcIntersect1(s.volumes, &h, &args);
            if (h.hit.geomID == RTC_INVALID_GEOMETRY_ID) break;
            const float th = h.ray.tfar;
            const U32 v = U32(s.plan->meshes[h.hit.geomID].volume);
            const U32 flags = d.x * h.hit.Ng_x + d.y * h.hit.Ng_y + d.z * h.hit.Ng_z < 0.0f ? volume::Entry : volume::Exit;
            if (!(n > 0 && x[n - 1].t == th && x[n - 1].volume == v && x[n - 1].flags == flags)) x[n++] = volume::Crossing{th, v, flags};
            t = th + fmaxf(1e-6f, th * 1e-6f);
        }
        return n;
    }
};

// Per-pixel sums and sample counts in double precision (ACC-06). A chunk covers
// one tile, so a lock per tile serialises only workers on the same tile. Sums of
// the odd-index samples are kept beside the totals, for the adaptive error
// measure (MoonRay's Beauty Odd buffer).
class HostFilm {
public:
    HostFilm(U32 width, U32 height)
        : width_(width), height_(height), sums_(size_t(width) * height * 4, 0.0), odd_(size_t(width) * height * 4, 0.0),
          counts_(size_t(width) * height, 0),
          locks_(((width + TileSize - 1) / TileSize) * ((height + TileSize - 1) / TileSize)) {}
    void add(U32 tile, const U32* pixels, const double (*sums)[4], const double (*odd)[4], const U32* counts) {
        auto& lock = locks_[tile].flag;
        while (lock.test_and_set(std::memory_order_acquire)) std::this_thread::yield();
        for (U32 i = 0; i < TilePixels; ++i) {
            if (pixels[i] == ~0u || !counts[i]) continue;
            for (int c = 0; c < 4; ++c) {
                sums_[size_t(pixels[i]) * 4 + c] += sums[i][c];
                odd_[size_t(pixels[i]) * 4 + c] += odd[i][c];
            }
            counts_[pixels[i]] += counts[i];
        }
        lock.clear(std::memory_order_release);
    }
    void addOne(U32 pixel, U32 index, const Radiance& r) {
        const U32 tilesX = (width_ + TileSize - 1) / TileSize;
        const U32 tile = (pixel / width_ / TileSize) * tilesX + (pixel % width_) / TileSize;
        auto& lock = locks_[tile].flag;
        while (lock.test_and_set(std::memory_order_acquire)) std::this_thread::yield();
        const double v[4] = {r.rgb[0], r.rgb[1], r.rgb[2], r.alpha};
        for (int c = 0; c < 4; ++c) {
            sums_[size_t(pixel) * 4 + c] += v[c];
            if (index & 1) odd_[size_t(pixel) * 4 + c] += v[c];
        }
        ++counts_[pixel];
        lock.clear(std::memory_order_release);
    }
    // A copy that is consistent tile by tile, taken while workers keep adding.
    void snapshot(std::vector<double>& sums, std::vector<double>& odd, std::vector<U32>& counts) {
        sums.resize(sums_.size());
        odd.resize(odd_.size());
        counts.resize(counts_.size());
        for (U32 tile = 0; tile < locks_.size(); ++tile) {
            auto& lock = locks_[tile].flag;
            while (lock.test_and_set(std::memory_order_acquire)) std::this_thread::yield();
            for (U32 p = 0; p < TilePixels; ++p) {
                const U32 pixel = tilePixel(tile, p, width_, height_);
                if (pixel == ~0u) continue;
                for (int c = 0; c < 4; ++c) {
                    sums[size_t(pixel) * 4 + c] = sums_[size_t(pixel) * 4 + c];
                    odd[size_t(pixel) * 4 + c] = odd_[size_t(pixel) * 4 + c];
                }
                counts[pixel] = counts_[pixel];
            }
            lock.clear(std::memory_order_release);
        }
    }
    // The picture so far, RGB: each pixel's mean over its samples here and in a copy of the GPU's film (gpuSums
    // and gpuCounts, or none), black where none has landed. Consistent tile by tile, taken while workers keep
    // adding. Returns the samples it saw.
    U64 preview(float* rgb, const double* gpuSums, const U32* gpuCounts) {
        U64 seen = 0;
        for (U32 tile = 0; tile < locks_.size(); ++tile) {
            auto& lock = locks_[tile].flag;
            while (lock.test_and_set(std::memory_order_acquire)) std::this_thread::yield();
            for (U32 p = 0; p < TilePixels; ++p) {
                const U32 pixel = tilePixel(tile, p, width_, height_);
                if (pixel == ~0u) continue;
                const U32 count = counts_[pixel] + (gpuCounts ? gpuCounts[pixel] : 0u);
                seen += count;
                for (int c = 0; c < 3; ++c)
                    rgb[size_t(pixel) * 3 + c] = count ? float((sums_[size_t(pixel) * 4 + c] + (gpuSums ? gpuSums[size_t(pixel) * 4 + c] : 0.0)) / count) : 0.0f;
            }
            lock.clear(std::memory_order_release);
        }
        return seen;
    }
    const std::vector<double>& sums() const { return sums_; }
    const std::vector<double>& odd() const { return odd_; }
    const std::vector<U32>& counts() const { return counts_; }

private:
    struct Lock { std::atomic_flag flag = ATOMIC_FLAG_INIT; };
    U32 width_, height_;
    std::vector<double> sums_, odd_;
    std::vector<U32> counts_;
    std::vector<Lock> locks_;
};

// An adaptive frame's pass tables, host side: for each pass slot, the active-pixel
// mask of every tile and the sample-index base of every pixel; and the samples
// each pass has completed on the CPU.
struct PassTables {
    std::vector<std::uint64_t> masks[PassSlots];
    std::vector<U32> bases[PassSlots];
    std::atomic<U64> cpuDone[MaxPasses] = {};
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

// Renders one claimed chunk on the CPU into the host film and returns the samples
// rendered. With pass tables (adaptive frames) only the tile's active pixels are
// rendered, each from its own sample-index base.
inline U64 renderChunk(const CpuScene& scene, const mixed::Config& config, const Chunk& chunk, HostFilm& film,
                       CpuCounters& counters, PassTables* tables = nullptr) {
    CpuBackend backend{scene};
    U32 pixels[TilePixels], counts[TilePixels] = {}, base[TilePixels] = {};
    double sums[TilePixels][4] = {}, odd[TilePixels][4] = {};
    U32 first = chunk.first;
    std::uint64_t mask = ~0ull;
    if (tables) {
        const U32 slot = chunkPass(chunk) % PassSlots;
        mask = tables->masks[slot][chunk.tile];
        first = chunkOffset(chunk);
    }
    for (U32 p = 0; p < TilePixels; ++p) {
        pixels[p] = (mask >> p & 1) ? tilePixel(chunk.tile, p, config.width, config.height) : ~0u;
        if (tables && pixels[p] != ~0u) base[p] = tables->bases[chunkPass(chunk) % PassSlots][pixels[p]];
    }
    for (U32 s = 0; s < chunk.count; ++s)
        for (U32 p = 0; p < TilePixels; ++p) {
            if (pixels[p] == ~0u) continue;
            Radiance r;
            const U32 index = base[p] + first + s;
            if (integrate(config, pixels[p], index, backend, r) != SampleStatus::Done) {
                counters.failures.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            const double v[4] = {r.rgb[0], r.rgb[1], r.rgb[2], r.alpha};
            for (int c = 0; c < 4; ++c) {
                sums[p][c] += v[c];
                if (index & 1) odd[p][c] += v[c];
            }
            ++counts[p];
        }
    film.add(chunk.tile, pixels, sums, odd, counts);
    U64 done = 0;
    for (U32 p = 0; p < TilePixels; ++p) done += counts[p];
    counters.samples.fetch_add(done, std::memory_order_relaxed);
    counters.chunks.fetch_add(1, std::memory_order_relaxed);
    if (tables) tables->cpuDone[chunkPass(chunk)].fetch_add(done, std::memory_order_relaxed);
    return done;
}

// CPU lane workers. They persist across frames (created and pinned once) and
// wait between frames. In a frame each moves through the grid by the cellular
// rules and claims one chunk at a time. A worker counts as idle until it has
// claimed work, so a worker that wakes late never holds a frame open; an idle
// worker holds no work, so a frame may end without waiting for workers to sleep.
class CpuLane {
public:
    // affinity: the logical processors the workers may run on (0 for any).
    CpuLane(const CpuScene& scene, unsigned threads, DWORD_PTR affinity = 0)
        : scene_(scene), active_(new std::atomic<U32>[std::max(1u, threads)]) {
        for (unsigned w = 0; w < std::max(1u, threads); ++w) active_[w].store(~0u, std::memory_order_relaxed);
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
    void begin(const mixed::Config& config, Grid& grid, HostFilm& film, RetryQueue& retries, PassTables* tables = nullptr) {
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
            tables_ = tables;
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
    // The tile worker w is rendering (~0u: none), for a host's outlines of the work; read from any thread.
    U32 activeTile(unsigned w) const { return active_[w].load(std::memory_order_relaxed); }
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
                        film.addOne(retry[i].pixel, retry[i].index, r);
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
            active_[w].store(chunk.tile, std::memory_order_relaxed);
            const U64 samples = renderChunk(scene_, config_, chunk, film, counters, tables_);
            active_[w].store(~0u, std::memory_order_relaxed);
            const U64 took = U64(std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - begun).count());
            counters.busyMicros.fetch_add(took, std::memory_order_relaxed);
            for (U64 v = counters.slowestChunkMicros.load(); took > v && !counters.slowestChunkMicros.compare_exchange_weak(v, took);) {}
            grid.rendered(chunk.cell, Device::Cpu, samples);
        }
        setIdle(true);
    }

    const CpuScene& scene_;
    std::unique_ptr<std::atomic<U32>[]> active_;  // each worker's tile (activeTile)
    std::vector<std::thread> workers_;
    std::mutex mutex_, idleMutex_;
    std::condition_variable wake_, idleWake_;
    bool stop_ = false;
    U64 frame_ = 0;
    mixed::Config config_{};
    Grid* grid_ = nullptr;
    HostFilm* film_ = nullptr;
    RetryQueue* retries_ = nullptr;
    PassTables* tables_ = nullptr;
    std::chrono::steady_clock::time_point started_ = std::chrono::steady_clock::now();
    std::atomic<bool> closing_{false}, cancelled_{false};
    std::atomic<unsigned> idle_{0}, parked_{0};
};

}  // namespace xpu2::interactive::async
