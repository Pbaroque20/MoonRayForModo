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

// The tile for these settings, written as the two PFM images: 0; 2 for settings out of range; 1 where the images
// cannot be written.
static int tile(const Settings& s, const char* displacementPath, const char* foamPath) {
    const int n = s.n;
    if (n < 2 || (n & (n - 1)) || n > 4096 || !(s.size > 0) || !(s.windSpeed > 0)) return 2;
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

    std::vector<Complex> pair1(size_t(n) * n), pair2(size_t(n) * n), pair3(size_t(n) * n);
    const Complex I(0, 1);
    for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i) {
            const double kx = ks[i], kz = ks[j], k = std::hypot(kx, kz);
            if (k < 1e-12) continue;
            const double w = frequency(s, k) * s.seconds;
            const Complex e(std::cos(w), std::sin(w));
            const Complex h = h0[size_t(j) * n + i] * e + std::conj(h0[size_t((n - j) % n) * n + (n - i) % n]) * std::conj(e);
            const Complex dx = -I * (kx / k) * h, dz = -I * (kz / k) * h;
            const size_t at = size_t(j) * n + i;
            pair1[at] = h + I * dx;
            pair2[at] = dz + I * ((kx * kx / k) * h);
            pair3[at] = (kz * kz / k) * h + I * ((kx * kz / k) * h);
        }
    ifft2(pair1, n);
    ifft2(pair2, n);
    ifft2(pair3, n);
    std::vector<float> displacement(size_t(n) * n * 3), foam(size_t(n) * n);
    const double chop = s.choppiness, threshold = s.foamThreshold;
    for (int j = 0; j < n; ++j)
        for (int i = 0; i < n; ++i) {
            const size_t at = size_t(j) * n + i;
            const double sign = ((i + j) & 1) ? -1.0 : 1.0;
            const double h = pair1[at].real() * sign * scale, dx = pair1[at].imag() * sign * scale;
            const double dz = pair2[at].real() * sign * scale, jxx = pair2[at].imag() * sign * scale;
            const double jzz = pair3[at].real() * sign * scale, jxz = pair3[at].imag() * sign * scale;
            displacement[3 * at] = float(chop * dx);
            displacement[3 * at + 1] = float(h);
            displacement[3 * at + 2] = float(chop * dz);
            const double jacobian = (1 + chop * jxx) * (1 + chop * jzz) - (chop * jxz) * (chop * jxz);
            foam[at] = threshold > 0 ? float(std::fmin(1.0, std::fmax(0.0, (threshold - jacobian) / threshold))) : 0.0f;
        }
    if (!writePfm(displacementPath, n, displacement, 3) || !writePfm(foamPath, n, foam, 1)) return 1;
    return 0;
}

// What the kit calls (moonray_modo/ocean.py, by ctypes): the resolution, then values in ocean.py's arguments() order
// (size, wind speed, wind direction, wave height, choppiness, small waves, wind alignment, against wind, depth, seed,
// loop, foam threshold, seconds), and the two images' paths. The same returns as tile().
extern "C" __declspec(dllexport) int modo_ocean_tile(int resolution, const double* values, int count, const char* displacementPath,
                                                     const char* foamPath) {
    if (!values || count != 13 || !displacementPath || !foamPath) return 2;
    Settings s;
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
    return tile(s, displacementPath, foamPath);
}
