// Sol's indexer: geometry, not shading (sol/DESIGN.md, "Sol's indexer").
//
// XPU2's indexer classifies a scene's objects by the shading families they need and seeds each cell on the device
// that renders them best. Sol's indexer does the same work for geometry:
//
//   - The geometry index (GeometryIndex): every plan mesh as clusters of 128 consecutive triangles with their bounds,
//     and, once a probe stands on a mesh, its welded topology (scan.h). Kept across frames while the plan's mesh is
//     the same object, as XPU2 keeps tessellations.
//   - The virtual surface (VirtualSurface): the visible geometry of the frame, reconstructed by probes in geometric
//     passes. A quadtree over the frame whose corners are probes; each probe's radial scan says which surface it
//     stands on and where that surface ends. Pass 0 is a coarse lattice (stride s0); a quad that has not converged is
//     split in four (new probes at its edges' middles and centre) for the next pass, down to the finest stride.
//   - It is handed to the devices as one small piece (pack, SurfaceView): sites and quads, which any device evaluates
//     per pixel (evaluate) without the meshes; the meshes stay in each device's ray structures for the paths.
//
// A quad has converged, within the tolerance, when its reconstruction (the Bregman Delaunay interpolation of its four
// probes, bvd.h) is the visible surface over it and its margin:
//   1. its four probes stand on one connected surface (each probe's scan reaches the others' triangles);
//   2. no scan found the surface ending inside it (a silhouette, a border of the mesh, a hole);
//   3. the sandwich gap (bvd.h sandwichGap) is under the tolerance at every pixel: the geometric variance the passes
//      converge within;
//   4. the scanned triangles over it lie within the tolerance of the reconstruction (a crease or a saddle's relief
//      between the probes, where the sandwich bound does not hold);
//   5. no other geometry lies in front of the reconstruction there (the clusters' bounds, then their triangles).
// A quad whose four probes all miss has converged as background when no geometry's bounds reach it.
#pragma once
#include "async_cpu.h"
#include "scan.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>

namespace sol {

namespace async = xpu2::interactive::async;
namespace resume = xpu2::interactive::resume;

// Workers kept for the process: a pass hands them its items and takes part itself. Starting a dozen threads for each
// of a pass's steps cost more than the steps' work (about 4 ms a step on Windows).
class Pool {
public:
    explicit Pool(unsigned workers) {
        for (unsigned i = 0; i < workers; ++i) threads.emplace_back([this] { loop(); });
    }
    ~Pool() {
        {
            std::lock_guard<std::mutex> l(m);
            stop = true;
        }
        wake.notify_all();
        for (auto& t : threads) t.join();
    }
    void run(size_t n, const std::function<void(size_t)>& f) {
        if (n == 0) return;
        std::lock_guard<std::mutex> one(caller);  // one job at a time
        {
            std::lock_guard<std::mutex> l(m);
            job = &f;
            count = n;
            next = 0;
            busy = threads.size();
            ++generation;
        }
        wake.notify_all();
        work();
        std::unique_lock<std::mutex> l(m);
        done.wait(l, [&] { return busy == 0; });
        job = nullptr;
    }

private:
    std::vector<std::thread> threads;
    std::mutex m, caller;
    std::condition_variable wake, done;
    const std::function<void(size_t)>* job = nullptr;
    size_t count = 0, busy = 0;
    uint64_t generation = 0;
    std::atomic<size_t> next{0};
    bool stop = false;
    void work() {
        for (size_t k; (k = next.fetch_add(1)) < count;) (*job)(k);
    }
    void loop() {
        uint64_t seen = 0;
        for (;;) {
            {
                std::unique_lock<std::mutex> l(m);
                wake.wait(l, [&] { return stop || generation != seen; });
                if (stop) return;
                seen = generation;
            }
            work();
            std::lock_guard<std::mutex> l(m);
            if (--busy == 0) done.notify_one();
        }
    }
};

template <class F>
void parallel(unsigned threads, size_t n, F f) {
    static Pool pool(std::max(1u, threads) - 1);
    pool.run(n, std::function<void(size_t)>(f));
}

inline double secondsSince(std::chrono::steady_clock::time_point t) {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - t).count();
}

// ---------------------------------------------------------------------------------------------------------------
// The geometry index.

struct Cluster {
    float lo[3], hi[3];
    uint32_t first = 0, count = 0;
};

struct MeshIndex {
    const cpu::MeshData* data = nullptr;  // what it was made from
    bool triangles = false;               // a triangle mesh (else points or curves: bounds alone)
    bool occludes = false;                // seen by camera rays (and not a volume's container)
    std::vector<Cluster> clusters;
    std::shared_ptr<const Topology> topology;
};

struct GeometryIndex {
    static constexpr uint32_t ClusterSize = 128;
    std::vector<MeshIndex> meshes;  // plan mesh i
    size_t clusterCount = 0;

