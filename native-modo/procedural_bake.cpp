// procedurals.bake's patterns, for the plugin's Python: Modo's Grid, Dots, Cellular, Wood, Weave and Ripples laid flat
// over one unit of UV, as procedurals.sample works them out (the same arithmetic in doubles, the same order, the same
// random numbers: _chance's BLAKE2b of the whole numbers, 4 bytes), so a bake is the one Python made, pixel for pixel
// to a float's last digit. Done here over the machine's threads with Python's lock let go: in Python a 512 pixel bake
// took seconds, and the slower patterns were held to 256; a final render's at 2048 would have taken minutes.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>

namespace {

const double PI = 3.14159265358979323846;

// ---- BLAKE2b (RFC 7693), unkeyed, a digest of outlen bytes: what hashlib.blake2b(data, digest_size=outlen) gives ----
const uint64_t IV[8] = {0x6a09e667f3bcc908ULL, 0xbb67ae8584caa73bULL, 0x3c6ef372fe94f82bULL, 0xa54ff53a5f1d36f1ULL,
                        0x510e527fade682d1ULL, 0x9b05688c2b3e6c1fULL, 0x1f83d9abfb41bd6bULL, 0x5be0cd19137e2179ULL};
const uint8_t SIGMA[12][16] = {
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}, {14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3},
    {11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4}, {7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8},
    {9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13}, {2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9},
    {12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11}, {13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10},
    {6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5}, {10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0},
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}, {14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3}};

inline uint64_t rotr(uint64_t x, int n) { return (x >> n) | (x << (64 - n)); }

void compress(uint64_t h[8], const uint8_t block[128], uint64_t counter, bool last) {
    uint64_t v[16], m[16];
    for (int i = 0; i < 16; ++i) {
        uint64_t w = 0;
        for (int b = 7; b >= 0; --b) w = (w << 8) | block[8 * i + b];
        m[i] = w;
    }
    for (int i = 0; i < 8; ++i) { v[i] = h[i]; v[i + 8] = IV[i]; }
    v[12] ^= counter;
    if (last) v[14] = ~v[14];
    auto g = [&](int a, int b, int c, int d, uint64_t x, uint64_t y) {
        v[a] = v[a] + v[b] + x; v[d] = rotr(v[d] ^ v[a], 32);
        v[c] = v[c] + v[d];     v[b] = rotr(v[b] ^ v[c], 24);
        v[a] = v[a] + v[b] + y; v[d] = rotr(v[d] ^ v[a], 16);
        v[c] = v[c] + v[d];     v[b] = rotr(v[b] ^ v[c], 63);
    };
    for (int r = 0; r < 12; ++r) {
        const uint8_t* s = SIGMA[r];
        g(0, 4, 8, 12, m[s[0]], m[s[1]]);   g(1, 5, 9, 13, m[s[2]], m[s[3]]);
        g(2, 6, 10, 14, m[s[4]], m[s[5]]);  g(3, 7, 11, 15, m[s[6]], m[s[7]]);
        g(0, 5, 10, 15, m[s[8]], m[s[9]]);  g(1, 6, 11, 12, m[s[10]], m[s[11]]);
        g(2, 7, 8, 13, m[s[12]], m[s[13]]); g(3, 4, 9, 14, m[s[14]], m[s[15]]);
    }
    for (int i = 0; i < 8; ++i) h[i] ^= v[i] ^ v[i + 8];
}

// _chance: the whole numbers packed as little-endian 64-bit ('<%dq'), their 4-byte BLAKE2b read little-endian, over
// 2^32 - 1. At most a few numbers: one block.
double chance(const int64_t* whole, int count) {
    uint64_t h[8];
    std::memcpy(h, IV, sizeof(h));
    h[0] ^= 0x01010000ULL ^ 4ULL;   // depth 1, fanout 1, no key, a 4-byte digest
    uint8_t block[128] = {0};
    for (int i = 0; i < count; ++i)
        for (int b = 0; b < 8; ++b) block[8 * i + b] = uint8_t(uint64_t(whole[i]) >> (8 * b));
    compress(h, block, uint64_t(8 * count), true);
    const uint32_t digest = uint32_t(h[0] & 0xffffffffULL);
    return double(digest) / 4294967295.0;
}
double chance2(int64_t a, int64_t b) { const int64_t w[2] = {a, b}; return chance(w, 2); }
double chance3(int64_t a, int64_t b, int64_t c) { const int64_t w[3] = {a, b, c}; return chance(w, 3); }

