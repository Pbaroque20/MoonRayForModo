// An Ocean Plane's waves in Modo's viewport (the kit's ocean_viewport.py): points where the sea's surface stands,
// around the viewport's eye, sparser with the distance and none past a set one, so that what is drawn costs the same
// however far the sea reaches.
//
// MR_ocean_preview_load keeps a sea under a name: its tiles of long waves (modo_ocean_preview, a few thousand numbers
// each), each with how it lies on the plane, as the renders lay them (nodes.expand_ocean: an ImageMap turned by the
// tile's turn about 0, then scaled by its ratio, repeating). MR_ocean_preview_points works the points out (for tests,
// and for the drawing); MR_ocean_preview_draw draws them on the viewport's stroke object, which is only borrowed for the
// call, the rings centred under the eye the view itself reports (ILxView EyeVector), or under its centre in a view from
// the front, top or side.
//
// A sea is also drawn on a surface kept apart from it (MR_ocean_preview_mesh, MR_ocean_preview_level): a flat mesh
// wearing a material whose Ocean node makes the sea, on its own faces and through its own UVs, or an Ocean Plane's
// level wearing a Modo material's sea (MR_ocean_preview_surface_points, MR_ocean_preview_surface_draw).
#include <lx_draw.hpp>
#include <lxw_draw.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace {
struct Part {
    int width = 0, height = 0;
    double ratio = 1.0, cosTurn = 1.0, sinTurn = 0.0;
    std::vector<float> values;   // width x height x 3, rows by V, as the displacement image holds them
};
struct Sea {
    std::vector<Part> parts;
};
std::mutex lock;
std::map<std::string, std::shared_ptr<const Sea>> kept;

std::shared_ptr<const Sea> find(const char* name) {
    std::lock_guard<std::mutex> held(lock);
    const auto found = kept.find(name ? name : "");
    return found == kept.end() ? nullptr : found->second;
}

// The sea's displacement at a place of the plane's UVs (u, v), each tile read as MoonRay's ImageMap reads it: the
// coordinates turned (u c + v s, -u s + v c), scaled, repeated, and the texels, centred at (i + 0.5) / width,
// blended bilinearly. The displacement image's own (push along U, height, push along V), summed over the tiles. A
// material's Ocean node lays the sea repeatU x repeatV times across the surface's UVs (its Repeat, or the tiles Fit to
// Mesh lays): each tile's scale is its ratio times those, after the turn, as the ImageMap's scale follows its rotation.
void displacement(const Sea& sea, double u, double v, double out[3], double repeatU = 1.0, double repeatV = 1.0) {
    out[0] = out[1] = out[2] = 0.0;
    for (const Part& part : sea.parts) {
        double su = (u * part.cosTurn + v * part.sinTurn) * part.ratio * repeatU, sv = (-u * part.sinTurn + v * part.cosTurn) * part.ratio * repeatV;
        su = su - std::floor(su);
        sv = sv - std::floor(sv);
        const double x = su * part.width - 0.5, y = sv * part.height - 0.5;
        const double fx = std::floor(x), fy = std::floor(y), tx = x - fx, ty = y - fy;
        auto wrap = [](long long i, int n) { return int(((i % n) + n) % n); };
        const int x0 = wrap((long long)fx, part.width), x1 = wrap((long long)fx + 1, part.width);
        const int y0 = wrap((long long)fy, part.height), y1 = wrap((long long)fy + 1, part.height);
        const float* p = part.values.data();
        for (int k = 0; k < 3; ++k) {
            const double a = p[(size_t(y0) * part.width + x0) * 3 + k], b = p[(size_t(y0) * part.width + x1) * 3 + k];
            const double c = p[(size_t(y1) * part.width + x0) * 3 + k], d = p[(size_t(y1) * part.width + x1) * 3 + k];
            out[k] += (a + (b - a) * tx) * (1.0 - ty) + (c + (d - c) * tx) * ty;
        }
    }
}

// The points' colours, by height: the troughs' deep blue and the crests' light blue, and the steps between.
const double Colours[2][3] = {{0.10, 0.32, 0.92}, {0.62, 0.86, 1.0}};
const int Bands = 8;

// Points a level holds along each side of its square from the middle: level 0 a square 2 x Reach + 1 points wide,
// Spacing apart; each level after it twice as far apart and twice as wide, less the square inside it.
const int Reach = 32;