    // The clusters of every plan mesh not already indexed from the same data.
    void index(const cpu::Plan& plan, unsigned threads) {
        meshes.resize(plan.meshes.size());
        parallel(threads, plan.meshes.size(), [&](size_t i) {
            const cpu::Mesh& e = plan.meshes[i];
            MeshIndex& mi = meshes[i];
            if (mi.data == e.data.get() && !e.instance) return;
            const cpu::MeshData& m = *e.data;
            mi = MeshIndex{};
            mi.data = e.data.get();
            mi.occludes = (e.visibility & 1u) && e.volume < 0 && !m.gate;
            mi.triangles = !m.points && !m.curveBasis && !m.triangles.empty();
            auto grow = [](Cluster& c, const surface::V3& p, float r) {
                c.lo[0] = std::min(c.lo[0], p.x - r), c.lo[1] = std::min(c.lo[1], p.y - r), c.lo[2] = std::min(c.lo[2], p.z - r);
                c.hi[0] = std::max(c.hi[0], p.x + r), c.hi[1] = std::max(c.hi[1], p.y + r), c.hi[2] = std::max(c.hi[2], p.z + r);
            };
            auto fresh = [] {
                Cluster c;
                for (int k = 0; k < 3; ++k) c.lo[k] = 3.4e38f, c.hi[k] = -3.4e38f;
                return c;
            };
            if (mi.triangles) {
                for (uint32_t f = 0; f < m.triangles.size(); f += ClusterSize) {
                    Cluster c = fresh();
                    c.first = f;
                    c.count = std::min<uint32_t>(ClusterSize, uint32_t(m.triangles.size()) - f);
                    for (uint32_t t = f; t < f + c.count; ++t) {
                        const auto& tr = m.triangles[t];
                        grow(c, vertexOf(e, m, tr.a), 0), grow(c, vertexOf(e, m, tr.b), 0), grow(c, vertexOf(e, m, tr.c), 0);
                    }
                    mi.clusters.push_back(c);
                }
            } else if (m.points) {
                Cluster c = fresh();
                for (unsigned p = 0; p < m.points && p < m.positions.size(); ++p)
                    grow(c, vertexOf(e, m, p), p < m.pointRadius.size() ? m.pointRadius[p] : 0.0f);
                mi.clusters.push_back(c);
            } else if (m.curveBasis) {
                Cluster c = fresh();
                for (size_t p = 0; p + 3 < m.curvePoints.size(); p += 4) {
                    const surface::V3 q{m.curvePoints[p], m.curvePoints[p + 1], m.curvePoints[p + 2]};
                    grow(c, q, m.curvePoints[p + 3]);
                }
                if (e.instance) {
                    // Curves under an instance: their box placed as a whole (its corners), conservatively.
                    Cluster placed = fresh();
                    for (int k = 0; k < 8; ++k) {
                        const surface::V3 q{(k & 1) ? c.hi[0] : c.lo[0], (k & 2) ? c.hi[1] : c.lo[1], (k & 4) ? c.hi[2] : c.lo[2]};
                        const float* x = e.objectToWorld;
                        grow(placed, {q.x * x[0] + q.y * x[3] + q.z * x[6] + x[9], q.x * x[1] + q.y * x[4] + q.z * x[7] + x[10], q.x * x[2] + q.y * x[5] + q.z * x[8] + x[11]}, 0);
                    }
                    c = placed;
                }
                mi.clusters.push_back(c);
            }
        });
        clusterCount = 0;
        for (const auto& mi : meshes) clusterCount += mi.clusters.size();
    }

    // The topologies of these meshes, made where missing.
    void topologies(const cpu::Plan& plan, std::vector<uint32_t> geoms, unsigned threads) {
        std::sort(geoms.begin(), geoms.end());
        geoms.erase(std::unique(geoms.begin(), geoms.end()), geoms.end());
        geoms.erase(std::remove_if(geoms.begin(), geoms.end(), [&](uint32_t g) { return bool(meshes[g].topology); }), geoms.end());
        parallel(threads, geoms.size(), [&](size_t i) {
            meshes[geoms[i]].topology = std::make_shared<const Topology>(buildTopology(*plan.meshes[geoms[i]].data));
        });
    }
};

// A cluster seen from the camera: its frame bounds and its nearest inverse depth (an upper bound of w over it).
struct FrameCluster {
    double x0, y0, x1, y1, wMax;
    uint32_t mesh, cluster;
};

struct FrameClusters {
    int bin = 8, binsX = 0, binsY = 0;
    std::vector<FrameCluster> clusters;
    std::vector<std::vector<uint32_t>> bins;  // the clusters whose bounds reach each bin of the frame
    template <class F>
    void each(double x0, double y0, double x1, double y1, std::vector<uint32_t>& seen, F f) const {
        seen.clear();
        const int bx0 = std::max(0, int(std::floor(x0 / bin))), bx1 = std::min(binsX - 1, int(std::floor(x1 / bin)));
        const int by0 = std::max(0, int(std::floor(y0 / bin))), by1 = std::min(binsY - 1, int(std::floor(y1 / bin)));
        for (int by = by0; by <= by1; ++by)
            for (int bx = bx0; bx <= bx1; ++bx)
                for (uint32_t c : bins[size_t(by) * binsX + bx]) {
                    if (std::find(seen.begin(), seen.end(), c) != seen.end()) continue;
                    seen.push_back(c);
                    const FrameCluster& k = clusters[c];
                    if (k.x1 < x0 || k.x0 > x1 || k.y1 < y0 || k.y0 > y1) continue;
                    if (!f(k)) return;
                }
    }
};

