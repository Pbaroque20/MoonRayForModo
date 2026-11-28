// Rhea's store of surface colours (rhea/object_warp.h ObjectStore) as both devices look it up (rhea/DESIGN.md 37): its
// cells' layout (Entry), the hash that places them, and a ray's lookup at its first hit (lookupHit), so that the graphics
// card answers phase one's lookups beside its first hits (launch mode 5, GpuLane::firstHits) from a copy of the store's
// table kept on it (GpuLane::rheaStoreSync), and the CPU from the same arithmetic where the card does not.
//
// The CPU's own lookups (ObjectStore::lookup) remain the fallback; this is their port, without the CPU's memo of the
// last cells (each GPU thread finds its eight corners anew), in the same double arithmetic.
#pragma once
// (No standard headers but math.h: NVRTC compiles it.)
#if !defined(__CUDACC_RTC__)
#include <math.h>
#endif

#ifdef __CUDACC__
#define RHEA_HD __host__ __device__
#else
#define RHEA_HD
#endif

namespace xpu2::interactive::rheastore {

// A cell's sums: colour (0-2), albedo (3-5), emission (6-8), the weight (9) in the cell itself (Entry, NB of them); and
// beside it, kept only where the store learns view-dependent light (Extra, a slot's at the same index): the diffuse light
// (10-12), and from the pixels whose reflected light was known, their specular light (13-15), that reflected light (16-18)
// and their weight (19). NV: both, as a lookup's means hold them.
constexpr int NB = 10, NV = 20, VW = 9, VD = 10, VS = 13, VR = 16, VWS = 19;
constexpr unsigned char NoBin = 255;

struct Entry {
    long long x = 0, y = 0, z = 0;
    short level = 0;
    unsigned char bin = 0, full = 0;
    unsigned obj = 0;
    float v[NB] = {};
};
struct Extra {
    float v[NV - NB] = {};
};
// A slot's sums for its light's slope (rhea/DESIGN.md 43, the sparse radiance cache; ObjectStore::Options::sparse): its
// pixels' places d in the cell (cell units from its middle) and their colour L, weighted as its means: d (0-2), d d'
// (3-8: xx yy zz xy xz yz), d L (9-17: a colour channel's three).
struct Grad {
    float s[18] = {};
};

// A cell's colour at d (its place in the cell, cell units from its middle): its mean plus its least-squares slope times
// the way from its pixels' centroid. The slope regularised (a cell's pixels lie on a surface, so its spread across the
// surface is none), its change held to the mean either way (no negative light, no runaway). The same on both devices.
RHEA_HD inline void cellColour(const Entry& e, const float* gs, const double d[3], double out[3]) {
    const double W = e.v[VW];
    double pc[3], C[3][3];
    for (int i = 0; i < 3; ++i) pc[i] = gs[i] / W;
    const int ia[6] = {0, 1, 2, 0, 0, 1}, ib[6] = {0, 1, 2, 1, 2, 2};
    for (int k = 0; k < 6; ++k) C[ia[k]][ib[k]] = C[ib[k]][ia[k]] = gs[3 + k] / W - pc[ia[k]] * pc[ib[k]];
    for (int i = 0; i < 3; ++i) C[i][i] += 0.01;
    const double det = C[0][0] * (C[1][1] * C[2][2] - C[1][2] * C[2][1]) - C[0][1] * (C[1][0] * C[2][2] - C[1][2] * C[2][0]) +
                       C[0][2] * (C[1][0] * C[2][1] - C[1][1] * C[2][0]);
    for (int c = 0; c < 3; ++c) out[c] = e.v[c] / W;
    if (!(fabs(det) > 1e-12)) return;
    double inv[3][3];
    inv[0][0] = (C[1][1] * C[2][2] - C[1][2] * C[2][1]) / det, inv[0][1] = (C[0][2] * C[2][1] - C[0][1] * C[2][2]) / det;
    inv[0][2] = (C[0][1] * C[1][2] - C[0][2] * C[1][1]) / det, inv[1][0] = (C[1][2] * C[2][0] - C[1][0] * C[2][2]) / det;
    inv[1][1] = (C[0][0] * C[2][2] - C[0][2] * C[2][0]) / det, inv[1][2] = (C[0][2] * C[1][0] - C[0][0] * C[1][2]) / det;
    inv[2][0] = (C[1][0] * C[2][1] - C[1][1] * C[2][0]) / det, inv[2][1] = (C[0][1] * C[2][0] - C[0][0] * C[2][1]) / det;
    inv[2][2] = (C[0][0] * C[1][1] - C[0][1] * C[1][0]) / det;
    for (int c = 0; c < 3; ++c) {
        const double mean = out[c];
        double b[3];
        for (int i = 0; i < 3; ++i) b[i] = gs[9 + c * 3 + i] / W - pc[i] * mean;
        double change = 0;
        for (int i = 0; i < 3; ++i) {
            double slope = 0;
            for (int j = 0; j < 3; ++j) slope += inv[i][j] * b[j];
            change += slope * (d[i] - pc[i]);
        }
        out[c] = mean + (change < -mean ? -mean : change > mean ? mean : change);
    }
}

// What a lookup needs of the store and of the view (ObjectStore's options, ObjectWarp's, rhea::View's camera).
struct View {
    const Entry* slots = nullptr;   // the table (open addressing), mask + 1 of them; none: no lookups
    const Extra* extras = nullptr;  // a slot's view-dependent sums each, or none
    const Grad* grads = nullptr;    // a slot's slope sums each (the sparse cache), or none: its means alone
    unsigned long long mask = 0;
    int levels = 4, lookupUp = 5, byObject = 0, kind = 0;  // kind: rhea::View's (0 perspective, 1 orthographic, 2 directional)
    double scale = 2, grazing = 8, angle = 0;
    double toCamera[4][4] = {};
    double fp[3] = {0, 0, 0};       // the perspective camera's focal point (camera space)
    int parts = 0;                  // the specular parts wanted (ObjectWarp::Options::specular)
    int pad = 0;
};

// A ray's lookup: found, the colour, the confidence and the sizes up it came from, the hit's depth and lifted depth's
// inputs, and the specular parts (where parts).
struct Look {
    float rgb[3] = {0, 0, 0};
    float conf = 0;
    int up = 0, found = 0;
    float share = 0;
    float diffuse[3] = {0, 0, 0}, emission[3] = {0, 0, 0}, specular[3] = {0, 0, 0}, reflected[3] = {0, 0, 0};
    float albedo[3] = {0, 0, 0};  // the cells' albedo (the smoothing's demodulation, smoothNodes)
};

RHEA_HD inline unsigned long long hashOf(long long x, long long y, long long z, int level, int bin, unsigned obj) {
    unsigned long long h = (unsigned long long)(x) * 0x9E3779B97F4A7C15ull;
    h ^= (unsigned long long)(y) * 0xC2B2AE3D27D4EB4Full + (h << 6) + (h >> 2);
    h ^= (unsigned long long)(z) * 0x165667B19E3779F9ull + (h << 6) + (h >> 2);
    h ^= ((unsigned long long)(unsigned short)(level) << 8 | (unsigned long long)(bin)) * 0x27D4EB2F165667C5ull;
    if (obj) h ^= (unsigned long long)(obj) * 0xD6E8FEB86659FD93ull + (h << 6) + (h >> 2);
    h ^= h >> 31, h *= 0xBF58476D1CE4E5B9ull, h ^= h >> 29;
    return h;
}

RHEA_HD inline const Entry* find(const Entry* slots, unsigned long long mask, long long x, long long y, long long z, int level, int bin,
                                 unsigned obj) {
    if (!slots) return nullptr;
    for (unsigned long long i = hashOf(x, y, z, level, bin, obj) & mask;; i = (i + 1) & mask) {
        const Entry& e = slots[i];
        if (!e.full) return nullptr;
        if (e.x == x && e.y == y && e.z == z && e.level == level && e.bin == bin && e.obj == obj) return &e;
    }
}

RHEA_HD inline int levelOf(double side) { return side > 0 ? int(floor(log2(side))) : -60; }

// How much longer a pixel is along a surface than across it (ObjectStore::stretch).
RHEA_HD inline double stretch(const double n[3], const double d[3], double most) {
    const double nl = sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]), dl = sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
    if (!(nl > 0) || !(dl > 0)) return 1.0;
    const double c = fabs(n[0] * d[0] + n[1] * d[1] + n[2] * d[2]) / (nl * dl);
    const double floorCos = 1.0 / (most > 1.0 ? most : 1.0);
    return 1.0 / (c > floorCos ? c : floorCos);
}

