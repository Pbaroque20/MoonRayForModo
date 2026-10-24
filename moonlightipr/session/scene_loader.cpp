// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
#include "scene_loader.h"
#include "subdivide.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <cstring>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>

namespace moonlightipr {
namespace {

// Layout flags; keep in step with moonlightipr_scene.py.
const uint32_t MESH_HAS_DATA = 1, MESH_HAS_NORMALS = 2, MESH_HAS_MATERIAL_IDS = 4, MESH_SMOOTH = 8, MESH_HAS_UVS = 16, MESH_MOVES = 32,
               MESH_SUBDIVIDE = 64,     // the data is a control cage to be subdivided here
               MESH_CURVES = 128,       // the data is curves: control points, their radii and each segment's first point
               MESH_LINEAR = 256,       // those curves' segments are straight, from one point to the next
               MESH_RIBBON = 512,       // and they are lit as flat ribbons that face the ray
               MESH_DISPLACE = 1024;    // its materials displace it: split finer here, then moved by their height
const uint32_t SCENE_DENOISE = 1, SCENE_WORKING_SPACE = 2, SCENE_MOTION = 4, SCENE_PRESENCE_SHADOWS = 8;
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

// A texture file's size without reading its pixels: (width, height, whether it holds floats). Zero where it is not one
// of the packer's files.
struct ImageSize {
    uint32_t width = 0, height = 0;
    bool floatData = false;
};

ImageSize imageSize(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    char head[64] = {};
    file.read(head, sizeof(head));
    const size_t got = size_t(file.gcount());
    ImageSize size;
    if (got >= 12 && std::memcmp(head, "MLF1", 4) == 0) {
        std::memcpy(&size.width, head + 4, 4);
        std::memcpy(&size.height, head + 8, 4);
        size.floatData = true;
    } else if (got >= 2 && head[0] == 'P' && head[1] == 'F') {
        std::istringstream fields(std::string(head + 2, got - 2));
        fields >> size.width >> size.height;
        size.floatData = true;
    } else if (got >= 18) {
        const auto byte = [&](size_t i) { return static_cast<unsigned char>(head[i]); };
        size.width = byte(12) | (byte(13) << 8);
        size.height = byte(14) | (byte(15) << 8);
    }
    return size;
}

// The bytes a texture takes on the card, given the most texels it may have across a side (0 for no limit): halves for
// floats, bytes for the rest, four to a texel.
size_t cardBytes(const ImageSize& size, uint32_t limit) {
    uint32_t width = size.width, height = size.height;
    while (limit && std::max(width, height) > limit) { width = std::max(1u, width / 2); height = std::max(1u, height / 2); }
    return size_t(width) * height * (size.floatData ? 8 : 4);
}

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
// One step of a material's displacement, as the packer gives it (moonlightipr_materials.displacement_tree): run at each
// vertex on a stack of vectors.
struct DisplacementStep {
    uint32_t code = 0;      // 0 a Normal displacement, 1 a Vector one, 2 two joined, 3 nothing
    float a = 0.0f, b = 0.0f;
    uint32_t c = 0;
};
const uint32_t DISPLACE_NORMAL = 0, DISPLACE_VECTOR = 1, DISPLACE_COMBINE = 2, DISPLACE_SLOTS_READ = 4;

// A mesh to be displaced once the materials are set: its vertices as split, its smooth normals, its triangles and their
// materials and first texture coordinates, and the displacement of each material that displaces it.
struct Displacing {
    uint32_t mesh = 0;
    // As the shutter opens, and its normals; and as it closes, for a mesh that changes shape, or empty.
    std::vector<float> positions, directions, closing, closingDirections;
    std::vector<uint32_t> indices, materialIds;
    std::vector<float> uvs;     // the first set, 6 per triangle, for the tangents a Vector displacement turns by
    uint32_t material = 0;
    std::vector<std::pair<uint32_t, std::vector<DisplacementStep>>> programs;
    bool smooth = false;
};

// Each vertex's tangent: which way texture u runs on the surface (MoonRay's dPds), from the triangles about it.
std::vector<float> tangentsOf(const std::vector<float>& positions, const std::vector<uint32_t>& indices, const std::vector<float>& uvs) {
    std::vector<float> tangents(positions.size(), 0.0f);
    if (uvs.size() != indices.size() * 2) return tangents;
    for (size_t t = 0; t < indices.size() / 3; ++t) {
        const uint32_t a = indices[t * 3], b = indices[t * 3 + 1], c = indices[t * 3 + 2];
        float e1[3], e2[3];
        for (int axis = 0; axis < 3; ++axis) {
            e1[axis] = positions[b * 3 + axis] - positions[a * 3 + axis];
            e2[axis] = positions[c * 3 + axis] - positions[a * 3 + axis];
        }
        const float* uv = &uvs[t * 6];
        const float du1 = uv[2] - uv[0], dv1 = uv[3] - uv[1], du2 = uv[4] - uv[0], dv2 = uv[5] - uv[1];
        const float det = du1 * dv2 - du2 * dv1;
        if (std::fabs(det) < 1e-12f) continue;
        for (int axis = 0; axis < 3; ++axis) {
            const float along = (e1[axis] * dv2 - e2[axis] * dv1) / det;
            for (uint32_t v : {a, b, c}) tangents[v * 3 + axis] += along;
        }
    }
    return tangents;
}

// Where a vertex goes, by its material's program: MoonRay's displacement nodes, each a vector at the vertex.
void displaced(float* position, const float* normal, const float* tangent, const float* values, const std::vector<DisplacementStep>& program) {
    std::vector<std::array<float, 3>> stack;
    for (const DisplacementStep& step : program) {
        std::array<float, 3> made = {0.0f, 0.0f, 0.0f};
        const uint32_t slot = std::min(step.c & 255u, DISPLACE_SLOTS_READ - 1);
        const float* value = values + slot * 3;
        if (step.code == DISPLACE_NORMAL) {
            // MoonRay's NormalDisplacement: the height above its zero value, by its multiplier, along the normal.
            const float height = ((value[0] + value[1] + value[2]) / 3.0f - step.a) * step.b;
            for (int axis = 0; axis < 3; ++axis) made[axis] = normal[axis] * height;
        } else if (step.code == DISPLACE_VECTOR) {
            const float v[3] = {value[0] * step.a, value[1] * step.a, value[2] * step.a};
            if (step.c & 256u) {
                // In object space, as the mesh's own vertices are.
                made = {v[0], v[1], v[2]};
            } else {
                // In tangent space: MoonRay's frame of the normal (z) and texture u's way along it (x), y their cross;
                // its TNB style has green up, so the vector's y and z change places.
                const float* n = normal;
                float y[3] = {n[1] * tangent[2] - n[2] * tangent[1], n[2] * tangent[0] - n[0] * tangent[2], n[0] * tangent[1] - n[1] * tangent[0]};
                const float length = std::sqrt(y[0] * y[0] + y[1] * y[1] + y[2] * y[2]);
                if (length > 1e-12f) {
                    for (float& component : y) component /= length;
                } else {
                    // No texture u here: any way across the normal.
                    const float other[3] = {std::fabs(n[0]) < 0.9f ? 1.0f : 0.0f, std::fabs(n[0]) < 0.9f ? 0.0f : 1.0f, 0.0f};
                    y[0] = n[1] * other[2] - n[2] * other[1]; y[1] = n[2] * other[0] - n[0] * other[2]; y[2] = n[0] * other[1] - n[1] * other[0];
                    const float again = std::sqrt(y[0] * y[0] + y[1] * y[1] + y[2] * y[2]);
                    for (float& component : y) component /= std::max(again, 1e-12f);
                }
                const float x[3] = {y[1] * n[2] - y[2] * n[1], y[2] * n[0] - y[0] * n[2], y[0] * n[1] - y[1] * n[0]};
                const bool tnb = !(step.c & 512u);
                const float l[3] = {v[0], tnb ? v[2] : v[1], tnb ? v[1] : v[2]};
                for (int axis = 0; axis < 3; ++axis) made[axis] = x[axis] * l[0] + y[axis] * l[1] + n[axis] * l[2];
            }
        } else if (step.code == DISPLACE_COMBINE && stack.size() >= 2) {
            std::array<float, 3> second = stack.back();
            stack.pop_back();
            std::array<float, 3> first = stack.back();
            stack.pop_back();
            for (int axis = 0; axis < 3; ++axis) {
                first[axis] *= step.a;
                second[axis] *= step.b;
            }
            const float one = first[0] * first[0] + first[1] * first[1] + first[2] * first[2];
            const float two = second[0] * second[0] + second[1] * second[1] + second[2] * second[2];
            if (step.c == 1) made = one > two ? first : second;
            else if (step.c == 2) made = one < two ? first : second;
            else for (int axis = 0; axis < 3; ++axis) made[axis] = first[axis] + second[axis];
        }
        stack.push_back(made);
    }
    if (stack.empty()) return;
    for (int axis = 0; axis < 3; ++axis)
        if (std::isfinite(stack.back()[axis])) position[axis] += stack.back()[axis];
}

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
    // "MLS" and a letter for the form of the scene, which changes whenever what is written in it does: "C" since
    // the scene's sample clamp is written in it, "D" since a toon material's ramps are, "E" since a hair toon's highlights are,
    // "F" since the lights' poses at the shutter's close are, "G" since the volume scattering factors are, "H" since the
    // camera's film offset is, "I" since a material's fuzz is, "J" since the light sets are, "K" since a mesh may be displaced, "L" since by a program of displacement nodes, "M" since a material's clearcoat bump strength is. A plugin and a session of different versions say so plainly, in
    // place of reading each other's scenes wrongly.
    const uint32_t mark = in.value<uint32_t>();
    if ((mark & 0x00ffffff) != 0x00534c4d) throw std::runtime_error("Not a MoonLightIPR scene: " + path);
    if (mark != 0x4d534c4d)
        throw std::runtime_error("This MoonLightIPR and the plugin are of different versions (the scene is form '" + std::string(1, char(mark >> 24))
                                 + "', this MoonLightIPR reads 'M'). Install the kit and its runtime from the same release.");
    ++generation;
    SceneSettings settings;
    settings.width = in.value<uint32_t>();
    settings.height = in.value<uint32_t>();
    const uint32_t maxDepth = in.value<uint32_t>(), maxDiffuseDepth = in.value<uint32_t>(), maxGlossyDepth = in.value<uint32_t>();
    const uint32_t maxVolumeDepth = in.value<uint32_t>();
    settings.targetSamples = in.value<uint32_t>();
    const uint32_t sceneFlags = in.value<uint32_t>();
    settings.denoise = (sceneFlags & SCENE_DENOISE) != 0;
    // The render rests once the picture is clean: noise of about a step of an 8-bit screen's colour, or three where
    // the denoiser takes away what is left, rather than gathering every sample of a scene that needs few.
    renderer.setConvergence(settings.denoise ? 0.012f : 0.004f);
    const float sampleClamp = in.value<float>();
    const uint32_t sampleClampDepth = in.value<uint32_t>();
    float volumeFactors[3];
    in.floats(volumeFactors, 3);
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
    camera.projection = in.value<uint32_t>();
    in.floats(camera.projectionValues, 4);
    in.floats(camera.region, 4);
    camera.draft = in.value<uint32_t>();
    in.floats(camera.filmShift, 2);
    // With motion blur, the camera again as it is when the shutter closes.
    Camera cameraClose = camera;
    if (sceneFlags & SCENE_MOTION) {
        in.floats(cameraClose.eye, 3);
        in.floats(cameraClose.target, 3);
        in.floats(cameraClose.up, 3);
        cameraClose.verticalFovDegrees = in.value<float>();
    }

