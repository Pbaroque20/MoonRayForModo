"""Make the Asset Library's stand-ins: low-res everyday objects (a chair, a table, a lamp, a car, a person...) a linked
mesh is drawn as in Modo's viewport while its own mesh renders (links.py: the Scene Proxy's preview item).

Each is built here from boxes, cylinders, cones, spheres and turned profiles, a few hundred polygons at most, and
written as an OBJ fitted to a unit box (-0.5 to 0.5 across and deep, 0 to 1 high, standing on its base), which the
Links panel stretches to the linked mesh's own bounds. standins.json lists each with the words a mesh's name is matched
by. The kit's own work, under the kit's licence.

    python tools/make_standins.py [folder]     (kit/MoonRayForModo/assets/library/standins)"""
import json
import math
import sys
from pathlib import Path


class Shape:
    """Points and polygons (0-based corner lists), built up part by part."""

    def __init__(self):
        self.points, self.faces = [], []

    def add(self, points, faces):
        base = len(self.points)
        self.points += [tuple(float(c) for c in p) for p in points]
        self.faces += [[base + i for i in face] for face in faces]
        return self

    def box(self, centre, size):
        cx, cy, cz = centre
        sx, sy, sz = (s / 2.0 for s in size)
        points = [(cx + x * sx, cy + y * sy, cz + z * sz) for y in (-1, 1) for z in (-1, 1) for x in (-1, 1)]
        # Corners: 0..3 below, 4..7 above; each face wound outward.
        faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
        return self.add(points, faces)

    def lathe(self, profile, centre=(0, 0, 0), sides=12, axis='y'):
        """A profile of (radius, height) pairs from the bottom up turned about an upright axis (or 'x', 'z' lying),
        closed at either end where its radius is not 0."""
        cx, cy, cz = centre
        rings = []
        points = []
        for radius, height in profile:
            ring = []
            for k in range(sides if radius > 0 else 1):
                a = 2 * math.pi * k / sides
                u, v = radius * math.cos(a), radius * math.sin(a)
                # (u, v, along the axis) right-handed for every axis, so that every face below is wound outward.
                if axis == 'y':
                    p = (cx + u, cy + height, cz - v)
                elif axis == 'x':
                    p = (cx + height, cy + u, cz + v)
                else:
                    p = (cx + u, cy + v, cz + height)
                ring.append(len(points))
                points.append(p)
            rings.append(ring)
        faces = []
        for a, b in zip(rings, rings[1:]):
            if len(a) == 1 and len(b) == 1:
                continue
            if len(a) == 1:
                faces += [[a[0], b[(k + 1) % sides], b[k]] for k in range(sides)]
            elif len(b) == 1:
                faces += [[a[k], a[(k + 1) % sides], b[0]] for k in range(sides)]
            else:
                faces += [[a[k], a[(k + 1) % sides], b[(k + 1) % sides], b[k]] for k in range(sides)]
        # The bottom cap faces back along the axis, the top along it.
        if len(rings[0]) > 1:
            faces.append(list(reversed(rings[0])))
        if len(rings[-1]) > 1:
            faces.append(list(rings[-1]))
        return self.add(points, faces)

    def cylinder(self, centre, radius, height, sides=12, axis='y'):
        return self.lathe([(radius, 0), (radius, height)], centre, sides, axis)

    def sphere(self, centre, radius, rings=6, sides=12, squash=1.0):
        profile = [(0, 0)] + [(radius * math.sin(math.pi * k / rings), radius * squash * (1 - math.cos(math.pi * k / rings)))
                              for k in range(1, rings)] + [(0, 2 * radius * squash)]
        return self.lathe(profile, (centre[0], centre[1] - radius * squash, centre[2]), sides)

    def fitted(self):
        """The shape fitted to the unit box: -0.5 to 0.5 across (x) and deep (z), 0 to 1 high, each axis on its own."""
        low = [min(p[k] for p in self.points) for k in range(3)]
        high = [max(p[k] for p in self.points) for k in range(3)]
        size = [max(high[k] - low[k], 1e-9) for k in range(3)]
        points = [((p[0] - low[0]) / size[0] - 0.5, (p[1] - low[1]) / size[1], (p[2] - low[2]) / size[2] - 0.5) for p in self.points]
        return points, self.faces, size


