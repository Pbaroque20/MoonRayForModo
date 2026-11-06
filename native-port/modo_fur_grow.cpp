// Modo's fur, grown as moonray_modo/fur.py grows it, for when there is a great deal of it.
//
//   modo_fur_grow <input> <output prefix>
// The input is "MFG1"; then, as 64-bit integers, the seed and the most fibres to grow (0 for as many as Modo would);
// as 32-bit integers the joints of a fibre, whether its width is absolute, whether it bends up, and whether a curl only
// sways; twenty-three doubles of the Fur material (in the order of Settings below); the number of triangles, their
// three corners and the surface's normal at each as doubles, and for each the group its fibres go in; then five
// 32-bit integers, one for each weight map (density, length, clump, curl, bend), 1 where it is given, and each given
// map as three doubles a triangle. "MFG2" adds, after the maps, the guides (fur.Guides): the guide mode as a 32-bit
// integer (0 none, 1 clump, 2 Direction, 3 Direction + Length, 4 shape, 5 range), Guide Range and Guide Length as
// doubles, the number of guides (32-bit), and each guide's number of points (32-bit) and points (three doubles each).
// "MFG3" is MFG1 followed by the width map (a 32-bit 1 and three doubles a triangle, or a 0), the vector map (a 1 and
// three vectors of three doubles a triangle, or a 0), and the guides as MFG2 has them.
// For each group there is a file <prefix>.<group>.mfc: "MFC1", the number of fibres (32-bit) and of points (64-bit),
// the radius at the root and at the tip (floats), the number of points of each fibre (32-bit), each point as four
// floats (where it is, and the fibre's radius there) and each point's place as two floats (which fibre of the group,
// 0 to 1, and how far along it). <prefix>.info holds, as 64-bit integers, how many fibres Modo would grow, how many
// were grown, the number of groups, and for each its number, its fibres and its points; then the radius at the root
// and at the tip as doubles.
//
// Every step is the one fur.py takes, in its order, with Python's own random numbers, so the same fur grows here as
// there for the same number of fibres: the plugin falls back on fur.py where this program is not to be had.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {

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

struct Settings {
    double dist, length, width, widthAbs, taper, flex, growthJitter, sclJitter, nrmJitter, density, rootBend, curls,
           curlRadius, clumps, clumpSize, kinkAmp, kinkAmpTip, kinkScl, kinkOff, frizAmp, frizAmpTip, strays, straysAmp;
};

struct P { double x, y, z; };
struct Triangle { P a, b, c, na, nb, nc; };

template <class T> T take(const std::vector<char>& data, size_t& at) {
    if (at + sizeof(T) > data.size()) throw std::runtime_error("the request is cut short");
    T value;
    std::memcpy(&value, data.data() + at, sizeof(T));
    at += sizeof(T);
    return value;
}

struct Placed { size_t picked; double r, s, t, x, y, z, nx, ny, nz; };

double distance(const P& a, const P& b) {
    return std::sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y) + (a.z - b.z) * (a.z - b.z));
}

// fur.Guides: each guide's root, its form as offsets from the root at steps + 1 even lengths along it, its length and
// the way it sets out, and a grid of the roots. The same arithmetic and the same order as fur.py's.
enum { GUIDE_NONE, GUIDE_CLUMP, GUIDE_NORMAL, GUIDE_DIRLEN, GUIDE_SHAPE, GUIDE_RANGE };
struct Guides {
    std::vector<P> roots, directions;
    std::vector<std::vector<P>> offsets;
    std::vector<double> lengths;
    int steps = 2;
    double cell = 1.0;
    std::map<std::tuple<int64_t, int64_t, int64_t>, std::vector<size_t>> grid;

