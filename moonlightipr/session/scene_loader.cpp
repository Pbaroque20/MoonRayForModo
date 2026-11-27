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
#include <set>
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
               MESH_DISPLACE = 1024,    // its materials displace it: split finer here, then moved by their height
               MESH_HAS_REST = 2048,    // its rest positions follow (form 'c'), for glitter in reference space
               MESH_HARD_EDGES = 4096;  // its corners' normals as given follow (form 'e'): a displaced mesh's hard edges
const uint32_t SCENE_DENOISE = 1, SCENE_WORKING_SPACE = 2, SCENE_MOTION = 4, SCENE_PRESENCE_SHADOWS = 8, SCENE_FLAT_OUT = 16,
               SCENE_KEEP_FLAKES = 32;     // Keep Metallic Flakes (Renderer::setKeepFlakes)
const uint32_t LAYER_UDIM = 1 << 19;    // as in src/device/shared.h
const uint32_t IRIDESCENCE_STEPS = 512; // likewise
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
    bool gradient = false;      // one of the packer's own gradients ("MLF1"), which is read as it is
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
        size.gradient = true;
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

// The bytes a texture takes on the card, given the most texels it may have across a side (0 for no limit): with its
// smaller copies and compressed, as it is prepared (preparedBytes), but for the packer's gradients, which are as they are.
size_t cardBytes(const ImageSize& size, uint32_t limit) {
    uint32_t width = size.width, height = size.height;
    while (limit && std::max(width, height) > limit) { width = std::max(1u, width / 2); height = std::max(1u, height / 2); }
    return preparedBytes(width, height, size.floatData, !size.gradient, !size.gradient);
}

// A texture made ready for the card is kept beside the packer's file, as that file's name and ".mlt", and read from there
// the next time, so that a picture is filtered down and compressed once. The packer's file is named by what it was made
// from, so the two go together; one made smaller to fit (a limit) is not kept.
std::string preparedPath(const std::string& file) { return file + ".mlt"; }

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
    // Its hard edges (MESH_HARD_EDGES): the drawn mesh's vertices, each a point of the displaced one (pointOf), the
    // points split where their corners' normals as given disagree, and its triangles by them (drawn). Empty: one each.
    std::vector<uint32_t> pointOf, drawn;
};

// A displaced mesh's hard edges (native-port/modo_hard_edges.h's rule): its points split where the corners about one
// disagree as given (normals under a degree apart agree), so that each side of a hard edge has a vertex of its own
// that its shading normals are made over; the displacement still moves each point once. keys: each triangle corner's
// normal as given. pointOf: each drawn vertex's point (the points first, as they are; then the split-off ones), drawn:
// the triangles by the drawn vertices. Nothing where no point needs splitting.
void hardEdgeVertices(const std::vector<uint32_t>& indices, const std::vector<float>& keys, size_t pointCount,
                      std::vector<uint32_t>& pointOf, std::vector<uint32_t>& drawn) {
    pointOf.clear();
    drawn.clear();
    if (keys.size() != indices.size() * 3) return;
    std::vector<float> unit(keys.size(), 0.0f);
    for (size_t i = 0; i < indices.size(); ++i) {
        const float* k = &keys[i * 3];
        const float l = std::sqrt(k[0] * k[0] + k[1] * k[1] + k[2] * k[2]);
        if (l > 0.0f && std::isfinite(l))
            for (int axis = 0; axis < 3; ++axis) unit[i * 3 + axis] = k[axis] / l;
    }
    std::vector<uint32_t> first(pointCount + 1, 0);
    for (uint32_t v : indices)
        if (v < pointCount) ++first[v + 1];
    for (size_t v = 0; v < pointCount; ++v) first[v + 1] += first[v];
    std::vector<uint32_t> at(first.begin(), first.end() - 1), corners(first[pointCount]);
    for (size_t i = 0; i < indices.size(); ++i)
        if (indices[i] < pointCount) corners[at[indices[i]]++] = uint32_t(i);
    std::vector<uint32_t> made(indices.begin(), indices.end()), vertexOf, extra;
    for (size_t v = 0; v < pointCount; ++v) {
        const uint32_t begin = first[v], end = first[v + 1];
        vertexOf.assign(end - begin, 0);
        for (uint32_t j = begin; j < end; ++j) {
            const float* b = &unit[size_t(corners[j]) * 3];
            uint32_t found = ~0u;
            for (uint32_t i = begin; i < j && found == ~0u; ++i) {
                const float* a = &unit[size_t(corners[i]) * 3];
                if (a[0] * b[0] + a[1] * b[1] + a[2] * b[2] >= 0.9999f) found = vertexOf[i - begin];
            }
            if (found == ~0u) {
                if (j == begin) {
                    found = uint32_t(v);
                } else {
                    found = uint32_t(pointCount + extra.size());
                    extra.push_back(uint32_t(v));
                }
            }
            vertexOf[j - begin] = found;
            made[corners[j]] = found;
        }
    }
    if (extra.empty()) return;
    pointOf.resize(pointCount + extra.size());
    for (size_t v = 0; v < pointCount; ++v) pointOf[v] = uint32_t(v);
    std::copy(extra.begin(), extra.end(), pointOf.begin() + std::ptrdiff_t(pointCount));
    drawn = std::move(made);
}

