// A 2D Delaunay triangulation of the frame's probes (rhea/DESIGN.md 18), then flipped to the Bregman Delaunay one.
//
// The triangulation is Delaunator's (Vladimir Agafonkin, ISC license): a sweep-hull insertion in order of distance from a
// seed triangle's circumcentre, with Lawson flips, kept as half-edges (triangles[e] is half-edge e's start, e and
// halfedges[e] the two sides of one edge, -1 on the hull). Near-duplicate points are left out of it.
//
// bregmanFlips then turns the Euclidean triangulation into the Bregman Delaunay one where the probes' local convexity
// agrees (bvd.h quadDiagonal: the lower hull of the lifted sites, sign by their tangent planes): an edge of a convex quad
// takes the quad's other diagonal when that one is lower in the lift. On a plane the two are the same triangulation (an
// affine generator changes no diagram, the paper's Property 4).
#pragma once
#include "bvd.h"
#include <cmath>
#include <cstdint>
#include <limits>
#include <numeric>
#include <vector>

namespace rhea {

class Delaunay {
public:
    std::vector<int> triangles;  // three point indices a triangle
    std::vector<int> halfedges;  // the other side of each half-edge, -1 on the hull
    std::vector<int> hull;       // the hull's points in order

    explicit Delaunay(std::vector<double> coords) : coords_(std::move(coords)) {
        const int n = int(coords_.size() / 2);
        if (n < 3) return;
        const int maxTriangles = std::max(2 * n - 5, 0);
        triangles.assign(size_t(maxTriangles) * 3, 0);
        halfedges.assign(size_t(maxTriangles) * 3, -1);
        hashSize_ = int(std::ceil(std::sqrt(double(n))));
        hullPrev_.assign(n, 0), hullNext_.assign(n, 0), hullTri_.assign(n, 0), hullHash_.assign(hashSize_, -1);
        std::vector<int> ids(n);
        std::vector<double> dists(n);
        double minX = 1e300, minY = 1e300, maxX = -1e300, maxY = -1e300;
        for (int i = 0; i < n; ++i) {
            const double x = X(i), y = Y(i);
            minX = std::min(minX, x), minY = std::min(minY, y), maxX = std::max(maxX, x), maxY = std::max(maxY, y);
            ids[i] = i;
        }
        const double cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
        int i0 = 0, i1 = -1, i2 = -1;
        double best = 1e300;
        for (int i = 0; i < n; ++i) {
            const double d = dist(cx, cy, X(i), Y(i));
            if (d < best) i0 = i, best = d;
        }
        best = 1e300;
        for (int i = 0; i < n; ++i) {
            if (i == i0) continue;
            const double d = dist(X(i0), Y(i0), X(i), Y(i));
            if (d < best && d > 0) i1 = i, best = d;
        }
        if (i1 < 0) return;  // every point the same
        double minRadius = 1e300;
        for (int i = 0; i < n; ++i) {
            if (i == i0 || i == i1) continue;
            const double r = circumradius(X(i0), Y(i0), X(i1), Y(i1), X(i), Y(i));
            if (r < minRadius) i2 = i, minRadius = r;
        }
        if (i2 < 0 || !(minRadius < 1e300)) {
            triangles.clear(), halfedges.clear();  // all on one line: no triangle
            return;
        }
        if (orient(X(i0), Y(i0), X(i1), Y(i1), X(i2), Y(i2)) < 0) std::swap(i1, i2);
        circumcenter(X(i0), Y(i0), X(i1), Y(i1), X(i2), Y(i2), cx_, cy_);
        for (int i = 0; i < n; ++i) dists[i] = dist(X(i), Y(i), cx_, cy_);
        std::stable_sort(ids.begin(), ids.end(), [&](int a, int b) { return dists[a] < dists[b]; });
        hullStart_ = i0;
        int hullSize = 3;
        hullNext_[i0] = hullPrev_[i2] = i1;
        hullNext_[i1] = hullPrev_[i0] = i2;
        hullNext_[i2] = hullPrev_[i1] = i0;
        hullTri_[i0] = 0, hullTri_[i1] = 1, hullTri_[i2] = 2;
        hullHash_[hashKey(X(i0), Y(i0))] = i0;
        hullHash_[hashKey(X(i1), Y(i1))] = i1;
        hullHash_[hashKey(X(i2), Y(i2))] = i2;
        length_ = 0;
        addTriangle(i0, i1, i2, -1, -1, -1);
        double xp = 0, yp = 0;
        for (int k = 0; k < n; ++k) {
            const int i = ids[k];
            const double x = X(i), y = Y(i);
            const double eps = std::numeric_limits<double>::epsilon();
            if (k > 0 && std::fabs(x - xp) <= eps && std::fabs(y - yp) <= eps) continue;  // a near-duplicate
            xp = x, yp = y;
            if (i == i0 || i == i1 || i == i2) continue;
            // A visible edge of the hull, found through the hash.
            int start = 0;
            for (int j = 0, key = hashKey(x, y); j < hashSize_; ++j) {
                start = hullHash_[(key + j) % hashSize_];
                if (start != -1 && start != hullNext_[start]) break;
            }
            start = hullPrev_[start];
            int e = start, q;
            while (q = hullNext_[e], orient(x, y, X(e), Y(e), X(q), Y(q)) >= 0) {
                e = q;
                if (e == start) {
                    e = -1;
                    break;
                }
            }
            if (e == -1) continue;  // a near-duplicate, most likely
            int t = addTriangle(e, i, hullNext_[e], -1, -1, hullTri_[e]);
            hullTri_[i] = legalize(t + 2);
            hullTri_[e] = t;
            ++hullSize;
            int nn = hullNext_[e];
            while (q = hullNext_[nn], orient(x, y, X(nn), Y(nn), X(q), Y(q)) < 0) {
                t = addTriangle(nn, i, q, hullTri_[i], -1, hullTri_[nn]);
                hullTri_[i] = legalize(t + 2);
                hullNext_[nn] = nn;  // off the hull
                --hullSize;
                nn = q;
            }
            if (e == start) {
                while (q = hullPrev_[e], orient(x, y, X(q), Y(q), X(e), Y(e)) < 0) {
                    t = addTriangle(q, i, e, -1, hullTri_[e], hullTri_[q]);
                    legalize(t + 2);
                    hullTri_[q] = t;
                    hullNext_[e] = e;
                    --hullSize;
                    e = q;
                }
            }
            hullStart_ = hullPrev_[i] = e;
            hullNext_[e] = hullPrev_[nn] = i;
            hullNext_[i] = nn;
            hullHash_[hashKey(x, y)] = i;
            hullHash_[hashKey(X(e), Y(e))] = e;
        }
        hull.resize(hullSize);
        for (int i = 0, e = hullStart_; i < hullSize; ++i) hull[i] = e, e = hullNext_[e];
        triangles.resize(length_), halfedges.resize(length_);
    }

