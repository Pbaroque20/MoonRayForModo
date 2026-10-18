"""Picking from a Cryptomatte buffer in the preview: the matte under a pixel, its name and what it is of, and the
picture of the mattes picked.

A Cryptomatte buffer holds, for each pixel, a few ranks of (ID, coverage), the matte covering most first. Each rank is
read from the buffer's file once, as the compositor reads buffers, and kept until the file changes. The names come from
the scene the picture was rendered from, worked out as the manifest is (cryptomatte.mattes), since a preview buffer's
file carries no manifest of its own. Finding a matte's pixels looks for its ID's four bytes in each rank, which is quick
whatever the size of the picture: only the pixels it covers are visited."""
import array
import re
import struct
import subprocess
import tempfile
from pathlib import Path

from . import cryptomatte, native

_ranks = {}
_names = {}


def _read_pfm(path):
    data = Path(path).read_bytes()
    lines, at = [], 0
    while len(lines) < 3:
        end = data.index(b'\n', at)
        lines.append(data[at:end].strip())
        at = end + 1
    width, height = (int(v) for v in lines[1].split())
    values = array.array('f')
    values.frombytes(data[at:at + width * height * 12])
    if (float(lines[2]) > 0) != (struct.pack('=I', 1) == struct.pack('>I', 1)):
        values.byteswap()
    return width, height, values


def _part(listed, key):
    """Which part of an EXR holds a Cryptomatte, from the image tool's description of the file: (its index, its layers).
    A render to a file with Cryptomatte of more than one kind keeps each in a part named after its output; the part of
    that name is taken, and otherwise the first with Cryptomatte in it."""
    parts, current = {}, 0
    for line in listed.splitlines():
        found = re.match(r'\s*subimage\s+(\d+):', line)
        if found:
            current = int(found.group(1))
        held = parts.setdefault(current, {'name': None, 'layers': []})
        if 'channel list:' in line:
            held['layers'] = sorted(set(re.findall(r'\b(Cryptomatte\d\d)\.R\b', line)))
        named = re.match(r'\s*name:\s*"(.*)"', line)
        if named:
            held['name'] = named.group(1)
    with_mattes = [index for index in sorted(parts) if parts[index]['layers']]
    index = next((index for index in with_mattes if parts[index]['name'] == key), with_mattes[0] if with_mattes else 0)
    return index, parts.get(index, {}).get('layers', [])


def ranks(frame, key):
    """A Cryptomatte buffer's ranks, (width, height, [(IDs, coverages)]), each as floats rows from the bottom up; None where
    the buffer has no file to read."""
    path = (frame.get('files') or {}).get(key)
    if not path or not Path(path).is_file():
        return None
    # A file may hold Cryptomatte of more than one kind, each in its own part: each is kept by the file and its output.
    stamp = (str(path), Path(path).stat().st_mtime_ns, key)
    if stamp in _ranks:
        return _ranks[stamp]
    runtime = Path(frame['runtime'])
    env = native.environment(runtime)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    listed = subprocess.run([str(runtime / 'oiiotool.exe'), '--info', '-v', '-a', str(path)], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=60, creationflags=flags).stdout.decode(errors='replace')
    part, layers = _part(listed, key)
    chosen = ['--subimage', str(part)] if part else []
    found, size = [], None
    with tempfile.TemporaryDirectory(prefix='MoonRayCrypto-') as folder:
        # Every rank in one run: the file is read once, and each rank written as (ID, coverage, coverage).
        command, targets = [str(runtime / 'oiiotool.exe'), '--no-autopremult'], []
        for layer in layers:
            for id_channel, amount in (('R', 'G'), ('B', 'A')):
                target = Path(folder) / ('%s%s.pfm' % (layer, id_channel))
                command += ['-i', str(path)] + chosen + ['--ch', '%s.%s,%s.%s,%s.%s' % (layer, id_channel, layer, amount, layer, amount), '-d', 'float', '-o', str(target)]
                targets.append(target)
        subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, creationflags=flags)
        for target in targets:
            if not target.is_file():
                continue
            width, height, values = _read_pfm(target)
            size = (width, height)
            found.append((values[0::3], values[1::3]))
    result = (size[0], size[1], found) if size else None
    for held in [held for held in _ranks if held[0] == stamp[0] and held[2] == key]:
        del _ranks[held]
    _ranks[stamp] = result
    return result


