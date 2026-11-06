"""A heavy mesh read out of Modo in one call.

Asking Modo for a mesh a polygon at a time from Python costs tens of microseconds for each polygon, which is minutes
for a scene of millions. The plugin's native geometry adapter (bin/MoonRayGeometry.lx) reads the whole mesh at once
and hands it over as a file of numbers; this module asks it to and lays the numbers out as the scene reader wants
them. Where the adapter is missing or older than this, read() returns None and the mesh is read the slow way."""
import ctypes
import os
import struct
import tempfile
from array import array
from pathlib import Path

# Below this many polygons a mesh is read a polygon at a time, through Modo's own accessors. Every mesh is read by the
# adapter since 0.5.3.1: the small meshes of a car (22,000 polygons in all) were a second of each reading the slow way.
THRESHOLD = 1
_bridge = False


def bridge():
    global _bridge
    if _bridge is False:
        _bridge = None
        path = Path(os.environ.get('MOONRAY_MODO_GEOMETRY', '') or Path(__file__).resolve().parents[2] / 'bin/MoonRayGeometry.lx')
        try:
            library = ctypes.CDLL(str(path))
            library.MR_mesh_file.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            library.MR_mesh_file.restype = ctypes.c_char_p
            _bridge = library
        except (OSError, AttributeError):
            pass
    return _bridge


class Mesh:
    """What the adapter read: points, and for each surface polygon its corners, material tag and kind, with the UV
    and normal values of every corner."""

    def __init__(self, data):
        if data[:4] != b'MRM1':
            raise ValueError('Not a mesh from the geometry adapter')
        points, faces, corners, uv_count, has_normal, tag_count, self.lines, self.small = struct.unpack_from('<8i', data, 4)
        self.offset, self.data = 36, data
        # Points, UVs and normals kept as the runs of numbers they came in, read as lists only where something walks
        # them (rows.Rows): made into lists here, a car's 1.5 million polygons took 5 s of every reading.
        self.vertices = self.rows(self.numbers('f', points * 3), 3)
        self.counts = self.numbers('i', faces)
        self.tag_indices = self.numbers('i', faces)
        self.subdivided = self.numbers('B', faces)
        self.indices = self.numbers('i', corners)
        self.uv_names, self.uv_valid, self.uv_values = [], [], []
        for _ in range(uv_count):
            self.uv_names.append(self.text())
            self.uv_valid.append(self.numbers('B', faces))
            self.uv_values.append(self.rows(self.numbers('f', corners * 2), 2))
        self.normal_valid, self.normal_values = None, None
        if has_normal:
            self.normal_valid = self.numbers('B', faces)
            self.normal_values = self.rows(self.numbers('f', corners * 3), 3)
        self.tags = [self.text() for _ in range(tag_count)]
        del self.data

    @staticmethod
    def rows(flat, size):
        """A run of numbers as rows of size, kept as the run (rows.Rows)."""
        from hashlib import blake2b
        from .rows import Rows
        return Rows(flat, size, 'mesh:%d:%s' % (size, blake2b(memoryview(flat), digest_size=16).hexdigest()))

    @staticmethod
    def grouped(flat, size):
        """A run of numbers as a list of points, size numbers to each, without a step of Python for each one."""
        return list(map(list, zip(*[iter(flat)] * size)))

    def faces(self):
        """Every polygon as the list of its corners' points."""
        counts, indices = self.counts, self.indices
        if not len(counts):
            return []
        # The corners and the counts kept as they came (rows.Faces), cut into lists only where something walks them.
        from hashlib import blake2b
        from .rows import Faces
        mark = blake2b(memoryview(indices), digest_size=16)
        mark.update(memoryview(counts))
        return Faces(indices, counts, 'mesh-faces:' + mark.hexdigest())

    def numbers(self, kind, count):
        values = array(kind)
        size = values.itemsize * count
        values.frombytes(self.data[self.offset:self.offset + size])
        if len(values) != count:
            raise ValueError('The geometry adapter wrote less than it said')
        self.offset += size
        return values

    def text(self):
        size, = struct.unpack_from('<i', self.data, self.offset)
        self.offset += 4 + size
        return self.data[self.offset - size:self.offset].decode('utf-8', errors='replace')

    def uv_map(self, name):
        """Which of the mesh's UV maps a name means, as the slow reader chooses: none named is the first by name,
        @index:N the Nth; None if there is no such map."""
        order = sorted(range(len(self.uv_names)), key=lambda i: self.uv_names[i])
        if not name or str(name).startswith('@index:'):
            index = int(str(name).split(':', 1)[1]) if name else 0
            return order[index] if index < len(order) else None
        return self.uv_names.index(name) if name in self.uv_names else None


# Meshes the adapter read whole and found to hold nothing but surface polygons, by item: the search for curves and
# loose points in them, a second walk over every polygon, can then be left out.
SURFACES_ONLY = {}


def read(mesh):
    """The mesh as the adapter reads it, or None where it should be read the slow way."""
    library = bridge()
    if library is None or mesh.PolygonCount() < THRESHOLD:
        return None
    try:
        address = mesh.__peekobj__()
    except AttributeError:
        return None
    handle, name = tempfile.mkstemp(prefix='MoonRay-mesh-', suffix='.bin')
    os.close(handle)
    try:
        error = library.MR_mesh_file(ctypes.c_void_p(address), name.encode('utf-8'))
        if error:
            return None
        with open(name, 'rb') as stream:
            return Mesh(stream.read())
    except (OSError, ValueError, struct.error):
        return None
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


class Part:
    """Some of a Mesh's polygons (faces: their places, in order), with all the mesh's points: their corners, counts,
    material tags, UVs and normals gathered out of the mesh's runs by the adapter (rows.gather). Read as a Mesh is."""

    def __init__(self, mesh, faces):
        from array import array
        from itertools import accumulate, chain
        from hashlib import blake2b
        from .rows import gather, Rows
        starts = array('q', accumulate(mesh.counts, initial=0))
        places = array('I', chain.from_iterable(range(starts[f], starts[f + 1]) for f in faces))
        picked = array('I', faces)

        def pick(values, width, places=places):
            held = gather(values, width, places)
            if held is None:
                raise ValueError('The geometry adapter could not gather a part of the mesh')
            return held
        self.vertices, self.tags, self.lines, self.small = mesh.vertices, mesh.tags, mesh.lines, mesh.small
        self.indices = pick(mesh.indices, 4)
        self.counts = pick(mesh.counts, 4, picked)
        self.tag_indices = pick(mesh.tag_indices, 4, picked)
        self.subdivided = pick(mesh.subdivided, 1, picked)
        self.uv_names = mesh.uv_names
        self.uv_valid = [pick(valid, 1, picked) for valid in mesh.uv_valid]
        self.uv_values = [self._rows(pick(values.data, 8), 2) for values in mesh.uv_values]
        self.normal_valid = pick(mesh.normal_valid, 1, picked) if mesh.normal_valid is not None else None
        self.normal_values = self._rows(pick(mesh.normal_values.data, 12), 3) if mesh.normal_values is not None else None
        self.faces_of = picked

    _rows = staticmethod(Mesh.rows)
    faces = Mesh.faces
    uv_map = Mesh.uv_map
