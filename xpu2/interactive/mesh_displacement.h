// Private experimental: MoonRay's displacement of triangle meshes for the path tracer (PATH_TRACER.md). The uniform
// tessellation of PolyMesh::tessellate (TriMesh::generateIndexBufferAndSurfaceSamples and generateVertexBuffer, over
// MeshTessellationUtil's lookups and ring stitching), PolyMesh::displaceMesh through a NormalDisplacement or a
// VectorDisplacement whose maps run on the host (shade_mapnodes.h), and the smooth shading normals PolyMeshCalcNv
// computes after. The tessellated quads become triangles (v0, v1, v3) and (v2, v3, v1), as Embree splits them, each
// with its corners' texture coordinates and primitive attributes taken from its base face (TriMesh::getTriangleST,
// getTriangleAttributes). Included by cpu_scene.h after the map admission. Derived from MoonRay Apache-2.0,
// Copyright 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include <array>
#include <cstdint>
#include <unordered_map>

namespace xpu2::interactive::cpu::displace {

// A place in a base triangle as Embree encodes barycentrics: the weights of corners 1 and 2.
struct Uv {
    float u = 0, v = 0;
};
inline Uv mix(float a, Uv p, float b, Uv q) { return Uv{a * p.u + b * q.u, a * p.v + b * q.v}; }

// MeshTessellationUtil's StitchPoint.
struct StitchPoint {
    int vertex = 0;
    float t = 0, deltaT = 0;
};

// The tessellated mesh before it is placed: quads (v3 == v2 for a triangle), each corner's place in its base face
// (faceVaryingUv), each quad's base face, and each vertex's base face and place there (its surface sample).
struct Tessellation {
    int vertexCount = 0;
    std::vector<int> quads;
    std::vector<Uv> quadUv;
    std::vector<int> quadFace;
    std::vector<int> sampleFace;
    std::vector<Uv> sampleUv;
};

// PolyTopologyIdLookup, PolyFaceTopology and PolyTessellatedVertexLookup for triangles.
struct Lookup {
    std::vector<std::array<int, 3>> corner, edge;
    std::vector<int> outer, edgeStart, edgeCount, interiorStart;
    int total = 0;

