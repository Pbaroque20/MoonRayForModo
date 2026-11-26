// Modo's Blob and Sprite items for MoonRay, made from their particles (kit: moonray_modo/particles.py).
//
//   modo_particles <request> <answer>
//
// The request ("MPR1", little endian) holds what to make, the particles and their settings:
//   char[4] "MPR1"; uint32 mode (1 a blob's surface, 2 a sprite's fog); uint32 count; uint32 flags (1: velocities);
//   float level (a blob: the field's threshold); float voxel (the cell size, world units); uint32 table size N;
//   float table[N] (a sprite: its fog's density from the centre (0) out to its radius (N-1), per unit of length);
//   then for each particle: float x, y, z, radius, weight (a sprite: its density), and with velocities float vx, vy, vz
//   (units a second).
//
// A blob's answer ("MPM1"): Modo's blob field, each particle's (1 - d^2 / radius^2)^3 out to its radius summed, cut at
// the level (Modo renders the surface where the sum is 1 - Level; measured, tools/probe_cl_blob_field.py). The field is
// laid in a sparse grid, cut into faces (OpenVDB's volumeToMesh), and each point taken onto the true surface along the
// field's slope (two Newton steps on the particles' own sum), its velocity the particles' weighted by their share of
// the field there. Faces face out (Modo's winding: the corners turn anticlockwise seen from outside).
//   char[4] "MPM1"; uint32 points; uint32 faces; uint32 corners; uint32 flags (1: velocities);
//   float points[3 * points]; [float velocities[3 * points]]; int32 counts[faces]; int32 corners[corners]
//
// A sprite's answer is a VDB file: a float grid "density" of extinction per unit length (each particle's table times
// its weight, summed), a fog volume, and with velocities a vector grid "v" (the particles' velocities weighted by their
// density). Its last line on stdout: "sprite <active voxels>".
#include <openvdb/openvdb.h>
#include <openvdb/tools/Composite.h>
#include <openvdb/tools/VolumeToMesh.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace {

struct Particle {
    float x, y, z, radius, weight;
    float vx, vy, vz;
};

struct Request {
    uint32_t mode = 0, flags = 0;
    float level = 0.5f, voxel = 0.1f;
    std::vector<float> table;
    std::vector<Particle> particles;
};

template <typename T> T take(const std::vector<char>& data, size_t& at) {
    if (at + sizeof(T) > data.size()) throw std::runtime_error("the request is cut short");
    T value;
    std::memcpy(&value, data.data() + at, sizeof(T));
    at += sizeof(T);
    return value;
}

Request read(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("the request cannot be read");
    std::vector<char> data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    if (data.size() < 4 || std::memcmp(data.data(), "MPR1", 4)) throw std::runtime_error("not a particles request");
    size_t at = 4;
    Request r;
    r.mode = take<uint32_t>(data, at);
    const uint32_t count = take<uint32_t>(data, at);
    r.flags = take<uint32_t>(data, at);
    r.level = take<float>(data, at);
    r.voxel = take<float>(data, at);
    const uint32_t n = take<uint32_t>(data, at);
    for (uint32_t i = 0; i < n; ++i) r.table.push_back(take<float>(data, at));
    r.particles.reserve(count);
    const bool moving = r.flags & 1;
    for (uint32_t i = 0; i < count; ++i) {
        Particle p{};
        p.x = take<float>(data, at), p.y = take<float>(data, at), p.z = take<float>(data, at);
        p.radius = take<float>(data, at), p.weight = take<float>(data, at);
        if (moving) p.vx = take<float>(data, at), p.vy = take<float>(data, at), p.vz = take<float>(data, at);
        if (std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z) && p.radius > 0.0f && std::isfinite(p.radius))
            r.particles.push_back(p);
    }
    if (!(r.voxel > 0.0f) || !std::isfinite(r.voxel)) throw std::runtime_error("the cell size is not usable");
    return r;
}

unsigned threads() {
    return std::max(1u, std::min(32u, std::thread::hardware_concurrency()));
}

