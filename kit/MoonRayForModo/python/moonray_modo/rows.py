"""Rows of numbers as Modo hands them over, kept as they came.

A heavy scene's meshes come from the geometry adapter as long runs of 32-bit numbers (evaluated._row). Made into a
Python list for every point, corner and face, they were most of the time a reading took, and gigabytes of Modo's
memory (a car scene: 47 s of a 190 s preview start). Rows and Faces keep the run itself and read as the lists they
stand for: what only passes them on (the binary scene file, the scene digest, MoonLightIPR's packing) takes the run
as it is; the lists are made only where something walks them one by one, and then once."""
from array import array
from hashlib import blake2b
from itertools import accumulate
import ctypes

# The geometry adapter (bin/MoonRayGeometry.lx), where it has the arithmetic below (MR_uv_transform, MR_zigzag4):
# set by evaluated once it has loaded it. Without it, the plugin's own Python does the same.
NATIVE = None


def adapter(library):
    """Use the adapter's arithmetic on rows, where it has it."""
    global NATIVE
    try:
        library.MR_uv_transform.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_longlong, ctypes.c_void_p]
        library.MR_uv_transform.restype = ctypes.c_int
        library.MR_zigzag4.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_longlong]
        library.MR_zigzag4.restype = ctypes.c_int
    except AttributeError:
        return
    # Gathering and the finite check (MR_gather, MR_finite), where the adapter has them: done there, Python's lock is
    # let go meanwhile, and Modo's thread goes on.
    try:
        library.MR_gather.argtypes = [ctypes.c_void_p, ctypes.c_longlong, ctypes.c_longlong, ctypes.c_void_p, ctypes.c_longlong, ctypes.c_void_p]
        library.MR_gather.restype = ctypes.c_int
        library.MR_finite.argtypes = [ctypes.c_void_p, ctypes.c_longlong]
        library.MR_finite.restype = ctypes.c_int
        library.MR_most.argtypes = [ctypes.c_void_p, ctypes.c_longlong]
        library.MR_most.restype = ctypes.c_longlong
        library.MR_iota.argtypes = [ctypes.c_void_p, ctypes.c_longlong]
        library.MR_iota.restype = ctypes.c_int
    except AttributeError:
        pass
    NATIVE = library


def _native():
    """The adapter where it can be had: the one evaluated loaded, else the kit's own, as simplify loads it (the same
    file as Modo's plugin)."""
    if NATIVE is None:
        try:
            from .simplify import library
            held = library()
            if held is not None:
                adapter(held)
        except Exception:
            pass
    return NATIVE if NATIVE is not None and hasattr(NATIVE, 'MR_gather') and hasattr(NATIVE, 'MR_iota') else None


def gather(values, width, places):
    """The items of values (an array, width bytes each) at places (whole numbers), one after another, as an array of
    the same kind, by the adapter, away from Python's lock; None where it cannot (no adapter, a place beyond them)."""
    native = _native()
    if native is None or not isinstance(values, array) or width <= 0 or len(values) * values.itemsize % width:
        return None
    places = places if isinstance(places, array) and places.typecode in ('I', 'L') and places.itemsize == 4 else array('I', places)
    rows = len(values) * values.itemsize // width
    out = array(values.typecode, bytes(width * len(places)))
    if len(places) and native.MR_gather(_address(values), rows, width, _address(places), len(places), _address(out)):
        return None
    return out


def most(values):
    """The largest of an array of 32-bit whole numbers (0 where empty), by the adapter where it can, else Python's."""
    native = _native()
    if native is None or not isinstance(values, array) or values.itemsize != 4 or values.typecode not in ('I', 'L'):
        return max(values) if len(values) else 0
    return int(native.MR_most(_address(values), len(values))) if len(values) else 0


def iota(count):
    """0, 1, 2 ... count - 1 as an array of 32-bit whole numbers, by the adapter where it can."""
    native = _native()
    if native is None or count <= 0:
        return array('I', range(max(0, count)))
    out = array('I', bytes(4 * count))
    native.MR_iota(_address(out), count)
    return out


def finite(values):
    """Whether every number of a 32-bit float array is finite, by the adapter; None where it cannot be asked."""
    native = _native()
    if native is None or not isinstance(values, array) or values.typecode != 'f':
        return None
    return not len(values) or bool(native.MR_finite(_address(values), len(values)))


def _address(held):
    return held.buffer_info()[0] if isinstance(held, array) else ctypes.addressof(ctypes.c_char.from_buffer(held))


