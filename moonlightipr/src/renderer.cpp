// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// Host side of MoonLightIPR: CUDA buffers, OptiX acceleration structures, pipeline and denoiser.
#include "moonlightipr/moonlightipr.h"
#include "device/shared.h"

#include <cuda_runtime.h>
#include <optix.h>
#include <optix_function_table_definition.h>
#include <optix_stack_size.h>
#include <optix_stubs.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace moonlightipr {
namespace {

void check(cudaError_t result, const char* call) {
    if (result != cudaSuccess) throw std::runtime_error(std::string(call) + ": " + cudaGetErrorString(result));
}
void check(OptixResult result, const char* call) {
    if (result != OPTIX_SUCCESS) throw std::runtime_error(std::string(call) + ": " + optixGetErrorName(result));
}
#define ML_CHECK(call) check(call, #call)

// Device allocation that only grows, so repeated edits reuse it.
struct Buffer {
    CUdeviceptr ptr = 0;
    size_t bytes = 0;

    Buffer() = default;
    Buffer(const Buffer&) = delete;
    Buffer& operator=(const Buffer&) = delete;
    ~Buffer() { release(); }

    void release() {
        if (ptr) cudaFree(reinterpret_cast<void*>(ptr));
        ptr = 0;
        bytes = 0;
    }
    void reserve(size_t size) {
        if (size <= bytes) return;
        release();
        void* memory = nullptr;
        ML_CHECK(cudaMalloc(&memory, size));
        ptr = reinterpret_cast<CUdeviceptr>(memory);
        bytes = size;
    }
    void upload(const void* data, size_t size) {
        reserve(size);
        if (size) ML_CHECK(cudaMemcpy(reinterpret_cast<void*>(ptr), data, size, cudaMemcpyHostToDevice));
    }
    template <class T> void upload(const std::vector<T>& values) { upload(values.data(), values.size() * sizeof(T)); }
    void swap(Buffer& other) {
        std::swap(ptr, other.ptr);
        std::swap(bytes, other.bytes);
    }
};

struct Mesh {
    Buffer positions, normals, indices, materialIds, uvs, accel, widths;
    bool curves = false;    // round curve segments: positions, widths and each segment's first point
    bool linear = false;    // those segments are straight, not cubic B-splines
    bool ribbon = false;    // and they are lit as flat ribbons facing the ray
    OptixTraversableHandle handle = 0;
    uint32_t triangleCount = 0;
    uint32_t uvSetCount = 0;
    // For a mesh that changes shape during the shutter: its vertices at both ends, kept here to
    // be blended for each sample, and what refitting its acceleration structure needs.
    std::vector<float> open, close;
    size_t vertexCount = 0, updateBytes = 0, accelBytes = 0;
    int32_t uvSlots[UV_SLOTS] = {-1, -1, -1, -1, -1, -1, -1, -1};
    bool ownsMaterials = false;
    uint32_t maxMaterial = 0;
};

// OptiX's test of a ray against a curve is made for one set of build flags, so every set of curves is built with
// these, whether or not it changes shape during the shutter.
const unsigned CURVE_BUILD_FLAGS = OPTIX_BUILD_FLAG_ALLOW_UPDATE | OPTIX_BUILD_FLAG_ALLOW_COMPACTION | OPTIX_BUILD_FLAG_PREFER_FAST_TRACE;

struct SbtRecord {
    alignas(OPTIX_SBT_RECORD_ALIGNMENT) char header[OPTIX_SBT_RECORD_HEADER_SIZE];
};

void logCallback(unsigned level, const char* tag, const char* message, void*) {
    if (level <= 2) std::cerr << "[MoonLightIPR OptiX] " << tag << ": " << message << std::endl;
}

void subtract(const float* a, const float* b, float* out) { for (int i = 0; i < 3; ++i) out[i] = a[i] - b[i]; }
void cross(const float* a, const float* b, float* out) {
    out[0] = a[1] * b[2] - a[2] * b[1];
    out[1] = a[2] * b[0] - a[0] * b[2];
    out[2] = a[0] * b[1] - a[1] * b[0];
}
void scaleTo(float* v, float length) {
    const float current = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (!(current > 0.0f)) throw std::runtime_error("MoonLightIPR was given a zero-length camera or light direction");
    for (int i = 0; i < 3; ++i) v[i] *= length / current;
}

struct Texture {
    cudaArray_t array = nullptr;
    cudaTextureObject_t object = 0;
    // How bright the picture is, on a grid of at most 64 by 64, top row first: what a light that wears it is sampled by.
    std::vector<float> brightness;
    uint32_t gridWidth = 0, gridHeight = 0;
    ~Texture() {
        if (object) cudaDestroyTextureObject(object);
        if (array) cudaFreeArray(array);
    }
};

// The albedo of a specular lobe with a Fresnel term of one, by sampling its facets: for each
// roughness and view cosine, and then its cosine-weighted average per roughness.
std::vector<float> albedoTable(bool beckmann) {
    const float pi = 3.14159265358979323846f;
    const int steps = int(ALBEDO_STEPS), strata = 48;
    std::vector<float> table(ALBEDO_TABLE);
    for (int ri = 0; ri < steps; ++ri) {
        const float roughness = float(ri) / (steps - 1), alpha = std::max(roughness * roughness, 0.002f), a2 = alpha * alpha;
        const auto shadowing = [&](float nv) {
            if (nv <= 0.0f) return 0.0f;
            if (!beckmann) return 2.0f * nv / (nv + std::sqrt(a2 + (1.0f - a2) * nv * nv));
            const float a = nv / (alpha * std::sqrt(std::max(1e-12f, 1.0f - nv * nv)));
            return a < 1.6f ? (3.535f * a + 2.181f * a * a) / (1.0f + 2.276f * a + 2.577f * a * a) : 1.0f;
        };
        for (int ci = 0; ci < steps; ++ci) {
            const float cosine = std::max(float(ci) / (steps - 1), 0.02f), sine = std::sqrt(1.0f - cosine * cosine);
            double sum = 0.0;
            for (int i = 0; i < strata; ++i)
                for (int j = 0; j < strata; ++j) {
                    // A facet drawn from the distribution; the reflected light is weighted by what
                    // the density of that draw leaves of the lobe.
                    const float u = (i + 0.5f) / strata, phi = 2.0f * pi * (j + 0.5f) / strata;
                    const float tan2 = beckmann ? -a2 * std::log(1.0f - u) : a2 * u / (1.0f - u);
                    const float hz = 1.0f / std::sqrt(1.0f + tan2), hs = hz * std::sqrt(tan2);
                    const float hx = hs * std::cos(phi), hy = hs * std::sin(phi);
                    const float along = sine * hx + cosine * hz;
                    if (along <= 0.0f) continue;
                    const float wiz = 2.0f * along * hz - cosine;
                    if (wiz <= 0.0f) continue;
                    (void)hy;
                    sum += shadowing(cosine) * shadowing(wiz) * along / (cosine * hz);
                }
            table[ri * steps + ci] = std::min(1.0f, float(sum / (strata * strata)));
        }
        // Average over the hemisphere: 2 * integral of E(mu) mu dmu, by the trapezium rule.
        double average = 0.0;
        for (int ci = 0; ci + 1 < steps; ++ci) {
            const float m0 = float(ci) / (steps - 1), m1 = float(ci + 1) / (steps - 1);
            average += (table[ri * steps + ci] * m0 + table[ri * steps + ci + 1] * m1) * 0.5f * (m1 - m0);
        }
        table[steps * steps + ri] = std::min(1.0f, float(2.0 * average));
    }
    return table;
}

DeviceMaterial toDevice(const Material& m) {
    DeviceMaterial d{};
    std::copy(m.baseColor, m.baseColor + 3, d.color);
    std::copy(m.emission, m.emission + 3, d.emission);
    d.colorAmount = m.baseColorAmount;
    d.emissionAmount = m.emissionAmount;
    d.metallic = std::clamp(m.metallic, 0.0f, 1.0f);
    d.roughness = std::clamp(m.roughness, 0.0f, 1.0f);
    d.ior = std::max(m.ior, 1.0f);
    d.underRoughness = std::min(m.underRoughness, 1.0f);
    std::copy(m.transmissionColor, m.transmissionColor + 3, d.transmissionColor);
    d.transmission = std::clamp(m.transmission, 0.0f, 1.0f);
    d.transmissionRoughness = std::clamp(m.transmissionRoughness, 0.0f, 1.0f);
    d.transmissionIor = std::max(m.transmissionIor, 1.0f);
    d.coat = std::clamp(m.clearcoat, 0.0f, 1.0f);
    d.coatRoughness = std::clamp(m.clearcoatRoughness, 0.0f, 1.0f);
    d.dissolve = std::clamp(m.dissolve, 0.0f, 1.0f);
    d.bumpStrength = m.bumpStrength;
    d.coatBump = std::clamp(m.clearcoatBump, 0.0f, 1.0f);
    d.anisotropy = std::clamp(m.anisotropy, -1.0f, 1.0f);
    std::copy(m.tangent, m.tangent + 2, d.tangent);
    d.tangentSlot = std::min<uint32_t>(m.tangentSlot, UV_SLOTS);
    d.subsurface = std::clamp(m.subsurface, 0.0f, 1.0f);
    std::copy(m.subsurfaceColor, m.subsurfaceColor + 3, d.subsurfaceColor);
    d.subsurfaceRadius = std::max(m.subsurfaceRadius, 0.0f);
    d.absorptionDistance = m.thin ? 0.0f : std::max(m.absorptionDistance, 0.0f);
    d.abbe = std::max(m.abbe, 0.0f);
    d.specular = std::clamp(m.specularWeight, 0.0f, 1.0f);
    for (int c = 0; c < 3; ++c) {
        d.back[c] = std::clamp(m.diffuseTransmission[c], 0.0f, 1.0f);
        d.frontKeep[c] = std::clamp(m.diffuseKept[c], 0.0f, 1.0f);
        d.fuzzColor[c] = std::max(m.fuzzColor[c], 0.0f);
    }
    d.fuzz = std::clamp(m.fuzz, 0.0f, 1.0f);
    d.fuzzRoughness = std::clamp(m.fuzzRoughness, 0.05f, 1.0f);
    // MoonRay's VelvetAttenuator: fibres that do not absorb let through as much as their colour does not reflect.
    d.fuzzDims = d.fuzz * (m.fuzzAbsorbs ? 1.0f : std::max(d.fuzzColor[0], std::max(d.fuzzColor[1], d.fuzzColor[2])));
    d.flags = (m.thin ? MATERIAL_THIN : 0) | (m.clearcoatDims ? MATERIAL_COAT_DIMS : 0) | (m.dissolve > 0.0f ? MATERIAL_HAS_PRESENCE : 0)
            | (m.beckmann ? MATERIAL_BECKMANN : 0) | ((unsigned(m.roughnessCurve) & 3u) << MATERIAL_ROUGH_SHIFT)
            | (m.noCaustics ? MATERIAL_NO_CAUSTICS : 0) | (m.randomWalk ? MATERIAL_RANDOM_WALK : 0);
    d.layerStart = m.layerStart;
    d.layerCount = m.layerCount;
    return d;
}

// MoonRay's HairUtil: a roughness as the variance of a lobe along the fibre and as the width of one around it,
// and what turns a hair colour into absorption.
DeviceHair toDeviceHair(const Material& m) {
    DeviceHair d{};
    for (int i = 0; i < 4; ++i) {
        const float r = std::clamp(m.hairRoughness[i], 0.01f, 0.999f);
        const float root = 0.726f * r + 0.812f * r * r + 3.7f * std::pow(r, 20.0f);
        d.variance[i] = root * root;
        const float shift = std::clamp(m.hairOffset[i], -10.0f, 10.0f) * 3.14159265358979323846f / 180.0f;
        d.sinShift[i] = std::sin(shift);
        d.cosShift[i] = std::cos(shift);
    }
    std::copy(m.hairTint, m.hairTint + 9, d.tint);
    const float a = std::clamp(m.hairAzimuthalRoughness, 0.01f, 0.999999f);
    d.azimuthal = std::max(0.626657069f * (0.265f * a + 1.194f * a * a + 5.372f * std::pow(a, 22.0f)), 0.05f);
    d.absorption = 5.969f - 0.215f * a + 2.532f * a * a - 10.73f * a * a * a + 5.574f * a * a * a * a + 0.245f * a * a * a * a * a;
    d.eta = std::max(m.ior, 1.0001f);
    d.saturation = m.hairSaturation;
    d.lobes = m.hairLobes & 15;
    d.lobes |= m.hairGlint ? HAIR_GLINT : 0;
    d.fresnel = std::min<uint32_t>(m.hairFresnel, 2);
    // MoonRay: a cuticle of half a layer to a layer and a half; a glint's width from its roughness.
    d.layers = 0.5f + std::clamp(m.hairCuticle, 0.0f, 1.0f);
    d.glintWidth = std::max(0.125f * m.hairGlintRoughness * m.hairGlintRoughness, 1e-3f);
    d.glintEccentricity = std::clamp(m.hairGlintEccentricity, 0.5f, 1.0f);
    d.glintSaturation = m.hairGlintSaturation;
    std::copy(m.hairTwists, m.hairTwists + 2, d.twists);
    return d;
}

}

