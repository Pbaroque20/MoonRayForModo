// Host side of MoonLightIPR: CUDA buffers, OptiX acceleration structures, pipeline and denoiser.
#include "moonlight/moonlight.h"
#include "device/shared.h"

#include <cuda_runtime.h>
#include <optix.h>
#include <optix_function_table_definition.h>
#include <optix_stack_size.h>
#include <optix_stubs.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <utility>
#include <vector>

namespace moonlight {
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
    Buffer positions, normals, indices, materialIds, uvs, accel;
    OptixTraversableHandle handle = 0;
    uint32_t triangleCount = 0;
    uint32_t uvSetCount = 0;
    int32_t uvSlots[UV_SLOTS] = {-1, -1, -1, -1, -1, -1, -1, -1};
    bool ownsMaterials = false;
    uint32_t maxMaterial = 0;
};

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
    d.flags = (m.thin ? MATERIAL_THIN : 0) | (m.clearcoatDims ? MATERIAL_COAT_DIMS : 0) | (m.dissolve > 0.0f ? MATERIAL_HAS_PRESENCE : 0)
            | (m.beckmann ? MATERIAL_BECKMANN : 0);
    d.layerStart = m.layerStart;
    d.layerCount = m.layerCount;
    return d;
}

}

struct Renderer::Impl {
    OptixDeviceContext context = nullptr;
    OptixModule module = nullptr;
    OptixProgramGroup groups[4] = {};
    OptixPipeline pipeline = nullptr;
    OptixShaderBindingTable sbt = {};
    Buffer raygenRecord, missRecords, hitRecord;

    std::vector<std::unique_ptr<Mesh>> meshes;
    std::vector<std::unique_ptr<Texture>> textures;
    std::vector<int32_t> layerTextures;     // the texture each current layer uses, or -1
    std::vector<Instance> instances;
    size_t materialCount = 0;
    Buffer meshTable, instanceTable, materialTable, layerTable, albedoTables, instanceInput, instanceAccel, accelTemp;
    Buffer envPixels, envBackground, envMarginal, envConditional, distantLights, lights;
    Buffer beauty, albedo, normal, denoised, paramsBuffer;

    OptixDenoiser denoiser = nullptr;
    OptixDenoiserSizes denoiserSizes = {};
    size_t denoiserScratchBytes = 0;
    Buffer denoiserState, denoiserScratch, denoiserIntensity;

    LaunchParams params = {};
    Camera camera;
    uint32_t samples = 0;
    bool validated = false;

    ~Impl() {
        if (denoiser) optixDenoiserDestroy(denoiser);
        if (pipeline) optixPipelineDestroy(pipeline);
        for (OptixProgramGroup group : groups) if (group) optixProgramGroupDestroy(group);
        if (module) optixModuleDestroy(module);
        if (context) optixDeviceContextDestroy(context);
    }

