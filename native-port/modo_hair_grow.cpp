// Hair grown from guide curves, as moonray_modo/hair.py grows it, for when there is a great deal of it.
//
//   modo_hair_grow <input> <output>
// The input is "MHG1"; mode and strands a guide as two 32-bit integers; the seed as a 64-bit one; the cluster's width,
// how far it closes and how much lengths vary as doubles; sixteen doubles that take a grown point back into the mesh's
// own space (basis vectors in rows); the number of guides, the number of points of each, and their points, root first;
// then the number of the scalp's triangles, or -1 for no scalp, and their corners. The output is "MHS1", how many
// guides start too far from the scalp, how many strands, the number of points of each, and their points.
//
// Every step is the one hair.py takes, in its order, with Python's own random numbers, so the same hair grows here as
// there: the plugin falls back on hair.py where this program is not to be had.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace {

struct V { double x, y, z; };
V sub(V a, V b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
V add(V a, V b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
V scaled(V a, double k) { return {a.x * k, a.y * k, a.z * k}; }
double dot(V a, V b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
V cross(V a, V b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
V unit(V a, V fallback = {0.0, 1.0, 0.0}) {
    const double length = std::sqrt(dot(a, a));
    return length > 1e-12 ? scaled(a, 1.0 / length) : fallback;
}
double component(V a, int k) { return k == 0 ? a.x : k == 1 ? a.y : a.z; }

// Python's random.Random: the Mersenne Twister, seeded from a whole number as CPython seeds it.
struct Chance {
    uint32_t mt[624];
    int at = 625;
    void start(uint32_t s) {
        mt[0] = s;
        for (at = 1; at < 624; ++at) mt[at] = 1812433253u * (mt[at - 1] ^ (mt[at - 1] >> 30)) + uint32_t(at);
    }
    explicit Chance(uint64_t seed) {
        std::vector<uint32_t> key;
        key.push_back(uint32_t(seed & 0xffffffffu));
        if (seed >> 32) key.push_back(uint32_t(seed >> 32));
        start(19650218u);
        size_t i = 1, j = 0;
        for (size_t k = std::max<size_t>(624, key.size()); k; --k) {
            mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1664525u)) + key[j] + uint32_t(j);
            ++i; ++j;
            if (i >= 624) { mt[0] = mt[623]; i = 1; }
            if (j >= key.size()) j = 0;
        }
        for (size_t k = 623; k; --k) {
            mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1566083941u)) - uint32_t(i);
            ++i;
            if (i >= 624) { mt[0] = mt[623]; i = 1; }
        }
        mt[0] = 0x80000000u;
        at = 624;
    }
    uint32_t next() {
        if (at >= 624) {
            for (int k = 0; k < 624; ++k) {
                const uint32_t y = (mt[k] & 0x80000000u) | (mt[(k + 1) % 624] & 0x7fffffffu);
                mt[k] = mt[(k + 397) % 624] ^ (y >> 1) ^ ((y & 1u) ? 0x9908b0dfu : 0u);
            }
            at = 0;
        }
        uint32_t y = mt[at++];
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c5680u;
        y ^= (y << 15) & 0xefc60000u;
        y ^= y >> 18;
        return y;
    }
    double random() {
        const uint32_t a = next() >> 5, b = next() >> 6;
        return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
    }
    double uniform(double low, double high) { return low + (high - low) * random(); }
};

