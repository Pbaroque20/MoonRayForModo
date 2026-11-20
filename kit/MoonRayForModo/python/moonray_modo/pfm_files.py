"""Float PFM files made from what oiiotool writes, for the readers that take PFM (MoonLightIPR's session, the
compositor program, Cryptomatte picking, the compositor's probe).

oiiotool's own PFM writer (OpenImageIO 3.1.17, the runtime's) turns over each block of rows it writes by itself, not the
picture as a whole: a picture larger than one block came out with its bands out of order. A 2048 x 1024 picture was
written whole and right; a 3840 x 2160 one with its halves swapped; a tester's 8K garage HDRI in six bands, its ceiling
lights put below the floor, and a MoonLightIPR Render of a car (which takes its environment at full size) came out at
less than half of realtime's brightness (realtime's environment is made smaller, so written whole). oiiotool writes the
picture as an uncompressed float TIFF instead, top row first in strips, and it is turned into a PFM here."""
import array
import struct
import sys
import uuid
from pathlib import Path

PFM_CHANNELS = {1: b'Pf', 3: b'PF'}


def _tags(data):
    """The first image directory of a classic TIFF: (byte order, {tag: [values]})."""
    order = data[:2]
    if order not in (b'II', b'MM'):
        raise ValueError('not a TIFF')
    e = '<' if order == b'II' else '>'
    magic, offset = struct.unpack(e + 'HI', data[2:8])
    if magic != 42:
        raise ValueError('not a classic TIFF')
    count = struct.unpack(e + 'H', data[offset:offset + 2])[0]
    sizes = {1: ('B', 1), 2: ('B', 1), 3: ('H', 2), 4: ('I', 4), 16: ('Q', 8)}
    tags = {}
    for index in range(count):
        entry = offset + 2 + 12 * index
        tag, kind, number = struct.unpack(e + 'HHI', data[entry:entry + 8])
        if kind not in sizes:
            continue
        code, size = sizes[kind]
        where = entry + 8 if number * size <= 4 else struct.unpack(e + 'I', data[entry + 8:entry + 12])[0]
        tags[tag] = list(struct.unpack(e + code * number, data[where:where + number * size]))
    return e, tags


def tiff_to_pfm(tiff, pfm):
    """An uncompressed float TIFF of one or three channels (as oiiotool writes it) written as a PFM, bottom row first."""
    data = Path(tiff).read_bytes()
    e, tags = _tags(data)
    width, height = tags[256][0], tags[257][0]
    channels = tags.get(277, [1])[0]
    if channels not in PFM_CHANNELS:
        raise ValueError('a PFM holds one or three channels, not %d' % channels)
    if tags.get(259, [1])[0] != 1 or tags.get(284, [1])[0] != 1 or tags.get(274, [1])[0] != 1:
        raise ValueError('the TIFF is compressed, planar or turned')
    if set(tags.get(258, [32])) != {32} or set(tags.get(339, [3])) != {3}:
        raise ValueError('the TIFF does not hold 32-bit floats')
    row = width * channels * 4
    strips = b''.join(data[start:start + length] for start, length in zip(tags[273], tags[279]))
    if len(strips) < row * height:
        raise ValueError('the TIFF holds %d bytes of a %d x %d picture' % (len(strips), width, height))
    if (e == '<') != (sys.byteorder == 'little'):
        held = array.array('f')
        held.frombytes(strips[:row * height])
        held.byteswap()
        strips = held.tobytes()
    view = memoryview(strips)
    scale = b'-1.0' if sys.byteorder == 'little' else b'1.0'
    with open(pfm, 'wb') as out:
        out.write(PFM_CHANNELS[channels] + b'\n%d %d\n' % (width, height) + scale + b'\n')
        for y in range(height - 1, -1, -1):
            out.write(view[y * row:(y + 1) * row])


def steps(args, target):
    """Image-tool steps that make target, a PFM, with its rows in order, for runners that take a list of
    (arguments, the file made): oiiotool writing an uncompressed float TIFF beside it, then (['@pfm', that TIFF],
    target), which the runner does with run_step. args are the image tool's, ending with '-o', target."""
    target = Path(target)
    if len(args) < 2 or args[-2] != '-o' or Path(args[-1]) != target:
        raise ValueError('the image tool steps do not end in writing %s' % target.name)
    tiff = target.with_suffix('.tif')
    return [(list(args[:-2]) + ['--compression', 'none', '-o', str(tiff)], tiff), (['@pfm', str(tiff)], target)]


def run_step(args, target):
    """An ['@pfm', TIFF] step (steps): the TIFF turned into target, and let go."""
    tiff = Path(args[1])
    try:
        tiff_to_pfm(tiff, target)
    finally:
        try:
            tiff.unlink()
        except OSError:
            pass


def through_tiff(write, target):
    """A PFM at target from write(path), which has oiiotool write the picture to path as an uncompressed float TIFF
    (its arguments end with '-d', 'float', '--compression', 'none', '-o', path)."""
    target = Path(target)
    tiff = target.with_name(target.stem + '-' + uuid.uuid4().hex + '.tif')
    try:
        write(tiff)
        tiff_to_pfm(tiff, target)
    finally:
        try:
            tiff.unlink()
        except OSError:
            pass
