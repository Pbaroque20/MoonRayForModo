// vertex_maps.read for the plugin's Python, in one call: a mesh's weight, RGB and RGBA maps, each at every point, or
// at every corner of every surface polygon where it holds values set apart on some polygon (Modo's discontinuous
// values). Python asked Modo a point, and a corner, at a time (seconds a map on a heavy mesh, Modo's thread held).
// The same maps in the same order (by name, then kind, then ID), the same test for values set apart (the map's
// discontinuous values enumerated), a point or corner without a value 0; an RGBA map a colour and, as name_alpha, a
// number. Read-only. Runs on Modo's main thread, where Python called it.
//
// The file is "MVM1"; the number of points; the number of surface polygons and each one's number of corners (32-bit); the number of entries;
// for each its name (a 32-bit length and its bytes), its kind (0 a number, 1 a colour), its size (1 or 3), whether it is
// by corner (1) or by point (0), and its values as 32-bit floats: size a point, or size a corner of each surface polygon.
#include <lx_mesh.hpp>
#include <lx_visitor.hpp>
#include <lx_value.hpp>
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {

void put(std::ofstream& out, std::int32_t value) { out.write(reinterpret_cast<const char*>(&value), sizeof(value)); }
void put(std::ofstream& out, const std::string& text) { put(out, std::int32_t(text.size())); out.write(text.data(), std::streamsize(text.size())); }
void put(std::ofstream& out, const std::vector<float>& values) {
    if (!values.empty()) out.write(reinterpret_cast<const char*>(values.data()), std::streamsize(values.size() * sizeof(float)));
}

struct Listed : public CLxImpl_AbstractVisitor {
    CLxUser_MeshMap* maps = nullptr;
    std::vector<std::tuple<std::string, LXtID4, LXtMeshMapID>> found;
    LxResult Evaluate() override {
        LXtID4 type = 0;
        if (LXx_FAIL(maps->Type(&type))) return LXe_OK;
        if (type == LXi_VMAP_WEIGHT || type == LXi_VMAP_RGB || type == LXi_VMAP_RGBA) {
            const char* name = nullptr;
            maps->Name(&name);
            found.emplace_back(name ? name : "", type, maps->ID());
        }
        return LXe_OK;
    }
};

struct Any : public CLxImpl_AbstractVisitor {
    bool seen = false;
    LxResult Evaluate() override { seen = true; return LXe_ABORT; }
};

bool surface(LXtID4 type) {
    return type != LXxID4('C','U','R','V') && type != LXxID4('B','E','Z','R') && type != LXxID4('B','S','P','L') &&
           type != LXxID4('L','I','N','E') && type != LXxID4('O','P','N','T');
}

void write(void* object, const char* path) {
    CLxUser_Mesh mesh;
    mesh.set(static_cast<ILxUnknownID>(object));
    if (!mesh.test()) throw std::runtime_error("Not a mesh");
    CLxUser_Point points;
    CLxUser_Polygon polygons;
    CLxUser_MeshMap maps;
    if (!mesh.GetPoints(points) || !mesh.GetPolygons(polygons) || !mesh.GetMaps(maps)) throw std::runtime_error("Mesh accessors unavailable");
    Listed listed;
    listed.maps = &maps;
    maps.Enum(&listed);
    // As Python's sorted() orders (name, type, ID).
    std::sort(listed.found.begin(), listed.found.end(), [](const auto& a, const auto& b) {
        if (std::get<0>(a) != std::get<0>(b)) return std::get<0>(a) < std::get<0>(b);
        if (std::get<1>(a) != std::get<1>(b)) return std::get<1>(a) < std::get<1>(b);
        return reinterpret_cast<std::uintptr_t>(std::get<2>(a)) < reinterpret_cast<std::uintptr_t>(std::get<2>(b));
    });
    const int pointCount = mesh.NPoints(), polygonCount = mesh.NPolygons();
    // The surface polygons, as the scene reader counts them: each one's corners.
    std::vector<std::int32_t> counts;
    std::vector<LXtPointID> corners;
    std::vector<LXtPolygonID> faces;
    for (int i = 0; i < polygonCount; ++i) {
        if (LXx_FAIL(polygons.SelectByIndex(i))) throw std::runtime_error("Polygon unavailable");
        LXtID4 type = 0;
        unsigned count = 0;
        polygons.Type(&type);
        if (!surface(type)) continue;
        polygons.VertexCount(&count);
        if (count < 3) continue;
        counts.push_back(std::int32_t(count));
        faces.push_back(polygons.ID());
        for (unsigned k = 0; k < count; ++k) {
            LXtPointID point = nullptr;
            if (LXx_FAIL(polygons.VertexByIndex(k, &point))) throw std::runtime_error("Polygon corner unavailable");
            corners.push_back(point);
        }
    }
    std::ofstream out(std::filesystem::u8path(path), std::ios::binary | std::ios::trunc);
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.write("MVM1", 4);
    put(out, std::int32_t(pointCount));
    put(out, std::int32_t(counts.size()));
    if (!counts.empty()) out.write(reinterpret_cast<const char*>(counts.data()), std::streamsize(counts.size() * sizeof(std::int32_t)));
    std::int32_t entries = 0;
    for (const auto& map : listed.found) entries += std::get<1>(map) == LXi_VMAP_RGBA ? 2 : 1;
    put(out, entries);
    CLxUser_Point walker;
    CLxUser_Polygon around;
    mesh.GetPoints(walker);
    mesh.GetPolygons(around);
    for (const auto& map : listed.found) {
        const std::string& name = std::get<0>(map);
        const LXtID4 type = std::get<1>(map);
        const LXtMeshMapID id = std::get<2>(map);
        const int size = type == LXi_VMAP_WEIGHT ? 1 : type == LXi_VMAP_RGB ? 3 : 4;
        maps.Select(id);
        Any any;
        maps.EnumContents(&any, walker, around);
        const bool apart = any.seen;
        std::vector<float> values;
        if (apart) {
            values.reserve(corners.size() * size_t(size));
            size_t at = 0;
            for (size_t f = 0; f < faces.size(); ++f) {
                polygons.Select(faces[f]);
                for (std::int32_t k = 0; k < counts[f]; ++k, ++at) {
                    float value[4] = {0, 0, 0, 0};
                    if (polygons.MapEvaluate(id, corners[at], value) != LXe_OK) value[0] = value[1] = value[2] = value[3] = 0;
                    values.insert(values.end(), value, value + size);
                }
            }
        } else {
            values.reserve(size_t(pointCount) * size_t(size));
            for (int p = 0; p < pointCount; ++p) {
                float value[4] = {0, 0, 0, 0};
                if (LXx_FAIL(points.SelectByIndex(p)) || points.MapEvaluate(id, value) != LXe_OK) value[0] = value[1] = value[2] = value[3] = 0;
                values.insert(values.end(), value, value + size);
            }
        }
        auto entry = [&](const std::string& called, int kind, int width, int offset) {
            put(out, called);
            put(out, std::int32_t(kind));
            put(out, std::int32_t(width));
            put(out, std::int32_t(apart));
            if (width == size) { put(out, values); return; }
            std::vector<float> part;
            part.reserve(values.size() / size_t(size) * size_t(width));
            for (size_t v = 0; v < values.size(); v += size_t(size))
                for (int k = 0; k < width; ++k) part.push_back(values[v + size_t(offset + k)]);
            put(out, part);
        };
        if (size == 4) { entry(name, 1, 3, 0); entry(name + "_alpha", 0, 1, 3); }
        else entry(name, size == 3 ? 1 : 0, size, 0);
    }
    out.close();
}

}  // namespace

// object is the address of the lx.object.Mesh Python holds. Returns null, or what went wrong.
extern "C" __declspec(dllexport) const char* MR_vertex_maps(void* object, const char* path) {
    static thread_local std::string error;
    try {
        if (!object || !path || !*path) throw std::runtime_error("Missing mesh or output path");
        write(object, path);
        return nullptr;
    } catch (const std::exception& failure) { error = failure.what(); }
      catch (...) { error = "Unknown vertex map reader error"; }
    return error.c_str();
}
