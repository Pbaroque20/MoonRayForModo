"""Modo's fur grown by the runtime's own program, into files MoonRay reads for itself.

fur.py grows fur a fibre at a time in Python and hands MoonRay every point of it as text, which is why it stops at
sixty thousand fibres and makes them wider to cover the surface. The runtime's modo_fur_grow takes the same steps in
the same order, with Python's own random numbers, many times faster, and writes the fibres to a file of plain numbers
that the runtime's ModoFurGeometry reads: no fibre passes through Python or through the scene's text, so as many are
grown as Modo would grow, each as wide as the Fur material says. Where the program is not to be had, or fails, grow()
returns None and the fur is grown in Python as before.
"""
import hashlib
import os
import struct
import subprocess
import tempfile
from array import array
from itertools import chain
from pathlib import Path

PROGRAM = 'modo_fur_grow.exe'
# The Fur material's numbers in the order the program takes them.
NUMBERS = ('dist', 'length', 'width', 'widthAbs', 'taper', 'flex', 'growthJitter', 'sclJitter', 'nrmJitter', 'density', 'rootBend', 'curls',
           'curlRadius', 'clumps', 'clumpSize', 'kinkAmp', 'kinkAmpTip', 'kinkScl', 'kinkOff', 'frizAmp', 'frizAmpTip', 'strays', 'straysAmp')
MAPS = ('density', 'length', 'clump', 'curl', 'bend')
# Fur files are kept by what they were grown from, here, and the oldest cleared out past this many.
KEPT = 24


def program(runtime=None):
    """Where the program is, or None."""
    try:
        from . import native
        found = Path(runtime) if runtime else Path(native.default_runtime())
    except Exception:
        return None
    path = found / PROGRAM
    return path if path.is_file() else None


def reads(runtime=None):
    """Whether this runtime's MoonRay can read a fur file (its ModoFurGeometry)."""
    try:
        from . import native
        found = Path(runtime) if runtime else Path(native.default_runtime())
        return (found / 'ModoFurGeometry.dll').is_file() or (found / 'ModoFurGeometry.so').is_file()
    except Exception:
        return False


def folder():
    path = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo/Fur'
    path.mkdir(parents=True, exist_ok=True)
    return path


def request(triangles, held, maps, groups, most=0):
    """What the program is asked: the triangles with the group each one's fibres go in, the Fur material's settings
    (fur.settings) and the weight maps there are."""
    from . import fur
    held = dict(fur.CHANNELS, **held)
    parts = [b'MFG1', struct.pack('<2q4i', int(held['seed']), int(most), int(held['maxSegment']), 1 if held['widthMode'] == 'absolute' else 0,
                                  1 if held['bendDirection'] == 'up' else 0, 0 if held['curlMode'] == 'curls' else 1),
             struct.pack('<%dd' % len(NUMBERS), *[float(held[name]) for name in NUMBERS]),
             struct.pack('<i', len(triangles)),
             array('d', chain.from_iterable(chain.from_iterable(triangles))).tobytes(),
             array('i', [int(group) for group in groups]).tobytes(),
             struct.pack('<5i', *[1 if (maps or {}).get(name) else 0 for name in MAPS])]
    for name in MAPS:
        if (maps or {}).get(name):
            parts.append(array('d', chain.from_iterable(maps[name])).tobytes())
    return b''.join(parts)


def grow(triangles, held, maps, groups, most=0, runtime=None):
    """Grow the fur into files. Returns {'wanted', 'grown', 'root', 'tip', 'files': {group: (path, fibres, points)}},
    or None where the program cannot be used. The same request gives the same files, which are kept."""
    tool = program(runtime)
    if tool is None:
        return None
    try:
        asked = request(triangles, held, maps, groups, most)
        key = hashlib.sha1(asked).hexdigest()
        home = folder()
        prefix = home / key
        info = Path(str(prefix) + '.info')
        if not info.is_file():
            source = home / (key + '.in')
            source.write_bytes(asked)
            try:
                from . import native
                done = subprocess.run([str(tool), str(source), str(prefix)], env=native.environment(tool.parent), stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=1800)
            finally:
                try:
                    source.unlink()
                except OSError:
                    pass
            if done.returncode or not info.is_file():
                return None
            clear(home, keep=key)
        data = info.read_bytes()
        wanted, grown, count = struct.unpack_from('<3q', data, 0)
        files = {}
        for index in range(count):
            group, fibres, points = struct.unpack_from('<3q', data, 24 + 24 * index)
            path = Path('%s.%d.mfc' % (prefix, group))
            if not path.is_file():
                return None
            files[int(group)] = (path, int(fibres), int(points))
        root, tip = struct.unpack_from('<2d', data, 24 + 24 * count)
        os.utime(str(info), None)
        return {'wanted': int(wanted), 'grown': int(grown), 'root': root, 'tip': tip, 'files': files}
    except (OSError, ValueError, struct.error, subprocess.SubprocessError):
        return None


def clear(home, keep=None):
    """Leave the fur most lately grown and clear out the rest, a whole growth at a time."""
    try:
        growths = sorted(home.glob('*.info'), key=lambda path: path.stat().st_mtime, reverse=True)
        for info in growths[KEPT:]:
            stem = info.name[:-len('.info')]
            if stem == keep:
                continue
            for path in home.glob(stem + '.*'):
                try:
                    path.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def read(path, most=0):
    """A fur file as lists: (points, the number of points of each fibre, the radius at each point, each point's place
    as [across, along], how many fibres the file holds). most takes that many fibres at most, evenly through the
    file: for whatever cannot take them all."""
    with open(str(path), 'rb') as source:
        head = source.read(24)
        if len(head) < 24 or head[:4] != b'MFC1':
            raise ValueError('not a fur file')
        fibres, points = struct.unpack_from('<IQ', head, 4)
        counts = array('I')
        counts.fromfile(source, fibres)
        placed = array('f')
        placed.fromfile(source, 4 * points)
        across = array('f')
        across.fromfile(source, 2 * points)
    every = 1 if not most or fibres <= most else -(-fibres // most)
    vertices, kept, radii, places = [], [], [], []
    start = 0
    for index, count in enumerate(counts):
        if index % every == 0:
            kept.append(count)
            for at in range(start, start + count):
                vertices.append([placed[4 * at], placed[4 * at + 1], placed[4 * at + 2]])
                radii.append(placed[4 * at + 3])
                places.append([across[2 * at], across[2 * at + 1]])
        start += count
    return vertices, kept, radii, places, fibres