def chair():
    s = Shape().box((0, 0.45, 0), (0.45, 0.05, 0.45))
    for x in (-0.19, 0.19):
        for z in (-0.19, 0.19):
            s.box((x, 0.225, z), (0.04, 0.45, 0.04))
    s.box((-0.19, 0.7, -0.19), (0.04, 0.5, 0.04)).box((0.19, 0.7, -0.19), (0.04, 0.5, 0.04))
    return s.box((0, 0.78, -0.2), (0.42, 0.28, 0.03))


def stool():
    s = Shape().cylinder((0, 0.62, 0), 0.18, 0.05, 16)
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        s.box((0.13 * math.cos(a), 0.31, 0.13 * math.sin(a)), (0.035, 0.62, 0.035))
    return s


def table():
    s = Shape().box((0, 0.73, 0), (1.4, 0.05, 0.8))
    for x in (-0.64, 0.64):
        for z in (-0.34, 0.34):
            s.box((x, 0.355, z), (0.06, 0.71, 0.06))
    return s


def sofa():
    s = Shape().box((0, 0.22, 0), (2.0, 0.24, 0.9))
    s.box((0, 0.42, 0.06), (1.7, 0.16, 0.75))
    s.box((0, 0.6, -0.36), (2.0, 0.55, 0.2))
    return s.box((-0.93, 0.42, 0), (0.16, 0.42, 0.9)).box((0.93, 0.42, 0), (0.16, 0.42, 0.9))


def bed():
    s = Shape().box((0, 0.17, 0), (1.6, 0.3, 2.1))
    s.box((0, 0.42, 0.05), (1.5, 0.2, 1.95))
    s.box((0, 0.6, -1.03), (1.6, 1.0, 0.06))
    return s.box((-0.38, 0.56, -0.8), (0.6, 0.1, 0.32)).box((0.38, 0.56, -0.8), (0.6, 0.1, 0.32))


def shelf():
    s = Shape()
    for x in (-0.48, 0.48):
        s.box((x, 0.9, 0), (0.03, 1.8, 0.35))
    for y in (0.02, 0.45, 0.9, 1.35, 1.78):
        s.box((0, y, 0), (0.93, 0.03, 0.35))
    return s.box((0, 0.9, -0.17), (0.99, 1.8, 0.01))


def cabinet():
    s = Shape().box((0, 0.45, 0), (0.9, 0.82, 0.5)).box((0, 0.02, 0.02), (0.86, 0.04, 0.46))
    s.box((0, 0.88, 0), (0.94, 0.04, 0.54))
    return s.box((-0.05, 0.6, 0.255), (0.02, 0.12, 0.02)).box((0.05, 0.6, 0.255), (0.02, 0.12, 0.02))


def floor_lamp():
    s = Shape().cylinder((0, 0, 0), 0.16, 0.03, 16).cylinder((0, 0.03, 0), 0.015, 1.4, 8)
    return s.lathe([(0.22, 1.35), (0.14, 1.65), (0, 1.65)], sides=16)


def table_lamp():
    s = Shape().lathe([(0.1, 0), (0.1, 0.03), (0.03, 0.05), (0.025, 0.3), (0, 0.3)], sides=16)
    return s.lathe([(0.17, 0.22), (0.1, 0.45), (0, 0.45)], sides=16)


def bottle():
    return Shape().lathe([(0, 0), (0.035, 0), (0.037, 0.02), (0.037, 0.19), (0.03, 0.23), (0.013, 0.27), (0.013, 0.31), (0, 0.31)], sides=16)


def mug():
    s = Shape().lathe([(0, 0), (0.04, 0), (0.042, 0.005), (0.043, 0.1), (0.038, 0.1), (0.037, 0.012), (0, 0.012)], sides=16)
    return s.box((0.055, 0.075, 0), (0.012, 0.012, 0.012)).box((0.062, 0.05, 0), (0.012, 0.05, 0.012)).box((0.055, 0.025, 0), (0.012, 0.012, 0.012))


