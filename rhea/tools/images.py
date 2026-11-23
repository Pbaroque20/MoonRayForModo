"""Plain-Python image helpers for the engine's tests: raw float32 RGBA films, PNGs and error measures.

No numpy here: the pythoncore interpreter the harness uses has none. Films are XPU2's: float32 RGBA, pixel i = y * width
+ x with y counted from the bottom (MoonRay's rows); PNGs are written top row first."""
import math
import struct
import zlib
from array import array
from pathlib import Path


def read_rgba(path, width, height):
    a = array('f')
    a.frombytes(Path(path).read_bytes())
    if len(a) != width * height * 4:
        raise ValueError(f'{path}: {len(a)} floats, not {width}x{height}x4')
    return a


def write_rgba(path, rgba):
    Path(path).write_bytes(array('f', rgba).tobytes())


def srgb(v):
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _png(path, width, height, rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw.extend(row)
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
                           chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def write_png(path, rgba, width, height, scale=1.0, linear=False, flip=True):
    """rgba: a film (bottom row first when flip); shown with the sRGB curve unless linear, times scale."""
    rows = []
    for y in range(height):
        sy = height - 1 - y if flip else y
        row = bytearray()
        for x in range(width):
            i = (sy * width + x) * 4
            for c in range(3):
                v = rgba[i + c] * scale
                v = min(max(v, 0.0), 1.0) if linear else srgb(v)
                row.append(int(round(v * 255)))
        rows.append(row)
    _png(path, width, height, rows)


def write_png_rgb(path, rgb, width, height, flip=True):
    """rgb: display values in [0, 1], three a pixel, bottom row first when flip."""
    rows = []
    for y in range(height):
        sy = height - 1 - y if flip else y
        row = bytearray()
        for x in range(width):
            i = (sy * width + x) * 3
            for c in range(3):
                row.append(int(round(min(max(rgb[i + c], 0.0), 1.0) * 255)))
        rows.append(row)
    _png(path, width, height, rows)


def luma(rgba, i):
    return 0.2126 * rgba[i * 4] + 0.7152 * rgba[i * 4 + 1] + 0.0722 * rgba[i * 4 + 2]


def errors(test, ref, width, height, block=8):
    """Mean absolute error, relative MSE (MoonRay's: (t - r)^2 / (r^2 + 0.01), averaged over channels), mean ratio of
    the RGB sums, and the mean of 8x8 block means' absolute differences."""
    n = width * height
    mae = rmse = 0.0
    st = sr = 0.0
    for i in range(n):
        for c in range(3):
            t, r = test[i * 4 + c], ref[i * 4 + c]
            mae += abs(t - r)
            rmse += (t - r) ** 2 / (r * r + 0.01)
            st += t
            sr += r
    bx, by = width // block, height // block
    berr = 0.0
    for j in range(by):
        for k in range(bx):
            dt = dr = 0.0
            for y in range(j * block, (j + 1) * block):
                for x in range(k * block, (k + 1) * block):
                    i = (y * width + x) * 4
                    dt += test[i] + test[i + 1] + test[i + 2]
                    dr += ref[i] + ref[i + 1] + ref[i + 2]
            berr += abs(dt - dr) / (3 * block * block)
    return {'mean_abs': mae / (3 * n), 'relative_mse': rmse / (3 * n), 'mean_ratio': st / sr if sr else math.nan,
            'block_error': berr / max(1, bx * by)}
