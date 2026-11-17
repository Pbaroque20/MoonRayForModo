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
#include <cmath>
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

struct Read {
    std::vector<std::string> uvNames;   // by name
    std::map<std::pair<std::string, std::string>, Surface> surfaces;
    std::vector<std::pair<std::string, std::string>> order;
};

void read(void* object, bool byPart, Read& made, bool ngons = true) {
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
    // By name; which of them the render cache gives in which order is learnt for each mesh (MR_mesh_matches).
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
        unsigned sides = 0;
        polygons.VertexCount(&sides);
        // Polygons of more than four corners, where refused: the render cache cut a few of a tester's otherwise
        // than Modo's triangulation gives them.
        if (!ngons && sides > 4) { failed = "a polygon of more than four corners"; return; }
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
    for (const auto& entry : list.found) made.uvNames.push_back(entry.first);
    made.surfaces = std::move(surfaces);
    made.order = std::move(order);
}

void write(void* object, const char* path, bool byPart, bool ngons) {
    Read made;
    read(object, byPart, made, ngons);
    const size_t uvCount = made.uvNames.size();
    std::ofstream out(std::filesystem::u8path(path), std::ios::binary | std::ios::trunc);
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.write("MRS1", 4);
    put(out, std::int32_t(uvCount));
    for (const auto& name : made.uvNames) put(out, name);
    put(out, std::int32_t(made.order.size()));
    for (const auto& key : made.order) {
        const Surface& surface = made.surfaces[key];
        put(out, key.first);
        put(out, key.second);
        put(out, std::int32_t(surface.positions.size() / 3));
        put(out, surface.positions);
        put(out, surface.normals);
        for (const auto& values : surface.uvs) put(out, values);
    }
    out.close();
}

// A triangle as a number: its three corners (point, normal, UVs, each to 1e-5) as numbers, in sorted order, mixed.
std::uint64_t mix(std::uint64_t h, std::int64_t v) {
    h ^= std::uint64_t(v) + 0x9E3779B97F4A7C15ull + (h << 6) + (h >> 2);
    return h * 0xFF51AFD7ED558CCDull;
}
std::int64_t q(float v) { return std::int64_t(std::llround(double(v) * 1e5)); }
std::uint64_t corner(const float* p, const float* n, const std::vector<const float*>& uvs, long long c) {
    std::uint64_t h = 0x84222325CBF29CE4ull;
    for (int k = 0; k < 3; ++k) h = mix(h, q(p[k]));
    for (int k = 0; k < 3; ++k) h = mix(h, n ? q(n[k]) : 0x7FFFFFFF);
    for (const float* uv : uvs) { h = mix(h, q(uv[2 * c])); h = mix(h, q(uv[2 * c + 1])); }
    return h;
}
std::uint64_t triangle(std::uint64_t a, std::uint64_t b, std::uint64_t c) {
    if (a > b) std::swap(a, b);
    if (b > c) std::swap(b, c);
    if (a > b) std::swap(a, b);
    return mix(mix(mix(0x1234567ull, std::int64_t(a)), std::int64_t(b)), std::int64_t(c));
}
}

// One segment of a surface as the render cache gave it (evaluated.capture's rows): its points, its faces' corners into
// them and the corners' counts, a normal and the value of each UV set at each corner.
struct MR_Segment {
    const char* material;
    const char* part;
    const float* vertices;
    long long vertexCount;
    const std::int32_t* corners;
    const std::int32_t* sizes;
    long long faceCount;
    const float* normals;        // null where it has none
    int uvCount;
    const float* const* uvs;
};