// Python's whole-number rules: % keeps the divisor's sign, round() rounds halves to even, int() cuts toward zero.
inline int64_t pymod(int64_t a, int64_t b) { int64_t r = a % b; return (r != 0 && ((r < 0) != (b < 0))) ? r + b : r; }
inline double pymodf(double a, double b) { double r = std::fmod(a, b); return (r != 0 && ((r < 0) != (b < 0))) ? r + b : r; }
inline int64_t pyround(double x) { return int64_t(std::nearbyint(x)); }
inline double clamp01(double x) { return std::max(0.0, std::min(1.0, x)); }

double bias(double x, double b) {
    b = std::max(.00001, std::min(.99999, b));
    x = std::max(0.0, std::min(1.0, x));
    return x / ((1 / b - 2) * (1 - x) + 1);
}

// The random numbers a bake reads, each worked out once before the threads start (the hash was most of a 2048 pixel
// bake's 12 s): for a noise, every lattice point of its period; for Cellular, every cell of each octave. The same
// numbers as chance gives, read from a table.
struct Table {
    int64_t period = 0, periodY = 0, seed = 0;
    std::vector<double> values;
    void make(int64_t p, int64_t q, int64_t s) {
        period = p; periodY = q; seed = s;
        values.resize(size_t(p) * size_t(q));
        for (int64_t j = 0; j < q; ++j)
            for (int64_t i = 0; i < p; ++i) values[size_t(j) * size_t(p) + size_t(i)] = chance3(i, j, s);
    }
    double at(int64_t i, int64_t j) const { return values[size_t(j) * size_t(period) + size_t(i)]; }
    bool fits(int64_t p, int64_t q, int64_t s) const { return period == p && periodY == q && seed == s; }
};

struct Tables {
    Table wander, grain;                     // Wood's two noises
    std::vector<int64_t> counts;             // Cellular: each octave's cells across
    std::vector<Table> px, py, vary;         // and its points' places and its cells' variation
    std::vector<double> sources;             // Ripples: each source's place, u then v
};
const Tables* TABLES = nullptr;              // set while MR_procedural_bake runs, read by its threads
std::mutex BAKING;                           // one bake at a time: its tables are TABLES

double noise(double x, double y, int64_t period, int64_t seed, int64_t periodY = 0) {
    periodY = periodY ? periodY : period;
    const Table* held = nullptr;
    if (TABLES) for (const Table* t : {&TABLES->wander, &TABLES->grain}) if (t->fits(period, periodY, seed)) held = t;
    const double x0 = std::floor(x), y0 = std::floor(y);
    double fx = x - x0, fy = y - y0;
    fx = fx * fx * (3 - 2 * fx);
    fy = fy * fy * (3 - 2 * fy);
    auto at = [&](double i, double j) {
        const int64_t a = pymod(int64_t(i), period), b = pymod(int64_t(j), periodY);
        return held ? held->at(a, b) : chance3(a, b, seed);
    };
    const double low = at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx;
    const double high = at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx;
    return low * (1 - fy) + high * fy;
}

double step(double value, double edge, double soft) {
    if (soft <= 1e-9) return value >= edge ? 1.0 : 0.0;
    const double t = std::max(0.0, std::min(1.0, (value - edge + soft) / (2 * soft)));
    return t * t * (3 - 2 * t);
}