inline FrameClusters liftClusters(const GeometryIndex& index, const Frame& frame, unsigned width, unsigned height, double margin) {
    FrameClusters out;
    out.binsX = int((width + out.bin - 1) / out.bin);
    out.binsY = int((height + out.bin - 1) / out.bin);
    out.bins.assign(size_t(out.binsX) * out.binsY, {});
    for (uint32_t g = 0; g < index.meshes.size(); ++g) {
        const MeshIndex& mi = index.meshes[g];
        if (!mi.occludes) continue;
        for (uint32_t c = 0; c < mi.clusters.size(); ++c) {
            const Cluster& k = mi.clusters[c];
            FrameCluster f{1e300, 1e300, -1e300, -1e300, 0, g, c};
            bool everywhere = false;
            for (int i = 0; i < 8 && !everywhere; ++i) {
                const surface::V3 p{(i & 1) ? k.hi[0] : k.lo[0], (i & 2) ? k.hi[1] : k.lo[1], (i & 4) ? k.hi[2] : k.lo[2]};
                double x, y, w;
                if (!frame.lift(p, x, y, w)) {
                    everywhere = true;  // the box reaches the camera's plane: it may be anywhere in the frame
                    break;
                }
                f.x0 = std::min(f.x0, x), f.x1 = std::max(f.x1, x), f.y0 = std::min(f.y0, y), f.y1 = std::max(f.y1, y);
                f.wMax = std::max(f.wMax, w);
            }
            if (everywhere) f = {-1e300, -1e300, 1e300, 1e300, 1e300, g, c};
            if (f.x1 < -margin || f.y1 < -margin || f.x0 > width + margin || f.y0 > height + margin) continue;
            const uint32_t id = uint32_t(out.clusters.size());
            out.clusters.push_back(f);
            const int bx0 = std::max(0, int(std::floor(std::max(-1.0, f.x0 - margin) / out.bin)));
            const int bx1 = std::min(out.binsX - 1, int(std::floor(std::min(double(width), f.x1 + margin) / out.bin)));
            const int by0 = std::max(0, int(std::floor(std::max(-1.0, f.y0 - margin) / out.bin)));
            const int by1 = std::min(out.binsY - 1, int(std::floor(std::min(double(height), f.y1 + margin) / out.bin)));
            for (int by = by0; by <= by1; ++by)
                for (int bx = bx0; bx <= bx1; ++bx) out.bins[size_t(by) * out.binsX + bx].push_back(id);
        }
    }
    return out;
}

// ---------------------------------------------------------------------------------------------------------------
// Clipping a triangle to a region of the frame, its inverse depth carried (linear over a lifted triangle).

struct Vertex3 {
    double x, y, w;
};

struct Poly {
    Vertex3 v[16];
    int n = 0;
};

// Keep the part of p where a x + b y + c >= 0.
inline Poly clip(const Poly& p, double a, double b, double c) {
    Poly o;
    for (int i = 0; i < p.n; ++i) {
        const Vertex3& s = p.v[i];
        const Vertex3& e = p.v[(i + 1) % p.n];
        const double ds = a * s.x + b * s.y + c, de = a * e.x + b * e.y + c;
        if (ds >= 0 && o.n < 16) o.v[o.n++] = s;
        if ((ds >= 0) != (de >= 0) && o.n < 16) {
            const double t = ds / (ds - de);
            o.v[o.n++] = {s.x + t * (e.x - s.x), s.y + t * (e.y - s.y), s.w + t * (e.w - s.w)};
        }
    }
    return o;
}

// A triangle of a mesh lifted onto the frame, clipped at the camera's near plane first (in camera space).
inline bool liftClipped(const Frame& f, const cpu::Mesh& e, const cpu::MeshData& m, uint32_t prim, double nearClip, Poly& out) {
    const auto& t = m.triangles[prim];
    const uint32_t vi[3] = {t.a, t.b, t.c};
    D3 c[3];
    for (int k = 0; k < 3; ++k) c[k] = f.camera(vertexOf(e, m, vi[k]));
    D3 q[8];
    int n = 0;
    for (int i = 0; i < 3; ++i) {
        const D3& s = c[i];
        const D3& d = c[(i + 1) % 3];
        const double ds = -nearClip - s.z, de = -nearClip - d.z;  // >= 0: in front of the near plane
        if (ds >= 0) q[n++] = s;
        if ((ds >= 0) != (de >= 0)) {
            const double u = ds / (ds - de);
            q[n++] = {s.x + u * (d.x - s.x), s.y + u * (d.y - s.y), s.z + u * (d.z - s.z)};
        }
    }
    out.n = 0;
    for (int i = 0; i < n; ++i) {
        Vertex3 v;
        if (!f.liftCamera(q[i], v.x, v.y, v.w)) continue;
        out.v[out.n++] = v;
    }
    return out.n >= 3;
}

// ---------------------------------------------------------------------------------------------------------------
// The virtual surface.