def vase():
    return Shape().lathe([(0, 0), (0.06, 0), (0.1, 0.08), (0.11, 0.16), (0.07, 0.27), (0.05, 0.32), (0.065, 0.36), (0, 0.36)], sides=16)


def plant():
    s = Shape().lathe([(0, 0), (0.1, 0), (0.13, 0.22), (0.11, 0.22), (0, 0.22)], sides=12)
    return s.sphere((0, 0.45, 0), 0.24, 6, 10).sphere((0.12, 0.6, 0.05), 0.14, 5, 8)


def tree():
    s = Shape().cylinder((0, 0, 0), 0.08, 1.1, 8)
    return s.sphere((0, 1.65, 0), 0.75, 7, 12, 1.05)


def pine():
    s = Shape().cylinder((0, 0, 0), 0.07, 0.6, 8)
    for base, radius, height in ((0.4, 0.6, 0.9), (0.95, 0.45, 0.75), (1.45, 0.3, 0.6)):
        s.lathe([(radius, base), (0, base + height)], sides=12)
    return s


def person():
    s = Shape()
    for x in (-0.1, 0.1):
        s.box((x, 0.44, 0), (0.13, 0.88, 0.15))
    s.box((0, 1.17, 0), (0.4, 0.58, 0.22))
    for x in (-0.25, 0.25):
        s.box((x, 1.1, 0), (0.09, 0.62, 0.11))
    s.cylinder((0, 1.46, 0), 0.05, 0.08, 8)
    return s.sphere((0, 1.65, 0), 0.11, 6, 10, 1.15)


def car():
    s = Shape().box((0, 0.5, 0), (1.85, 0.5, 4.4))
    s.box((0, 0.98, -0.25), (1.6, 0.46, 2.2))
    for x in (-0.86, 0.86):
        for z in (-1.35, 1.4):
            s.cylinder((x - 0.11, 0.34, z), 0.34, 0.22, 14, axis='x')
    return s


def door():
    s = Shape().box((0, 1.02, 0), (0.86, 2.04, 0.04))
    s.box((-0.47, 1.06, 0), (0.08, 2.12, 0.12)).box((0.47, 1.06, 0), (0.08, 2.12, 0.12)).box((0, 2.08, 0), (1.02, 0.08, 0.12))
    return s.cylinder((0.33, 1.0, 0.02), 0.025, 0.09, 8, axis='z')


def window():
    s = Shape()
    for x in (-0.6, 0, 0.6):
        s.box((x, 0.6, 0), (0.06, 1.2, 0.08))
    for y in (0.03, 0.6, 1.17):
        s.box((0, y, 0), (1.26, 0.06, 0.08))
    return s.box((0, 0.6, 0), (1.14, 1.08, 0.01))


def screen():
    s = Shape().box((0, 0.5, 0), (1.0, 0.6, 0.05)).box((0, 0.1, 0), (0.06, 0.2, 0.05))
    return s.box((0, 0.01, 0), (0.35, 0.02, 0.22))


def barrel():
    return Shape().lathe([(0, 0), (0.27, 0), (0.3, 0.2), (0.31, 0.43), (0.3, 0.66), (0.27, 0.86), (0, 0.86)], sides=16)


def rock():
    s = Shape().sphere((0, 0.3, 0), 0.4, 5, 9, 0.75)
    # Each point pushed in or out a little, the same every time: a stone, not a ball.
    s.points = [(x * (1 + 0.12 * math.sin(3.1 * i)), y * (1 + 0.1 * math.cos(2.3 * i)), z * (1 + 0.12 * math.sin(1.7 * i + 1)))
                for i, (x, y, z) in enumerate(s.points)]
    return s


def box():
    return Shape().box((0, 0.5, 0), (1, 1, 1))


def ball():
    return Shape().sphere((0, 0.5, 0), 0.5, 8, 14)