// The points, four floats each: where it stands (x, y, z, in the world) and its height above the plane's. Around (cx,
// cz), a level at a time, each level's points on the world's grid of its spacing (so that they stay where they are as
// the eye moves, the levels' edges moving by whole steps), none farther than distance from the grid point nearest
// (cx, cz), at most most. All of it follows from that grid point, so the points are the same until the eye moves
// half a step (kept, below).
// The plane at height, its UVs the world's X and Z over tile (ocean_plane.made); the displacement image's vector by
// factor, its push along V the other way (MoonRay's tangent frame on a plane facing up: U along +X, the cross of the
// normal and U, -Z, the other way).
size_t points(const Sea& sea, double cx, double cz, double height, double tile, double factor, double spacing, double distance,
              size_t most, std::vector<float>& out) {
    out.clear();
    if (!(tile > 0) || !(spacing > 0) || !(distance > 0) || !std::isfinite(cx) || !std::isfinite(cz)) return 0;
    const double far2 = distance * distance;
    const double ox = std::round(cx / spacing) * spacing, oz = std::round(cz / spacing) * spacing;
    double innerLow[2] = {0, 0}, innerHigh[2] = {0, 0};
    bool inner = false;
    for (int level = 0; level < 40 && out.size() / 4 < most; ++level) {
        const double step = spacing * std::ldexp(1.0, level);
        // The level's square: about its grid point nearest the eye's, Reach steps each way.
        const double mx = std::round(ox / step) * step, mz = std::round(oz / step) * step;
        const double low[2] = {mx - Reach * step, mz - Reach * step}, high[2] = {mx + Reach * step, mz + Reach * step};
        for (int j = -Reach; j <= Reach; ++j) {
            const double z = mz + j * step;
            for (int i = -Reach; i <= Reach; ++i) {
                const double x = mx + i * step;
                // Inside the level within: drawn there, more closely.
                if (inner && x > innerLow[0] && x < innerHigh[0] && z > innerLow[1] && z < innerHigh[1]) continue;
                const double ex = x - ox, ez = z - oz;
                if (ex * ex + ez * ez > far2) continue;
                double moved[3];
                displacement(sea, x / tile, z / tile, moved);
                const double dx = moved[0] * factor, dy = moved[1] * factor, dz = -moved[2] * factor;
                out.push_back(float(x + dx));
                out.push_back(float(height + dy));
                out.push_back(float(z + dz));
                out.push_back(float(dy));
                if (out.size() / 4 >= most) break;
            }
            if (out.size() / 4 >= most) break;
        }
        // Past the distance on every side: no level beyond.
        if (low[0] <= ox - distance && high[0] >= ox + distance && low[1] <= oz - distance && high[1] >= oz + distance) break;
        innerLow[0] = low[0];
        innerLow[1] = low[1];
        innerHigh[0] = high[0];
        innerHigh[1] = high[1];
        inner = true;
    }
    return out.size() / 4;
}

// Each plane's points as last drawn, and what they were made from: drawn again as they are while the sea, the
// settings and the eye's grid point are the same (another viewport, a selection, another item moved).
struct Drawn {
    std::shared_ptr<const Sea> sea;
    double ox = 0, oz = 0, height = 0, tile = 0, factor = 0, spacing = 0, distance = 0;
    size_t most = 0;
    std::vector<float> points;
};
std::map<std::string, Drawn> drawn;

std::vector<float> pointsFor(const std::string& name, const std::shared_ptr<const Sea>& sea, double cx, double cz, double height, double tile,
                             double factor, double spacing, double distance, size_t most) {
    const double ox = spacing > 0 ? std::round(cx / spacing) * spacing : cx, oz = spacing > 0 ? std::round(cz / spacing) * spacing : cz;
    {
        std::lock_guard<std::mutex> held(lock);
        const auto found = drawn.find(name);
        if (found != drawn.end()) {
            const Drawn& d = found->second;
            if (d.sea == sea && d.ox == ox && d.oz == oz && d.height == height && d.tile == tile && d.factor == factor && d.spacing == spacing &&
                d.distance == distance && d.most == most)
                return d.points;
        }
    }
    Drawn made;
    made.sea = sea;
    made.ox = ox;
    made.oz = oz;
    made.height = height;
    made.tile = tile;
    made.factor = factor;
    made.spacing = spacing;
    made.distance = distance;
    made.most = most;
    points(*sea, cx, cz, height, tile, factor, spacing, distance, most, made.points);
    std::vector<float> result = made.points;
    std::lock_guard<std::mutex> held(lock);
    drawn[name] = std::move(made);
    return result;
}

// ---- A sea on a surface of its own: a flat mesh wearing a material whose Ocean node makes it, or an Ocean Plane's
// level wearing a Modo material's sea ------------------------------------------------------------------------------
//
// The surface is a plane in the world, its places (a, b) along two directions on it (along, across) from a point of it
// (origin). Its UVs are worked out from (a, b) (u = u0 + ua a + ub b, v = v0 + va a + vb b), as a flat mesh's UVs are
// laid on it, and the sea pushes each place along MoonRay's tangent frame there: along U's direction (tangent), along
// the normal, and along their cross (normal x tangent), the displacement image's own three as the Vector
// Displacement's tangent space takes them. A mesh's is bounded: only places on its faces (inside, a raster of them over
// its extent) are drawn.
struct Surface {
    double origin[3] = {0, 0, 0}, along[3] = {1, 0, 0}, across[3] = {0, 0, 1}, normal[3] = {0, 1, 0};
    double tangent[3] = {1, 0, 0}, bitangent[3] = {0, 0, -1};
    double u0 = 0, ua = 1, ub = 0, v0 = 0, va = 0, vb = 1;
    bool bounded = false;
    double low[2] = {0, 0}, high[2] = {0, 0};
    int maskWidth = 0, maskHeight = 0;
    std::vector<unsigned char> mask;   // maskWidth x maskHeight, rows by b; empty where the faces fill low..high

    bool inside(double a, double b) const {
        if (!bounded) return true;
        if (a < low[0] || a > high[0] || b < low[1] || b > high[1]) return false;
        if (mask.empty()) return true;
        const double sa = high[0] - low[0], sb = high[1] - low[1];
        const int i = std::min(maskWidth - 1, std::max(0, sa > 0 ? int((a - low[0]) / sa * maskWidth) : 0));
        const int j = std::min(maskHeight - 1, std::max(0, sb > 0 ? int((b - low[1]) / sb * maskHeight) : 0));
        return mask[size_t(j) * maskWidth + i] != 0;
    }
};
std::map<std::string, std::shared_ptr<const Surface>> surfaces;

