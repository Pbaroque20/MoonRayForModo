// host.subdivision_creases for the plugin's Python, in one call: Modo's subdivision weights on the edges and points of
// a subdivided mesh's faces. Python asked Modo for each edge by its two points, an edge and a point at a time (every
// edge of a heavy subdivided mesh, Modo's thread held). The same edges in the same order (each once, as the faces first
// meet it, its points lower first), the same points (each once, in index order), an edge or point Modo has not, or
// without a weight, left out; the weights as Modo holds them (Python makes them MoonRay's sharpness). Read-only. Runs
// on Modo's main thread, where Python called it.
#include <lx_mesh.hpp>
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

namespace {

struct Room {
    std::int32_t* edges; float* edgeWeights; long long edgeRoom;
    std::int32_t* points; float* pointWeights; long long pointRoom;
};

void read(void* object, void* map, const std::uint32_t* corners, const std::int32_t* counts, long long faceCount,
          const Room& room, long long* made) {
    CLxUser_Mesh mesh;
    mesh.set(static_cast<ILxUnknownID>(object));
    if (!mesh.test()) throw std::runtime_error("Not a mesh");
    CLxUser_Point points;
    CLxUser_Edge edge;
    if (!mesh.GetPoints(points) || !mesh.GetEdges(edge)) throw std::runtime_error("Mesh accessors unavailable");
    const LXtMeshMapID weights = static_cast<LXtMeshMapID>(map);
    const long long pointCount = mesh.NPoints();
    std::vector<LXtPointID> ids(size_t(std::max(0LL, pointCount)), nullptr);
    auto id = [&](std::uint32_t index) -> LXtPointID {
        if ((long long)index >= pointCount) return nullptr;
        if (!ids[index]) {
            if (LXx_FAIL(points.SelectByIndex(index))) return nullptr;
            ids[index] = points.ID();
        }
        return ids[index];
    };
    long long edgesMade = 0, pointsMade = 0, at = 0;
    std::unordered_set<std::uint64_t> seen;
    std::vector<std::uint32_t> used;
    for (long long f = 0; f < faceCount; ++f) {
        const long long size = counts[f];
        if (size < 0) throw std::runtime_error("Bad face size");
        for (long long k = 0; k < size; ++k) {
            const std::uint32_t a = corners[at + k], b = corners[at + (k + 1) % size];
            used.push_back(a);
            const std::uint32_t lo = std::min(a, b), hi = std::max(a, b);
            if (!seen.insert((std::uint64_t(lo) << 32) | hi).second) continue;
            const LXtPointID p = id(lo), q = id(hi);
            if (!p || !q || LXx_FAIL(edge.SelectEndpoints(p, q))) continue;
            float value = 0.0f;
            if (edge.MapValue(weights, &value) != LXe_OK || !(value > 0.0f)) continue;
            if (edgesMade >= room.edgeRoom) throw std::runtime_error("Too little room for the creases");
            room.edges[2 * edgesMade] = std::int32_t(lo);
            room.edges[2 * edgesMade + 1] = std::int32_t(hi);
            room.edgeWeights[edgesMade++] = value;
        }
        at += size;
    }
    std::sort(used.begin(), used.end());
    used.erase(std::unique(used.begin(), used.end()), used.end());
    for (const std::uint32_t index : used) {
        const LXtPointID p = id(index);
        if (!p || LXx_FAIL(points.Select(p))) continue;
        float value = 0.0f;
        if (points.MapValue(weights, &value) != LXe_OK || !(value > 0.0f)) continue;
        if (pointsMade >= room.pointRoom) throw std::runtime_error("Too little room for the corners");
        room.points[pointsMade] = std::int32_t(index);
        room.pointWeights[pointsMade++] = value;
    }
    made[0] = edgesMade;
    made[1] = pointsMade;
}

}  // namespace

// object is the address of the lx.object.Mesh Python holds, map the Subdivision weight map's ID. The faces as their
// corners (point indices) and each one's number of corners. Edges go out as point pairs with their weights, points as
// indices with theirs; made: how many of each. Returns null, or what went wrong.
extern "C" __declspec(dllexport) const char* MR_subdivision_creases(void* object, void* map, const std::uint32_t* corners,
                                                                     const std::int32_t* counts, long long faceCount,
                                                                     std::int32_t* edges, float* edgeWeights, long long edgeRoom,
                                                                     std::int32_t* points, float* pointWeights, long long pointRoom,
                                                                     long long* made) {
    static thread_local std::string error;
    try {
        if (!object || !map || !made || (faceCount && (!corners || !counts))) throw std::runtime_error("Missing mesh, map or faces");
        read(object, map, corners, counts, faceCount, Room{edges, edgeWeights, edgeRoom, points, pointWeights, pointRoom}, made);
        return nullptr;
    } catch (const std::exception& failure) { error = failure.what(); }
      catch (...) { error = "Unknown crease reader error"; }
    return error.c_str();
}
