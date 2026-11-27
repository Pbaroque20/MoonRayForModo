// Modo's Smooth Positions for the plugin's Python (moonray_modo/smooth_positions.py): a displaced polygon cage split
// n times onto Modo's smooth surface, its points placed as Modo's render cache places them (Phong tessellation at a
// shape factor given, a half: each point the mean of its place on the flat face and Phong's), each edge's points made
// once for both its faces. The same steps, in the same order, as smooth_positions._refine, so that the adapter and the
// Python fallback make the same mesh; in Python a 128-face column split into 32,768 faces took seconds, which held large
// cages to a budget. A split is kept behind a handle: its points and faces, then any corner's or point's values carried
// to the new places by the same weights (UVs, normals, maps), and the positions at the shutter's close.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <unordered_map>
#include <vector>

namespace {

// An edge's point: its two points (the lower first) and its step from the lower.
struct EdgeKey {
    uint32_t low, high, step;
    bool operator==(const EdgeKey& o) const { return low == o.low && high == o.high && step == o.step; }
};
struct EdgeHash {
    size_t operator()(const EdgeKey& k) const { return std::hash<uint64_t>()((uint64_t(k.low) << 32 | k.high) * 1000003u + k.step); }
};

// A face of size corners (3 or 4) split n times: its places, each place's weights on the corners, each place's edge
// (corner a, corner b, step from a; a < 0 where inside), and its new faces as places. As smooth_positions._layout.
struct Layout {
    std::vector<std::array<double, 4>> weights;
    std::vector<std::array<int, 3>> edges;
    std::vector<std::vector<int>> faces;
};

Layout layout(int size, int n) {
    Layout out;
    if (size == 4) {
        std::vector<int> at((n + 1) * (n + 1));
        for (int j = 0; j <= n; ++j)
            for (int i = 0; i <= n; ++i) {
                const double s = double(i) / n, t = double(j) / n;
                at[j * (n + 1) + i] = int(out.weights.size());
                out.weights.push_back({(1 - s) * (1 - t), s * (1 - t), s * t, (1 - s) * t});
                std::array<int, 3> e{-1, -1, 0};
                if (j == 0) e = {0, 1, i};
                else if (i == n) e = {1, 2, j};
                else if (j == n) e = {3, 2, i};
                else if (i == 0) e = {0, 3, j};
                out.edges.push_back(e);
            }
        for (int j = 0; j < n; ++j)
            for (int i = 0; i < n; ++i)
                out.faces.push_back({at[j * (n + 1) + i], at[j * (n + 1) + i + 1], at[(j + 1) * (n + 1) + i + 1], at[(j + 1) * (n + 1) + i]});
    } else {
        std::vector<std::vector<int>> at(n + 1, std::vector<int>(n + 1, -1));
        for (int j = 0; j <= n; ++j)
            for (int i = 0; i <= n - j; ++i) {
                at[i][j] = int(out.weights.size());
                out.weights.push_back({double(n - i - j) / n, double(i) / n, double(j) / n, 0.0});
                std::array<int, 3> e{-1, -1, 0};
                if (j == 0) e = {0, 1, i};
                else if (i + j == n) e = {1, 2, j};
                else if (i == 0) e = {0, 2, j};
                out.edges.push_back(e);
            }
        for (int j = 0; j < n; ++j)
            for (int i = 0; i < n - j; ++i) {
                out.faces.push_back({at[i][j], at[i + 1][j], at[i][j + 1]});
                if (i + j < n - 1) out.faces.push_back({at[i + 1][j], at[i + 1][j + 1], at[i][j + 1]});
            }
    }
    return out;
}

void unit(double* v) {
    const double length = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (length > 1e-30) { v[0] /= length; v[1] /= length; v[2] /= length; } else { v[0] = v[1] = v[2] = 0.0; }
}

// Each point's normal: its faces' Newell normals summed, made unit (smooth_positions.point_normals).
std::vector<double> pointNormals(const float* points, long long pointCount, const int32_t* corners, const int32_t* counts,
                                 long long faceCount) {
    std::vector<double> sums(size_t(pointCount) * 3, 0.0);
    long long at = 0;
    for (long long f = 0; f < faceCount; ++f) {
        const int size = counts[f];
        double n[3] = {0, 0, 0};
        for (int k = 0; k < size; ++k) {
            const float* a = points + size_t(corners[at + k]) * 3;
            const float* b = points + size_t(corners[at + (k + 1) % size]) * 3;
            n[0] += (double(a[1]) - b[1]) * (double(a[2]) + b[2]);
            n[1] += (double(a[2]) - b[2]) * (double(a[0]) + b[0]);
            n[2] += (double(a[0]) - b[0]) * (double(a[1]) + b[1]);
        }
        for (int k = 0; k < size; ++k)
            for (int c = 0; c < 3; ++c) sums[size_t(corners[at + k]) * 3 + c] += n[c];
        at += size;
    }
    for (long long p = 0; p < pointCount; ++p) unit(&sums[size_t(p) * 3]);
    return sums;
}

// p's place on Modo's smooth surface: Phong's (p taken to each corner's tangent plane, weighed) mixed by shape.
void phong(const double* p, const double* corners, const double* normals, const double* w, int size, double shape, double* out) {
    double q[3] = {0, 0, 0};
    for (int c = 0; c < size; ++c) {
        const double* x = corners + c * 3;
        const double* n = normals + c * 3;
        const double d = (p[0] - x[0]) * n[0] + (p[1] - x[1]) * n[1] + (p[2] - x[2]) * n[2];
        for (int k = 0; k < 3; ++k) q[k] += w[c] * (p[k] - d * n[k]);
    }
    for (int k = 0; k < 3; ++k) out[k] = (1 - shape) * p[k] + shape * q[k];
}

struct Split {
    long long sourcePoints = 0;
    std::vector<float> points;                 // 3 each
    std::vector<int32_t> corners, counts, fromFace;
    // Each new point (past the source's): its face's corners as source points, how many, and their weights.
    std::vector<std::array<int32_t, 4>> pointFrom;
    std::vector<std::array<double, 4>> pointWeight;
    std::vector<int> pointSize;
    // Each new corner: its face's corners as source corners, how many, and its weights.
    std::vector<std::array<int64_t, 4>> cornerFrom;
    std::vector<std::array<double, 4>> cornerWeight;
    std::vector<int> cornerSize;
    // The source, for the shutter's close: corners and counts.
    std::vector<int32_t> sourceCorners, sourceCounts;
};

}  // namespace