std::shared_ptr<const Surface> findSurface(const char* name) {
    std::lock_guard<std::mutex> held(lock);
    const auto found = surfaces.find(name ? name : "");
    return found == surfaces.end() ? nullptr : found->second;
}

double dot3(const double a[3], const double b[3]) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
void cross3(const double a[3], const double b[3], double out[3]) {
    const double x = a[1] * b[2] - a[2] * b[1], y = a[2] * b[0] - a[0] * b[2], z = a[0] * b[1] - a[1] * b[0];
    out[0] = x;
    out[1] = y;
    out[2] = z;
}
bool normalise3(double v[3]) {
    const double length = std::sqrt(dot3(v, v));
    if (!(length > 1e-300) || !std::isfinite(length)) return false;
    v[0] /= length;
    v[1] /= length;
    v[2] /= length;
    return true;
}

// The surface's place nearest the eye (its (a, b), inside its extent where it is bounded): the middle of its points.
void centreOf(const Surface& s, const double eye[3], double& ca, double& cb) {
    const double d[3] = {eye[0] - s.origin[0], eye[1] - s.origin[1], eye[2] - s.origin[2]};
    ca = dot3(d, s.along);
    cb = dot3(d, s.across);
    if (s.bounded) {
        ca = std::min(std::max(ca, s.low[0]), s.high[0]);
        cb = std::min(std::max(cb, s.low[1]), s.high[1]);
    }
}

// The points of a sea on a surface (four floats each, as points() gives them: where each stands in the world and its
// height along the surface's normal), around (ca, cb) in levels as points() lays them, on the surface's own grid,
// only where the surface is (inside), at most most of them.
size_t surfacePoints(const Sea& sea, const Surface& s, double repeatU, double repeatV, double factor, double ca, double cb, double spacing,
                     double distance, size_t most, std::vector<float>& out) {
    out.clear();
    if (!(spacing > 0) || !(distance > 0) || !std::isfinite(ca) || !std::isfinite(cb) || !std::isfinite(factor)) return 0;
    const double far2 = distance * distance;
    const double oa = std::round(ca / spacing) * spacing, ob = std::round(cb / spacing) * spacing;
    double innerLow[2] = {0, 0}, innerHigh[2] = {0, 0};
    bool inner = false;
    for (int level = 0; level < 40 && out.size() / 4 < most; ++level) {
        const double step = spacing * std::ldexp(1.0, level);
        const double ma = std::round(oa / step) * step, mb = std::round(ob / step) * step;
        const double low[2] = {ma - Reach * step, mb - Reach * step}, high[2] = {ma + Reach * step, mb + Reach * step};
        for (int j = -Reach; j <= Reach; ++j) {
            const double b = mb + j * step;
            for (int i = -Reach; i <= Reach; ++i) {
                const double a = ma + i * step;
                if (inner && a > innerLow[0] && a < innerHigh[0] && b > innerLow[1] && b < innerHigh[1]) continue;
                const double ea = a - oa, eb = b - ob;
                if (ea * ea + eb * eb > far2) continue;
                if (!s.inside(a, b)) continue;
                double moved[3];
                displacement(sea, s.u0 + s.ua * a + s.ub * b, s.v0 + s.va * a + s.vb * b, moved, repeatU, repeatV);
                const double d0 = moved[0] * factor, d1 = moved[1] * factor, d2 = moved[2] * factor;
                for (int k = 0; k < 3; ++k)
                    out.push_back(float(s.origin[k] + a * s.along[k] + b * s.across[k] + d0 * s.tangent[k] + d1 * s.normal[k] + d2 * s.bitangent[k]));
                out.push_back(float(d1));
                if (out.size() / 4 >= most) break;
            }
            if (out.size() / 4 >= most) break;
        }
        if (low[0] <= oa - distance && high[0] >= oa + distance && low[1] <= ob - distance && high[1] >= ob + distance) break;
        // A bounded surface wholly inside this level: none of it is left for the levels beyond.
        if (s.bounded && low[0] <= s.low[0] && high[0] >= s.high[0] && low[1] <= s.low[1] && high[1] >= s.high[1]) break;
        innerLow[0] = low[0];
        innerLow[1] = low[1];
        innerHigh[0] = high[0];
        innerHigh[1] = high[1];
        inner = true;
    }
    return out.size() / 4;
}

// Each sea on a surface as last drawn, and what it was made from, as drawn (above) for an Ocean Plane.
struct DrawnOn {
    std::shared_ptr<const Sea> sea;
    std::shared_ptr<const Surface> surface;
    std::vector<double> settings;
    std::vector<float> points;
};
std::map<std::string, DrawnOn> drawnOn;