// The point of a triangle nearest p (Ericson, Real-Time Collision Detection), number by number as hair.py has it.
V on_triangle(V p, V a, V b, V c) {
    const double abx = b.x - a.x, aby = b.y - a.y, abz = b.z - a.z;
    const double acx = c.x - a.x, acy = c.y - a.y, acz = c.z - a.z;
    const double apx = p.x - a.x, apy = p.y - a.y, apz = p.z - a.z;
    const double d1 = abx * apx + aby * apy + abz * apz, d2 = acx * apx + acy * apy + acz * apz;
    if (d1 <= 0 && d2 <= 0) return a;
    const double bpx = p.x - b.x, bpy = p.y - b.y, bpz = p.z - b.z;
    const double d3 = abx * bpx + aby * bpy + abz * bpz, d4 = acx * bpx + acy * bpy + acz * bpz;
    if (d3 >= 0 && d4 <= d3) return b;
    const double vc = d1 * d4 - d3 * d2;
    if (vc <= 0 && d1 >= 0 && d3 <= 0) {
        const double k = d1 / (d1 - d3);
        return {a.x + abx * k, a.y + aby * k, a.z + abz * k};
    }
    const double cpx = p.x - c.x, cpy = p.y - c.y, cpz = p.z - c.z;
    const double d5 = abx * cpx + aby * cpy + abz * cpz, d6 = acx * cpx + acy * cpy + acz * cpz;
    if (d6 >= 0 && d5 <= d6) return c;
    const double vb = d5 * d2 - d1 * d6;
    if (vb <= 0 && d2 >= 0 && d6 <= 0) {
        const double k = d2 / (d2 - d6);
        return {a.x + acx * k, a.y + acy * k, a.z + acz * k};
    }
    const double va = d3 * d6 - d5 * d4;
    if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
        const double k = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        return {b.x + (c.x - b.x) * k, b.y + (c.y - b.y) * k, b.z + (c.z - b.z) * k};
    }
    const double denominator = 1.0 / (va + vb + vc);
    const double v = vb * denominator, w = vc * denominator;
    return {a.x + (abx * v + acx * w), a.y + (aby * v + acy * w), a.z + (abz * v + acz * w)};
}

struct Triangle { V a, b, c; };
struct Patch { std::vector<int> candidates; std::vector<double> distances; V origin; };
struct Landed { bool found = false; V point{}, normal{}; };

using Cell = std::tuple<long long, long long, long long>;

struct Scalp {
    std::vector<Triangle> triangles;
    std::vector<V> middles;
    std::vector<double> reaches;
    double widest = 0.0, size = 1.0;
    std::map<Cell, std::vector<int>> cells;

    explicit Scalp(const std::vector<Triangle>& given) {
        for (const Triangle& t : given) {
            const V n = cross(sub(t.b, t.a), sub(t.c, t.a));
            if (dot(n, n) > 1e-24) triangles.push_back(t);
        }
        for (const Triangle& t : triangles) {
            const V middle = {(t.a.x + t.b.x + t.c.x) / 3.0, (t.a.y + t.b.y + t.c.y) / 3.0, (t.a.z + t.b.z + t.c.z) / 3.0};
            middles.push_back(middle);
            double reach = 0.0;
            for (const V corner : {t.a, t.b, t.c}) reach = std::max(reach, std::sqrt(dot(sub(corner, middle), sub(corner, middle))));
            reaches.push_back(reach);
            widest = std::max(widest, reach);
        }
        if (triangles.empty()) return;
        double low[3], high[3];
        for (int k = 0; k < 3; ++k) {
            low[k] = 1e300; high[k] = -1e300;
            for (const Triangle& t : triangles)
                for (const V corner : {t.a, t.b, t.c}) {
                    low[k] = std::min(low[k], component(corner, k));
                    high[k] = std::max(high[k], component(corner, k));
                }
        }
        double extent = std::max(high[0] - low[0], std::max(high[1] - low[1], high[2] - low[2]));
        if (!(extent != 0.0)) extent = 1.0;
        size = std::max(extent / std::max(2.0, std::pow(triangles.size() / 2.0, 1 / 3.0) * 2), 1e-9);
        for (size_t index = 0; index < triangles.size(); ++index) {
            const Triangle& t = triangles[index];
            long long lower[3], upper[3];
            for (int k = 0; k < 3; ++k) {
                lower[k] = (long long)std::floor(std::min(component(t.a, k), std::min(component(t.b, k), component(t.c, k))) / size);
                upper[k] = (long long)std::floor(std::max(component(t.a, k), std::max(component(t.b, k), component(t.c, k))) / size);
            }
            for (long long x = lower[0]; x <= upper[0]; ++x)
                for (long long y = lower[1]; y <= upper[1]; ++y)
                    for (long long z = lower[2]; z <= upper[2]; ++z) cells[Cell(x, y, z)].push_back(int(index));
        }
    }

