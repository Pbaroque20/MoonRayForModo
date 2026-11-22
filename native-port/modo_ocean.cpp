// modo_ocean.dll: an ocean tile as the kit's moonray_modo/ocean.py makes it (Tessendorf's "Simulating Ocean Water"), many
// times faster. The same Phillips spectrum, the same random numbers (splitmix64, Box-Muller), the same scale for the
// heights, written as the same two PFM images: the displacement (dx, height, dz) and the foam.
//
// modo_ocean_tile(resolution, values, 13, displacement.pfm, foam.pfm): see the function at the end.
#include <cmath>
#include <complex>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

using Complex = std::complex<double>;
static const double Pi = 3.14159265358979323846, Gravity = 9.81;

struct Settings {
    int n;
    double size, windSpeed, windDirection, waveHeight, choppiness, smallWaves, windAlignment, againstWind, depth;
    long long seed;
    double loop, foamThreshold, seconds;
    // One cascade of a sea split over tiles of several sizes (ocean.py cascades): the waves of wavenumbers kLow up to
    // kHigh (radians a metre; kHigh 0 for no end), each by its share of the spectrum over its own tile's cells, and the
    // heights' scale given (the cascades' together). fixedScale 0: the whole tile, scaled to its own heights.
    double kLow = 0.0, kHigh = 0.0, fixedScale = 0.0;
    // A cascade looked up turned by this many degrees (the ImageMap's rotation_angle): its sideways push and its slope
    // written turned back into the surface's U and V, so the sea moves as the waves run (count 17).
    double turn = 0.0;
};

static uint64_t splitmix(uint64_t& state) {
    state += 0x9E3779B97F4A7C15ull;
    uint64_t z = state;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

static std::vector<double> gaussians(long long seed, size_t count) {
    uint64_t state = uint64_t(seed) * 0x2545F4914F6CDD1Dull + 1ull;
    std::vector<double> out(2 * count);
    for (size_t i = 0; i < count; ++i) {
        const uint64_t a = splitmix(state), b = splitmix(state);
        const double u1 = double((a >> 11) + 1) / double(1ull << 53), u2 = double(b >> 11) / double(1ull << 53);
        const double r = std::sqrt(-2.0 * std::log(u1));
        out[2 * i] = r * std::cos(2 * Pi * u2);
        out[2 * i + 1] = r * std::sin(2 * Pi * u2);
    }
    return out;
}

static double phillips(const Settings& s, double kx, double kz) {
    const double k2 = kx * kx + kz * kz;
    if (k2 < 1e-12) return 0.0;
    const double k = std::sqrt(k2), big = s.windSpeed * s.windSpeed / Gravity, angle = s.windDirection * Pi / 180.0;
    const double along = (kx * std::cos(angle) + kz * std::sin(angle)) / k;
    double p = std::exp(-1.0 / (k2 * big * big)) / (k2 * k2) * std::pow(std::fabs(along), s.windAlignment);
    if (along < 0) p *= s.againstWind;
    return p * std::exp(-k2 * s.smallWaves * s.smallWaves);
}

// A cell's amplitude before the heights' scale: the whole tile's sqrt(P / 2); a cascade's only within its band, by its
// share of the spectrum over its own cells (sqrt(P / 2) times a cell's width in wavenumber, 2 pi over the tile).
static bool cascaded(const Settings& s) { return s.fixedScale > 0 || s.kLow > 0 || s.kHigh > 0; }

static double cellAmplitude(const Settings& s, double kx, double kz) {
    if (!cascaded(s)) return std::sqrt(phillips(s, kx, kz) / 2.0);
    const double k = std::hypot(kx, kz);
    if (k < s.kLow || (s.kHigh > 0 && k >= s.kHigh)) return 0.0;
    return std::sqrt(phillips(s, kx, kz) / 2.0) * (2 * Pi / s.size);
}

static double frequency(const Settings& s, double k) {
    double w = s.depth > 0 ? std::sqrt(Gravity * k * std::tanh(k * s.depth)) : std::sqrt(Gravity * k);
    if (s.loop > 0) {
        const double w0 = 2 * Pi / s.loop;
        w = std::floor(w / w0) * w0;
    }
    return w;
}

// An inverse DFT without the 1/n, radix 2, in place; stride steps between the elements of one row or column.
static void ifft(Complex* data, int n, int stride) {
    for (int i = 1, j = 0; i < n; ++i) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j |= bit;
        if (i < j) std::swap(data[i * stride], data[j * stride]);
    }
    for (int length = 2; length <= n; length <<= 1) {
        const Complex step = std::polar(1.0, 2 * Pi / length);
        const int half = length / 2;
        for (int start = 0; start < n; start += length) {
            Complex w = 1.0;
            for (int k = start; k < start + half; ++k) {
                const Complex a = data[k * stride], b = data[(k + half) * stride] * w;
                data[k * stride] = a + b;
                data[(k + half) * stride] = a - b;
                w *= step;
            }
        }
    }
}