struct Renderer::Impl {
    OptixDeviceContext context = nullptr;
    OptixModule module = nullptr, curveModule = nullptr, linearModule = nullptr;
    OptixProgramGroup groups[7] = {};       // the last, the displacement pass's ray generation
    OptixPipeline pipeline = nullptr;
    OptixShaderBindingTable sbt = {};
    Buffer raygenRecord, missRecords, hitRecord, displaceRecord;
    OptixShaderBindingTable displaceSbt = {};

    std::vector<std::unique_ptr<Mesh>> meshes;
    std::vector<std::unique_ptr<Texture>> textures;
    std::vector<std::unique_ptr<Texture>> grids;     // 3D, of densities
    std::vector<float> gridPeaks;
    std::vector<int32_t> volumeGrids;       // every grid the current materials use
    std::vector<int32_t> lightGrids;        // and those the lights' filters use
    std::vector<int32_t> layerTextures;     // every texture the current layers use
    std::vector<int32_t> lightTextures;     // and those the lights and their filters use
    std::vector<int32_t> distantTextures;
    std::vector<Instance> instances;
    size_t materialCount = 0, layerCount = 0, lightCount = 0;
    Buffer meshTable, instanceTable, materialTable, layerTable, tileTable, hairTable, volumeTable, toonTable, albedoTables, instanceInput, instanceAccel, accelTemp;
    Buffer envPixels, envBackground, envMarginal, envConditional, distantLights, lights, lightTriangles, lightFilters;
    Buffer lightDistributions, distantDistributions;
    Buffer beauty, albedo, normal, denoised, lighting, paramsBuffer;
    // Stopping once clean (setConvergence): the even samples' mean, and which squares of the picture are done.
    Buffer half, done;
    Buffer lightSetTable;
    float cleanBelow = 0.0f;
    uint32_t nextCheck = 0;
    std::vector<uint8_t> tileDone, tilePassed;
    bool clean = false;
    // The last sample sent to the graphics card: the next waits for it asleep, rather than in the copy of its
    // settings, which would spin a core of the processor at full power the while. Loading a scene still waits as it did:
    // its many small copies would each lose a moment waking up.
    cudaEvent_t launched = nullptr;

    OptixDenoiser denoiser = nullptr;
    OptixDenoiserSizes denoiserSizes = {};
    size_t denoiserScratchBytes = 0;
    Buffer denoiserState, denoiserScratch, denoiserIntensity;

    LaunchParams params = {};
    Camera camera, cameraClose;
    bool cameraMoves = false, instancesMove = false, meshesMove = false, lightsMove = false;
    // The light tables as the shutter opens and as it closes, from which each moment's are blended.
    std::vector<DeviceDistantLight> distantOpen, distantClose;
    std::vector<DeviceLight> lightsOpen, lightsClose;
    uint32_t samples = 0;
    bool validated = false;
    // The kernel loaded: the full one's file, and the features of the one in use (FEATURE_*). A scene whose materials
    // use fewer is rendered by a kernel made without the rest (specialize).
    std::string kernelPath;
    unsigned kernelFeatures = FEATURE_ALL;

    ~Impl() {
        if (launched) cudaEventDestroy(launched);
        if (denoiser) optixDenoiserDestroy(denoiser);
        destroyPipeline();
        if (context) optixDeviceContextDestroy(context);
    }

    void destroyPipeline() {
        if (pipeline) optixPipelineDestroy(pipeline);
        for (OptixProgramGroup& group : groups) { if (group) optixProgramGroupDestroy(group); group = nullptr; }
        if (curveModule) optixModuleDestroy(curveModule);
        if (linearModule) optixModuleDestroy(linearModule);
        if (module) optixModuleDestroy(module);
        pipeline = nullptr; curveModule = linearModule = module = nullptr;
    }

    // The kernel made for these features, where it is beside the full one (MoonLightIPRKernel_fNN.ptx); the full one
    // where it is not, or where MOONLIGHTIPR_FULL_KERNEL is set. Only the pipeline is made again: meshes, their
    // acceleration structures and every buffer stay as they are.
    void specialize(unsigned features) {
        if (std::getenv("MOONLIGHTIPR_FULL_KERNEL")) features = FEATURE_ALL;
        std::string path = kernelPath;
        if (features != FEATURE_ALL) {
            const size_t dot = kernelPath.rfind(".ptx");
            char suffix[16];
            std::snprintf(suffix, sizeof(suffix), "_f%02u", features);
            const std::string candidate = dot == std::string::npos ? kernelPath : kernelPath.substr(0, dot) + suffix + kernelPath.substr(dot);
            if (std::ifstream(candidate).good()) path = candidate;
            else features = FEATURE_ALL;
        }
        if (features == kernelFeatures) return;
        ML_CHECK(cudaDeviceSynchronize());  // a queued launch may still run the pipeline
        destroyPipeline();
        createPipeline(path);
        kernelFeatures = features;
    }