    int edgeVertexId(int e, int n, bool reverse) const {
        return reverse ? edgeStart[e] + edgeCount[e] - 1 - n : edgeStart[e] + n;
    }
    int maxEdgeVertexCount(int f) const {
        return std::max(std::max(edgeCount[edge[f][0]], edgeCount[edge[f][1]]), edgeCount[edge[f][2]]);
    }
    int interiorVertexId(int f, int m, int ring, int c, int n) const {
        int offset = 0;
        if (ring > 0) offset += 3 * (m - ring) * ring;
        const int perEdge = m - 2 * ring;
        // otherwise a degenerate ring of one vertex
        if (perEdge > 1) offset += (c * (perEdge - 1) + n) % (3 * (perEdge - 1));
        return interiorStart[f] + offset;
    }
    int ringCount(int f) const { return (maxEdgeVertexCount(f) + 3) / 2; }
};

inline Lookup lookup(const std::vector<Tri>& tris, size_t vertexCount, int edgeVertexCount) {
    Lookup l;
    std::unordered_map<int64_t, int> ids;
    auto key = [](int64_t a, int64_t b) { return a < b ? (b << 32) + a : (a << 32) + b; };
    const size_t faces = tris.size();
    l.corner.resize(faces);
    l.edge.resize(faces);
    for (size_t f = 0; f < faces; ++f) {
        const int c[3] = {int(tris[f].a), int(tris[f].b), int(tris[f].c)};
        for (int v = 0; v < 3; ++v) {
            const int64_t k = key(c[v], c[(v + 1) % 3]);
            auto it = ids.find(k);
            if (it == ids.end()) it = ids.emplace(k, int(ids.size())).first;
            l.corner[f][v] = c[v];
            l.edge[f][v] = it->second;
        }
    }
    l.outer.assign(vertexCount, -1);
    l.edgeStart.assign(ids.size(), -1);
    l.edgeCount.assign(ids.size(), -1);
    l.interiorStart.assign(faces, -1);
    for (size_t f = 0; f < faces; ++f) {
        for (int i = 0; i < 3; ++i)
            if (l.outer[l.corner[f][i]] == -1) l.outer[l.corner[f][i]] = l.total++;
        for (int i = 0; i < 3; ++i) {
            const int e = l.edge[f][i];
            if (l.edgeStart[e] == -1) {
                l.edgeStart[e] = l.total;
                l.edgeCount[e] = edgeVertexCount;  // uniform tessellation: every edge alike
                l.total += edgeVertexCount;
            }
        }
        const int m = l.maxEdgeVertexCount(int(f));
        int interior = 0;
        if (m != 0) interior = m % 2 == 0 ? 3 * m * m / 4 : 1 + 3 * (m * m - 1) / 4;
        l.interiorStart[f] = l.total;
        l.total += interior;
    }
    return l;
}

// generateTriangleStitchRings: the inner ring along corner c's edge and the outer ring on the edge itself.
inline void stitchRings(const Lookup& l, int f, int c, int m, float ringUvDelta, std::vector<StitchPoint>& inner,
                        std::vector<Uv>& innerUv, std::vector<StitchPoint>& outer, std::vector<Uv>& outerUv) {
    const int index0 = c, index1 = (c + 1) % 3;
    const float innerDeltaT = 1.0f / float(1 + m);
    const Uv cornerUv0[3] = {{0.0f, 0.0f}, {1.0f, 0.0f}, {0.0f, 1.0f}};
    const Uv cornerUv1[3] = {{ringUvDelta, ringUvDelta}, {1.0f - 2 * ringUvDelta, ringUvDelta}, {ringUvDelta, 1.0f - 2 * ringUvDelta}};
    const int innerCount = m;
    const float wInner = innerCount == 1 ? 0.0f : 1.0f / float(innerCount - 1);
    inner.resize(size_t(innerCount));
    innerUv.resize(size_t(innerCount));
    for (int i = 0; i < innerCount; ++i) {
        inner[size_t(i)] = StitchPoint{l.interiorVertexId(f, m, 0, c, i), float(i + 1) * innerDeltaT, innerDeltaT};
        innerUv[size_t(i)] = mix(1.0f - float(i) * wInner, cornerUv1[index0], float(i) * wInner, cornerUv1[index1]);
    }
    const int e = l.edge[f][c];
    const int edgeVertices = l.edgeCount[e];
    const int outerCount = edgeVertices + 2;
    const float wOuter = 1.0f / float(outerCount - 1);
    const float outerDeltaT = 1.0f / float(edgeVertices + 1);
    const bool reverse = l.corner[f][index0] > l.corner[f][index1];
    outer.resize(size_t(outerCount));
    outerUv.resize(size_t(outerCount));
    outer[0] = StitchPoint{l.outer[l.corner[f][index0]], 0.0f, outerDeltaT};
    outerUv[0] = cornerUv0[index0];
    for (int i = 0; i < edgeVertices; ++i) {
        outer[size_t(1 + i)] = StitchPoint{l.edgeVertexId(e, i, reverse), float(i + 1) * outerDeltaT, outerDeltaT};
        outerUv[size_t(1 + i)] = mix(1.0f - float(i + 1) * wOuter, cornerUv0[index0], float(i + 1) * wOuter, cornerUv0[index1]);
    }
    outer[size_t(outerCount - 1)] = StitchPoint{l.outer[l.corner[f][index1]], 1.0f, 0.0f};
    outerUv[size_t(outerCount - 1)] = cornerUv0[index1];
}

// stitchRings: quads (and quads with v3 == v2) between an inner and an outer ring.
inline void stitch(const std::vector<StitchPoint>& inner, const std::vector<Uv>& innerUv, const std::vector<StitchPoint>& outer,
                   const std::vector<Uv>& outerUv, int f, Tessellation& out) {
    const int innerCount = int(inner.size()), outerCount = int(outer.size());
    int i = 0, o = 0;
    int v0 = inner[0].vertex, v1 = outer[0].vertex, v2;
    Uv v0Uv = innerUv[0], v1Uv = outerUv[0], v2Uv;
    auto quad = [&](int a, int b, int c, int d, Uv ua, Uv ub, Uv uc, Uv ud) {
        out.quads.insert(out.quads.end(), {a, b, c, d});
        out.quadUv.insert(out.quadUv.end(), {ua, ub, uc, ud});
        out.quadFace.push_back(f);
    };
    while (i < innerCount - 1 && o < outerCount - 1) {
        const StitchPoint& s0 = inner[size_t(i)];
        const StitchPoint& s1 = outer[size_t(o)];
        // both stitch points move forward to a quad when they are close
        const float threshold = 0.5f * std::min(s0.deltaT, s1.deltaT);
        if (std::abs(s0.t - s1.t) < threshold && std::abs(s0.t + s0.deltaT - s1.t - s1.deltaT) < threshold) {
            ++i;
            ++o;
            v2 = outer[size_t(o)].vertex;
            const int v3 = inner[size_t(i)].vertex;
            v2Uv = outerUv[size_t(o)];
            const Uv v3Uv = innerUv[size_t(i)];
            quad(v0, v1, v2, v3, v0Uv, v1Uv, v2Uv, v3Uv);
            v0 = v3;
            v1 = v2;
            v0Uv = v3Uv;
            v1Uv = v2Uv;
        } else if ((s1.t + s1.deltaT) - s0.t >= (s0.t + s0.deltaT) - s1.t) {
            ++i;
            v2 = inner[size_t(i)].vertex;
            v2Uv = innerUv[size_t(i)];
            quad(v0, v1, v2, v2, v0Uv, v1Uv, v2Uv, v2Uv);
            v0 = v2;
            v0Uv = v2Uv;
        } else {
            ++o;
            v2 = outer[size_t(o)].vertex;
            v2Uv = outerUv[size_t(o)];
            quad(v0, v1, v2, v2, v0Uv, v1Uv, v2Uv, v2Uv);
            v1 = v2;
            v1Uv = v2Uv;
        }
    }
    if (i == innerCount - 1) {
        ++o;
        while (o < outerCount) {
            v2 = outer[size_t(o)].vertex;
            v2Uv = outerUv[size_t(o)];
            quad(v0, v1, v2, v2, v0Uv, v1Uv, v2Uv, v2Uv);
            v1 = v2;
            v1Uv = v2Uv;
            ++o;
        }
    }
    if (o == outerCount - 1) {
        ++i;
        while (i < innerCount) {
            v2 = inner[size_t(i)].vertex;
            v2Uv = innerUv[size_t(i)];
            quad(v0, v1, v2, v2, v0Uv, v1Uv, v2Uv, v2Uv);
            v0 = v2;
            v0Uv = v2Uv;
            ++i;
        }
    }
}

// TriMesh::generateIndexBufferAndSurfaceSamples (OpenGL's triangle tessellation: interior rings, then each corner's
// edge stitched to the outermost interior ring).
inline Tessellation tessellate(const std::vector<Tri>& tris, size_t vertexCount, int edgeVertexCount) {
    const Lookup l = lookup(tris, vertexCount, edgeVertexCount);
    Tessellation out;
    out.vertexCount = l.total;
    out.sampleFace.assign(size_t(l.total), 0);
    out.sampleUv.assign(size_t(l.total), Uv{});
    auto sample = [&](int vid, int f, Uv uv) {
        out.sampleFace[size_t(vid)] = f;
        out.sampleUv[size_t(vid)] = uv;
    };
    std::vector<StitchPoint> inner, outer;
    std::vector<Uv> innerUv, outerUv;
    for (int f = 0; f < int(tris.size()); ++f) {
        const int m = l.maxEdgeVertexCount(f);
        if (m == 0) {
            const int a = l.outer[l.corner[f][0]], b = l.outer[l.corner[f][1]], c = l.outer[l.corner[f][2]];
            out.quads.insert(out.quads.end(), {a, b, c, c});
            out.quadUv.insert(out.quadUv.end(), {Uv{0, 0}, Uv{1, 0}, Uv{0, 1}, Uv{0, 1}});
            out.quadFace.push_back(f);
            sample(a, f, Uv{0, 0});
            sample(b, f, Uv{1, 0});
            sample(c, f, Uv{0, 1});
            continue;
        }
        const int interiorRings = l.ringCount(f) - 1;
        // the barycentrics shift from 0 to 1/3 over the rings from the outer vertices to the centre
        const float ringUvDelta = 2.0f / (3.0f * float(m + 1));
        for (int r = 0; r < interiorRings - 1; ++r) {
            const Uv cornerUv0[3] = {{float(r + 1) * ringUvDelta, float(r + 1) * ringUvDelta},
                                     {1.0f - float(2 * (r + 1)) * ringUvDelta, float(r + 1) * ringUvDelta},
                                     {float(r + 1) * ringUvDelta, 1.0f - float(2 * (r + 1)) * ringUvDelta}};
            const Uv cornerUv1[3] = {{float(r + 2) * ringUvDelta, float(r + 2) * ringUvDelta},
                                     {1.0f - float(2 * (r + 2)) * ringUvDelta, float(r + 2) * ringUvDelta},
                                     {float(r + 2) * ringUvDelta, 1.0f - float(2 * (r + 2)) * ringUvDelta}};
            const int edgeVertices = m - 2 * (r + 1);
            const float w0 = 1.0f / float(edgeVertices + 1);
            const float w1 = 1.0f / float(edgeVertices - 1);
            for (int c = 0; c < 3; ++c) {
                const int c1 = (c + 1) % 3, c2 = (c + 2) % 3;
                // corner quad
                out.quads.insert(out.quads.end(), {l.interiorVertexId(f, m, r, c, 0), l.interiorVertexId(f, m, r, c, 1),
                                                   l.interiorVertexId(f, m, r + 1, c, 0),
                                                   l.interiorVertexId(f, m, r, c2, edgeVertices)});
                out.quadUv.insert(out.quadUv.end(), {cornerUv0[c], mix(1.0f - w0, cornerUv0[c], w0, cornerUv0[c1]), cornerUv1[c],
                                                     mix(1.0f - w0, cornerUv0[c], w0, cornerUv0[c2])});
                out.quadFace.push_back(f);
                // edge quads
                for (int n = 1; n < edgeVertices; ++n) {
                    out.quads.insert(out.quads.end(), {l.interiorVertexId(f, m, r, c, n), l.interiorVertexId(f, m, r, c, n + 1),
                                                       l.interiorVertexId(f, m, r + 1, c, n),
                                                       l.interiorVertexId(f, m, r + 1, c, n - 1)});
                    out.quadUv.insert(out.quadUv.end(),
                                      {mix(1.0f - float(n) * w0, cornerUv0[c], float(n) * w0, cornerUv0[c1]),
                                       mix(1.0f - float(n + 1) * w0, cornerUv0[c], float(n + 1) * w0, cornerUv0[c1]),
                                       mix(1.0f - float(n) * w1, cornerUv1[c], float(n) * w1, cornerUv1[c1]),
                                       mix(1.0f - float(n - 1) * w1, cornerUv1[c], float(n - 1) * w1, cornerUv1[c1])});
                    out.quadFace.push_back(f);
                }
                for (int n = 0; n < edgeVertices + 1; ++n)
                    sample(l.interiorVertexId(f, m, r, c, n), f, mix(1.0f - float(n) * w0, cornerUv0[c], float(n) * w0, cornerUv0[c1]));
            }
        }
        // the centre: a triangle for an even count, a vertex for an odd one
        if (m % 2 == 0) {
            const int a = l.interiorVertexId(f, m, interiorRings - 1, 0, 0), b = l.interiorVertexId(f, m, interiorRings - 1, 1, 0),
                      c = l.interiorVertexId(f, m, interiorRings - 1, 2, 0);
            const float k = float(interiorRings) * ringUvDelta, k2 = float(2 * interiorRings) * ringUvDelta;
            const Uv uv0{k, k}, uv1{1.0f - k2, k}, uv2{k, 1.0f - k2};
            out.quads.insert(out.quads.end(), {a, b, c, c});
            out.quadUv.insert(out.quadUv.end(), {uv0, uv1, uv2, uv2});
            out.quadFace.push_back(f);
            sample(a, f, uv0);
            sample(b, f, uv1);
            sample(c, f, uv2);
        } else {
            sample(l.interiorVertexId(f, m, interiorRings - 1, 0, 0), f, Uv{1.0f / 3.0f, 1.0f / 3.0f});
        }
        // each corner's edge stitched to the interior
        const Uv cornerUv[3] = {{0, 0}, {1, 0}, {0, 1}};
        for (int c = 0; c < 3; ++c) {
            stitchRings(l, f, c, m, ringUvDelta, inner, innerUv, outer, outerUv);
            stitch(inner, innerUv, outer, outerUv, f, out);
            const int outerCount = int(outer.size());
            const float w = 1.0f / float(outerCount - 1);
            for (int v = 0; v < outerCount - 1; ++v)
                sample(outer[size_t(v)].vertex, f, mix(1.0f - float(v) * w, cornerUv[c], float(v) * w, cornerUv[(c + 1) % 3]));
        }
    }
    return out;
}

// A displacement shader as its maps evaluate it: NormalDisplacement (height, zero value, height multiplier) or
// VectorDisplacement in tangent space (vector, factor, the tangent space style).
struct Shader {
    enum Kind : unsigned { Normal = 1, Vector = 2 };
    unsigned kind = Normal, program = shade::NoMapProgram;
    unsigned heightReg = shade::MapNoRegister, multiplierReg = shade::MapNoRegister, vectorReg = shade::MapNoRegister;
    float height = 1, zero = 0, multiplier = 1;
    V3 vector{0, 0, 0};
    float factor = 1;
    int style = 0;  // 0 TNB (green up), 1 TBN
};

// The textures as the CPU backend reads them (async_cpu.h's HostTextures).
struct Textures {
    const tex::Image* const* images;
    unsigned count;
    unsigned lookup(unsigned texture, tex::Binding b, const tex::Footprint& f, surface::V3& out) const {
        if (texture >= count || !images[texture]) return tex::Invalid;
        b.image = images[texture];
        return tex::lookup(b, f, out);
    }
};

// NormalDisplacement::displace (evalFloatWithPreAdd and evalFloat: a bound map's average scales a nonzero value)
// and VectorDisplacement::displace (a bound map replaces the value).
inline V3 displacement(const Shader& d, const float* pool, const shade::State& st, const Textures& textures) {
    shade::Color regs[shade::MapMaxRegisters];
    if (d.program != shade::NoMapProgram)
        need(shade::runMapProgram(pool, d.program, st, textures, regs) == tex::Ready, "A displacement map did not evaluate");
    if (d.kind == Shader::Normal) {
        float height = d.height, multiplier = d.multiplier;
        if (!shade::isZero(height) && d.heightReg != shade::MapNoRegister) height *= shade::colorAverage(regs[d.heightReg]) + -d.zero;
        if (!shade::isZero(multiplier) && d.multiplierReg != shade::MapNoRegister)
            multiplier *= shade::colorAverage(regs[d.multiplierReg]);
        return st.N * (height * multiplier);
    }
    V3 v = d.vector;
    if (d.vectorReg != shade::MapNoRegister) v = V3{regs[d.vectorReg].x, regs[d.vectorReg].y, regs[d.vectorReg].z};
    v = v * d.factor;
    const shade::Frame f = shade::frame(st.N, shade::normalize(st.dPds));
    return d.style == 0 ? shade::localToGlobal(f, V3{v.x, v.z, v.y}) : shade::localToGlobal(f, v);
}

// PolyMeshCalcNv::computeVn: each vertex's normal the normalized sum of its faces' (a quad's diagonals crossed, a
// triangle's edges; a quad with v3 == v2 counts twice at v2), (0, 0, 1) where that is not finite.
inline std::vector<V3> smoothNormals(const std::vector<V3>& p, const std::vector<int>& faces, int corners) {
    std::vector<V3> sum(p.size(), V3{0, 0, 0});
    for (size_t f = 0; f + size_t(corners) <= faces.size(); f += size_t(corners)) {
        const V3 n = corners == 4 ? surface::cross(p[size_t(faces[f + 2])] - p[size_t(faces[f])], p[size_t(faces[f + 3])] - p[size_t(faces[f + 1])])
                                  : surface::cross(p[size_t(faces[f + 1])] - p[size_t(faces[f])], p[size_t(faces[f + 2])] - p[size_t(faces[f])]);
        for (int k = 0; k < corners; ++k) sum[size_t(faces[f + size_t(k)])] = sum[size_t(faces[f + size_t(k)])] + n;
    }
    for (auto& n : sum) {
        const float l = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z);
        n = V3{n.x / l, n.y / l, n.z / l};
        if (!surface::finite(n)) n = V3{0, 0, 1};
    }
    return sum;
}