static void ifft2(std::vector<Complex>& grid, int n) {
    for (int j = 0; j < n; ++j) ifft(grid.data() + size_t(j) * n, n, 1);
    for (int i = 0; i < n; ++i) ifft(grid.data() + i, n, n);
}

static bool writePfm(const std::string& path, int n, const std::vector<float>& values, int channels) {
    const std::string staged = path + ".part";
    FILE* f = std::fopen(staged.c_str(), "wb");
    if (!f) return false;
    std::fprintf(f, "%s\n%d %d\n-1.0\n", channels == 3 ? "PF" : "Pf", n, n);
    const bool ok = std::fwrite(values.data(), sizeof(float), values.size(), f) == values.size();
    std::fclose(f);
    if (!ok) return false;
    std::remove(path.c_str());
    return std::rename(staged.c_str(), path.c_str()) == 0;
}

// The tile's fields: the displacement (dx, height, dz), the foam (grey, three channels) and, where slope is wanted, the
// slope of the displaced surface (the normal of its tangents along x and z, the sideways push included) as the height's
// change across one tile along U and along V, what MoonLightIPR's shading reads where its vertices are too far apart
// for the finest waves (ocean.py). With cutoff (cycles across the tile) above 0, only the waves longer than it: each
// wave weighed by exp(-(cycles / cutoff)^2), so that nothing rings where the long waves end and the short begin.
struct Fields {
    std::vector<float> displacement, foam, slope;
};

static void fields(const Settings& s, const std::vector<Complex>& h0, double scale, const std::vector<double>& ks, double cutoff,
                   bool wantSlope, Fields& out) {
    const int n = s.n;
    std::vector<Complex> pair1(size_t(n) * n), pair2(size_t(n) * n), pair3(size_t(n) * n), pair4(wantSlope ? size_t(n) * n : 0);
    const Complex I(0, 1);
    for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i) {
            const double kx = ks[i], kz = ks[j], k = std::hypot(kx, kz);
            if (k < 1e-12) continue;
            const double w = frequency(s, k) * s.seconds;
            const Complex e(std::cos(w), std::sin(w));
            Complex h = h0[size_t(j) * n + i] * e + std::conj(h0[size_t((n - j) % n) * n + (n - i) % n]) * std::conj(e);
            if (cutoff > 0) {
                const double cycles = k * s.size / (2 * Pi) / cutoff;
                h *= std::exp(-cycles * cycles);
            }
            const Complex dx = -I * (kx / k) * h, dz = -I * (kz / k) * h;
            const size_t at = size_t(j) * n + i;
            pair1[at] = h + I * dx;
            pair2[at] = dz + I * ((kx * kx / k) * h);
            pair3[at] = (kz * kz / k) * h + I * ((kx * kz / k) * h);
            if (wantSlope) pair4[at] = I * kx * h + I * (I * kz * h);   // the height's change along x and along z
        }
    ifft2(pair1, n);
    ifft2(pair2, n);
    ifft2(pair3, n);
    if (wantSlope) ifft2(pair4, n);
    out.displacement.assign(size_t(n) * n * 3, 0.0f);
    out.foam.assign(size_t(n) * n * 3, 0.0f);
    out.slope.assign(wantSlope ? size_t(n) * n * 3 : 0, 0.0f);
    const double chop = s.choppiness, threshold = s.foamThreshold;
    for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i) {
            const size_t at = size_t(j) * n + i;
            const double sign = ((i + j) & 1) ? -1.0 : 1.0;
            const double h = pair1[at].real() * sign * scale, dx = pair1[at].imag() * sign * scale;
            const double dz = pair2[at].real() * sign * scale, jxx = pair2[at].imag() * sign * scale;
            const double jzz = pair3[at].real() * sign * scale, jxz = pair3[at].imag() * sign * scale;
            // Turned from the tile's axes into the surface's (the lookup turns surface to tile by -turn: vectors back by +turn).
            const double c = std::cos(s.turn * Pi / 180.0), sn = std::sin(s.turn * Pi / 180.0);
            out.displacement[3 * at] = float(chop * (c * dx - sn * dz));
            out.displacement[3 * at + 1] = float(h);
            out.displacement[3 * at + 2] = float(chop * (sn * dx + c * dz));
            const double jacobian = (1 + chop * jxx) * (1 + chop * jzz) - (chop * jxz) * (chop * jxz);
            const float f = threshold > 0 ? float(std::fmin(1.0, std::fmax(0.0, (threshold - jacobian) / threshold))) : 0.0f;
            out.foam[3 * at] = out.foam[3 * at + 1] = out.foam[3 * at + 2] = f;
            if (wantSlope) {
                const double hx = pair4[at].real() * sign * scale, hz = pair4[at].imag() * sign * scale;
                const double a = 1 + chop * jxx, b = 1 + chop * jzz, e = chop * jxz;
                const double held = std::fmax(jacobian, 0.05);
                const double gx = (b * hx - e * hz) / held * s.size, gz = (a * hz - e * hx) / held * s.size;
                out.slope[3 * at] = float(c * gx - sn * gz);
                out.slope[3 * at + 1] = float(sn * gx + c * gz);
                out.slope[3 * at + 2] = 0.0f;
            }
        }
}