// Whether the mesh read directly (as MR_mesh_surfaces reads it) gives the very surfaces the render cache gave for it
// (segments), triangle for triangle, to 1e-5: 1 where it does, with order (room for the UV sets) saying which of the
// mesh's UV maps, by name, each UV set is; 0 where it does not; -1 where the mesh cannot be read so (subdivision
// surfaces, curves). For the geometry cache: a mesh that matched is read directly once it is edited.
extern "C" __declspec(dllexport) int MR_mesh_matches(void* object, int by_part, const MR_Segment* segments, int segmentCount, int* order) {
    try {
        Read made;
        read(object, (by_part & 1) != 0, made);
        const int uvCount = segmentCount ? segments[0].uvCount : 0;
        for (int s = 0; s < segmentCount; ++s) if (segments[s].uvCount != uvCount) return 0;
        const int maps = int(made.uvNames.size());
        if (uvCount > maps) return 0;
        // The render cache's triangles, by surface.
        std::map<std::pair<std::string, std::string>, std::vector<std::uint64_t>> theirs;
        for (int s = 0; s < segmentCount; ++s) {
            const MR_Segment& g = segments[s];
            auto& into = theirs[{g.material ? g.material : "", g.part ? g.part : ""}];
            std::vector<const float*> uvs(g.uvs, g.uvs + g.uvCount);
            long long c = 0;
            for (long long f = 0; f < g.faceCount; ++f) {
                if (g.sizes[f] != 3) return 0;
                std::uint64_t h[3];
                for (int k = 0; k < 3; ++k) {
                    const std::int32_t i = g.corners[c + k];
                    if (i < 0 || i >= g.vertexCount) return 0;
                    h[k] = corner(g.vertices + 3 * i, g.normals ? g.normals + 3 * (c + k) : nullptr, uvs, c + k);
                }
                into.push_back(triangle(h[0], h[1], h[2]));
                c += 3;
            }
        }
        if (theirs.size() != made.surfaces.size()) return 0;
        for (auto& entry : theirs) {
            if (!made.surfaces.count(entry.first)) return 0;
            std::sort(entry.second.begin(), entry.second.end());
        }
        // Every choice of the mesh's maps for the UV sets, in turn, until one gives the same triangles.
        std::vector<int> chosen(uvCount, 0);
        std::vector<bool> used(maps, false);
        std::function<bool(int)> next = [&](int at) -> bool {
            if (at == uvCount) {
                for (const auto& entry : theirs) {
                    const Surface& mine = made.surfaces.at(entry.first);
                    std::vector<const float*> uvs;
                    for (int u : chosen) uvs.push_back(mine.uvs[u].data());
                    const long long corners = (long long)(mine.positions.size() / 3);
                    std::vector<std::uint64_t> ours;
                    ours.reserve(size_t(corners / 3));
                    for (long long c = 0; c + 2 < corners; c += 3)
                        ours.push_back(triangle(corner(&mine.positions[3 * c], &mine.normals[3 * c], uvs, c),
                                                corner(&mine.positions[3 * (c + 1)], &mine.normals[3 * (c + 1)], uvs, c + 1),
                                                corner(&mine.positions[3 * (c + 2)], &mine.normals[3 * (c + 2)], uvs, c + 2)));
                    std::sort(ours.begin(), ours.end());
                    if (ours != entry.second) return false;
                }
                return true;
            }
            for (int m = 0; m < maps; ++m) {
                if (used[m]) continue;
                used[m] = true;
                chosen[at] = m;
                if (next(at + 1)) return true;
                used[m] = false;
            }
            return false;
        };
        if (!next(0)) return 0;
        for (int u = 0; u < uvCount; ++u) order[u] = chosen[u];
        return 1;
    } catch (const std::exception&) { return -1; }
      catch (...) { return -1; }
}

// object is the address of the lx.object.Mesh Python holds. by_part: a surface for each part as well as each material,
// as the render cache cuts a mesh where the Shader Tree has a part mask (the kit goes by how the render cache cut the
// same mesh before); else the part is left empty, as it gives it. by_part's 2 refuses polygons of more than four
// corners. Returns null, or what went wrong.
extern "C" __declspec(dllexport) const char* MR_mesh_surfaces(void* object, const char* path, int by_part) {
    static thread_local std::string error;
    try {
        if (!object || !path || !*path) throw std::runtime_error("Missing mesh or output path");
        write(object, path, (by_part & 1) != 0, (by_part & 2) == 0);
        return nullptr;
    } catch (const std::exception& failure) { error = failure.what(); }
      catch (...) { error = "Unknown mesh surfaces error"; }
    return error.c_str();
}