// Points (three numbers each) at the drawn vertices.
std::vector<float> atVertices(const std::vector<float>& points, const std::vector<uint32_t>& pointOf) {
    std::vector<float> out(pointOf.size() * 3);
    for (size_t i = 0; i < pointOf.size(); ++i)
        for (int axis = 0; axis < 3; ++axis) out[i * 3 + axis] = points[size_t(pointOf[i]) * 3 + axis];
    return out;
}

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
    // camera's film offset is, "I" since a material's fuzz is, "J" since the light sets are, "K" since a mesh may be displaced, "L" since by a program of displacement nodes, "M" since a material's clearcoat bump strength is, "N" since whether the camera sees each light is, "O" since the subsurface scatterings a path may have are, "P" since each instance's own number is, "Q" since the roughness clamp is, "R" since what reflections and refractions see of the environment is, "S" since the kinds of rays each light is hidden from are, "T" since a displaced mesh may be split by its distance from the camera, "U" since where each moving instance stands at the frame is, "W" since how each light's picture is repeated, turned and moved across it is, "X" since a material's iridescence is, "Y" since a tilted lens's plane of focus is, "Z" since a material's shadow catcher is, "a" since a mesh's slot map is 32 long, "b" since it is 64 long, "c" since a material's glitter is, "d" since how a fog is lit is, "e" since a displaced mesh's corners' normals as given may be. A plugin and a session of different versions say so plainly, in
    // place of reading each other's scenes wrongly.
    const uint32_t mark = in.value<uint32_t>();
    if ((mark & 0x00ffffff) != 0x00534c4d) throw std::runtime_error("Not a MoonLightIPR scene: " + path);
    if (mark != 0x65534c4d)
        throw std::runtime_error("This MoonLightIPR and the plugin are of different versions (the scene is form '" + std::string(1, char(mark >> 24))
                                 + "', this MoonLightIPR reads 'e'). Install the kit and its runtime from the same release.");
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
    settings.flatOut = (sceneFlags & SCENE_FLAT_OUT) != 0;
    renderer.setKeepFlakes((sceneFlags & SCENE_KEEP_FLAKES) != 0);
    renderer.setConvergence(settings.flatOut ? 0.0f : settings.denoise ? 0.012f : 0.004f);
    const float sampleClamp = in.value<float>();
    const uint32_t sampleClampDepth = in.value<uint32_t>();
    const uint32_t maxSubsurface = in.value<uint32_t>();
    const float roughnessClamp = in.value<float>();
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
    // The tilt of the plane of focus (form 'Y').
    in.floats(camera.focusTilt, 2);
    // A bokeh image: its size, then its brightnesses, top row first (form 'B'); 0 for none.
    camera.bokehSize = in.value<uint32_t>();
    if (camera.bokehSize > 256) throw std::runtime_error("MoonLightIPR bokeh image is too large");
    camera.bokeh.resize(size_t(camera.bokehSize) * camera.bokehSize);
    if (!camera.bokeh.empty()) in.floats(camera.bokeh.data(), camera.bokeh.size());
    // With motion blur, the camera again as it is when the shutter closes.
    Camera cameraClose = camera;
    // Where the frame falls in the shutter, 0 its opening and 1 its closing (form 'U').
    float frameMoment = 0.5f;
    if (sceneFlags & SCENE_MOTION) {
        in.floats(cameraClose.eye, 3);
        in.floats(cameraClose.target, 3);
        in.floats(cameraClose.up, 3);
        cameraClose.verticalFovDegrees = in.value<float>();
        frameMoment = std::clamp(in.value<float>(), 0.0f, 1.0f);
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
    // Where the new images would not all fit on the graphics card as they are, the largest are kept whole in the
    // computer's memory instead (out of core, TextureDesc::hostResident), which the card reads across the bus, until
    // the rest fit: nothing is made smaller. The card keeps room for the picture's own buffers, the denoiser and the
    // geometry. Only where the computer's memory will not hold them either are images made smaller, as they all were
    // before: halved until no side is longer than the largest limit, a power of two, at which they fit.
    // MOONLIGHTIPR_TEXTURE_LIMIT, where it is set, is that limit and keeps every image on the card;
    // MOONLIGHTIPR_TEXTURES_IN_MEMORY=1 keeps every new image in the computer's memory (for tests).
    uint32_t limit = 0;
    std::set<uint64_t> inMemory;
    {
        std::vector<std::pair<ImageSize, uint64_t>> sizes;
        for (const TextureEntry& entry : entries)
            if (textures.find(entry.key) == textures.end()) sizes.push_back({imageSize(entry.file), entry.key});
        const auto needed = [&](uint32_t cap) { size_t total = 0; for (const auto& size : sizes) total += cardBytes(size.first, cap); return total; };
        const size_t reserve = size_t(1024) << 20;
        const size_t free = renderer.freeMemory();
        const size_t room = free > reserve ? size_t(double(free - reserve) * 0.8) : 0;
        const char* allInMemory = std::getenv("MOONLIGHTIPR_TEXTURES_IN_MEMORY");
        if (const char* forced = std::getenv("MOONLIGHTIPR_TEXTURE_LIMIT")) limit = uint32_t(std::strtoul(forced, nullptr, 10));
        else if (allInMemory && *allInMemory == '1') {
            for (const auto& size : sizes) inMemory.insert(size.second);
        } else if (!sizes.empty() && needed(0) > room) {
            // The largest to the computer's memory first, until what is left fits on the card.
            std::vector<std::pair<ImageSize, uint64_t>> largestFirst = sizes;
            std::sort(largestFirst.begin(), largestFirst.end(), [](const auto& a, const auto& b) { return cardBytes(a.first, 0) > cardBytes(b.first, 0); });
            size_t onCard = needed(0), moved = 0;
            for (const auto& size : largestFirst) {
                if (onCard <= room) break;
                inMemory.insert(size.second);
                onCard -= cardBytes(size.first, 0);
                moved += cardBytes(size.first, 0);
            }
            std::cerr << "MoonLightIPR textures: " << inMemory.size() << " of " << sizes.size() << " kept whole in the computer's memory ("
                      << (moved >> 20) << " MB), the " << (free >> 20) << " MB free on the graphics card not holding them all" << std::endl;
            // The limit they would all have been made smaller to, kept for where the computer's memory refuses them.
            limit = 256;
            for (uint32_t cap = 8192; cap >= 256; cap /= 2)
                if (needed(cap) <= room) { limit = cap; break; }
        }
    }
    std::vector<uint32_t> textureIndices(entries.size());
    for (size_t t = 0; t < entries.size(); ++t) {
        uint32_t& textureIndex = textureIndices[t];
        const uint64_t key = entries[t].key;
        const uint32_t flags = entries[t].flags;
        const std::string& file = entries[t].file;
        auto cached = textures.find(key);
        if (cached == textures.end()) {
            const bool outOfCore = inMemory.count(key) != 0;
            const bool srgb = (flags & TEXTURE_SRGB) != 0;
            const uint32_t maxSize = outOfCore ? 0 : (inMemory.empty() ? limit : 0);
            TextureDesc desc;
            desc.srgb = srgb;
            desc.wrapU = TextureDesc::Wrap((flags >> TEXTURE_WRAP_U_SHIFT) & 3);
            desc.wrapV = TextureDesc::Wrap((flags >> TEXTURE_WRAP_V_SHIFT) & 3);
            desc.hostResident = outOfCore;
            desc.maxSize = maxSize;
            // On the card: as prepared before where that is kept, else prepared now (and kept, unless made smaller).
            PreparedTexture prepared;
            // MOONLIGHTIPR_TEXTURE_PREP, for tests: "plain" for the picture alone, "mips" for its smaller copies uncompressed.
            const char* preparing = std::getenv("MOONLIGHTIPR_TEXTURE_PREP");
            const std::string prep = preparing ? preparing : "";
            const bool reused = prep.empty() && !outOfCore && !maxSize && readPreparedTexture(preparedPath(file), prepared)
                                && prepared.srgb == (srgb && prepared.format != PreparedTexture::Halves && prepared.format != PreparedTexture::BC6H);
            Image image;
            if (!reused) {
                image = readImage(file);
                desc.pixels = image.floatData ? static_cast<const void*>(image.floats.data()) : image.bytes.data();
                desc.width = image.width;
                desc.height = image.height;
                desc.floatData = image.floatData;
                const bool gradient = imageSize(file).gradient;
                if (!outOfCore) {
                    prepared = prepareTexture(desc, !gradient && prep != "plain", !gradient && prep.empty());
                    if (!maxSize && !gradient && prep.empty()) writePreparedTexture(preparedPath(file), prepared);
                }
            }
            if (!outOfCore) desc.prepared = &prepared;
            uint32_t made = 0;
            try {
                // MOONLIGHTIPR_TEXTURES_REFUSED=1, for tests: the card refuses every new image, as a full one does.
                const char* refusing = std::getenv("MOONLIGHTIPR_TEXTURES_REFUSED");
                if (!outOfCore && refusing && *refusing == '1')
                    throw std::runtime_error("cudaMallocMipmappedArray: out of memory (MOONLIGHTIPR_TEXTURES_REFUSED)");
                made = renderer.addTexture(desc);
            } catch (const std::exception& refused) {
                if (!outOfCore) {
                    // The card refused it after all (the room was reckoned before the geometry, and other programs may
                    // have taken memory since): kept whole in the computer's memory instead, never left out. Said, as
                    // the others kept there are.
                    std::cerr << "MoonLightIPR textures: " << file << " kept whole in the computer's memory, the graphics card refusing it ("
                              << refused.what() << ")" << std::endl;
                    if (reused) {
                        image = readImage(file);
                        desc.pixels = image.floatData ? static_cast<const void*>(image.floats.data()) : image.bytes.data();
                        desc.width = image.width;
                        desc.height = image.height;
                        desc.floatData = image.floatData;
                    }
                    desc.hostResident = true;
                    desc.prepared = nullptr;
                    desc.maxSize = 0;
                    made = renderer.addTexture(desc);
                    cached = textures.emplace(key, CachedMesh{made, 0}).first;
                    cached->second.lastUsed = generation;
                    textureIndex = cached->second.index;
                    continue;
                }
                // The computer's memory would not hold it either: on the card, made smaller, as before.
                std::cerr << "MoonLightIPR textures: at most " << limit << " pixels across for " << file
                          << ", the computer's memory refusing it (" << refused.what() << ")" << std::endl;
                desc.hostResident = false;
                desc.maxSize = limit;
                prepared = prepareTexture(desc, !imageSize(file).gradient, !imageSize(file).gradient);
                desc.prepared = &prepared;
                made = renderer.addTexture(desc);
            }
            cached = textures.emplace(key, CachedMesh{made, 0}).first;
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
        material.clearcoatStraight = (materialFlags & (1u << 17)) != 0;
        material.beckmann = (materialFlags & 16) != 0;
        material.roughnessCurve = int((materialFlags >> 8) & 3);
        material.noCaustics = (materialFlags & 1024) != 0;
        material.randomWalk = (materialFlags & 2048) != 0;
        material.roughnessClamped = (materialFlags & 16384) != 0;
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
            // How it is lit (form 'd'): FOG_NO_SHADOW, FOG_NO_ENVIRONMENT.
            material.volumeSwitches = in.value<uint32_t>();
        }
        if (materialFlags & (1u << 16)) {
            // MoonRay's iridescence: the lobe it tints, its numbers, then its colours from index 0 to 1.
            material.iridescent = true;
            material.iridescenceCoat = in.value<uint32_t>() == 1;
            material.iridescenceStrength = in.value<float>();
            material.iridescenceExponent = in.value<float>();
            material.iridescenceThickness = in.value<float>();
            material.iridescenceAt0 = in.value<float>();
            material.iridescenceAt90 = in.value<float>();
            material.iridescenceColors.resize(IRIDESCENCE_STEPS * 3);
            in.floats(material.iridescenceColors.data(), IRIDESCENCE_STEPS * 3);
        }
        if (materialFlags & (1u << 18)) {
            // The kit's shadow catcher (form 'Z'): its strength; a matte with 1 << 19.
            material.shadowCatcher = std::min(std::max(in.value<float>(), 0.0f), 1.0f);
            material.shadowMatte = (materialFlags & (1u << 19)) != 0;
        }
        if (materialFlags & (1u << 20)) {
            // MoonRay's glitter (form 'c'): its seed, space and switches (1 compensate a reference space's stretch, 2 bounces
            // see the average, 4 the camera's flakes add), then its amount, randomness, density, jitter and level-of-detail
            // quality, and styles A and B's frequency, size, roughness and colour, then the colour variation.
            material.glitter = true;
            material.glitterSeed = in.value<int32_t>();
            material.glitterSpace = in.value<uint32_t>();
            const uint32_t switches = in.value<uint32_t>();
            material.glitterCompensate = (switches & 1) != 0;
            material.glitterApproximate = (switches & 2) != 0;
            material.glitterAdditive = (switches & 4) != 0;
            material.glitterMask = in.value<float>();
            material.glitterRandomness = in.value<float>();
            material.glitterDensity = in.value<float>();
            material.glitterJitter = in.value<float>();
            material.glitterLodQuality = in.value<float>();
            for (int style = 0; style < 2; ++style) {
                material.glitterFrequency[style] = in.value<float>();
                material.glitterSize[style] = in.value<float>();
                material.glitterRoughness[style] = in.value<float>();
                in.floats(material.glitterColor + 3 * style, 3);
            }
            in.floats(material.glitterVariation, 3);
            const float numbers[] = {material.glitterMask, material.glitterRandomness, material.glitterDensity, material.glitterJitter};
            for (float v : numbers)
                if (!std::isfinite(v)) throw std::runtime_error("MoonLightIPR scene material has a glitter that cannot be read");
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
        layer.pattern = in.value<uint32_t>();
        in.floats(layer.settings, 24);
        in.floats(layer.rows, 12);
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

    // The environment: a column of rows from zenith to nadir for what diffuse light sees, one for what the camera sees,
    // one for what reflections see and one for what refractions see (form R), each optionally with a
    // latitude-longitude image added.
    struct EnvironmentPart {
        std::vector<float> rows;
        bool hasImage = false;
        uint64_t key = 0;
        std::string file;
        float scale = 1.0f;
        float rotation[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
        bool operator==(const EnvironmentPart& other) const {
            return rows == other.rows && hasImage == other.hasImage
                && (!hasImage || (key == other.key && scale == other.scale && std::equal(rotation, rotation + 9, other.rotation)));
        }
    } parts[ENVIRONMENT_PARTS];
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
    // How a light's picture is laid across it (form W): MoonRay's texture transform, its repeats, its border colour and
    // its flags (PictureTransform).
    auto readPicture = [&in](PictureTransform& picture) {
        in.floats(picture.m, 6);
        picture.repsU = in.value<float>();
        picture.repsV = in.value<float>();
        in.floats(picture.border, 3);
        picture.flags = in.value<uint32_t>();
    };
    std::vector<DistantLight> lights(in.value<uint32_t>());
    for (DistantLight& light : lights) {
        in.floats(light.direction, 3);
        in.floats(light.radiance, 3);
        light.angularExtentDegrees = in.value<float>();
        // Bit 1: seen by the camera; bits 3 to 5 (form S): hidden from diffuse light, reflections, refractions.
        const uint32_t seen = in.value<uint32_t>();
        light.visibleInCamera = (seen & 1u) != 0;
        light.hiddenFrom = (seen >> 2) & 7u;
        in.floats(light.axisX, 3);
        in.floats(light.axisY, 3);
        light.texture = image(in.value<int32_t>());
        in.floats(light.seenRadiance, 3);
        light.seenExtentDegrees = in.value<float>();
        readPicture(light.picture);
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
        // Bit 1: seen by the camera. Bit 2: a mesh light that is no surface of the scene (a Modo Mesh Light's shape).
        // Bits 3 to 5 (form S): hidden from diffuse light, reflections, refractions.
        const uint32_t seen = in.value<uint32_t>();
        light.visibleInCamera = (seen & 1u) != 0;
        light.alone = (seen & 2u) != 0;
        light.hiddenFrom = (seen >> 2) & 7u;
        readPicture(light.picture);
        lightFilters[l].resize(in.value<uint32_t>());
        for (LightFilter& filter : lightFilters[l]) {
            const uint32_t filterKind = in.value<uint32_t>();
            if (filterKind > LightFilter::Group) throw std::runtime_error("MoonLightIPR scene has an unknown light filter");
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
            std::vector<float> positions, normals, closePositions, restPositions, cornerKeys;
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
                // Its rest positions (form 'c'), for glitter in reference space.
                restPositions = in.array<float>(flags & MESH_HAS_REST ? size_t(vertexCount) * 3 : 0);
                // Its corners' normals as given (form 'e'): a displaced mesh's hard edges (hardEdgeVertices).
                cornerKeys = in.array<float>(flags & MESH_HARD_EDGES ? size_t(triangleCount) * 9 : 0);
            }
            // A displaced mesh: how often to split it, the material its instances give it, and each displacing
            // material's program (form 'L').
            uint32_t splits = 0, displacedMaterial = 0;
            // Split by its distance from the camera (form 'T', the splits' top bit): the camera in the mesh's own
            // space, the angle an edge may span from it, and the most triangles (splitByDistance).
            bool byDistance = false;
            float camera[3] = {0, 0, 0}, angle = 0.0f;
            uint32_t budget = 0;
            std::vector<std::pair<uint32_t, std::vector<DisplacementStep>>> programs;
            if (flags & MESH_DISPLACE) {
                splits = in.value<uint32_t>();
                if (splits & 0x80000000u) {
                    byDistance = true;
                    splits &= 0xffu;
                    for (float& value : camera) value = in.value<float>();
                    angle = in.value<float>();
                    budget = in.value<uint32_t>();
                    if (!(angle > 0.0f) || !std::isfinite(angle) || budget == 0 || budget > 50000000u)
                        throw std::runtime_error("MoonLightIPR scene's distance split is out of range");
                }
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
            // A mesh the session splits takes its own points as its rest (they are not split with it).
            if (flags & MESH_DISPLACE) restPositions.clear();
            if (cached == meshes.end() && (flags & MESH_DISPLACE)) {
                // Split finer, so that the displacement has vertices to move; moved once the materials are set.
                const std::vector<uint32_t> coarse = closePositions.empty() || byDistance ? std::vector<uint32_t>() : indices;
                // The corners' normals as given split with the triangles, as two more coordinate sets (x y, then z).
                const size_t ownSets = uvSets.size();
                if (!cornerKeys.empty()) {
                    std::vector<float> xy(size_t(triangleCount) * 6), z(size_t(triangleCount) * 6, 0.0f);
                    for (size_t corner = 0; corner < size_t(triangleCount) * 3; ++corner) {
                        xy[corner * 2] = cornerKeys[corner * 3];
                        xy[corner * 2 + 1] = cornerKeys[corner * 3 + 1];
                        z[corner * 2] = cornerKeys[corner * 3 + 2];
                    }
                    uvSets.push_back(std::move(xy));
                    uvSets.push_back(std::move(z));
                }
                Triangles fine = byDistance
                    ? splitByDistance(Triangles{std::move(positions), std::move(indices), std::move(materialIds), std::move(uvSets)}, closePositions,
                                      camera, angle, splits, budget)
                    : split(Triangles{std::move(positions), std::move(indices), std::move(materialIds), std::move(uvSets)}, splits);
                positions = std::move(fine.positions);
                indices = std::move(fine.indices);
                materialIds = std::move(fine.materialIds);
                uvSets = std::move(fine.uvSets);
                vertexCount = uint32_t(positions.size() / 3);
                triangleCount = uint32_t(indices.size() / 3);
                if (!cornerKeys.empty() && uvSets.size() == ownSets + 2) {
                    const std::vector<float>& xy = uvSets[ownSets];
                    const std::vector<float>& z = uvSets[ownSets + 1];
                    cornerKeys.assign(size_t(triangleCount) * 9, 0.0f);
                    for (size_t corner = 0; corner < size_t(triangleCount) * 3; ++corner) {
                        cornerKeys[corner * 3] = xy[corner * 2];
                        cornerKeys[corner * 3 + 1] = xy[corner * 2 + 1];
                        cornerKeys[corner * 3 + 2] = z[corner * 2];
                    }
                    uvSets.resize(ownSets);
                } else {
                    cornerKeys.clear();
                }
                for (uint32_t index : indices)
                    if (index >= vertexCount) throw std::runtime_error("MoonLightIPR scene mesh index is out of range");
                normals = smoothNormals(positions, indices);
                // Where the mesh is as the shutter closes, split the same way: the splitting goes by the triangles
                // alone, so the vertices it makes match those above one for one.
                if (!closePositions.empty() && !byDistance) {
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
                // A displaced mesh's hard edges: drawn with its points split where its corners disagree as given, its
                // shading normals made over each side (hardEdgeVertices); displaced by its points, one each.
                std::vector<uint32_t> pointOf, drawn;
                if ((flags & MESH_DISPLACE) && (flags & MESH_SMOOTH)) hardEdgeVertices(indices, cornerKeys, vertexCount, pointOf, drawn);
                std::vector<float> drawnPositions, drawnNormals, drawnClosing;
                const bool split = !pointOf.empty();
                if (split) {
                    drawnPositions = atVertices(positions, pointOf);
                    drawnNormals = smoothNormals(drawnPositions, drawn);
                    if (!closePositions.empty()) drawnClosing = atVertices(closePositions, pointOf);
                }
                MeshDesc desc;
                desc.positions = split ? drawnPositions.data() : positions.data();
                desc.normals = split ? drawnNormals.data() : normals.empty() ? nullptr : normals.data();
                desc.vertexCount = split ? uint32_t(pointOf.size()) : vertexCount;
                desc.indices = split ? drawn.data() : indices.data();
                desc.materialIds = materialIds.empty() ? nullptr : materialIds.data();
                desc.triangleCount = triangleCount;
                desc.uvSets = uvPointers.data();
                desc.uvSetCount = uvPointers.size();
                desc.closePositions = closePositions.empty() ? nullptr : split ? drawnClosing.data() : closePositions.data();
                desc.restPositions = !split && restPositions.size() == size_t(vertexCount) * 3 ? restPositions.data() : nullptr;
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
                    held.pointOf = std::move(pointOf);
                    held.drawn = std::move(drawn);
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
        // The top bit (form 'c'): one of an instancer's placements, whose object space is its reference mesh's.
        instance.instanced = (instance.visibility & (1u << 31)) != 0;
        instance.visibility &= ~(1u << 31);
        instance.value = in.value<float>();
        in.floats(instance.transform, 12);
        if (sceneFlags & SCENE_MOTION) {
            in.floats(instance.closeTransform, 12);
            // And where it is at the frame (form 'U').
            in.floats(instance.frameTransform, 12);
            instance.framed = true;
            instance.frameMoment = frameMoment;
            instance.moves = !std::equal(instance.transform, instance.transform + 12, instance.closeTransform)
                             || !std::equal(instance.transform, instance.transform + 12, instance.frameTransform);
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
        if (const char* dump = std::getenv("MOONLIGHTIPR_DUMP_DISPLACE")) {
            // For tests: the displaced vertices, then the values the displacement pass found, as raw floats.
            if (FILE* out = std::fopen(dump, "wb")) {
                std::fwrite(held.positions.data(), sizeof(float), held.positions.size(), out);
                std::fwrite(values.data(), sizeof(float), values.size(), out);
                std::fclose(out);
            }
        }
        if (!held.pointOf.empty()) {
            // Split at its hard edges: each side's shading normals over its own triangles (hardEdgeVertices).
            const std::vector<float> drawnPositions = atVertices(held.positions, held.pointOf);
            const std::vector<float> drawnShading = smoothNormals(drawnPositions, held.drawn);
            const std::vector<float> drawnClosing = held.closing.empty() ? std::vector<float>() : atVertices(held.closing, held.pointOf);
            renderer.reshapeMesh(held.mesh, drawnPositions.data(), drawnShading.data(), drawnClosing.empty() ? nullptr : drawnClosing.data());
            continue;
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
        // Reflections and refractions that see what diffuse light sees are not built again (the usual case: every
        // environment visible to every ray).
        bool used[ENVIRONMENT_PARTS] = {true, true, !(parts[2] == parts[0]), !(parts[3] == parts[0])};
        int sized = -1;
        for (int p = 0; p < ENVIRONMENT_PARTS; ++p) {
            if (!used[p] || !parts[p].hasImage) continue;
            if (parts[p].key != environmentImageKey[p] || !environmentImage[p]) {
                // Another part showing the same image shares it.
                std::shared_ptr<std::vector<float>> shared;
                for (int q = 0; q < ENVIRONMENT_PARTS && !shared; ++q)
                    if (q != p && environmentImage[q] && environmentImageKey[q] == parts[p].key) {
                        shared = environmentImage[q];
                        environmentImageWidth[p] = environmentImageWidth[q];
                        environmentImageHeight[p] = environmentImageHeight[q];
                    }
                if (!shared) {
                    const Image image = readImage(parts[p].file);
                    if (!image.floatData || image.width < 2) throw std::runtime_error("MoonLightIPR environment image is not a float image");
                    shared = std::make_shared<std::vector<float>>(size_t(image.width) * image.height * 3);
                    // MoonRay puts the middle of the image behind the map's forward axis, so turn it half way round.
                    for (uint32_t y = 0; y < image.height; ++y)
                        for (uint32_t x = 0; x < image.width; ++x) {
                            const float* from = &image.floats[(size_t(y) * image.width + (x + image.width / 2) % image.width) * 4];
                            std::memcpy(&(*shared)[(size_t(y) * image.width + x) * 3], from, 3 * sizeof(float));
                        }
                    environmentImageWidth[p] = image.width;
                    environmentImageHeight[p] = image.height;
                }
                environmentImage[p] = shared;
                environmentImageKey[p] = parts[p].key;
            }
            // The packer makes every environment image the same size.
            if (sized >= 0 && (environmentImageWidth[p] != environmentImageWidth[sized] || environmentImageHeight[p] != environmentImageHeight[sized]))
                throw std::runtime_error("MoonLightIPR scene uses environment images of different sizes");
            if (sized < 0) sized = p;
        }
        // Images no part shows any more let their memory go.
        for (int p = 0; p < ENVIRONMENT_PARTS; ++p)
            if (!used[p] || !parts[p].hasImage) { environmentImage[p].reset(); environmentImageKey[p] = 0; }
        Environment environment;
        environment.width = sized >= 0 ? environmentImageWidth[sized] : 1;
        environment.height = sized >= 0 ? environmentImageHeight[sized] : rowCount;
        std::vector<float> pixels[ENVIRONMENT_PARTS];
        for (int p = 0; p < ENVIRONMENT_PARTS; ++p) {
            if (!used[p]) continue;
            pixels[p].resize(size_t(environment.width) * environment.height * 3);
            for (uint32_t y = 0; y < environment.height; ++y) {
                const float* row = &parts[p].rows[size_t(std::min<uint64_t>(uint64_t(y) * rowCount / environment.height, rowCount - 1)) * 3];
                for (uint32_t x = 0; x < environment.width; ++x) {
                    const size_t i = (size_t(y) * environment.width + x) * 3;
                    for (int c = 0; c < 3; ++c)
                        pixels[p][i + c] = row[c] + (parts[p].hasImage ? (*environmentImage[p])[i + c] * parts[p].scale : 0.0f);
                }
            }
        }
        environment.pixels = pixels[0].data();
        environment.background = pixels[1].data();
        std::copy(parts[0].rotation, parts[0].rotation + 9, environment.rotation);
        std::copy(parts[1].rotation, parts[1].rotation + 9, environment.backgroundRotation);
        if (used[2]) {
            environment.reflected = pixels[2].data();
            std::copy(parts[2].rotation, parts[2].rotation + 9, environment.reflectedRotation);
        }
        if (used[3]) {
            environment.through = pixels[3].data();
            std::copy(parts[3].rotation, parts[3].rotation + 9, environment.throughRotation);
        }
        renderer.setEnvironment(environment);
        environmentHash = environmentNow;
    }
    renderer.setMaxDepth(maxDepth, maxDiffuseDepth, maxGlossyDepth, maxVolumeDepth, (sceneFlags & SCENE_PRESENCE_SHADOWS) != 0);
    renderer.setSampleClamp(sampleClamp, sampleClampDepth);
    renderer.setRoughnessClamp(roughnessClamp);
    renderer.setMaxSubsurface(maxSubsurface);
    renderer.setVolumeScattering(volumeFactors[0], volumeFactors[1], volumeFactors[2]);
    if (settings.width != renderer.width() || settings.height != renderer.height()) renderer.resize(settings.width, settings.height);
    renderer.setCamera(camera);
    renderer.setCameraMotion(sceneFlags & SCENE_MOTION ? &cameraClose : nullptr);
    return settings;
}

}