    void createPipeline(const std::string& ptxPath) {
        std::ifstream file(ptxPath, std::ios::binary);
        const std::string ptx((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        if (ptx.empty()) throw std::runtime_error("Cannot read MoonLightIPR device program: " + ptxPath);

        OptixModuleCompileOptions moduleOptions = {};
        moduleOptions.maxRegisterCount = OPTIX_COMPILE_DEFAULT_MAX_REGISTER_COUNT;
        OptixPipelineCompileOptions pipelineOptions = {};
        pipelineOptions.traversableGraphFlags = OPTIX_TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_LEVEL_INSTANCING;
        // Two words carry a radiance ray's hit record; a ray looking for a light uses all eight to add up the fog it crosses.
        pipelineOptions.numPayloadValues = 11;
        pipelineOptions.numAttributeValues = 2;
        pipelineOptions.exceptionFlags = OPTIX_EXCEPTION_FLAG_NONE;
        pipelineOptions.pipelineLaunchParamsVariableName = "params";
        pipelineOptions.usesPrimitiveTypeFlags = OPTIX_PRIMITIVE_TYPE_FLAGS_TRIANGLE | OPTIX_PRIMITIVE_TYPE_FLAGS_ROUND_CUBIC_BSPLINE
                                             | OPTIX_PRIMITIVE_TYPE_FLAGS_ROUND_LINEAR;

        char log[4096];
        size_t logSize = sizeof(log);
        const OptixResult compiled = optixModuleCreateFromPTX(context, &moduleOptions, &pipelineOptions,
            ptx.data(), ptx.size(), log, &logSize, &module);
        if (compiled != OPTIX_SUCCESS) throw std::runtime_error(std::string("MoonLightIPR device program rejected: ") + log);

        // OptiX's own test of a ray against a curve; its options must be those the curves are built with.
        OptixBuiltinISOptions curveOptions = {};
        curveOptions.builtinISModuleType = OPTIX_PRIMITIVE_TYPE_ROUND_CUBIC_BSPLINE;
        curveOptions.buildFlags = CURVE_BUILD_FLAGS;
        curveOptions.curveEndcapFlags = OPTIX_CURVE_ENDCAP_ON;
        ML_CHECK(optixBuiltinISModuleGet(context, &moduleOptions, &pipelineOptions, &curveOptions, &curveModule));
        curveOptions.builtinISModuleType = OPTIX_PRIMITIVE_TYPE_ROUND_LINEAR;
        curveOptions.curveEndcapFlags = OPTIX_CURVE_ENDCAP_DEFAULT;
        ML_CHECK(optixBuiltinISModuleGet(context, &moduleOptions, &pipelineOptions, &curveOptions, &linearModule));

        OptixProgramGroupDesc descriptions[7] = {};
        descriptions[0].kind = OPTIX_PROGRAM_GROUP_KIND_RAYGEN;
        descriptions[0].raygen.module = module;
        descriptions[0].raygen.entryFunctionName = "__raygen__moonlightipr";
        descriptions[1].kind = OPTIX_PROGRAM_GROUP_KIND_MISS;
        descriptions[1].miss.module = module;
        descriptions[1].miss.entryFunctionName = "__miss__radiance";
        descriptions[2].kind = OPTIX_PROGRAM_GROUP_KIND_MISS;
        descriptions[2].miss.module = module;
        descriptions[2].miss.entryFunctionName = "__miss__shadow";
        descriptions[3].kind = OPTIX_PROGRAM_GROUP_KIND_HITGROUP;
        descriptions[3].hitgroup.moduleCH = module;
        descriptions[3].hitgroup.entryFunctionNameCH = "__closesthit__radiance";
        descriptions[3].hitgroup.moduleAH = module;
        descriptions[3].hitgroup.entryFunctionNameAH = "__anyhit__presence";
        descriptions[4].kind = OPTIX_PROGRAM_GROUP_KIND_HITGROUP;
        descriptions[4].hitgroup.moduleCH = module;
        descriptions[4].hitgroup.entryFunctionNameCH = "__closesthit__curve";
        descriptions[4].hitgroup.moduleAH = module;
        descriptions[4].hitgroup.entryFunctionNameAH = "__anyhit__curve";
        descriptions[4].hitgroup.moduleIS = curveModule;
        descriptions[5] = descriptions[4];
        descriptions[5].hitgroup.moduleIS = linearModule;
        descriptions[6].kind = OPTIX_PROGRAM_GROUP_KIND_RAYGEN;
        descriptions[6].raygen.module = module;
        descriptions[6].raygen.entryFunctionName = "__raygen__displace";
        OptixProgramGroupOptions groupOptions = {};
        logSize = sizeof(log);
        ML_CHECK(optixProgramGroupCreate(context, descriptions, 7, &groupOptions, log, &logSize, groups));

        // Shading runs in the ray generation program, so traces never nest.
        OptixPipelineLinkOptions linkOptions = {};
        linkOptions.maxTraceDepth = 1;
        logSize = sizeof(log);
        ML_CHECK(optixPipelineCreate(context, &pipelineOptions, &linkOptions, groups, 7, log, &logSize, &pipeline));
        OptixStackSizes stackSizes = {};
        for (OptixProgramGroup group : groups) ML_CHECK(optixUtilAccumulateStackSizes(group, &stackSizes));
        unsigned fromTraversal = 0, fromState = 0, continuation = 0;
        ML_CHECK(optixUtilComputeStackSizes(&stackSizes, 1, 0, 0, &fromTraversal, &fromState, &continuation));
        ML_CHECK(optixPipelineSetStackSize(pipeline, fromTraversal, fromState, continuation, 2));

        // Geometry is found through the instance id, so one hit record serves every mesh and one each kind of curve.
        SbtRecord raygen, miss[2], hit[3];
        ML_CHECK(optixSbtRecordPackHeader(groups[0], &raygen));
        ML_CHECK(optixSbtRecordPackHeader(groups[1], &miss[0]));
        ML_CHECK(optixSbtRecordPackHeader(groups[2], &miss[1]));
        ML_CHECK(optixSbtRecordPackHeader(groups[3], &hit[0]));
        ML_CHECK(optixSbtRecordPackHeader(groups[4], &hit[1]));
        ML_CHECK(optixSbtRecordPackHeader(groups[5], &hit[2]));
        raygenRecord.upload(&raygen, sizeof(raygen));
        missRecords.upload(miss, sizeof(miss));
        hitRecord.upload(hit, sizeof(hit));
        sbt.raygenRecord = raygenRecord.ptr;
        sbt.missRecordBase = missRecords.ptr;
        sbt.missRecordStrideInBytes = sizeof(SbtRecord);
        sbt.missRecordCount = 2;
        sbt.hitgroupRecordBase = hitRecord.ptr;
        sbt.hitgroupRecordStrideInBytes = sizeof(SbtRecord);
        sbt.hitgroupRecordCount = 3;
        // The displacement pass runs with its own ray generation and the same records otherwise.
        SbtRecord displace;
        ML_CHECK(optixSbtRecordPackHeader(groups[6], &displace));
        displaceRecord.upload(&displace, sizeof(displace));
        displaceSbt = sbt;
        displaceSbt.raygenRecord = displaceRecord.ptr;
    }

    // refit moves an existing structure to the vertices now in the mesh's buffer.
    void buildMesh(Mesh& mesh, size_t vertexCount, size_t triangleCount, bool refit = false) {
        // Rays switch the any-hit test off themselves unless the scene has a partly absent material or a fog, whose
        // edges must each be counted once.
        const unsigned flags = OPTIX_GEOMETRY_FLAG_REQUIRE_SINGLE_ANYHIT_CALL;
        OptixBuildInput input = {};
        input.type = OPTIX_BUILD_INPUT_TYPE_TRIANGLES;
        input.triangleArray.vertexBuffers = &mesh.positions.ptr;
        input.triangleArray.numVertices = unsigned(vertexCount);
        input.triangleArray.vertexFormat = OPTIX_VERTEX_FORMAT_FLOAT3;
        input.triangleArray.vertexStrideInBytes = 3 * sizeof(float);
        input.triangleArray.indexBuffer = mesh.indices.ptr;
        input.triangleArray.numIndexTriplets = unsigned(triangleCount);
        input.triangleArray.indexFormat = OPTIX_INDICES_FORMAT_UNSIGNED_INT3;
        input.triangleArray.indexStrideInBytes = 3 * sizeof(uint32_t);
        input.triangleArray.flags = &flags;
        input.triangleArray.numSbtRecords = 1;
        if (mesh.curves) {
            input = OptixBuildInput{};
            input.type = OPTIX_BUILD_INPUT_TYPE_CURVES;
            input.curveArray.curveType = mesh.linear ? OPTIX_PRIMITIVE_TYPE_ROUND_LINEAR : OPTIX_PRIMITIVE_TYPE_ROUND_CUBIC_BSPLINE;
            input.curveArray.numPrimitives = unsigned(triangleCount);
            input.curveArray.vertexBuffers = &mesh.positions.ptr;
            input.curveArray.numVertices = unsigned(vertexCount);
            input.curveArray.vertexStrideInBytes = 3 * sizeof(float);
            input.curveArray.widthBuffers = &mesh.widths.ptr;
            input.curveArray.widthStrideInBytes = sizeof(float);
            input.curveArray.indexBuffer = mesh.indices.ptr;
            input.curveArray.indexStrideInBytes = sizeof(uint32_t);
            input.curveArray.flag = OPTIX_GEOMETRY_FLAG_REQUIRE_SINGLE_ANYHIT_CALL;
            input.curveArray.endcapFlags = mesh.linear ? OPTIX_CURVE_ENDCAP_DEFAULT : OPTIX_CURVE_ENDCAP_ON;
        }

        OptixAccelBuildOptions options = {};
        if (!mesh.close.empty()) {
            // A mesh that changes shape is refitted for every sample, so it is not compacted.
            options.buildFlags = mesh.curves ? CURVE_BUILD_FLAGS : OPTIX_BUILD_FLAG_ALLOW_UPDATE | OPTIX_BUILD_FLAG_PREFER_FAST_TRACE;
            options.operation = refit ? OPTIX_BUILD_OPERATION_UPDATE : OPTIX_BUILD_OPERATION_BUILD;
            if (refit) {
                accelTemp.reserve(mesh.updateBytes);
                ML_CHECK(optixAccelBuild(context, nullptr, &options, &input, 1, accelTemp.ptr, mesh.updateBytes,
                    mesh.accel.ptr, mesh.accelBytes, &mesh.handle, nullptr, 0));
                return;
            }
            OptixAccelBufferSizes sizes = {};
            ML_CHECK(optixAccelComputeMemoryUsage(context, &options, &input, 1, &sizes));
            accelTemp.reserve(sizes.tempSizeInBytes);
            mesh.accel.reserve(sizes.outputSizeInBytes);
            mesh.updateBytes = sizes.tempUpdateSizeInBytes;
            mesh.accelBytes = sizes.outputSizeInBytes;
            ML_CHECK(optixAccelBuild(context, nullptr, &options, &input, 1, accelTemp.ptr, sizes.tempSizeInBytes,
                mesh.accel.ptr, sizes.outputSizeInBytes, &mesh.handle, nullptr, 0));
            return;
        }
        options.buildFlags = mesh.curves ? CURVE_BUILD_FLAGS : OPTIX_BUILD_FLAG_ALLOW_COMPACTION | OPTIX_BUILD_FLAG_PREFER_FAST_TRACE;
        options.operation = OPTIX_BUILD_OPERATION_BUILD;
        OptixAccelBufferSizes sizes = {};
        ML_CHECK(optixAccelComputeMemoryUsage(context, &options, &input, 1, &sizes));
        accelTemp.reserve(sizes.tempSizeInBytes);
        mesh.accel.reserve(sizes.outputSizeInBytes);
        Buffer compactedSize;
        compactedSize.reserve(sizeof(uint64_t));
        OptixAccelEmitDesc emit = {};
        emit.result = compactedSize.ptr;
        emit.type = OPTIX_PROPERTY_TYPE_COMPACTED_SIZE;
        ML_CHECK(optixAccelBuild(context, nullptr, &options, &input, 1, accelTemp.ptr, sizes.tempSizeInBytes,
            mesh.accel.ptr, sizes.outputSizeInBytes, &mesh.handle, &emit, 1));

        uint64_t compacted = 0;
        ML_CHECK(cudaMemcpy(&compacted, reinterpret_cast<void*>(compactedSize.ptr), sizeof(compacted), cudaMemcpyDeviceToHost));
        if (compacted && compacted < sizes.outputSizeInBytes) {
            Buffer smaller;
            smaller.reserve(compacted);
            ML_CHECK(optixAccelCompact(context, nullptr, mesh.handle, smaller.ptr, compacted, &mesh.handle));
            ML_CHECK(cudaDeviceSynchronize());
            mesh.accel.swap(smaller);
        }
    }

    void uploadMeshTable() {
        std::vector<DeviceMesh> table;
        for (const auto& mesh : meshes) {
            DeviceMesh entry = {};
            if (mesh) {
                entry.positions = mesh->positions.ptr;
                entry.normals = mesh->normals.ptr;
                entry.indices = mesh->indices.ptr;
                entry.materialIds = mesh->materialIds.ptr;
                entry.uvs = mesh->uvs.ptr;
                entry.triangleCount = mesh->triangleCount;
                entry.curves = mesh->curves ? (mesh->linear ? 2 : 1) | (mesh->ribbon ? 4 : 0) : 0;
                // A slot may only name a set this mesh has; the kernel does not check.
                for (unsigned slot = 0; slot < UV_SLOTS; ++slot)
                    entry.uvSet[slot] = mesh->uvSlots[slot] >= 0 && uint32_t(mesh->uvSlots[slot]) < mesh->uvSetCount ? mesh->uvSlots[slot] : -1;
            }
            table.push_back(entry);
        }
        meshTable.upload(table);
        params.meshes = meshTable.ptr;
    }

    // time runs from 0, the shutter opening, to 1, its closing.
    void buildInstances(float time = 0.0f) {
        std::vector<OptixInstance> input(instances.size());
        std::vector<DeviceInstance> table(instances.size());
        bool mixed = false;
        for (size_t i = 0; i < instances.size(); ++i) {
            for (int k = 0; k < 12; ++k)
                input[i].transform[k] = instances[i].moves ? instances[i].transform[k] + (instances[i].closeTransform[k] - instances[i].transform[k]) * time
                                                           : instances[i].transform[k];
            input[i].instanceId = unsigned(i);
            input[i].sbtOffset = meshes[instances[i].mesh]->curves ? (meshes[instances[i].mesh]->linear ? 2 : 1) : 0;
            input[i].visibilityMask = instances[i].visibility & 255u;
            if ((instances[i].visibility & 31u) != 31u) mixed = true;
            input[i].flags = OPTIX_INSTANCE_FLAG_NONE;
            input[i].traversableHandle = meshes[instances[i].mesh]->handle;
            table[i] = {instances[i].mesh, instances[i].material, instances[i].light, instances[i].visibility >> 8};
        }
        params.mixedVisibility = mixed ? 1 : 0;
        instanceTable.upload(table);
        params.instances = instanceTable.ptr;
        params.traversable = 0;     // tracing an empty scene always misses
        if (instances.empty()) return;

        instanceInput.upload(input);
        OptixBuildInput build = {};
        build.type = OPTIX_BUILD_INPUT_TYPE_INSTANCES;
        build.instanceArray.instances = instanceInput.ptr;
        build.instanceArray.numInstances = unsigned(input.size());
        OptixAccelBuildOptions options = {};
        options.buildFlags = OPTIX_BUILD_FLAG_PREFER_FAST_BUILD;
        options.operation = OPTIX_BUILD_OPERATION_BUILD;
        OptixAccelBufferSizes sizes = {};
        ML_CHECK(optixAccelComputeMemoryUsage(context, &options, &build, 1, &sizes));
        accelTemp.reserve(sizes.tempSizeInBytes);
        instanceAccel.reserve(sizes.outputSizeInBytes);
        OptixTraversableHandle handle = 0;
        ML_CHECK(optixAccelBuild(context, nullptr, &options, &build, 1, accelTemp.ptr, sizes.tempSizeInBytes,
            instanceAccel.ptr, sizes.outputSizeInBytes, &handle, nullptr, 0));
        params.traversable = handle;
    }

    // Puts the scene where it is at one moment of the shutter: the camera, the meshes that change
    // shape, and then the instance layer, which holds what moves and bounds what changed.
    void setTime(float time) {
        if (cameraMoves) {
            const Camera held = camera;
            for (int i = 0; i < 3; ++i) {
                camera.eye[i] += (cameraClose.eye[i] - camera.eye[i]) * time;
                camera.target[i] += (cameraClose.target[i] - camera.target[i]) * time;
                camera.up[i] += (cameraClose.up[i] - camera.up[i]) * time;
            }
            camera.verticalFovDegrees += (cameraClose.verticalFovDegrees - camera.verticalFovDegrees) * time;
            updateCamera();
            camera = held;
        }
        if (meshesMove) {
            std::vector<float> blended;
            for (const auto& mesh : meshes) {
                if (!mesh || mesh->close.empty()) continue;
                blended.resize(mesh->open.size());
                for (size_t i = 0; i < blended.size(); ++i) blended[i] = mesh->open[i] + (mesh->close[i] - mesh->open[i]) * time;
                mesh->positions.upload(blended);
                buildMesh(*mesh, mesh->vertexCount, mesh->triangleCount, true);
            }
        }
        if (instancesMove || meshesMove) buildInstances(time);
        if (lightsMove) {
            const auto blend = [time](const float* a, const float* b, float* out, bool unitLength) {
                for (int k = 0; k < 3; ++k) out[k] = a[k] + (b[k] - a[k]) * time;
                if (unitLength) scaleTo(out, 1.0f);
            };
            std::vector<DeviceDistantLight> distant = distantOpen;
            for (size_t i = 0; i < distant.size(); ++i) {
                blend(distantOpen[i].direction, distantClose[i].direction, distant[i].direction, true);
                blend(distantOpen[i].u, distantClose[i].u, distant[i].u, distant[i].texture != 0);
                blend(distantOpen[i].v, distantClose[i].v, distant[i].v, distant[i].texture != 0);
            }
            std::vector<DeviceLight> local = lightsOpen;
            for (size_t i = 0; i < local.size(); ++i) {
                if (local[i].type == LIGHT_MESH) continue;
                blend(lightsOpen[i].position, lightsClose[i].position, local[i].position, false);
                blend(lightsOpen[i].u, lightsClose[i].u, local[i].u, false);
                blend(lightsOpen[i].v, lightsClose[i].v, local[i].v, false);
                blend(lightsOpen[i].normal, lightsClose[i].normal, local[i].normal, true);
            }
            if (!distant.empty()) {
                distantLights.upload(distant);
                params.distantLights = distantLights.ptr;
            }
            if (!local.empty()) {
                lights.upload(local);
                params.lights = lights.ptr;
            }
        }
    }

    void updateCamera() {
        if (!params.width || !params.height) return;
        float w[3], u[3], v[3];
        subtract(camera.target, camera.eye, w);
        scaleTo(w, 1.0f);
        cross(w, camera.up, u);
        const float halfHeight = std::tan(camera.verticalFovDegrees * 3.14159265358979323846f / 360.0f);
        scaleTo(u, halfHeight * float(params.width) / float(params.height));
        cross(u, w, v);
        scaleTo(v, halfHeight);
        std::copy(camera.eye, camera.eye + 3, params.cameraOrigin);
        std::copy(u, u + 3, params.cameraU);
        std::copy(v, v + 3, params.cameraV);
        std::copy(w, w + 3, params.cameraW);
        params.lensRadius = std::max(camera.lensRadius, 0.0f);
        params.focusDistance = std::max(camera.focusDistance, 1e-6f);
        params.lensBlades = camera.blades >= 3 ? std::min<uint32_t>(camera.blades, 64) : 0;
        params.lensAngle = camera.bladeAngle;
        params.cameraProjection = camera.projection <= 3 ? camera.projection : 0;
        std::copy(camera.projectionValues, camera.projectionValues + 4, params.cameraProjectionValues);
        // Rows count upward from the picture's foot; the region's top and bottom are measured from its head.
        const auto edge = [](float fraction, unsigned size) { return unsigned(std::lround(std::clamp(fraction, 0.0f, 1.0f) * float(size))); };
        params.draft = camera.draft <= 2 ? camera.draft : 0;
        // The film offset is in halves of the film's width; up the picture, a half of its height is less by its shape.
        params.cameraShift[0] = camera.filmShift[0];
        params.cameraShift[1] = camera.filmShift[1] * float(params.width) / float(params.height);
        params.region[0] = edge(camera.region[0], params.width);
        params.region[2] = edge(camera.region[2], params.width);
        params.region[1] = edge(1.0f - camera.region[3], params.height);
        params.region[3] = edge(1.0f - camera.region[1], params.height);
        if (params.region[2] <= params.region[0] || params.region[3] <= params.region[1]) {
            params.region[0] = params.region[1] = 0;
            params.region[2] = params.width;
            params.region[3] = params.height;
        }
    }

    // Material indices are followed on the GPU without bounds checks, so reject bad ones here.
    void validate() {
        if (validated) return;
        if (!params.width || !params.height) throw std::runtime_error("MoonLightIPR has no image size; call resize first");
        for (const Instance& instance : instances) {
            const Mesh& mesh = *meshes[instance.mesh];
            const uint32_t highest = mesh.ownsMaterials ? mesh.maxMaterial : instance.material;
            if (highest >= materialCount) throw std::runtime_error("MoonLightIPR instance refers to a missing material");
            if (instance.light >= 0 && size_t(instance.light) >= lightCount)
                throw std::runtime_error("MoonLightIPR instance refers to a missing light");
        }
        validated = true;
    }

    void restart() {
        samples = 0;
        validated = false;
        clean = false;
    }

    // How a difference shows on the screen: the light squeezed into 0 to 1, then encoded as sRGB is, so that noise
    // in the dark counts as much as the eye sees it there.
    static float shown(float value) {
        const float squeezed = std::max(value, 0.0f) / (1.0f + std::max(value, 0.0f));
        return squeezed <= 0.0031308f ? 12.92f * squeezed : 1.055f * std::pow(squeezed, 1.0f / 2.4f) - 0.055f;
    }

    // Each square of the picture is judged by how far the mean of its even samples lies from the mean of them all,
    // which is about how noisy the picture there still is. A square under cleanBelow at two checks running takes no
    // more samples; once every square has, the picture is clean and the render can rest.
    void converge() {
        const uint32_t width = params.width, height = params.height;
        const size_t count = size_t(width) * height;
        std::vector<float> all(count * 4), even(count * 4);
        ML_CHECK(cudaMemcpy(all.data(), reinterpret_cast<void*>(beauty.ptr), all.size() * sizeof(float), cudaMemcpyDeviceToHost));
        ML_CHECK(cudaMemcpy(even.data(), reinterpret_cast<void*>(half.ptr), even.size() * sizeof(float), cudaMemcpyDeviceToHost));
        const uint32_t columns = params.doneColumns, rows = (height + CLEAN_TILE - 1) / CLEAN_TILE;
        bool everywhere = true;
        for (uint32_t row = 0; row < rows; ++row)
            for (uint32_t column = 0; column < columns; ++column) {
                const size_t tile = size_t(row) * columns + column;
                if (tileDone[tile]) continue;
                float noise = 0.0f;
                uint32_t pixels = 0;
                for (uint32_t y = row * CLEAN_TILE; y < std::min(height, (row + 1) * CLEAN_TILE); ++y)
                    for (uint32_t x = column * CLEAN_TILE; x < std::min(width, (column + 1) * CLEAN_TILE); ++x, ++pixels) {
                        const size_t i = (size_t(y) * width + x) * 4;
                        float apart = 0.0f;
                        for (int c = 0; c < 3; ++c) apart = std::max(apart, std::fabs(shown(all[i + c]) - shown(even[i + c])));
                        noise += apart;
                    }
                const bool passes = noise < cleanBelow * float(pixels);
                if (passes && tilePassed[tile]) tileDone[tile] = 1;
                tilePassed[tile] = passes ? 1 : 0;
                everywhere = everywhere && tileDone[tile];
            }
        done.upload(tileDone);
        clean = everywhere;
    }

    void download(const Buffer& source, float* rgb) {
        const size_t count = size_t(params.width) * params.height;
        std::vector<float> pixels(count * 4);
        ML_CHECK(cudaMemcpy(pixels.data(), reinterpret_cast<void*>(source.ptr), pixels.size() * sizeof(float), cudaMemcpyDeviceToHost));
        for (size_t i = 0; i < count; ++i) std::copy(&pixels[i * 4], &pixels[i * 4] + 3, rgb + i * 3);
    }

    OptixImage2D image(const Buffer& buffer) const {
        OptixImage2D result = {};
        result.data = buffer.ptr;
        result.width = params.width;
        result.height = params.height;
        result.rowStrideInBytes = params.width * 4 * sizeof(float);
        result.pixelStrideInBytes = 4 * sizeof(float);
        result.format = OPTIX_PIXEL_FORMAT_FLOAT4;
        return result;
    }

    // How the denoiser is used. Textures survive it best when it is given the light alone: the picture is
    // divided by the surface colour first, denoised, and multiplied by it again, so that what is in the
    // colour (a wood grain, a printed pattern) is never the denoiser's to smooth. As a picture gathers
    // samples its own detail is trusted more, and a growing share of it is kept beside the denoised one.
    // MOONLIGHTIPR_DENOISE chooses for experiments: "plain" is the denoiser alone, as it was.
    bool lightAlone() const {
        const char* mode = std::getenv("MOONLIGHTIPR_DENOISE");
        return !mode || std::string(mode) != "plain";
    }
    float keptShare() const {
        const char* mode = std::getenv("MOONLIGHTIPR_DENOISE_KEEP");
        if (mode) return std::clamp(float(std::atof(mode)), 0.0f, 1.0f);
        // None of the picture's own noise up to 32 samples, half of it at 256, four fifths from 1024 on: about
        // the shares at which the two, measured against a finished picture, are as wrong as each other.
        return std::clamp((std::log2(float(std::max(samples, 1u))) - 5.0f) / 6.0f, 0.0f, 0.8f);
    }

    void denoise() {
        const size_t count = size_t(params.width) * params.height;
        // The surface colour is never quite nothing, so that dividing by it is safe; the same is multiplied back.
        const float floor = 0.05f;
        std::vector<float> colour, light;
        if (lightAlone()) {
            colour.resize(count * 4);
            light.resize(count * 4);
            ML_CHECK(cudaMemcpy(colour.data(), reinterpret_cast<void*>(albedo.ptr), colour.size() * sizeof(float), cudaMemcpyDeviceToHost));
            ML_CHECK(cudaMemcpy(light.data(), reinterpret_cast<void*>(beauty.ptr), light.size() * sizeof(float), cudaMemcpyDeviceToHost));
            for (size_t i = 0; i < count; ++i)
                for (int c = 0; c < 3; ++c) light[i * 4 + c] /= std::max(colour[i * 4 + c], 0.0f) + floor;
            lighting.upload(light.data(), light.size() * sizeof(float));
        }
        if (!denoiser) {
            OptixDenoiserOptions options = {};
            options.guideAlbedo = 1;
            options.guideNormal = 1;
            ML_CHECK(optixDenoiserCreate(context, OPTIX_DENOISER_MODEL_KIND_HDR, &options, &denoiser));
            ML_CHECK(optixDenoiserComputeMemoryResources(denoiser, params.width, params.height, &denoiserSizes));
            denoiserScratchBytes = std::max(denoiserSizes.withoutOverlapScratchSizeInBytes, denoiserSizes.computeIntensitySizeInBytes);
            denoiserState.reserve(denoiserSizes.stateSizeInBytes);
            denoiserScratch.reserve(denoiserScratchBytes);
            denoiserIntensity.reserve(sizeof(float));
            ML_CHECK(optixDenoiserSetup(denoiser, nullptr, params.width, params.height, denoiserState.ptr,
                denoiserSizes.stateSizeInBytes, denoiserScratch.ptr, denoiserScratchBytes));
        }
        OptixDenoiserGuideLayer guides = {};
        guides.albedo = image(albedo);
        guides.normal = image(normal);
        OptixDenoiserLayer layer = {};
        layer.input = image(lightAlone() ? lighting : beauty);
        layer.output = image(denoised);
        OptixDenoiserParams denoiserParams = {};
        denoiserParams.denoiseAlpha = OPTIX_DENOISER_ALPHA_MODE_COPY;
        denoiserParams.hdrIntensity = denoiserIntensity.ptr;
        denoiserParams.blendFactor = keptShare();
        ML_CHECK(optixDenoiserComputeIntensity(denoiser, nullptr, &layer.input, denoiserIntensity.ptr,
            denoiserScratch.ptr, denoiserScratchBytes));
        ML_CHECK(optixDenoiserInvoke(denoiser, nullptr, &denoiserParams, denoiserState.ptr, denoiserSizes.stateSizeInBytes,
            &guides, &layer, 1, 0, 0, denoiserScratch.ptr, denoiserScratchBytes));
        if (lightAlone()) {
            ML_CHECK(cudaMemcpy(light.data(), reinterpret_cast<void*>(denoised.ptr), light.size() * sizeof(float), cudaMemcpyDeviceToHost));
            for (size_t i = 0; i < count; ++i)
                for (int c = 0; c < 3; ++c) light[i * 4 + c] *= std::max(colour[i * 4 + c], 0.0f) + floor;
            denoised.upload(light.data(), light.size() * sizeof(float));
        }
    }
};

Renderer::Renderer(const std::string& ptxPath) : impl(new Impl) {
    ML_CHECK(cudaFree(nullptr));    // creates the CUDA context OptiX attaches to
    if (optixInit() != OPTIX_SUCCESS)
        throw std::runtime_error("OptiX is unavailable; MoonLightIPR needs an NVIDIA RTX driver");
    OptixDeviceContextOptions options = {};
    options.logCallbackFunction = &logCallback;
    options.logCallbackLevel = 2;
    ML_CHECK(optixDeviceContextCreate(nullptr, &options, &impl->context));
    impl->kernelPath = ptxPath;
    impl->createPipeline(ptxPath);
    // MoonRay's defaults, including its sample_clamping_value.
    impl->params.maxDepth = 4;
    impl->params.maxDiffuseDepth = impl->params.maxGlossyDepth = 2;
    impl->params.maxVolumeDepth = 1;
    impl->params.sampleClamp = 10.0f;
    impl->params.sampleClampDepth = 1;
    impl->params.volumeAttenuation = impl->params.volumeContribution = 0.65f;
    impl->params.volumePhaseAttenuation = 0.5f;
    {
        const char* toon = std::getenv("MOONRAY_MODO_TOON_TERMINATOR");
        impl->params.toonTerminator = toon && toon[0] == '1';
    }
    std::vector<float> albedo = albedoTable(false);
    const std::vector<float> beckmann = albedoTable(true);
    albedo.insert(albedo.end(), beckmann.begin(), beckmann.end());
    impl->albedoTables.upload(albedo);
    impl->params.albedo2 = impl->albedoTables.ptr;
    setEnvironment(Environment());
}

Renderer::~Renderer() = default;

uint32_t Renderer::addMesh(const MeshDesc& desc) {
    if (!desc.positions || !desc.indices || !desc.vertexCount || !desc.triangleCount)
        throw std::runtime_error("MoonLightIPR mesh needs positions and triangle indices");
    if (desc.vertexCount > 0xffffffffu || desc.triangleCount > 0xffffffffu)
        throw std::runtime_error("MoonLightIPR mesh is too large");
    for (size_t i = 0; i < desc.triangleCount * 3; ++i)
        if (desc.indices[i] >= desc.vertexCount) throw std::runtime_error("MoonLightIPR mesh index is out of range");

    auto mesh = std::make_unique<Mesh>();
    mesh->positions.upload(desc.positions, desc.vertexCount * 3 * sizeof(float));
    mesh->indices.upload(desc.indices, desc.triangleCount * 3 * sizeof(uint32_t));
    if (desc.normals) mesh->normals.upload(desc.normals, desc.vertexCount * 3 * sizeof(float));
    if (desc.materialIds) {
        mesh->materialIds.upload(desc.materialIds, desc.triangleCount * sizeof(uint32_t));
        mesh->ownsMaterials = true;
        mesh->maxMaterial = *std::max_element(desc.materialIds, desc.materialIds + desc.triangleCount);
    }
    mesh->triangleCount = uint32_t(desc.triangleCount);
    mesh->vertexCount = desc.vertexCount;
    if (desc.closePositions) {
        mesh->open.assign(desc.positions, desc.positions + desc.vertexCount * 3);
        mesh->close.assign(desc.closePositions, desc.closePositions + desc.vertexCount * 3);
    }
    if (desc.uvSetCount) {
        const size_t perSet = desc.triangleCount * 6;
        std::vector<float> all(perSet * desc.uvSetCount);
        for (size_t set = 0; set < desc.uvSetCount; ++set)
            std::copy(desc.uvSets[set], desc.uvSets[set] + perSet, all.begin() + set * perSet);
        mesh->uvs.upload(all);
        mesh->uvSetCount = uint32_t(desc.uvSetCount);
    }
    impl->buildMesh(*mesh, desc.vertexCount, desc.triangleCount);
    auto slot = std::find(impl->meshes.begin(), impl->meshes.end(), nullptr);
    if (slot == impl->meshes.end()) slot = impl->meshes.emplace(slot);
    *slot = std::move(mesh);
    impl->uploadMeshTable();
    impl->restart();
    return uint32_t(slot - impl->meshes.begin());
}

uint32_t Renderer::addCurves(const CurveDesc& desc) {
    if (!desc.positions || !desc.radii || !desc.segments || !desc.pointCount || !desc.segmentCount)
        throw std::runtime_error("MoonLightIPR curves need control points, radii and segments");
    if (desc.pointCount > 0xffffffffu || desc.segmentCount > 0xffffffffu) throw std::runtime_error("MoonLightIPR curves are too large");
    for (size_t i = 0; i < desc.segmentCount; ++i)
        if (size_t(desc.segments[i]) + (desc.linear ? 2 : 4) > desc.pointCount) throw std::runtime_error("MoonLightIPR curve segment is out of range");
    for (size_t i = 0; i < desc.pointCount; ++i)
        if (!(desc.radii[i] >= 0.0f) || !std::isfinite(desc.radii[i])) throw std::runtime_error("MoonLightIPR curve radius is invalid");
    auto mesh = std::make_unique<Mesh>();
    mesh->curves = true;
    mesh->linear = desc.linear;
    mesh->ribbon = desc.ribbon;
    if (desc.strands) mesh->normals.upload(desc.strands, desc.pointCount * 3 * sizeof(float));
    if (desc.closePositions) {
        mesh->open.assign(desc.positions, desc.positions + desc.pointCount * 3);
        mesh->close.assign(desc.closePositions, desc.closePositions + desc.pointCount * 3);
    }
    mesh->positions.upload(desc.positions, desc.pointCount * 3 * sizeof(float));
    mesh->widths.upload(desc.radii, desc.pointCount * sizeof(float));
    mesh->indices.upload(desc.segments, desc.segmentCount * sizeof(uint32_t));
    if (desc.uvs) {
        mesh->uvs.upload(desc.uvs, desc.pointCount * 2 * sizeof(float));
        mesh->uvSetCount = 1;
    }
    mesh->triangleCount = uint32_t(desc.segmentCount);
    mesh->vertexCount = desc.pointCount;
    impl->buildMesh(*mesh, desc.pointCount, desc.segmentCount);
    auto slot = std::find(impl->meshes.begin(), impl->meshes.end(), nullptr);
    if (slot == impl->meshes.end()) slot = impl->meshes.emplace(slot);
    *slot = std::move(mesh);
    impl->uploadMeshTable();
    impl->restart();
    return uint32_t(slot - impl->meshes.begin());
}

void Renderer::removeMesh(uint32_t mesh) {
    if (mesh >= impl->meshes.size() || !impl->meshes[mesh]) throw std::runtime_error("MoonLightIPR mesh does not exist");
    for (const Instance& instance : impl->instances)
        if (instance.mesh == mesh) throw std::runtime_error("MoonLightIPR mesh is still instanced");
    ML_CHECK(cudaDeviceSynchronize());  // a queued launch may still read its buffers
    impl->meshes[mesh].reset();
    impl->uploadMeshTable();
}

void Renderer::setInstances(const Instance* instances, size_t count) {
    for (size_t i = 0; i < count; ++i)
        if (instances[i].mesh >= impl->meshes.size() || !impl->meshes[instances[i].mesh])
            throw std::runtime_error("MoonLightIPR instance refers to a missing mesh");
    impl->instances.assign(instances, instances + count);
    impl->instancesMove = impl->meshesMove = false;
    for (const Instance& instance : impl->instances) {
        impl->instancesMove = impl->instancesMove || instance.moves;
        impl->meshesMove = impl->meshesMove || !impl->meshes[instance.mesh]->close.empty();
    }
    impl->buildInstances();
    impl->restart();
}

void Renderer::setMeshUvSlots(uint32_t mesh, const int32_t slots[UV_SLOT_COUNT]) {
    if (mesh >= impl->meshes.size() || !impl->meshes[mesh]) throw std::runtime_error("MoonLightIPR mesh does not exist");
    if (std::equal(slots, slots + UV_SLOTS, impl->meshes[mesh]->uvSlots)) return;
    std::copy(slots, slots + UV_SLOTS, impl->meshes[mesh]->uvSlots);
    impl->uploadMeshTable();
    impl->restart();
}

namespace {

uint16_t toHalf(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, 4);
    const uint32_t sign = (bits >> 16) & 0x8000u;
    const int32_t exponent = int32_t((bits >> 23) & 0xffu) - 127 + 15;
    uint32_t mantissa = bits & 0x7fffffu;
    if (((bits >> 23) & 0xffu) == 0xffu) return uint16_t(sign | 0x7c00u | (mantissa ? 0x200u : 0u));   // not a number, or infinite
    if (exponent >= 31) return uint16_t(sign | 0x7c00u);                                               // too large: infinite
    if (exponent <= 0) {
        if (exponent < -10) return uint16_t(sign);                                                     // too small: nothing
        mantissa |= 0x800000u;
        const uint32_t shift = uint32_t(14 - exponent);
        uint32_t half = mantissa >> shift;
        if ((mantissa >> (shift - 1)) & 1u) ++half;                                                    // rounded
        return uint16_t(sign | half);
    }
    uint32_t half = sign | (uint32_t(exponent) << 10) | (mantissa >> 13);
    if (mantissa & 0x1000u) ++half;                                                                    // rounded
    return uint16_t(half);
}

float fromSrgb(float c) { return c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f); }
float toSrgb(float c) { return c <= 0.0031308f ? c * 12.92f : 1.055f * std::pow(c, 1.0f / 2.4f) - 0.055f; }

// A picture of four floats a texel, halved across and down, each texel the mean of the four (or two, at an odd edge)
// it covers.
void halve(std::vector<float>& rgba, uint32_t& width, uint32_t& height) {
    const uint32_t w = std::max(1u, width / 2), h = std::max(1u, height / 2);
    std::vector<float> out(size_t(w) * h * 4);
    for (uint32_t y = 0; y < h; ++y)
        for (uint32_t x = 0; x < w; ++x) {
            float sum[4] = {0, 0, 0, 0};
            int count = 0;
            for (uint32_t dy = 0; dy < 2; ++dy)
                for (uint32_t dx = 0; dx < 2; ++dx) {
                    const uint32_t sx = std::min(width - 1, x * 2 + dx), sy = std::min(height - 1, y * 2 + dy);
                    const float* in = &rgba[(size_t(sy) * width + sx) * 4];
                    for (int c = 0; c < 4; ++c) sum[c] += in[c];
                    ++count;
                }
            for (int c = 0; c < 4; ++c) out[(size_t(y) * w + x) * 4 + c] = sum[c] / float(count);
        }
    rgba.swap(out);
    width = w;
    height = h;
}

}

