// An edited mesh's surfaces read straight from the mesh, as Modo's render cache would give them, for the kit's
// geometry cache (geometry_cache.py): a surface for each material and part tag, its polygons cut by Modo's own
// triangulation (ILxPolygon::GenerateTriangles), every corner with its point, Modo's own normal of the point for that
// polygon (ILxPoint::Normal: the render cache's, to a hundredth of a degree on a tester's cars) and the value of every
// UV map there (MapEvaluate). Reading one mesh this way leaves out the render cache's evaluation of the whole scene.
// Refused ("!" and why) for what the render cache makes something else of: subdivision surfaces, curves, points.
// Read-only. Runs on Modo's main thread, where Python called it.
#include <lx_mesh.hpp>
#include <lx_visitor.hpp>
#include <lx_value.hpp>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <algorithm>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
struct Walk : public CLxImpl_AbstractVisitor {
    std::function<void()> step;
    explicit Walk(std::function<void()> f) : step(std::move(f)) {}
    LxResult Evaluate() override { step(); return LXe_OK; }
};

struct UvMaps : public CLxImpl_AbstractVisitor {
    CLxUser_MeshMap* maps = nullptr;
    std::vector<std::pair<std::string, LXtMeshMapID>> found;   // in Modo's order
    LxResult Evaluate() override {
        const char* name = nullptr;
        maps->Name(&name);
        found.emplace_back(name ? name : "", maps->ID());
        return LXe_OK;
    }
};

struct Surface {
    std::vector<float> positions, normals;
    std::vector<std::vector<float>> uvs;
};

template <class T> void put(std::ofstream& out, const std::vector<T>& values) {
    if (!values.empty()) out.write(reinterpret_cast<const char*>(values.data()), std::streamsize(values.size() * sizeof(T)));
}
void put(std::ofstream& out, std::int32_t value) { out.write(reinterpret_cast<const char*>(&value), sizeof(value)); }
void put(std::ofstream& out, const std::string& text) { put(out, std::int32_t(text.size())); out.write(text.data(), std::streamsize(text.size())); }

void write(void* object, const char* path, bool byPart) {
    CLxUser_Mesh mesh;
    mesh.set(static_cast<ILxUnknownID>(object));
    if (!mesh.test()) throw std::runtime_error("Not a mesh");
    CLxUser_Point point;
    CLxUser_Polygon polygons;
    CLxUser_MeshMap maps;
    if (!mesh.GetPoints(point) || !mesh.GetPolygons(polygons) || !mesh.GetMaps(maps)) throw std::runtime_error("Mesh accessors unavailable");
    UvMaps list;
    list.maps = &maps;
    maps.FilterByType(LXi_VMAP_TEXTUREUV);
    maps.Enum(&list);
    // In the render cache's order: by name (a tester's tyre's Texture, TireSidewall and Laufflaeche came Laufflaeche,
    // Texture, TireSidewall).
    std::sort(list.found.begin(), list.found.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
    const size_t uvCount = list.found.size();
    std::map<std::pair<std::string, std::string>, Surface> surfaces;
    std::vector<std::pair<std::string, std::string>> order;
    CLxLoc_StringTag tags;
    const char* failed = nullptr;   // nothing is thrown inside Modo's walk
    Walk walk([&]() {
        if (failed) return;
        LXtID4 type = 0;
        polygons.Type(&type);
        if (type != LXiPTYP_FACE) { failed = type == LXiPTYP_SUBD || type == LXiPTYP_PSUB ? "subdivision surface" : "not a face"; return; }
        tags.set(polygons);
        const char* material = nullptr;
        const char* part = nullptr;
        if (!tags.test() || LXx_FAIL(tags.Get(LXi_POLYTAG_MATERIAL, &material))) material = nullptr;
        if (!byPart || !tags.test() || LXx_FAIL(tags.Get(LXi_POLYTAG_PART, &part))) part = nullptr;
        const auto key = std::make_pair(std::string(material ? material : ""), std::string(part ? part : ""));
        auto found = surfaces.find(key);
        if (found == surfaces.end()) {
            found = surfaces.emplace(key, Surface{}).first;
            found->second.uvs.resize(uvCount);
            order.push_back(key);
        }
        Surface& surface = found->second;
        unsigned triangles = 0;
        if (LXx_FAIL(polygons.GenerateTriangles(&triangles))) { failed = "no triangles"; return; }
        const LXtPolygonID id = polygons.ID();
        for (unsigned t = 0; t < triangles; ++t) {
            LXtPointID corners[3] = {nullptr, nullptr, nullptr};
            if (LXx_FAIL(polygons.TriangleByIndex(t, &corners[0], &corners[1], &corners[2]))) { failed = "triangle unavailable"; return; }
            for (LXtPointID corner : corners) {
                LXtFVector position;
                LXtVector normal = {0, 0, 0};
                if (LXx_FAIL(point.Select(corner)) || LXx_FAIL(point.Pos(position)) || LXx_FAIL(point.Normal(id, normal))) {
                    failed = "corner unavailable";
                    return;
                }
                for (int k = 0; k < 3; ++k) surface.positions.push_back(position[k]);
                for (int k = 0; k < 3; ++k) surface.normals.push_back(float(normal[k]));
                for (size_t u = 0; u < uvCount; ++u) {
                    float value[2] = {0.0f, 0.0f};
                    // A corner without a value is 0, as the render cache gives it (a tester's tyres, exactly).
                    polygons.MapEvaluate(list.found[u].second, corner, value);
                    surface.uvs[u].push_back(value[0]);
                    surface.uvs[u].push_back(value[1]);
                }
            }
        }
    });
    polygons.Enum(&walk);
    if (failed) throw std::runtime_error(failed);
    std::ofstream out(std::filesystem::u8path(path), std::ios::binary | std::ios::trunc);
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.write("MRS1", 4);
    put(out, std::int32_t(uvCount));
    for (const auto& entry : list.found) put(out, entry.first);
    put(out, std::int32_t(order.size()));
    for (const auto& key : order) {
        const Surface& surface = surfaces[key];
        put(out, key.first);
        put(out, key.second);
        put(out, std::int32_t(surface.positions.size() / 3));
        put(out, surface.positions);
        put(out, surface.normals);
        for (const auto& values : surface.uvs) put(out, values);
    }
    out.close();
}
}

// object is the address of the lx.object.Mesh Python holds. by_part: a surface for each part as well as each material,
// as the render cache cuts a mesh where the Shader Tree has a part mask (the kit goes by how the render cache cut the
// same mesh before); else the part is left empty, as it gives it. Returns null, or what went wrong.
extern "C" __declspec(dllexport) const char* MR_mesh_surfaces(void* object, const char* path, int by_part) {
    static thread_local std::string error;
    try {
        if (!object || !path || !*path) throw std::runtime_error("Missing mesh or output path");
        write(object, path, by_part != 0);
        return nullptr;
    } catch (const std::exception& failure) { error = failure.what(); }
      catch (...) { error = "Unknown mesh surfaces error"; }
    return error.c_str();
}