// Each part of the particles laid into a grid of its own on a thread of its own, the grids then summed.
template <typename Splat>
openvdb::FloatGrid::Ptr laid(const Request& r, Splat splat, openvdb::Vec3SGrid::Ptr* carried = nullptr) {
    const unsigned n = threads();
    std::vector<openvdb::FloatGrid::Ptr> grids(n);
    std::vector<openvdb::Vec3SGrid::Ptr> moving(n);
    std::vector<std::thread> workers;
    const size_t count = r.particles.size();
    for (unsigned t = 0; t < n; ++t) {
        grids[t] = openvdb::FloatGrid::create(0.0f);
        moving[t] = openvdb::Vec3SGrid::create(openvdb::Vec3f(0.0f));
        workers.emplace_back([&, t]() {
            auto at = grids[t]->getAccessor();
            openvdb::Vec3SGrid::Accessor held = moving[t]->getAccessor();
            openvdb::Vec3SGrid::Accessor* moved = carried ? &held : nullptr;
            for (size_t i = count * t / n; i < count * (t + 1) / n; ++i) splat(r.particles[i], at, moved);
        });
    }
    for (auto& w : workers) w.join();
    for (unsigned t = 1; t < n; ++t) {
        openvdb::tools::compSum(*grids[0], *grids[t]);
        if (carried) openvdb::tools::compSum(*moving[0], *moving[t]);
    }
    if (carried) *carried = moving[0];
    return grids[0];
}

// The particles by cell of a grid as wide as the largest radius, for asking which reach a point.
struct Lookup {
    float cell;
    std::unordered_map<int64_t, std::vector<uint32_t>> cells;
    static int64_t key(int i, int j, int k) {
        return (int64_t(i) & 0x1fffff) | ((int64_t(j) & 0x1fffff) << 21) | ((int64_t(k) & 0x1fffff) << 42);
    }
    explicit Lookup(const std::vector<Particle>& ps) {
        float most = 1e-6f;
        for (const auto& p : ps) most = std::max(most, p.radius);
        cell = most;
        for (uint32_t i = 0; i < ps.size(); ++i)
            cells[key(int(std::floor(ps[i].x / cell)), int(std::floor(ps[i].y / cell)), int(std::floor(ps[i].z / cell)))].push_back(i);
    }
    template <typename F> void near(const openvdb::Vec3f& p, F visit) const {
        const int i0 = int(std::floor(p.x() / cell)), j0 = int(std::floor(p.y() / cell)), k0 = int(std::floor(p.z() / cell));
        for (int i = i0 - 1; i <= i0 + 1; ++i)
            for (int j = j0 - 1; j <= j0 + 1; ++j)
                for (int k = k0 - 1; k <= k0 + 1; ++k) {
                    auto found = cells.find(key(i, j, k));
                    if (found == cells.end()) continue;
                    for (uint32_t index : found->second) visit(index);
                }
    }
};

// The blob field at a point, its slope, and the particles' velocities weighted by their share of it.
void field(const Request& r, const Lookup& lookup, const openvdb::Vec3f& p, float& value, openvdb::Vec3f& slope, openvdb::Vec3f* velocity) {
    value = 0.0f;
    slope = openvdb::Vec3f(0.0f);
    openvdb::Vec3f carried(0.0f);
    lookup.near(p, [&](uint32_t index) {
        const Particle& q = r.particles[index];
        const openvdb::Vec3f d(p.x() - q.x, p.y() - q.y, p.z() - q.z);
        const float rr = q.radius * q.radius;
        const float s = d.lengthSqr() / rr;
        if (s >= 1.0f) return;
        const float u = 1.0f - s;
        const float f = u * u * u;
        value += f;
        slope += d * (-6.0f * u * u / rr);
        carried += openvdb::Vec3f(q.vx, q.vy, q.vz) * f;
    });
    if (velocity) *velocity = value > 0.0f ? carried / value : openvdb::Vec3f(0.0f);
}

