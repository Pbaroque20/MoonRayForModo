"""Fast change detection for preview snapshots.

A snapshot's geometry lists are large and are never edited in place: an unchanged mesh keeps
the same list objects from one capture to the next. Each list is hashed once and remembered by
identity, so comparing two snapshots costs what changed rather than the size of the scene.
"""
import hashlib
import json
import marshal
import threading
from .rows import Rows

# Per-mesh lists that scale with polygon count, and with instances, strands or particles: each hashed once by the list
# itself (content). The others json.dumps walked whole at every edit: a scattered scene's matrices, a mesh's map values.
HEAVY = ('vertices', 'vertices_close', 'faces', 'uvs', 'normals', 'face_materials', 'creases', 'corners',
         'instances', 'instances_close', 'instance_ids', 'instance_attributes', 'instance_velocities', 'instance_variation',
         'counts', 'radii', 'ids', 'velocities', 'widths')
# Dicts of a mesh's maps whose values are heavy: {name: {'kind', 'values'}}.
MAPPED = ('point_attributes', 'corner_attributes')
_remembered = {}
# Where lists were made from rows of numbers handed over whole (evaluated registers itself), what each was made from:
# a function giving a list's numbers flat, as an array, and a digest of their bytes; None for any other list.
FLAT = []
# A scene is made ready for MoonLightIPR on a thread of its own, which asks for these hashes too.
_lock = threading.RLock()


def flat(value):
    """A list's numbers flat, as the array they were handed over in, and a digest of them; None where it was not."""
    for source in FLAT:
        held = source(value)
        if held is not None:
            return held
    return None


def content(value):
    """A stable hash of one large list; equal values hash equally within a session."""
    entry = _remembered.get(id(value))
    if entry is None or entry[0] is not value:
        # Rows of numbers handed over whole (rows.Rows, rows.Faces) carry the digest of their bytes: known by it whether
        # or not evaluated's hook is set. A scene read without Modo's render cache never set it, and marshal, which
        # cannot write Rows, stopped the render ("unmarshallable object").
        held = (value.data, value.digest) if isinstance(value, Rows) and value.digest else flat(value)
        # A list made from a row handed over is known by that row's bytes, which were hashed as they came: the
        # numbers of a large scene's meshes are not walked again. Else marshal walks nested lists of numbers and
        # strings in C; version 2 writes floats exactly.
        entry = (value, held[1] if held is not None else hashlib.blake2b(marshal.dumps(value, 2), digest_size=16).hexdigest())
        with _lock:
            if len(_remembered) > 8192:
                _remembered.clear()     # only digest() prunes; bound callers that never use it
            _remembered[id(value)] = entry
    return entry[1]


def _unknown(value):
    raise TypeError('Object of type %s is not JSON serializable' % type(value).__name__)


def digest(scene, *extra):
    """Hash a snapshot and any settings that also decide whether a preview must restart."""
    used = set()

    def light(mesh):
        result = dict(mesh)
        for key in HEAVY:
            if isinstance(mesh.get(key), (list, Rows)) and mesh[key]:
                result[key] = content(mesh[key]); used.add(id(mesh[key]))
        for key in MAPPED:
            held = mesh.get(key)
            if isinstance(held, dict):
                result[key] = {}
                for name, entry in held.items():
                    values = entry.get('values') if isinstance(entry, dict) else None
                    if isinstance(values, (list, Rows)) and values:
                        result[key][name] = dict(entry, values=content(values)); used.add(id(values))
                    else:
                        result[key][name] = entry
        sets = mesh.get('uv_sets')
        if isinstance(sets, dict):
            result['uv_sets'] = {}
            for name, values in sets.items():
                result['uv_sets'][name] = content(values); used.add(id(values))
        return result

    compact = dict(scene)
    for key in ('meshes', 'extra_geometry'):
        if isinstance(scene.get(key), list):
            compact[key] = [light(item) if isinstance(item, dict) else item for item in scene[key]]
    # Holding only the lists of the latest snapshot keeps their ids from being reused.
    with _lock:
        for stale in [key for key in _remembered if key not in used]:
            del _remembered[stale]
    # Rows anywhere else (a vertex map's values, say) by their digest too.
    encoded = json.dumps([compact, list(extra)], sort_keys=True, separators=(',', ':'),
                         default=lambda value: content(value) if isinstance(value, Rows) else _unknown(value))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()