    // Read new images before the materials whose layers will refer to them.
    struct TextureEntry {
        uint64_t key;
        uint32_t flags;
        std::string file;
    };
    std::vector<TextureEntry> entries(in.value<uint32_t>());
    for (TextureEntry& entry : entries) {
        entry.key = in.value<uint64_t>();
        entry.flags = in.value<uint32_t>();
        entry.file = in.text(in.value<uint32_t>());
    }
    // Where the new images would not all fit on the graphics card as they are, each is made smaller: halved until no
    // side is longer than the largest limit, a power of two, at which they all fit. The card keeps room for the
    // picture's own buffers, the denoiser and the geometry. MOONLIGHTIPR_TEXTURE_LIMIT, where it is set, is the limit.
    uint32_t limit = 0;
    {
        std::vector<ImageSize> sizes;
        for (const TextureEntry& entry : entries)
            if (textures.find(entry.key) == textures.end()) sizes.push_back(imageSize(entry.file));
        const auto needed = [&](uint32_t cap) { size_t total = 0; for (const ImageSize& size : sizes) total += cardBytes(size, cap); return total; };
        const size_t reserve = size_t(1024) << 20;
        const size_t free = renderer.freeMemory();
        const size_t room = free > reserve ? size_t(double(free - reserve) * 0.8) : 0;
        if (const char* forced = std::getenv("MOONLIGHTIPR_TEXTURE_LIMIT")) limit = uint32_t(std::strtoul(forced, nullptr, 10));
        else if (!sizes.empty() && needed(0) > room) {
            limit = 256;
            for (uint32_t cap = 8192; cap >= 256; cap /= 2)
                if (needed(cap) <= room) { limit = cap; break; }
        }
        uint32_t largest = 0;
        for (const ImageSize& size : sizes) largest = std::max(largest, std::max(size.width, size.height));
        if (limit && largest > limit)
            std::cerr << "MoonLightIPR textures: at most " << limit << " pixels across, to fit the " << (free >> 20)
                      << " MB free on the graphics card (they would take " << (needed(0) >> 20) << " MB as they are)" << std::endl;
    }
    std::vector<uint32_t> textureIndices(entries.size());
    for (size_t t = 0; t < entries.size(); ++t) {
        uint32_t& textureIndex = textureIndices[t];
        const uint64_t key = entries[t].key;
        const uint32_t flags = entries[t].flags;
        const std::string& file = entries[t].file;
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
            desc.maxSize = limit;
            cached = textures.emplace(key, CachedMesh{renderer.addTexture(desc), 0}).first;
        }
        cached->second.lastUsed = generation;
        textureIndex = cached->second.index;
    }

