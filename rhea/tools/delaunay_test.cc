// Checks of rhea/delaunay.h: the triangulation of random, lattice and duplicated points, and the Bregman flips.
// Prints one JSON line; exits non-zero on the first failed check.
#include "delaunay.h"
#include <cstdio>
#include <random>
#include <set>

using namespace rhea;

static int failures = 0;
static void check(bool ok, const char* what) {
    if (!ok) {
        std::fprintf(stderr, "FAILED: %s\n", what);
        ++failures;
    }
}

static double orient(const std::vector<double>& c, int a, int b, int d) {
    return (c[2 * a + 1] - c[2 * d + 1]) * (c[2 * b] - c[2 * d]) - (c[2 * a] - c[2 * d]) * (c[2 * b + 1] - c[2 * d + 1]);
}

// The convex hull's area (monotone chain) of the points.
static double hullArea(const std::vector<double>& c) {
    std::vector<std::pair<double, double>> p;
    for (size_t i = 0; i < c.size(); i += 2) p.push_back({c[i], c[i + 1]});
    std::sort(p.begin(), p.end());
    p.erase(std::unique(p.begin(), p.end()), p.end());
    if (p.size() < 3) return 0;
    std::vector<std::pair<double, double>> h(2 * p.size());
    size_t k = 0;
    auto cross = [](auto o, auto a, auto b) { return (a.first - o.first) * (b.second - o.second) - (a.second - o.second) * (b.first - o.first); };
    for (size_t i = 0; i < p.size(); ++i) {
        while (k >= 2 && cross(h[k - 2], h[k - 1], p[i]) <= 0) --k;
        h[k++] = p[i];
    }
    for (size_t i = p.size() - 1, t = k + 1; i > 0; --i) {
        while (k >= t && cross(h[k - 2], h[k - 1], p[i - 1]) <= 0) --k;
        h[k++] = p[i - 1];
    }
    h.resize(k - 1);
    double a = 0;
    for (size_t i = 0; i < h.size(); ++i) a += h[i].first * h[(i + 1) % h.size()].second - h[(i + 1) % h.size()].first * h[i].second;
    return std::fabs(a) / 2;
}

// Valid half-edges, one orientation, the hull covered, and (Delaunay) every edge locally Delaunay.
static void valid(const std::vector<double>& c, const Delaunay& d, bool delaunay, const char* name) {
    const auto& t = d.triangles;
    const auto& h = d.halfedges;
    bool pairs = true, orientation = true, local = true;
    double area = 0;
    int sign = 0;
    for (size_t e = 0; e < t.size(); ++e) {
        if (h[e] != -1) {
            const int o = h[e];
            pairs = pairs && h[o] == int(e) && t[e] == t[Delaunay::next(o)] && t[Delaunay::next(int(e))] == t[o];
        }
        if (e % 3 == 0) {
            const double s = orient(c, t[e], t[e + 1], t[e + 2]);
            const int sg = s > 0 ? 1 : (s < 0 ? -1 : 0);
            if (!sign) sign = sg;
            orientation = orientation && sg == sign;
            area += std::fabs(s) / 2;
        }
        if (delaunay && h[e] != -1 && int(e) < h[e]) {
            // The opposite point of the other triangle outside this one's circumcircle (within rounding).
            const int a0 = int(e) - int(e) % 3;
            const int p0 = t[a0 + (e + 2) % 3], pr = t[e], pl = t[a0 + (e + 1) % 3];
            const int o = h[e];
            const int p1 = t[o - o % 3 + (o + 2) % 3];
            const double ax = c[2 * p0] - c[2 * p1], ay = c[2 * p0 + 1] - c[2 * p1 + 1], bx = c[2 * pr] - c[2 * p1], by = c[2 * pr + 1] - c[2 * p1 + 1];
            const double cx = c[2 * pl] - c[2 * p1], cy = c[2 * pl + 1] - c[2 * p1 + 1];
            const double det = ax * (by * (cx * cx + cy * cy) - (bx * bx + by * by) * cy) - ay * (bx * (cx * cx + cy * cy) - (bx * bx + by * by) * cx) +
                               (ax * ax + ay * ay) * (bx * cy - by * cx);
            const double scale = (ax * ax + ay * ay + bx * bx + by * by + cx * cx + cy * cy);
            local = local && det >= -1e-9 * scale * scale;
        }
    }
    char what[256];
    std::snprintf(what, sizeof what, "%s: half-edges pair up", name);
    check(pairs, what);
    std::snprintf(what, sizeof what, "%s: one orientation", name);
    check(orientation, what);
    const double hull = hullArea(c);
    std::snprintf(what, sizeof what, "%s: the triangles cover the hull (%.6f of %.6f)", name, area, hull);
    check(std::fabs(area - hull) <= 1e-7 * std::max(1.0, hull), what);
    if (delaunay) {
        std::snprintf(what, sizeof what, "%s: every edge locally Delaunay", name);
        check(local, what);
    }
}