enum State : uint8_t {
    Background = 0,    // its probes all missed and no geometry's bounds reach it: the environment
    Trusted = 1,       // converged: the reconstruction is the visible surface within the tolerance
    Gap = 2,           // the sandwich gap above the tolerance at the finest stride
    Crease = 3,        // scanned triangles off the reconstruction (a crease, a saddle's relief)
    Disconnected = 4,  // its probes on different surfaces
    Boundary = 5,      // a scan found its surface ending inside (a silhouette, a border, a hole)
    Occluded = 6,      // other geometry in front of the reconstruction
    Edge = 7,          // converged, but phase 1's light changes too fast across it (set by evaluate)
    Miss = 8,          // some probes hit, some missed
    Truncated = 9,     // a scan stopped short (its limits, the camera's plane, or a surface that is not a mesh)
};
constexpr int States = 10;
inline const char* stateName(int s) {
    static const char* names[States] = {"background", "trusted", "gap", "crease", "disconnected", "boundary", "occluded", "edge", "miss", "truncated"};
    return names[s];
}

struct Site {
    int px = 0, py = 0, level = 0;
    bool hit = false, scannable = false;
    uint32_t geom = ~0u, prim = 0;
    Plane h;
    double w = 0;
    Patch patch;
    float rgb[3] = {0, 0, 0};
};

struct Quad {
    int x0 = 0, y0 = 0, x1 = 0, y1 = 0, level = 0;
    int corner[4] = {-1, -1, -1, -1};  // (x0, y0), (x1, y0), (x1, y1), (x0, y1): counter-clockwise in the frame's raster
    int child = -1;                    // the first of four children, -1 a leaf
    uint8_t state = Truncated;
    bool diagAC = true;
    int8_t sign = 1;
    double gap = 0;   // its largest relative sandwich gap
    Plane half[2];    // the Bregman Delaunay planes: (a, b, c) and (a, c, d) for the diagonal ac, else (a, b, d) and (b, c, d)
};

struct SurfaceOptions {
    unsigned s0 = 16, minStride = 2, rings = 128, tris = 16384, threads = 12;
    double tol = 0.002;   // the geometric tolerance: relative inverse depth (relative depth)
    double margin = 1.0;  // pixels around a quad its reconstruction must also hold (the pixel filter's reach)
};

struct PassStats {
    int level = 0;
    size_t quads = 0, newSites = 0, sites = 0, refined = 0;
    size_t states[States] = {};
    double traceSeconds = 0, scanSeconds = 0, testSeconds = 0, seconds = 0;
};

class VirtualSurface {
public:
    unsigned width = 0, height = 0, s0 = 16, rootX = 0, rootY = 0;
    std::vector<Site> sites;
    std::vector<Quad> quads;  // the roots first, row by row
    std::vector<PassStats> passes;
    size_t visited = 0;
    double clusterSeconds = 0, topologySeconds = 0;

    void build(const cpu::Plan& plan, const async::CpuScene& scene, const Frame& frame, GeometryIndex& index, const SurfaceOptions& op) {
        width = plan.width, height = plan.height, s0 = op.s0;
        sites.clear(), quads.clear(), passes.clear();
        siteAt.assign(size_t(width) * height, -1);
        visited = 0;
        auto t = std::chrono::steady_clock::now();
        const FrameClusters clusters = liftClusters(index, frame, width, height, op.margin);
        clusterSeconds = secondsSince(t);
        topologySeconds = 0;
        std::vector<int> xs, ys;
        for (int x = 0; x < int(width) - 1; x += int(s0)) xs.push_back(x);
        xs.push_back(int(width) - 1);
        for (int y = 0; y < int(height) - 1; y += int(s0)) ys.push_back(y);
        ys.push_back(int(height) - 1);
        rootX = unsigned(xs.size() - 1), rootY = unsigned(ys.size() - 1);
        std::vector<int> pending;
        for (unsigned j = 0; j < rootY; ++j)
            for (unsigned i = 0; i < rootX; ++i) {
                pending.push_back(int(quads.size()));
                quads.push_back(makeQuad(xs[i], ys[j], xs[i + 1], ys[j + 1], 0));
            }
        size_t scanned = 0;
        for (int level = 0; !pending.empty(); ++level) {
            const auto began = std::chrono::steady_clock::now();
            PassStats ps;
            ps.level = level;
            ps.quads = pending.size();
            ps.newSites = sites.size() - scanned;
            // The new probes: their camera rays, then their meshes' topologies, then their scans.
            t = std::chrono::steady_clock::now();
            parallel(op.threads, sites.size() - scanned, [&](size_t i) { trace(plan, scene, sites[scanned + i]); });
            ps.traceSeconds = secondsSince(t);
            t = std::chrono::steady_clock::now();
            std::vector<uint32_t> geoms;
            for (size_t i = scanned; i < sites.size(); ++i)
                if (sites[i].scannable) geoms.push_back(sites[i].geom);
            index.topologies(plan, geoms, op.threads);
            topologySeconds += secondsSince(t);
            t = std::chrono::steady_clock::now();
            const double window = double(s0 >> std::min(level, 30)) + op.margin + 1.0;
            parallel(op.threads, sites.size() - scanned, [&](size_t i) {
                Site& s = sites[scanned + i];
                if (!s.scannable) return;
                const double cx = s.px + 0.5, cy = s.py + 0.5;
                s.patch = scan(frame, plan, *index.meshes[s.geom].topology, s.geom, s.prim, cx - window, cy - window, cx + window, cy + window,
                               op.rings, op.tris);
                s.h = planeThrough(s.patch.seedTri.x, s.patch.seedTri.y, s.patch.seedTri.w);
                if (!s.h.ok) {
                    s.scannable = false;
                    return;
                }
                s.w = s.h.at(cx, cy);
            });
            for (size_t i = scanned; i < sites.size(); ++i) visited += sites[i].patch.visited;
            ps.scanSeconds = secondsSince(t);
            scanned = sites.size();
            // The pass's quads tested; those that have not converged split for the next pass.
            t = std::chrono::steady_clock::now();
            parallel(op.threads, pending.size(), [&](size_t i) { test(plan, frame, index, clusters, op, quads[pending[i]]); });
            ps.testSeconds = secondsSince(t);
            std::vector<int> next;
            for (int q : pending) {
                const Quad c = quads[q];
                if (c.state == Trusted || c.state == Background || c.x1 - c.x0 <= int(op.minStride) || c.y1 - c.y0 <= int(op.minStride)) {
                    ++ps.states[c.state];
                    continue;
                }
                const int xm = (c.x0 + c.x1) / 2, ym = (c.y0 + c.y1) / 2;
                const int first = int(quads.size());
                quads[q].child = first;
                quads.push_back(makeQuad(c.x0, c.y0, xm, ym, level + 1));
                quads.push_back(makeQuad(xm, c.y0, c.x1, ym, level + 1));
                quads.push_back(makeQuad(xm, ym, c.x1, c.y1, level + 1));
                quads.push_back(makeQuad(c.x0, ym, xm, c.y1, level + 1));
                for (int k = 0; k < 4; ++k) next.push_back(first + k);
                ++ps.refined;
            }
            ps.sites = sites.size();
            ps.seconds = secondsSince(began);
            passes.push_back(ps);
            pending = std::move(next);
        }
    }