    // The triangles that may come within reach of a point, nearest first; of two as near, the earlier in the mesh.
    Patch around(V point, double reach) const {
        Patch patch;
        patch.origin = point;
        if (triangles.empty()) return patch;
        long long low[3], high[3];
        for (int k = 0; k < 3; ++k) {
            low[k] = (long long)std::floor((component(point, k) - reach) / size);
            high[k] = (long long)std::floor((component(point, k) + reach) / size);
        }
        std::vector<int> found;
        for (long long x = low[0]; x <= high[0]; ++x)
            for (long long y = low[1]; y <= high[1]; ++y)
                for (long long z = low[2]; z <= high[2]; ++z) {
                    const auto cell = cells.find(Cell(x, y, z));
                    if (cell != cells.end()) found.insert(found.end(), cell->second.begin(), cell->second.end());
                }
        std::sort(found.begin(), found.end());
        found.erase(std::unique(found.begin(), found.end()), found.end());
        std::vector<std::pair<double, int>> ordered;
        for (int index : found) ordered.push_back({std::sqrt(dot(sub(middles[index], point), sub(middles[index], point))), index});
        std::sort(ordered.begin(), ordered.end());
        for (const auto& entry : ordered) {
            patch.candidates.push_back(entry.second);
            patch.distances.push_back(entry.first);
        }
        return patch;
    }

    Landed nearest_among(V point, const Patch& patch, double reach) const {
        double best = reach;
        int found = -1, last = -1;
        V at{};
        const double moved = std::sqrt((point.x - patch.origin.x) * (point.x - patch.origin.x) + (point.y - patch.origin.y) * (point.y - patch.origin.y)
                                       + (point.z - patch.origin.z) * (point.z - patch.origin.z));
        std::vector<std::tuple<double, int, int>> near;
        for (size_t place = 0; place < patch.candidates.size(); ++place) {
            const int index = patch.candidates[place];
            if (patch.distances[place] - moved - widest > best) break;
            const V m = middles[index];
            const double gap = std::sqrt((point.x - m.x) * (point.x - m.x) + (point.y - m.y) * (point.y - m.y) + (point.z - m.z) * (point.z - m.z)) - reaches[index];
            if (gap <= best) near.push_back(std::make_tuple(gap, int(place), index));
        }
        std::sort(near.begin(), near.end());
        for (const auto& entry : near) {
            if (std::get<0>(entry) > best) break;
            const int place = std::get<1>(entry), index = std::get<2>(entry);
            const Triangle& t = triangles[index];
            const V q = on_triangle(point, t.a, t.b, t.c);
            const double distance = std::sqrt((point.x - q.x) * (point.x - q.x) + (point.y - q.y) * (point.y - q.y) + (point.z - q.z) * (point.z - q.z));
            if (distance < best || (distance == best && place > last)) {
                best = distance; found = index; last = place; at = q;
            }
        }
        Landed landed;
        if (found < 0) return landed;
        const Triangle& t = triangles[found];
        landed.found = true;
        landed.point = at;
        landed.normal = unit(cross(sub(t.b, t.a), sub(t.c, t.a)));
        return landed;
    }
};

std::vector<V> resampled(const std::vector<V>& strand, size_t count) {
    if (strand.size() == count) return strand;
    std::vector<double> lengths{0.0};
    for (size_t i = 0; i + 1 < strand.size(); ++i) lengths.push_back(lengths.back() + std::sqrt(dot(sub(strand[i + 1], strand[i]), sub(strand[i + 1], strand[i]))));
    const double total = lengths.back();
    std::vector<V> result;
    size_t segment = 0;
    for (size_t i = 0; i < count; ++i) {
        const double target = total * double(i) / double(count - 1);
        while (segment + 2 < strand.size() && lengths[segment + 1] < target) ++segment;
        const double span = lengths[segment + 1] - lengths[segment];
        const double t = span > 1e-12 ? (target - lengths[segment]) / span : 0.0;
        result.push_back(add(strand[segment], scaled(sub(strand[segment + 1], strand[segment]), t)));
    }
    return result;
}