// The side a normal faces (ObjectStore::binsOf).
RHEA_HD inline void binsOf(const double n[3], unsigned char out[2]) {
    const double a[3] = {fabs(n[0]), fabs(n[1]), fabs(n[2])};
    int i0 = 0;
    for (int k = 1; k < 3; ++k)
        if (a[k] > a[i0]) i0 = k;
    int i1 = (i0 + 1) % 3;
    for (int k = 0; k < 3; ++k)
        if (k != i0 && a[k] > a[i1]) i1 = k;
    out[0] = (unsigned char)(i0 * 2 + (n[i0] < 0));
    out[1] = a[i1] > 0.75 * a[i0] ? (unsigned char)(i1 * 2 + (n[i1] < 0)) : NoBin;
}

// The table's means at p (ObjectStore::means, without the memo): trilinear between the cells about it at the first size
// that has any, the coarser sizes filling what the finer leave.
RHEA_HD inline bool means(const View& s, const double p[3], const unsigned char bins[2], unsigned obj, int first, int levels, double out[NV],
                          float& confidence, int& up, int nv) {
    double acc[NV];
    for (int q = 0; q < NV; ++q) acc[q] = 0;
    double have = 0;
    confidence = 0, up = 0;
    for (int k = 0; k < levels; ++k) {
        const int level = first + k;
        const double size = ldexp(1.0, level);
        const double fx = p[0] / size - 0.5, fy = p[1] / size - 0.5, fz = p[2] / size - 0.5;
        const long long x0 = (long long)floor(fx), y0 = (long long)floor(fy), z0 = (long long)floor(fz);
        const double tx = fx - x0, ty = fy - y0, tz = fz - z0;
        double c[NV];
        for (int q = 0; q < NV; ++q) c[q] = 0;
        double wsum = 0;
        for (int corner = 0; corner < 8; ++corner) {
            const int dx = corner & 1, dy = corner >> 1 & 1, dz = corner >> 2 & 1;
            const Entry* e = find(s.slots, s.mask, x0 + dx, y0 + dy, z0 + dz, level, bins[0], obj);
            if (!e && bins[1] != NoBin) e = find(s.slots, s.mask, x0 + dx, y0 + dy, z0 + dz, level, bins[1], obj);
            if (!e || !(e->v[VW] > 0)) continue;
            const double tri = (dx ? tx : 1 - tx) * (dy ? ty : 1 - ty) * (dz ? tz : 1 - tz);
            if (tri <= 0) continue;
            const double w = tri / e->v[VW];
            if (s.grads) {
                // Its colour at the point by its slope (cellColour), the rest by its means.
                const double d[3] = {fx + 0.5 - double(x0 + dx) - 0.5, fy + 0.5 - double(y0 + dy) - 0.5, fz + 0.5 - double(z0 + dz) - 0.5};
                double col[3];
                cellColour(*e, s.grads[e - s.slots].s, d, col);
                for (int q = 0; q < 3; ++q) c[q] += tri * col[q];
                for (int q = 3; q < (nv < NB ? nv : NB); ++q) c[q] += w * e->v[q];
            } else
                for (int q = 0; q < (nv < NB ? nv : NB); ++q) c[q] += w * e->v[q];
            if (nv > NB && s.extras) {
                const Extra& x = s.extras[e - s.slots];
                for (int q = NB; q < nv; ++q) c[q] += w * x.v[q - NB];
            }
            wsum += tri;
        }
        if (wsum <= 0) continue;
        const double take = (1.0 - have) * (wsum / 0.5 < 1.0 ? wsum / 0.5 : 1.0);
        for (int q = 0; q < nv; ++q) acc[q] += take * c[q] / wsum;
        if (have == 0) {
            confidence = float(wsum < 1.0 ? wsum : 1.0);
            up = k;
        }
        have += take;
        if (have > 0.999) break;
    }
    if (have <= 0) return false;
    for (int q = 0; q < nv; ++q) out[q] = acc[q] / have;
    return true;
}

