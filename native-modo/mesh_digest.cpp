// A mesh's fingerprint, for the kit's geometry cache (geometry_cache.py): a digest of everything in a mesh that
// Modo's render cache makes a surface from, so that a surface kept on disk from an earlier reading is taken again
// only while its mesh still digests the same. Its points, its polygons (kind, corners, every tag), and the values of
// every map where the mesh holds them: on points, on polygon corners (discontinuous values) and, for subdivision
// weights and edge picks, on edges.
// Read-only. Runs on Modo's main thread, where Python called it.
#include <lx_mesh.hpp>
#include <lx_visitor.hpp>
#include <lx_value.hpp>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>
#include <unordered_map>
#include <functional>

namespace {
// Two 64-bit lanes, each word mixed in by multiply and rotate; not cryptographic, only to tell one mesh from another.
struct Digest {
    std::uint64_t a = 0x9E3779B97F4A7C15ull, b = 0xC2B2AE3D27D4EB4Full, n = 0;
    static std::uint64_t rotl(std::uint64_t v, int r) { return (v << r) | (v >> (64 - r)); }
    void word(std::uint32_t v) {
        a = rotl((a ^ v) * 0xFF51AFD7ED558CCDull, 29);
        b = rotl((b + v) * 0xC4CEB9FE1A85EC53ull, 31) ^ a;
        ++n;
    }
    void number(float v) { std::uint32_t w; std::memcpy(&w, &v, 4); word(w); }
    void text(const char* s) {
        const std::size_t size = s ? std::strlen(s) : 0;
        word(std::uint32_t(size));
        for (std::size_t i = 0; i < size; i += 4) {
            std::uint32_t w = 0;
            std::memcpy(&w, s + i, size - i < 4 ? size - i : 4);
            word(w);
        }
    }
    std::string hex() {
        word(std::uint32_t(n));
        std::uint64_t x = a ^ rotl(b, 17), y = b ^ rotl(a, 43);
        x ^= x >> 33; x *= 0xFF51AFD7ED558CCDull; x ^= x >> 33;
        y ^= y >> 29; y *= 0xC4CEB9FE1A85EC53ull; y ^= y >> 32;
        static const char* digits = "0123456789abcdef";
        std::string out(32, '0');
        for (int i = 0; i < 16; ++i) { out[15 - i] = digits[x & 15]; x >>= 4; out[31 - i] = digits[y & 15]; y >>= 4; }
        return out;
    }
};

// A visitor that runs a function at each element its accessor is walked to.
struct Each : public CLxImpl_AbstractVisitor {
    std::function<void()> step;
    explicit Each(std::function<void()> f) : step(std::move(f)) {}
    LxResult Evaluate() override { step(); return LXe_OK; }
};

struct Map { LXtMeshMapID id; LXtID4 type; unsigned dimension; std::string name; };
struct MapList : public CLxImpl_AbstractVisitor {
    CLxUser_MeshMap* maps = nullptr;
    std::vector<Map> found;
    LxResult Evaluate() override {
        Map map{maps->ID(), 0, 0, ""};
        const char* name = nullptr;
        maps->Name(&name);
        map.name = name ? name : "";
        maps->Type(&map.type);
        maps->Dimension(&map.dimension);
        found.push_back(map);
        return LXe_OK;
    }
};

// One map's values where the mesh holds them, by the accessors' places: (point, polygon, values) in order, so that
// the digest does not depend on the order Modo walks them in. Walked by Modo's own enumeration of the values a map
// holds: asked for at every point and every corner of every map, a car's meshes took 11 s.
struct Held { std::uint32_t a, b; std::uint32_t at; };
struct Values : public CLxImpl_AbstractVisitor {
    enum Kind { POINTS, CORNERS, EDGES } kind = POINTS;
    LXtMeshMapID map = nullptr;
    unsigned dimension = 0;
    CLxUser_Point* point = nullptr;
    CLxUser_Polygon* polygon = nullptr;
    CLxUser_Edge* edge = nullptr;
    const std::unordered_map<LXtPointID, std::uint32_t>* points = nullptr;
    const std::unordered_map<LXtPolygonID, std::uint32_t>* polygons = nullptr;
    std::vector<Held> held;
    std::vector<float> numbers, value;
    std::uint32_t indexOf(LXtPointID id) const { auto f = points->find(id); return f == points->end() ? 0xFFFFFFFFu : f->second; }
    LxResult Evaluate() override {
        value.assign(std::max(dimension, 1u), 0.0f);
        Held entry{0, 0, std::uint32_t(numbers.size())};
        if (kind == POINTS) {
            entry.a = indexOf(point->ID());
            if (point->MapValue(map, value.data()) != LXe_OK) return LXe_OK;
        } else if (kind == CORNERS) {
            entry.a = indexOf(point->ID());
            auto f = polygons->find(polygon->ID());
            entry.b = f == polygons->end() ? 0xFFFFFFFFu : f->second;
            if (polygon->MapValue(map, point->ID(), value.data()) != LXe_OK) return LXe_OK;
        } else {
            LXtPointID p = nullptr, q = nullptr;
            if (LXx_FAIL(edge->Endpoints(&p, &q))) return LXe_OK;
            entry.a = indexOf(p); entry.b = indexOf(q);
            if (entry.a > entry.b) std::swap(entry.a, entry.b);
            if (edge->MapValue(map, value.data()) != LXe_OK) return LXe_OK;
        }
        numbers.insert(numbers.end(), value.begin(), value.begin() + dimension);
        held.push_back(entry);
        return LXe_OK;
    }
    void into(Digest& d) {
        std::sort(held.begin(), held.end(), [](const Held& x, const Held& y) { return x.a != y.a ? x.a < y.a : x.b < y.b; });
        d.word(std::uint32_t(kind)); d.word(std::uint32_t(held.size()));
        for (const auto& entry : held) {
            d.word(entry.a); d.word(entry.b);
            for (unsigned k = 0; k < dimension; ++k) d.number(numbers[entry.at + k]);
        }
    }
};

std::string digest(void* object) {
    CLxUser_Mesh mesh;
    mesh.set(static_cast<ILxUnknownID>(object));
    if (!mesh.test()) throw std::runtime_error("Not a mesh");
    CLxUser_Point points, walker;
    CLxUser_Polygon polygons, faces;
    CLxUser_Edge edge;
    CLxUser_MeshMap maps, one;
    if (!mesh.GetPoints(points) || !mesh.GetPoints(walker) || !mesh.GetPolygons(polygons) || !mesh.GetPolygons(faces) ||
        !mesh.GetEdges(edge) || !mesh.GetMaps(maps) || !mesh.GetMaps(one))
        throw std::runtime_error("Mesh accessors unavailable");
    MapList list;
    list.maps = &maps;
    maps.Enum(&list);
    std::sort(list.found.begin(), list.found.end(), [](const Map& x, const Map& y) { return x.type != y.type ? x.type < y.type : x.name < y.name; });
    const unsigned pointCount = mesh.NPoints(), polygonCount = mesh.NPolygons();
    Digest d;
    d.word(pointCount); d.word(polygonCount); d.word(unsigned(list.found.size()));
    for (const auto& map : list.found) { d.text(map.name.c_str()); d.word(map.type); d.word(map.dimension); }
    std::unordered_map<LXtPointID, std::uint32_t> pointIndex;
    pointIndex.reserve(pointCount * 2 + 1);
    // Walked in the mesh's own order (its accessors' Enumerate): selected by index one at a time, a tester's tyre of
    // 130,000 polygons took 1.4 s, as long as a million points of plainer meshes.
    std::uint32_t at = 0;
    // Nothing is thrown inside Modo's walks: what went wrong is noted, and thrown once the walk is over.
    const char* failed = nullptr;
    Each pointWalk([&]() {
        LXtFVector position;
        if (LXx_FAIL(points.Pos(position))) { failed = "Point unavailable"; return; }
        pointIndex.emplace(points.ID(), at++);
        d.number(position[0]); d.number(position[1]); d.number(position[2]);
    });
    points.Enum(&pointWalk);
    if (failed) throw std::runtime_error(failed);
    if (at != pointCount) throw std::runtime_error("Points walked are not the mesh's");
    std::unordered_map<LXtPolygonID, std::uint32_t> polygonIndex;
    polygonIndex.reserve(polygonCount * 2 + 1);
    CLxLoc_StringTag tags;
    // The values on polygons' corners (discontinuous), read as the polygons are walked, for the kinds of map that have
    // them: Modo's walk over a map's discontinuous values took a tester's tyre 1.8 s, the polygons' own walk a tenth.
    std::vector<const Map*> cornerMaps;
    for (const auto& map : list.found)
        if (map.type == LXi_VMAP_TEXTUREUV || map.type == LXi_VMAP_NORMAL || map.type == LXi_VMAP_RGB || map.type == LXi_VMAP_RGBA)
            cornerMaps.push_back(&map);
    std::vector<LXtPointID> corners;
    std::vector<float> cornerValue(64);
    at = 0;
    Each polygonWalk([&]() {
        polygonIndex.emplace(polygons.ID(), at++);
        LXtID4 type = 0;
        unsigned count = 0;
        polygons.Type(&type);
        polygons.VertexCount(&count);
        d.word(type); d.word(count);
        for (unsigned k = 0; k < count; ++k) {
            LXtPointID corner = nullptr;
            if (LXx_FAIL(polygons.VertexByIndex(k, &corner))) { failed = "Polygon corner unavailable"; return; }
            auto found = pointIndex.find(corner);
            if (found == pointIndex.end()) { failed = "Polygon corner unknown"; return; }
            d.word(found->second);
            corners.resize(count);
            corners[k] = corner;
        }
        for (const Map* map : cornerMaps) {
            if (map->dimension > cornerValue.size()) cornerValue.resize(map->dimension);
            for (unsigned k = 0; k < count; ++k)
                if (polygons.MapValue(map->id, corners[k], cornerValue.data()) == LXe_OK) {
                    d.word(k + 1);
                    for (unsigned c = 0; c < map->dimension; ++c) d.number(cornerValue[c]);
                }
        }
        tags.set(polygons);
        unsigned tagCount = 0;
        if (tags.test() && LXx_OK(tags.Count(&tagCount))) {
            d.word(tagCount);
            for (unsigned t = 0; t < tagCount; ++t) {
                LXtID4 kind = 0;
                const char* tag = nullptr;
                if (LXx_OK(tags.ByIndex(t, &kind, &tag))) { d.word(kind); d.text(tag); }
            }
        }
    });
    polygons.Enum(&polygonWalk);
    if (failed) throw std::runtime_error(failed);
    if (at != polygonCount) throw std::runtime_error("Polygons walked are not the mesh's");
    for (const auto& map : list.found) {
        if (LXx_FAIL(one.Select(map.id))) continue;
        for (int kind = 0; kind < 3; ++kind) {
            Values values;
            values.kind = Values::Kind(kind);
            values.map = map.id; values.dimension = map.dimension;
            values.point = &walker; values.polygon = &faces; values.edge = &edge;
            values.points = &pointIndex; values.polygons = &polygonIndex;
            if (kind == Values::POINTS) one.EnumContents(&values, walker);
            else if (kind == Values::CORNERS) continue;   // read as the polygons were walked
            else if (map.type == LXi_VMAP_SUBDIV || map.type == LXi_VMAP_EPCK) one.EnumContents(&values, edge);
            values.into(d);
        }
    }
    return d.hex();
}
}

