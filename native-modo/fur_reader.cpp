// A mesh's fur surface out of Modo in one call, for extra_geometry.fur_entries: what it read from Python a polygon and a
// point at a time (a minute on a heavy pelt, Modo's thread held throughout). The same reading in the same order: the
// surface polygons of the fur's material cut into triangles as a fan from each polygon's first corner, each point's
// normal the sum of its polygons' Newell normals made unit, the material of each triangle, the weight maps and the
// vector map the Fur material names (a point without a value has 0), and the guide curves (extra_geometry.fur_guides).
// Read-only. Runs on Modo's main thread, where Python called it.
//
// The request is lines of a key, a tab and a value: "wanted" (the material tag the fur is on; empty for all),
// "surface" (1 to read the surface; 0 for guides alone), "weight" (a weight map's name, once for each, in order),
// "vector" (the vector map's name), "guides" (1 to read the mesh's curves as guides), "guidetag" and "guidekind"
// (MATR, PART or PICK: the tag the guides are chosen by; without one, the curves wearing "wanted").
// The file is "MFS1"; the number of triangles; for each, its corners and their normals (18 doubles); the number of
// material names and each name (a 32-bit length and its bytes); each triangle's material by its place among them;
// for each weight map asked, 1 and three doubles a triangle where it was found, else 0; the same for the vector map,
// with nine doubles a triangle; the number of guides and for each its number of points and its points (doubles).
#include <lx_mesh.hpp>
#include <lx_value.hpp>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void put(std::ofstream& out, std::int32_t value) { out.write(reinterpret_cast<const char*>(&value), sizeof(value)); }
void put(std::ofstream& out, const std::string& text) { put(out, std::int32_t(text.size())); out.write(text.data(), std::streamsize(text.size())); }
void put(std::ofstream& out, const std::vector<double>& values) {
    if (!values.empty()) out.write(reinterpret_cast<const char*>(values.data()), std::streamsize(values.size() * sizeof(double)));
}

std::string tagOf(CLxLoc_StringTag& tag, LXtID4 kind) {
    const char* name = nullptr;
    return (tag.test() && LXx_OK(tag.Get(kind, &name)) && name) ? name : "";
}

