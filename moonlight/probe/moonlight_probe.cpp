// Standalone MoonLight check: renders a built-in scene, times samples and edits, writes images.
// Usage: moonlight_probe <kernel.ptx> <output-directory> [samples] [width] [height]
#include "moonlight/moonlight.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

const float PI = 3.14159265358979323846f;

double milliseconds(std::chrono::steady_clock::time_point since) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - since).count();
}

void sphere(int segments, int rings, std::vector<float>& positions, std::vector<float>& normals, std::vector<uint32_t>& indices) {
    for (int r = 0; r <= rings; ++r) {
        const float theta = PI * r / rings;
        for (int s = 0; s <= segments; ++s) {
            const float phi = 2.0f * PI * s / segments;
            const float n[3] = {std::sin(theta) * std::cos(phi), std::cos(theta), std::sin(theta) * std::sin(phi)};
            positions.insert(positions.end(), n, n + 3);
            normals.insert(normals.end(), n, n + 3);
        }
    }
    for (int r = 0; r < rings; ++r)
        for (int s = 0; s < segments; ++s) {
            const uint32_t a = r * (segments + 1) + s, b = a + segments + 1;
            indices.insert(indices.end(), {a, a + 1, b, a + 1, b + 1, b});
        }
}

// Horizon-to-zenith gradient with a small, very bright sun to exercise importance sampling.
std::vector<float> sky(uint32_t width, uint32_t height) {
    std::vector<float> pixels(size_t(width) * height * 3);
    const float sunTheta = 0.30f * PI, sunPhi = 0.25f * PI;
    const float sun[3] = {std::sin(sunTheta) * std::sin(sunPhi), std::cos(sunTheta), -std::sin(sunTheta) * std::cos(sunPhi)};
    for (uint32_t y = 0; y < height; ++y)
        for (uint32_t x = 0; x < width; ++x) {
            const float theta = (y + 0.5f) / height * PI, phi = ((x + 0.5f) / width - 0.5f) * 2.0f * PI;
            const float d[3] = {std::sin(theta) * std::sin(phi), std::cos(theta), -std::sin(theta) * std::cos(phi)};
            const float up = std::max(d[1], 0.0f), below = d[1] < 0.0f ? 1.0f : 0.0f;
            float* out = &pixels[(size_t(y) * width + x) * 3];
            out[0] = below ? 0.20f : 0.55f - 0.35f * up;
            out[1] = below ? 0.18f : 0.70f - 0.30f * up;
            out[2] = below ? 0.16f : 0.90f - 0.10f * up;
            if (d[0] * sun[0] + d[1] * sun[1] + d[2] * sun[2] > std::cos(0.03f))
                for (int c = 0; c < 3; ++c) out[c] = c == 2 ? 1500.0f : 2000.0f;
        }
    return pixels;
}

moonlight::Instance placed(uint32_t mesh, uint32_t material, float x, float y, float z, float scale) {
    moonlight::Instance instance;
    instance.mesh = mesh;
    instance.material = material;
    const float transform[12] = {scale, 0, 0, x, 0, scale, 0, y, 0, 0, scale, z};
    std::copy(transform, transform + 12, instance.transform);
    return instance;
}

// Images arrive bottom row first, which is also the PFM convention.
void writePfm(const std::string& path, const std::vector<float>& rgb, uint32_t width, uint32_t height) {
    std::ofstream file(path, std::ios::binary);
    file << "PF\n" << width << " " << height << "\n-1.0\n";
    file.write(reinterpret_cast<const char*>(rgb.data()), rgb.size() * sizeof(float));
}

void writePpm(const std::string& path, const std::vector<float>& rgb, uint32_t width, uint32_t height) {
    std::ofstream file(path, std::ios::binary);
    file << "P6\n" << width << " " << height << "\n255\n";
    for (uint32_t y = height; y-- > 0;)
        for (uint32_t x = 0; x < width * 3; ++x) {
            const float linear = std::min(std::max(rgb[size_t(y) * width * 3 + x], 0.0f), 1.0f);
            const float encoded = linear <= 0.0031308f ? 12.92f * linear : 1.055f * std::pow(linear, 1.0f / 2.4f) - 0.055f;
            file.put(char(std::lround(encoded * 255.0f)));
        }
}