// points: 3 floats each; corners and counts: the faces; normals: 3 floats for each corner (the mesh's own), or null for
// the points' (Newell, summed and made unit); n: splits; shape: Modo's shape factor. Returns a handle, or null where a
// corner names a point beyond the points or a face has fewer than 3 corners.
extern "C" __declspec(dllexport) void* MR_smooth_split(const float* points, long long pointCount, const int32_t* corners,
                                                      const int32_t* counts, long long faceCount, const float* normals, int n,
                                                      double shape) {
    if (n < 1 || pointCount < 0 || faceCount < 0) return nullptr;
    long long total = 0;
    for (long long f = 0; f < faceCount; ++f) {
        if (counts[f] < 3) return nullptr;
        total += counts[f];
    }
    for (long long c = 0; c < total; ++c)
        if (corners[c] < 0 || corners[c] >= pointCount) return nullptr;
    std::vector<double> byPoint;
    if (!normals) byPoint = pointNormals(points, pointCount, corners, counts, faceCount);
    Split* made = new Split();
    made->sourcePoints = pointCount;
    made->sourceCorners.assign(corners, corners + total);
    made->sourceCounts.assign(counts, counts + faceCount);
    made->points.assign(points, points + size_t(pointCount) * 3);
    Layout layouts[2] = {layout(3, n), layout(4, n)};
    std::unordered_map<EdgeKey, int32_t, EdgeHash> onEdges;
    long long start = 0;
    for (long long f = 0; f < faceCount; ++f) {
        const int size = counts[f];
        // Faces of more than four corners as fans of triangles (corner 0, i, i + 1).
        std::vector<std::vector<int>> ways;
        if (size <= 4) {
            std::vector<int> way(size);
            for (int k = 0; k < size; ++k) way[k] = k;
            ways.push_back(way);
        } else {
            for (int i = 1; i < size - 1; ++i) ways.push_back({0, i, i + 1});
        }
        for (const auto& way : ways) {
            const int pieceSize = int(way.size());
            const Layout& L = layouts[pieceSize == 4 ? 1 : 0];
            int32_t face[4];
            double cornersAt[12], normalsAt[12];
            for (int c = 0; c < pieceSize; ++c) {
                face[c] = corners[start + way[c]];
                for (int k = 0; k < 3; ++k) {
                    cornersAt[c * 3 + k] = points[size_t(face[c]) * 3 + k];
                    normalsAt[c * 3 + k] = normals ? double(normals[size_t(start + way[c]) * 3 + k]) : byPoint[size_t(face[c]) * 3 + k];
                }
                if (normals) unit(&normalsAt[c * 3]);
            }
            std::vector<int32_t> made_at(L.weights.size());
            for (size_t place = 0; place < L.weights.size(); ++place) {
                const auto& w = L.weights[place];
                int corner = -1;
                for (int c = 0; c < pieceSize; ++c)
                    if (w[c] == 1.0) { corner = c; break; }
                if (corner >= 0) { made_at[place] = face[corner]; continue; }
                const auto& e = L.edges[place];
                EdgeKey key{0, 0, 0};
                if (e[0] >= 0) {
                    const uint32_t a = uint32_t(face[e[0]]), b = uint32_t(face[e[1]]);
                    const uint32_t step = uint32_t(e[2]);
                    key = a < b ? EdgeKey{a, b, step} : EdgeKey{b, a, uint32_t(n - int(step))};
                    auto found = onEdges.find(key);
                    if (found != onEdges.end()) { made_at[place] = found->second; continue; }
                }
                double p[3] = {0, 0, 0}, q[3];
                for (int c = 0; c < pieceSize; ++c)
                    for (int k = 0; k < 3; ++k) p[k] += cornersAt[c * 3 + k] * w[c];
                phong(p, cornersAt, normalsAt, w.data(), pieceSize, shape, q);
                for (int k = 0; k < 3; ++k) made->points.push_back(float(q[k]));
                const int32_t index = int32_t(made->points.size() / 3 - 1);
                std::array<int32_t, 4> from{0, 0, 0, 0};
                for (int c = 0; c < pieceSize; ++c) from[c] = face[c];
                made->pointFrom.push_back(from);
                made->pointWeight.push_back(w);
                made->pointSize.push_back(pieceSize);
                made_at[place] = index;
                if (e[0] >= 0) onEdges.emplace(key, index);
            }
            for (const auto& sub : L.faces) {
                for (int k : sub) {
                    made->corners.push_back(made_at[k]);
                    std::array<int64_t, 4> from{0, 0, 0, 0};
                    for (int c = 0; c < pieceSize; ++c) from[c] = start + way[c];
                    made->cornerFrom.push_back(from);
                    made->cornerWeight.push_back(L.weights[k]);
                    made->cornerSize.push_back(pieceSize);
                }
                made->counts.push_back(int32_t(sub.size()));
                made->fromFace.push_back(int32_t(f));
            }
        }
        start += size;
    }
    return made;
}

