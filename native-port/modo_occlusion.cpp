// modo_occlusion: how open each of a set of points is, as Modo's Occlusion texture measures it, for the MoonRay for Modo
// kit to hand MoonRay, XPU2 and MoonLightIPR as a weight at each point of a mesh (occlusion.py).
//
//   modo_occlusion <input.moc> <output.bin>
//
// Input, little-endian: "MOC1"; the triangle count, the point count, the rays a point (uint32 each); the distance and
// the spread in radians (float32 each); then the triangles that block rays, nine floats each (three corners in the
// world); then the points, six floats each (place and normal, in the world). Output: a float32 for each point, 1 wholly
// open, 0 closed in.
//
// The measure, fitted to Modo's own renders (tools/probe_gui_occlusion_layer.py: a floor meeting a wall, five settings;
// within 0.031 of Modo at every distance, 0.013 on average): rays leave the point spread by the cosine within the
// spread of its normal, each meeting something within the distance taking away (1 - t / distance)^3 of the light; how
// open the point is is 1 less the mean of that. The rays are a Hammersley set turned by an angle of each point's own, so
// that neighbouring points do not share their gaps. The work is spread over every core.
#include <embree4/rtcore.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

namespace {

struct Header {
    char magic[4];
    uint32_t triangles, points, rays;
    float distance, spread;
};

float radicalInverse(uint32_t bits) {
    bits = (bits << 16u) | (bits >> 16u);
    bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
    bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
    bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
    bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
    return float(bits) * 2.3283064365386963e-10f;
}

uint32_t hash(uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
    return x;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("usage: modo_occlusion <input.moc> <output.bin>");
        std::ifstream in(argv[1], std::ios::binary);
        Header head{};
        if (!in.read(reinterpret_cast<char*>(&head), sizeof(head)) || std::memcmp(head.magic, "MOC1", 4) != 0)
            throw std::runtime_error("not an occlusion request");
        if (head.rays == 0 || head.rays > 4096 || !(head.distance > 0.0f)) throw std::runtime_error("bad settings");
        std::vector<float> corners(size_t(head.triangles) * 9), points(size_t(head.points) * 6);
        if (!in.read(reinterpret_cast<char*>(corners.data()), std::streamsize(corners.size() * 4)) ||
            !in.read(reinterpret_cast<char*>(points.data()), std::streamsize(points.size() * 4)))
            throw std::runtime_error("the request is truncated");

        RTCDevice device = rtcNewDevice(nullptr);
        if (!device) throw std::runtime_error("Embree would not start");
        RTCScene scene = rtcNewScene(device);
        if (head.triangles) {
            RTCGeometry geometry = rtcNewGeometry(device, RTC_GEOMETRY_TYPE_TRIANGLE);
            float* vertices = static_cast<float*>(rtcSetNewGeometryBuffer(geometry, RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3,
                                                                           3 * sizeof(float), size_t(head.triangles) * 3));
            uint32_t* indices = static_cast<uint32_t*>(rtcSetNewGeometryBuffer(geometry, RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3,
                                                                                3 * sizeof(uint32_t), head.triangles));
            std::memcpy(vertices, corners.data(), corners.size() * 4);
            for (uint32_t i = 0; i < head.triangles * 3; ++i) indices[i] = i;
            rtcCommitGeometry(geometry);
            rtcAttachGeometry(scene, geometry);
            rtcReleaseGeometry(geometry);
        }
        rtcCommitScene(scene);

        // Rays leave a little off the surface, as far as the scene's size calls for.
        float low[3] = {1e30f, 1e30f, 1e30f}, high[3] = {-1e30f, -1e30f, -1e30f};
        for (size_t i = 0; i < corners.size(); ++i) {
            low[i % 3] = std::min(low[i % 3], corners[i]);
            high[i % 3] = std::max(high[i % 3], corners[i]);
        }
        float size = 0.0f;
        for (int k = 0; k < 3; ++k) size = std::max(size, high[k] - low[k]);
        const float lift = std::max(1e-5f, size * 1e-5f);
        const float cosMax = std::cos(std::min(std::max(head.spread, 1e-4f), 1.5707963f));

        std::vector<float> open(head.points, 1.0f);
        std::atomic<uint32_t> next{0};
        const unsigned cores = std::max(1u, std::thread::hardware_concurrency());
        std::vector<std::thread> workers;
        for (unsigned w = 0; w < cores; ++w)
            workers.emplace_back([&] {
                for (uint32_t p; (p = next.fetch_add(64)) < head.points;) {
                    for (uint32_t q = p; q < std::min(head.points, p + 64); ++q) {
                        const float* at = &points[size_t(q) * 6];
                        float n[3] = {at[3], at[4], at[5]};
                        const float length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
                        if (!(length > 0.0f)) continue;
                        for (float& c : n) c /= length;
                        // A frame about the normal.
                        float t[3] = {std::fabs(n[0]) < 0.9f ? 1.0f : 0.0f, std::fabs(n[0]) < 0.9f ? 0.0f : 1.0f, 0.0f};
                        float b[3] = {n[1] * t[2] - n[2] * t[1], n[2] * t[0] - n[0] * t[2], n[0] * t[1] - n[1] * t[0]};
                        float bl = std::sqrt(b[0] * b[0] + b[1] * b[1] + b[2] * b[2]);
                        for (float& c : b) c /= bl;
                        float u[3] = {b[1] * n[2] - b[2] * n[1], b[2] * n[0] - b[0] * n[2], b[0] * n[1] - b[1] * n[0]};
                        const float turn = float(hash(q * 2654435761u + 7u)) * 2.3283064365386963e-10f;
                        float lost = 0.0f;
                        for (uint32_t r = 0; r < head.rays; ++r) {
                            const float a = (float(r) + 0.5f) / float(head.rays);
                            const float c = std::sqrt(cosMax * cosMax + (1.0f - cosMax * cosMax) * a);
                            const float s = std::sqrt(std::max(0.0f, 1.0f - c * c));
                            float phi = 6.2831853f * (radicalInverse(r) + turn);
                            const float cx = s * std::cos(phi), cy = s * std::sin(phi);
                            RTCRayHit hit{};
                            hit.ray.org_x = at[0] + n[0] * lift;
                            hit.ray.org_y = at[1] + n[1] * lift;
                            hit.ray.org_z = at[2] + n[2] * lift;
                            hit.ray.dir_x = u[0] * cx + b[0] * cy + n[0] * c;
                            hit.ray.dir_y = u[1] * cx + b[1] * cy + n[1] * c;
                            hit.ray.dir_z = u[2] * cx + b[2] * cy + n[2] * c;
                            hit.ray.tnear = 0.0f;
                            hit.ray.tfar = head.distance;
                            hit.ray.mask = 0xFFFFFFFFu;
                            hit.hit.geomID = RTC_INVALID_GEOMETRY_ID;
                            rtcIntersect1(scene, &hit);
                            if (hit.hit.geomID != RTC_INVALID_GEOMETRY_ID) {
                                const float k = 1.0f - hit.ray.tfar / head.distance;
                                lost += k * k * k;
                            }
                        }
                        open[q] = std::min(1.0f, std::max(0.0f, 1.0f - lost / float(head.rays)));
                    }
                }
            });
        for (std::thread& worker : workers) worker.join();
        rtcReleaseScene(scene);
        rtcReleaseDevice(device);

        std::ofstream out(argv[2], std::ios::binary | std::ios::trunc);
        out.write(reinterpret_cast<const char*>(open.data()), std::streamsize(open.size() * 4));
        if (!out) throw std::runtime_error("cannot write the output");
        std::cout << head.points << " points, " << head.triangles << " triangles" << std::endl;
        return 0;
    } catch (const std::exception& problem) {
        std::cerr << "modo_occlusion: " << problem.what() << std::endl;
        return 1;
    }
}