void cells(double u, double v, int64_t count, bool round_, int64_t seed, double& distance, int64_t nearest[2], int octave = -1) {
    const double x = u * count, y = v * count, cx = std::floor(x), cy = std::floor(y);
    const bool tabled = TABLES && octave >= 0 && size_t(octave) < TABLES->counts.size() && TABLES->counts[octave] == count;
    double first = 9.0, second = 9.0;
    nearest[0] = nearest[1] = 0;
    for (int j = -1; j <= 1; ++j)
        for (int i = -1; i <= 1; ++i) {
            const int64_t a = int64_t(cx + i), b = int64_t(cy + j);
            const int64_t ma = pymod(a, count), mb = pymod(b, count);
            const double px = a + .15 + .7 * (tabled ? TABLES->px[octave].at(ma, mb) : chance3(ma, mb, seed));
            const double py = b + .15 + .7 * (tabled ? TABLES->py[octave].at(ma, mb) : chance3(ma, mb, seed + 1));
            const double d = std::hypot(x - px, y - py);
            if (d < first) { second = first; first = d; nearest[0] = pymod(a, count); nearest[1] = pymod(b, count); }
            else if (d < second) second = d;
        }
    distance = round_ ? first : .5 * (second - first);
}

// The settings, by their place in the array procedurals.native_bake hands over.
enum Slot {Kind, Pattern, Width, Transition, Bias, Gain, C1R, C1G, C1B, C2R, C2G, C2B, Alpha1, Alpha2, Round, CellWidth,
           TransWidth, Freqs, FreqRatio, AmpRatio, Variation, RingScale, Wave, WaveScale, Grain, GrainScale, YarnWidth,
           Roundness, Sources, Wavelength, Phase, SlotCount};
enum Kinds {Grid, Dots, Cellular, Wood, Weave, Ripples};
enum Patterns {Line, Square, Triangle, Hexagon};

double late(const double* d, double u, double v) {
    const int kind = int(d[Kind]);
    u -= std::floor(u);
    v -= std::floor(v);
    if (kind == Cellular) {
        const bool round_ = d[Round] != 0;
        const double width = std::max(0.0, std::min(1.0, d[CellWidth])), soft = .25 * std::max(0.0, d[TransWidth]);
        double total = 0.0, weight = 0.0, amplitude = 1.0;
        int64_t count = 4;
        const int64_t octaves = std::max<int64_t>(1, std::min<int64_t>(4, int64_t(d[Freqs])));
        for (int64_t octave = 0; octave < octaves; ++octave) {
            double distance;
            int64_t cell[2];
            cells(u, v, count, round_, 7 * octave, distance, cell, int(octave));
            double inside = round_ ? step(.5 * width - distance, 0.0, soft) : step(distance, .5 * (1 - width), soft);
            const bool tabled = TABLES && size_t(octave) < TABLES->counts.size() && TABLES->counts[size_t(octave)] == count;
            inside *= 1 - std::max(0.0, std::min(1.0, d[Variation])) * (tabled ? TABLES->vary[size_t(octave)].at(cell[0], cell[1])
                                                                                : chance3(cell[0], cell[1], 13 + octave));
            total += inside * amplitude;
            weight += amplitude;
            amplitude *= std::max(0.0, d[AmpRatio]);
            count = std::max(count + 1, pyround(count * std::max(1.0, d[FreqRatio])));
        }
        return weight != 0 ? total / weight : 0.0;
    }
    if (kind == Wood) {
        const int64_t rings = std::max<int64_t>(1, pyround(1 / std::max(.02, d[RingScale])));
        const int64_t slow = std::max<int64_t>(1, pyround(2 * std::max(.1, d[WaveScale])));
        const double wander = (noise(u * slow, v * slow, slow, 3) - .5) * 2 * std::max(0.0, d[Wave]);
        double ring = u * rings + wander;
        ring -= std::floor(ring);
        double t = 1 - std::pow(ring, .6);
        const int64_t fine = std::max<int64_t>(4, pyround(4 / std::max(.02, d[GrainScale])));
        // Python's // on whole numbers: fine is at least 4, so no sign to mind.
        const int64_t along = std::max<int64_t>(2, fine / 8);
        t += (noise(u * fine, v * along, fine, 5, along) - .5) * std::max(0.0, d[Grain]) * .6;
        return std::max(0.0, std::min(1.0, t));
    }
    if (kind == Weave) {
        const double x = u * 4, y = v * 4, cx = std::floor(x), cy = std::floor(y), fx = x - cx, fy = y - cy;
        const double width = std::max(.05, std::min(1.0, d[YarnWidth]));
        const bool across = pymod(int64_t(cx) + int64_t(cy), 2) == 0;
        const double along = across ? fx : fy, side = across ? fy : fx;
        const double off = std::fabs(side - .5);
        if (off > .5 * width) return 0.0;
        const double profile = std::cos(PI * off / width), arch = std::sin(PI * along);
        const double roundness = std::max(0.0, std::min(1.0, d[Roundness]));
        return std::max(0.0, std::min(1.0, (1 - roundness) + roundness * profile * (.5 + .5 * arch)));
    }
    // Ripples.
    const int64_t sources = std::max<int64_t>(1, std::min<int64_t>(64, int64_t(d[Sources])));
    const double length = std::max(.01, d[Wavelength]);
    double total = 0.0;
    for (int64_t index = 0; index < sources; ++index) {
        const bool tabled = TABLES && TABLES->sources.size() == size_t(2 * sources);
        const double dx = std::fabs(u - (tabled ? TABLES->sources[size_t(2 * index)] : chance2(index, 17)));
        const double dy = std::fabs(v - (tabled ? TABLES->sources[size_t(2 * index + 1)] : chance2(index, 29)));
        const double distance = std::hypot(std::min(dx, 1 - dx), std::min(dy, 1 - dy));
        total += std::cos(2 * PI * (distance / length - d[Phase]));
    }
    return std::max(0.0, std::min(1.0, .5 + .5 * total / std::sqrt(double(sources))));
}