// For each guide, the guides whose roots are nearest its own, found through a grid.
std::vector<std::vector<int>> neighbours(const std::vector<V>& roots, size_t count = 2) {
    std::vector<std::vector<int>> result(roots.size());
    if (roots.size() <= 1) return result;
    double low[3], high[3];
    for (int k = 0; k < 3; ++k) {
        low[k] = 1e300; high[k] = -1e300;
        for (const V& r : roots) { low[k] = std::min(low[k], component(r, k)); high[k] = std::max(high[k], component(r, k)); }
    }
    const double size = std::max(std::max(high[0] - low[0], std::max(high[1] - low[1], high[2] - low[2])) / std::max(1.0, std::pow(double(roots.size()), 1 / 3.0)), 1e-9);
    std::map<Cell, std::vector<int>> cells;
    for (size_t index = 0; index < roots.size(); ++index)
        cells[Cell((long long)std::floor(roots[index].x / size), (long long)std::floor(roots[index].y / size), (long long)std::floor(roots[index].z / size))].push_back(int(index));
    for (size_t index = 0; index < roots.size(); ++index) {
        const V root = roots[index];
        const long long centre[3] = {(long long)std::floor(root.x / size), (long long)std::floor(root.y / size), (long long)std::floor(root.z / size)};
        std::vector<std::pair<double, int>> found;
        long long ring = 0;
        while (found.size() < count && ring < 64) {
            ++ring;
            found.clear();
            for (long long x = centre[0] - ring; x <= centre[0] + ring; ++x)
                for (long long y = centre[1] - ring; y <= centre[1] + ring; ++y)
                    for (long long z = centre[2] - ring; z <= centre[2] + ring; ++z) {
                        const auto cell = cells.find(Cell(x, y, z));
                        if (cell == cells.end()) continue;
                        for (int other : cell->second)
                            if (other != int(index)) found.push_back({dot(sub(roots[other], root), sub(roots[other], root)), other});
                    }
        }
        std::sort(found.begin(), found.end());
        for (size_t k = 0; k < found.size() && k < count; ++k) result[index].push_back(found[k].second);
    }
    return result;
}

template <class T> T take(const std::vector<char>& data, size_t& at) {
    if (at + sizeof(T) > data.size()) throw std::runtime_error("the input ends too soon");
    T value;
    std::memcpy(&value, data.data() + at, sizeof(T));
    at += sizeof(T);
    return value;
}