std::vector<float> surfacePointsFor(const std::string& name, const std::shared_ptr<const Sea>& sea, const std::shared_ptr<const Surface>& surface,
                                    double repeatU, double repeatV, double factor, double ca, double cb, double spacing, double distance,
                                    size_t most) {
    const double oa = spacing > 0 ? std::round(ca / spacing) * spacing : ca, ob = spacing > 0 ? std::round(cb / spacing) * spacing : cb;
    const std::vector<double> settings = {repeatU, repeatV, factor, oa, ob, spacing, distance, double(most)};
    {
        std::lock_guard<std::mutex> held(lock);
        const auto found = drawnOn.find(name);
        if (found != drawnOn.end() && found->second.sea == sea && found->second.surface == surface && found->second.settings == settings)
            return found->second.points;
    }
    DrawnOn made;
    made.sea = sea;
    made.surface = surface;
    made.settings = settings;
    surfacePoints(*sea, *surface, repeatU, repeatV, factor, ca, cb, spacing, distance, most, made.points);
    std::vector<float> result = made.points;
    std::lock_guard<std::mutex> held(lock);
    drawnOn[name] = std::move(made);
    return result;
}

// The eye of the view being drawn (see MR_ocean_preview_draw), and the nine numbers sent back for probes.
void viewEye(CLxLoc_View& view, double eye[3], double sent[9]) {
    LXtVector centre;
    view.Center(centre);
    double cx = centre[0], cy = centre[1], cz = centre[2], first = 0.0, second = 0.0;
    const int type = view.Type();
    if (type == LXiVIEWv_PERSPECTIVE) {
        LXtVector toward;
        first = view.EyeVector(centre, toward);
        if (std::isfinite(first)) {
            const double ahead = 10.0 * std::max(first, 1.0);
            const LXtVector point = {centre[0] + toward[0] * ahead, centre[1] + toward[1] * ahead, centre[2] + toward[2] * ahead};
            LXtVector back;
            second = view.EyeVector(point, back);
            if (std::isfinite(second)) {
                cx = point[0] - back[0] * second;
                cy = point[1] - back[1] * second;
                cz = point[2] - back[2] * second;
            }
        }
    }
    eye[0] = cx;
    eye[1] = cy;
    eye[2] = cz;
    const double values[9] = {cx, cy, cz, double(type), centre[0], centre[1], centre[2], first, second};
    std::copy(values, values + 9, sent);
}

// The points drawn on the stroke object, coloured by their height in Bands steps (see MR_ocean_preview_draw).
void drawBands(CLxLoc_StrokeDraw& stroke, const std::vector<float>& made) {
    const size_t count = made.size() / 4;
    if (!count) return;
    double sum = 0.0, squares = 0.0;
    for (size_t i = 0; i < count; ++i) {
        sum += made[4 * i + 3];
        squares += double(made[4 * i + 3]) * made[4 * i + 3];
    }
    const double mean = sum / count, spread = std::sqrt(std::max(squares / count - mean * mean, 0.0));
    const double lowest = mean - 2.0 * spread, span = std::max(4.0 * spread, 1e-6);
    std::vector<size_t> bands[Bands];
    for (size_t i = 0; i < count; ++i) {
        const double t = (made[4 * i + 3] - lowest) / span;
        bands[std::min(Bands - 1, std::max(0, int(t * Bands)))].push_back(i);
    }
    for (int band = 0; band < Bands; ++band) {
        if (bands[band].empty()) continue;
        const double t = band / double(Bands - 1);
        LXtVector colour;
        for (int k = 0; k < 3; ++k) colour[k] = Colours[0][k] + (Colours[1][k] - Colours[0][k]) * t;
        stroke.Begin(LXiSTROKE_POINTS, colour, 1.0);
        for (const size_t i : bands[band]) {
            const LXtVector p = {made[4 * i], made[4 * i + 1], made[4 * i + 2]};
            stroke.Vertex(p, LXiSTROKE_ABSOLUTE);
        }
    }
}

// The largest side of a mesh surface's raster of where its faces are.
const int MaskSide = 256;