    // Each site's pixel (for a probe frame) and its radiance taken from that frame's picture.
    void takeRadiance(const std::vector<float>& rgba) {
        for (auto& s : sites)
            for (int c = 0; c < 3; ++c) s.rgb[c] = rgba[(size_t(s.py) * width + s.px) * 4 + c];
    }

private:
    std::vector<int> siteAt;

    int siteFor(int x, int y, int level) {
        int& i = siteAt[size_t(y) * width + x];
        if (i < 0) {
            i = int(sites.size());
            Site s;
            s.px = x, s.py = y, s.level = level;
            sites.push_back(s);
        }
        return i;
    }

    Quad makeQuad(int x0, int y0, int x1, int y1, int level) {
        Quad q;
        q.x0 = x0, q.y0 = y0, q.x1 = x1, q.y1 = y1, q.level = level;
        q.corner[0] = siteFor(x0, y0, level);
        q.corner[1] = siteFor(x1, y0, level);
        q.corner[2] = siteFor(x1, y1, level);
        q.corner[3] = siteFor(x0, y1, level);
        return q;
    }

    static void trace(const cpu::Plan& plan, const async::CpuScene& scene, Site& s) {
        surface::Ray ray;
        if (!surface::cameraRay(plan.camera, s.px + 0.5f, s.py + 0.5f, ray)) return;
        ray.mask = 1u;  // a camera ray
        async::CpuBackend backend{scene};
        const resume::Hit h = backend.trace(ray);
        if (h.geom == ~0u) return;
        s.hit = true;
        s.geom = h.geom;
        s.prim = h.prim;
        const auto& m = *plan.meshes[h.geom].data;
        s.scannable = !m.points && !m.curveBasis && !m.triangles.empty();
    }

    // The quad's reconstruction at (x, y): the half its point lies in and that half's plane.
    static int halfAt(const Quad& q, const Site* const c[4], double x, double y) {
        // The diagonal ac splits it into abc (b's side) and acd; bd into abd (a's side) and bcd.
        const Site& p = q.diagAC ? *c[0] : *c[1];
        const Site& r = q.diagAC ? *c[2] : *c[3];
        const Site& ref = q.diagAC ? *c[1] : *c[0];
        const double dx = r.px - p.px, dy = r.py - p.py;
        const double side = dx * (y - (p.py + 0.5)) - dy * (x - (p.px + 0.5));
        const double refSide = dx * (ref.py - p.py) - dy * (ref.px - p.px);
        return (side >= 0) == (refSide >= 0) ? 0 : 1;
    }