// object is the address of the lx.object.Mesh Python holds. Returns 32 hex digits, or "!" and what went wrong.
extern "C" __declspec(dllexport) const char* MR_mesh_digest(void* object) {
    static thread_local std::string result;
    try {
        if (!object) throw std::runtime_error("Missing mesh");
        result = digest(object);
    } catch (const std::exception& failure) { result = std::string("!") + failure.what(); }
      catch (...) { result = "!Unknown mesh digest error"; }
    return result.c_str();
}

// Each polygon corner's normal as Modo's mesh gives it (the point's normal for that polygon, ILxPoint::Normal), in the
// mesh's order of polygons and corners: out has room for 3 floats a corner (room: the corners it has room for).
// Returns the corners written, or -1. For the geometry cache's direct reading of an edited mesh (geometry_cache).
extern "C" __declspec(dllexport) long long MR_corner_normals(void* object, float* out, long long room) {
    try {
        CLxUser_Mesh mesh;
        mesh.set(static_cast<ILxUnknownID>(object));
        if (!mesh.test()) return -1;
        CLxUser_Point point;
        CLxUser_Polygon polygons;
        if (!mesh.GetPoints(point) || !mesh.GetPolygons(polygons)) return -1;
        long long at = 0;
        bool bad = false;
        Each walk([&]() {
            unsigned count = 0;
            polygons.VertexCount(&count);
            const LXtPolygonID id = polygons.ID();
            for (unsigned k = 0; k < count; ++k) {
                LXtPointID corner = nullptr;
                LXtVector n = {0, 0, 0};
                if (at >= room || LXx_FAIL(polygons.VertexByIndex(k, &corner)) || LXx_FAIL(point.Select(corner)) ||
                    LXx_FAIL(point.Normal(id, n))) { bad = true; return; }
                out[3 * at] = float(n[0]); out[3 * at + 1] = float(n[1]); out[3 * at + 2] = float(n[2]);
                ++at;
            }
        });
        polygons.Enum(&walk);
        return bad ? -1 : at;
    } catch (...) { return -1; }
}
