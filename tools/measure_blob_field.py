"""Measure what tools/probe_cl_blob_field.py rendered (Modo's) or the same experiments rendered by MoonRay: from each
picture's alpha, per experiment slot, the blob's radius as a disc of its area, the pair's neck (alpha summed down the
column at its middle) and length (along the row), and sprites' alpha along the row through their centre.

measure_blob_field.py <folder> [suffix] : reads <folder>/<experiment><suffix>.exr (suffix default '.Final Color Output.0001')
and prints JSON. 100 pixels a metre, origin at pixel (800, 400)."""
import json
import sys
from pathlib import Path

import OpenImageIO as oiio

SCALE = 100.0
CX, CY = 800, 400


def alpha(path):
    """The picture's alpha as rows of floats, top row first (written as a one-channel PFM by OpenImageIO and read back:
    the toolchain's Python has no numpy for get_pixels)."""
    import struct
    import tempfile
    from array import array
    buf = oiio.ImageBuf(str(path))
    one = oiio.ImageBufAlgo.channels(buf, ('A',))
    staged = Path(tempfile.gettempdir()) / 'measure_blob_field.pfm'
    if not one.write(str(staged)):
        raise OSError(one.geterror())
    data = staged.read_bytes()
    head = data.split(b'\n', 3)
    width, height = map(int, head[1].split())
    scale = float(head[2])
    values = array('f')
    values.frombytes(head[3][:4 * width * height])
    if scale > 0:
        values.byteswap()
    rows = [values[(height - 1 - y) * width:(height - y) * width].tolist() for y in range(height)]
    return rows, width, height


def region(a, x0, x1):
    """Sum of alpha between columns x0..x1 (metres)."""
    p0, p1 = int(CX + x0 * SCALE), int(CX + x1 * SCALE)
    return sum(sum(row[p0:p1]) for row in a)


def column(a, x):
    p = int(round(CX + x * SCALE))
    return sum(row[p] for row in a) / SCALE


def row_span(a, x0, x1):
    p0, p1 = int(CX + x0 * SCALE), int(CX + x1 * SCALE)
    return sum(a[CY][p0:p1]) / SCALE


def main():
    folder = Path(sys.argv[1])
    suffix = sys.argv[2] if len(sys.argv) > 2 else '.Final Color Output.0001'
    found = {}
    for name in ('levels', 'pairs-a', 'pairs-b', 'sizes', 'sprites', 'spritesb', 'sprites2', 'sprites3'):
        path = folder / (name + suffix + '.exr')
        if not path.is_file():
            continue
        a, w, h = alpha(path)
        if name == 'levels':
            found[name] = [round((region(a, x - 1.4, x + 1.4) / 3.14159265) ** .5 / SCALE, 4) for x in (-6, -3, 0, 3, 6)]
        elif name.startswith('pairs'):
            found[name] = [{'neck': round(column(a, x), 4), 'length': round(row_span(a, x - 2.4, x + 2.4), 4)} for x in (-5, 0, 5)]
        elif name == 'sizes':
            found[name] = [round(column(a, -7.0 + 1.4 * i), 4) for i in range(11)]
        else:
            found[name] = [[round(a[CY][int(CX + (x + d) * SCALE)], 4) for d in (0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5)] for x in (-6, -3, 0, 3, 6)]
    print(json.dumps(found, indent=1))


if __name__ == '__main__':
    main()