// The tile for these settings, written as the PFM images (the slope where slopePath is given; with cutoff above 0 and
// both paths given, also the long waves' displacement and the shorter waves as a tangent-space normal map, ocean.py
// split): 0; 2 for settings out of range; 1 where the images cannot be written.
static int tile(const Settings& s, const char* displacementPath, const char* foamPath, const char* slopePath, double cutoff = 0.0,
                const char* coarsePath = nullptr, const char* finePath = nullptr) {
    const int n = s.n;
    if (n < 2 || (n & (n - 1)) || n > 4096 || !(s.size > 0) || !(s.windSpeed > 0)) return 2;
    const bool split = cutoff > 0 && coarsePath && finePath;
    if ((coarsePath || finePath) && !split) return 2;
    std::vector<double> ks(n);
    for (int i = 0; i < n; ++i) ks[i] = 2 * Pi * (i - n / 2) / s.size;
    const std::vector<double> noise = gaussians(s.seed, size_t(n) * n);
    std::vector<Complex> h0(size_t(n) * n);
    for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i) {
            const double amplitude = cellAmplitude(s, ks[i], ks[j]);
            const size_t at = size_t(j) * n + i;
            h0[at] = Complex(noise[2 * at] * amplitude, noise[2 * at + 1] * amplitude);
        }
    double scale = s.fixedScale;
    if (!(scale > 0)) {
        double variance = 0.0;
        for (int j = 0; j < n; ++j)
            for (int i = 0; i < n; ++i)
                variance += std::norm(h0[size_t(j) * n + i]) + std::norm(h0[size_t((n - j) % n) * n + (n - i) % n]);
        const double target = s.waveHeight * 0.21 * s.windSpeed * s.windSpeed / Gravity / 4.0;
        scale = variance > 0 ? target / std::sqrt(variance) : 0.0;
    }

    Fields full;
    fields(s, h0, scale, ks, 0.0, slopePath != nullptr || split, full);
    if (!writePfm(displacementPath, n, full.displacement, 3) || !writePfm(foamPath, n, full.foam, 3)) return 1;
    if (slopePath && !writePfm(slopePath, n, full.slope, 3)) return 1;
    if (split) {
        // The long waves, for a displacement a renderer's dicing can follow; the rest as a normal map over them: the
        // slope less the long waves' slope, as a tangent-space normal (U, V, the surface's normal), 0 to 1.
        Fields coarse;
        fields(s, h0, scale, ks, cutoff, true, coarse);
        std::vector<float> fine(size_t(n) * n * 3);
        for (size_t at = 0; at < size_t(n) * n; ++at) {
            const double fx = (full.slope[3 * at] - coarse.slope[3 * at]) / s.size;
            const double fz = (full.slope[3 * at + 1] - coarse.slope[3 * at + 1]) / s.size;
            const double length = std::sqrt(fx * fx + fz * fz + 1.0);
            fine[3 * at] = float(0.5 - 0.5 * fx / length);
            fine[3 * at + 1] = float(0.5 - 0.5 * fz / length);
            fine[3 * at + 2] = float(0.5 + 0.5 / length);
        }
        if (!writePfm(coarsePath, n, coarse.displacement, 3) || !writePfm(finePath, n, fine, 3)) return 1;
    }
    return 0;
}