const double REACH = 4.0, PI = 3.141592653589793;

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 3) {
            std::cerr << "usage: modo_hair_grow <input> <output>" << std::endl;
            return 2;
        }
        std::ifstream source(argv[1], std::ios::binary);
        const std::vector<char> data((std::istreambuf_iterator<char>(source)), std::istreambuf_iterator<char>());
        if (data.size() < 4 || std::memcmp(data.data(), "MHG1", 4) != 0) throw std::runtime_error("not hair to grow");
        size_t at = 4;
        const int32_t mode = take<int32_t>(data, at);
        const int32_t count = std::max<int32_t>(1, take<int32_t>(data, at));
        const int64_t seed = take<int64_t>(data, at);
        const double width = take<double>(data, at);
        const double clump = std::min(1.0, std::max(0.0, take<double>(data, at)));
        const double variation = std::min(.95, std::max(0.0, take<double>(data, at)));
        double back[16];
        for (double& value : back) value = take<double>(data, at);
        const int32_t given = take<int32_t>(data, at);
        std::vector<int32_t> counts(given);
        for (int32_t& value : counts) value = take<int32_t>(data, at);
        std::vector<std::vector<V>> guides;
        for (int32_t points : counts) {
            std::vector<V> guide(points);
            for (V& p : guide) { p.x = take<double>(data, at); p.y = take<double>(data, at); p.z = take<double>(data, at); }
            if (guide.size() >= 2) guides.push_back(guide);
        }
        const int32_t faces = take<int32_t>(data, at);
        std::vector<Triangle> triangles(std::max<int32_t>(0, faces));
        for (Triangle& t : triangles)
            for (V* corner : {&t.a, &t.b, &t.c}) { corner->x = take<double>(data, at); corner->y = take<double>(data, at); corner->z = take<double>(data, at); }
        const bool surfaced = faces >= 0;
        const Scalp scalp(triangles);

        std::vector<V> roots;
        for (const auto& guide : guides) roots.push_back(guide[0]);
        const bool between = mode == 1;
        const std::vector<std::vector<int>> near = between ? neighbours(roots) : std::vector<std::vector<int>>(roots.size());
        std::vector<double> out;
        std::vector<int32_t> made;
        int64_t adrift = 0;
        out.reserve(size_t(guides.size()) * count * 8 * 3);
        for (size_t index = 0; index < guides.size(); ++index) {
            const std::vector<V>& guide = guides[index];
            Chance chance(uint64_t(seed * 1000003 + int64_t(index)));
            const V root = guide[0];
            double span = width * (REACH + 1);
            if (!near[index].empty()) {
                double furthest = 0.0;
                for (int other : near[index]) furthest = std::max(furthest, std::sqrt(dot(sub(roots[other], root), sub(roots[other], root))));
                span += furthest;
            }
            Patch patch;
            Landed placed;
            if (surfaced) {
                patch = scalp.around(root, span);
                placed = scalp.nearest_among(root, patch, width * REACH);
                if (!placed.found) ++adrift;
            }
            const V normal = placed.found ? placed.normal : unit(sub(guide[1], guide[0]));
            const double off = placed.found ? std::sqrt(dot(sub(placed.point, root), sub(placed.point, root))) : -1.0;
            const V helper = std::fabs(normal.x) < .9 ? V{1.0, 0.0, 0.0} : V{0.0, 1.0, 0.0};
            const V across = unit(cross(normal, helper));
            const V along = cross(normal, across);
            const size_t steps = guide.size() - 1;
            std::vector<V> own;
            for (const V& p : guide) own.push_back(sub(p, root));
            std::vector<std::vector<V>> shapes{guide};
            for (int other : near[index]) shapes.push_back(resampled(guides[other], guide.size()));
            const bool others = !near[index].empty();
            for (int32_t strand = 0; strand < count; ++strand) {
                const double angle = chance.uniform(0, 2 * PI), distance = width * std::sqrt(chance.random());
                const double shorter = 1.0 - variation * chance.random();
                V start, spread;
                std::vector<V> body;
                double near_by = -1.0;
                if (others) {
                    std::vector<double> weights;
                    for (size_t k = 0; k < shapes.size(); ++k) weights.push_back(chance.random());
                    weights[0] += 1.0;
                    double total = 0.0;
                    for (double w : weights) total += w;
                    for (double& w : weights) w = w / total;
                    start = {0.0, 0.0, 0.0};
                    for (size_t k = 0; k < shapes.size(); ++k) start = add(start, scaled(shapes[k][0], weights[k]));
                    for (size_t j = 0; j < guide.size(); ++j) {
                        V reach = {0.0, 0.0, 0.0};
                        for (size_t k = 0; k < shapes.size(); ++k) reach = add(reach, scaled(sub(shapes[k][j], shapes[k][0]), weights[k]));
                        body.push_back(reach);
                    }
                    const V offset = scaled(add(scaled(across, std::cos(angle)), scaled(along, std::sin(angle))), distance * .25);
                    start = add(start, offset);
                    spread = {0.0, 0.0, 0.0};
                } else {
                    spread = scaled(add(scaled(across, std::cos(angle)), scaled(along, std::sin(angle))), distance);
                    start = add(root, spread);
                    body = own;
                    if (off >= 0.0) near_by = std::min(width * REACH, (distance + off) * 1.0001 + 1e-9);
                }
                Landed landed;
                // As hair.py has it: a reach of nothing is no reach given, and the widest is used.
                if (surfaced) landed = scalp.nearest_among(start, patch, near_by > 0.0 ? near_by : width * REACH);
                V base;
                if (!landed.found) {
                    base = root;
                    spread = {0.0, 0.0, 0.0};
                    body = own;
                } else {
                    base = landed.point;
                }
                const double pull = others ? 0.0 : -clump / double(steps);
                for (size_t j = 0; j < body.size(); ++j) {
                    const V p = {base.x + (body[j].x * shorter + spread.x * (pull * double(j))), base.y + (body[j].y * shorter + spread.y * (pull * double(j))),
                                 base.z + (body[j].z * shorter + spread.z * (pull * double(j)))};
                    // Back into the mesh's own space, basis vectors in rows.
                    out.push_back(p.x * back[0] + p.y * back[4] + p.z * back[8] + back[12]);
                    out.push_back(p.x * back[1] + p.y * back[5] + p.z * back[9] + back[13]);
                    out.push_back(p.x * back[2] + p.y * back[6] + p.z * back[10] + back[14]);
                }
                made.push_back(int32_t(body.size()));
            }
        }
        std::ofstream target(argv[2], std::ios::binary);
        const int64_t strands = int64_t(made.size());
        target.write("MHS1", 4);
        target.write(reinterpret_cast<const char*>(&adrift), sizeof(adrift));
        target.write(reinterpret_cast<const char*>(&strands), sizeof(strands));
        target.write(reinterpret_cast<const char*>(made.data()), made.size() * sizeof(int32_t));
        target.write(reinterpret_cast<const char*>(out.data()), out.size() * sizeof(double));
        if (!target) throw std::runtime_error("cannot write the output");
        return 0;
    } catch (const std::exception& problem) {
        std::cerr << "modo_hair_grow: " << problem.what() << std::endl;
        return 1;
    }
}
