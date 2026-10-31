"""MoonLightIPR's subdivision: texture coordinates go where the surface goes. An unevenly spaced grid whose coordinates
are its own x and y must have them still after subdividing, at every corner: carried linearly across each face they were
not, and a texture stretched. A seam down the middle (two pieces of the map, the second moved over) must stay a seam.

check_subdivide_uvs.py"""
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
TEST = r"""
#include "subdivide.h"
#include <cmath>
#include <cstdio>
using namespace moonlightipr;
int main() {
    const float xs[5] = {0.0f, 0.1f, 0.5f, 0.6f, 1.5f}, ys[4] = {0.0f, 0.7f, 0.8f, 2.0f};
    for (int seam = 0; seam < 2; ++seam) {
        Cage cage;
        for (float y : ys) for (float x : xs) { cage.positions.push_back(x); cage.positions.push_back(y); cage.positions.push_back(0.0f); }
        std::vector<float> uv;
        for (int j = 0; j < 3; ++j) for (int i = 0; i < 4; ++i) {
            const int v[4] = {j * 5 + i, j * 5 + i + 1, (j + 1) * 5 + i + 1, (j + 1) * 5 + i};
            cage.faceSizes.push_back(4);
            for (int k : v) {
                cage.corners.push_back(uint32_t(k));
                uv.push_back(cage.positions[k * 3] + (seam && i >= 2 ? 10.0f : 0.0f));
                uv.push_back(cage.positions[k * 3 + 1]);
            }
        }
        cage.uvSets.push_back(uv);
        Triangles fine = subdivide(cage, 3);
        double worst = 0, across = 0;
        const size_t corners = fine.indices.size();
        for (size_t c = 0; c < corners; ++c) {
            const float* p = &fine.positions[size_t(fine.indices[c]) * 3];
            const float* t = &fine.uvSets[0][c * 2];
            const double u = (seam && t[0] > 5.0f) ? t[0] - 10.0f : t[0];
            worst = std::fmax(worst, std::fmax(std::fabs(u - p[0]), std::fabs(t[1] - p[1])));
            if (seam && t[0] > 5.0f) across = std::fmax(across, 1.0);
        }
        std::printf("%s: worst %.6f over %zu corners%s\n", seam ? "seam" : "whole", worst, corners, seam && across > 0 ? ", second piece kept" : "");
        if (worst > (seam ? 0.1 : 1e-4) || (seam && across == 0)) return 1;
    }
    return 0;
}
"""


def main():
    compiler = root / 'toolchain/msys64/ucrt64/bin/g++.exe'
    session = root / 'moonlightipr/session'
    with tempfile.TemporaryDirectory() as folder:
        source = pathlib.Path(folder) / 'check.cpp'
        source.write_text(TEST, encoding='utf-8')
        exe = pathlib.Path(folder) / 'check.exe'
        import os
        env = dict(os.environ, PATH=str(compiler.parent) + os.pathsep + os.environ.get('PATH', ''))
        subprocess.run([str(compiler), '-std=c++17', '-O1', '-static', '-I' + str(session), str(source), str(session / 'subdivide.cpp'), '-o', str(exe)], check=True, env=env)
        raise SystemExit(subprocess.run([str(exe)], env=env).returncode)


if __name__ == '__main__':
    main()