    // Whether a clipped piece of a triangle departs from the quad's reconstruction by more than tol (relative): in
    // front only (another surface), or on either side (the quad's own scanned surface).
    static bool departs(const Quad& q, const Site* const c[4], const Poly& tri, double r[4], double tol, bool bothSides) {
        for (int h = 0; h < 2; ++h) {
            Poly p = clip(tri, 1, 0, -r[0]);
            p = clip(p, -1, 0, r[2]);
            p = clip(p, 0, 1, -r[1]);
            p = clip(p, 0, -1, r[3]);
            if (p.n < 3) return false;
            // The half: the diagonal's side holding its third corner.
            const Site& a = q.diagAC ? *c[0] : *c[1];
            const Site& b = q.diagAC ? *c[2] : *c[3];
            const Site& ref = h == 0 ? (q.diagAC ? *c[1] : *c[0]) : (q.diagAC ? *c[3] : *c[2]);
            const double ax = a.px + 0.5, ay = a.py + 0.5, dx = b.px - a.px, dy = b.py - a.py;
            // n . (p - a) with n = (-dy, dx), oriented towards ref.
            double nx = -dy, ny = dx;
            if (nx * (ref.px + 0.5 - ax) + ny * (ref.py + 0.5 - ay) < 0) nx = -nx, ny = -ny;
            p = clip(p, nx, ny, -(nx * ax + ny * ay));
            for (int i = 0; i < p.n; ++i) {
                const double t = q.half[h].at(p.v[i].x, p.v[i].y);
                const double d = (p.v[i].w - t) / std::max(std::fabs(t), 1e-30);
                if (d > tol || (bothSides && d < -tol)) return true;
            }
        }
        return false;
    }

    static bool segmentMeetsRect(const Segment& s, const double r[4]) {
        // Liang-Barsky.
        double t0 = 0, t1 = 1;
        const double dx = s.x1 - s.x0, dy = s.y1 - s.y0;
        const double p[4] = {-dx, dx, -dy, dy}, qv[4] = {s.x0 - r[0], r[2] - s.x0, s.y0 - r[1], r[3] - s.y0};
        for (int i = 0; i < 4; ++i) {
            if (p[i] == 0) {
                if (qv[i] < 0) return false;
                continue;
            }
            const double t = qv[i] / p[i];
            if (p[i] < 0) t0 = std::max(t0, t);
            else t1 = std::min(t1, t);
            if (t0 > t1) return false;
        }
        return true;
    }

    void test(const cpu::Plan& plan, const Frame& frame, const GeometryIndex& index, const FrameClusters& clusters, const SurfaceOptions& op,
              Quad& q) const {
        const Site* c[4] = {&sites[q.corner[0]], &sites[q.corner[1]], &sites[q.corner[2]], &sites[q.corner[3]]};
        double r[4] = {q.x0 + 0.5 - op.margin, q.y0 + 0.5 - op.margin, q.x1 + 0.5 + op.margin, q.y1 + 0.5 + op.margin};
        std::vector<uint32_t> seen;
        const int hits = c[0]->hit + c[1]->hit + c[2]->hit + c[3]->hit;
        if (hits == 0) {
            // The environment, unless some geometry reaches into it: its bounds, then its triangles.
            bool any = false;
            clusters.each(r[0], r[1], r[2], r[3], seen, [&](const FrameCluster& k) {
                const MeshIndex& mi = index.meshes[k.mesh];
                if (!mi.triangles) {
                    any = true;
                    return false;
                }
                const Cluster& cl = mi.clusters[k.cluster];
                const cpu::Mesh& oe = plan.meshes[k.mesh];
                for (uint32_t prim = cl.first; prim < cl.first + cl.count && !any; ++prim) {
                    Poly p;
                    if (!liftClipped(frame, oe, *oe.data, prim, plan.camera.nearClip, p)) continue;
                    p = clip(p, 1, 0, -r[0]);
                    p = clip(p, -1, 0, r[2]);
                    p = clip(p, 0, 1, -r[1]);
                    p = clip(p, 0, -1, r[3]);
                    any = p.n >= 3;
                }
                return !any;
            });
            q.state = any ? Miss : Background;
            return;
        }
        if (hits < 4) {
            q.state = Miss;
            return;
        }
        for (const Site* s : c)
            if (!s->scannable || s->patch.truncated || s->patch.behind) {
                q.state = Truncated;
                return;
            }
        // 1. One connected surface.
        for (int i = 0; i < 4; ++i)
            for (int j = 0; j < 4; ++j)
                if (i != j && (c[i]->geom != c[j]->geom || !c[i]->patch.contains(c[j]->prim))) {
                    q.state = Disconnected;
                    return;
                }
        // 2. No end of the surface inside.
        for (const Site* s : c)
            for (const Segment& g : s->patch.bounds)
                if (segmentMeetsRect(g, r)) {
                    q.state = Boundary;
                    return;
                }
        // 3. The Bregman Delaunay triangulation of the four probes and its sandwich gap.
        double x[4], y[4], w[4];
        Plane h[4];
        for (int k = 0; k < 4; ++k) x[k] = c[k]->px + 0.5, y[k] = c[k]->py + 0.5, w[k] = c[k]->w, h[k] = c[k]->h;
        const int sign = convexity(x, y, w, h, 4);
        q.sign = int8_t(sign);
        q.diagAC = quadDiagonal(x, y, w, sign == 0 ? 1 : sign);
        const int tri[2][3] = {{0, 1, 2}, {0, 2, 3}}, triBD[2][3] = {{0, 1, 3}, {1, 2, 3}};
        for (int k = 0; k < 2; ++k) {
            const int* t = q.diagAC ? tri[k] : triBD[k];
            const double tx[3] = {x[t[0]], x[t[1]], x[t[2]]}, ty[3] = {y[t[0]], y[t[1]], y[t[2]]}, tw[3] = {w[t[0]], w[t[1]], w[t[2]]};
            q.half[k] = planeThrough(tx, ty, tw);
            if (!q.half[k].ok) {
                q.state = Gap;
                return;
            }
        }
        double gap = 0;
        for (int py = q.y0; py <= q.y1; ++py)
            for (int px = q.x0; px <= q.x1; ++px) {
                const double cx = px + 0.5, cy = py + 0.5;
                const double t = q.half[halfAt(q, c, cx, cy)].at(cx, cy);
                gap = std::max(gap, sandwichGap(cx, cy, t, h, 4, sign) / std::max(t, 1e-30));
            }
        q.gap = gap;
        if (gap > op.tol) {
            q.state = Gap;
            return;
        }
        const cpu::Mesh& e = plan.meshes[c[0]->geom];
        const cpu::MeshData& m = *e.data;
        const double nearClip = plan.camera.nearClip;
        // 4. The scanned surface over it within the tolerance of the reconstruction.
        for (const Site* s : c)
            for (uint32_t prim : s->patch.prims) {
                Poly p;
                if (liftClipped(frame, e, m, prim, nearClip, p) && departs(q, c, p, r, op.tol, true)) {
                    q.state = Crease;
                    return;
                }
            }
        // 5. Nothing else in front of it.
        double qmin = 1e300;
        for (int k = 0; k < 4; ++k) {
            const double cx = k & 1 ? r[2] : r[0], cy = k & 2 ? r[3] : r[1];
            qmin = std::min({qmin, q.half[0].at(cx, cy), q.half[1].at(cx, cy)});
        }
        bool occluded = false;
        clusters.each(r[0], r[1], r[2], r[3], seen, [&](const FrameCluster& k) {
            if (k.wMax <= qmin * (1 + op.tol)) return true;
            const MeshIndex& mi = index.meshes[k.mesh];
            if (!mi.triangles) {
                occluded = true;  // points or curves: their bounds alone
                return false;
            }
            const Cluster& cl = mi.clusters[k.cluster];
            const cpu::Mesh& oe = plan.meshes[k.mesh];
            const cpu::MeshData& om = *oe.data;
            for (uint32_t prim = cl.first; prim < cl.first + cl.count; ++prim) {
                if (k.mesh == c[0]->geom && (c[0]->patch.contains(prim) || c[1]->patch.contains(prim) || c[2]->patch.contains(prim) ||
                                             c[3]->patch.contains(prim)))
                    continue;  // its own surface, checked above
                Poly p;
                if (liftClipped(frame, oe, om, prim, nearClip, p) && departs(q, c, p, r, op.tol, false)) {
                    occluded = true;
                    return false;
                }
            }
            return true;
        });
        q.state = occluded ? Occluded : Trusted;
    }
};