int blob(const Request& r, const char* answer) {
    const float v = r.voxel, level = r.level;
    const bool moving = r.flags & 1;
    auto grid = laid(r, [v](const Particle& p, openvdb::FloatGrid::Accessor& at, openvdb::Vec3SGrid::Accessor*) {
        const float rr = p.radius * p.radius;
        const int x0 = int(std::floor((p.x - p.radius) / v)), x1 = int(std::ceil((p.x + p.radius) / v));
        const int y0 = int(std::floor((p.y - p.radius) / v)), y1 = int(std::ceil((p.y + p.radius) / v));
        const int z0 = int(std::floor((p.z - p.radius) / v)), z1 = int(std::ceil((p.z + p.radius) / v));
        for (int i = x0; i <= x1; ++i)
            for (int j = y0; j <= y1; ++j)
                for (int k = z0; k <= z1; ++k) {
                    const float dx = i * v - p.x, dy = j * v - p.y, dz = k * v - p.z;
                    const float s = (dx * dx + dy * dy + dz * dz) / rr;
                    if (s >= 1.0f) continue;
                    const float u = 1.0f - s;
                    const openvdb::Coord c(i, j, k);
                    at.setValue(c, at.getValue(c) + u * u * u);
                }
    });
    grid->setTransform(openvdb::math::Transform::createLinearTransform(v));
    std::vector<openvdb::Vec3s> points;
    std::vector<openvdb::Vec3I> triangles;
    std::vector<openvdb::Vec4I> quads;
    openvdb::tools::volumeToMesh(*grid, points, triangles, quads, double(level), 0.0);
    const Lookup lookup(r.particles);
    std::vector<openvdb::Vec3f> velocities(moving ? points.size() : 0);
    // Each point onto the surface, along the field's slope; never farther than a cell from where the grid put it.
    {
        const unsigned n = threads();
        std::vector<std::thread> workers;
        for (unsigned t = 0; t < n; ++t)
            workers.emplace_back([&, t]() {
                for (size_t i = points.size() * t / n; i < points.size() * (t + 1) / n; ++i) {
                    const openvdb::Vec3f start = points[i];
                    openvdb::Vec3f p = start, slope;
                    float value;
                    for (int step = 0; step < 3; ++step) {
                        field(r, lookup, p, value, slope, nullptr);
                        const float g = slope.lengthSqr();
                        if (!(g > 1e-20f)) break;
                        openvdb::Vec3f moved = p - slope * ((value - level) / g);
                        const openvdb::Vec3f off = moved - start;
                        if (off.length() > v) moved = start + off * (v / off.length());
                        p = moved;
                    }
                    points[i] = p;
                    if (moving) {
                        openvdb::Vec3f carried;
                        field(r, lookup, p, value, slope, &carried);
                        velocities[i] = carried;
                    }
                }
            });
        for (auto& w : workers) w.join();
    }
    // Which way the faces turn: outward is down the slope. volumeToMesh turns them all alike, so the faces are asked
    // by vote and turned together where most face in.
    long long out = 0, in = 0;
    auto vote = [&](const openvdb::Vec3f& a, const openvdb::Vec3f& b, const openvdb::Vec3f& c) {
        const openvdb::Vec3f normal = (b - a).cross(c - a);
        float value;
        openvdb::Vec3f slope;
        field(r, lookup, (a + b + c) / 3.0f, value, slope, nullptr);
        const float d = normal.dot(-slope);
        if (d > 0) ++out; else if (d < 0) ++in;
    };
    const size_t sample = std::max<size_t>(1, (quads.size() + triangles.size()) / 2000);
    for (size_t i = 0; i < quads.size(); i += sample) vote(points[quads[i][0]], points[quads[i][1]], points[quads[i][2]]);
    for (size_t i = 0; i < triangles.size(); i += sample) vote(points[triangles[i][0]], points[triangles[i][1]], points[triangles[i][2]]);
    const bool turn = in > out;
    std::ofstream file(answer, std::ios::binary);
    if (!file) throw std::runtime_error("the answer cannot be written");
    const uint32_t header[5] = {uint32_t(points.size()), uint32_t(quads.size() + triangles.size()), uint32_t(4 * quads.size() + 3 * triangles.size()),
                                uint32_t(moving ? 1 : 0), 0};
    file.write("MPM1", 4);
    file.write(reinterpret_cast<const char*>(header), sizeof(header));
    file.write(reinterpret_cast<const char*>(points.data()), points.size() * sizeof(openvdb::Vec3s));
    if (moving) file.write(reinterpret_cast<const char*>(velocities.data()), velocities.size() * sizeof(openvdb::Vec3f));
    std::vector<int32_t> counts;
    counts.reserve(quads.size() + triangles.size());
    counts.insert(counts.end(), quads.size(), 4);
    counts.insert(counts.end(), triangles.size(), 3);
    file.write(reinterpret_cast<const char*>(counts.data()), counts.size() * sizeof(int32_t));
    std::vector<int32_t> corners;
    corners.reserve(header[2]);
    for (const auto& q : quads) {
        if (turn) corners.insert(corners.end(), {int32_t(q[3]), int32_t(q[2]), int32_t(q[1]), int32_t(q[0])});
        else corners.insert(corners.end(), {int32_t(q[0]), int32_t(q[1]), int32_t(q[2]), int32_t(q[3])});
    }
    for (const auto& t : triangles) {
        if (turn) corners.insert(corners.end(), {int32_t(t[2]), int32_t(t[1]), int32_t(t[0])});
        else corners.insert(corners.end(), {int32_t(t[0]), int32_t(t[1]), int32_t(t[2])});
    }
    file.write(reinterpret_cast<const char*>(corners.data()), corners.size() * sizeof(int32_t));
    file.close();
    std::cout << "blob " << points.size() << " points " << counts.size() << " faces" << std::endl;
    return 0;
}