def names(frame, category):
    """The mattes of the scene a frame was rendered from, ({ID: name}, {name: [what it is of]})."""
    snapshot = frame.get('snapshot') or {}
    held = (id(snapshot), category)
    if held not in _names:
        geometries = list(snapshot.get('meshes') or []) + list(snapshot.get('extra_geometry') or [])
        mattes = cryptomatte.mattes(geometries, category, snapshot)
        _names.clear()
        _names[held] = ({value: label for label, value in mattes.items()}, cryptomatte.owners(geometries, category, snapshot))
    return _names[held]


def at(frame, key, x, y):
    """The ID of the matte covering most of a pixel (x across, y down from the top), or None."""
    read = ranks(frame, key)
    if read is None:
        return None
    width, height, found = read
    if not (0 <= x < width and 0 <= y < height) or not found:
        return None
    index = (height - 1 - y) * width + x
    best = max(found, key=lambda rank: rank[1][index])
    if best[1][index] <= 0.0:
        return None
    return struct.unpack('<I', struct.pack('<f', best[0][index]))[0]


def buffer_of(snapshot, category):
    """The name of a scene's Cryptomatte output of a category, or None."""
    return next((entry.get('name') for entry in (snapshot or {}).get('custom_aovs') or []
                 if entry.get('kind') == 'cryptomatte' and entry.get('category', 'object') == category), None)


def ids_of(frame, category, matte):
    """The IDs a matte named in a Cryptomatte node is written with: #number for an ID given as a number, else every
    matte of the frame's scene by that name."""
    if matte.startswith('#') and matte[1:].isdigit():
        return [cryptomatte.bits(int(matte[1:]))]
    snapshot = frame.get('snapshot') or {}
    geometries = list(snapshot.get('meshes') or []) + list(snapshot.get('extra_geometry') or [])
    return [value for label, value in cryptomatte.mattes(geometries, category, snapshot).items() if label == matte]


def matte_file(frame, category, matte, folder):
    """A matte of a Cryptomatte node as a picture file in folder: grey, as much as it covers each pixel."""
    key = buffer_of(frame.get('snapshot'), category)
    if not key or key not in (frame.get('files') or {}):
        raise ValueError('The Cryptomatte node takes the %s Cryptomatte, which this render has not made: choose it among the '
                         'buffers to add it, and render again' % category)
    if not matte:
        raise ValueError('Choose the matte of the Cryptomatte node')
    read = coverage(frame, key, ids_of(frame, category, matte))
    if read is None:
        raise ValueError('Cannot read the %s Cryptomatte' % category)
    width, height, covered = read
    values = array.array('f', bytes(width * height * 12))
    for pixel, amount in covered.items():
        row, column = divmod(pixel, width)
        at = ((height - 1 - row) * width + column) * 3
        values[at] = values[at + 1] = values[at + 2] = min(1.0, amount)
    if struct.pack('=I', 1) == struct.pack('>I', 1):
        values.byteswap()
    target = Path(folder) / ('matte_%s_%08x.pfm' % (category, abs(hash(matte)) & 0xffffffff))
    target.write_bytes(('PF\n%d %d\n-1.0\n' % (width, height)).encode('ascii') + values.tobytes())
    return target


def coverage(frame, key, ids):
    """How much the mattes with these IDs cover each pixel they reach: (width, height, {pixel: coverage}), pixels counted
    from the top left, row by row; None where the buffer cannot be read."""
    read = ranks(frame, key)
    if read is None:
        return None
    width, height, found = read
    covered = {}
    for values, amounts in found:
        held = values.tobytes()
        for value in ids:
            pattern, start = struct.pack('<I', value), 0
            while True:
                at_byte = held.find(pattern, start)
                if at_byte < 0:
                    break
                start = at_byte + 1
                if at_byte % 4:
                    continue
                index = at_byte // 4
                amount = amounts[index]
                if amount > 0.0:
                    row, column = divmod(index, width)
                    pixel = (height - 1 - row) * width + column
                    covered[pixel] = covered.get(pixel, 0.0) + amount
    return width, height, covered