void read(void* object, const char* request, const char* path) {
    CLxUser_Mesh mesh;
    mesh.set(static_cast<ILxUnknownID>(object));
    if (!mesh.test()) throw std::runtime_error("Not a mesh");
    std::string wanted, vectorName, guideTag;
    LXtID4 guideKind = LXi_POLYTAG_MATERIAL;
    bool surfaceWanted = true, guidesWanted = false;
    std::vector<std::string> weightNames;
    std::istringstream lines(request ? request : "");
    for (std::string line; std::getline(lines, line);) {
        const size_t tab = line.find('\t');
        if (tab == std::string::npos) continue;
        const std::string key = line.substr(0, tab), value = line.substr(tab + 1);
        if (key == "wanted") wanted = value;
        else if (key == "surface") surfaceWanted = value == "1";
        else if (key == "weight") weightNames.push_back(value);
        else if (key == "vector") vectorName = value;
        else if (key == "guides") guidesWanted = value == "1";
        else if (key == "guidetag") guideTag = value;
        else if (key == "guidekind") guideKind = value == "PART" ? LXi_POLYTAG_PART : value == "PICK" ? LXi_POLYTAG_PICK : LXi_POLYTAG_MATERIAL;
    }
    CLxUser_Point points;
    CLxUser_Polygon polygons;
    if (!mesh.GetPoints(points) || !mesh.GetPolygons(polygons)) throw std::runtime_error("Mesh accessors unavailable");
    CLxLoc_StringTag tag;
    auto position = [&](LXtPointID point) {
        LXtFVector at;
        if (LXx_FAIL(points.Select(point)) || LXx_FAIL(points.Pos(at))) throw std::runtime_error("Point unavailable");
        return std::vector<double>{double(at[0]), double(at[1]), double(at[2])};
    };

    // The surface: its polygons of the fur's material, each as its corners and its material.
    std::map<LXtPointID, size_t> place;              // each point's place among the points read, in the order met
    std::vector<std::vector<double>> places;
    std::vector<LXtPointID> pointsOf;
    std::vector<std::vector<size_t>> faces;
    std::vector<std::int32_t> faceTags;
    std::map<std::string, std::int32_t> tagIndex;
    std::vector<std::string> tagNames;
    std::vector<std::vector<std::vector<double>>> guides;
    const int polygonCount = mesh.NPolygons();
    for (int i = 0; i < polygonCount; ++i) {
        if (LXx_FAIL(polygons.SelectByIndex(i))) throw std::runtime_error("Polygon unavailable");
        LXtID4 type = 0;
        unsigned count = 0;
        polygons.Type(&type);
        polygons.VertexCount(&count);
        tag.set(polygons);
        if (guidesWanted && type == LXiPTYP_LINE && count >= 2) {
            // A guide: a curve of the chosen tag, or wearing the fur's material where no tag is chosen.
            bool keep;
            if (!guideTag.empty()) {
                const std::string value = tagOf(tag, guideKind);
                if (guideKind == LXi_POLYTAG_PICK) {
                    keep = false;
                    std::istringstream sets(value);
                    for (std::string one; std::getline(sets, one, ';');) if (one == guideTag) keep = true;
                } else keep = value == guideTag;
            } else keep = wanted.empty() || tagOf(tag, LXi_POLYTAG_MATERIAL) == wanted;
            if (keep) {
                std::vector<std::vector<double>> strand;
                for (unsigned k = 0; k < count; ++k) {
                    LXtPointID point = nullptr;
                    if (LXx_FAIL(polygons.VertexByIndex(k, &point))) throw std::runtime_error("Curve point unavailable");
                    strand.push_back(position(point));
                }
                guides.push_back(std::move(strand));
            }
            continue;
        }
        if (!surfaceWanted) continue;
        if ((type != LXiPTYP_FACE && type != LXiPTYP_SUBD && type != LXiPTYP_PSUB) || count < 3) continue;
        const std::string material = tagOf(tag, LXi_POLYTAG_MATERIAL);
        if (!wanted.empty() && material != wanted) continue;
        std::vector<size_t> corners;
        for (unsigned k = 0; k < count; ++k) {
            LXtPointID point = nullptr;
            if (LXx_FAIL(polygons.VertexByIndex(k, &point))) throw std::runtime_error("Polygon corner unavailable");
            auto held = place.find(point);
            if (held == place.end()) {
                held = place.emplace(point, places.size()).first;
                places.push_back(position(point));
                pointsOf.push_back(point);
            }
            corners.push_back(held->second);
        }
        auto named = tagIndex.find(material);
        if (named == tagIndex.end()) { named = tagIndex.emplace(material, std::int32_t(tagNames.size())).first; tagNames.push_back(material); }
        faces.push_back(std::move(corners));
        faceTags.push_back(named->second);
    }

    // Each point's normal: its polygons' Newell normals summed, a polygon once for each of its corners there.
    std::vector<double> normals(places.size() * 3, 0.0);
    for (const auto& corners : faces) {
        double x = 0, y = 0, z = 0;
        for (size_t k = 0; k < corners.size(); ++k) {
            const auto& a = places[corners[k]];
            const auto& b = places[corners[(k + 1) % corners.size()]];
            x += (a[1] - b[1]) * (a[2] + b[2]); y += (a[2] - b[2]) * (a[0] + b[0]); z += (a[0] - b[0]) * (a[1] + b[1]);
        }
        for (size_t point : corners) { normals[point * 3] += x; normals[point * 3 + 1] += y; normals[point * 3 + 2] += z; }
    }
    for (size_t p = 0; p < places.size(); ++p) {
        double size = std::sqrt(normals[p * 3] * normals[p * 3] + normals[p * 3 + 1] * normals[p * 3 + 1] + normals[p * 3 + 2] * normals[p * 3 + 2]);
        if (size == 0.0) size = 1.0;
        for (int k = 0; k < 3; ++k) normals[p * 3 + k] /= size;
    }

    // The triangles, and each one's material.
    std::vector<double> triangles;
    std::vector<std::int32_t> worn;
    std::vector<std::array<size_t, 3>> trios;
    for (size_t f = 0; f < faces.size(); ++f) {
        const auto& c = faces[f];
        for (size_t k = 1; k + 1 < c.size(); ++k) {
            trios.push_back({c[0], c[k], c[k + 1]});
            worn.push_back(faceTags[f]);
        }
    }
    for (const auto& t : trios) {
        for (size_t corner : t) for (int k = 0; k < 3; ++k) triangles.push_back(places[corner][k]);
        for (size_t corner : t) for (int k = 0; k < 3; ++k) triangles.push_back(normals[corner * 3 + k]);
    }

    // A point map's values at every triangle's corners (width values each), or nothing where the map is not found.
    CLxUser_MeshMap maps;
    const bool haveMaps = mesh.GetMaps(maps);
    auto cornersOf = [&](LXtID4 type, const std::string& name, int width, std::vector<double>& out) {
        if (!haveMaps || LXx_FAIL(maps.SelectByName(type, name.c_str()))) return false;
        const LXtMeshMapID id = maps.ID();
        std::vector<double> values(places.size() * size_t(width), 0.0);
        for (size_t p = 0; p < places.size(); ++p) {
            float value[3] = {0.0f, 0.0f, 0.0f};
            if (LXx_FAIL(points.Select(pointsOf[p]))) throw std::runtime_error("Point unavailable");
            if (LXx_OK(points.MapEvaluate(id, value))) for (int k = 0; k < width; ++k) values[p * size_t(width) + k] = double(value[k]);
        }
        for (const auto& t : trios) for (size_t corner : t) for (int k = 0; k < width; ++k) out.push_back(values[corner * size_t(width) + k]);
        return true;
    };

    std::ofstream out(std::filesystem::u8path(path), std::ios::binary | std::ios::trunc);
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.write("MFS1", 4);
    put(out, std::int32_t(trios.size()));
    put(out, triangles);
    put(out, std::int32_t(tagNames.size()));
    for (const auto& name : tagNames) put(out, name);
    if (!worn.empty()) out.write(reinterpret_cast<const char*>(worn.data()), std::streamsize(worn.size() * sizeof(std::int32_t)));
    for (const auto& name : weightNames) {
        std::vector<double> values;
        const bool found = cornersOf(LXi_VMAP_WEIGHT, name, 1, values);
        put(out, std::int32_t(found));
        if (found) put(out, values);
    }
    {
        std::vector<double> values;
        const bool found = !vectorName.empty() && cornersOf(LXi_VMAP_VECTOR, vectorName, 3, values);
        put(out, std::int32_t(found));
        if (found) put(out, values);
    }
    put(out, std::int32_t(guides.size()));
    for (const auto& strand : guides) {
        put(out, std::int32_t(strand.size()));
        for (const auto& p : strand) out.write(reinterpret_cast<const char*>(p.data()), std::streamsize(3 * sizeof(double)));
    }
    out.close();
}

}  // namespace

// object is the address of the lx.object.Mesh Python holds. Returns null, or what went wrong.
extern "C" __declspec(dllexport) const char* MR_fur_surface(void* object, const char* request, const char* path) {
    static thread_local std::string error;
    try {
        if (!object || !path || !*path) throw std::runtime_error("Missing mesh or output path");
        read(object, request, path);
        return nullptr;
    } catch (const std::exception& failure) { error = failure.what(); }
      catch (...) { error = "Unknown fur reader error"; }
    return error.c_str();
}
