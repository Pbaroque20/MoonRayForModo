// A VDB shape in Modo's viewport: the box its grid fills and points where it is thick (the kit's vdb_preview), drawn
// here rather than in Python, where some thousands of vertices a redraw went through Modo's Python wrappers one by one.
//
// MR_vdb_preview_load reads a coarse grid made by the runtime's modo_vdb_grid ("MLV1" or "MLV4": three counts, the
// largest value, sixteen floats placing the unit cube in the grid's own space, then the values, x fastest) and keeps
// the box and the points under a name; it is called on a thread of the kit's own. MR_vdb_preview_draw draws what is kept
// under a name on the viewport's stroke object, which is only borrowed for the call.
#include <lx_draw.hpp>
#include <lxw_draw.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <vector>

namespace {
struct Preview {
    std::array<std::array<double, 3>, 8> corners;
    std::vector<std::array<double, 3>> points;
};
std::mutex lock;
std::map<std::string, Preview> kept;

// The box's twelve edges, as pairs of its corners (corner index = 4 u + 2 v + w).
const int EDGES[12][2] = {{0, 1}, {2, 3}, {4, 5}, {6, 7}, {0, 2}, {1, 3}, {4, 6}, {5, 7}, {0, 4}, {1, 5}, {2, 6}, {3, 7}};
}

// Reads a coarse grid file and keeps its box and, where the grid is at least thick times its largest value, up to most
// points, evenly taken. 1 where it was read, 0 where it was not.
extern "C" __declspec(dllexport) int MR_vdb_preview_load(const char* path, const char* name, double thick, int most) {
    try {
        std::ifstream in(path, std::ios::binary);
        if (!in) return 0;
        std::vector<char> data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
        if (data.size() < 84 || (std::memcmp(data.data(), "MLV1", 4) && std::memcmp(data.data(), "MLV4", 4))) return 0;
        const size_t width = std::memcmp(data.data(), "MLV1", 4) == 0 ? 1 : 4;
        uint32_t counts[3];
        float largest, rows[16];
        std::memcpy(counts, data.data() + 4, sizeof(counts));
        std::memcpy(&largest, data.data() + 16, sizeof(largest));
        std::memcpy(rows, data.data() + 20, sizeof(rows));
        const size_t total = size_t(counts[0]) * counts[1] * counts[2];
        if (!total || data.size() < 84 + total * width * sizeof(float)) return 0;
        const float* values = reinterpret_cast<const float*>(data.data() + 84);
        auto place = [&](double u, double v, double w) {
            std::array<double, 3> p;
            for (int k = 0; k < 3; ++k) p[k] = u * rows[k] + v * rows[4 + k] + w * rows[8 + k] + rows[12 + k];
            return p;
        };
        Preview made;
        for (int i = 0; i < 8; ++i) made.corners[i] = place((i >> 2) & 1, (i >> 1) & 1, i & 1);
        const float floor = largest > 0.0f ? float(thick) * largest : 3.4e38f;
        std::vector<size_t> dense;
        for (size_t i = 0; i < total; ++i) {
            float value = values[i * width];
            for (size_t k = 1; k < std::min<size_t>(width, 3); ++k) value = std::max(value, values[i * width + k]);
            if (value >= floor) dense.push_back(i);
        }
        const size_t step = std::max<size_t>(1, dense.size() / size_t(std::max(1, most)));
        for (size_t n = 0; n < dense.size(); n += step) {
            const size_t i = dense[n];
            const size_t x = i % counts[0], rest = i / counts[0];
            const size_t y = rest % counts[1], z = rest / counts[1];
            made.points.push_back(place((x + 0.5) / counts[0], (y + 0.5) / counts[1], (z + 0.5) / counts[2]));
        }
        std::lock_guard<std::mutex> held(lock);
        kept[name] = std::move(made);
        return 1;
    } catch (...) {
        return 0;
    }
}

// Draws what is kept under a name on a viewport's stroke object (ILxStrokeDraw, borrowed): its box's edges, then its
// points. 1 where something was kept to draw, 0 where nothing is yet.
extern "C" __declspec(dllexport) int MR_vdb_preview_draw(void* strokeObject, const char* name, double red, double green, double blue) {
    Preview shown;
    {
        std::lock_guard<std::mutex> held(lock);
        const auto found = kept.find(name);
        if (found == kept.end()) return 0;
        shown = found->second;
    }
    CLxLoc_StrokeDraw stroke;
    if (!stroke.set(reinterpret_cast<ILxUnknownID>(strokeObject))) return 0;
    LXtVector color = {red, green, blue};
    stroke.Begin(LXiSTROKE_LINES, color, 1.0);
    for (const auto& edge : EDGES) {
        stroke.Vertex(shown.corners[edge[0]].data(), LXiSTROKE_ABSOLUTE);
        stroke.Vertex(shown.corners[edge[1]].data(), LXiSTROKE_ABSOLUTE);
    }
    if (!shown.points.empty()) {
        stroke.Begin(LXiSTROKE_POINTS, color, 0.6);
        for (const auto& point : shown.points) stroke.Vertex(point.data(), LXiSTROKE_ABSOLUTE);
    }
    return 1;
}