int sprite(const Request& r, const char* answer) {
    const float v = r.voxel;
    const bool moving = r.flags & 1;
    const std::vector<float>& table = r.table;
    if (table.size() < 2) throw std::runtime_error("a sprite needs its density table");
    const float last = float(table.size() - 1);
    openvdb::Vec3SGrid::Ptr carried;
    auto grid = laid(r, [&](const Particle& p, openvdb::FloatGrid::Accessor& at, openvdb::Vec3SGrid::Accessor* moved) {
        const int x0 = int(std::floor((p.x - p.radius) / v)), x1 = int(std::ceil((p.x + p.radius) / v));
        const int y0 = int(std::floor((p.y - p.radius) / v)), y1 = int(std::ceil((p.y + p.radius) / v));
        const int z0 = int(std::floor((p.z - p.radius) / v)), z1 = int(std::ceil((p.z + p.radius) / v));
        const openvdb::Vec3f velocity(p.vx, p.vy, p.vz);
        for (int i = x0; i <= x1; ++i)
            for (int j = y0; j <= y1; ++j)
                for (int k = z0; k <= z1; ++k) {
                    const float dx = i * v - p.x, dy = j * v - p.y, dz = k * v - p.z;
                    const float d = std::sqrt(dx * dx + dy * dy + dz * dz) / p.radius;
                    if (d >= 1.0f) continue;
                    const float at_ = d * last;
                    const int low = std::min(int(at_), int(table.size()) - 2);
                    const float t = at_ - low;
                    const float value = p.weight * (table[low] * (1.0f - t) + table[low + 1] * t);
                    if (!(value > 0.0f)) continue;
                    const openvdb::Coord c(i, j, k);
                    at.setValue(c, at.getValue(c) + value);
                    if (moved) moved->setValue(c, moved->getValue(c) + velocity * value);
                }
    }, moving ? &carried : nullptr);
    const auto transform = openvdb::math::Transform::createLinearTransform(v);
    grid->setTransform(transform);
    grid->setName("density");
    grid->setGridClass(openvdb::GRID_FOG_VOLUME);
    openvdb::GridPtrVec written{grid};
    if (moving && carried) {
        // The weighted sum of velocities, divided by the density where there is any.
        auto density = grid->getConstAccessor();
        for (auto it = carried->beginValueOn(); it; ++it) {
            const float d = density.getValue(it.getCoord());
            it.setValue(d > 0.0f ? *it / d : openvdb::Vec3f(0.0f));
        }
        carried->setTransform(transform);
        carried->setName("v");
        carried->setVectorType(openvdb::VEC_CONTRAVARIANT_RELATIVE);
        written.push_back(carried);
    }
    openvdb::io::File out(answer);
    out.write(written);
    out.close();
    std::cout << "sprite " << grid->activeVoxelCount() << std::endl;
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 3) {
            std::cerr << "usage: modo_particles <request> <answer>" << std::endl;
            return 2;
        }
        openvdb::initialize();
        const Request r = read(argv[1]);
        if (r.mode == 1) return blob(r, argv[2]);
        if (r.mode == 2) return sprite(r, argv[2]);
        std::cerr << "unknown mode " << r.mode << std::endl;
        return 2;
    } catch (const std::exception& e) {
        std::cerr << "modo_particles: " << e.what() << std::endl;
        return 1;
    }
}