// What the kit calls (moonray_modo/ocean.py, by ctypes): the resolution, then values in ocean.py's arguments() order
// (size, wind speed, wind direction, wave height, choppiness, small waves, wind alignment, against wind, depth, seed,
// loop, foam threshold, seconds), and the two images' paths. The same returns as tile().
extern "C" __declspec(dllexport) int modo_ocean_tile_slope(int resolution, const double* values, int count, const char* displacementPath,
                                                           const char* foamPath, const char* slopePath);

extern "C" __declspec(dllexport) int modo_ocean_tile(int resolution, const double* values, int count, const char* displacementPath,
                                                     const char* foamPath) {
    return modo_ocean_tile_slope(resolution, values, count, displacementPath, foamPath, nullptr);
}

static bool settings(int resolution, const double* values, int count, Settings& s) {
    if (!values || (count != 13 && count != 16 && count != 17)) return false;
    s.n = resolution;
    s.size = values[0];
    s.windSpeed = values[1];
    s.windDirection = values[2];
    s.waveHeight = values[3];
    s.choppiness = values[4];
    s.smallWaves = values[5];
    s.windAlignment = values[6];
    s.againstWind = values[7];
    s.depth = values[8];
    s.seed = (long long)values[9];
    s.loop = values[10];
    s.foamThreshold = values[11];
    s.seconds = values[12];
    if (count >= 16) {
        s.kLow = values[13];
        s.kHigh = values[14];
        s.fixedScale = values[15];
    }
    if (count == 17) s.turn = values[16];
    return true;
}

// A cascade's expected variance of the heights before their scale (count 16, the scale ignored): the sum over its band's
// cells of both halves' expected power, 2 P(k) times a cell's area in wavenumber. The cascades' sum gives the scale that
// makes the sea's heights a fully developed sea's for its wind, as one tile's are. 0, or 2 for settings out of range.
extern "C" __declspec(dllexport) int modo_ocean_band_variance(int resolution, const double* values, int count, double* variance) {
    Settings s;
    if (!settings(resolution, values, count, s) || !variance || resolution < 2 || (resolution & (resolution - 1)) || !(s.size > 0)) return 2;
    const int n = resolution;
    const double cell = 2 * Pi / s.size;
    double sum = 0.0;
    for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i) {
            const double kx = cell * (i - n / 2), kz = cell * (j - n / 2), k = std::hypot(kx, kz);
            if (k < 1e-12 || k < s.kLow || (s.kHigh > 0 && k >= s.kHigh)) continue;
            sum += 2.0 * phillips(s, kx, kz) * cell * cell;
        }
    *variance = sum;
    return 0;
}

// As modo_ocean_tile, and the slope image too where slopePath is given.
extern "C" __declspec(dllexport) int modo_ocean_tile_slope(int resolution, const double* values, int count, const char* displacementPath,
                                                           const char* foamPath, const char* slopePath) {
    Settings s;
    if (!settings(resolution, values, count, s) || !displacementPath || !foamPath) return 2;
    return tile(s, displacementPath, foamPath, slopePath);
}

