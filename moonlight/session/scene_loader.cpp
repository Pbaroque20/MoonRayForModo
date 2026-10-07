#include "scene_loader.h"

#include <cmath>
#include <cstring>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>

namespace moonlight {
namespace {

// Layout flags; keep in step with moonlight_scene.py.
const uint32_t MESH_HAS_DATA = 1, MESH_HAS_NORMALS = 2, MESH_HAS_MATERIAL_IDS = 4, MESH_SMOOTH = 8, MESH_HAS_UVS = 16, MESH_MOVES = 32;
const uint32_t SCENE_DENOISE = 1, SCENE_WORKING_SPACE = 2, SCENE_MOTION = 4;
const uint32_t LAYER_UDIM = 1 << 19;    // as in src/device/shared.h
const uint32_t TEXTURE_FLOAT = 1, TEXTURE_SRGB = 2, TEXTURE_WRAP_U_SHIFT = 2, TEXTURE_WRAP_V_SHIFT = 4;
// Meshes unused for this many scenes are freed, so hiding and showing an item stays cheap.
const uint64_t MESH_RETENTION = 8;

class Reader {
public:
    explicit Reader(const std::string& path) {
        std::ifstream file(path, std::ios::binary);
        data.assign(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
        if (data.empty()) throw std::runtime_error("Cannot read MoonLightIPR scene: " + path);
    }
    template <class T> T value() {
        T result;
        std::memcpy(&result, bytes(sizeof(T)), sizeof(T));
        return result;
    }
    template <class T> std::vector<T> array(size_t count) {
        if (count > data.size() / sizeof(T)) throw std::runtime_error("MoonLightIPR scene is truncated");
        std::vector<T> result(count);
        if (count) std::memcpy(result.data(), bytes(count * sizeof(T)), count * sizeof(T));
        return result;
    }
    void floats(float* out, size_t count) { std::memcpy(out, bytes(count * sizeof(float)), count * sizeof(float)); }
    std::string text(size_t count) { return std::string(bytes(count), count); }
    size_t position() const { return offset; }
    // FNV-1a over a stretch already read, to tell whether a section changed.
    uint64_t hash(size_t from, size_t to) const {
        uint64_t value = 1469598103934665603ull;
        for (size_t i = from; i < to; ++i) value = (value ^ static_cast<unsigned char>(data[i])) * 1099511628211ull;
        return value;
    }
    bool finished() const { return offset == data.size(); }

private:
    const char* bytes(size_t count) {
        if (count > data.size() - offset) throw std::runtime_error("MoonLightIPR scene is truncated");
        offset += count;
        return data.data() + offset - count;
    }
    std::vector<char> data;
    size_t offset = 0;
};

// The packer converts every image to one of two simple files with the runtime's oiiotool:
// an uncompressed 32-bit Targa for ordinary images, or a PFM for high dynamic range ones.
// Gradients it writes itself, as "MLF1", a width and a height, then RGBA floats, top row first.
struct Image {
    uint32_t width = 0, height = 0;
    bool floatData = false;
    std::vector<unsigned char> bytes;   // RGBA, top row first
    std::vector<float> floats;
};

Image readImage(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    const std::vector<char> data((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    if (data.size() < 18) throw std::runtime_error("Cannot read MoonLightIPR texture: " + path);
    Image image;
    if (std::memcmp(data.data(), "MLF1", 4) == 0) {
        std::memcpy(&image.width, data.data() + 4, 4);
        std::memcpy(&image.height, data.data() + 8, 4);
        const size_t count = size_t(image.width) * image.height;
        if (!count || count > (data.size() - 12) / 16) throw std::runtime_error("Unsupported MoonLightIPR texture file: " + path);
        image.floatData = true;
        image.floats.resize(count * 4);
        std::memcpy(image.floats.data(), data.data() + 12, count * 16);
        return image;
    }
    if (data[0] == 'P' && data[1] == 'F') {
        // "PF", width and height, then a scale whose sign gives the byte order; rows run bottom up.
        size_t offset = 0;
        std::string fields[3];
        for (int line = 0, field = 0; field < 3 && offset < data.size(); ++offset) {
            const char c = data[offset];
            if (line == 0) { if (c == '\n') line = 1; continue; }
            if (c == ' ' || c == '\n' || c == '\r' || c == '\t') { if (!fields[field].empty()) ++field; }
            else fields[field] += c;
        }
        image.width = uint32_t(std::stoul(fields[0]));
        image.height = uint32_t(std::stoul(fields[1]));
        const size_t count = size_t(image.width) * image.height;
        if (std::stof(fields[2]) >= 0.0f || !count || count > (data.size() - offset) / 12)
            throw std::runtime_error("Unsupported MoonLightIPR texture file: " + path);
        image.floatData = true;
        image.floats.resize(count * 4);
        for (uint32_t y = 0; y < image.height; ++y) {
            const char* row = data.data() + offset + size_t(image.height - 1 - y) * image.width * 12;
            for (uint32_t x = 0; x < image.width; ++x) {
                float* out = &image.floats[(size_t(y) * image.width + x) * 4];
                std::memcpy(out, row + size_t(x) * 12, 12);
                out[3] = 1.0f;
            }
        }
        return image;
    }
    const auto byte = [&](size_t i) { return static_cast<unsigned char>(data[i]); };
    const uint32_t depth = byte(16), start = 18 + byte(0);
    image.width = byte(12) | (byte(13) << 8);
    image.height = byte(14) | (byte(15) << 8);
    const size_t count = size_t(image.width) * image.height, pixel = depth / 8;
    if (byte(1) != 0 || byte(2) != 2 || (depth != 24 && depth != 32) || !count || data.size() < start || count > (data.size() - start) / pixel)
        throw std::runtime_error("Unsupported MoonLightIPR texture file: " + path);
    const bool topFirst = (byte(17) & 0x20) != 0;
    image.bytes.resize(count * 4);
    for (uint32_t y = 0; y < image.height; ++y) {
        const size_t row = start + size_t(topFirst ? y : image.height - 1 - y) * image.width * pixel;
        for (uint32_t x = 0; x < image.width; ++x) {
            const size_t in = row + size_t(x) * pixel;
            unsigned char* out = &image.bytes[(size_t(y) * image.width + x) * 4];
            out[0] = byte(in + 2);      // stored blue, green, red
            out[1] = byte(in + 1);
            out[2] = byte(in);
            out[3] = depth == 32 ? byte(in + 3) : 255;
        }
    }
    return image;
}

// Area-weighted vertex normals, the same default MoonRay's smooth_normal produces.
std::vector<float> smoothNormals(const std::vector<float>& positions, const std::vector<uint32_t>& indices) {
    std::vector<float> normals(positions.size(), 0.0f);
    for (size_t t = 0; t + 2 < indices.size(); t += 3) {
        const float* p0 = &positions[indices[t] * 3];
        const float* p1 = &positions[indices[t + 1] * 3];
        const float* p2 = &positions[indices[t + 2] * 3];
        const float a[3] = {p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]}, b[3] = {p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]};
        const float n[3] = {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
        for (int corner = 0; corner < 3; ++corner)
            for (int axis = 0; axis < 3; ++axis) normals[indices[t + corner] * 3 + axis] += n[axis];
    }
    for (size_t v = 0; v + 2 < normals.size(); v += 3) {
        const float length = std::sqrt(normals[v] * normals[v] + normals[v + 1] * normals[v + 1] + normals[v + 2] * normals[v + 2]);
        // An unreferenced or degenerate vertex still needs a unit normal.
        if (length > 0.0f) for (int axis = 0; axis < 3; ++axis) normals[v + axis] /= length;
        else normals[v + 1] = 1.0f;
    }
    return normals;
}

}

SceneSettings SceneLoader::apply(const std::string& path) {
    Reader in(path);
    if (in.value<uint32_t>() != 0x37534c4d) throw std::runtime_error("Not a MoonLightIPR scene: " + path);   // "MLS7"
    ++generation;
    SceneSettings settings;
    settings.width = in.value<uint32_t>();
    settings.height = in.value<uint32_t>();
    const uint32_t maxDepth = in.value<uint32_t>(), maxDiffuseDepth = in.value<uint32_t>(), maxGlossyDepth = in.value<uint32_t>();
    settings.targetSamples = in.value<uint32_t>();
    const uint32_t sceneFlags = in.value<uint32_t>();
    settings.denoise = (sceneFlags & SCENE_DENOISE) != 0;
    float workingSpace[9];
    in.floats(workingSpace, 9);

    Camera camera;
    in.floats(camera.eye, 3);
    in.floats(camera.target, 3);
    in.floats(camera.up, 3);
    camera.verticalFovDegrees = in.value<float>();
    camera.lensRadius = in.value<float>();
    camera.focusDistance = in.value<float>();
    camera.blades = in.value<uint32_t>();
    camera.bladeAngle = in.value<float>();
    // With motion blur, the camera again as it is when the shutter closes.
    Camera cameraClose = camera;
    if (sceneFlags & SCENE_MOTION) {
        in.floats(cameraClose.eye, 3);
        in.floats(cameraClose.target, 3);
        in.floats(cameraClose.up, 3);
        cameraClose.verticalFovDegrees = in.value<float>();
    }

    // Read new images before the materials whose layers will refer to them.
    std::vector<uint32_t> textureIndices(in.value<uint32_t>());
    for (uint32_t& textureIndex : textureIndices) {
        const uint64_t key = in.value<uint64_t>();
        const uint32_t flags = in.value<uint32_t>();
        const std::string file = in.text(in.value<uint32_t>());
        auto cached = textures.find(key);
        if (cached == textures.end()) {
            const Image image = readImage(file);
            TextureDesc desc;
            desc.pixels = image.floatData ? static_cast<const void*>(image.floats.data()) : image.bytes.data();
            desc.width = image.width;
            desc.height = image.height;
            desc.floatData = image.floatData;
            desc.srgb = (flags & TEXTURE_SRGB) != 0;
            desc.wrapU = TextureDesc::Wrap((flags >> TEXTURE_WRAP_U_SHIFT) & 3);
            desc.wrapV = TextureDesc::Wrap((flags >> TEXTURE_WRAP_V_SHIFT) & 3);
            cached = textures.emplace(key, CachedMesh{renderer.addTexture(desc), 0}).first;
        }
        cached->second.lastUsed = generation;
        textureIndex = cached->second.index;
    }

    std::vector<Material> materials(in.value<uint32_t>());
    for (Material& material : materials) {
        in.floats(material.baseColor, 3);
        material.metallic = in.value<float>();
        material.roughness = in.value<float>();
        material.ior = in.value<float>();
        in.floats(material.emission, 3);
        material.baseColorAmount = in.value<float>();
        material.emissionAmount = in.value<float>();
        material.underRoughness = in.value<float>();
        material.transmission = in.value<float>();
        in.floats(material.transmissionColor, 3);
        material.transmissionRoughness = in.value<float>();
        material.transmissionIor = in.value<float>();
        material.clearcoat = in.value<float>();
        material.clearcoatRoughness = in.value<float>();
        material.dissolve = in.value<float>();
        material.bumpStrength = in.value<float>();
        material.anisotropy = in.value<float>();
        in.floats(material.tangent, 2);
        material.subsurface = in.value<float>();
        in.floats(material.subsurfaceColor, 3);
        material.subsurfaceRadius = in.value<float>();
        material.absorptionDistance = in.value<float>();
        material.abbe = in.value<float>();
        const uint32_t materialFlags = in.value<uint32_t>();
        material.thin = (materialFlags & 1) != 0;
        material.clearcoatDims = (materialFlags & 2) != 0;
        material.beckmann = (materialFlags & 16) != 0;
        material.layerStart = in.value<uint32_t>();
        material.layerCount = in.value<uint32_t>();
        material.tangentSlot = in.value<uint32_t>();
    }
    std::vector<Layer> layers(in.value<uint32_t>());
    for (Layer& layer : layers) {
        layer.channel = in.value<uint32_t>();
        layer.blend = in.value<uint32_t>();
        layer.flags = in.value<uint32_t>();
        const int32_t texture = in.value<int32_t>();
        // A UDIM row names its run in the tile list instead of one image.
        if (layer.flags & LAYER_UDIM) layer.texture = texture;
        else if (texture >= int32_t(textureIndices.size())) throw std::runtime_error("MoonLightIPR scene layer refers to a missing texture");
        else layer.texture = texture < 0 ? -1 : int32_t(textureIndices[texture]);
        layer.uvSlot = in.value<uint32_t>();
        in.floats(layer.value, 3);
        layer.opacity = in.value<float>();
        layer.gain = in.value<float>();
        layer.offset = in.value<float>();
        in.floats(layer.scale, 2);
        layer.gamma = in.value<float>();
        layer.bias = in.value<float>();
        layer.gainCurve = in.value<float>();
        in.floats(layer.color2, 3);
        layer.alpha1 = in.value<float>();
        layer.alpha2 = in.value<float>();
        layer.octaves = in.value<float>();
        layer.lacunarity = in.value<float>();
        layer.persistence = in.value<float>();
    }
    // Runs of a count and that many images, one per UDIM tile from 1001 on; -1 where one is missing.
    std::vector<int32_t> tiles = in.array<int32_t>(in.value<uint32_t>());
    for (size_t i = 0; i < tiles.size();) {
        const size_t run = tiles[i] < 0 ? tiles.size() : size_t(tiles[i]);
        if (run >= tiles.size() - i) throw std::runtime_error("MoonLightIPR scene tile list is malformed");
        for (size_t t = 1; t <= run; ++t) {
            int32_t& tile = tiles[i + t];
            if (tile >= int32_t(textureIndices.size())) throw std::runtime_error("MoonLightIPR scene tile refers to a missing texture");
            tile = tile < 0 ? -1 : int32_t(textureIndices[tile]);
        }
        i += run + 1;
    }

    // The environment: a column of rows from zenith to nadir for what lights the scene and one
    // for what the camera sees, each optionally with a latitude-longitude image added.
    struct EnvironmentPart {
        std::vector<float> rows;
        bool hasImage = false;
        uint64_t key = 0;
        std::string file;
        float scale = 1.0f;
        float rotation[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    } parts[2];
    const size_t environmentStart = in.position();
    const uint32_t rowCount = in.value<uint32_t>();
    if (!rowCount || rowCount > 4096) throw std::runtime_error("MoonLightIPR scene environment is invalid");
    for (EnvironmentPart& part : parts) part.rows = in.array<float>(size_t(rowCount) * 3);
    for (EnvironmentPart& part : parts) {
        part.hasImage = in.value<uint32_t>() != 0;
        if (!part.hasImage) continue;
        part.key = in.value<uint64_t>();
        part.file = in.text(in.value<uint32_t>());
        part.scale = in.value<float>();
        in.floats(part.rotation, 9);
    }
    const uint64_t environmentNow = in.hash(environmentStart, in.position());

    std::vector<DistantLight> lights(in.value<uint32_t>());
    for (DistantLight& light : lights) {
        in.floats(light.direction, 3);
        in.floats(light.radiance, 3);
        light.angularExtentDegrees = in.value<float>();
    }

    std::vector<Light> localLights(in.value<uint32_t>());
    std::vector<std::vector<float>> lightTriangles(localLights.size());
    for (size_t l = 0; l < localLights.size(); ++l) {
        Light& light = localLights[l];
        const uint32_t kind = in.value<uint32_t>();
        if (kind > Light::Mesh) throw std::runtime_error("MoonLightIPR scene has an unknown light kind");
        light.kind = Light::Kind(kind);
        in.floats(light.position, 3);
        in.floats(light.axisX, 3);
        in.floats(light.axisY, 3);
        in.floats(light.direction, 3);
        light.width = in.value<float>();
        light.height = in.value<float>();
        light.radius = in.value<float>();
        in.floats(light.radiance, 3);
        light.outerConeDegrees = in.value<float>();
        light.innerConeDegrees = in.value<float>();
        if (light.kind == Light::Mesh) {
            lightTriangles[l] = in.array<float>(size_t(in.value<uint32_t>()) * 9);
            light.triangles = lightTriangles[l].data();
            light.triangleCount = lightTriangles[l].size() / 9;
        }
    }

    // Load new meshes before replacing the instances that will refer to them.
    std::vector<uint32_t> meshIndices(in.value<uint32_t>());
    std::vector<std::vector<int32_t>> meshSlots(meshIndices.size());
    for (size_t m = 0; m < meshIndices.size(); ++m) {
        uint32_t& meshIndex = meshIndices[m];
        const uint64_t key = in.value<uint64_t>();
        const uint32_t flags = in.value<uint32_t>();
        meshSlots[m] = in.array<int32_t>(UV_SLOT_COUNT);
        auto cached = meshes.find(key);
        if (flags & MESH_HAS_DATA) {
            const uint32_t vertexCount = in.value<uint32_t>(), triangleCount = in.value<uint32_t>();
            const std::vector<float> positions = in.array<float>(size_t(vertexCount) * 3);
            std::vector<float> normals = in.array<float>(flags & MESH_HAS_NORMALS ? size_t(vertexCount) * 3 : 0);
            const std::vector<uint32_t> indices = in.array<uint32_t>(size_t(triangleCount) * 3);
            const std::vector<uint32_t> materialIds = in.array<uint32_t>(flags & MESH_HAS_MATERIAL_IDS ? triangleCount : 0);
            std::vector<std::vector<float>> uvSets(flags & MESH_HAS_UVS ? in.value<uint32_t>() : 0);
            if (uvSets.size() > UV_SLOT_COUNT) throw std::runtime_error("MoonLightIPR scene mesh has too many coordinate sets");
            for (std::vector<float>& set : uvSets) set = in.array<float>(size_t(triangleCount) * 6);
            const std::vector<float> closePositions = in.array<float>(flags & MESH_MOVES ? size_t(vertexCount) * 3 : 0);
            if (cached == meshes.end()) {
                std::vector<const float*> uvPointers;
                for (const std::vector<float>& set : uvSets) uvPointers.push_back(set.data());
                for (uint32_t index : indices)
                    if (index >= vertexCount) throw std::runtime_error("MoonLightIPR scene mesh index is out of range");
                if (normals.empty() && (flags & MESH_SMOOTH)) normals = smoothNormals(positions, indices);
                MeshDesc desc;
                desc.positions = positions.data();
                desc.normals = normals.empty() ? nullptr : normals.data();
                desc.vertexCount = vertexCount;
                desc.indices = indices.data();
                desc.materialIds = materialIds.empty() ? nullptr : materialIds.data();
                desc.triangleCount = triangleCount;
                desc.uvSets = uvPointers.data();
                desc.uvSetCount = uvPointers.size();
                desc.closePositions = closePositions.empty() ? nullptr : closePositions.data();
                cached = meshes.emplace(key, CachedMesh{renderer.addMesh(desc), 0}).first;
            }
        }
        if (cached == meshes.end()) throw std::runtime_error("MoonLightIPR scene omits a mesh this session has not loaded");
        cached->second.lastUsed = generation;
        meshIndex = cached->second.index;
    }

    std::vector<Instance> instances(in.value<uint32_t>());
    for (Instance& instance : instances) {
        const uint32_t mesh = in.value<uint32_t>();
        if (mesh >= meshIndices.size()) throw std::runtime_error("MoonLightIPR scene instance refers to a missing mesh");
        instance.mesh = meshIndices[mesh];
        instance.material = in.value<uint32_t>();
        instance.light = in.value<int32_t>();
        if (instance.light >= int32_t(localLights.size())) throw std::runtime_error("MoonLightIPR scene instance refers to a missing light");
        in.floats(instance.transform, 12);
        if (sceneFlags & SCENE_MOTION) {
            in.floats(instance.closeTransform, 12);
            instance.moves = !std::equal(instance.transform, instance.transform + 12, instance.closeTransform);
        }
    }
    if (!in.finished()) throw std::runtime_error("MoonLightIPR scene has trailing data");

    renderer.setMaterials(materials.data(), materials.size(), layers.data(), layers.size(), tiles.data(), tiles.size());
    renderer.setWorkingSpace(sceneFlags & SCENE_WORKING_SPACE ? workingSpace : nullptr);
    for (auto entry = textures.begin(); entry != textures.end();) {
        if (generation - entry->second.lastUsed >= MESH_RETENTION) {
            renderer.removeTexture(entry->second.index);
            entry = textures.erase(entry);
        } else ++entry;
    }
    for (size_t m = 0; m < meshIndices.size(); ++m) renderer.setMeshUvSlots(meshIndices[m], meshSlots[m].data());
    // Lights before the instances that may be the surface of one.
    renderer.setDistantLights(lights.data(), lights.size());
    renderer.setLights(localLights.data(), localLights.size());
    renderer.setInstances(instances.data(), instances.size());
    for (auto entry = meshes.begin(); entry != meshes.end();) {
        if (generation - entry->second.lastUsed >= MESH_RETENTION) {
            renderer.removeMesh(entry->second.index);
            entry = meshes.erase(entry);
        } else ++entry;
    }
    if (environmentNow != environmentHash) {
        const EnvironmentPart* pictured = nullptr;
        for (int p = 0; p < 2; ++p) {
            if (!parts[p].hasImage) continue;
            if (parts[p].key != environmentImageKey[p]) {
                const Image image = readImage(parts[p].file);
                if (!image.floatData || image.width < 2) throw std::runtime_error("MoonLightIPR environment image is not a float image");
                environmentImage[p].resize(size_t(image.width) * image.height * 3);
                // MoonRay puts the middle of the image behind the map's forward axis, so turn it half way round.
                for (uint32_t y = 0; y < image.height; ++y)
                    for (uint32_t x = 0; x < image.width; ++x) {
                        const float* from = &image.floats[(size_t(y) * image.width + (x + image.width / 2) % image.width) * 4];
                        std::memcpy(&environmentImage[p][(size_t(y) * image.width + x) * 3], from, 3 * sizeof(float));
                    }
                environmentImageWidth[p] = image.width;
                environmentImageHeight[p] = image.height;
                environmentImageKey[p] = parts[p].key;
            }
            // The packer makes every environment image the same size.
            if (pictured && (environmentImageWidth[0] != environmentImageWidth[1] || environmentImageHeight[0] != environmentImageHeight[1]))
                throw std::runtime_error("MoonLightIPR scene uses environment images of different sizes");
            pictured = &parts[p];
        }
        const int sized = parts[0].hasImage ? 0 : 1;
        Environment environment;
        environment.width = pictured ? environmentImageWidth[sized] : 1;
        environment.height = pictured ? environmentImageHeight[sized] : rowCount;
        std::vector<float> pixels[2];
        for (int p = 0; p < 2; ++p) {
            pixels[p].resize(size_t(environment.width) * environment.height * 3);
            for (uint32_t y = 0; y < environment.height; ++y) {
                const float* row = &parts[p].rows[size_t(std::min<uint64_t>(uint64_t(y) * rowCount / environment.height, rowCount - 1)) * 3];
                for (uint32_t x = 0; x < environment.width; ++x) {
                    const size_t i = (size_t(y) * environment.width + x) * 3;
                    for (int c = 0; c < 3; ++c)
                        pixels[p][i + c] = row[c] + (parts[p].hasImage ? environmentImage[p][i + c] * parts[p].scale : 0.0f);
                }
            }
        }
        environment.pixels = pixels[0].data();
        environment.background = pixels[1].data();
        std::copy(parts[0].rotation, parts[0].rotation + 9, environment.rotation);
        std::copy(parts[1].rotation, parts[1].rotation + 9, environment.backgroundRotation);
        renderer.setEnvironment(environment);
        environmentHash = environmentNow;
    }
    renderer.setMaxDepth(maxDepth, maxDiffuseDepth, maxGlossyDepth);
    if (settings.width != renderer.width() || settings.height != renderer.height()) renderer.resize(settings.width, settings.height);
    renderer.setCamera(camera);
    renderer.setCameraMotion(sceneFlags & SCENE_MOTION ? &cameraClose : nullptr);
    return settings;
}

}