uint32_t Renderer::addTexture(const TextureDesc& desc) {
    if (!desc.pixels || !desc.width || !desc.height || desc.width > 16384 || desc.height > 16384)
        throw std::runtime_error("MoonLightIPR texture has no pixels or is too large");
    auto texture = std::make_unique<Texture>();
    // What the card is given: the picture as it is, or halved to its size limit, with a picture of high dynamic range
    // as halves. Bytes are halved as light, from sRGB where they are sRGB, so that a smaller picture is not darker.
    uint32_t width = desc.width, height = desc.height;
    std::vector<unsigned char> bytes;
    std::vector<uint16_t> halves;
    const bool smaller = desc.maxSize && std::max(width, height) > desc.maxSize;
    if (desc.floatData || smaller) {
        std::vector<float> rgba(size_t(width) * height * 4);
        for (size_t i = 0; i < rgba.size(); ++i) {
            if (desc.floatData) rgba[i] = static_cast<const float*>(desc.pixels)[i];
            else {
                const float v = static_cast<const unsigned char*>(desc.pixels)[i] / 255.0f;
                rgba[i] = desc.srgb && (i % 4) != 3 ? fromSrgb(v) : v;
            }
        }
        while (desc.maxSize && std::max(width, height) > desc.maxSize) halve(rgba, width, height);
        if (desc.floatData) {
            halves.resize(rgba.size());
            for (size_t i = 0; i < rgba.size(); ++i) halves[i] = toHalf(rgba[i]);
        } else {
            bytes.resize(rgba.size());
            for (size_t i = 0; i < rgba.size(); ++i) {
                const float v = desc.srgb && (i % 4) != 3 ? toSrgb(rgba[i]) : rgba[i];
                bytes[i] = static_cast<unsigned char>(std::lround(std::min(1.0f, std::max(0.0f, v)) * 255.0f));
            }
        }
    }
    const void* uploaded = desc.floatData ? static_cast<const void*>(halves.data()) : (bytes.empty() ? desc.pixels : bytes.data());
    const cudaChannelFormatDesc format = desc.floatData ? cudaCreateChannelDesc(16, 16, 16, 16, cudaChannelFormatKindFloat)
                                                        : cudaCreateChannelDesc(8, 8, 8, 8, cudaChannelFormatKindUnsigned);
    const size_t rowBytes = size_t(width) * (desc.floatData ? 8 : 4);
    ML_CHECK(cudaMallocArray(&texture->array, &format, width, height));
    ML_CHECK(cudaMemcpy2DToArray(texture->array, 0, 0, uploaded, rowBytes, rowBytes, height, cudaMemcpyHostToDevice));
    cudaResourceDesc resource = {};
    resource.resType = cudaResourceTypeArray;
    resource.res.array.array = texture->array;
    const cudaTextureAddressMode modes[] = {cudaAddressModeWrap, cudaAddressModeClamp, cudaAddressModeMirror, cudaAddressModeBorder};
    cudaTextureDesc sampling = {};
    sampling.addressMode[0] = modes[std::min<uint32_t>(desc.wrapU, 3)];
    sampling.addressMode[1] = modes[std::min<uint32_t>(desc.wrapV, 3)];
    sampling.filterMode = cudaFilterModeLinear;
    sampling.readMode = desc.floatData ? cudaReadModeElementType : cudaReadModeNormalizedFloat;
    sampling.normalizedCoords = 1;
    sampling.sRGB = desc.srgb && !desc.floatData;
    ML_CHECK(cudaCreateTextureObject(&texture->object, &resource, &sampling, nullptr));
    texture->gridWidth = std::min<uint32_t>(desc.width, 64);
    texture->gridHeight = std::min<uint32_t>(desc.height, 64);
    texture->brightness.assign(size_t(texture->gridWidth) * texture->gridHeight, 0.0f);
    for (uint32_t y = 0; y < desc.height; ++y)
        for (uint32_t x = 0; x < desc.width; ++x) {
            const size_t i = (size_t(y) * desc.width + x) * 4;
            float rgb[3];
            for (int c = 0; c < 3; ++c)
                rgb[c] = desc.floatData ? static_cast<const float*>(desc.pixels)[i + c] : static_cast<const unsigned char*>(desc.pixels)[i + c] / 255.0f;
            const float value = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
            if (std::isfinite(value) && value > 0.0f)
                texture->brightness[size_t(uint64_t(y) * texture->gridHeight / desc.height) * texture->gridWidth + size_t(uint64_t(x) * texture->gridWidth / desc.width)] += value;
        }
    auto slot = std::find(impl->textures.begin(), impl->textures.end(), nullptr);
    if (slot == impl->textures.end()) slot = impl->textures.emplace(slot);
    *slot = std::move(texture);
    return uint32_t(slot - impl->textures.begin());
}