// ---------------------------------------------------------------------------------------------------------------
// The piece the devices take: the virtual surface without the meshes, and its evaluation at a pixel.

struct PackedHeader {
    uint32_t magic = 0x31534f4c;  // "LOS1"
    uint32_t width = 0, height = 0, s0 = 0, rootX = 0, rootY = 0, sites = 0, quads = 0;
    float tauR = 0.25f, pad = 0;
};
struct PackedSite {
    uint16_t px, py;
    uint32_t hit;
    float a, b, c, w;
    float rgb[3];
};
struct PackedQuad {
    uint16_t x0, y0, x1, y1;
    int32_t child;
    uint8_t state, diagAC;
    int8_t sign;
    uint8_t pad;
    uint32_t corner[4];
    float half[2][3];
};

inline std::vector<uint8_t> pack(const VirtualSurface& v, float tauR) {
    PackedHeader hd;
    hd.width = v.width, hd.height = v.height, hd.s0 = v.s0, hd.rootX = v.rootX, hd.rootY = v.rootY;
    hd.sites = uint32_t(v.sites.size()), hd.quads = uint32_t(v.quads.size()), hd.tauR = tauR;
    std::vector<uint8_t> out(sizeof(PackedHeader) + v.sites.size() * sizeof(PackedSite) + v.quads.size() * sizeof(PackedQuad));
    std::memcpy(out.data(), &hd, sizeof hd);
    auto* ps = reinterpret_cast<PackedSite*>(out.data() + sizeof hd);
    for (size_t i = 0; i < v.sites.size(); ++i) {
        const Site& s = v.sites[i];
        ps[i] = PackedSite{uint16_t(s.px), uint16_t(s.py), uint32_t(s.hit), float(s.h.a), float(s.h.b), float(s.h.c), float(s.w),
                           {s.rgb[0], s.rgb[1], s.rgb[2]}};
    }
    auto* pq = reinterpret_cast<PackedQuad*>(ps + v.sites.size());
    for (size_t i = 0; i < v.quads.size(); ++i) {
        const Quad& q = v.quads[i];
        PackedQuad o{uint16_t(q.x0), uint16_t(q.y0), uint16_t(q.x1), uint16_t(q.y1), q.child, q.state, uint8_t(q.diagAC), q.sign, 0,
                     {uint32_t(q.corner[0]), uint32_t(q.corner[1]), uint32_t(q.corner[2]), uint32_t(q.corner[3])}, {}};
        for (int k = 0; k < 2; ++k) o.half[k][0] = float(q.half[k].a), o.half[k][1] = float(q.half[k].b), o.half[k][2] = float(q.half[k].c);
        pq[i] = o;
    }
    return out;
}