// A ray's lookup at its first hit (ObjectWarp's shade with ObjectStore::lookup): the hit's normal turned toward the
// camera (rhea::View::toward), its footprint from its depth, its cells at its own size and up. hitGeom: the hit's
// geometry (~0u: none, nothing found).
RHEA_HD inline void lookupHit(const View& s, const float dir[3], const float point[3], const float normal[3], unsigned hitGeom, Look& out) {
    out = Look{};
    if (!s.slots || hitGeom == ~0u) return;
    const double pw[4] = {point[0], point[1], point[2], 1.0};
    double c[4];
    for (int j = 0; j < 4; ++j) c[j] = pw[0] * s.toCamera[0][j] + pw[1] * s.toCamera[1][j] + pw[2] * s.toCamera[2][j] + pw[3] * s.toCamera[3][j];
    const double cx = c[0] / c[3], cy = c[1] / c[3], cz = c[2] / c[3];
    const double depth = s.kind == 2 ? sqrt(cx * cx + cy * cy + cz * cz) : -cz;
    // toward
    const double l = sqrt(double(normal[0]) * normal[0] + double(normal[1]) * normal[1] + double(normal[2]) * normal[2]);
    double n[3] = {0, 0, 0};
    if (l > 0) {
        n[0] = normal[0] / l, n[1] = normal[1] / l, n[2] = normal[2] / l;
        const double nc[3] = {n[0] * s.toCamera[0][0] + n[1] * s.toCamera[1][0] + n[2] * s.toCamera[2][0],
                              n[0] * s.toCamera[0][1] + n[1] * s.toCamera[1][1] + n[2] * s.toCamera[2][1],
                              n[0] * s.toCamera[0][2] + n[1] * s.toCamera[1][2] + n[2] * s.toCamera[2][2]};
        double v[3] = {0, 0, -1};
        if (s.kind != 1) {
            const bool persp = s.kind == 0;
            v[0] = cx - (persp ? s.fp[0] : 0.0), v[1] = cy - (persp ? s.fp[1] : 0.0), v[2] = cz - (persp ? s.fp[2] : 0.0);
        }
        if (nc[0] * v[0] + nc[1] * v[1] + nc[2] * v[2] > 0) n[0] = -n[0], n[1] = -n[1], n[2] = -n[2];
    }
    const double foot = s.kind == 1 ? s.angle : s.angle * depth;
    const double d[3] = {dir[0], dir[1], dir[2]};
    unsigned char bins[2];
    binsOf(n, bins);
    const int first = levelOf(foot * stretch(n, d, s.grazing) * s.scale);
    const int most = s.levels + 6;
    const int levels = s.lookupUp >= 0 ? (most < s.lookupUp + 1 ? most : s.lookupUp + 1) : most;
    double m[NV];
    const double p[3] = {point[0], point[1], point[2]};
    const unsigned obj = s.byObject ? hitGeom + 1 : 0u;
    if (!means(s, p, bins, obj, first, levels, m, out.conf, out.up, s.parts && s.extras ? NV : NB)) return;
    out.found = 1;
    for (int ch = 0; ch < 3; ++ch) out.rgb[ch] = float(m[ch] > 0 ? m[ch] : 0.0), out.albedo[ch] = float(m[3 + ch] > 0 ? m[3 + ch] : 0.0);
    if (s.parts && s.extras) {
        for (int ch = 0; ch < 3; ++ch) {
            out.emission[ch] = float(m[6 + ch] > 0 ? m[6 + ch] : 0.0);
            out.diffuse[ch] = float(m[VD + ch] > 0 ? m[VD + ch] : 0.0);
            out.specular[ch] = m[VWS] > 0 ? float(m[VS + ch] / m[VWS] > 0 ? m[VS + ch] / m[VWS] : 0.0) : 0.0f;
            out.reflected[ch] = m[VWS] > 0 ? float(m[VR + ch] / m[VWS] > 0 ? m[VR + ch] / m[VWS] : 0.0) : 0.0f;
        }
        out.share = float(m[VWS] < 0 ? 0.0 : m[VWS] > 1 ? 1.0 : m[VWS]);
    }
}

