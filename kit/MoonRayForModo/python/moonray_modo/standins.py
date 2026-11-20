"""The Asset Library's stand-ins: low-res everyday objects (a chair, a table, a lamp, a car, a person...) that a linked
mesh is drawn as in Modo's viewport while its own mesh renders (links.py: the Scene Proxy's preview item). Made by
tools/make_standins.py into assets/library/standins, each an OBJ fitted to a unit box (-0.5 to 0.5 across and deep, 0 to
1 high), listed in standins.json with the words a mesh's name is matched by. The Links panel takes one by the mesh's
name (choose), else a box, and stretches it to the mesh's own bounds (fitted)."""
import json
import re
from pathlib import Path

DEFAULT = 'Box'
AUTO = 'auto'       # chosen by the mesh's name (choose)
NONE = 'none'       # no stand-in: the proxy draws its mesh itself
LABEL = ' Stand-in'  # a stand-in is named for its mesh: 'Chair Stand-in'
TAG = 'MRSI'        # the item tag a stand-in carries in its link file: its name in the library


def folder():
    from .asset_library import bundled
    return bundled() / 'standins'


_CATALOG = {}


def catalog(where=None):
    """The stand-ins, in the library's order: dicts of name, file (its path), words."""
    where = Path(where) if where else folder()
    key = str(where)
    if key not in _CATALOG:
        try:
            held = json.loads((where / 'standins.json').read_text(encoding='utf-8'))['standins']
        except (OSError, ValueError, KeyError):
            held = []
        _CATALOG[key] = [dict(entry, file=str(where / entry['file'])) for entry in held if (where / entry['file']).is_file()]
    return _CATALOG[key]


def find(name, where=None):
    """A stand-in by its name (any case); None where the library has none of it."""
    for entry in catalog(where):
        if entry['name'].lower() == str(name or '').lower():
            return entry
    return None


def words(name):
    """A mesh's name as lower-case words: split at anything not a letter and at camelCase ('OfficeChair_02' -> office,
    chair), each also without a plural 's'."""
    found = []
    for part in re.findall(r'[A-Za-z]+', str(name or '')):
        for word in re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+', part) or [part]:
            word = word.lower()
            found.append(word)
            if len(word) > 3 and word.endswith('s'):
                found.append(word[:-1])
    return found


def choose(name, where=None):
    """The stand-in for a mesh named name: the library's one with a word of the name among its words (the longest such
    word winning, so 'table lamp' is a table lamp, not a table), else one whose word the name holds run together
    ('floorlamp'), else the box."""
    held = catalog(where)
    said = words(name)
    best, length, first = None, 0, len(said)
    for entry in held:
        for word in entry['words']:
            if word not in said:
                continue
            # Longer words first; of words as long, the one said first ('pine_tree' is a pine).
            at = said.index(word)
            if len(word) > length or (len(word) == length and at < first):
                best, length, first = entry, len(word), at
    # Two words of the name read together ('Table Lamp', 'floor_lamp') as the library's run-together ones.
    joined = ''.join(said)
    for entry in held:
        for word in entry['words']:
            if len(word) > length and len(word) > 5 and word in joined:
                best, length = entry, len(word)
    return best or find(DEFAULT, where)


def read(path):
    """An OBJ's points and polygons (0-based corner lists); its own, as tools/make_standins.py writes them."""
    points, faces = [], []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith('v '):
            points.append(tuple(float(v) for v in line.split()[1:4]))
        elif line.startswith('f '):
            faces.append([int(v.split('/')[0]) - 1 for v in line.split()[1:]])
    return points, faces


def fitted(points, low, high):
    """A stand-in's points (fitted to the unit box) stretched to the bounds low-high: across and deep about their middle,
    up from their bottom."""
    size = [max(high[k] - low[k], 1e-6) for k in range(3)]
    middle = [(low[k] + high[k]) / 2.0 for k in range(3)]
    return [(middle[0] + x * size[0], low[1] + y * size[1], middle[2] + z * size[2]) for x, y, z in points]
