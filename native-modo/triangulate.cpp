// polygons.py's cutting of polygons into triangles, for the plugin's Python (polygons.triangulate): MoonRay's n-gon ear
// clipping (geom/TriMesh.cc, TriMesh::splitNGons) or the "N-gons triangulated cleanly" override's, a fan where it finds
// no ear or a face is not one to clip, the same arithmetic in doubles, the same tests in the same order. In Python each
// face was a step of its own (a car's 291 meshes with n-gons, 6.7 s of a scene written; MoonLightIPR's packing of a mesh
// of quads, a corner at a time).
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace {

struct V { double x, y, z; };
V sub(const V& a, const V& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
V cross(const V& a, const V& b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
double dot(const V& a, const V& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
V unit(const V& a) {
    const double length = std::sqrt(dot(a, a));
    return length ? V{a.x / length, a.y / length, a.z / length} : V{0.0, 0.0, 0.0};
}

// polygons._unit_normal: MoonRay's unitNormal of three points.
V unitNormal(const V& a, const V& b, const V& c) {
    auto det = [](const V& r0, const V& r1, const V& r2) { return dot(r0, cross(r1, r2)); };
    const double x = det({1, a.y, a.z}, {1, b.y, b.z}, {1, c.y, c.z});
    const double y = det({a.x, 1, a.z}, {b.x, 1, b.z}, {c.x, 1, c.z});
    const double z = det({a.x, a.y, 1}, {b.x, b.y, 1}, {c.x, c.y, 1});
    const double m = std::max(1e-6, std::sqrt(x * x + y * y + z * z));
    return {x / m, y / m, z / m};
}

V summed(const std::vector<V>& p) {
    V total{0.0, 0.0, 0.0};
    for (size_t i = 0; i < p.size(); ++i) {
        const V c = cross(p[i], p[(i + 1) % p.size()]);
        total = {total.x + c.x, total.y + c.y, total.z + c.z};
    }
    return total;
}

// polygons._inside: whether p lies in the triangle a, b, c.
bool inside(const V& p, const V& a, const V& b, const V& c) {
    const V v0 = sub(b, a), v1 = sub(c, a), v2 = sub(p, a);
    const double d00 = dot(v0, v0), d01 = dot(v0, v1), d11 = dot(v1, v1), d20 = dot(v2, v0), d21 = dot(v2, v1);
    const double den = d00 * d11 - d01 * d01;
    if (!den) return false;
    const double y = (d11 * d20 - d01 * d21) / den;
    const double w = (d00 * d21 - d01 * d20) / den;
    return 1.0 - y - w >= 0 && y >= 0 && w >= 0;
}

// polygons.ear_clip: the triangles of a flat polygon of more than four corners as its corners' places in it, or false
// where it is fanned instead.
bool earClip(const std::vector<V>& p, bool clean, std::vector<uint32_t>& out) {
    const size_t n = p.size();
    if (n <= 4) return false;
    V normal;
    double near = 0.0;
    if (clean) {
        // polygons._clean_normal.
        const V total = summed(p);
        const double length = std::sqrt(dot(total, total));
        V lo = p[0], hi = p[0];
        for (const V& q : p) {
            lo = {std::min(lo.x, q.x), std::min(lo.y, q.y), std::min(lo.z, q.z)};
            hi = {std::max(hi.x, q.x), std::max(hi.y, q.y), std::max(hi.z, q.z)};
        }
        const double extent = std::sqrt((hi.x - lo.x) * (hi.x - lo.x) + (hi.y - lo.y) * (hi.y - lo.y) + (hi.z - lo.z) * (hi.z - lo.z));
        if (!(std::isfinite(length) && extent > 0 && length / 2 > 1e-10 * extent * extent)) return false;
        normal = {total.x / length, total.y / length, total.z / length};
        for (size_t i = 1; i < n; ++i)
            if (std::fabs(dot(sub(p[i], p[0]), normal)) > 1e-4 * extent) return false;
        const double reach = 1e-7 * extent;
        near = reach * reach;
    } else {
        // polygons._area, _planar and _normal: MoonRay's own tests.
        const V total = summed(p);
        const double area = dot(total, unitNormal(p[0], p[1], p[2])) / 2.0;
        if (std::isnan(area) || area < 1e-6) return false;
        const V across = cross(sub(p[0], p[1]), sub(p[2], p[1]));
        for (size_t i = 3; i < n; ++i)
            if (!(std::fabs(dot(unit(sub(p[0], p[i])), across)) <= 1e-6)) return false;
        normal = unit(area < 0.0 ? V{-total.x, -total.y, -total.z} : total);
    }
    std::vector<uint32_t> local(n);
    for (size_t i = 0; i < n; ++i) local[i] = uint32_t(i);
    const size_t start = out.size();
    while (local.size() > 3) {
        const size_t m = local.size();
        bool cut = false;
        for (size_t step = 0; step < m; ++step) {
            const size_t i = m - 1 - step;
            const uint32_t ia = local[i], ib = local[(i + m - 1) % m], ic = local[(i + 1) % m];
            const V& va = p[ia];
            const V& vb = p[ib];
            const V& vc = p[ic];
            // A corner turned against the face is no ear; nor is one whose triangle holds another corner.
            if (dot(cross(sub(vc, va), sub(vb, va)), normal) < 0.0) continue;
            bool holds = false;
            for (uint32_t l : local) {
                if (l == ia || l == ib || l == ic) continue;
                if (clean) {
                    const V da = sub(p[l], va), db = sub(p[l], vb), dc = sub(p[l], vc);
                    if (std::min(std::min(dot(da, da), dot(db, db)), dot(dc, dc)) <= near) continue;
                }
                if (inside(p[l], vb, va, vc)) { holds = true; break; }
            }
            if (holds) continue;
            out.push_back(ib); out.push_back(ia); out.push_back(ic);
            local.erase(local.begin() + long(i));
            cut = true;
            break;
        }
        if (!cut) { out.resize(start); return false; }
    }
    out.insert(out.end(), local.begin(), local.end());
    return true;
}

}  // namespace

// The faces (counts, and their corners into points: three doubles each) cut into triangles. clean: the override's rules,
// else MoonRay's. keep: triangles and quads are kept whole (as MoonRay is handed a mesh, polygons.cut_mesh), else every
// face is cut into triangles, a quad as (0, 1, 2, 0, 2, 3) (MoonLightIPR). For each new corner, the place of the old corner
// it is among the old corners (places); for each new face its old face (faces_out) and its number of corners (sizes).
// made: the new corners and faces written. Returns 0, or -1 where the room given is short or a corner is out of range.
extern "C" __declspec(dllexport) int MR_triangulate(const double* points, long long pointCount, const uint32_t* corners,
                                                    const int32_t* counts, long long faceCount, int clean, int keep,
                                                    uint32_t* places, int32_t* faces_out, int32_t* sizes,
                                                    long long cornerRoom, long long faceRoom, long long* made) {
    long long at = 0, cornersMade = 0, facesMade = 0;
    std::vector<V> polygon;
    std::vector<uint32_t> cut;
    for (long long f = 0; f < faceCount; ++f) {
        const long long size = counts[f];
        if (size < 0) return -1;
        const bool whole = keep ? size <= 4 : size == 3;
        cut.clear();
        bool clipped = false;
        if (!whole && size > 4) {
            polygon.resize(size_t(size));
            for (long long k = 0; k < size; ++k) {
                const uint32_t v = corners[at + k];
                if ((long long)v >= pointCount) return -1;
                polygon[size_t(k)] = {points[3LL * v], points[3LL * v + 1], points[3LL * v + 2]};
            }
            clipped = earClip(polygon, clean != 0, cut);
        }
        if (whole) {
            if (cornersMade + size > cornerRoom || facesMade + 1 > faceRoom) return -1;
            for (long long k = 0; k < size; ++k) places[cornersMade++] = uint32_t(at + k);
            faces_out[facesMade] = int32_t(f);
            sizes[facesMade++] = int32_t(size);
        } else {
            if (!clipped)
                for (long long k = 1; k + 1 < size; ++k) { cut.push_back(0); cut.push_back(uint32_t(k)); cut.push_back(uint32_t(k + 1)); }
            if (cornersMade + (long long)cut.size() > cornerRoom || facesMade + (long long)cut.size() / 3 > faceRoom) return -1;
            for (size_t k = 0; k < cut.size(); k += 3) {
                for (size_t j = 0; j < 3; ++j) places[cornersMade++] = uint32_t(at + cut[k + j]);
                faces_out[facesMade] = int32_t(f);
                sizes[facesMade++] = 3;
            }
        }
        at += size;
    }
    made[0] = cornersMade;
    made[1] = facesMade;
    return 0;
}