// A flat mesh as a surface (see Surface): its faces' corners placed in the world, their Newell normal, how far they
// stand off the plane through their middle, and a fit of their UVs over the plane by least squares. Nullptr where the
// faces are not flat, their UVs are not laid flat across them (u and v a fixed step per metre, as a plane's are), or
// there is nothing; fit then gives why (1 not flat, 2 UVs not flat, 3 nothing).
std::shared_ptr<Surface> meshSurface(int pointCount, const float* xyz, int faceCount, const int* counts, const int* corners, const float* uvs,
                                     const unsigned char* wanted, const double* m, double out[8], int& fit) {
    fit = 3;
    if (pointCount < 3 || faceCount < 1 || !xyz || !counts || !corners || !uvs || !m) return nullptr;
    auto world = [&](int i, double w[3]) {
        const double x = xyz[3 * size_t(i)], y = xyz[3 * size_t(i) + 1], z = xyz[3 * size_t(i) + 2];
        w[0] = x * m[0] + y * m[4] + z * m[8] + m[12];
        w[1] = x * m[1] + y * m[5] + z * m[9] + m[13];
        w[2] = x * m[2] + y * m[6] + z * m[10] + m[14];
    };
    std::vector<size_t> starts(size_t(faceCount) + 1, 0);
    for (int f = 0; f < faceCount; ++f) {
        if (counts[f] < 0) return nullptr;
        starts[f + 1] = starts[f] + size_t(counts[f]);
    }
    double n[3] = {0, 0, 0}, centre[3] = {0, 0, 0}, lowest[3] = {HUGE_VAL, HUGE_VAL, HUGE_VAL}, highest[3] = {-HUGE_VAL, -HUGE_VAL, -HUGE_VAL};
    size_t used = 0;
    for (int f = 0; f < faceCount; ++f) {
        const int count = counts[f];
        if (count < 3 || (wanted && !wanted[f])) continue;
        for (int k = 0; k < count; ++k) {
            const int i = corners[starts[f] + k], j = corners[starts[f] + (k + 1) % count];
            if (i < 0 || i >= pointCount || j < 0 || j >= pointCount) return nullptr;
            double p[3], q[3];
            world(i, p);
            world(j, q);
            n[0] += (p[1] - q[1]) * (p[2] + q[2]);
            n[1] += (p[2] - q[2]) * (p[0] + q[0]);
            n[2] += (p[0] - q[0]) * (p[1] + q[1]);
            for (int c = 0; c < 3; ++c) {
                centre[c] += p[c];
                lowest[c] = std::min(lowest[c], p[c]);
                highest[c] = std::max(highest[c], p[c]);
            }
            ++used;
        }
    }
    const double twiceArea = std::sqrt(dot3(n, n));
    if (!used || !(twiceArea > 0)) return nullptr;
    auto s = std::make_shared<Surface>();
    for (int c = 0; c < 3; ++c) {
        s->normal[c] = n[c] / twiceArea;
        s->origin[c] = centre[c] / double(used);
    }
    const double size = std::sqrt((highest[0] - lowest[0]) * (highest[0] - lowest[0]) + (highest[1] - lowest[1]) * (highest[1] - lowest[1]) +
                                  (highest[2] - lowest[2]) * (highest[2] - lowest[2]));
    // Any two directions on the plane, for the fit; the surface's own are U's direction and the normal's cross with it.
    double first[3], second[3];
    const double pick[3] = {std::fabs(s->normal[0]) < 0.9 ? 1.0 : 0.0, std::fabs(s->normal[0]) < 0.9 ? 0.0 : 1.0, 0.0};
    cross3(s->normal, pick, second);
    normalise3(second);
    cross3(second, s->normal, first);
    normalise3(first);
    // Flat: no corner farther off the plane than a ten-thousandth of the faces' size.
    double sums[3][3] = {{0, 0, 0}, {0, 0, 0}, {0, 0, 0}}, us[3] = {0, 0, 0}, vs[3] = {0, 0, 0};
    double uLow = HUGE_VAL, uHigh = -HUGE_VAL, vLow = HUGE_VAL, vHigh = -HUGE_VAL;
    for (int f = 0; f < faceCount; ++f) {
        const int count = counts[f];
        if (count < 3 || (wanted && !wanted[f])) continue;
        for (int k = 0; k < count; ++k) {
            double p[3];
            world(corners[starts[f] + k], p);
            const double d[3] = {p[0] - s->origin[0], p[1] - s->origin[1], p[2] - s->origin[2]};
            if (std::fabs(dot3(d, s->normal)) > 1e-4 * size + 1e-7) {
                fit = 1;
                return nullptr;
            }
            const double a = dot3(d, first), b = dot3(d, second);
            const double u = uvs[2 * (starts[f] + k)], v = uvs[2 * (starts[f] + k) + 1];
            const double row[3] = {a, b, 1.0};
            for (int r = 0; r < 3; ++r) {
                for (int c = 0; c < 3; ++c) sums[r][c] += row[r] * row[c];
                us[r] += row[r] * u;
                vs[r] += row[r] * v;
            }
            uLow = std::min(uLow, u);
            uHigh = std::max(uHigh, u);
            vLow = std::min(vLow, v);
            vHigh = std::max(vHigh, v);
        }
    }
    // The fit (Cramer's rule on the three sums): u = ua a + ub b + u0 over (first, second).
    auto det3 = [](const double x[3][3]) {
        return x[0][0] * (x[1][1] * x[2][2] - x[1][2] * x[2][1]) - x[0][1] * (x[1][0] * x[2][2] - x[1][2] * x[2][0]) +
               x[0][2] * (x[1][0] * x[2][1] - x[1][1] * x[2][0]);
    };
    const double whole = det3(sums);
    fit = 2;
    if (!(std::fabs(whole) > 1e-300)) return nullptr;
    auto solve = [&](const double rhs[3], double result[3]) {
        for (int c = 0; c < 3; ++c) {
            double swapped[3][3];
            for (int r = 0; r < 3; ++r)
                for (int k = 0; k < 3; ++k) swapped[r][k] = k == c ? rhs[r] : sums[r][k];
            result[c] = det3(swapped) / whole;
        }
    };
    double fu[3], fv[3];
    solve(us, fu);
    solve(vs, fv);
    // UVs laid flat: each corner's own within a ten-thousandth of their spread of the fit.
    const double spreadUv = std::max(std::max(uHigh - uLow, vHigh - vLow), 1e-9);
    for (int f = 0; f < faceCount; ++f) {
        const int count = counts[f];
        if (count < 3 || (wanted && !wanted[f])) continue;
        for (int k = 0; k < count; ++k) {
            double p[3];
            world(corners[starts[f] + k], p);
            const double d[3] = {p[0] - s->origin[0], p[1] - s->origin[1], p[2] - s->origin[2]};
            const double a = dot3(d, first), b = dot3(d, second);
            if (std::fabs(fu[0] * a + fu[1] * b + fu[2] - uvs[2 * (starts[f] + k)]) > 1e-4 * spreadUv ||
                std::fabs(fv[0] * a + fv[1] * b + fv[2] - uvs[2 * (starts[f] + k) + 1]) > 1e-4 * spreadUv)
                return nullptr;
        }
    }
    const double det = fu[0] * fv[1] - fu[1] * fv[0];
    if (!(std::fabs(det) > 1e-300)) return nullptr;
    // How the plane moves for a step of U and of V: the fit turned about.
    const double duA = fv[1] / det, duB = -fv[0] / det, dvA = -fu[1] / det, dvB = fu[0] / det;
    double dPdu[3], dPdv[3];
    for (int c = 0; c < 3; ++c) {
        dPdu[c] = first[c] * duA + second[c] * duB;
        dPdv[c] = first[c] * dvA + second[c] * dvB;
    }
    std::copy(dPdu, dPdu + 3, s->tangent);
    if (!normalise3(s->tangent)) return nullptr;
    cross3(s->normal, s->tangent, s->bitangent);
    std::copy(s->tangent, s->tangent + 3, s->along);
    std::copy(s->bitangent, s->bitangent + 3, s->across);
    // The fit over the surface's own directions.
    const double c11 = dot3(s->along, first), c12 = dot3(s->along, second), c21 = dot3(s->across, first), c22 = dot3(s->across, second);
    s->u0 = fu[2];
    s->ua = fu[0] * c11 + fu[1] * c12;
    s->ub = fu[0] * c21 + fu[1] * c22;
    s->v0 = fv[2];
    s->va = fv[0] * c11 + fv[1] * c12;
    s->vb = fv[0] * c21 + fv[1] * c22;
    // Its extent along them, and the raster of where its faces are.
    s->bounded = true;
    s->low[0] = s->low[1] = HUGE_VAL;
    s->high[0] = s->high[1] = -HUGE_VAL;
    std::vector<double> placed;
    placed.reserve(used * 2);
    for (int f = 0; f < faceCount; ++f) {
        const int count = counts[f];
        if (count < 3 || (wanted && !wanted[f])) continue;
        for (int k = 0; k < count; ++k) {
            double p[3];
            world(corners[starts[f] + k], p);
            const double d[3] = {p[0] - s->origin[0], p[1] - s->origin[1], p[2] - s->origin[2]};
            const double a = dot3(d, s->along), b = dot3(d, s->across);
            placed.push_back(a);
            placed.push_back(b);
            s->low[0] = std::min(s->low[0], a);
            s->low[1] = std::min(s->low[1], b);
            s->high[0] = std::max(s->high[0], a);
            s->high[1] = std::max(s->high[1], b);
        }
    }
    const double sa = s->high[0] - s->low[0], sb = s->high[1] - s->low[1];
    if (!(sa > 0) || !(sb > 0)) return nullptr;
    s->maskWidth = sa >= sb ? MaskSide : std::max(1, int(std::ceil(MaskSide * sa / sb)));
    s->maskHeight = sb >= sa ? MaskSide : std::max(1, int(std::ceil(MaskSide * sb / sa)));
    s->mask.assign(size_t(s->maskWidth) * s->maskHeight, 0);
    const double cellA = sa / s->maskWidth, cellB = sb / s->maskHeight;
    size_t at = 0, filled = 0;
    for (int f = 0; f < faceCount; ++f) {
        const int count = counts[f];
        if (count < 3 || (wanted && !wanted[f])) continue;
        const double* corner = placed.data() + at;
        at += size_t(count) * 2;
        // The face as a fan of triangles from its first corner; a cell is the face's where its middle is in one.
        for (int k = 1; k + 1 < count; ++k) {
            const double ax = corner[0], ay = corner[1], bx = corner[2 * k], by = corner[2 * k + 1], cx = corner[2 * k + 2], cy = corner[2 * k + 3];
            const double area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
            if (area == 0) continue;
            const int i0 = std::max(0, int(std::floor((std::min({ax, bx, cx}) - s->low[0]) / cellA)));
            const int i1 = std::min(s->maskWidth - 1, int(std::floor((std::max({ax, bx, cx}) - s->low[0]) / cellA)));
            const int j0 = std::max(0, int(std::floor((std::min({ay, by, cy}) - s->low[1]) / cellB)));
            const int j1 = std::min(s->maskHeight - 1, int(std::floor((std::max({ay, by, cy}) - s->low[1]) / cellB)));
            for (int j = j0; j <= j1; ++j) {
                const double y = s->low[1] + (j + 0.5) * cellB;
                for (int i = i0; i <= i1; ++i) {
                    unsigned char& cell = s->mask[size_t(j) * s->maskWidth + i];
                    if (cell) continue;
                    const double x = s->low[0] + (i + 0.5) * cellA;
                    const double w0 = (bx - x) * (cy - y) - (by - y) * (cx - x), w1 = (cx - x) * (ay - y) - (cy - y) * (ax - x),
                                 w2 = (ax - x) * (by - y) - (ay - y) * (bx - x);
                    if ((w0 >= 0 && w1 >= 0 && w2 >= 0) || (w0 <= 0 && w1 <= 0 && w2 <= 0)) {
                        cell = 1;
                        ++filled;
                    }
                }
            }
        }
    }
    if (filled == s->mask.size()) s->mask.clear();
    out[0] = twiceArea / 2.0;
    out[1] = std::sqrt(dot3(dPdu, dPdu));
    out[2] = std::sqrt(dot3(dPdv, dPdv));
    out[3] = s->normal[0];
    out[4] = s->normal[1];
    out[5] = s->normal[2];
    out[6] = sa;
    out[7] = sb;
    fit = 0;
    return s;
}
}  // namespace

