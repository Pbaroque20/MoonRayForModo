"""Fast change detection for preview snapshots.

A snapshot's geometry lists are large and are never edited in place: an unchanged mesh keeps
the same list objects from one capture to the next. Each list is hashed once and remembered by
identity, so comparing two snapshots costs what changed rather than the size of the scene.
"""
import hashlib
import json
import marshal

# Per-mesh lists that scale with polygon count.
HEAVY = ('vertices', 'vertices_close', 'faces', 'uvs', 'normals', 'face_materials', 'creases')
_remembered = {}


def content(value):
    """A stable hash of one large list; equal values hash equally within a session."""
    entry = _remembered.get(id(value))
    if entry is None or entry[0] is not value:
        if len(_remembered) > 8192:
            _remembered.clear()     # only digest() prunes; bound callers that never use it
        # marshal walks nested lists of numbers and strings in C; version 2 writes floats exactly.
        entry = (value, hashlib.blake2b(marshal.dumps(value, 2), digest_size=16).hexdigest())
        _remembered[id(value)] = entry
    return entry[1]


def digest(scene, *extra):
    """Hash a snapshot and any settings that also decide whether a preview must restart."""
    used = set()

    def light(mesh):
        result = dict(mesh)
        for key in HEAVY:
            if isinstance(mesh.get(key), list) and mesh[key]:
                result[key] = content(mesh[key]); used.add(id(mesh[key]))
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
    for stale in [key for key in _remembered if key not in used]:
        del _remembered[stale]
    encoded = json.dumps([compact, list(extra)], sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()