uint32_t Renderer::addGrid(const GridDesc& desc) {
    const size_t count = size_t(desc.counts[0]) * desc.counts[1] * desc.counts[2];
    if (!desc.values || !count || desc.counts[0] > 2048 || desc.counts[1] > 2048 || desc.counts[2] > 2048)
        throw std::runtime_error("MoonLightIPR grid has no values or is too large");
    auto grid = std::make_unique<Texture>();
    const bool colours = desc.channels == 4;
    const cudaChannelFormatDesc format = cudaCreateChannelDesc(32, colours ? 32 : 0, colours ? 32 : 0, colours ? 32 : 0, cudaChannelFormatKindFloat);
    const cudaExtent extent = make_cudaExtent(desc.counts[0], desc.counts[1], desc.counts[2]);
    ML_CHECK(cudaMalloc3DArray(&grid->array, &format, extent));
    cudaMemcpy3DParms copy = {};
    copy.srcPtr = make_cudaPitchedPtr(const_cast<float*>(desc.values), desc.counts[0] * sizeof(float) * (colours ? 4 : 1), desc.counts[0], desc.counts[1]);
    copy.dstArray = grid->array;
    copy.extent = extent;
    copy.kind = cudaMemcpyHostToDevice;
    ML_CHECK(cudaMemcpy3D(&copy));
    cudaResourceDesc resource = {};
    resource.resType = cudaResourceTypeArray;
    resource.res.array.array = grid->array;
    cudaTextureDesc sampling = {};
    // Outside the grid there is no fog.
    for (int axis = 0; axis < 3; ++axis) sampling.addressMode[axis] = cudaAddressModeBorder;
    sampling.filterMode = cudaFilterModeLinear;
    sampling.readMode = cudaReadModeElementType;
    sampling.normalizedCoords = 1;
    ML_CHECK(cudaCreateTextureObject(&grid->object, &resource, &sampling, nullptr));
    auto slot = std::find(impl->grids.begin(), impl->grids.end(), nullptr);
    if (slot == impl->grids.end()) { slot = impl->grids.emplace(slot); impl->gridPeaks.push_back(0.0f); }
    *slot = std::move(grid);
    // A grid of colours is told from one of numbers by a peak below nothing: the two are read differently on the GPU.
    impl->gridPeaks[slot - impl->grids.begin()] = colours ? -1.0f : std::max(desc.peak, 0.0f);
    return uint32_t(slot - impl->grids.begin());
}

void Renderer::removeGrid(uint32_t grid) {
    if (grid >= impl->grids.size() || !impl->grids[grid]) throw std::runtime_error("MoonLightIPR grid does not exist");
    if (std::find(impl->volumeGrids.begin(), impl->volumeGrids.end(), int32_t(grid)) != impl->volumeGrids.end()
        || std::find(impl->lightGrids.begin(), impl->lightGrids.end(), int32_t(grid)) != impl->lightGrids.end())
        throw std::runtime_error("MoonLightIPR grid is still used by a material");
    ML_CHECK(cudaDeviceSynchronize());
    impl->grids[grid].reset();
}

void Renderer::removeTexture(uint32_t texture) {
    if (texture >= impl->textures.size() || !impl->textures[texture]) throw std::runtime_error("MoonLightIPR texture does not exist");
    if (std::find(impl->layerTextures.begin(), impl->layerTextures.end(), int32_t(texture)) != impl->layerTextures.end()
        || std::find(impl->lightTextures.begin(), impl->lightTextures.end(), int32_t(texture)) != impl->lightTextures.end()
        || std::find(impl->distantTextures.begin(), impl->distantTextures.end(), int32_t(texture)) != impl->distantTextures.end())
        throw std::runtime_error("MoonLightIPR texture is still used by a material or a light");
    ML_CHECK(cudaDeviceSynchronize());  // a queued launch may still sample it
    impl->textures[texture].reset();
}