double gained(double t, double g) {
    return t < .5 ? .5 * bias(2 * t, 1 - g) : 1 - .5 * bias(2 - 2 * t, 1 - g);
}

void finish(const double* d, double t, float* rgb, float* alpha) {
    const double low = std::min(d[Alpha1], d[Alpha2]), high = std::max(d[Alpha1], d[Alpha2]);
    const double a = std::min(high, std::max(low, d[Alpha1] * t + d[Alpha2] * (1 - t)));
    for (int c = 0; c < 3; ++c) rgb[c] = float(d[C1R + c] * t + d[C2R + c] * (1 - t));
    alpha[0] = alpha[1] = alpha[2] = float(std::max(0.0, std::min(1.0, a)));
}

void sample(const double* d, double u, double v, float* rgb, float* alpha) {
    const int kind = int(d[Kind]);
    if (kind >= Cellular) {
        double t = bias(late(d, u, v), d[Bias]);
        t = gained(t, d[Gain]);
        finish(d, t, rgb, alpha);
        return;
    }
    const int pattern = int(d[Pattern]);
    double x = u - std::floor(u), y = v - std::floor(v);
    if (pattern == Triangle || pattern == Hexagon) {
        y = v * 2;
        const double row = std::floor(y);
        y -= row;
        x = pymodf(u - .5 * pymodf(row, 2), 1);
    }
    const double dx = std::fabs(x - .5), dy = std::fabs(y - .5);
    double distance;
    if (kind == Dots) distance = std::hypot(dx, dy);
    else if (pattern == Line) distance = std::min(x, 1 - x);
    else if (pattern == Triangle)
        distance = std::min({std::min(y, 1 - y) * .5, std::fabs(pymodf(x + y * .5, 1) - .5), std::fabs(pymodf(x - y * .5, 1) - .5)});
    else if (pattern == Hexagon) distance = std::fabs(std::max(dx, dx * .5 + dy * .75) - .5);
    else distance = std::min({x, 1 - x, y, 1 - y});
    const double radius = std::max(0.0, std::min(1.0, d[Width])) * .5, transition = std::max(0.0, d[Transition]) * .5;
    double t = transition <= 1e-9 ? (distance <= radius ? 1.0 : 0.0)
                                  : std::max(0.0, std::min(1.0, (radius + transition - distance) / (2 * transition)));
    t = t * t * (3 - 2 * t);
    t = bias(t, d[Bias]);
    t = gained(t, d[Gain]);
    finish(d, t, rgb, alpha);
}

}  // namespace