// Returns the mean luminance, or a negative value if any pixel is not finite.
double meanLuminance(const std::vector<float>& rgb) {
    double sum = 0.0;
    for (size_t i = 0; i < rgb.size(); i += 3) {
        if (!std::isfinite(rgb[i]) || !std::isfinite(rgb[i + 1]) || !std::isfinite(rgb[i + 2])) return -1.0;
        sum += 0.2126 * rgb[i] + 0.7152 * rgb[i + 1] + 0.0722 * rgb[i + 2];
    }
    return sum / double(rgb.size() / 3);
}

}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "Usage: moonlight_probe <kernel.ptx> <output-directory> [samples] [width] [height]" << std::endl;
        return 2;
    }
    const std::string output = argv[2];
    const int samples = argc > 3 ? std::atoi(argv[3]) : 64;
    const uint32_t width = argc > 4 ? std::atoi(argv[4]) : 960, height = argc > 5 ? std::atoi(argv[5]) : 540;
    try {
        auto start = std::chrono::steady_clock::now();
        moonlight::Renderer renderer(argv[1]);
        std::cout << "Device: " << renderer.deviceName() << "\nPipeline ready: " << milliseconds(start) << " ms" << std::endl;

        start = std::chrono::steady_clock::now();
        std::vector<float> positions, normals;
        std::vector<uint32_t> indices;
        sphere(256, 128, positions, normals, indices);
        moonlight::MeshDesc ball;
        ball.positions = positions.data();
        ball.normals = normals.data();
        ball.vertexCount = positions.size() / 3;
        ball.indices = indices.data();
        ball.triangleCount = indices.size() / 3;
        const uint32_t ballMesh = renderer.addMesh(ball);

        const float groundPositions[12] = {-20, 0, -20, 20, 0, -20, 20, 0, 20, -20, 0, 20};
        const uint32_t groundIndices[6] = {0, 2, 1, 0, 3, 2};
        moonlight::MeshDesc ground;
        ground.positions = groundPositions;
        ground.vertexCount = 4;
        ground.indices = groundIndices;
        ground.triangleCount = 2;
        const uint32_t groundMesh = renderer.addMesh(ground);

        std::vector<moonlight::Material> materials(4);
        materials[0].baseColor[0] = materials[0].baseColor[1] = materials[0].baseColor[2] = 0.5f;
        materials[0].roughness = 0.6f;
        materials[1] = {{0.8f, 0.1f, 0.08f}, 0.0f, 0.8f, 1.5f, {0, 0, 0}};      // matte red
        materials[2] = {{1.0f, 0.77f, 0.34f}, 1.0f, 0.2f, 1.5f, {0, 0, 0}};     // gold
        materials[3] = {{0.05f, 0.2f, 0.7f}, 0.0f, 0.1f, 1.5f, {0, 0, 0}};      // glossy blue
        renderer.setMaterials(materials.data(), materials.size());

        std::vector<moonlight::Instance> instances = {
            placed(groundMesh, 0, 0, 0, 0, 1), placed(ballMesh, 1, -2.3f, 1, 0, 1),
            placed(ballMesh, 2, 0, 1, 0, 1), placed(ballMesh, 3, 2.3f, 1, 0, 1)};
        renderer.setInstances(instances.data(), instances.size());

        const std::vector<float> skyPixels = sky(1024, 512);
        moonlight::Environment environment;
        environment.pixels = skyPixels.data();
        environment.width = 1024;
        environment.height = 512;
        renderer.setEnvironment(environment);

        moonlight::Camera camera;
        const float eye[3] = {0, 2.2f, 8.5f}, target[3] = {0, 0.9f, 0};
        std::copy(eye, eye + 3, camera.eye);
        std::copy(target, target + 3, camera.target);
        renderer.resize(width, height);
        renderer.setCamera(camera);
        renderer.synchronize();
        std::cout << "Scene upload (" << ball.triangleCount * 3 + 2 << " instanced triangles): " << milliseconds(start) << " ms" << std::endl;

        // The first launch includes one-time driver work, so time it apart from the steady state.
        start = std::chrono::steady_clock::now();
        renderer.render();
        renderer.synchronize();
        std::cout << "First sample: " << milliseconds(start) << " ms" << std::endl;
        start = std::chrono::steady_clock::now();
        for (int i = 1; i < samples; ++i) renderer.render();
        renderer.synchronize();
        if (samples > 1)
            std::cout << "Steady state: " << milliseconds(start) / (samples - 1) << " ms per sample at " << width << "x" << height << std::endl;

        std::vector<float> beauty(size_t(width) * height * 3), denoised(beauty.size());
        renderer.readBeauty(beauty.data());
        start = std::chrono::steady_clock::now();
        renderer.readDenoised(denoised.data());
        std::cout << "First denoise and readback: " << milliseconds(start) << " ms" << std::endl;
        start = std::chrono::steady_clock::now();
        renderer.readDenoised(denoised.data());
        std::cout << "Denoise and readback: " << milliseconds(start) << " ms" << std::endl;
        writePfm(output + "/moonlight_beauty.pfm", beauty, width, height);
        writePpm(output + "/moonlight_beauty.ppm", beauty, width, height);
        writePpm(output + "/moonlight_denoised.ppm", denoised, width, height);

        // Edit paths: each restarts accumulation and is timed to its first new sample.
        std::vector<float> edited(beauty.size());
        start = std::chrono::steady_clock::now();
        materials[2].roughness = 0.6f;
        renderer.setMaterial(2, materials[2]);
        renderer.render();
        renderer.synchronize();
        std::cout << "Material edit to next sample: " << milliseconds(start) << " ms" << std::endl;

        start = std::chrono::steady_clock::now();
        instances[2] = placed(ballMesh, 2, 0, 1.6f, 0, 1);
        renderer.setInstances(instances.data(), instances.size());
        renderer.render();
        renderer.synchronize();
        std::cout << "Transform edit to next sample: " << milliseconds(start) << " ms" << std::endl;

        start = std::chrono::steady_clock::now();
        camera.eye[0] = 3.0f;
        renderer.setCamera(camera);
        renderer.render();
        renderer.synchronize();
        std::cout << "Camera edit to next sample: " << milliseconds(start) << " ms" << std::endl;
        if (renderer.sampleCount() != 1) throw std::runtime_error("An edit did not restart accumulation");
        for (int i = 1; i < 16; ++i) renderer.render();
        renderer.readDenoised(edited.data());
        writePpm(output + "/moonlight_edited_denoised.ppm", edited, width, height);

        const double beautyMean = meanLuminance(beauty), denoisedMean = meanLuminance(denoised), editedMean = meanLuminance(edited);
        std::cout << "Mean luminance: beauty " << beautyMean << ", denoised " << denoisedMean << ", edited " << editedMean << std::endl;
        if (beautyMean <= 0.0 || denoisedMean <= 0.0 || editedMean <= 0.0)
            throw std::runtime_error("An image is black or contains non-finite pixels");
        std::cout << "MoonLight probe passed" << std::endl;
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "MoonLight probe failed: " << error.what() << std::endl;
        return 1;
    }
}
