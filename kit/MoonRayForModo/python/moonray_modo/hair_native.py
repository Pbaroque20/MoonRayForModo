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
        # A scalp the adapter made (extra_geometry.Triangles) is already its run of numbers.
        flat = getattr(triangles, 'flat', None)
        parts += [struct.pack('<i', len(triangles)), (flat if flat is not None else array('d', chain.from_iterable(chain.from_iterable(triangles)))).tobytes()]
    return b''.join(parts)


class Strand:
    """One strand of the program's answer: its points, kept in the answer's one run of numbers (three doubles a point)
    and read as the list of [x, y, z] they stand for. A batch of them is taken from the run as it is
    (extra_geometry._shaped_natively), not made into lists and back."""
    __slots__ = ('data', 'start', 'count')

    def __init__(self, data, start, count):
        self.data, self.start, self.count = data, start, count

    def numbers(self):
        return self.data[3 * self.start:3 * (self.start + self.count)]

    def points(self):
        flat = self.numbers().tolist()
        return [flat[k:k + 3] for k in range(0, len(flat), 3)]

    def __len__(self):
        return self.count

    def __iter__(self):
        return iter(self.points())

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.points()[index]
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError('point index out of range')
        at = 3 * (self.start + index)
        return self.data[at:at + 3].tolist()

    def __eq__(self, other):
        return self.points() == (other.points() if isinstance(other, Strand) else other)

    # No __add__ or __radd__: a list += a Strand would find __radd__ before the list's own extending, and copy the
    # whole list for each strand (two minutes for 30,000 strands).
    __hash__ = None


def answer(data):
    """The program's answer as (strands, how many guides start too far from the scalp): each strand its points
    (Strand, read as a list of points)."""
    if len(data) < 20 or data[:4] != b'MHS1':
        raise ValueError('the hair that came back is not hair')
    adrift, strands = struct.unpack_from('<2q', data, 4)
    counts = array('i')
    counts.frombytes(data[20:20 + 4 * strands])
    flat = array('d')
    flat.frombytes(data[20 + 4 * strands:])
    if len(flat) != 3 * sum(counts):
        raise ValueError('the hair that came back is cut short')
    made, start = [], 0
    for count in counts:
        made.append(Strand(flat, start, count))
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
