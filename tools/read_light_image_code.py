"""Read a render of tools/probe_cl_light_images.py's scenes as image coordinates: for each pixel lit enough, u = R / (4 B)
and v = G / (4 B) (the uv-code image's blue is a constant 0.25), with the floor point the pixel sees (the camera 8
units above, a 5.76 unit square). Prints a grid of samples and fits u and v as linear functions of the floor's x and z.

read_light_image_code.py <runtime> <picture.exr> [step]"""
import struct
import subprocess
import sys
from pathlib import Path


def pixels(runtime, source):
    target = Path(str(source) + '.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    target.unlink()
    return width, height, values


def code(runtime, source):
    """{(x, z): (u, v, brightness)} for lit pixels; rows of the PFM run bottom up."""
    width, height, values = pixels(runtime, source)
    found = {}
    peak = max(values[2::3]) or 1.0
    for row in range(height):
        for column in range(width):
            r, g, b = values[(row * width + column) * 3:(row * width + column) * 3 + 3]
            if b < peak * .05:
                continue
            x = ((column + .5) / width - .5) * 5.76
            # The picture's top is -z; PFM row 0 is the bottom of the picture (+z).
            z = (.5 - (row + .5) / height) * 5.76
            found[(x, z)] = (r / (4 * b), g / (4 * b), b * 4)
    return found


def solve(samples, index):
    rows = [(x, z, 1.0, held[index]) for (x, z), held in samples.items()]
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    atb = [sum(r[i] * r[3] for r in rows) for i in range(3)]
    # Gaussian elimination.
    m = [ata[i] + [atb[i]] for i in range(3)]
    for i in range(3):
        p = max(range(i, 3), key=lambda k: abs(m[k][i]))
        m[i], m[p] = m[p], m[i]
        for k in range(3):
            if k != i and m[i][i]:
                f = m[k][i] / m[i][i]
                m[k] = [a - f * b for a, b in zip(m[k], m[i])]
    coefficients = [m[i][3] / m[i][i] if m[i][i] else 0.0 for i in range(3)]
    residual = max(abs(x * coefficients[0] + z * coefficients[1] + coefficients[2] - v) for x, z, _, v in rows) if rows else 0.0
    return coefficients, residual


if __name__ == '__main__':
    runtime, source = Path(sys.argv[1]), Path(sys.argv[2])
    step = float(sys.argv[3]) if len(sys.argv) > 3 else .5
    samples = code(runtime, source)
    print('%d lit pixels' % len(samples))
    for name, index in (('u', 0), ('v', 1)):
        coefficients, residual = solve(samples, index)
        print('%s = %.4f x + %.4f z + %.4f  (largest miss %.4f)' % (name, coefficients[0], coefficients[1], coefficients[2], residual))
    grid = {}
    for (x, z), held in samples.items():
        key = (round(x / step) * step, round(z / step) * step)
        grid.setdefault(key, []).append(held)
    for key in sorted(grid, key=lambda k: (k[1], k[0])):
        held = grid[key]
        print('x %5.2f z %5.2f: u %.3f v %.3f bright %.4f' % (key[0], key[1], *(sum(h[i] for h in held) / len(held) for i in range(3))))