void Renderer::setMaterials(const Material* materials, size_t count, const Layer* layers, size_t layerCount,
                            const int32_t* tiles, size_t tileCount) {
    // The kernel for what these materials use: without the code of the heavy features none of them has.
    unsigned features = 0;
    for (size_t i = 0; i < count; ++i) {
        const Material& m = materials[i];
        if (m.volume) features |= FEATURE_FOG;
        if (m.hair) features |= FEATURE_HAIR;
        if (m.subsurface > 0.0f && m.subsurfaceRadius > 0.0f) features |= FEATURE_SUBSURFACE;
        if (m.toonDiffuse || m.toonSpecular) features |= FEATURE_TOON;
        if (m.fuzz > 0.0f) features |= FEATURE_FUZZ;
    }
    for (size_t i = 0; i < layerCount; ++i)
        if (layers[i].channel == CHANNEL_SUBSURFACE || layers[i].channel == CHANNEL_SUBSURFACE_COLOR) features |= FEATURE_SUBSURFACE;
    impl->specialize(features);
    std::vector<DeviceMaterial> table(count);
    std::transform(materials, materials + count, table.begin(), toDevice);
    std::vector<DeviceHair> hairs;
    for (size_t i = 0; i < count; ++i) {
        if (!materials[i].hair) continue;
        table[i].flags |= MATERIAL_HAIR;
        table[i].hair = unsigned(hairs.size());
        hairs.push_back(toDeviceHair(materials[i]));
    }
    impl->hairTable.upload(hairs);
    impl->params.hairs = impl->hairTable.ptr;
    // Toon materials: their ramps, by the same number a hair or a fog would have had.
    std::vector<DeviceToon> toons;
    for (size_t i = 0; i < count; ++i) {
        const Material& m = materials[i];
        const size_t first = TOON_STEPS * 4 + 8 + 8, extra = TOON_STEPS + 8 + 5;
        if (m.hair || m.volume || !(m.toonDiffuse || m.toonSpecular) || m.toon.size() != first + m.toonMore * extra) continue;
        // A highlight's numbers: its ramp's input scale, intensity, Fresnel blend, tint, normalization, then what it is
        // (a surface's or a hair fibre's), its roughness, whether its Fresnel is glass's, and the roughness it dims
        // what is under it with, and its ramp's value past its end.
        auto highlight = [](DeviceToon& d, const float* ramp, const float* numbers, const float* kind) {
            std::copy(ramp, ramp + TOON_STEPS, d.specular);
            d.specularScale = std::max(numbers[1], 1e-4f);
            d.intensity = numbers[2];
            d.blend = std::clamp(numbers[3], 0.0f, 1.0f);
            std::copy(numbers + 4, numbers + 7, d.tint);
            d.level = numbers[7];
            d.model = kind[0] > 0.5f ? TOON_HAIR : TOON_SURFACE;
            // MoonRay's HairUtil: a roughness as the variance of the reflection along the fibre.
            const float r = std::clamp(kind[1], 0.01f, 0.999f);
            const float root = 0.726f * r + 0.812f * r * r + 3.7f * std::pow(r, 20.0f);
            d.variance = root * root;
            d.plain = kind[2] > 0.5f ? 1u : 0u;
            const float smooth = 1.0f - kind[3] * kind[3];
            d.underBlend = std::clamp(1.0f - smooth * smooth * smooth, 0.0f, 1.0f);
            d.specularBeyond = kind[4];
        };
        DeviceToon d{};
        std::copy(m.toon.begin(), m.toon.begin() + TOON_STEPS * 3, d.diffuse);
        const float* numbers = m.toon.data() + TOON_STEPS * 4;
        d.diffuseScale = std::max(numbers[0], 1e-4f);
        std::copy(numbers + 8, numbers + 11, d.diffuseBeyond);
        highlight(d, m.toon.data() + TOON_STEPS * 3, numbers, numbers + 11);
        d.more = m.toonMore;
        table[i].flags |= (m.toonDiffuse ? MATERIAL_TOON_DIFFUSE : 0) | (m.toonSpecular ? MATERIAL_TOON_SPECULAR : 0);
        table[i].hair = unsigned(toons.size());
        toons.push_back(d);
        // A hair toon's further highlights, straight after its first.
        for (unsigned k = 0; k < m.toonMore; ++k) {
            const float* block = m.toon.data() + first + k * extra;
            DeviceToon e{};
            highlight(e, block, block + TOON_STEPS, block + TOON_STEPS + 8);
            toons.push_back(e);
        }
    }
    impl->toonTable.upload(toons);
    impl->params.toons = impl->toonTable.ptr;
    std::vector<DeviceVolume> volumes;
    std::vector<int32_t> usedGrids;
    for (size_t i = 0; i < count; ++i) {
        if (!materials[i].volume) continue;
        DeviceVolume fog{};
        for (int c = 0; c < 3; ++c) {
            fog.extinction[c] = std::max(materials[i].volumeExtinction[c], 0.0f);
            fog.albedo[c] = std::clamp(materials[i].volumeAlbedo[c], 0.0f, 1.0f);
            fog.emission[c] = std::max(materials[i].volumeEmission[c], 0.0f);
        }
        fog.anisotropy = std::clamp(materials[i].volumeAnisotropy, -0.99f, 0.99f);
        if (materials[i].volumeGrid >= 0) {
            const int32_t grid = materials[i].volumeGrid;
            if (size_t(grid) >= impl->grids.size() || !impl->grids[grid] || impl->gridPeaks[grid] < 0.0f) throw std::runtime_error("MoonLightIPR volume refers to a missing grid");
            fog.grid = static_cast<unsigned long long>(impl->grids[grid]->object);
            fog.peak = impl->gridPeaks[grid];
            std::copy(materials[i].volumeRows, materials[i].volumeRows + 12, fog.rows);
            usedGrids.push_back(grid);
            if (materials[i].volumeGlowGrid >= 0) {
                const int32_t glow = materials[i].volumeGlowGrid;
                if (size_t(glow) >= impl->grids.size() || !impl->grids[glow] || impl->gridPeaks[glow] >= 0.0f) throw std::runtime_error("MoonLightIPR volume refers to a missing grid");
                fog.glow = static_cast<unsigned long long>(impl->grids[glow]->object);
                std::copy(materials[i].volumeGlowRows, materials[i].volumeGlowRows + 12, fog.glowRows);
                usedGrids.push_back(glow);
            }
        }
        table[i].flags = (table[i].flags & ~MATERIAL_HAIR) | MATERIAL_VOLUME;
        table[i].hair = unsigned(volumes.size());
        volumes.push_back(fog);
    }
    impl->volumeTable.upload(volumes);
    impl->volumeGrids = std::move(usedGrids);
    impl->params.volumes = impl->volumeTable.ptr;
    impl->params.volumeCount = unsigned(volumes.size());
    // Layers and textures are followed on the GPU without checks, so settle them here.
    for (const DeviceMaterial& material : table)
        if (size_t(material.layerStart) + material.layerCount > layerCount) throw std::runtime_error("MoonLightIPR material refers to missing layers");
    std::vector<DeviceLayer> layerTable(layerCount);
    std::vector<int32_t> used;
    const auto object = [&](int32_t texture) {
        if (texture < 0 || size_t(texture) >= impl->textures.size() || !impl->textures[texture])
            throw std::runtime_error("MoonLightIPR layer refers to a missing texture");
        used.push_back(texture);
        return static_cast<unsigned long long>(impl->textures[texture]->object);
    };
    // The tile list as the kernel reads it: texture objects in place of indices, 0 for none.
    std::vector<unsigned long long> tileTable(tileCount);
    for (size_t i = 0; i < tileCount;) {
        const size_t run = tiles[i] < 0 ? tileCount : size_t(tiles[i]);
        if (run >= tileCount - i) throw std::runtime_error("MoonLightIPR tile list is malformed");
        tileTable[i] = run;
        for (size_t t = 1; t <= run; ++t) tileTable[i + t] = tiles[i + t] < 0 ? 0 : object(tiles[i + t]);
        i += run + 1;
    }
    impl->tileTable.upload(tileTable);
    for (size_t i = 0; i < layerCount; ++i) {
        const Layer& layer = layers[i];
        DeviceLayer& out = layerTable[i];
        out.channel = layer.channel;
        out.blend = layer.blend;
        out.flags = layer.flags & ~(LAYER_IMAGE | LAYER_CURVES);
        out.uvSlot = layer.uvSlot;
        std::copy(layer.value, layer.value + 3, out.value);
        out.opacity = layer.opacity;
        out.gain = layer.gain;
        out.offset = layer.offset;
        std::copy(layer.scale, layer.scale + 2, out.scale);
        out.gamma = layer.gamma;
        out.bias = layer.bias;
        out.gainCurve = layer.gainCurve;
        std::copy(layer.color2, layer.color2 + 3, out.color2);
        out.alpha1 = layer.alpha1;
        out.alpha2 = layer.alpha2;
        out.octaves = layer.octaves;
        out.lacunarity = layer.lacunarity;
        out.persistence = layer.persistence;
        out.pattern = layer.pattern;
        std::copy(layer.settings, layer.settings + 8, out.settings);
        std::copy(layer.rows, layer.rows + 12, out.rows);
        if (layer.gamma != 1.0f || layer.bias != 0.5f || layer.gainCurve != 0.5f) out.flags |= LAYER_CURVES;
        // Coordinates and channels are followed on the GPU without checks.
        const unsigned sources = out.flags & (LAYER_RAMP | LAYER_CHECKER | LAYER_NOISE | LAYER_UDIM | LAYER_PROCEDURAL);
        if (sources & (sources - 1)) throw std::runtime_error("MoonLightIPR layer has more than one source");
        if (out.flags & LAYER_RAMP) {
            if (layer.uvSlot >= CHANNEL_COUNT) throw std::runtime_error("MoonLightIPR gradient layer refers to a missing channel");
            out.texture = object(layer.texture);
        } else if (out.flags & LAYER_UDIM) {
            if (layer.texture < 0 || size_t(layer.texture) >= tileCount || layer.uvSlot >= UV_SLOTS)
                throw std::runtime_error("MoonLightIPR layer refers to missing tiles or a missing coordinate slot");
            out.texture = impl->tileTable.ptr + size_t(layer.texture) * sizeof(unsigned long long);
        } else if (out.flags & (LAYER_CHECKER | LAYER_NOISE)) {
            if (layer.uvSlot >= UV_SLOTS) throw std::runtime_error("MoonLightIPR layer refers to a missing coordinate slot");
        } else if (layer.texture >= 0) {
            if (layer.uvSlot >= UV_SLOTS) throw std::runtime_error("MoonLightIPR layer refers to a missing coordinate slot");
            out.texture = object(layer.texture);
            out.flags |= LAYER_IMAGE;
        }
    }
    // A material can be partly absent through its own value or a layer on that channel; only then
    // do rays pay for the any-hit test.
    impl->params.presence = 0;
    for (DeviceMaterial& material : table) {
        for (unsigned i = 0; i < material.layerCount; ++i)
            if (layerTable[material.layerStart + i].channel == CHANNEL_DISSOLVE || layerTable[material.layerStart + i].channel == CHANNEL_STENCIL)
                material.flags |= MATERIAL_HAS_PRESENCE;
            else if (layerTable[material.layerStart + i].channel == CHANNEL_BUMP && material.bumpStrength != 0.0f) material.flags |= MATERIAL_HAS_BUMP;
        if (material.flags & (MATERIAL_HAS_PRESENCE | MATERIAL_VOLUME)) impl->params.presence = 1;
    }
    impl->layerTable.upload(layerTable);
    impl->params.layers = impl->layerTable.ptr;
    impl->layerTextures = std::move(used);
    impl->layerCount = layerCount;
    impl->materialTable.upload(table);
    impl->params.materials = impl->materialTable.ptr;
    impl->materialCount = count;
    impl->restart();
}

void Renderer::setMaterial(uint32_t index, const Material& material) {
    if (index >= impl->materialCount) throw std::runtime_error("MoonLightIPR material index is out of range");
    if (size_t(material.layerStart) + material.layerCount > impl->layerCount)
        throw std::runtime_error("MoonLightIPR material refers to missing layers");
    const DeviceMaterial value = toDevice(material);
    ML_CHECK(cudaMemcpy(reinterpret_cast<void*>(impl->materialTable.ptr + index * sizeof(DeviceMaterial)), &value,
        sizeof(value), cudaMemcpyHostToDevice));
    impl->restart();
}