    static int next(int e) { return e % 3 == 2 ? e - 2 : e + 1; }
    static int prev(int e) { return e % 3 == 0 ? e + 2 : e - 1; }

    // The Bregman flips (see the head of this file): w the points' inverse depths, h their tangent planes. Returns the
    // number of edges flipped. Quads whose four sites are a saddle keep their Euclidean diagonal.
    int bregmanFlips(const std::vector<double>& w, const std::vector<Plane>& h, int passes = 4) {
        int flipped = 0;
        for (int pass = 0; pass < passes; ++pass) {
            int now = 0;
            for (int a = 0; a < int(triangles.size()); ++a) {
                const int b = halfedges[a];
                if (b < a) continue;  // each edge once (and none on the hull)
                const int a0 = a - a % 3, b0 = b - b % 3;
                const int ar = a0 + (a + 2) % 3, al = a0 + (a + 1) % 3, bl = b0 + (b + 2) % 3;
                const int p0 = triangles[ar], pr = triangles[a], pl = triangles[al], p1 = triangles[bl];
                // The quad pr, p1, pl, p0 with the diagonal pr-pl; only a convex one may take p0-p1.
                const double s1 = orient(X(pr), Y(pr), X(pl), Y(pl), X(p0), Y(p0)), s2 = orient(X(pr), Y(pr), X(pl), Y(pl), X(p1), Y(p1));
                const double s3 = orient(X(p0), Y(p0), X(p1), Y(p1), X(pr), Y(pr)), s4 = orient(X(p0), Y(p0), X(p1), Y(p1), X(pl), Y(pl));
                if (!(s1 * s2 < 0 && s3 * s4 < 0)) continue;
                const double qx[4] = {X(pr), X(p1), X(pl), X(p0)}, qy[4] = {Y(pr), Y(p1), Y(pl), Y(p0)};
                const double qw[4] = {w[pr], w[p1], w[pl], w[p0]};
                const Plane qh[4] = {h[pr], h[p1], h[pl], h[p0]};
                if (!(qh[0].ok && qh[1].ok && qh[2].ok && qh[3].ok)) continue;
                const int sign = convexity(qx, qy, qw, qh, 4);
                if (sign == 0) continue;
                if (quadDiagonal(qx, qy, qw, sign)) continue;  // pr-pl is the lower: as it is
                // Flip to p0-p1, as Delaunator's legalize does.
                triangles[a] = p1;
                triangles[b] = p0;
                const int hbl = halfedges[bl], har = halfedges[ar];
                link(a, hbl);
                link(b, har);
                link(ar, bl);
                ++now;
            }
            flipped += now;
            if (!now) break;
        }
        return flipped;
    }

private:
    std::vector<double> coords_;  // the points, x then y, kept for the flips
    std::vector<int> hullPrev_, hullNext_, hullTri_, hullHash_;
    int hashSize_ = 0, hullStart_ = 0, length_ = 0;
    double cx_ = 0, cy_ = 0;

