// A whole mesh out of Modo in one call, for scenes too heavy to be read a polygon at a time from Python.
// Python hands over the mesh it already holds; what comes back, in a file, is its points, its surface polygons with
// their material tags, and for every corner the value of each UV map and of the first vertex normal map.
// Read-only. Runs on Modo's main thread, where Python called it.
#include <lx_mesh.hpp>
#include <lx_visitor.hpp>
#include <lx_value.hpp>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct MapList : public CLxImpl_AbstractVisitor {
    CLxUser_MeshMap* maps = nullptr;
    std::map<std::string, LXtMeshMapID> found;      // by name, which is the order Python takes them in
    LxResult Evaluate() override {
        const char* name = nullptr;
        if (LXx_OK(maps->Name(&name))) found.emplace(name ? name : "", maps->ID());
        return LXe_OK;
    }
};
std::map<std::string, LXtMeshMapID> mapsOf(CLxUser_Mesh& mesh, LXtID4 type) {
    CLxUser_MeshMap maps;
    MapList list;
    if (!mesh.GetMaps(maps)) return list.found;
    maps.FilterByType(type);
    list.maps = &maps;
    maps.Enum(&list);
    return list.found;
}
template <class T> void put(std::ofstream& out, const std::vector<T>& values) {
    if (!values.empty()) out.write(reinterpret_cast<const char*>(values.data()), std::streamsize(values.size() * sizeof(T)));
}
void put(std::ofstream& out, std::int32_t value) { out.write(reinterpret_cast<const char*>(&value), sizeof(value)); }
void put(std::ofstream& out, const std::string& text) { put(out, std::int32_t(text.size())); out.write(text.data(), std::streamsize(text.size())); }
bool surface(LXtID4 type) {
    return type != LXxID4('C','U','R','V') && type != LXxID4('B','E','Z','R') && type != LXxID4('B','S','P','L') &&
           type != LXxID4('L','I','N','E') && type != LXxID4('O','P','N','T');
}

void write(void* object, const char* path) {
    CLxUser_Mesh mesh;
    mesh.set(static_cast<ILxUnknownID>(object));
    if (!mesh.test()) throw std::runtime_error("Not a mesh");
    CLxUser_Point points, lookup;
    CLxUser_Polygon polygons;
    if (!mesh.GetPoints(points) || !mesh.GetPoints(lookup) || !mesh.GetPolygons(polygons)) throw std::runtime_error("Mesh accessors unavailable");
    const int pointCount = mesh.NPoints(), polygonCount = mesh.NPolygons();

    std::vector<float> positions(size_t(pointCount) * 3);
    for (int i = 0; i < pointCount; ++i) {
        LXtFVector position;
        if (LXx_FAIL(points.SelectByIndex(i)) || LXx_FAIL(points.Pos(position))) throw std::runtime_error("Point unavailable");
        for (int k = 0; k < 3; ++k) positions[size_t(i) * 3 + k] = position[k];
    }

    const auto uvMaps = mapsOf(mesh, LXi_VMAP_TEXTUREUV);
    const auto normalMaps = mapsOf(mesh, LXi_VMAP_NORMAL);
    const bool hasNormal = !normalMaps.empty();
    const LXtMeshMapID normalMap = hasNormal ? normalMaps.begin()->second : nullptr;

    std::vector<std::int32_t> counts, tags, indices;
    std::vector<std::uint8_t> subdivided;
    std::vector<std::vector<std::uint8_t>> uvValid(uvMaps.size());
    std::vector<std::vector<float>> uvValues(uvMaps.size());
    std::vector<std::uint8_t> normalValid;
    std::vector<float> normalValues;
    std::map<std::string, std::int32_t> tagIndex;
    std::vector<std::string> tagNames;
    std::int32_t lines = 0, small = 0;
    CLxLoc_StringTag tag;
    std::vector<LXtPointID> corners;

    for (int i = 0; i < polygonCount; ++i) {
        if (LXx_FAIL(polygons.SelectByIndex(i))) throw std::runtime_error("Polygon unavailable");
        LXtID4 type = 0;
        unsigned count = 0;
        polygons.Type(&type);
        if (!surface(type)) { ++lines; continue; }
        polygons.VertexCount(&count);
        if (count < 3) { ++small; continue; }
        corners.resize(count);
        for (unsigned k = 0; k < count; ++k) {
            unsigned index = 0;
            if (LXx_FAIL(polygons.VertexByIndex(k, &corners[k])) || LXx_FAIL(lookup.Select(corners[k])) || LXx_FAIL(lookup.Index(&index)))
                throw std::runtime_error("Polygon corner unavailable");
            indices.push_back(std::int32_t(index));
        }
        const char* name = nullptr;
        tag.set(polygons);
        std::string material = (tag.test() && LXx_OK(tag.Get(LXi_POLYTAG_MATERIAL, &name)) && name) ? name : "";
        auto held = tagIndex.find(material);
        if (held == tagIndex.end()) { held = tagIndex.emplace(material, std::int32_t(tagNames.size())).first; tagNames.push_back(material); }
        counts.push_back(std::int32_t(count));
        tags.push_back(held->second);
        subdivided.push_back(type == LXiPTYP_SUBD || type == LXiPTYP_PSUB);
        size_t which = 0;
        for (const auto& entry : uvMaps) {
            // A corner without a value leaves the map without one for the whole polygon, as the Python reader has it.
            bool valid = true;
            for (unsigned k = 0; k < count; ++k) {
                float value[2] = {0.0f, 0.0f};
                if (polygons.MapEvaluate(entry.second, corners[k], value) != LXe_OK) valid = false;
                uvValues[which].push_back(value[0]);
                uvValues[which].push_back(value[1]);
            }
            uvValid[which++].push_back(valid);
        }
        if (hasNormal) {
            bool valid = true;
            for (unsigned k = 0; k < count; ++k) {
                float value[3] = {0.0f, 0.0f, 0.0f};
                if (polygons.MapEvaluate(normalMap, corners[k], value) != LXe_OK) valid = false;
                for (float v : value) normalValues.push_back(v);
            }
            normalValid.push_back(valid);
        }
    }

    std::ofstream out(std::filesystem::u8path(path), std::ios::binary | std::ios::trunc);
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.write("MRM1", 4);
    for (std::int32_t value : {std::int32_t(pointCount), std::int32_t(counts.size()), std::int32_t(indices.size()), std::int32_t(uvMaps.size()),
                               std::int32_t(hasNormal), std::int32_t(tagNames.size()), lines, small}) put(out, value);
    put(out, positions);
    put(out, counts);
    put(out, tags);
    put(out, subdivided);
    put(out, indices);
    size_t which = 0;
    for (const auto& entry : uvMaps) {
        put(out, entry.first);
        put(out, uvValid[which]);
        put(out, uvValues[which++]);
    }
    if (hasNormal) { put(out, normalValid); put(out, normalValues); }
    for (const auto& name : tagNames) put(out, name);
    out.close();
}
}

// object is the address of the lx.object.Mesh Python holds. Returns null, or what went wrong.
extern "C" __declspec(dllexport) const char* MR_mesh_file(void* object, const char* path) {
    static thread_local std::string error;
    try {
        if (!object || !path || !*path) throw std::runtime_error("Missing mesh or output path");
        write(object, path);
        return nullptr;
    } catch (const std::exception& failure) { error = failure.what(); }
      catch (...) { error = "Unknown mesh reader error"; }
    return error.c_str();
}