    void createPipeline(const std::string& ptxPath) {
        std::ifstream file(ptxPath, std::ios::binary);
        const std::string ptx((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        if (ptx.empty()) throw std::runtime_error("Cannot read MoonLightIPR device program: " + ptxPath);

        OptixModuleCompileOptions moduleOptions = {};
        moduleOptions.maxRegisterCount = OPTIX_COMPILE_DEFAULT_MAX_REGISTER_COUNT;
        OptixPipelineCompileOptions pipelineOptions = {};
        pipelineOptions.traversableGraphFlags = OPTIX_TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_LEVEL_INSTANCING;
        pipelineOptions.numPayloadValues = 2;
        pipelineOptions.numAttributeValues = 2;
        pipelineOptions.exceptionFlags = OPTIX_EXCEPTION_FLAG_NONE;
        pipelineOptions.pipelineLaunchParamsVariableName = "params";
        pipelineOptions.usesPrimitiveTypeFlags = OPTIX_PRIMITIVE_TYPE_FLAGS_TRIANGLE;

        char log[4096];
        size_t logSize = sizeof(log);
        const OptixResult compiled = optixModuleCreateFromPTX(context, &moduleOptions, &pipelineOptions,
            ptx.data(), ptx.size(), log, &logSize, &module);
        if (compiled != OPTIX_SUCCESS) throw std::runtime_error(std::string("MoonLightIPR device program rejected: ") + log);

        OptixProgramGroupDesc descriptions[4] = {};
        descriptions[0].kind = OPTIX_PROGRAM_GROUP_KIND_RAYGEN;
        descriptions[0].raygen.module = module;
        descriptions[0].raygen.entryFunctionName = "__raygen__moonlight";
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
        OptixProgramGroupOptions groupOptions = {};
        logSize = sizeof(log);
        ML_CHECK(optixProgramGroupCreate(context, descriptions, 4, &groupOptions, log, &logSize, groups));

        // Shading runs in the ray generation program, so traces never nest.
        OptixPipelineLinkOptions linkOptions = {};
        linkOptions.maxTraceDepth = 1;
        logSize = sizeof(log);
        ML_CHECK(optixPipelineCreate(context, &pipelineOptions, &linkOptions, groups, 4, log, &logSize, &pipeline));
        OptixStackSizes stackSizes = {};
        for (OptixProgramGroup group : groups) ML_CHECK(optixUtilAccumulateStackSizes(group, &stackSizes));
        unsigned fromTraversal = 0, fromState = 0, continuation = 0;
        ML_CHECK(optixUtilComputeStackSizes(&stackSizes, 1, 0, 0, &fromTraversal, &fromState, &continuation));
        ML_CHECK(optixPipelineSetStackSize(pipeline, fromTraversal, fromState, continuation, 2));

        // Geometry is found through the instance id, so one hit record serves every mesh.
        SbtRecord raygen, miss[2], hit;
        ML_CHECK(optixSbtRecordPackHeader(groups[0], &raygen));
        ML_CHECK(optixSbtRecordPackHeader(groups[1], &miss[0]));
        ML_CHECK(optixSbtRecordPackHeader(groups[2], &miss[1]));
        ML_CHECK(optixSbtRecordPackHeader(groups[3], &hit));
        raygenRecord.upload(&raygen, sizeof(raygen));
        missRecords.upload(miss, sizeof(miss));
        hitRecord.upload(&hit, sizeof(hit));
        sbt.raygenRecord = raygenRecord.ptr;
        sbt.missRecordBase = missRecords.ptr;
        sbt.missRecordStrideInBytes = sizeof(SbtRecord);
        sbt.missRecordCount = 2;
        sbt.hitgroupRecordBase = hitRecord.ptr;
        sbt.hitgroupRecordStrideInBytes = sizeof(SbtRecord);
        sbt.hitgroupRecordCount = 1;
    }

    void buildMesh(Mesh& mesh, size_t vertexCount, size_t triangleCount) {
        // Rays switch the any-hit test off themselves unless the scene has a partly absent material.
        const unsigned flags = OPTIX_GEOMETRY_FLAG_NONE;
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

        OptixAccelBuildOptions options = {};
        options.buildFlags = OPTIX_BUILD_FLAG_ALLOW_COMPACTION | OPTIX_BUILD_FLAG_PREFER_FAST_TRACE;
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
                // A slot may only name a set this mesh has; the kernel does not check.
                for (unsigned slot = 0; slot < UV_SLOTS; ++slot)
                    entry.uvSet[slot] = mesh->uvSlots[slot] >= 0 && uint32_t(mesh->uvSlots[slot]) < mesh->uvSetCount ? mesh->uvSlots[slot] : -1;
            }
            table.push_back(entry);
        }
        meshTable.upload(table);
        params.meshes = meshTable.ptr;
    }

    void buildInstances() {
        std::vector<OptixInstance> input(instances.size());
        std::vector<DeviceInstance> table(instances.size());
        for (size_t i = 0; i < instances.size(); ++i) {
            std::copy(instances[i].transform, instances[i].transform + 12, input[i].transform);
            input[i].instanceId = unsigned(i);
            input[i].sbtOffset = 0;
            input[i].visibilityMask = 255;
            input[i].flags = OPTIX_INSTANCE_FLAG_NONE;
            input[i].traversableHandle = meshes[instances[i].mesh]->handle;
            table[i] = {instances[i].mesh, instances[i].material};
        }
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
    }

    // Material indices are followed on the GPU without bounds checks, so reject bad ones here.
    void validate() {
        if (validated) return;
        if (!params.width || !params.height) throw std::runtime_error("MoonLightIPR has no image size; call resize first");
        for (const Instance& instance : instances) {
            const Mesh& mesh = *meshes[instance.mesh];
            const uint32_t highest = mesh.ownsMaterials ? mesh.maxMaterial : instance.material;
            if (highest >= materialCount) throw std::runtime_error("MoonLightIPR instance refers to a missing material");
        }
        validated = true;
    }