int main() {
    std::mt19937 rng(7);
    std::uniform_real_distribution<double> u(0, 320);
    // Random points.
    {
        std::vector<double> c;
        for (int i = 0; i < 3000; ++i) c.push_back(u(rng)), c.push_back(u(rng) * 0.75);
        Delaunay d(c);
        valid(c, d, true, "random");
        check(d.triangles.size() / 3 == size_t(2 * 3000 - int(d.hull.size()) - 2), "random: 2n - h - 2 triangles");
    }
    // A lattice (co-circular quads everywhere) with a few points on top of others.
    {
        std::vector<double> c;
        for (int y = 0; y <= 240; y += 8)
            for (int x = 0; x <= 320; x += 8) c.push_back(x + 0.5), c.push_back(y + 0.5);
        for (int i = 0; i < 40; ++i) c.push_back(c[2 * i * 7]), c.push_back(c[2 * i * 7 + 1]);  // duplicates
        Delaunay d(c);
        valid(c, d, true, "lattice");
    }
    // Lattice points jittered within their cells, as reprojected probes land.
    {
        std::vector<double> c;
        std::uniform_real_distribution<double> j(-3.5, 3.5);
        for (int y = 0; y <= 240; y += 8)
            for (int x = 0; x <= 320; x += 8) c.push_back(x + j(rng)), c.push_back(y + j(rng));
        Delaunay d(c);
        valid(c, d, true, "jittered");
        // Bregman flips over a lifted paraboloid cap (concave inverse depth, as a ball's front) and a saddle: still a
        // valid triangulation of the same hull.
        const int n = int(c.size() / 2);
        std::vector<double> w(n);
        std::vector<Plane> h(n);
        // k 0: a round cap, w = 1 - a (x^2 + y^2): its lift is a paraboloid, so the Bregman Delaunay triangulation is the
        // Euclidean one (no flip); 1: a stretched cap (a != b), which it is not (flips); 2: a saddle, where a quad flips
        // only if its four probes happen to agree on one convexity (rare).
        const double as[3] = {0.3, 0.3, 0.3}, bs[3] = {0.3, 0.02, -0.3};
        const char* names[3] = {"round cap", "stretched cap", "saddle"};
        int flips[3] = {};
        for (int k = 0; k < 3; ++k) {
            Delaunay e(c);
            for (int i = 0; i < n; ++i) {
                const double x = (c[2 * i] - 160) / 160, y = (c[2 * i + 1] - 120) / 160;
                const double a = as[k], b = bs[k];
                w[i] = 1 - a * x * x - b * y * y;
                h[i].a = -2 * a * x / 160, h[i].b = -2 * b * y / 160;
                h[i].c = w[i] - h[i].a * c[2 * i] - h[i].b * c[2 * i + 1];
                h[i].ok = true;
            }
            flips[k] = e.bregmanFlips(w, h);
            valid(c, e, false, names[k]);
            std::printf("{\"flips\": \"%s\", \"count\": %d, \"edges\": %d}\n", names[k], flips[k], int(e.triangles.size() / 2));
        }
        check(flips[0] == 0, "a round cap: the Euclidean triangulation, no flip");
        check(flips[1] > 0, "a stretched cap: Bregman flips");
        check(flips[2] * 100 < int(c.size()), "a saddle: flips rare");
    }
    // Too few points, all on one line.
    {
        Delaunay a(std::vector<double>{0, 0, 1, 1});
        check(a.triangles.empty(), "two points: no triangle");
        Delaunay b(std::vector<double>{0, 0, 1, 1, 2, 2, 3, 3});
        check(b.triangles.empty(), "collinear: no triangle");
    }
    std::printf("{\"status\":\"%s\",\"failures\":%d}\n", failures ? "failed" : "passed", failures);
    return failures ? 1 : 0;
}
