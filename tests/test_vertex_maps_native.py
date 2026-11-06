"""Vertex maps as the geometry adapter hands them over (native-modo/vertex_maps.cpp, vertex_maps._parse): the same
maps read() gave in Python, a point's values as a run (rows.Rows, rows.Singles for a number), a corner's as Corners;
for_faces and as_vectors on them as on lists, and a weight map written for MoonRay from its run."""
import struct
import sys
import types
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
lx = sys.modules['lx']
if not hasattr(lx, 'symbol'):
    lx.symbol = types.SimpleNamespace(i_VMAP_WEIGHT='WGHT', i_VMAP_RGB='RGB ', i_VMAP_RGBA='RGBA')
lxu = sys.modules['lxu']
if not hasattr(lxu, 'utils'):
    lxu.utils = types.ModuleType('lxu.utils')
    sys.modules['lxu.utils'] = lxu.utils
lxu.__path__ = getattr(lxu, '__path__', [])
from moonray_modo import rdla, rows, vertex_maps  # noqa: E402

COUNTS = [4, 3, 4]                  # three surface polygons
POINTS = 5


def entry(name, kind, width, apart, values):
    data = name.encode('utf-8')
    return struct.pack('<i', len(data)) + data + struct.pack('<3i', kind, width, apart) + array('f', values).tobytes()


def file_of(*entries):
    return (b'MVM1' + struct.pack('<2i', POINTS, len(COUNTS)) + array('i', COUNTS).tobytes() + struct.pack('<i', len(entries))
            + b''.join(entries))


# As Modo gives them: 32-bit floats.
HEAT = array('f', [.5, 1.5, 2.5, 3.5, 4.5]).tolist()
PAINT = array('f', [float(k) for k in range(3 * sum(COUNTS))]).tolist()
FLOW = array('f', [float(k) / 10 for k in range(3 * POINTS)]).tolist()


def made():
    return vertex_maps._parse(file_of(entry('Heat', 0, 1, 0, HEAT), entry('Paint', 1, 3, 1, PAINT), entry('Flow', 1, 3, 0, FLOW)))


def as_lists():
    paint = [[PAINT[3 * c:3 * c + 3] for c in range(s, s + n)] for s, n in ((0, 4), (4, 3), (7, 4))]
    return {'Heat': {'kind': 'float', 'points': [[v] for v in HEAT]},
            'Paint': {'kind': 'color', 'corners': paint},
            'Flow': {'kind': 'color', 'points': [FLOW[3 * p:3 * p + 3] for p in range(POINTS)]}}


def plain(maps):
    out = {}
    for name, held in maps.items():
        if 'points' in held:
            out[name] = (held['kind'], [list(v) for v in held['points']])
        else:
            out[name] = (held['kind'], [[list(v) for v in face] for face in held['corners']])
    return out


class Parsed(unittest.TestCase):
    def test_the_maps_as_python_read_them(self):
        maps = made()
        self.assertIsInstance(maps['Heat']['points'], rows.Singles)
        self.assertIsInstance(maps['Paint']['corners'], vertex_maps.Corners)
        self.assertEqual(plain(maps), plain(as_lists()))
        self.assertEqual(maps['Heat']['points'][2], [2.5])

    def test_short_file_is_refused(self):
        data = file_of(entry('Heat', 0, 1, 0, HEAT))
        with self.assertRaises(ValueError):
            vertex_maps._parse(data[:-4])

    def test_for_faces_all_some_and_none(self):
        for ordinals in ([0, 1, 2], [2, 0], [1], []):
            native = vertex_maps.for_faces(made(), ordinals)
            python = vertex_maps.for_faces(as_lists(), ordinals)
            with self.subTest(ordinals=ordinals):
                for a, b in zip(native, python):
                    self.assertEqual({k: (v['kind'], [list(x) for x in v['values']]) for k, v in a.items()},
                                     {k: (v['kind'], [list(x) for x in v['values']]) for k, v in b.items()})

    def test_every_polygon_keeps_the_run(self):
        maps = made()
        _, corners = vertex_maps.for_faces(maps, [0, 1, 2])
        self.assertIs(corners['Paint']['values'], maps['Paint']['corners'].values)

    def test_as_vectors(self):
        kinds = {'Flow': 'vec2', 'Paint': 'vec3'}
        native, python = vertex_maps.as_vectors(made(), kinds), vertex_maps.as_vectors(as_lists(), kinds)
        self.assertEqual(plain(native), plain(python))
        self.assertIsInstance(native['Flow']['points'], rows.Rows)
        self.assertEqual(native['Flow']['points'].width, 2)


class WrittenTheSame(unittest.TestCase):
    def scene(self, maps):
        points, corners = vertex_maps.for_faces(maps, [0, 1, 2])
        mesh = {'identity': 'q||', 'name': 'Q', 'vertices': [[float(p), 0.0, 0.0] for p in range(POINTS)],
                'faces': [[0, 1, 2, 3], [1, 2, 4], [0, 2, 3, 4]], 'material': '', 'matrix': rdla.IDENTITY,
                'point_attributes': points, 'corner_attributes': corners}
        return rdla.scene_text({'camera': {'matrix': rdla.IDENTITY, 'film_mm': 36, 'focal_mm': 50}, 'lights': [], 'materials': {}, 'meshes': [mesh]}, 16, 16)

    def test_scene_text(self):
        self.assertEqual(self.scene(made()), self.scene(as_lists()))

    def test_binary_scene(self):
        from moonray_modo import rdlb
        written = []
        for maps in (made(), as_lists()):
            with rdlb.collecting() as sink:
                text = self.scene(maps)
            written.append((text, sorted((name, o.bytes()) for name, o in sink.objects.items())))
        self.assertEqual(written[0], written[1])


class Singles(unittest.TestCase):
    def test_read_as_one_number_lists(self):
        held = rows.Singles(array('f', [1.0, 2.0]), 'x')
        self.assertEqual(list(held), [[1.0], [2.0]])
        self.assertEqual(held[1], [2.0])
        self.assertEqual(held, [[1.0], [2.0]])
        self.assertIs(rows.numbers(held, 1), held.data)
        import pickle
        self.assertEqual(pickle.loads(pickle.dumps(held)), held)


if __name__ == '__main__':
    unittest.main()