// Keeps a sea under a name: count tiles, the i-th widths[i] x heights[i] x 3 floats of values in turn (the long waves'
// displacement, modo_ocean_preview, or the swell's one row), laid on the plane as ratios[i] tiles to one of the sea's
// and turned by turns[i] degrees. 1 where it was kept.
extern "C" __declspec(dllexport) int MR_ocean_preview_load(const char* name, int count, const int* widths, const int* heights,
                                                           const double* ratios, const double* turns, const float* values) {
    if (!name || count < 0 || (count && (!widths || !heights || !ratios || !turns || !values))) return 0;
    try {
        auto sea = std::make_shared<Sea>();
        size_t at = 0;
        for (int i = 0; i < count; ++i) {
            if (widths[i] < 1 || heights[i] < 1 || !std::isfinite(ratios[i]) || !std::isfinite(turns[i])) return 0;
            Part part;
            part.width = widths[i];
            part.height = heights[i];
            part.ratio = ratios[i];
            const double turn = turns[i] * 3.14159265358979323846 / 180.0;
            part.cosTurn = std::cos(turn);
            part.sinTurn = std::sin(turn);
            const size_t size = size_t(part.width) * part.height * 3;
            part.values.assign(values + at, values + at + size);
            at += size;
            sea->parts.push_back(std::move(part));
        }
        std::lock_guard<std::mutex> held(lock);
        kept[name] = std::move(sea);
        return 1;
    } catch (...) {
        return 0;
    }
}