    // Grids of densities, which the fogs among the materials refer to: "MLV1", three counts, the largest value, a
    // transform the packer has already used, then the values.
    std::vector<uint32_t> gridIndices(in.value<uint32_t>());
    for (uint32_t& gridIndex : gridIndices) {
        const uint64_t key = in.value<uint64_t>();
        const std::string file = in.text(in.value<uint32_t>());
        auto cached = grids.find(key);
        if (cached == grids.end()) {
            std::ifstream source(file, std::ios::binary);
            const std::vector<char> data((std::istreambuf_iterator<char>(source)), std::istreambuf_iterator<char>());
            GridDesc desc;
            if (data.size() < 84 || (std::memcmp(data.data(), "MLV1", 4) != 0 && std::memcmp(data.data(), "MLV4", 4) != 0))
                throw std::runtime_error("Cannot read MoonLightIPR grid: " + file);
            desc.channels = data[3] == '4' ? 4 : 1;
            std::memcpy(desc.counts, data.data() + 4, 12);
            std::memcpy(&desc.peak, data.data() + 16, 4);
            const size_t count = size_t(desc.counts[0]) * desc.counts[1] * desc.counts[2] * desc.channels;
            if (!count || count > (data.size() - 84) / 4) throw std::runtime_error("MoonLightIPR grid is truncated: " + file);
            std::vector<float> values(count);
            std::memcpy(values.data(), data.data() + 84, count * 4);
            desc.values = values.data();
            cached = grids.emplace(key, CachedMesh{renderer.addGrid(desc), 0}).first;
        }
        cached->second.lastUsed = generation;
        gridIndex = cached->second.index;
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
        material.specularWeight = in.value<float>();
        in.floats(material.diffuseTransmission, 3);
        in.floats(material.diffuseKept, 3);
        material.fuzz = in.value<float>();
        in.floats(material.fuzzColor, 3);
        material.fuzzRoughness = in.value<float>();
        material.fuzzAbsorbs = in.value<float>() > 0.5f;
        material.clearcoatBump = in.value<float>();
        const uint32_t materialFlags = in.value<uint32_t>();
        material.thin = (materialFlags & 1) != 0;
        material.clearcoatDims = (materialFlags & 2) != 0;
        material.beckmann = (materialFlags & 16) != 0;
        material.roughnessCurve = int((materialFlags >> 8) & 3);
        material.noCaustics = (materialFlags & 1024) != 0;
        material.randomWalk = (materialFlags & 2048) != 0;
        material.layerStart = in.value<uint32_t>();
        material.layerCount = in.value<uint32_t>();
        material.tangentSlot = in.value<uint32_t>();
        if (materialFlags & (4096 | 8192)) {
            // A toon material's two ramps follow, and the numbers that go with them.
            material.toonDiffuse = (materialFlags & 4096) != 0;
            material.toonSpecular = (materialFlags & 8192) != 0;
            material.toon.resize(256 * 4 + 8 + 8);
            in.floats(material.toon.data(), 256 * 4 + 8);
            // How many highlights follow, the diffuse ramp's value past its end and what the first highlight is, then
            // each further highlight's ramp and numbers.
            material.toonMore = std::min(in.value<uint32_t>(), 2u);
            in.floats(material.toon.data() + 256 * 4 + 8, 8);
            const size_t extra = 256 + 8 + 5;
            material.toon.resize(material.toon.size() + material.toonMore * extra);
            in.floats(material.toon.data() + 256 * 4 + 8 + 8, material.toonMore * extra);
        }
        if (materialFlags & 64) {
            // A hair fibre's four lobes follow.
            material.hair = true;
            in.floats(material.hairRoughness, 4);
            in.floats(material.hairOffset, 4);
            in.floats(material.hairTint, 9);
            material.hairAzimuthalRoughness = in.value<float>();
            material.hairSaturation = in.value<float>();
            material.hairLobes = in.value<uint32_t>();
            material.hairFresnel = in.value<uint32_t>();
            material.hairGlint = (material.hairLobes & 16) != 0;
            material.hairGlintRoughness = in.value<float>();
            material.hairGlintEccentricity = in.value<float>();
            material.hairGlintSaturation = in.value<float>();
            in.floats(material.hairTwists, 2);
            material.hairCuticle = in.value<float>();
        }
        if (materialFlags & 128) {
            // An even fog in place of a surface.
            material.volume = true;
            in.floats(material.volumeExtinction, 3);
            in.floats(material.volumeAlbedo, 3);
            in.floats(material.volumeEmission, 3);
            material.volumeAnisotropy = in.value<float>();
            const int32_t grid = in.value<int32_t>();
            if (grid >= int32_t(gridIndices.size())) throw std::runtime_error("MoonLightIPR scene volume refers to a missing grid");
            material.volumeGrid = grid < 0 ? -1 : int32_t(gridIndices[grid]);
            in.floats(material.volumeRows, 12);
            const int32_t glow = in.value<int32_t>();
            if (glow >= int32_t(gridIndices.size())) throw std::runtime_error("MoonLightIPR scene volume refers to a missing grid");
            material.volumeGlowGrid = glow < 0 ? -1 : int32_t(gridIndices[glow]);
            in.floats(material.volumeGlowRows, 12);
        }
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

    const auto image = [&](int32_t texture) {
        if (texture >= int32_t(textureIndices.size())) throw std::runtime_error("MoonLightIPR scene light refers to a missing texture");
        return texture < 0 ? -1 : int32_t(textureIndices[texture]);
    };
    std::vector<DistantLight> lights(in.value<uint32_t>());
    for (DistantLight& light : lights) {
        in.floats(light.direction, 3);
        in.floats(light.radiance, 3);
        light.angularExtentDegrees = in.value<float>();
        light.visibleInCamera = in.value<uint32_t>() != 0;
        in.floats(light.axisX, 3);
        in.floats(light.axisY, 3);
        light.texture = image(in.value<int32_t>());
        in.floats(light.seenRadiance, 3);
        light.seenExtentDegrees = in.value<float>();
    }

    std::vector<Light> localLights(in.value<uint32_t>());
    std::vector<std::vector<float>> lightTriangles(localLights.size());
    std::vector<std::vector<LightFilter>> lightFilters(localLights.size());
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
        light.texture = image(in.value<int32_t>());
        lightFilters[l].resize(in.value<uint32_t>());
        for (LightFilter& filter : lightFilters[l]) {
            const uint32_t filterKind = in.value<uint32_t>();
            if (filterKind > LightFilter::Vdb) throw std::runtime_error("MoonLightIPR scene has an unknown light filter");
            filter.kind = LightFilter::Kind(filterKind);
            filter.flags = in.value<uint32_t>();
            in.floats(filter.values, 4);
            in.floats(filter.rows, 12);
            const int32_t named = in.value<int32_t>();
            if (filter.kind == LightFilter::Vdb) {
                // A grid, by its place among the scene's grids.
                if (named < 0 || named >= int32_t(gridIndices.size())) throw std::runtime_error("MoonLightIPR scene light filter refers to a missing grid");
                filter.texture = int32_t(gridIndices[named]);
            } else {
                filter.texture = image(named);
            }
            in.floats(filter.more, 12);
            filter.ramp = image(in.value<int32_t>());
        }
        light.filters = lightFilters[l].data();
        light.filterCount = lightFilters[l].size();
        if (light.kind == Light::Mesh) {
            lightTriangles[l] = in.array<float>(size_t(in.value<uint32_t>()) * 9);
            light.triangles = lightTriangles[l].data();
            light.triangleCount = lightTriangles[l].size() / 9;
        }
    }

