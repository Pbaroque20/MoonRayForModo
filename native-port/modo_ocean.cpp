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
#include <string>
#include <vector>

using Complex = std::complex<double>;
static const double Pi = 3.14159265358979323846, Gravity = 9.81;

struct Settings {
    int n;
    double size, windSpeed, windDirection, waveHeight, choppiness, smallWaves, windAlignment, againstWind, depth;
    long long seed;
    double loop, foamThreshold, seconds;
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
            out.displacement[3 * at] = float(chop * dx);
            out.displacement[3 * at + 1] = float(h);
            out.displacement[3 * at + 2] = float(chop * dz);
            const double jacobian = (1 + chop * jxx) * (1 + chop * jzz) - (chop * jxz) * (chop * jxz);
            const float f = threshold > 0 ? float(std::fmin(1.0, std::fmax(0.0, (threshold - jacobian) / threshold))) : 0.0f;
            out.foam[3 * at] = out.foam[3 * at + 1] = out.foam[3 * at + 2] = f;
            if (wantSlope) {
                const double hx = pair4[at].real() * sign * scale, hz = pair4[at].imag() * sign * scale;
                const double a = 1 + chop * jxx, b = 1 + chop * jzz, e = chop * jxz;
                const double held = std::fmax(jacobian, 0.05);
                out.slope[3 * at] = float((b * hx - e * hz) / held * s.size);
                out.slope[3 * at + 1] = float((a * hz - e * hx) / held * s.size);
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
            const double amplitude = std::sqrt(phillips(s, ks[i], ks[j]) / 2.0);
            const size_t at = size_t(j) * n + i;
            h0[at] = Complex(noise[2 * at] * amplitude, noise[2 * at + 1] * amplitude);
        }
    double variance = 0.0;
    for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i)
            variance += std::norm(h0[size_t(j) * n + i]) + std::norm(h0[size_t((n - j) % n) * n + (n - i) % n]);
    const double target = s.waveHeight * 0.21 * s.windSpeed * s.windSpeed / Gravity / 4.0;
    const double scale = variance > 0 ? target / std::sqrt(variance) : 0.0;

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
    if (!values || count != 13) return false;
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
    return true;
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