void Renderer::setEnvironment(const Environment& environment) {
    // A constant colour still gets a small map, so one sampling path serves both cases.
    const bool mapped = environment.pixels != nullptr;
    const uint32_t width = mapped ? environment.width : 16, height = mapped ? environment.height : 8;
    if (!width || !height || width > 16384 || height > 16384) throw std::runtime_error("MoonLightIPR environment size is invalid");

    std::vector<float> pixels(size_t(width) * height * 4), marginal(height + 1), conditional(size_t(height) * (width + 1));
    for (uint32_t y = 0; y < height; ++y) {
        const float sinTheta = std::sin((y + 0.5f) / height * 3.14159265358979323846f);
        float* cdf = &conditional[size_t(y) * (width + 1)];
        cdf[0] = 0.0f;
        for (uint32_t x = 0; x < width; ++x) {
            float* out = &pixels[(size_t(y) * width + x) * 4];
            for (int c = 0; c < 3; ++c) {
                const float value = environment.color[c] * (mapped ? environment.pixels[(size_t(y) * width + x) * 3 + c] : 1.0f);
                out[c] = std::isfinite(value) ? std::max(value, 0.0f) : 0.0f;
            }
            out[3] = 1.0f;
            cdf[x + 1] = cdf[x] + (0.2126f * out[0] + 0.7152f * out[1] + 0.0722f * out[2]) * sinTheta;
        }
        marginal[y + 1] = marginal[y] + cdf[width];
        // A black row is never chosen, but keep its distribution well formed.
        for (uint32_t x = 1; x <= width; ++x) cdf[x] = cdf[width] > 0.0f ? cdf[x] / cdf[width] : float(x) / width;
        cdf[width] = 1.0f;
    }
    const float total = marginal[height];
    for (uint32_t y = 1; y <= height; ++y) marginal[y] = total > 0.0f ? marginal[y] / total : float(y) / height;
    marginal[height] = 1.0f;

    impl->envPixels.upload(pixels);
    if (mapped && environment.background) {
        for (size_t i = 0; i < size_t(width) * height; ++i)
            for (int c = 0; c < 3; ++c) {
                const float value = environment.color[c] * environment.background[i * 3 + c];
                pixels[i * 4 + c] = std::isfinite(value) ? std::max(value, 0.0f) : 0.0f;
            }
    }
    impl->envBackground.upload(pixels);
    impl->params.envBackground = impl->envBackground.ptr;
    impl->envMarginal.upload(marginal);
    impl->envConditional.upload(conditional);
    impl->params.envPixels = impl->envPixels.ptr;
    impl->params.envMarginal = impl->envMarginal.ptr;
    impl->params.envConditional = impl->envConditional.ptr;
    impl->params.envWidth = width;
    impl->params.envHeight = height;
    std::copy(environment.rotation, environment.rotation + 9, impl->params.envRotation);
    std::copy(environment.backgroundRotation, environment.backgroundRotation + 9, impl->params.envBackgroundRotation);
    for (float* rows : {impl->params.envRotation, impl->params.envBackgroundRotation})
        for (int row = 0; row < 3; ++row) scaleTo(rows + row * 3, 1.0f);
    impl->restart();
}

// Where a picture is bright, as the kernel draws points from it: its width and height, a running total over its
// rows, then one over each row's columns. Every part of the picture keeps a little chance, so that none of the
// light is lost; with round, only the circle inside the square counts, as for a disc.
static void appendDistribution(const Texture& texture, bool round, std::vector<float>& out) {
    const uint32_t width = texture.gridWidth, height = texture.gridHeight;
    std::vector<float> cells(texture.brightness);
    double total = 0.0;
    for (float value : cells) total += value;
    const float least = total > 0.0 ? float(0.05 * total / cells.size()) : 1.0f;
    for (uint32_t y = 0; y < height; ++y)
        for (uint32_t x = 0; x < width; ++x) {
            const float dx = (x + 0.5f) / width - 0.5f, dy = (y + 0.5f) / height - 0.5f;
            float& cell = cells[size_t(y) * width + x];
            // A cell the circle only touches still counts, since part of it is lit.
            const float margin = 0.75f / std::min(width, height);
            cell = round && std::sqrt(dx * dx + dy * dy) > 0.5f + margin ? 0.0f : cell + least;
        }
    out.push_back(float(width));
    out.push_back(float(height));
    const size_t rows = out.size();
    out.resize(out.size() + height + 1 + size_t(height) * (width + 1), 0.0f);
    for (uint32_t y = 0; y < height; ++y) {
        float* columns = &out[rows + height + 1 + size_t(y) * (width + 1)];
        for (uint32_t x = 0; x < width; ++x) columns[x + 1] = columns[x] + cells[size_t(y) * width + x];
        const float sum = columns[width];
        out[rows + y + 1] = out[rows + y] + sum;
        for (uint32_t x = 1; x <= width; ++x) columns[x] = sum > 0.0f ? columns[x] / sum : float(x) / width;
        columns[width] = 1.0f;
    }
    const float sum = out[rows + height];
    for (uint32_t y = 1; y <= height; ++y) out[rows + y] = sum > 0.0f ? out[rows + y] / sum : float(y) / height;
    out[rows + height] = 1.0f;
}

void Renderer::setDistantLights(const DistantLight* lights, size_t count) {
    std::vector<DeviceDistantLight> table(count);
    std::vector<int32_t> used;
    std::vector<float> distributions;
    std::vector<size_t> distributionStart(count, size_t(-1));
    for (size_t i = 0; i < count; ++i) {
        table[i] = DeviceDistantLight{};
        std::copy(lights[i].direction, lights[i].direction + 3, table[i].direction);
        scaleTo(table[i].direction, 1.0f);
        std::copy(lights[i].radiance, lights[i].radiance + 3, table[i].radiance);
        // 1 - cos(t) = 2 sin(t/2)^2 avoids cancellation for a small disc.
        const float radius = std::clamp(lights[i].angularExtentDegrees, 0.01f, 360.0f) * 3.14159265358979323846f / 360.0f;
        const float sinHalf = std::sin(0.5f * radius);
        table[i].versine = 2.0f * sinHalf * sinHalf;
        table[i].visible = lights[i].visibleInCamera ? 1.0f : 0.0f;
        std::copy(lights[i].seenRadiance, lights[i].seenRadiance + 3, table[i].seen);
        const float seenHalf = std::sin(0.5f * std::clamp(lights[i].seenExtentDegrees, 0.01f, 360.0f) * 3.14159265358979323846f / 360.0f);
        table[i].seenVersine = 2.0f * seenHalf * seenHalf;
        if (lights[i].texture >= 0) {
            if (size_t(lights[i].texture) >= impl->textures.size() || !impl->textures[lights[i].texture])
                throw std::runtime_error("MoonLightIPR light refers to a missing texture");
            used.push_back(lights[i].texture);
            table[i].texture = static_cast<unsigned long long>(impl->textures[lights[i].texture]->object);
            std::copy(lights[i].axisX, lights[i].axisX + 3, table[i].u);
            std::copy(lights[i].axisY, lights[i].axisY + 3, table[i].v);
            scaleTo(table[i].u, 1.0f);
            scaleTo(table[i].v, 1.0f);
            // MoonRay's DistantLight: half the square root of a half, over the sine of half the disc's radius.
            table[i].uvScale = 0.5f * std::sqrt(0.5f) / sinHalf;
            distributionStart[i] = distributions.size();
            appendDistribution(*impl->textures[lights[i].texture], true, distributions);
        }
    }
    impl->distantDistributions.upload(distributions);
    for (size_t i = 0; i < count; ++i)
        if (distributionStart[i] != size_t(-1)) table[i].distribution = impl->distantDistributions.ptr + distributionStart[i] * sizeof(float);
    impl->distantTextures = std::move(used);
    impl->distantLights.upload(table);
    impl->params.distantLights = impl->distantLights.ptr;
    impl->params.distantLightCount = unsigned(count);
    impl->distantOpen = table;
    impl->lightsMove = false;
    impl->restart();
}

void Renderer::setLights(const Light* lights, size_t count) {
    const float pi = 3.14159265358979323846f;
    std::vector<DeviceLight> table(count);
    std::vector<float> triangles;       // of every mesh light, 10 floats each
    std::vector<size_t> triangleStart(count, 0);
    std::vector<DeviceFilter> filters;
    std::vector<int32_t> usedGrids;
    std::vector<int32_t> used;
    std::vector<float> distributions;
    std::vector<size_t> distributionStart(count, size_t(-1));
    const auto object = [&](int32_t texture) {
        if (texture < 0 || size_t(texture) >= impl->textures.size() || !impl->textures[texture])
            throw std::runtime_error("MoonLightIPR light refers to a missing texture");
        used.push_back(texture);
        return static_cast<unsigned long long>(impl->textures[texture]->object);
    };
    impl->params.envPortal = 0;
    for (size_t i = 0; i < count; ++i) {
        const Light& light = lights[i];
        DeviceLight& out = table[i];
        out = DeviceLight{};
        out.type = light.kind;
        std::copy(light.radiance, light.radiance + 3, out.radiance);
        if (light.texture >= 0 && light.kind != Light::Portal && light.kind != Light::Mesh) out.texture = object(light.texture);
        // The flat lights and the cylinder are sampled where their picture is bright; a sphere's and a spot's evenly.
        if (out.texture && (light.kind == Light::Rect || light.kind == Light::Disk || light.kind == Light::Cylinder)) {
            distributionStart[i] = distributions.size();
            appendDistribution(*impl->textures[light.texture], light.kind == Light::Disk, distributions);
        }
        out.filterStart = unsigned(filters.size());
        out.filterCount = unsigned(light.filterCount);
        for (size_t f = 0; f < light.filterCount; ++f) {
            const LightFilter& in = light.filters[f];
            DeviceFilter filter = {};
            filter.type = in.kind;
            filter.flags = in.flags;
            std::copy(in.values, in.values + 4, filter.a);
            std::copy(in.rows, in.rows + 12, filter.rows);
            std::copy(in.more, in.more + 12, filter.b);
            if (in.kind == LightFilter::Cookie) filter.texture = object(in.texture);
            if (in.ramp >= 0 && (in.kind == LightFilter::Rod || in.kind == LightFilter::Vdb)) filter.ramp = object(in.ramp);
            if (in.kind == LightFilter::Vdb) {
                if (in.texture < 0 || size_t(in.texture) >= impl->grids.size() || !impl->grids[in.texture] || impl->gridPeaks[in.texture] < 0.0f)
                    throw std::runtime_error("MoonLightIPR light filter refers to a missing grid");
                filter.texture = static_cast<unsigned long long>(impl->grids[in.texture]->object);
                usedGrids.push_back(in.texture);
            }
            if (in.kind == LightFilter::Ramp) {
                if (!(in.values[1] > in.values[0])) throw std::runtime_error("MoonLightIPR ramp filter has no length");
                filter.texture = object(in.texture);
            }
            filters.push_back(filter);
        }
        if (light.kind == Light::Mesh) {
            // A corner, two edges and the running share of the area, which picks a triangle.
            if (!light.triangles || !light.triangleCount || light.triangleCount > 0xffffffffu)
                throw std::runtime_error("MoonLightIPR mesh light has no triangles");
            triangleStart[i] = triangles.size();
            double total = 0.0;
            for (size_t t = 0; t < light.triangleCount; ++t) {
                const float* p = light.triangles + t * 9;
                float e1[3], e2[3], n[3];
                subtract(p + 3, p, e1);
                subtract(p + 6, p, e2);
                cross(e1, e2, n);
                total += 0.5 * std::sqrt(double(n[0]) * n[0] + double(n[1]) * n[1] + double(n[2]) * n[2]);
                triangles.insert(triangles.end(), p, p + 3);
                triangles.insert(triangles.end(), e1, e1 + 3);
                triangles.insert(triangles.end(), e2, e2 + 3);
                triangles.push_back(float(total));
            }
            if (!(total > 0.0) || !std::isfinite(total)) throw std::runtime_error("MoonLightIPR mesh light has no area");
            for (size_t t = 0; t < light.triangleCount; ++t) triangles[triangleStart[i] + t * 10 + 9] /= float(total);
            triangles.back() = 1.0f;
            // A mesh light has no cone; the number says instead whether the camera sees the surface shining.
            out.pad = light.outerConeDegrees > 0.5f ? 1u : 0u;
            out.area = float(total);
            out.triangleCount = uint32_t(light.triangleCount);
            continue;
        }
        if (!(light.radius > 0.0f) || !(light.width > 0.0f) || !(light.height > 0.0f))
            throw std::runtime_error("MoonLightIPR light has no size");
        if (light.kind == Light::Cylinder) {
            // Its axis, and the two directions across it.
            out.radius = light.radius;
            out.halfHeight = 0.5f * light.height;
            std::copy(light.position, light.position + 3, out.position);
            std::copy(light.axisX, light.axisX + 3, out.u);
            std::copy(light.axisY, light.axisY + 3, out.v);
            std::copy(light.direction, light.direction + 3, out.normal);
            for (float* axis : {out.u, out.v, out.normal}) scaleTo(axis, 1.0f);
            out.area = 2.0f * pi * light.radius * light.height;
            continue;
        }
        if (light.kind == Light::Portal) impl->params.envPortal = 1;
        out.radius = light.radius;
        std::copy(light.position, light.position + 3, out.position);
        std::copy(light.axisX, light.axisX + 3, out.u);
        std::copy(light.axisY, light.axisY + 3, out.v);
        std::copy(light.direction, light.direction + 3, out.normal);
        const bool rect = light.kind == Light::Rect || light.kind == Light::Portal;
        scaleTo(out.u, rect ? 0.5f * light.width : 1.0f);
        scaleTo(out.v, rect ? 0.5f * light.height : 1.0f);
        scaleTo(out.normal, 1.0f);
        out.area = rect ? light.width * light.height : 3.14159265358979323846f * light.radius * light.radius;
        if (light.kind == Light::Spot) {
            // MoonRay's defaults: the falloff is measured on a focal plane far down the axis.
            const float outer = std::clamp(light.outerConeDegrees, 0.01f, 179.0f);
            const float inner = std::clamp(light.innerConeDegrees, 0.0f, outer);
            const float tanOuter = std::tan(outer * 3.14159265358979323846f / 360.0f);
            const float tanInner = std::tan(inner * 3.14159265358979323846f / 360.0f);
            out.focalDistance = 1.0e10f;
            const float focalRadius = tanOuter * out.focalDistance + light.radius;
            out.rcpFocalRadius = 1.0f / focalRadius;
            out.falloffGradient = focalRadius / std::max((tanOuter - tanInner) * out.focalDistance, 1.0e-10f);
        }
    }
    // Past a handful, a shadow ray to every light at every bounce costs more than the noise of
    // sampling one, chosen by how much light it puts out.
    float total = 0.0f;
    for (DeviceLight& light : table) {
        const float area = light.type == LIGHT_SPHERE ? 4.0f * 3.14159265358979323846f * light.radius * light.radius : light.area;
        light.pick = std::max(1e-6f, (0.2126f * light.radiance[0] + 0.7152f * light.radiance[1] + 0.0722f * light.radiance[2]) * area);
        total += light.pick;
    }
    float running = 0.0f;
    for (DeviceLight& light : table) {
        light.pick /= total;
        light.cumulative = running += light.pick;
    }
    if (!table.empty()) table.back().cumulative = 1.0f;
    impl->params.lightPick = count > 4;
    impl->lightDistributions.upload(distributions);
    for (size_t i = 0; i < count; ++i)
        if (distributionStart[i] != size_t(-1)) table[i].distribution = impl->lightDistributions.ptr + distributionStart[i] * sizeof(float);
    impl->lightTriangles.upload(triangles);
    for (size_t i = 0; i < count; ++i)
        if (table[i].type == LIGHT_MESH) table[i].triangles = impl->lightTriangles.ptr + triangleStart[i] * sizeof(float);
    impl->lights.upload(table);
    impl->params.lights = impl->lights.ptr;
    impl->params.lightCount = unsigned(count);
    impl->lightsOpen = table;
    impl->lightsMove = false;
    impl->lightCount = count;
    impl->lightFilters.upload(filters);
    impl->params.lightFilters = impl->lightFilters.ptr;
    impl->lightTextures = std::move(used);
    impl->lightGrids = std::move(usedGrids);
    impl->restart();
}