    // Load new meshes before replacing the instances that will refer to them.
    std::vector<Displacing> displacing;
    std::vector<uint32_t> meshIndices(in.value<uint32_t>());
    std::vector<std::vector<int32_t>> meshSlots(meshIndices.size());
    for (size_t m = 0; m < meshIndices.size(); ++m) {
        uint32_t& meshIndex = meshIndices[m];
        const uint64_t key = in.value<uint64_t>();
        const uint32_t flags = in.value<uint32_t>();
        meshSlots[m] = in.array<int32_t>(UV_SLOT_COUNT);
        auto cached = meshes.find(key);
        if ((flags & MESH_HAS_DATA) && (flags & MESH_CURVES)) {
            const uint32_t pointCount = in.value<uint32_t>(), segmentCount = in.value<uint32_t>();
            const std::vector<float> positions = in.array<float>(size_t(pointCount) * 3), radii = in.array<float>(pointCount);
            const std::vector<uint32_t> segments = in.array<uint32_t>(segmentCount);
            const std::vector<float> strands = in.array<float>(size_t(pointCount) * 3);
            const std::vector<float> uvs = in.array<float>(flags & MESH_HAS_UVS ? size_t(pointCount) * 2 : 0);
            const std::vector<float> closing = in.array<float>(flags & MESH_MOVES ? size_t(pointCount) * 3 : 0);
            if (cached == meshes.end()) {
                CurveDesc desc;
                desc.positions = positions.data();
                desc.radii = radii.data();
                desc.pointCount = pointCount;
                desc.segments = segments.data();
                desc.segmentCount = segmentCount;
                desc.uvs = uvs.empty() ? nullptr : uvs.data();
                desc.linear = (flags & MESH_LINEAR) != 0;
                desc.ribbon = (flags & MESH_RIBBON) != 0;
                desc.strands = strands.data();
                desc.closePositions = closing.empty() ? nullptr : closing.data();
                cached = meshes.emplace(key, CachedMesh{renderer.addCurves(desc), 0}).first;
            }
        } else if (flags & MESH_HAS_DATA) {
            uint32_t vertexCount = 0, triangleCount = 0;
            std::vector<float> positions, normals, closePositions;
            std::vector<uint32_t> indices, materialIds;
            std::vector<std::vector<float>> uvSets;
            if (flags & MESH_SUBDIVIDE) {
                // A control cage: polygons as they were modelled, subdivided here as MoonRay does
                // for a subdivision surface.
                Cage cage;
                const uint32_t cageVertices = in.value<uint32_t>(), faceCount = in.value<uint32_t>(), cornerCount = in.value<uint32_t>();
                const uint32_t levels = in.value<uint32_t>(), creaseCount = in.value<uint32_t>();
                if (levels > 6) throw std::runtime_error("MoonLightIPR scene asks for too many subdivision levels");
                cage.positions = in.array<float>(size_t(cageVertices) * 3);
                cage.faceSizes = in.array<uint32_t>(faceCount);
                cage.corners = in.array<uint32_t>(cornerCount);
                cage.faceMaterials = in.array<uint32_t>(flags & MESH_HAS_MATERIAL_IDS ? faceCount : 0);
                cage.uvSets.resize(flags & MESH_HAS_UVS ? in.value<uint32_t>() : 0);
                if (cage.uvSets.size() > UV_SLOT_COUNT) throw std::runtime_error("MoonLightIPR scene mesh has too many coordinate sets");
                for (std::vector<float>& set : cage.uvSets) set = in.array<float>(size_t(cornerCount) * 2);
                cage.creaseEdges = in.array<uint32_t>(size_t(creaseCount) * 2);
                cage.creaseSharpness = in.array<float>(creaseCount);
                if (cached == meshes.end()) {
                    Triangles fine = subdivide(std::move(cage), levels);
                    positions = std::move(fine.positions);
                    indices = std::move(fine.indices);
                    materialIds = std::move(fine.materialIds);
                    uvSets = std::move(fine.uvSets);
                    vertexCount = uint32_t(positions.size() / 3);
                    triangleCount = uint32_t(indices.size() / 3);
                }
            } else {
                vertexCount = in.value<uint32_t>();
                triangleCount = in.value<uint32_t>();
                positions = in.array<float>(size_t(vertexCount) * 3);
                normals = in.array<float>(flags & MESH_HAS_NORMALS ? size_t(vertexCount) * 3 : 0);
                indices = in.array<uint32_t>(size_t(triangleCount) * 3);
                materialIds = in.array<uint32_t>(flags & MESH_HAS_MATERIAL_IDS ? triangleCount : 0);
                uvSets.resize(flags & MESH_HAS_UVS ? in.value<uint32_t>() : 0);
                if (uvSets.size() > UV_SLOT_COUNT) throw std::runtime_error("MoonLightIPR scene mesh has too many coordinate sets");
                for (std::vector<float>& set : uvSets) set = in.array<float>(size_t(triangleCount) * 6);
                closePositions = in.array<float>(flags & MESH_MOVES ? size_t(vertexCount) * 3 : 0);
            }
            // A displaced mesh: how often to split it, the material its instances give it, and each displacing
            // material's program (form 'L').
            uint32_t splits = 0, displacedMaterial = 0;
            std::vector<std::pair<uint32_t, std::vector<DisplacementStep>>> programs;
            if (flags & MESH_DISPLACE) {
                splits = in.value<uint32_t>();
                displacedMaterial = in.value<uint32_t>();
                programs.resize(in.value<uint32_t>());
                if (splits > 8 || programs.size() > 4096) throw std::runtime_error("MoonLightIPR scene displaces a mesh beyond its limits");
                for (auto& entry : programs) {
                    entry.first = in.value<uint32_t>();
                    entry.second.resize(in.value<uint32_t>());
                    if (entry.second.size() > 256) throw std::runtime_error("MoonLightIPR scene's displacement is too long");
                    for (DisplacementStep& step : entry.second) {
                        step.code = in.value<uint32_t>();
                        step.a = in.value<float>();
                        step.b = in.value<float>();
                        step.c = in.value<uint32_t>();
                    }
                }
            }
            if (cached == meshes.end() && (flags & MESH_DISPLACE)) {
                // Split finer, so that the displacement has vertices to move; moved once the materials are set.
                const std::vector<uint32_t> coarse = closePositions.empty() ? std::vector<uint32_t>() : indices;
                Triangles fine = split(Triangles{std::move(positions), std::move(indices), std::move(materialIds), std::move(uvSets)}, splits);
                positions = std::move(fine.positions);
                indices = std::move(fine.indices);
                materialIds = std::move(fine.materialIds);
                uvSets = std::move(fine.uvSets);
                vertexCount = uint32_t(positions.size() / 3);
                triangleCount = uint32_t(indices.size() / 3);
                for (uint32_t index : indices)
                    if (index >= vertexCount) throw std::runtime_error("MoonLightIPR scene mesh index is out of range");
                normals = smoothNormals(positions, indices);
                // Where the mesh is as the shutter closes, split the same way: the splitting goes by the triangles
                // alone, so the vertices it makes match those above one for one.
                if (!closePositions.empty()) {
                    closePositions = split(Triangles{std::move(closePositions), coarse, {}, {}}, splits).positions;
                    if (closePositions.size() != positions.size()) throw std::runtime_error("MoonLightIPR scene's displaced mesh moves unevenly");
                }
            }
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
                if (flags & MESH_DISPLACE) {
                    Displacing held;
                    held.mesh = cached->second.index;
                    held.positions = std::move(positions);
                    held.directions = std::move(normals);
                    if (!closePositions.empty()) {
                        held.closingDirections = smoothNormals(closePositions, held.indices.empty() ? indices : held.indices);
                        held.closing = std::move(closePositions);
                    }
                    held.indices = std::move(indices);
                    held.materialIds = std::move(materialIds);
                    held.material = displacedMaterial;
                    held.programs = std::move(programs);
                    if (!uvSets.empty()) held.uvs = uvSets[0];
                    held.smooth = (flags & MESH_SMOOTH) != 0;
                    displacing.push_back(std::move(held));
                }
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
        instance.visibility = in.value<uint32_t>();
        in.floats(instance.transform, 12);
        if (sceneFlags & SCENE_MOTION) {
            in.floats(instance.closeTransform, 12);
            instance.moves = !std::equal(instance.transform, instance.transform + 12, instance.closeTransform);
        }
    }
    // In a scene with motion, where each light is when the shutter closes; everything else about it is as it opens.
    std::vector<DistantLight> closingDistant;
    std::vector<Light> closingLocal;
    if (sceneFlags & SCENE_MOTION) {
        const uint32_t distantCount = in.value<uint32_t>();
        if (distantCount != lights.size()) throw std::runtime_error("MoonLightIPR scene's closing distant lights do not match its lights");
        closingDistant = lights;
        for (DistantLight& light : closingDistant) {
            in.floats(light.direction, 3);
            in.floats(light.axisX, 3);
            in.floats(light.axisY, 3);
        }
        const uint32_t localCount = in.value<uint32_t>();
        if (localCount != localLights.size()) throw std::runtime_error("MoonLightIPR scene's closing lights do not match its lights");
        closingLocal = localLights;
        for (Light& light : closingLocal) {
            float pose[12];
            in.floats(pose, 12);
            if (light.kind == Light::Mesh) continue;
            std::copy(pose, pose + 3, light.position);
            std::copy(pose + 3, pose + 6, light.axisX);
            std::copy(pose + 6, pose + 9, light.axisY);
            std::copy(pose + 9, pose + 12, light.direction);
        }
    }
    // The light sets: which lights reach each instance, a bit for the environment, then each distant light and each
    // other light. An instance names its set above the eight bits of its visibility; set 0 is every light.
    const uint32_t setWords = in.value<uint32_t>(), setCount = in.value<uint32_t>();
    if (!setCount || setWords != (1 + lights.size() + localLights.size() + 31) / 32)
        throw std::runtime_error("MoonLightIPR scene's light sets do not match its lights");
    std::vector<uint32_t> lightSets(size_t(setWords) * setCount);
    for (uint32_t& word : lightSets) word = in.value<uint32_t>();
    for (const Instance& instance : instances)
        if ((instance.visibility >> 8) >= setCount) throw std::runtime_error("MoonLightIPR scene instance refers to a missing light set");
    if (!in.finished()) throw std::runtime_error("MoonLightIPR scene has trailing data");

    renderer.setMaterials(materials.data(), materials.size(), layers.data(), layers.size(), tiles.data(), tiles.size());
    renderer.setWorkingSpace(sceneFlags & SCENE_WORKING_SPACE ? workingSpace : nullptr);
    for (auto entry = grids.begin(); entry != grids.end();) {
        if (generation - entry->second.lastUsed >= MESH_RETENTION) {
            renderer.removeGrid(entry->second.index);
            entry = grids.erase(entry);
        } else ++entry;
    }
    for (auto entry = textures.begin(); entry != textures.end();) {
        if (generation - entry->second.lastUsed >= MESH_RETENTION) {
            renderer.removeTexture(entry->second.index);
            entry = textures.erase(entry);
        } else ++entry;
    }
    for (size_t m = 0; m < meshIndices.size(); ++m) renderer.setMeshUvSlots(meshIndices[m], meshSlots[m].data());
    // Displaced meshes, now their materials can be read: each vertex is looked up on the first triangle that has it,
    // and moved along its smooth normal by the height there times its material's Displacement Distance.
    for (Displacing& held : displacing) {
        const size_t vertexCount = held.positions.size() / 3, triangleCount = held.indices.size() / 3;
        std::vector<uint32_t> primitives(vertexCount, 0xffffffffu);
        std::vector<float> barycentrics(vertexCount * 2, 0.0f);
        for (size_t t = 0; t < triangleCount; ++t)
            for (int corner = 0; corner < 3; ++corner) {
                const uint32_t v = held.indices[t * 3 + corner];
                if (primitives[v] != 0xffffffffu) continue;
                primitives[v] = uint32_t(t);
                barycentrics[v * 2] = corner == 1 ? 1.0f : 0.0f;
                barycentrics[v * 2 + 1] = corner == 2 ? 1.0f : 0.0f;
            }
        for (uint32_t& primitive : primitives)
            if (primitive == 0xffffffffu) primitive = 0;    // a vertex no triangle uses stays where it is (its height is unused)
        std::vector<float> values(vertexCount * DISPLACE_SLOTS_READ * 3, 0.0f);
        renderer.displacementValues(held.mesh, held.material, primitives.data(), barycentrics.data(), vertexCount, values.data());
        const std::vector<float> tangents = tangentsOf(held.positions, held.indices, held.uvs);
        const std::vector<float> closingTangents = held.closing.empty() ? std::vector<float>() : tangentsOf(held.closing, held.indices, held.uvs);
        for (size_t v = 0; v < vertexCount; ++v) {
            const uint32_t material = held.materialIds.empty() ? held.material : held.materialIds[primitives[v]];
            const std::vector<DisplacementStep>* program = nullptr;
            for (const auto& entry : held.programs)
                if (entry.first == material) program = &entry.second;
            if (!program) continue;
            const float* found = &values[v * DISPLACE_SLOTS_READ * 3];
            displaced(&held.positions[v * 3], &held.directions[v * 3], &tangents[v * 3], found, *program);
            // As the shutter closes, the same values by where the surface then faces.
            if (!held.closing.empty())
                displaced(&held.closing[v * 3], &held.closingDirections[v * 3], &closingTangents[v * 3], found, *program);
        }
        const std::vector<float> shading = held.smooth ? smoothNormals(held.positions, held.indices) : std::vector<float>();
        renderer.reshapeMesh(held.mesh, held.positions.data(), shading.empty() ? nullptr : shading.data(),
                             held.closing.empty() ? nullptr : held.closing.data());
    }
    // Lights before the instances that may be the surface of one.
    renderer.setDistantLights(lights.data(), lights.size());
    renderer.setLights(localLights.data(), localLights.size());
    renderer.setLightMotion(closingDistant.data(), closingDistant.size(), closingLocal.data(), closingLocal.size());
    renderer.setLightSets(lightSets.data(), setWords, setCount);
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
    renderer.setMaxDepth(maxDepth, maxDiffuseDepth, maxGlossyDepth, maxVolumeDepth, (sceneFlags & SCENE_PRESENCE_SHADOWS) != 0);
    renderer.setSampleClamp(sampleClamp, sampleClampDepth);
    renderer.setVolumeScattering(volumeFactors[0], volumeFactors[1], volumeFactors[2]);
    if (settings.width != renderer.width() || settings.height != renderer.height()) renderer.resize(settings.width, settings.height);
    renderer.setCamera(camera);
    renderer.setCameraMotion(sceneFlags & SCENE_MOTION ? &cameraClose : nullptr);
    return settings;
}

}
