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
// blended bilinearly. The displacement image's own (push along U, height, push along V), summed over the tiles.
void displacement(const Sea& sea, double u, double v, double out[3]) {
    out[0] = out[1] = out[2] = 0.0;
    for (const Part& part : sea.parts) {
        double su = (u * part.cosTurn + v * part.sinTurn) * part.ratio, sv = (-u * part.sinTurn + v * part.cosTurn) * part.ratio;
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
    LXtVector centre;
    view.Center(centre);
    double cx = centre[0], cy = centre[1], cz = centre[2], first = 0.0, second = 0.0;
    const int type = view.Type();
    // Looking through a camera, the view's centre is the camera itself (seen in Modo 16.1, 2026-11-21: a camera at
    // (0, 6, 0) gave that centre, while EyeVector measured from 4 m behind it, which put the points' middle there).
    // In a perspective view the centre is the point it turns about: the eye is found back from a point well ahead
    // along the way it looks.
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
    if (eye) {
        const double sent[9] = {cx, cy, cz, double(type), centre[0], centre[1], centre[2], first, second};
        std::copy(sent, sent + 9, eye);
    }
    const std::vector<float> made = pointsFor(name, sea, cx, cz, height, tile, factor, spacing, distance, size_t(std::max(most, 0)));
    const size_t count = made.size() / 4;
    if (!count) return 0;
    (void)red;
    (void)green;
    (void)blue;
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
    return int(count);
}
