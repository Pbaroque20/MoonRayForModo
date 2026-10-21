"""MoonRay's binary scene format (RDLB), written here for the heavy arrays of the scene's geometry.

A scene is then two files MoonRay is given in turn: its text (RDLA) declares every object and sets everything else,
and this file sets the geometry's long lists (points, faces, UVs, normals, part faces) on the objects the text
declared. MoonRay reads these as bytes rather than parsing millions of numbers as text: on a heavy Modo scene its
loading went from 42 s to a third of a second. The picture is the same: the numbers are the same floats.

The format is scene_rdl2's (BinaryWriter / BinaryReader, ValueContainerEnq): two big-endian 64-bit lengths, a
manifest and a payload; each record a SceneObject (class, name, then its attributes, each a type, a name, a timestep
count and the values). Integer lists are zigzag variable-length numbers, which MoonRay also reads in a fixed width
of four bytes each (a value below 2^27): that width is written here with whole-list integer arithmetic, so that no
step of Python is taken for each number.
"""
from array import array
from contextlib import contextmanager
from itertools import chain
import struct
import sys

# scene_rdl2's ValueContainerUtil::ValueType
BOOL, INT, INT_VECTOR, FLOAT, FLOAT_VECTOR, STRING, STRING_VECTOR = 1, 3, 4, 7, 8, 11, 12
RGB_VECTOR = 14
VEC2F_VECTOR, VEC3F_VECTOR = 18, 22
SCENE_OBJECT_2 = 2
FIXED_LIMIT = 1 << 27

_LITTLE = sys.byteorder == 'little'


_SMALL = [bytes((n,)) for n in range(128)]


def vl(value):
    """An unsigned variable-length number."""
    if value < 128:
        return _SMALL[value]
    out = bytearray()
    while value > 0x7f:
        out.append((value & 0x7f) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def zigzag(value):
    return vl((value << 1) ^ (value >> 63) if value < 0 else value << 1)


def text(value):
    data = str(value).encode('utf-8')
    return vl(len(data)) + data


def _pattern(lane, count):
    """A repeating 32-bit pattern as one integer, for count lanes."""
    return int.from_bytes(struct.pack('<I', lane) * count, 'little')


def int_list(values):
    """IntVector values (zigzag variable-length), each in four bytes."""
    held = values if isinstance(values, array) and values.typecode in ('i', 'I', 'l', 'L') else array('l', values)
    count = len(held)
    if not count:
        return vl(0)
    if min(held) < 0 or max(held) >= FIXED_LIMIT:
        return vl(count) + b''.join(zigzag(int(v)) for v in held)
    lanes = array('I', held)
    if not _LITTLE:
        lanes.byteswap()
    x = int.from_bytes(lanes.tobytes(), 'little') << 1     # zigzag of a value that is not negative
    y = ((x & _pattern(0x7f, count)) | ((x << 1) & _pattern(0x7f00, count)) | ((x << 2) & _pattern(0x7f0000, count))
         | ((x << 3) & _pattern(0x7f000000, count)) | _pattern(0x808080, count))
    return vl(count) + y.to_bytes(4 * count, 'little')


def float_list(values, size=1):
    """Float vectors (FloatVector, Vec2fVector, Vec3fVector): their floats as they lie in memory."""
    flat = values if isinstance(values, array) and values.typecode == 'f' else array(
        'f', chain.from_iterable(values) if size > 1 else values)
    if len(flat) % size:
        raise ValueError('Vector list of the wrong size')
    if not _LITTLE:
        flat = array('f', flat)
        flat.byteswap()
    return vl(len(flat) // size) + flat.tobytes()


def string_list(values):
    values = list(values)
    return vl(len(values)) + b''.join(text(v) for v in values)


_HEADERS = {}


class SceneObject:
    def __init__(self, klass, name):
        self.klass, self.name, self.parts = klass, name, []

    def add(self, kind, attribute, encoded):
        # The type, not a transient id, the name, no further timestep (not blurrable), timestep 0, the value.
        header = _HEADERS.get((kind, attribute))
        if header is None:
            header = _HEADERS[(kind, attribute)] = vl(kind) + b'\x00' + text(attribute) + b'\x00\x00'
        self.parts.append(header + encoded)

    def bytes(self):
        body = text(self.klass) + text(self.name) + b''.join(self.parts) + vl(0) + b'\x00'   # end of values, of bindings
        return struct.pack('<Q', 8 + len(body)) + body


class Sink:
    """Collects the scene's binary records while its text is written, and how each list would be written as text
    (for a loaded preview session's changes: scene_delta.difference)."""

    def __init__(self, fingerprints=True):
        self.objects = {}
        self.texts = {}
        # Only a loaded preview session compares one scene's text with the next's (scene_delta).
        self.fingerprints = fingerprints

    def text_of(self, owner, attribute):
        """The text of one list now in the binary file, by its object as the scene text names it, or None."""
        written = self.texts.get((owner, attribute))
        return written() if written is not None else None

    def object(self, klass, name):
        held = self.objects.get(name)
        if held is None:
            held = self.objects[name] = SceneObject(klass, name)
        return held

    def payload(self):
        records = [o.bytes() for o in self.objects.values()]
        manifest_body = vl(len(records)) + b''.join(vl(SCENE_OBJECT_2) + vl(len(r)) for r in records)
        manifest = struct.pack('<Q', 8 + len(manifest_body)) + manifest_body
        payload = b''.join(records)
        return struct.pack('>QQ', len(manifest), len(payload)) + manifest + payload

    def write(self, path):
        with open(path, 'wb') as out:
            out.write(self.payload())


_SINK = None


def _cached(kind, source, encode):
    global _cached
    from .serialization import array
    _cached = array   # imported once: under Modo every import statement runs through PySide's import hook
    return array(kind, source, encode)


@contextmanager
def collecting(fingerprints=True):
    """While the scene's text is written, its geometry's heavy lists go to a Sink instead."""
    global _SINK
    held, _SINK = _SINK, Sink(fingerprints)
    try:
        yield _SINK
    finally:
        _SINK = held


def active():
    return _SINK


def heavy(klass, name, attribute, kind, source, label, encode, owner=None, written=None):
    """Put one heavy list on the object in the binary file, if one is being written: its fingerprint if it was, else
    None. The encoded bytes are kept with the scene's other written lists (serialization.array), by the list they
    came from; the fingerprint goes in the text in the list's place, so that a change to the list is a change there."""
    if _SINK is None:
        return None
    encoded = _cached('rdlb-' + label, source, encode)
    _SINK.object(klass, name).add(kind, attribute, encoded)
    if not _SINK.fingerprints:
        return ''
    if owner is not None and written is not None:
        _SINK.texts[(owner, attribute)] = written
    return _cached('rdlb-fingerprint-' + label, source, lambda: _blake2b(encoded, digest_size=12).hexdigest())


from hashlib import blake2b as _blake2b
