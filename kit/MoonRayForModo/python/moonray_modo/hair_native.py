"""Hair grown by the runtime's own program, where the runtime has it.

hair.py grows hair a strand at a time in Python, which for a head of thirty thousand strands is some seconds each time
a guide is moved or a setting changed. The runtime's modo_hair_grow takes the same steps in the same order, with
Python's own random numbers, and so grows the same hair in a small part of the time. Where the program is not to be
had, or fails, grow() returns None and the hair is grown in Python instead.
"""
import struct
import subprocess
import tempfile
import uuid
from array import array
from itertools import chain
from pathlib import Path

PROGRAM = 'modo_hair_grow.exe'
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def program(runtime=None):
    """Where the program is, or None."""
    try:
        from . import native
        found = Path(runtime) if runtime else native.default_runtime()
    except Exception:
        return None
    path = Path(found) / PROGRAM
    return path if path.is_file() else None


def request(guides, triangles, mode, count, width, clump, length_variation, seed, back=None):
    """What the program is asked: the guides, the scalp's triangles or None, and the settings hair.grow takes."""
    guides = [guide for guide in guides]
    parts = [b'MHG1', struct.pack('<2iq3d16d', int(mode), int(count), int(seed), float(width), float(clump), float(length_variation), *(back or IDENTITY)),
             struct.pack('<i', len(guides)), array('i', [len(guide) for guide in guides]).tobytes(),
             array('d', chain.from_iterable(chain.from_iterable(guides))).tobytes()]
    if triangles is None:
        parts.append(struct.pack('<i', -1))
    else:
        parts += [struct.pack('<i', len(triangles)), array('d', chain.from_iterable(chain.from_iterable(triangles))).tobytes()]
    return b''.join(parts)


def answer(data):
    """The program's answer as (strands, how many guides start too far from the scalp): each strand a list of points."""
    if len(data) < 20 or data[:4] != b'MHS1':
        raise ValueError('the hair that came back is not hair')
    adrift, strands = struct.unpack_from('<2q', data, 4)
    counts = array('i')
    counts.frombytes(data[20:20 + 4 * strands])
    flat = array('d')
    flat.frombytes(data[20 + 4 * strands:])
    if len(flat) != 3 * sum(counts):
        raise ValueError('the hair that came back is cut short')
    points = [list(point) for point in zip(*[iter(flat)] * 3)]
    made, start = [], 0
    for count in counts:
        made.append(points[start:start + count])
        start += count
    return made, int(adrift)


def grow(guides, triangles, mode, count, width, clump, length_variation, seed, back=None, runtime=None):
    """As hair.grow, with the scalp given as its triangles and each point taken through back, a transform with its
    basis vectors in rows. None where the program cannot be used."""
    tool = program(runtime)
    if tool is None:
        return None
    folder = Path(tempfile.gettempdir())
    name = 'moonray-hair-' + uuid.uuid4().hex
    asked, given = folder / (name + '.in'), folder / (name + '.out')
    try:
        from . import native
        asked.write_bytes(request(guides, triangles, mode, count, width, clump, length_variation, seed, back))
        done = subprocess.run([str(tool), str(asked), str(given)], env=native.environment(tool.parent), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=600)
        if done.returncode or not given.is_file():
            return None
        return answer(given.read_bytes())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        for path in (asked, given):
            try:
                path.unlink()
            except OSError:
                pass