// Lets go of the sea kept under a name (an Ocean Plane deleted, or its points turned off).
extern "C" __declspec(dllexport) void MR_ocean_preview_forget(const char* name) {
    std::lock_guard<std::mutex> held(lock);
    kept.erase(name ? name : "");
    drawn.erase(name ? name : "");
}

// The points of the sea kept under name around (cx, cz) (points above), at most most of them, into out (4 floats each);
// how many, or -1 where no sea is kept under the name.
extern "C" __declspec(dllexport) int MR_ocean_preview_points(const char* name, double cx, double cz, double height, double tile, double factor,
                                                             double spacing, double distance, int most, float* out) {
    const std::shared_ptr<const Sea> sea = find(name);
    if (!sea) return -1;
    std::vector<float> made;
    const size_t count = points(*sea, cx, cz, height, tile, factor, spacing, distance, size_t(std::max(most, 0)), made);
    if (out) std::copy(made.begin(), made.end(), out);
    return int(count);
}

// Draws the sea kept under name on a viewport's stroke object (ILxStrokeDraw, borrowed, in world space): its points
// around the eye (in a perspective or camera view) or the view's centre (front, top, side), coloured by their height:
// deep blue in the troughs to light blue on the crests (Colours), in Bands steps over the points' own spread of heights
// (two of their standard deviations either side of their mean, so that one tall crest does not wash the rest out). The
// item's colour (red, green, blue) is its grid's, which shows it selected; the points keep theirs. Where eye is given, nine numbers are sent back
// through it, for probes: the eye's place (x, y, z), the view's kind (its Type), its centre (x, y, z), and the distances
// EyeVector gave for the centre and for the point ahead. How many points were drawn; -1 where no sea is kept under the name or the view cannot be read.
extern "C" __declspec(dllexport) int MR_ocean_preview_draw(void* strokeObject, const char* name, double height, double tile, double factor,
                                                           double spacing, double distance, int most, double red, double green,
                                                           double blue, double* eye) {
    const std::shared_ptr<const Sea> sea = find(name);
    if (!sea) return -1;
    CLxLoc_StrokeDraw stroke;
    CLxLoc_View view;
    if (!stroke.set(reinterpret_cast<ILxUnknownID>(strokeObject)) || !view.set(reinterpret_cast<ILxUnknownID>(strokeObject))) return -1;
    // Looking through a camera, the view's centre is the camera itself (seen in Modo 16.1, 2026-11-21: a camera at
    // (0, 6, 0) gave that centre, while EyeVector measured from 4 m behind it, which put the points' middle there).
    // In a perspective view the centre is the point it turns about: the eye is found back from a point well ahead
    // along the way it looks (viewEye).
    double at[3], sent[9];
    viewEye(view, at, sent);
    if (eye) std::copy(sent, sent + 9, eye);
    (void)red;
    (void)green;
    (void)blue;
    const std::vector<float> made = pointsFor(name, sea, at[0], at[2], height, tile, factor, spacing, distance, size_t(std::max(most, 0)));
    const size_t count = made.size() / 4;
    if (!count) return 0;
    drawBands(stroke, made);
    return int(count);
}