// Phase one's light smoothed over its surfaces (rhea/DESIGN.md 39): an edge-aware a-trous filter (Dammertz and others,
// 2010) over a grid of nodes (ObjectWarp's fine grid), on the light with the surface's colour divided out (the cells'
// albedo: section 16's demodulation), so that the light within a surface becomes a smooth gradient while its texture,
// multiplied back after, stays as sharp as it was. A node's neighbours count by the B3 spline's weights at the pass's
// step, and only where they are on its object, on its plane (lifted depth), facing its way (normal) and of about its
// light (relative luminance: shadow edges stay). The same arithmetic on the CPU and on the graphics card (launch mode 6).
struct SmoothNode {
    float w = 0;                 // lifted depth (1 / depth), 0: not a surface (left as it is)
    float n[3] = {0, 0, 0};      // unit normal
    unsigned obj = 0;            // object plus one
    unsigned flags = 0;          // 1: demodulated (else its plain colour, a dark surface's), 2: left as it is
};
struct SmoothParams {
    int gw = 0, gh = 0, step = 1;
    float depth = 0.02f;   // lifted depths differing by more than this share of the node's weigh little
    float normal = 32.0f;  // the normals' cosine to this power
    float light = 0.25f;   // luminances differing by more than this share of their mean weigh little
    int pad = 0;
};

