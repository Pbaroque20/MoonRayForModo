"""A mesh's fur surface read by the geometry adapter (native-modo/fur_reader.cpp, MR_fur_surface) in one call, where
extra_geometry.fur_entries read it a polygon and a point at a time from Python (a minute on a heavy pelt, Modo's
thread held throughout). The same triangles, normals, materials, maps and guides in the same order; read() returns
None where the adapter is missing or older than this, and fur_entries reads it the slow way."""
import ctypes
import os
import struct
import tempfile
from array import array

_READER = [False]


def _reader():
    if _READER[0] is False:
        _READER[0] = None
        from .mesh_reader import bridge
        library = bridge()
        try:
            if library is not None:
                library.MR_fur_surface.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
                library.MR_fur_surface.restype = ctypes.c_char_p
                _READER[0] = library.MR_fur_surface
        except AttributeError:
            pass
    return _READER[0]


class Flat:
    """Items of `size` numbers each, `parts` at a time (a triangle's six corners and normals; a weight at three corners;
    a vector at three corners), kept as the run of doubles the adapter wrote, read as the tuples fur.py walks.
    The native grower's request (fur_native.request) takes the run itself."""
    __slots__ = ('flat', 'size', 'parts')

    def __init__(self, flat, size, parts):
        self.flat, self.size, self.parts = flat, size, parts

    def __len__(self):
        return len(self.flat) // (self.size * self.parts)

    def __bool__(self):
        return len(self.flat) > 0

    def __getitem__(self, index):
        count = len(self)
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError('index out of range')
        start = index * self.size * self.parts
        values = self.flat[start:start + self.size * self.parts]
        if self.size == 1:
            return tuple(values)
        return tuple(tuple(values[k * self.size:(k + 1) * self.size]) for k in range(self.parts))

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


def read(mesh, wanted='', weights=(), vector='', guides=False, guide_tag='', guide_kind='MATR', surface=True):
    """The fur surface of an lx.object.Mesh: {'triangles': Flat of (a, b, c, na, nb, nc), 'worn': each triangle's material,
    'weights': {name: Flat of three weights a triangle, or None where not found}, 'vector': Flat of three vectors a
    triangle, or None, 'guides': [[point, ...], ...]}; None where the adapter cannot."""
    reader = _reader()
    if reader is None:
        return None
    try:
        address = mesh.__peekobj__()
    except AttributeError:
        return None
    lines = ['wanted\t' + (wanted or ''), 'surface\t' + ('1' if surface else '0'), 'guides\t' + ('1' if guides else '0')]
    lines += ['weight\t' + name for name in weights]
    if vector:
        lines.append('vector\t' + vector)
    if guide_tag:
        lines += ['guidetag\t' + guide_tag, 'guidekind\t' + guide_kind]
    handle, name = tempfile.mkstemp(prefix='MoonRay-fur-', suffix='.bin')
    os.close(handle)
    try:
        error = reader(ctypes.c_void_p(address), '\n'.join(lines).encode('utf-8'), name.encode('utf-8'))
        if error:
            return None
        with open(name, 'rb') as stream:
            data = stream.read()
    except OSError:
        return None
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass
    try:
        return _parse(data, weights, bool(vector))
    except (ValueError, struct.error, IndexError):
        return None


def _parse(data, weights, vector):
    if data[:4] != b'MFS1':
        raise ValueError('Not a fur surface')
    at = 4

    def number(kind='<i'):
        nonlocal at
        value, = struct.unpack_from(kind, data, at)
        at += struct.calcsize(kind)
        return value

    def doubles(count):
        nonlocal at
        values = array('d')
        values.frombytes(data[at:at + 8 * count])
        if len(values) != count:
            raise ValueError('The fur surface is cut short')
        at += 8 * count
        return values
    count = number()
    triangles = Flat(doubles(count * 18), 3, 6)
    names = []
    for _ in range(number()):
        size = number()
        names.append(data[at:at + size].decode('utf-8', errors='replace'))
        at += size
    worn_numbers = array('i')
    worn_numbers.frombytes(data[at:at + 4 * count])
    at += 4 * count
    worn = [names[i] for i in worn_numbers]
    found = {}
    for name in weights:
        found[name] = Flat(doubles(count * 3), 1, 3) if number() else None
    vectors = Flat(doubles(count * 9), 3, 3) if number() else None
    strands = []
    for _ in range(number()):
        points = doubles(number() * 3)
        strands.append([list(points[k:k + 3]) for k in range(0, len(points), 3)])
    return {'triangles': triangles, 'worn': worn, 'weights': found, 'vector': vectors if vector else None, 'guides': strands}
