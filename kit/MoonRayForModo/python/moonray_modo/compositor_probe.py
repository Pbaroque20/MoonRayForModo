"""The compositor's probe: the linear values of a render's buffers at one pixel, for the editor to work out what each
node makes there (compositor.sample).

A buffer the preview holds in memory is read from there; any other is read from its file once, as the compositor reads
it (with not-a-number values made black and its kind's channels picked), into a picture kept for later probes until the
file changes."""
import array
import subprocess
import sys
import tempfile
from pathlib import Path

from . import compositor, native, outputs

_pictures = {}


def _read_pfm(path):
    """A PFM file as (width, height, floats), rows from the bottom up, three floats a pixel."""
    data = Path(path).read_bytes()
    lines, at = [], 0
    while len(lines) < 3:
        end = data.index(b'\n', at)
        lines.append(data[at:end].strip())
        at = end + 1
    if lines[0] != b'PF':
        raise ValueError('not a colour PFM')
    width, height = (int(v) for v in lines[1].split())
    scale = float(lines[2])
    values = array.array('f')
    values.frombytes(data[at:at + width * height * 12])
    # A negative scale says the floats are little-endian.
    if (scale > 0) != (sys.byteorder == 'big'):
        values.byteswap()
    return width, height, values


def _picture(frame, key):
    """A buffer's picture read from its file, (width, height, floats bottom row first), or None."""
    path = frame.get('files', {}).get(key)
    if not path or not Path(path).is_file():
        return None
    stamp = (str(path), Path(path).stat().st_mtime_ns, key)
    if stamp in _pictures:
        return _pictures[stamp]
    runtime = Path(frame['runtime'])
    kind = outputs.display_kind(frame.get('snapshot', {}), key)
    with tempfile.TemporaryDirectory(prefix='MoonRayProbe-') as folder:
        target = Path(folder) / 'probe.pfm'
        done = subprocess.run([str(runtime / 'oiiotool.exe'), '--no-autopremult', str(path), '--fixnan', 'black'] + compositor._channels(kind)
                              + ['-d', 'float', '-o', str(target)], env=native.environment(runtime), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        picture = _read_pfm(target) if done.returncode == 0 and target.is_file() else None
    # Only the newest picture of each buffer is kept.
    for held in [held for held in _pictures if held[0] == stamp[0] and held[2] == key]:
        del _pictures[held]
    _pictures[stamp] = picture
    return picture


def value(frame, key, x, y):
    """A buffer's linear value at a pixel (x across, y down from the top), as (r, g, b), or None."""
    held = (frame.get('linear') or {}).get(key)
    if held:
        width, height, pixels = held
        if 0 <= x < width and 0 <= y < height:
            values = array.array('f')
            values.frombytes(bytes(pixels[((height - 1 - y) * width + x) * 12:((height - 1 - y) * width + x) * 12 + 12]))
            return tuple(values)
    picture = _picture(frame, key)
    if picture is None:
        return None
    width, height, values = picture
    if not (0 <= x < width and 0 <= y < height):
        return None
    at = ((height - 1 - y) * width + x) * 3
    return tuple(values[at:at + 3])


def size(frame):
    """The render's width and height, from a buffer in memory or the beauty's picture; None where there is none."""
    for key, held in (frame.get('linear') or {}).items():
        return held[0], held[1]
    picture = _picture(frame, 'beauty')
    return (picture[0], picture[1]) if picture else None