// As modo_ocean_tile_slope, and the tile split at cutoff cycles across it (tile above): the long waves' displacement
// (coarsePath) and the shorter waves as a normal map (finePath), for MoonRay, whose dicing follows only the long ones.
extern "C" __declspec(dllexport) int modo_ocean_tile_split(int resolution, const double* values, int count, const char* displacementPath,
                                                           const char* foamPath, const char* slopePath, double cutoff,
                                                           const char* coarsePath, const char* finePath) {
    Settings s;
    if (!settings(resolution, values, count, s) || !displacementPath || !foamPath || !slopePath || !(cutoff > 0) || !coarsePath || !finePath)
        return 2;
    return tile(s, displacementPath, foamPath, slopePath, cutoff, coarsePath, finePath);
}

// ---- The sea's long waves, for a viewport ---------------------------------------------------------------------------
// The kit's ocean_viewport.py draws an Ocean Plane's waves in Modo's viewport as points, each where the sea puts it. It
// wants the same sea the renders get, but only its long waves (points a metre or more apart cannot show ripples), and
// at every frame of a scrub, so not written to disk at the full resolution. The tile's waves of fewer than preview / 2
// cycles across it are summed alone, at preview x preview points: each wave with the random numbers the full tile
// gives it (gaussianAt finds a cell's numbers without drawing those before), so the points stand where the full tile's
// long waves put them; the shorter waves are left out.