// The pattern over a resolution by resolution square of one unit of UV, rows from v = 0, each pixel sampled at its
// middle: its colour (3 floats a pixel) into rgb, its alpha (as grey, 3 floats a pixel) into alpha. settings holds
// SlotCount numbers in Slot's order. 0 done; 1 settings out of range.
extern "C" __declspec(dllexport) int MR_procedural_bake(const double* settings, int count, int resolution, float* rgb, float* alpha,
                                                        int threads) {
    if (!settings || count != SlotCount || resolution <= 0 || resolution > 16384 || !rgb || !alpha) return 1;
    if (settings[Kind] < Grid || settings[Kind] > Ripples) return 1;
    for (int i = 0; i < count; ++i) if (!std::isfinite(settings[i])) return 1;
    if (threads <= 0) threads = int(std::max(1u, std::thread::hardware_concurrency()));
    std::lock_guard<std::mutex> one(BAKING);
    // The tables the pattern reads, as late() works its sizes out.
    Tables tables;
    const double* d = settings;
    if (int(d[Kind]) == Cellular) {
        int64_t count = 4;
        const int64_t octaves = std::max<int64_t>(1, std::min<int64_t>(4, int64_t(d[Freqs])));
        for (int64_t octave = 0; octave < octaves; ++octave) {
            if (count > 4096) break;   // past this, worked out as it goes
            tables.counts.push_back(count);
            tables.px.emplace_back(); tables.px.back().make(count, count, 7 * octave);
            tables.py.emplace_back(); tables.py.back().make(count, count, 7 * octave + 1);
            tables.vary.emplace_back(); tables.vary.back().make(count, count, 13 + octave);
            count = std::max(count + 1, pyround(count * std::max(1.0, d[FreqRatio])));
        }
    } else if (int(d[Kind]) == Wood) {
        const int64_t slow = std::max<int64_t>(1, pyround(2 * std::max(.1, d[WaveScale])));
        const int64_t fine = std::max<int64_t>(4, pyround(4 / std::max(.02, d[GrainScale])));
        const int64_t along = std::max<int64_t>(2, fine / 8);
        if (slow <= 4096) tables.wander.make(slow, slow, 3);
        if (fine * along <= (int64_t(1) << 24)) tables.grain.make(fine, along, 5);
    }
    if (int(d[Kind]) == Ripples) {
        const int64_t sources = std::max<int64_t>(1, std::min<int64_t>(64, int64_t(d[Sources])));
        for (int64_t index = 0; index < sources; ++index) { tables.sources.push_back(chance2(index, 17)); tables.sources.push_back(chance2(index, 29)); }
    }
    TABLES = &tables;
    threads = std::max(1, std::min(threads, resolution));
    auto rows = [&](int begin, int end) {
        for (int y = begin; y < end; ++y)
            for (int x = 0; x < resolution; ++x) {
                const size_t at = 3 * (size_t(y) * resolution + x);
                sample(settings, (x + .5) / resolution, (y + .5) / resolution, rgb + at, alpha + at);
            }
    };
    std::vector<std::thread> pool;
    const int share = (resolution + threads - 1) / threads;
    for (int t = 0; t < threads; ++t) {
        const int begin = t * share, end = std::min(resolution, begin + share);
        if (begin < end) pool.emplace_back(rows, begin, end);
    }
    for (auto& t : pool) t.join();
    TABLES = nullptr;
    return 0;
}