// sizes: [points, faces, corners] of the split.
extern "C" __declspec(dllexport) void MR_smooth_split_sizes(void* handle, long long* sizes) {
    const Split* s = static_cast<const Split*>(handle);
    sizes[0] = (long long)(s->points.size() / 3);
    sizes[1] = (long long)s->counts.size();
    sizes[2] = (long long)s->corners.size();
}

// points: 3 floats each; corners, counts, fromFace (the source face of each new face): as sized.
extern "C" __declspec(dllexport) void MR_smooth_split_geometry(void* handle, float* points, int32_t* corners, int32_t* counts,
                                                               int32_t* fromFace) {
    const Split* s = static_cast<const Split*>(handle);
    std::copy(s->points.begin(), s->points.end(), points);
    std::copy(s->corners.begin(), s->corners.end(), corners);
    std::copy(s->counts.begin(), s->counts.end(), counts);
    std::copy(s->fromFace.begin(), s->fromFace.end(), fromFace);
}

// A value of width floats for each source corner, carried to each new corner (made unit where unitLength).
extern "C" __declspec(dllexport) void MR_smooth_split_corners(void* handle, const float* values, int width, float* out, int unitLength) {
    const Split* s = static_cast<const Split*>(handle);
    std::vector<double> held(static_cast<size_t>(width), 0.0);
    for (size_t c = 0; c < s->cornerFrom.size(); ++c) {
        std::fill(held.begin(), held.end(), 0.0);
        for (int k = 0; k < s->cornerSize[c]; ++k)
            for (int v = 0; v < width; ++v) held[v] += double(values[size_t(s->cornerFrom[c][k]) * width + v]) * s->cornerWeight[c][k];
        if (unitLength && width == 3) unit(held.data());
        for (int v = 0; v < width; ++v) out[c * width + v] = float(held[v]);
    }
}