// What the piece says at a pixel. Plain code over the packed arrays: what a GPU thread would run.
struct SurfaceView {
    const PackedHeader* hd = nullptr;
    const PackedSite* sites = nullptr;
    const PackedQuad* quads = nullptr;
    explicit SurfaceView(const std::vector<uint8_t>& bytes) {
        hd = reinterpret_cast<const PackedHeader*>(bytes.data());
        sites = reinterpret_cast<const PackedSite*>(bytes.data() + sizeof(PackedHeader));
        quads = reinterpret_cast<const PackedQuad*>(sites + hd->sites);
    }
};

struct PixelSurface {
    uint8_t state = Truncated;
    int leaf = -1, owner = -1, level = 0;
    float w = 0;       // the reconstruction's inverse depth (0: none)
    float rgb[3] = {0, 0, 0};
};

inline PixelSurface evaluate(const SurfaceView& v, int px, int py) {
    PixelSurface out;
    const PackedHeader& hd = *v.hd;
    const int ix = std::min(px / int(hd.s0), int(hd.rootX) - 1), iy = std::min(py / int(hd.s0), int(hd.rootY) - 1);
    int qi = iy * int(hd.rootX) + ix;
    while (v.quads[qi].child >= 0) {
        const PackedQuad& c0 = v.quads[v.quads[qi].child];
        const bool right = px >= c0.x1, down = py >= c0.y1;
        qi = v.quads[qi].child + (down ? (right ? 2 : 3) : (right ? 1 : 0));
        ++out.level;
    }
    const PackedQuad& q = v.quads[qi];
    out.leaf = qi;
    out.state = q.state;
    const PackedSite* c[4] = {&v.sites[q.corner[0]], &v.sites[q.corner[1]], &v.sites[q.corner[2]], &v.sites[q.corner[3]]};
    const float x = px + 0.5f, y = py + 0.5f;
    // The half (its triangle of corners) and barycentric weights there.
    const int a = q.diagAC ? 0 : 1, b = q.diagAC ? 2 : 3, ref = q.diagAC ? 1 : 0;
    const float dx = float(c[b]->px - c[a]->px), dy = float(c[b]->py - c[a]->py);
    const float side = dx * (y - (c[a]->py + 0.5f)) - dy * (x - (c[a]->px + 0.5f));
    const float refSide = dx * float(c[ref]->py - c[a]->py) - dy * float(c[ref]->px - c[a]->px);
    const int half = (side >= 0) == (refSide >= 0) ? 0 : 1;
    static const int triAC[2][3] = {{0, 1, 2}, {0, 2, 3}}, triBD[2][3] = {{0, 1, 3}, {1, 2, 3}};
    const int* t = q.diagAC ? triAC[half] : triBD[half];
    double tx[3], ty[3], bw[3];
    for (int k = 0; k < 3; ++k) tx[k] = c[t[k]]->px + 0.5, ty[k] = c[t[k]]->py + 0.5;
    if (!barycentric(x, y, tx, ty, bw, 1e-6)) {
        // On the quad's border, past a clamped corner: the nearest corner's.
        bw[0] = 1, bw[1] = bw[2] = 0;
    }
    for (int ch = 0; ch < 3; ++ch) out.rgb[ch] = float(bw[0] * c[t[0]]->rgb[ch] + bw[1] * c[t[1]]->rgb[ch] + bw[2] * c[t[2]]->rgb[ch]);
    // The cell: the corner whose plane predicts the reconstruction best (nearest on a tie).
    float best = 3.4e38f, bestDist = 3.4e38f;
    if (q.state == Trusted) {
        out.w = q.half[half][0] * x + q.half[half][1] * y + q.half[half][2];
        float lo = 3.4e38f, hi = -3.4e38f, mean = 0;
        for (int k = 0; k < 3; ++k) {
            const float* L = c[t[k]]->rgb;
            const float l = 0.2126f * L[0] + 0.7152f * L[1] + 0.0722f * L[2];
            lo = std::min(lo, l), hi = std::max(hi, l), mean += l / 3;
        }
        if ((hi - lo) / (mean + 1e-3f) > hd.tauR) out.state = Edge;
    }
    for (int k = 0; k < 4; ++k) {
        const float d2 = (c[k]->px + 0.5f - x) * (c[k]->px + 0.5f - x) + (c[k]->py + 0.5f - y) * (c[k]->py + 0.5f - y);
        float D = 0;
        if (out.w > 0) D = std::fabs(out.w - (c[k]->a * x + c[k]->b * y + c[k]->c)) / out.w;
        if (D < best - 1e-7f || (D <= best + 1e-7f && d2 < bestDist)) best = std::min(best, D), bestDist = d2, out.owner = int(q.corner[k]);
    }
    return out;
}

}  // namespace sol