void Renderer::setLightMotion(const DistantLight* distantClose, size_t distantCount, const Light* close, size_t count) {
    impl->lightsMove = false;
    impl->distantClose = impl->distantOpen;
    impl->lightsClose = impl->lightsOpen;
    if (distantCount && distantCount != impl->distantOpen.size()) throw std::runtime_error("MoonLightIPR closing distant lights do not match the lights");
    if (count && count != impl->lightsOpen.size()) throw std::runtime_error("MoonLightIPR closing lights do not match the lights");
    const auto differ = [](const float* a, const float* b) { return a[0] != b[0] || a[1] != b[1] || a[2] != b[2]; };
    for (size_t i = 0; i < distantCount; ++i) {
        DeviceDistantLight& out = impl->distantClose[i];
        std::copy(distantClose[i].direction, distantClose[i].direction + 3, out.direction);
        scaleTo(out.direction, 1.0f);
        if (out.texture) {
            std::copy(distantClose[i].axisX, distantClose[i].axisX + 3, out.u);
            std::copy(distantClose[i].axisY, distantClose[i].axisY + 3, out.v);
            scaleTo(out.u, 1.0f);
            scaleTo(out.v, 1.0f);
        }
        if (differ(out.direction, impl->distantOpen[i].direction)) impl->lightsMove = true;
    }
    for (size_t i = 0; i < count; ++i) {
        const Light& light = close[i];
        DeviceLight& out = impl->lightsClose[i];
        if (out.type == LIGHT_MESH) continue;
        // As setLights places it: a rect's and a portal's axes are its half extents, the others' unit.
        const bool rect = light.kind == Light::Rect || light.kind == Light::Portal;
        std::copy(light.position, light.position + 3, out.position);
        std::copy(light.axisX, light.axisX + 3, out.u);
        std::copy(light.axisY, light.axisY + 3, out.v);
        std::copy(light.direction, light.direction + 3, out.normal);
        scaleTo(out.u, rect ? 0.5f * light.width : 1.0f);
        scaleTo(out.v, rect ? 0.5f * light.height : 1.0f);
        scaleTo(out.normal, 1.0f);
        const DeviceLight& open = impl->lightsOpen[i];
        if (differ(out.position, open.position) || differ(out.u, open.u) || differ(out.v, open.v) || differ(out.normal, open.normal))
            impl->lightsMove = true;
    }
    impl->restart();
}

void Renderer::setCameraMotion(const Camera* close) {
    impl->cameraMoves = close != nullptr;
    if (close) impl->cameraClose = *close;
    impl->updateCamera();
    impl->restart();
}

void Renderer::setWorkingSpace(const float* matrix) {
    impl->params.working = matrix != nullptr;
    if (matrix) std::copy(matrix, matrix + 9, impl->params.workingMatrix);
    impl->restart();
}

void Renderer::setCamera(const Camera& camera) {
    impl->camera = camera;
    impl->updateCamera();
    impl->restart();
}

void Renderer::resize(uint32_t width, uint32_t height) {
    if (!width || !height || width > 16384 || height > 16384) throw std::runtime_error("MoonLightIPR image size is invalid");
    const size_t bytes = size_t(width) * height * 4 * sizeof(float);
    for (Buffer* buffer : {&impl->beauty, &impl->albedo, &impl->normal, &impl->denoised, &impl->half}) buffer->reserve(bytes);
    impl->params.beauty = impl->beauty.ptr;
    impl->params.albedo = impl->albedo.ptr;
    impl->params.normal = impl->normal.ptr;
    impl->params.width = width;
    impl->params.height = height;
    // The denoiser is sized for one resolution; it is recreated on the next request.
    if (impl->denoiser) ML_CHECK(optixDenoiserDestroy(impl->denoiser));
    impl->denoiser = nullptr;
    impl->updateCamera();
    impl->restart();
}

void Renderer::setVolumeScattering(float attenuation, float contribution, float phaseAttenuation) {
    impl->params.volumeAttenuation = std::clamp(attenuation, 0.0f, 1.0f);
    impl->params.volumeContribution = std::clamp(contribution, 0.0f, 1.0f);
    impl->params.volumePhaseAttenuation = std::clamp(phaseAttenuation, 0.0f, 1.0f);
    impl->restart();
}

void Renderer::setSampleClamp(float value, uint32_t depth) {
    impl->params.sampleClamp = std::max(value, 0.0f);
    impl->params.sampleClampDepth = depth;
    impl->restart();
}

void Renderer::setMaxDepth(uint32_t bounces, uint32_t diffuseBounces, uint32_t glossyBounces, uint32_t volumeBounces, bool presenceShadows) {
    impl->params.opaqueShadows = presenceShadows ? 0 : 1;
    impl->params.maxVolumeDepth = volumeBounces;
    impl->params.maxDepth = bounces;
    impl->params.maxDiffuseDepth = diffuseBounces;
    impl->params.maxGlossyDepth = glossyBounces;
    impl->restart();
}

void Renderer::render() {
    impl->validate();
    if (impl->samples == 0) {
        // Stopping once clean, for a picture that is rendered (a draft's lines are as clean as they will be at once).
        const bool judged = impl->cleanBelow > 0.0f && impl->params.draft == 0;
        impl->params.half = judged ? impl->half.ptr : 0;
        impl->params.done = 0;
        impl->params.doneColumns = (impl->params.width + CLEAN_TILE - 1) / CLEAN_TILE;
        if (judged) {
            const size_t tiles = size_t(impl->params.doneColumns) * ((impl->params.height + CLEAN_TILE - 1) / CLEAN_TILE);
            impl->tileDone.assign(tiles, 0);
            impl->tilePassed.assign(tiles, 0);
            impl->done.upload(impl->tileDone);
            impl->params.done = impl->done.ptr;
            impl->nextCheck = 16;
        }
    }
    if (impl->cameraMoves || impl->instancesMove || impl->meshesMove || impl->lightsMove) {
        // One moment per sample: the bits of the sample index reversed, which spreads any number
        // of samples evenly over the shutter.
        uint32_t bits = impl->samples, reversed = 0;
        for (int i = 0; i < 16; ++i, bits >>= 1) reversed = (reversed << 1) | (bits & 1);
        impl->setTime((reversed + 0.5f) / 65536.0f);
    }
    impl->params.sample = impl->samples;
    if (impl->launched) ML_CHECK(cudaEventSynchronize(impl->launched));
    else ML_CHECK(cudaEventCreateWithFlags(&impl->launched, cudaEventBlockingSync | cudaEventDisableTiming));
    impl->paramsBuffer.upload(&impl->params, sizeof(LaunchParams));
    ML_CHECK(optixLaunch(impl->pipeline, nullptr, impl->paramsBuffer.ptr, sizeof(LaunchParams), &impl->sbt,
        impl->params.width, impl->params.height, 1));
    ML_CHECK(cudaEventRecord(impl->launched, nullptr));
    ++impl->samples;
    if (impl->params.done && impl->samples == impl->nextCheck) {
        impl->converge();
        // Often at first, when a simple picture may already be clean, then every 256 samples.
        impl->nextCheck = impl->nextCheck < 256 ? impl->nextCheck * 2 : impl->nextCheck + 256;
    }
}

void Renderer::setLightSets(const uint32_t* sets, uint32_t words, size_t count) {
    impl->lightSetTable.upload(sets, size_t(words) * count * sizeof(uint32_t));
    impl->params.lightSets = impl->lightSetTable.ptr;
    impl->params.lightSetWords = words;
    impl->restart();
}

void Renderer::displacementValues(uint32_t mesh, uint32_t material, const uint32_t* primitives, const float* barycentrics,
                                  size_t count, float* values) {
    if (!count) return;
    if (mesh >= impl->meshes.size() || !impl->meshes[mesh] || impl->meshes[mesh]->curves)
        throw std::runtime_error("MoonLightIPR displacement refers to a missing mesh");
    if (!impl->meshes[mesh]->ownsMaterials && material >= impl->materialCount)
        throw std::runtime_error("MoonLightIPR displacement refers to a missing material");
    std::vector<DeviceDisplacePoint> points(count);
    for (size_t i = 0; i < count; ++i) {
        if (primitives[i] >= impl->meshes[mesh]->triangleCount) throw std::runtime_error("MoonLightIPR displacement refers to a missing triangle");
        points[i] = {primitives[i], barycentrics[i * 2], barycentrics[i * 2 + 1], 0};
    }
    Buffer place, found, settings;
    place.upload(points);
    found.reserve(count * DISPLACE_SLOTS * 3 * sizeof(float));
    LaunchParams launch = impl->params;
    launch.displacePoints = place.ptr;
    launch.displaceHeights = found.ptr;
    launch.displaceMesh = mesh;
    launch.displaceMaterial = material;
    settings.upload(&launch, sizeof(launch));
    ML_CHECK(optixLaunch(impl->pipeline, nullptr, settings.ptr, sizeof(LaunchParams), &impl->displaceSbt, unsigned(count), 1, 1));
    ML_CHECK(cudaMemcpy(values, reinterpret_cast<void*>(found.ptr), count * DISPLACE_SLOTS * 3 * sizeof(float), cudaMemcpyDeviceToHost));
}

void Renderer::reshapeMesh(uint32_t index, const float* positions, const float* normals, const float* closePositions) {
    if (index >= impl->meshes.size() || !impl->meshes[index] || impl->meshes[index]->curves)
        throw std::runtime_error("MoonLightIPR reshape refers to a missing mesh");
    Mesh& mesh = *impl->meshes[index];
    ML_CHECK(cudaDeviceSynchronize());  // a queued launch may still read the mesh
    mesh.positions.upload(positions, mesh.vertexCount * 3 * sizeof(float));
    // A mesh that changes shape is blended between these for each moment of the shutter.
    if (closePositions) {
        mesh.open.assign(positions, positions + mesh.vertexCount * 3);
        mesh.close.assign(closePositions, closePositions + mesh.vertexCount * 3);
    } else {
        mesh.open.clear();
        mesh.close.clear();
    }
    if (normals) mesh.normals.upload(normals, mesh.vertexCount * 3 * sizeof(float));
    else mesh.normals.release();
    impl->buildMesh(mesh, mesh.vertexCount, mesh.triangleCount);
    impl->uploadMeshTable();
    impl->restart();
}

void Renderer::setConvergence(float noise) {
    impl->cleanBelow = std::max(noise, 0.0f);
}

bool Renderer::converged() const { return impl->clean; }

uint32_t Renderer::sampleCount() const { return impl->samples; }
uint32_t Renderer::width() const { return impl->params.width; }
uint32_t Renderer::height() const { return impl->params.height; }

void Renderer::readBeauty(float* rgb) {
    if (!impl->samples) throw std::runtime_error("MoonLightIPR has no samples to read");
    impl->download(impl->beauty, rgb);
}

void Renderer::readDenoised(float* rgb) {
    if (!impl->samples) throw std::runtime_error("MoonLightIPR has no samples to read");
    impl->denoise();
    impl->download(impl->denoised, rgb);
}

void Renderer::synchronize() { ML_CHECK(cudaDeviceSynchronize()); }

size_t Renderer::freeMemory() const {
    size_t free = 0, total = 0;
    ML_CHECK(cudaMemGetInfo(&free, &total));
    return free;
}

std::string Renderer::deviceName() const {
    int device = 0;
    cudaDeviceProp properties;
    ML_CHECK(cudaGetDevice(&device));
    ML_CHECK(cudaGetDeviceProperties(&properties, device));
    return properties.name;
}

}