def column():
    return Shape().cylinder((0, 0, 0), 0.5, 1.0, 16)


# Name, maker, words a linked mesh's name is matched by (whole words or parts of camelCase/underscored names).
STANDINS = (
    ('Box', box, ['box', 'crate', 'cube', 'carton', 'block']),
    ('Ball', ball, ['ball', 'sphere', 'globe', 'orb']),
    ('Column', column, ['column', 'pillar', 'cylinder', 'post', 'pole', 'can', 'tube', 'pipe']),
    ('Chair', chair, ['chair', 'seat', 'armchair']),
    ('Stool', stool, ['stool']),
    ('Table', table, ['table', 'desk', 'bench']),
    ('Sofa', sofa, ['sofa', 'couch', 'settee']),
    ('Bed', bed, ['bed', 'mattress']),
    ('Bookshelf', shelf, ['shelf', 'shelves', 'bookcase', 'bookshelf', 'rack']),
    ('Cabinet', cabinet, ['cabinet', 'cupboard', 'drawer', 'drawers', 'dresser', 'wardrobe', 'closet', 'sideboard', 'fridge']),
    ('Floor lamp', floor_lamp, ['floorlamp', 'lamp', 'light', 'lantern']),
    ('Table lamp', table_lamp, ['tablelamp', 'desklamp', 'nightlight']),
    ('Bottle', bottle, ['bottle', 'wine', 'beer', 'flask']),
    ('Mug', mug, ['mug', 'cup']),
    ('Vase', vase, ['vase', 'jar', 'urn']),
    ('Potted plant', plant, ['plant', 'pot', 'flower', 'fern', 'succulent', 'bush', 'shrub']),
    ('Tree', tree, ['tree', 'oak', 'maple', 'palm']),
    ('Pine', pine, ['pine', 'fir', 'spruce', 'conifer', 'christmas']),
    ('Person', person, ['person', 'human', 'man', 'woman', 'character', 'body', 'figure', 'girl', 'boy', 'people', 'mannequin']),
    ('Car', car, ['car', 'vehicle', 'truck', 'van', 'suv', 'sedan', 'auto', 'lambo', 'lamborghini', 'ferrari', 'porsche', 'taxi']),
    ('Door', door, ['door', 'gate']),
    ('Window', window, ['window', 'pane']),
    ('Screen', screen, ['tv', 'television', 'monitor', 'screen', 'display']),
    ('Barrel', barrel, ['barrel', 'drum', 'keg']),
    ('Rock', rock, ['rock', 'stone', 'boulder', 'pebble']),
)


def write(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    catalog = []
    for name, make, words in STANDINS:
        points, faces, size = make().fitted()
        file_name = name.replace(' ', '_').lower() + '.obj'
        lines = ['# MoonRay for Modo stand-in: %s (Links panel). The kit\'s own work, under the kit\'s licence.' % name,
                 '# Fitted to a unit box: x and z -0.5 to 0.5, y 0 to 1. Proportions as made: %s' % ' x '.join('%.3g' % s for s in size),
                 'o %s' % name]
        lines += ['v %.5f %.5f %.5f' % p for p in points]
        lines += ['f ' + ' '.join(str(i + 1) for i in face) for face in faces]
        (folder / file_name).write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        catalog.append({'name': name, 'file': file_name, 'words': words, 'polygons': len(faces), 'points': len(points),
                        'proportions': [round(s, 3) for s in size]})
    (folder / 'standins.json').write_text(json.dumps({'standins': catalog}, indent=1) + '\n', encoding='utf-8', newline='\n')
    (folder / 'CREDITS.txt').write_text('Stand-ins for the Links panel: low-res everyday objects a linked mesh is drawn as in '
                                        "Modo's viewport. Made by tools/make_standins.py; the kit's own work, under the kit's "
                                        'licence.\n', encoding='utf-8', newline='\n')
    return catalog


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/assets/library/standins'
    made = write(target)
    print('%d stand-ins in %s, %d polygons at most' % (len(made), target, max(s['polygons'] for s in made)))