// The number splitmix gives at its k-th call (from 0) on a state begun at start: each call adds the same step, so the
// k-th is the step k + 1 times past the start, mixed.
static uint64_t splitmixAt(uint64_t start, uint64_t k) {
    uint64_t z = start + (k + 1) * 0x9E3779B97F4A7C15ull;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

// The pair gaussians(seed, count) gives cell at, worked out alone.
static Complex gaussianAt(uint64_t start, size_t at) {
    const uint64_t a = splitmixAt(start, 2 * uint64_t(at)), b = splitmixAt(start, 2 * uint64_t(at) + 1);
    const double u1 = double((a >> 11) + 1) / double(1ull << 53), u2 = double(b >> 11) / double(1ull << 53);
    const double r = std::sqrt(-2.0 * std::log(u1));
    return Complex(r * std::cos(2 * Pi * u2), r * std::sin(2 * Pi * u2));
}

// A preview's spectrum, which the time does not change: for each of its cells, h0 of its wave and of the wave opposite
// (the full tile's h0[k] and h0[-k]), and the heights' scale. Kept for the latest few settings, so that a scrub works
// out only the waves' movement.
struct PreviewSpectrum {
    std::vector<Complex> h, opposite;
    double scale = 0.0;
};
static std::mutex previewLock;
static std::vector<std::pair<std::string, std::shared_ptr<const PreviewSpectrum>>> previewKept;
static const size_t PreviewKeep = 32;

static std::shared_ptr<const PreviewSpectrum> previewSpectrum(const Settings& s, int m) {
    std::string key;
    auto add = [&](const void* data, size_t size) { key.append(static_cast<const char*>(data), size); };
    add(&s.n, sizeof s.n);
    add(&m, sizeof m);
    add(&s.seed, sizeof s.seed);
    for (double v : {s.size, s.windSpeed, s.windDirection, s.waveHeight, s.choppiness, s.smallWaves, s.windAlignment, s.againstWind,
                     s.depth, s.loop, s.foamThreshold, s.kLow, s.kHigh, s.fixedScale, s.turn})
        add(&v, sizeof v);
    {
        std::lock_guard<std::mutex> held(previewLock);
        for (const auto& kept : previewKept)
            if (kept.first == key) return kept.second;
    }
    const int n = s.n;
    const double cell = 2 * Pi / s.size;
    const uint64_t start = uint64_t(s.seed) * 0x2545F4914F6CDD1Dull + 1ull;
    // h0 of the wave a cells along x and b along z (each -n/2 to n/2 - 1), as tile() makes it.
    auto amplitudeAt = [&](int a, int b) {
        const size_t at = size_t(b + n / 2) * n + size_t(a + n / 2);
        const Complex g = gaussianAt(start, at);
        const double amplitude = cellAmplitude(s, cell * a, cell * b);
        return Complex(g.real() * amplitude, g.imag() * amplitude);
    };
    // The wave opposite: -a, but the full tile's -n/2 is its own (tile's (n - i) % n).
    auto opposite = [&](int a) { return a == -n / 2 ? a : -a; };
    auto made = std::make_shared<PreviewSpectrum>();
    made->h.assign(size_t(m) * m, Complex(0.0));
    made->opposite.assign(size_t(m) * m, Complex(0.0));
    for (int j = 0; j < m; ++j)
        for (int i = 0; i < m; ++i) {
            const int a = i - m / 2, b = j - m / 2;
            // A smaller grid's -m/2 has no opposite of its own in it (the full tile's +m/2): left out.
            if (m < n && (a == -m / 2 || b == -m / 2)) continue;
            const size_t at = size_t(j) * m + i;
            made->h[at] = amplitudeAt(a, b);
            made->opposite[at] = amplitudeAt(opposite(a), opposite(b));
        }
    made->scale = s.fixedScale;
    if (!(made->scale > 0)) {
        // A sea of one tile is scaled to its own heights, all its waves counted, as tile() scales it.
        double variance = 0.0;
        for (int b = -n / 2; b < n / 2; ++b)
            for (int a = -n / 2; a < n / 2; ++a) variance += 2.0 * std::norm(amplitudeAt(a, b));
        const double target = s.waveHeight * 0.21 * s.windSpeed * s.windSpeed / Gravity / 4.0;
        made->scale = variance > 0 ? target / std::sqrt(variance) : 0.0;
    }
    std::lock_guard<std::mutex> held(previewLock);
    previewKept.emplace_back(key, made);
    if (previewKept.size() > PreviewKeep) previewKept.erase(previewKept.begin());
    return made;
}

// The tile's long waves at preview x preview points across it (preview a power of two, at most the resolution): the
// displacement image's (dx, height, dz) at each, choppiness and turn as tile() writes them, rows by z, into out
// (preview x preview x 3 floats). The values as modo_ocean_tile's, the moment among them. 0; 2 for settings out of range.
extern "C" __declspec(dllexport) int modo_ocean_preview(int resolution, const double* values, int count, int preview, float* out) {
    Settings s;
    if (!settings(resolution, values, count, s) || !out) return 2;
    const int n = s.n, m = preview;
    if (n < 2 || (n & (n - 1)) || n > 4096 || !(s.size > 0) || !(s.windSpeed > 0) || m < 2 || (m & (m - 1)) || m > n) return 2;
    try {
        const std::shared_ptr<const PreviewSpectrum> spectrum = previewSpectrum(s, m);
        const double cell = 2 * Pi / s.size;
        const Complex I(0, 1);
        std::vector<Complex> pair1(size_t(m) * m), pair2(size_t(m) * m);
        for (int j = 0; j < m; ++j)
            for (int i = 0; i < m; ++i) {
                const double kx = cell * (i - m / 2), kz = cell * (j - m / 2), k = std::hypot(kx, kz);
                if (k < 1e-12) continue;
                const size_t at = size_t(j) * m + i;
                const double w = frequency(s, k) * s.seconds;
                const Complex e(std::cos(w), std::sin(w));
                const Complex h = spectrum->h[at] * e + std::conj(spectrum->opposite[at]) * std::conj(e);
                const Complex dx = -I * (kx / k) * h, dz = -I * (kz / k) * h;
                pair1[at] = h + I * dx;
                pair2[at] = dz;
            }
        ifft2(pair1, m);
        ifft2(pair2, m);
        const double scale = spectrum->scale, chop = s.choppiness;
        const double c = std::cos(s.turn * Pi / 180.0), sn = std::sin(s.turn * Pi / 180.0);
        for (int j = 0; j < m; ++j)
            for (int i = 0; i < m; ++i) {
                const size_t at = size_t(j) * m + i;
                const double sign = ((i + j) & 1) ? -1.0 : 1.0;
                const double h = pair1[at].real() * sign * scale, dx = pair1[at].imag() * sign * scale;
                const double dz = pair2[at].real() * sign * scale;
                out[3 * at] = float(chop * (c * dx - sn * dz));
                out[3 * at + 1] = float(h);
                out[3 * at + 2] = float(chop * (sn * dx + c * dz));
            }
    } catch (...) {
        return 1;
    }
    return 0;
}