    void restart() {
        samples = 0;
        validated = false;
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

    void denoise() {
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
        layer.input = image(beauty);
        layer.output = image(denoised);
        OptixDenoiserParams denoiserParams = {};
        denoiserParams.denoiseAlpha = OPTIX_DENOISER_ALPHA_MODE_COPY;
        denoiserParams.hdrIntensity = denoiserIntensity.ptr;
        ML_CHECK(optixDenoiserComputeIntensity(denoiser, nullptr, &layer.input, denoiserIntensity.ptr,
            denoiserScratch.ptr, denoiserScratchBytes));
        ML_CHECK(optixDenoiserInvoke(denoiser, nullptr, &denoiserParams, denoiserState.ptr, denoiserSizes.stateSizeInBytes,
            &guides, &layer, 1, 0, 0, denoiserScratch.ptr, denoiserScratchBytes));
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
    impl->createPipeline(ptxPath);
    // MoonRay's defaults, including its sample_clamping_value.
    impl->params.maxDepth = 4;
    impl->params.maxDiffuseDepth = impl->params.maxGlossyDepth = 2;
    impl->params.sampleClamp = 10.0f;
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

uint32_t Renderer::addTexture(const TextureDesc& desc) {
    if (!desc.pixels || !desc.width || !desc.height || desc.width > 16384 || desc.height > 16384)
        throw std::runtime_error("MoonLightIPR texture has no pixels or is too large");
    auto texture = std::make_unique<Texture>();
    const cudaChannelFormatDesc format = desc.floatData ? cudaCreateChannelDesc(32, 32, 32, 32, cudaChannelFormatKindFloat)
                                                        : cudaCreateChannelDesc(8, 8, 8, 8, cudaChannelFormatKindUnsigned);
    const size_t rowBytes = size_t(desc.width) * (desc.floatData ? 16 : 4);
    ML_CHECK(cudaMallocArray(&texture->array, &format, desc.width, desc.height));
    ML_CHECK(cudaMemcpy2DToArray(texture->array, 0, 0, desc.pixels, rowBytes, rowBytes, desc.height, cudaMemcpyHostToDevice));
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
    auto slot = std::find(impl->textures.begin(), impl->textures.end(), nullptr);
    if (slot == impl->textures.end()) slot = impl->textures.emplace(slot);
    *slot = std::move(texture);
    return uint32_t(slot - impl->textures.begin());
}

void Renderer::removeTexture(uint32_t texture) {
    if (texture >= impl->textures.size() || !impl->textures[texture]) throw std::runtime_error("MoonLightIPR texture does not exist");
    if (std::find(impl->layerTextures.begin(), impl->layerTextures.end(), int32_t(texture)) != impl->layerTextures.end())
        throw std::runtime_error("MoonLightIPR texture is still used by a material");
    ML_CHECK(cudaDeviceSynchronize());  // a queued launch may still sample it
    impl->textures[texture].reset();
}

void Renderer::setMaterials(const Material* materials, size_t count, const Layer* layers, size_t layerCount) {
    std::vector<DeviceMaterial> table(count);
    std::transform(materials, materials + count, table.begin(), toDevice);
    // Layers and textures are followed on the GPU without checks, so settle them here.
    for (const DeviceMaterial& material : table)
        if (size_t(material.layerStart) + material.layerCount > layerCount) throw std::runtime_error("MoonLightIPR material refers to missing layers");
    std::vector<DeviceLayer> layerTable(layerCount);
    std::vector<int32_t> used(layerCount, -1);
    for (size_t i = 0; i < layerCount; ++i) {
        const Layer& layer = layers[i];
        DeviceLayer& out = layerTable[i];
        out.channel = layer.channel;
        out.blend = layer.blend;
        out.flags = layer.flags & ~LAYER_IMAGE;
        out.uvSlot = layer.uvSlot;
        std::copy(layer.value, layer.value + 3, out.value);
        out.opacity = layer.opacity;
        out.gain = layer.gain;
        out.offset = layer.offset;
        if (layer.texture >= 0) {
            if (size_t(layer.texture) >= impl->textures.size() || !impl->textures[layer.texture] || layer.uvSlot >= UV_SLOTS)
                throw std::runtime_error("MoonLightIPR layer refers to a missing texture or coordinate slot");
            out.texture = impl->textures[layer.texture]->object;
            out.flags |= LAYER_IMAGE;
            used[i] = layer.texture;
        }
    }
    // A material can be partly absent through its own value or a layer on that channel; only then
    // do rays pay for the any-hit test.
    impl->params.presence = 0;
    for (DeviceMaterial& material : table) {
        for (unsigned i = 0; i < material.layerCount; ++i)
            if (layerTable[material.layerStart + i].channel == CHANNEL_DISSOLVE) material.flags |= MATERIAL_HAS_PRESENCE;
            else if (layerTable[material.layerStart + i].channel == CHANNEL_BUMP && material.bumpStrength != 0.0f) material.flags |= MATERIAL_HAS_BUMP;
        if (material.flags & MATERIAL_HAS_PRESENCE) impl->params.presence = 1;
    }
    impl->layerTable.upload(layerTable);
    impl->params.layers = impl->layerTable.ptr;
    impl->layerTextures = std::move(used);
    impl->materialTable.upload(table);
    impl->params.materials = impl->materialTable.ptr;
    impl->materialCount = count;
    impl->restart();
}

void Renderer::setMaterial(uint32_t index, const Material& material) {
    if (index >= impl->materialCount) throw std::runtime_error("MoonLightIPR material index is out of range");
    if (size_t(material.layerStart) + material.layerCount > impl->layerTextures.size())
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

void Renderer::setDistantLights(const DistantLight* lights, size_t count) {
    std::vector<DeviceDistantLight> table(count);
    for (size_t i = 0; i < count; ++i) {
        std::copy(lights[i].direction, lights[i].direction + 3, table[i].direction);
        scaleTo(table[i].direction, 1.0f);
        std::copy(lights[i].radiance, lights[i].radiance + 3, table[i].radiance);
        // 1 - cos(t) = 2 sin(t/2)^2 avoids cancellation for a small disc.
        const float radius = std::clamp(lights[i].angularExtentDegrees, 0.01f, 360.0f) * 3.14159265358979323846f / 360.0f;
        const float sinHalf = std::sin(0.5f * radius);
        table[i].versine = 2.0f * sinHalf * sinHalf;
    }
    impl->distantLights.upload(table);
    impl->params.distantLights = impl->distantLights.ptr;
    impl->params.distantLightCount = unsigned(count);
    impl->restart();
}

void Renderer::setLights(const Light* lights, size_t count) {
    std::vector<DeviceLight> table(count);
    for (size_t i = 0; i < count; ++i) {
        const Light& light = lights[i];
        DeviceLight& out = table[i];
        if (!(light.radius > 0.0f) || !(light.width > 0.0f) || !(light.height > 0.0f))
            throw std::runtime_error("MoonLightIPR light has no size");
        out.type = light.kind;
        out.radius = light.radius;
        std::copy(light.position, light.position + 3, out.position);
        std::copy(light.radiance, light.radiance + 3, out.radiance);
        std::copy(light.axisX, light.axisX + 3, out.u);
        std::copy(light.axisY, light.axisY + 3, out.v);
        std::copy(light.direction, light.direction + 3, out.normal);
        const bool rect = light.kind == Light::Rect;
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
    impl->lights.upload(table);
    impl->params.lights = impl->lights.ptr;
    impl->params.lightCount = unsigned(count);
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
    for (Buffer* buffer : {&impl->beauty, &impl->albedo, &impl->normal, &impl->denoised}) buffer->reserve(bytes);
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

void Renderer::setMaxDepth(uint32_t bounces, uint32_t diffuseBounces, uint32_t glossyBounces) {
    impl->params.maxDepth = bounces;
    impl->params.maxDiffuseDepth = diffuseBounces;
    impl->params.maxGlossyDepth = glossyBounces;
    impl->restart();
}

void Renderer::render() {
    impl->validate();
    impl->params.sample = impl->samples;
    impl->paramsBuffer.upload(&impl->params, sizeof(LaunchParams));
    ML_CHECK(optixLaunch(impl->pipeline, nullptr, impl->paramsBuffer.ptr, sizeof(LaunchParams), &impl->sbt,
        impl->params.width, impl->params.height, 1));
    ++impl->samples;
}

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

std::string Renderer::deviceName() const {
    int device = 0;
    cudaDeviceProp properties;
    ML_CHECK(cudaGetDevice(&device));
    ML_CHECK(cudaGetDeviceProperties(&properties, device));
    return properties.name;
}

}