// One node's light after a pass (in: every node's light, three floats a node).
RHEA_HD inline void smoothNode(const SmoothParams& p, const SmoothNode* nodes, const float* in, int x, int y, float out[3]) {
    const int i = y * p.gw + x;
    const SmoothNode& c = nodes[i];
    out[0] = in[i * 3], out[1] = in[i * 3 + 1], out[2] = in[i * 3 + 2];
    if (!(c.w > 0) || (c.flags & 2u)) return;
    const float h[5] = {1.0f / 16.0f, 1.0f / 4.0f, 3.0f / 8.0f, 1.0f / 4.0f, 1.0f / 16.0f};
    const float lc = 0.2126f * in[i * 3] + 0.7152f * in[i * 3 + 1] + 0.0722f * in[i * 3 + 2];
    float sum[3] = {0, 0, 0}, wsum = 0;
    for (int dy = -2; dy <= 2; ++dy) {
        const int yy = y + dy * p.step;
        if (yy < 0 || yy >= p.gh) continue;
        for (int dx = -2; dx <= 2; ++dx) {
            const int xx = x + dx * p.step;
            if (xx < 0 || xx >= p.gw) continue;
            const int j = yy * p.gw + xx;
            const SmoothNode& o = nodes[j];
            if (!(o.w > 0) || (o.flags & 2u) || o.obj != c.obj || (o.flags & 1u) != (c.flags & 1u)) continue;
            const float dw = fabsf(o.w - c.w) / (p.depth * c.w);
            const float cosn = c.n[0] * o.n[0] + c.n[1] * o.n[1] + c.n[2] * o.n[2];
            if (!(cosn > 0)) continue;
            const float lo = 0.2126f * in[j * 3] + 0.7152f * in[j * 3 + 1] + 0.0722f * in[j * 3 + 2];
            const float dl = fabsf(lo - lc) / (p.light * 0.5f * (lo + lc) + 1e-4f);
            const float wt = h[dx + 2] * h[dy + 2] * expf(-dw * dw - dl * dl) * powf(cosn, p.normal);
            sum[0] += wt * in[j * 3], sum[1] += wt * in[j * 3 + 1], sum[2] += wt * in[j * 3 + 2];
            wsum += wt;
        }
    }
    if (wsum > 0) out[0] = sum[0] / wsum, out[1] = sum[1] / wsum, out[2] = sum[2] / wsum;
}

// Rhea Draft's lines (rhea/DESIGN.md 42), as MoonLightIPR's Draft finds them (kernel.cu draftEdge): rays a little apart
// (apart pixels, a pixel at least) meet nothing and something, two objects, a crease (normals' cosine under crease), or
// one surface and another part in front of it (more than plane of the nearer's distance off the first's plane).
struct LineSettings {
    int width = 0, height = 0, samples = 1, pad = 0;  // samples: a pixel's rays samples x samples, fixed places in it
    float apart = 2.0f, crease = 0.82f, plane = 0.03f, pad2 = 0.0f;
};
RHEA_HD inline bool draftEdge(unsigned ga, const float na[3], const float pa[3], float ta, unsigned gb, const float nb[3], const float pb[3], float tb,
                              float crease, float plane) {
    const bool va = ga != ~0u, vb = gb != ~0u;
    if (va != vb) return true;
    if (!va) return false;
    if (ga != gb) return true;
    if (fabsf(na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2]) < crease) return true;
    const float d = (pb[0] - pa[0]) * na[0] + (pb[1] - pa[1]) * na[1] + (pb[2] - pa[2]) * na[2];
    return fabsf(d) > plane * fminf(ta, tb);
}

}  // namespace xpu2::interactive::rheastore