class Rows:
    """Rows of `width` numbers each, read as the list of lists they stand for (of numbers, for a width of 1)."""
    __slots__ = ('data', 'width', 'digest', '_rows', '__weakref__')

    def __init__(self, data, width, digest):
        self.data, self.width, self.digest, self._rows = data, width, digest, None

    def rows(self):
        """The rows as lists, made once."""
        if self._rows is None:
            numbers = self.data.tolist()
            # zip takes width numbers at a time: about three times as fast as slicing.
            self._rows = numbers if self.width == 1 else list(map(list, zip(*[iter(numbers)] * self.width)))
        return self._rows

    def __len__(self):
        return len(self.data) // self.width

    def __bool__(self):
        return len(self.data) > 0

    def __iter__(self):
        return iter(self.rows())

    def __reversed__(self):
        return reversed(self.rows())

    def __contains__(self, value):
        return value in self.rows()

    def __getitem__(self, index):
        if self._rows is not None or isinstance(index, slice):
            return self.rows()[index]
        width = self.width
        if width == 1:
            return self.data[index]
        count = len(self.data) // width
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError('row index out of range')
        return self.data[index * width:(index + 1) * width].tolist()

    def __eq__(self, other):
        if isinstance(other, Rows):
            return self.width == other.width and self.data == other.data
        return self.rows() == other

    def __ne__(self, other):
        return not self == other

    __hash__ = None

    def __add__(self, other):
        return self.rows() + list(other)

    def __radd__(self, other):
        return list(other) + self.rows()

    def index(self, value, *where):
        return self.rows().index(value, *where)

    def count(self, value):
        return self.rows().count(value)

    def copy(self):
        return list(self.rows())

    def __repr__(self):
        return 'Rows(%d of %d)' % (len(self), self.width)

    def __reduce__(self):
        return (Rows, (self.data, self.width, self.digest))


class Faces(Rows):
    """Faces, read as the list of each face's corners: a run of corners cut by a run of corner counts."""
    __slots__ = ('counts', 'uniform', '_starts')

    def __init__(self, corners, counts, digest):
        # Faces all of one size (a mesh of triangles, or of quads) are cut without the counts.
        self.uniform = counts[0] if len(counts) and min(counts) == max(counts) else 0
        Rows.__init__(self, corners, self.uniform or 1, digest)
        self.counts, self._starts = counts, None

    def rows(self):
        if self._rows is None:
            if self.uniform:
                numbers = self.data.tolist()
                self._rows = list(map(list, zip(*[iter(numbers)] * self.uniform)))
            else:
                from itertools import islice
                run = iter(self.data.tolist())
                self._rows = [list(islice(run, n)) for n in self.counts]
        return self._rows

    def __len__(self):
        return len(self.counts)

    def __bool__(self):
        return len(self.counts) > 0

    def __getitem__(self, index):
        if self._rows is not None or isinstance(index, slice):
            return self.rows()[index]
        count = len(self.counts)
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError('face index out of range')
        if self.uniform:
            return self.data[index * self.uniform:(index + 1) * self.uniform].tolist()
        if self._starts is None:
            self._starts = array('q', accumulate(self.counts, initial=0))
        return self.data[self._starts[index]:self._starts[index + 1]].tolist()

    def __eq__(self, other):
        if isinstance(other, Faces):
            return self.counts == other.counts and self.data == other.data
        return self.rows() == other

    def __repr__(self):
        return 'Faces(%d)' % len(self)

    def __reduce__(self):
        return (Faces, (self.data, self.counts, self.digest))


def numbers(value, width, typecode='f'):
    """A list of rows' numbers flat, as the run they came in, where they did (of this width and kind); else None."""
    if isinstance(value, Rows) and not isinstance(value, Faces) and value.width == width and value.data.typecode == typecode:
        return value.data
    return None


def corners(faces):
    """Faces' corners flat, as the run they came in, where they did; else None."""
    return faces.data if isinstance(faces, Faces) else None


def counts(faces):
    """Each face's number of corners, as the run it came in, where it did; else None."""
    return faces.counts if isinstance(faces, Faces) else None


def uv_transform(values, matrix):
    """UVs as Modo handed them over through a layer's matrix (coordinates.transform_uv's a..f, cos and sin of its
    rotation, its scale x and y), by the adapter: the same numbers as 32-bit floats, as Rows. None where it cannot."""
    held = numbers(values, 2)
    if NATIVE is None or held is None or not len(held):
        return None
    out = array('f', bytes(4 * len(held)))
    numbers_in = (ctypes.c_double * 10)(*matrix)
    if NATIVE.MR_uv_transform(_address(held), _address(out), len(held) // 2, ctypes.addressof(numbers_in)):
        return None
    return Rows(out, 2, 'uv:' + blake2b(memoryview(out), digest_size=16).hexdigest())


def zigzag4(held):
    """Whole numbers (0 to 2^27) in scene_rdl2's fixed four-byte zigzag form, by the adapter; None where it cannot."""
    if NATIVE is None or not isinstance(held, array) or held.typecode != 'i' or not len(held):
        return None
    out = bytearray(4 * len(held))
    return bytes(out) if NATIVE.MR_zigzag4(_address(held), _address(out), len(held)) == 0 else None


def corner_count(faces):
    """How many corners the faces have in all."""
    return len(faces.data) if isinstance(faces, Faces) else sum(map(len, faces))