// A base face's attribute (components n) at place uv: a varying (vertex) attribute's corners or a face-varying one's
// weighted (1 - u - v, u, v), as TriMesh::getAttribute and getTriangleAttributes take them on a tessellated mesh.
inline void attributeAt(const float* d, unsigned n, bool faceVarying, const Tri& t, int face, Uv uv, float* out) {
    const size_t i1 = faceVarying ? size_t(face) * 3 : t.a, i2 = faceVarying ? size_t(face) * 3 + 1 : t.b,
                 i3 = faceVarying ? size_t(face) * 3 + 2 : t.c;
    for (unsigned k = 0; k < n; ++k) out[k] = (1.0f - uv.u - uv.v) * d[i1 * n + k] + uv.u * d[i2 * n + k] + uv.v * d[i3 * n + k];
}

// PolyMesh::tessellate and displaceMesh on a prepared mesh (render-space positions, its normals, texture coordinates
// and primitive attributes): tessellated uniformly to edgeVertexCount vertices an edge (none: displaced as it is),
// each vertex displaced once from the first face that has it, by the state at that face's triangle (its geometric
// normal, its texture coordinates' partials and half its corners' differences as the texture footprint), and
// smooth normals computed over the displaced faces. The mesh's own normals are discarded.
inline std::shared_ptr<MeshData> displaceMesh(const MeshData& base, int edgeVertexCount, const Shader& shader, const float* pool,
                                              const Textures& textures, const float* worldToRender) {
    auto out = std::make_shared<MeshData>();
    out->name = base.name;  // no signature: the next frame never reuses a displaced mesh
    for (int i = 0; i < 12; ++i) out->worldToObject[i] = base.worldToObject[i];
    const bool tessellated = edgeVertexCount > 0;
    const bool hasUv = base.uvRate != shade::RateNone && !base.uvs.empty();
    const bool uvFaceVarying = base.uvRate == shade::RateFaceVarying;
    // A base face's st at a place (getTriangleST's attribute at the tessellated corner).
    auto baseSt = [&](int face, Uv uv, float st[2]) { attributeAt(base.uvs.data(), 2, uvFaceVarying, base.triangles[size_t(face)], face, uv, st); };

    Tessellation t;
    std::vector<V3> p;
    if (tessellated) {
        t = tessellate(base.triangles, base.positions.size(), edgeVertexCount);
        // generateVertexBuffer
        p.resize(size_t(t.vertexCount));
        for (int i = 0; i < t.vertexCount; ++i) {
            const Tri& b = base.triangles[size_t(t.sampleFace[size_t(i)])];
            const Uv uv = t.sampleUv[size_t(i)];
            const float w = 1.0f - uv.u - uv.v;
            p[size_t(i)] = base.positions[b.a] * w + base.positions[b.b] * uv.u + base.positions[b.c] * uv.v;
        }
    } else {
        p = base.positions;
    }

    // The faces as displaceMesh walks them: tessellated quads, else the base triangles.
    const int corners = tessellated ? 4 : 3;
    std::vector<int> faces;
    if (tessellated) faces = t.quads;
    else
        for (const Tri& tri : base.triangles) faces.insert(faces.end(), {int(tri.a), int(tri.b), int(tri.c)});
    const size_t faceCount = faces.size() / size_t(corners);
    // A face's triangle corners (getNeighborVertices) and their st (getTriangleST).
    auto triangle = [&](size_t f, bool first, int ids[3], float st[3][2]) {
        const int k[3] = {first ? 0 : 2, first ? 1 : 3, first ? (tessellated ? 3 : 2) : 1};
        for (int j = 0; j < 3; ++j) ids[j] = faces[f * size_t(corners) + size_t(k[j])];
        if (!tessellated) {
            const float d[3][2] = {{0, 0}, {1, 0}, {1, 1}};
            for (int j = 0; j < 3; ++j) {
                if (hasUv) {
                    const size_t i = uvFaceVarying ? f * 3 + size_t(j) : size_t(ids[j]);
                    st[j][0] = base.uvs[2 * i];
                    st[j][1] = base.uvs[2 * i + 1];
                } else {
                    st[j][0] = d[j][0];
                    st[j][1] = d[j][1];
                }
            }
            return;
        }
        const float d[2][3][2] = {{{0, 0}, {1, 0}, {0, 1}}, {{1, 1}, {0, 1}, {1, 0}}};
        for (int j = 0; j < 3; ++j) {
            if (hasUv) baseSt(t.quadFace[f], t.quadUv[f * 4 + size_t(k[j])], st[j]);
            else {
                st[j][0] = d[first ? 0 : 1][j][0];
                st[j][1] = d[first ? 0 : 1][j][1];
            }
        }
    };

    // Each vertex's first face and its corner there.
    std::vector<int64_t> first(p.size(), -1);
    for (size_t f = 0; f < faceCount; ++f)
        for (int v = 0; v < corners; ++v) {
            const size_t vid = size_t(faces[f * size_t(corners) + size_t(v)]);
            if (first[vid] < 0) first[vid] = int64_t(f) * 4 + v;
        }
    std::vector<V3> moved(p.size(), V3{0, 0, 0});
    for (size_t vid = 0; vid < p.size(); ++vid) {
        if (first[vid] < 0) continue;
        const size_t f = size_t(first[vid] / 4);
        const int vIndex = int(first[vid] % 4);
        // getNeighborVertices: the triangle of the face holding the vertex (a quad's second for its corner 2, unless
        // the quad is a triangle).
        const bool second = tessellated && vIndex == 2 && faces[f * 4 + 2] != faces[f * 4 + 3];
        int ids[3];
        float st[3][2];
        triangle(f, !second, ids, st);
        const int at = second ? 0 : (tessellated ? (vIndex == 3 ? 2 : vIndex) : vIndex);
        const V3 p1 = p[size_t(ids[0])], p2 = p[size_t(ids[1])], p3 = p[size_t(ids[2])];
        V3 normal = shade::normalize(surface::cross(p2 - p1, p3 - p1));
        if (!surface::finite(normal)) normal = V3{0, 0, 1};
        shade::State s;
        if (!shade::trianglePartials(p1, p2, p3, st[0], st[1], st[2], s.dPds, s.dPdt)) {
            const shade::Frame fr = shade::frame(normal);
            s.dPds = fr.x;
            s.dPdt = fr.y;
        }
        s.P = p[vid];
        s.N = s.Ng = normal;
        s.wo = V3{0, 0, 0};
        s.displacement = true;
        s.s = st[at][0];
        s.t = st[at][1];
        s.dsdx = 0.5f * (st[1][0] - st[0][0]);
        s.dsdy = 0.5f * (st[2][0] - st[0][0]);
        s.dtdx = 0.5f * (st[1][1] - st[0][1]);
        s.dtdy = 0.5f * (st[2][1] - st[0][1]);
        s.worldToRender = worldToRender;
        s.worldToObject = base.worldToObject;
        // The primitive attributes at the vertex's place in its base face (fillDisplacementAttributes).
        const int baseFace = tessellated ? t.quadFace[f] : int(f);
        const Tri& b = base.triangles[size_t(baseFace)];
        Uv place;
        if (tessellated) place = t.quadUv[f * 4 + size_t(vIndex)];
        else place = vIndex == 1 ? Uv{1, 0} : vIndex == 2 ? Uv{0, 1} : Uv{0, 0};
        s.prim = unsigned(baseFace);
        s.ia = b.a;
        s.ib = b.b;
        s.ic = b.c;
        s.u = place.u;
        s.v = place.v;
        s.prims = base.prims.data();
        s.primData = base.primData.data();
        s.primCount = unsigned(base.prims.size());
        moved[vid] = displacement(shader, pool, s, textures);
    }
    for (size_t vid = 0; vid < p.size(); ++vid) {
        p[vid] = p[vid] + moved[vid];
        need(surface::finite(p[vid]) && std::abs(p[vid].x) <= 10000 && std::abs(p[vid].y) <= 10000 && std::abs(p[vid].z) <= 10000,
             base.name + ": displaced vertex bound");
    }
    // the shading normals over the displaced faces
    out->normals = smoothNormals(p, faces, corners);
    out->normalRate = shade::RateVertex;
    out->positions = std::move(p);

    if (!tessellated) {
        out->triangles = base.triangles;
        out->uvs = base.uvs;
        out->uvRate = base.uvRate;
        out->prims = base.prims;
        out->primData = base.primData;
        return out;
    }
    // Each quad's triangles (v0, v1, v3) and, unless v3 == v2, (v2, v3, v1); a triangle of no area is never hit and
    // left out. Their st and primitive attributes a corner each, from the base face.
    struct Corner {
        size_t quad;
        bool first;
    };
    std::vector<Corner> made;
    for (size_t f = 0; f < faceCount; ++f)
        for (int half = 0; half < 2; ++half) {
            if (half == 1 && faces[f * 4 + 2] == faces[f * 4 + 3]) continue;
            int ids[3];
            float st[3][2];
            triangle(f, half == 0, ids, st);
            const V3 a = out->positions[size_t(ids[0])], b = out->positions[size_t(ids[1])], c = out->positions[size_t(ids[2])];
            V3 n;
            if (!surface::normalize(surface::cross(b - a, c - a), n)) continue;
            out->triangles.push_back(Tri{unsigned(ids[0]), unsigned(ids[1]), unsigned(ids[2])});
            made.push_back({f, half == 0});
            for (int j = 0; j < 3; ++j) {
                out->uvs.push_back(st[j][0]);
                out->uvs.push_back(st[j][1]);
            }
        }
    out->uvRate = shade::RateFaceVarying;
    // Constant attributes stay; uniform ones repeat a triangle; the rest become face-varying.
    for (const shade::PrimAttr& a : base.prims) {
        shade::PrimAttr n = a;
        n.offset = unsigned(out->primData.size());
        const float* d = base.primData.data() + a.offset;
        if (a.rate == shade::PrimConstant) {
            out->primData.insert(out->primData.end(), d, d + a.components);
        } else if (a.rate == shade::PrimUniform) {
            for (const Corner& c : made) {
                const size_t face = size_t(t.quadFace[c.quad]);
                out->primData.insert(out->primData.end(), d + face * a.components, d + (face + 1) * a.components);
            }
        } else {
            n.rate = shade::PrimFaceVarying;
            for (const Corner& c : made) {
                const int face = t.quadFace[c.quad];
                const int k[3] = {c.first ? 0 : 2, c.first ? 1 : 3, c.first ? 3 : 1};
                for (int j = 0; j < 3; ++j) {
                    float v[3];
                    attributeAt(d, a.components, a.rate == shade::PrimFaceVarying, base.triangles[size_t(face)], face,
                                t.quadUv[c.quad * 4 + size_t(k[j])], v);
                    out->primData.insert(out->primData.end(), v, v + a.components);
                }
            }
        }
        out->prims.push_back(n);
    }
    return out;
}
}  // namespace xpu2::interactive::cpu::displace