    Guides(const std::vector<std::vector<P>>& strands, int steps_) : steps(steps_) {
        for (const auto& points : strands) {
            if (points.size() < 2) continue;
            std::vector<double> along{0.0};
            for (size_t i = 1; i < points.size(); ++i) along.push_back(along.back() + distance(points[i - 1], points[i]));
            const double total = along.back();
            if (!(total > 0)) continue;
            std::vector<P> made;
            size_t at = 0;
            for (int j = 0; j <= steps; ++j) {
                const double sought = total * j / steps;
                while (at < along.size() - 2 && along[at + 1] < sought) ++at;
                const double span = along[at + 1] - along[at];
                const double f = span > 0 ? (sought - along[at]) / span : 0.0;
                const P& a = points[at];
                const P& b = points[at + 1];
                made.push_back({a.x + (b.x - a.x) * f - points[0].x, a.y + (b.y - a.y) * f - points[0].y, a.z + (b.z - a.z) * f - points[0].z});
            }
            P first = points[1];
            for (size_t i = 1; i < points.size(); ++i)
                if (distance(points[i], points[0]) > 0) { first = points[i]; break; }
            P way{first.x - points[0].x, first.y - points[0].y, first.z - points[0].z};
            double size = std::sqrt(way.x * way.x + way.y * way.y + way.z * way.z);
            if (size == 0.0) size = 1.0;
            roots.push_back(points[0]);
            offsets.push_back(std::move(made));
            lengths.push_back(total);
            directions.push_back({way.x / size, way.y / size, way.z / size});
        }
        if (roots.empty()) return;
        P low = roots[0], high = roots[0];
        for (const P& r : roots) {
            low = {std::min(low.x, r.x), std::min(low.y, r.y), std::min(low.z, r.z)};
            high = {std::max(high.x, r.x), std::max(high.y, r.y), std::max(high.z, r.z)};
        }
        const double spread = distance(low, high);
        cell = std::max(1e-4, spread / std::max(1.0, std::sqrt(double(roots.size()))));
        for (size_t i = 0; i < roots.size(); ++i) grid[key(roots[i])].push_back(i);
    }
    std::tuple<int64_t, int64_t, int64_t> key(const P& p) const {
        return std::make_tuple(int64_t(std::floor(p.x / cell)), int64_t(std::floor(p.y / cell)), int64_t(std::floor(p.z / cell)));
    }
    size_t nearest(const P& p) const {
        const auto c = key(p);
        const int64_t cx = std::get<0>(c), cy = std::get<1>(c), cz = std::get<2>(c);
        bool found = false;
        size_t best = 0;
        double least = 1e300;
        for (int64_t ring = 0;; ++ring) {
            for (int64_t i = cx - ring; i <= cx + ring; ++i)
                for (int64_t j = cy - ring; j <= cy + ring; ++j)
                    for (int64_t k = cz - ring; k <= cz + ring; ++k) {
                        if (std::max(std::max(std::llabs(i - cx), std::llabs(j - cy)), std::llabs(k - cz)) != ring) continue;
                        const auto here = grid.find(std::make_tuple(i, j, k));
                        if (here == grid.end()) continue;
                        for (size_t index : here->second) {
                            const double far = distance(roots[index], p);
                            if (far < least) { best = index; least = far; found = true; }
                        }
                    }
            if (found && ring * cell > least) return best;
            if (ring + 1 > 4096) return best;
        }
    }
    std::vector<std::pair<size_t, double>> within(const P& p, double reach) const {
        std::vector<std::pair<size_t, double>> found;
        if (reach <= 0) return found;
        const int64_t span = int64_t(std::ceil(reach / cell));
        const auto c = key(p);
        for (int64_t i = std::get<0>(c) - span; i <= std::get<0>(c) + span; ++i)
            for (int64_t j = std::get<1>(c) - span; j <= std::get<1>(c) + span; ++j)
                for (int64_t k = std::get<2>(c) - span; k <= std::get<2>(c) + span; ++k) {
                    const auto here = grid.find(std::make_tuple(i, j, k));
                    if (here == grid.end()) continue;
                    for (size_t index : here->second) {
                        const double far = distance(roots[index], p);
                        if (far <= reach) found.push_back({index, far});
                    }
                }
        return found;
    }
    std::vector<P> placed(size_t index, const P& p, double length) const {
        const double scale = length / lengths[index];
        std::vector<P> strand;
        for (const P& o : offsets[index]) strand.push_back({p.x + o.x * scale, p.y + o.y * scale, p.z + o.z * scale});
        return strand;
    }
    std::vector<P> blended(const std::vector<std::pair<size_t, double>>& near, const P& p, double reach, double scale) const {
        double total = 0.0;
        for (const auto& entry : near) total += 1.0 - entry.second / reach;
        if (total == 0.0) total = 1.0;
        std::vector<P> strand;
        for (int j = 0; j <= steps; ++j) {
            P point = p;
            for (const auto& entry : near) {
                const double w = 1.0 - entry.second / reach;
                const P& o = offsets[entry.first][j];
                point.x += o.x * scale * w / total;
                point.y += o.y * scale * w / total;
                point.z += o.z * scale * w / total;
            }
            strand.push_back(point);
        }
        return strand;
    }
};

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("usage: modo_fur_grow <input> <output prefix>");
        std::ifstream source(argv[1], std::ios::binary);
        std::vector<char> data((std::istreambuf_iterator<char>(source)), std::istreambuf_iterator<char>());
        size_t at = 0;
        // MFG2: as MFG1, then the guides (fur.Guides): the mode, Guide Range and Guide Length, and each guide's points.
        // MFG3: as MFG1, then the width map and the vector map, each after a flag, then the guides as MFG2 has them.
        const bool second = data.size() >= 4 && !std::memcmp(data.data(), "MFG2", 4);
        const bool third = data.size() >= 4 && !std::memcmp(data.data(), "MFG3", 4);
        if (data.size() < 4 || (std::memcmp(data.data(), "MFG1", 4) && !second && !third)) throw std::runtime_error("not a fur request");
        at = 4;
        const int64_t seed = take<int64_t>(data, at), most = take<int64_t>(data, at);
        const int32_t maxSegment = take<int32_t>(data, at), absolute = take<int32_t>(data, at), up = take<int32_t>(data, at),
                      flat = take<int32_t>(data, at);
        const Settings held = take<Settings>(data, at);
        const int32_t n = take<int32_t>(data, at);
        if (n < 0) throw std::runtime_error("a fur request with no triangles");
        std::vector<Triangle> triangles(n);
        for (auto& triangle : triangles) triangle = take<Triangle>(data, at);
        std::vector<int32_t> group(n);
        for (auto& g : group) g = take<int32_t>(data, at);
        std::vector<std::vector<double>> maps(5);
        int32_t given[5];
        for (int m = 0; m < 5; ++m) given[m] = take<int32_t>(data, at);
        for (int m = 0; m < 5; ++m)
            if (given[m]) {
                maps[m].resize(size_t(n) * 3);
                for (auto& w : maps[m]) w = take<double>(data, at);
            }
        int32_t mode = GUIDE_NONE;
        double guideRange = 0.0, guideLength = 1.0;
        std::vector<std::vector<P>> guideStrands;
        std::vector<double> widthMap, vectorMap;
        if (third) {
            if (take<int32_t>(data, at)) {
                widthMap.resize(size_t(n) * 3);
                for (auto& w : widthMap) w = take<double>(data, at);
            }
            if (take<int32_t>(data, at)) {
                vectorMap.resize(size_t(n) * 9);
                for (auto& v : vectorMap) v = take<double>(data, at);
            }
        }
        if (second || third) {
            mode = take<int32_t>(data, at);
            guideRange = std::max(0.0, take<double>(data, at));
            guideLength = std::max(0.0, take<double>(data, at));
            const int32_t many = take<int32_t>(data, at);
            for (int32_t g = 0; g < many; ++g) {
                std::vector<P> strand(size_t(std::max(0, take<int32_t>(data, at))));
                for (auto& p : strand) p = take<P>(data, at);
                guideStrands.push_back(std::move(strand));
            }
        }
        enum { DENSITY, LENGTH, CLUMP, CURL, BEND };

        std::vector<double> areas(n);
        double total = 0.0;
        for (int32_t i = 0; i < n; ++i) {
            const Triangle& q = triangles[i];
            const double ux = q.b.x - q.a.x, uy = q.b.y - q.a.y, uz = q.b.z - q.a.z;
            const double vx = q.c.x - q.a.x, vy = q.c.y - q.a.y, vz = q.c.z - q.a.z;
            const double nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
            total += .5 * std::sqrt(nx * nx + ny * ny + nz * nz);
            areas[i] = total;
        }
        double apart = std::max(1e-5, held.dist);
        const int64_t wanted = int64_t(total / (apart * apart) * std::max(0.0, held.density));
        const int64_t count = most > 0 ? std::min(wanted, most) : wanted;
        std::map<int32_t, std::vector<size_t>> members;   // the fibres of each group, in the order grown
        std::vector<std::vector<P>> strands;
        std::vector<double> widths;   // each fibre's width as a share of the radii
        double root = 0.0, tip = 0.0;
        if (count > 0 && total > 0) {
            // A fibre is as thick as the Fur material says, however many of Modo's are grown.
            root = absolute ? held.widthAbs / 2 : apart * std::max(0.0, held.width) / 2;
            tip = root * std::max(.02, 1.0 - std::min(1.0, std::max(0.0, held.taper)));
            const double curls = std::max(0.0, held.curls), clumps = std::min(1.0, std::max(0.0, held.clumps));
            const bool kinked = std::max(std::fabs(held.kinkAmp), std::fabs(held.kinkAmpTip)) > 0;
            const bool frizzed = std::max(std::fabs(held.frizAmp), std::fabs(held.frizAmpTip)) > 0;
            int steps = std::max(2, std::min(8, int(maxSegment)));
            if (curls > 0 || kinked || frizzed) steps = std::max(steps, 12);
            const double lean[3] = {0.0, up ? 1.0 : -1.0, 0.0};
            Chance chance{uint64_t(seed < 0 ? -seed : seed)};
            const int64_t second = seed * 7919 + 1;
            Chance other{uint64_t(second < 0 ? -second : second)};

            auto weight = [&](int what, size_t picked, double r, double s, double t) {
                if (maps[what].empty()) return 1.0;
                const double* w = &maps[what][picked * 3];
                return std::min(1.0, std::max(0.0, w[0] * r + w[1] * s + w[2] * t));
            };
            auto fibre = [&](double x, double y, double z, double dx, double dy, double dz, double length, double bend) {
                const double step = length / steps;
                std::vector<P> strand;
                strand.reserve(steps + 1);
                strand.push_back({x, y, z});
                for (int j = 1; j <= steps; ++j) {
                    const double pull = held.rootBend + held.flex * bend * j / steps;
                    const double bx = dx + lean[0] * pull, by = dy + lean[1] * pull, bz = dz + lean[2] * pull;
                    double size = std::sqrt(bx * bx + by * by + bz * bz);
                    if (size == 0.0) size = 1.0;
                    x = x + bx / size * step; y = y + by / size * step; z = z + bz / size * step;
                    strand.push_back({x, y, z});
                }
                return strand;
            };
            auto place = [&](Chance& pick) {
                const double sought = pick.random() * total;
                size_t picked = size_t(std::lower_bound(areas.begin(), areas.end(), sought) - areas.begin());
                picked = std::min(size_t(n) - 1, picked);
                const Triangle& q = triangles[picked];
                double s = pick.random(), t = pick.random();
                if (s + t > 1.0) { s = 1.0 - s; t = 1.0 - t; }
                const double r = 1.0 - s - t;
                return Placed{picked, r, s, t, q.a.x * r + q.b.x * s + q.c.x * t, q.a.y * r + q.b.y * s + q.c.y * t,
                              q.a.z * r + q.b.z * s + q.c.z * t, q.na.x * r + q.nb.x * s + q.nc.x * t,
                              q.na.y * r + q.nb.y * s + q.nc.y * t, q.na.z * r + q.nb.z * s + q.nc.z * t};
            };

            const double reach = std::max(1e-5, held.length * std::max(.05, held.kinkScl) * 3);
            double waves[6][4];
            for (auto& wave : waves) {
                wave[0] = other.random() * 2 - 1;
                wave[1] = other.random() * 2 - 1;
                wave[2] = other.random() * 2 - 1;
                wave[3] = other.random() * 6.2832;
            }
            std::vector<std::tuple<double, double, double>> swing(steps + 1), wound(steps + 1);
            for (int j = 0; j <= steps; ++j) {
                swing[j] = std::make_tuple(std::cos(3.1416 * j / steps), std::sin(3.1416 * j / steps),
                                           (held.kinkAmp + (held.kinkAmpTip - held.kinkAmp) * j / steps) * .35 * j / steps);
                wound[j] = std::make_tuple(std::cos(14.137 * j / steps), std::sin(14.137 * j / steps), std::min(1.0, 2.5 * j / steps));
            }
            auto kink = [&](std::vector<P>& strand, double length) {
                const P p = strand[0];
                const double u = p.x / reach + held.kinkOff, v = p.y / reach + held.kinkOff, w = p.z / reach + held.kinkOff;
                double ways[6];
                for (int k = 0; k < 6; ++k) ways[k] = std::sin(6.2832 * (u * waves[k][0] + v * waves[k][1] + w * waves[k][2]) + waves[k][3]);
                for (int j = 1; j <= steps; ++j) {
                    const double c = std::get<0>(swing[j]), s = std::get<1>(swing[j]);
                    const double much = std::get<2>(swing[j]) * length;
                    strand[j].x += much * (ways[0] * c + ways[3] * s);
                    strand[j].y += much * (ways[1] * c + ways[4] * s);
                    strand[j].z += much * (ways[2] * c + ways[5] * s);
                }
            };

            // Clumps: tufts, each about a fibre of its own that those near it lean in to, more toward their tips.
            std::vector<std::vector<P>> tufts;
            std::map<std::tuple<int64_t, int64_t, int64_t>, std::vector<size_t>> cells;
            const double size = std::max(1e-4, held.clumpSize);
            auto cell = [&](double value) { return int64_t(std::floor(value / size)); };
            // Guides, where the Fur material follows them; with Clump, they are the tufts, and no others are made.
            const Guides lead(mode != GUIDE_NONE ? guideStrands : std::vector<std::vector<P>>(), steps);
            const bool guided = mode != GUIDE_NONE && !lead.roots.empty();
            if (clumps > 0 && total / (size * size) < double(count) && !(guided && mode == GUIDE_CLUMP)) {
                const int64_t many = std::min<int64_t>(count, std::max<int64_t>(1, int64_t(total / (size * size))));
                for (int64_t k = 0; k < many; ++k) {
                    const Placed q = place(other);
                    double near = std::sqrt(q.nx * q.nx + q.ny * q.ny + q.nz * q.nz);
                    if (near == 0.0) near = 1.0;
                    const double length = held.length * (1.0 - held.sclJitter * .5) * weight(LENGTH, q.picked, q.r, q.s, q.t);
                    std::vector<P> middle = fibre(q.x, q.y, q.z, q.nx / near, q.ny / near, q.nz / near, length, weight(BEND, q.picked, q.r, q.s, q.t));
                    if (kinked) kink(middle, length);
                    cells[std::make_tuple(cell(q.x), cell(q.y), cell(q.z))].push_back(tufts.size());
                    tufts.push_back(std::move(middle));
                }
            }

            strands.reserve(size_t(count));
            for (int64_t made = 0; made < count; ++made) {
                const Placed q = place(chance);
                // A vector map gives the fibre its way and its length: the vector at its root (none where it is nothing).
                double base = held.length, nx = q.nx, ny = q.ny, nz = q.nz;
                const bool vectored = !vectorMap.empty();
                if (vectored) {
                    const double* v = &vectorMap[q.picked * 9];
                    const double vx = v[0] * q.r + v[3] * q.s + v[6] * q.t;
                    const double vy = v[1] * q.r + v[4] * q.s + v[7] * q.t;
                    const double vz = v[2] * q.r + v[5] * q.s + v[8] * q.t;
                    base = std::sqrt(vx * vx + vy * vy + vz * vz);
                    if (base > 0) { nx = vx / base; ny = vy / base; nz = vz / base; }
                }
                const double off = held.nrmJitter;
                double dx = nx + off * (2 * chance.random() - 1);
                double dy = ny + off * (2 * chance.random() - 1);
                double dz = nz + off * (2 * chance.random() - 1);
                const double first = chance.random(), next = chance.random();
                double length = base * (1.0 - held.sclJitter * first) * (1.0 - held.growthJitter * next * .5);
                if (vectored && !(base > 0)) continue;
                if (!maps[DENSITY].empty() && other.random() > weight(DENSITY, q.picked, q.r, q.s, q.t)) continue;
                length *= weight(LENGTH, q.picked, q.r, q.s, q.t);
                if (length <= 0) continue;
                const bool stray = other.random() < held.strays;
                if (stray) {
                    const double wild = .6 * held.straysAmp;
                    dx = dx + wild * (2 * other.random() - 1);
                    dy = dy + wild * (2 * other.random() - 1);
                    dz = dz + wild * (2 * other.random() - 1);
                }
                double near = std::sqrt(dx * dx + dy * dy + dz * dz);
                if (near == 0.0) near = 1.0;
                dx /= near; dy /= near; dz /= near;
                std::vector<P> strand;
                bool shaped = false;
                const P here{q.x, q.y, q.z};
                if (guided && mode != GUIDE_CLUMP) {
                    if (mode == GUIDE_RANGE) {
                        // Fur only within reach of a guide, of the form of those it is within reach of.
                        const auto close = lead.within(here, guideRange);
                        if (close.empty()) continue;
                        strand = lead.blended(close, here, guideRange, guideLength);
                        shaped = true;
                    } else if (mode == GUIDE_SHAPE) {
                        strand = lead.placed(lead.nearest(here), here, length * guideLength);
                        shaped = true;
                    } else {
                        // Direction: the nearest guide's way out of the surface; with Length, Guide Length too.
                        const P& way = lead.directions[lead.nearest(here)];
                        dx = way.x; dy = way.y; dz = way.z;
                        if (mode == GUIDE_DIRLEN) length *= guideLength;
                    }
                }
                if (!shaped) strand = fibre(q.x, q.y, q.z, dx, dy, dz, length, weight(BEND, q.picked, q.r, q.s, q.t));
                if (kinked) kink(strand, length);
                if (guided && mode == GUIDE_CLUMP && clumps > 0 && !stray) {
                    // Gathered to the nearest guide within reach, as to a tuft: its form at its root, as long as this fibre.
                    const auto close = lead.within(here, guideRange);
                    if (!close.empty()) {
                        size_t index = close[0].first;
                        double least = close[0].second;
                        for (const auto& entry : close)
                            if (entry.second < least) { index = entry.first; least = entry.second; }
                        const std::vector<P> middle = lead.placed(index, lead.roots[index], length);
                        const double much = clumps * weight(CLUMP, q.picked, q.r, q.s, q.t);
                        for (int j = 1; j <= steps; ++j) {
                            const double lean_in = much * j / steps;
                            strand[j].x += (middle[j].x - strand[j].x) * lean_in;
                            strand[j].y += (middle[j].y - strand[j].y) * lean_in;
                            strand[j].z += (middle[j].z - strand[j].z) * lean_in;
                        }
                    }
                }
                if (!tufts.empty() && !stray) {
                    const int64_t cx = cell(q.x), cy = cell(q.y), cz = cell(q.z);
                    bool found = false;
                    size_t best = 0;
                    double least = 1e30;
                    for (int64_t i = cx - 1; i <= cx + 1; ++i)
                        for (int64_t j = cy - 1; j <= cy + 1; ++j)
                            for (int64_t k = cz - 1; k <= cz + 1; ++k) {
                                const auto here = cells.find(std::make_tuple(i, j, k));
                                if (here == cells.end()) continue;
                                for (size_t which : here->second) {
                                    const P& m = tufts[which][0];
                                    const double far = (m.x - q.x) * (m.x - q.x) + (m.y - q.y) * (m.y - q.y) + (m.z - q.z) * (m.z - q.z);
                                    if (far < least) { best = which; least = far; found = true; }
                                }
                            }
                    if (found) {
                        const std::vector<P>& middle = tufts[best];
                        const double much = clumps * weight(CLUMP, q.picked, q.r, q.s, q.t);
                        for (int j = 1; j <= steps; ++j) {
                            const double lean_in = much * j / steps;
                            strand[j].x += (middle[j].x - strand[j].x) * lean_in;
                            strand[j].y += (middle[j].y - strand[j].y) * lean_in;
                            strand[j].z += (middle[j].z - strand[j].z) * lean_in;
                        }
                    }
                }
                if (curls > 0) {
                    const double wide = curls * weight(CURL, q.picked, q.r, q.s, q.t) * std::max(0.0, held.curlRadius) * length * .12;
                    double ax, ay, az;
                    if (std::fabs(dx) < .6) { ax = 0.0; ay = -dz; az = dy; } else { ax = -dz; ay = 0.0; az = dx; }
                    double span = std::sqrt(ax * ax + ay * ay + az * az);
                    if (span == 0.0) span = 1.0;
                    ax /= span; ay /= span; az /= span;
                    const double bx = dy * az - dz * ay, by = dz * ax - dx * az, bz = dx * ay - dy * ax;
                    const double phase = other.random() * 6.2832;
                    const double cp = std::cos(phase), sp = std::sin(phase);
                    for (int j = 1; j <= steps; ++j) {
                        const double ct = std::get<0>(wound[j]), st = std::get<1>(wound[j]);
                        const double out = std::get<2>(wound[j]) * wide;
                        const double c = (flat ? 0.0 : cp * ct - sp * st - cp) * out, w = (sp * ct + cp * st - sp) * out;
                        strand[j].x += ax * c + bx * w;
                        strand[j].y += ay * c + by * w;
                        strand[j].z += az * c + bz * w;
                    }
                }
                if (frizzed) {
                    for (int j = 1; j <= steps; ++j) {
                        const double along = double(j) / steps;
                        const double much = (held.frizAmp + (held.frizAmpTip - held.frizAmp) * along) * length * .2 * along;
                        strand[j].x += much * (2 * other.random() - 1);
                        strand[j].y += much * (2 * other.random() - 1);
                        strand[j].z += much * (2 * other.random() - 1);
                    }
                }
                members[group[q.picked]].push_back(strands.size());
                // The fibre's width as a share of the radii, from the width map (fur.py's weight('width')).
                if (widthMap.empty()) widths.push_back(1.0);
                else {
                    const double* w = &widthMap[q.picked * 3];
                    widths.push_back(std::min(1.0, std::max(0.0, w[0] * q.r + w[1] * q.s + w[2] * q.t)));
                }
                strands.push_back(std::move(strand));
            }
        }

        const std::string prefix = argv[2];
        const bool tapered = std::fabs(root - tip) > 1e-12;
        const bool scaled = !widthMap.empty();
        std::vector<int64_t> told{wanted, int64_t(strands.size()), int64_t(members.size())};
        for (const auto& entry : members) {
            const std::vector<size_t>& which = entry.second;
            uint64_t points = 0;
            for (size_t index : which) points += strands[index].size();
            std::vector<uint32_t> counts;
            counts.reserve(which.size());
            std::vector<float> placed, across;
            placed.reserve(size_t(points) * 4);
            across.reserve(size_t(points) * 2);
            std::vector<double> lengths;
            for (size_t k = 0; k < which.size(); ++k) {
                const std::vector<P>& strand = strands[which[k]];
                counts.push_back(uint32_t(strand.size()));
                lengths.assign(1, 0.0);
                for (size_t j = 1; j < strand.size(); ++j) {
                    const double x = strand[j].x - strand[j - 1].x, y = strand[j].y - strand[j - 1].y, z = strand[j].z - strand[j - 1].z;
                    lengths.push_back(lengths.back() + std::sqrt(x * x + y * y + z * z));
                }
                const double whole = lengths.back() != 0.0 ? lengths.back() : 1.0;
                const float fibre_at = float((double(k) + .5) / double(which.size()));
                for (size_t j = 0; j < strand.size(); ++j) {
                    const double along = lengths[j] / whole;
                    placed.push_back(float(strand[j].x)); placed.push_back(float(strand[j].y)); placed.push_back(float(strand[j].z));
                    placed.push_back(float((tapered ? root + (tip - root) * along : root) * (scaled ? widths[which[k]] : 1.0)));
                    across.push_back(fibre_at); across.push_back(float(along));
                }
            }
            std::ofstream target(prefix + "." + std::to_string(entry.first) + ".mfc", std::ios::binary);
            const uint32_t fibres = uint32_t(which.size());
            const float ends[2] = {float(root), float(tip)};
            target.write("MFC1", 4);
            target.write(reinterpret_cast<const char*>(&fibres), sizeof(fibres));
            target.write(reinterpret_cast<const char*>(&points), sizeof(points));
            target.write(reinterpret_cast<const char*>(ends), sizeof(ends));
            target.write(reinterpret_cast<const char*>(counts.data()), counts.size() * sizeof(uint32_t));
            target.write(reinterpret_cast<const char*>(placed.data()), placed.size() * sizeof(float));
            target.write(reinterpret_cast<const char*>(across.data()), across.size() * sizeof(float));
            if (!target) throw std::runtime_error("the fur could not be written");
            told.push_back(entry.first); told.push_back(int64_t(which.size())); told.push_back(int64_t(points));
        }
        std::ofstream info(prefix + ".info", std::ios::binary);
        const double ends[2] = {root, tip};
        info.write(reinterpret_cast<const char*>(told.data()), told.size() * sizeof(int64_t));
        info.write(reinterpret_cast<const char*>(ends), sizeof(ends));
        if (!info) throw std::runtime_error("the fur could not be written");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "modo_fur_grow: " << error.what() << std::endl;
        return 1;
    }
}