// A value of width floats for each source point, carried to every point of the split (the source's as they are).
extern "C" __declspec(dllexport) void MR_smooth_split_points(void* handle, const float* values, int width, float* out) {
    const Split* s = static_cast<const Split*>(handle);
    std::copy(values, values + size_t(s->sourcePoints) * width, out);
    for (size_t p = 0; p < s->pointFrom.size(); ++p)
        for (int v = 0; v < width; ++v) {
            double sum = 0.0;
            for (int k = 0; k < s->pointSize[p]; ++k) sum += double(values[size_t(s->pointFrom[p][k]) * width + v]) * s->pointWeight[p][k];
            out[(size_t(s->sourcePoints) + p) * width + v] = float(sum);
        }
}

// The split's points as the shutter closes: closing (the source's points then) placed on its own smooth surface, by its
// points' normals, as smooth_positions does.
extern "C" __declspec(dllexport) void MR_smooth_split_moved(void* handle, const float* closing, double shape, float* out) {
    const Split* s = static_cast<const Split*>(handle);
    const std::vector<double> normals = pointNormals(closing, s->sourcePoints, s->sourceCorners.data(), s->sourceCounts.data(),
                                                     (long long)s->sourceCounts.size());
    std::copy(closing, closing + size_t(s->sourcePoints) * 3, out);
    for (size_t p = 0; p < s->pointFrom.size(); ++p) {
        double cornersAt[12], normalsAt[12], q[3], at[3] = {0, 0, 0};
        const int size = s->pointSize[p];
        for (int c = 0; c < size; ++c)
            for (int k = 0; k < 3; ++k) {
                cornersAt[c * 3 + k] = closing[size_t(s->pointFrom[p][c]) * 3 + k];
                normalsAt[c * 3 + k] = normals[size_t(s->pointFrom[p][c]) * 3 + k];
                at[k] += cornersAt[c * 3 + k] * s->pointWeight[p][c];
            }
        phong(at, cornersAt, normalsAt, s->pointWeight[p].data(), size, shape, q);
        for (int k = 0; k < 3; ++k) out[(size_t(s->sourcePoints) + p) * 3 + k] = float(q[k]);
    }
}

extern "C" __declspec(dllexport) void MR_smooth_split_free(void* handle) { delete static_cast<Split*>(handle); }

// The most a corner's normal (normals: 3 floats a corner, or null for the points') turns from its face's, in degrees
// (smooth_positions.splits); -1 where a corner names a point beyond the points.
extern "C" __declspec(dllexport) double MR_smooth_split_turn(const float* points, long long pointCount, const int32_t* corners,
                                                            const int32_t* counts, long long faceCount, const float* normals) {
    long long at = 0;
    for (long long f = 0; f < faceCount; ++f) {
        for (int k = 0; k < counts[f]; ++k)
            if (corners[at + k] < 0 || corners[at + k] >= pointCount) return -1.0;
        at += counts[f];
    }
    std::vector<double> byPoint;
    if (!normals) byPoint = pointNormals(points, pointCount, corners, counts, faceCount);
    double most = 1.0;
    at = 0;
    for (long long f = 0; f < faceCount; ++f) {
        const int size = counts[f];
        double n[3] = {0, 0, 0};
        for (int k = 0; k < size; ++k) {
            const float* a = points + size_t(corners[at + k]) * 3;
            const float* b = points + size_t(corners[at + (k + 1) % size]) * 3;
            n[0] += (double(a[1]) - b[1]) * (double(a[2]) + b[2]);
            n[1] += (double(a[2]) - b[2]) * (double(a[0]) + b[0]);
            n[2] += (double(a[0]) - b[0]) * (double(a[1]) + b[1]);
        }
        unit(n);
        for (int k = 0; k < size; ++k) {
            double c[3];
            for (int v = 0; v < 3; ++v) c[v] = normals ? double(normals[size_t(at + k) * 3 + v]) : byPoint[size_t(corners[at + k]) * 3 + v];
            if (normals) unit(c);
            most = std::min(most, n[0] * c[0] + n[1] * c[1] + n[2] * c[2]);
        }
        at += size;
    }
    return std::acos(std::max(-1.0, std::min(1.0, most))) * 180.0 / 3.14159265358979323846;
}