    double X(int i) const { return coords_[2 * size_t(i)]; }
    double Y(int i) const { return coords_[2 * size_t(i) + 1]; }
    static double dist(double ax, double ay, double bx, double by) { return (ax - bx) * (ax - bx) + (ay - by) * (ay - by); }
    // robust-predicates' orient2d formula (its sign convention, used consistently below).
    static double orient(double ax, double ay, double bx, double by, double cx, double cy) {
        return (ay - cy) * (bx - cx) - (ax - cx) * (by - cy);
    }
    static bool inCircle(double ax, double ay, double bx, double by, double cx, double cy, double px, double py) {
        const double dx = ax - px, dy = ay - py, ex = bx - px, ey = by - py, fx = cx - px, fy = cy - py;
        const double ap = dx * dx + dy * dy, bp = ex * ex + ey * ey, cp = fx * fx + fy * fy;
        return dx * (ey * cp - bp * fy) - dy * (ex * cp - bp * fx) + ap * (ex * fy - ey * fx) < 0;
    }
    static double circumradius(double ax, double ay, double bx, double by, double cx, double cy) {
        const double dx = bx - ax, dy = by - ay, ex = cx - ax, ey = cy - ay;
        const double bl = dx * dx + dy * dy, cl = ex * ex + ey * ey, den = dx * ey - dy * ex;
        if (den == 0) return 1e300;
        const double d = 0.5 / den;
        const double x = (ey * bl - dy * cl) * d, y = (dx * cl - ex * bl) * d;
        const double r = x * x + y * y;
        return std::isfinite(r) ? r : 1e300;
    }
    static void circumcenter(double ax, double ay, double bx, double by, double cx, double cy, double& ox, double& oy) {
        const double dx = bx - ax, dy = by - ay, ex = cx - ax, ey = cy - ay;
        const double bl = dx * dx + dy * dy, cl = ex * ex + ey * ey, d = 0.5 / (dx * ey - dy * ex);
        ox = ax + (ey * bl - dy * cl) * d;
        oy = ay + (dx * cl - ex * bl) * d;
    }
    int hashKey(double x, double y) const {
        const double dx = x - cx_, dy = y - cy_;
        const double s = std::fabs(dx) + std::fabs(dy);
        const double p = s > 0 ? dx / s : 0;
        const double angle = (dy > 0 ? 3 - p : 1 + p) / 4;  // a pseudo-angle in [0, 1]
        return int(std::floor(angle * hashSize_)) % hashSize_;
    }
    void link(int a, int b) {
        halfedges[a] = b;
        if (b != -1) halfedges[b] = a;
    }
    int addTriangle(int i0, int i1, int i2, int a, int b, int c) {
        const int t = length_;
        triangles[t] = i0, triangles[t + 1] = i1, triangles[t + 2] = i2;
        link(t, a), link(t + 1, b), link(t + 2, c);
        length_ += 3;
        return t;
    }
    int legalize(int a) {
        int stack[1024];
        int i = 0, ar = 0;
        for (;;) {
            const int b = halfedges[a];
            const int a0 = a - a % 3;
            ar = a0 + (a + 2) % 3;
            if (b == -1) {
                if (i == 0) break;
                a = stack[--i];
                continue;
            }
            const int b0 = b - b % 3, al = a0 + (a + 1) % 3, bl = b0 + (b + 2) % 3;
            const int p0 = triangles[ar], pr = triangles[a], pl = triangles[al], p1 = triangles[bl];
            if (inCircle(X(p0), Y(p0), X(pr), Y(pr), X(pl), Y(pl), X(p1), Y(p1))) {
                triangles[a] = p1;
                triangles[b] = p0;
                const int hbl = halfedges[bl];
                if (hbl == -1) {  // the edge swapped on the hull's other side: fix the hull's triangle
                    int e = hullStart_;
                    do {
                        if (hullTri_[e] == bl) {
                            hullTri_[e] = a;
                            break;
                        }
                        e = hullPrev_[e];
                    } while (e != hullStart_);
                }
                link(a, hbl);
                link(b, halfedges[ar]);
                link(ar, bl);
                const int br = b0 + (b + 1) % 3;
                if (i < 1024) stack[i++] = br;
            } else {
                if (i == 0) break;
                a = stack[--i];
            }
        }
        return ar;
    }
};

}  // namespace rhea