// Keeps a flat mesh as a surface under name (Surface, meshSurface): pointCount points (xyz, the item's own space), placed
// in the world by matrix (16 numbers, Modo's rows, its place the last), faceCount faces of counts[f] corners each
// (corners, the points' places in turn), the first UV map's value at each corner (uvs, two each, in the corners' order),
// only the faces wanted marks (none: all). out (eight numbers) is sent back the faces' area, the metres a step of U and
// of V spans, their normal, and how far they reach along U's direction and across it. 0 where it was kept; 1 where the faces are not flat, 2 where their UVs are not laid flat
// on them, 3 where there is nothing (or it is not readable): nothing is kept under the name then.
extern "C" __declspec(dllexport) int MR_ocean_preview_mesh(const char* name, int pointCount, const float* xyz, int faceCount, const int* counts,
                                                           const int* corners, const float* uvs, const unsigned char* wanted,
                                                           const double* matrix, double* out) {
    if (!name) return 3;
    try {
        double sent[8] = {0, 0, 0, 0, 0, 0, 0, 0};
        int fit = 3;
        std::shared_ptr<Surface> made = meshSurface(pointCount, xyz, faceCount, counts, corners, uvs, wanted, matrix, sent, fit);
        if (out) std::copy(sent, sent + 8, out);
        std::lock_guard<std::mutex> held(lock);
        if (!made) {
            surfaces.erase(name);
            return fit ? fit : 3;
        }
        surfaces[name] = std::move(made);
        return 0;
    } catch (...) {
        std::lock_guard<std::mutex> held(lock);
        surfaces.erase(name);
        return 3;
    }
}

// Keeps an Ocean Plane's level as a surface under name: the world's level at height, reaching everywhere, its UVs the
// world's X and Z over tile (ocean_plane.made), its tangent frame a plane's facing up (U along +X; normal x U, -Z).
extern "C" __declspec(dllexport) int MR_ocean_preview_level(const char* name, double height, double tile) {
    if (!name || !(tile > 0) || !std::isfinite(height)) return 0;
    auto s = std::make_shared<Surface>();
    s->origin[1] = height;
    // along +X, across normal x along (-Z): (a, b) = (x, -z), so u = x / tile and v = z / tile = -b / tile.
    s->across[2] = -1.0;
    s->ua = 1.0 / tile;
    s->vb = -1.0 / tile;
    std::lock_guard<std::mutex> held(lock);
    surfaces[name] = std::move(s);
    return 1;
}

// Lets go of the surface kept under a name, and what was drawn on it.
extern "C" __declspec(dllexport) void MR_ocean_preview_surface_forget(const char* name) {
    std::lock_guard<std::mutex> held(lock);
    const std::string key = name ? name : "";
    surfaces.erase(key);
    for (auto i = drawnOn.begin(); i != drawnOn.end();) {
        if (i->first.size() > key.size() && i->first.compare(i->first.size() - key.size(), key.size(), key) == 0 &&
            i->first[i->first.size() - key.size() - 1] == '@')
            i = drawnOn.erase(i);
        else
            ++i;
    }
}

// The points of the sea kept under sea on the surface kept under surface, seen from (ex, ey, ez): its Ocean node's
// repeat (repeatU, repeatV) and the factor its heights are scaled by, Spacing apart next to the surface's place nearest
// the eye and out to distance, at most most, into out (4 floats each, as MR_ocean_preview_points gives them). How
// many, or -1 where either is not kept.
extern "C" __declspec(dllexport) int MR_ocean_preview_surface_points(const char* sea, const char* surface, double repeatU, double repeatV,
                                                                     double factor, double ex, double ey, double ez, double spacing,
                                                                     double distance, int most, float* out) {
    const std::shared_ptr<const Sea> kept = find(sea);
    const std::shared_ptr<const Surface> on = findSurface(surface);
    if (!kept || !on) return -1;
    const double eye[3] = {ex, ey, ez};
    double ca, cb;
    centreOf(*on, eye, ca, cb);
    std::vector<float> made;
    const size_t count = surfacePoints(*kept, *on, repeatU, repeatV, factor, ca, cb, spacing, distance, size_t(std::max(most, 0)), made);
    if (out) std::copy(made.begin(), made.end(), out);
    return int(count);
}

// Draws the sea kept under sea on the surface kept under surface on a viewport's stroke object (ILxStrokeDraw,
// borrowed, in world space), as MR_ocean_preview_draw draws an Ocean Plane's: around the surface's place nearest the
// view's eye, coloured by height. eye (nine numbers, where given) is sent back as there. How many points were drawn;
// -1 where either is not kept or the view cannot be read.
extern "C" __declspec(dllexport) int MR_ocean_preview_surface_draw(void* strokeObject, const char* sea, const char* surface, double repeatU,
                                                                   double repeatV, double factor, double spacing, double distance, int most,
                                                                   double* eye) {
    const std::shared_ptr<const Sea> kept = find(sea);
    const std::shared_ptr<const Surface> on = findSurface(surface);
    if (!kept || !on) return -1;
    CLxLoc_StrokeDraw stroke;
    CLxLoc_View view;
    if (!stroke.set(reinterpret_cast<ILxUnknownID>(strokeObject)) || !view.set(reinterpret_cast<ILxUnknownID>(strokeObject))) return -1;
    double at[3], sent[9];
    viewEye(view, at, sent);
    if (eye) std::copy(sent, sent + 9, eye);
    double ca, cb;
    centreOf(*on, at, ca, cb);
    const std::string key = std::string(sea) + "@" + surface;
    const std::vector<float> made =
        surfacePointsFor(key, kept, on, repeatU, repeatV, factor, ca, cb, spacing, distance, size_t(std::max(most, 0)));
    const size_t count = made.size() / 4;
    if (!count) return 0;
    drawBands(stroke, made);
    return int(count);
}
