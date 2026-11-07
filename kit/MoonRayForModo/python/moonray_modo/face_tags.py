"""The material tags a mesh's faces wear, as a set, made once for each list of tags.

A mesh read again for a move keeps its lists (incremental reuse): its face_materials is the same list from one reading
to the next. Making a set of it at every reading walked every face of the scene, ~70 ms a reading of a heavy car, on
Modo's thread while something was dragged. The set is remembered by the list itself, as scene_digest remembers hashes.
"""
import threading

_held = {}
_lock = threading.Lock()


def worn(mesh):
    """The tags a mesh's faces wear (its one material where they carry none), as a frozenset."""
    faces = mesh.get('face_materials')
    if not faces:
        return frozenset((mesh.get('material', ''),))
    entry = _held.get(id(faces))
    if entry is None or entry[0] is not faces:
        entry = (faces, frozenset(faces))
        with _lock:
            if len(_held) > 8192:
                _held.clear()
            _held[id(faces)] = entry
    return entry[1]
