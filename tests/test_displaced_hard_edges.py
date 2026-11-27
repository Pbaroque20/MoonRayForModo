"""The MoonRay Source Override "Displaced hard edges stay sharp" (MOONRAY_MODO_DISPLACED_HARD_EDGES): MoonRay drops a
displaced polygon mesh's normals and shades it smooth all over from its displaced shape, so a box's edges came out
round where Modo keeps them sharp. With it on, each corner where a point's faces disagreed as given gets a normal over
its own side (native-port/modo_hard_edges.h, in MoonRay's PolyMesh, XPU2's geometry library and MoonLightIPR's session),
the displacement itself unchanged; off, MoonRay as its source has it."""
import struct
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

for name in ('modo', 'lx', 'lxifc', 'lxu', 'lxu.utils'):
    sys.modules.setdefault(name, types.ModuleType(name))
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
sys.path.insert(0, str(ROOT / 'tests'))
from moonray_modo import moonlightipr_scene, native, rdla  # noqa: E402
from test_displacement_budget import displaced_scene  # noqa: E402

BOX = [[x, y, z] for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
FACES = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]


def text(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


class Switch(unittest.TestCase):
    def test_a_source_override_on_by_default(self):
        self.assertIn("'displaced_hard_edges': (True, bool)", text('kit/MoonRayForModo/python/moonray_modo/preferences.py'))
        self.assertIn("lx.bless(switch('displaced_hard_edges'),'moonray.pref.displacedHardEdges')", text('kit/MoonRayForModo/lxserv/moonray_preferences.py'))
        page = text('kit/MoonRayForModo/preferences.cfg')
        self.assertIn('cmd moonray.pref.displacedHardEdges ?', page)
        self.assertIn('Displaced hard edges stay sharp', page)
        # In the Source Overrides section, beside the others.
        self.assertLess(page.index('cmd moonray.pref.tiltShift ?'), page.index('cmd moonray.pref.displacedHardEdges ?'))

    def test_moonray_reads_it_as_it_starts(self):
        for on in (True, False):
            with mock.patch.object(native, 'displaced_hard_edges', return_value=on):
                self.assertEqual(native.environment(KIT)['MOONRAY_MODO_DISPLACED_HARD_EDGES'], '1' if on else '0')
                # A session started with it otherwise is started again.
                self.assertIn(on, native.source_switches())

    def test_unset_reads_as_on(self):
        header = text('native-port/modo_hard_edges.h')
        self.assertIn('std::getenv("MOONRAY_MODO_DISPLACED_HARD_EDGES")', header)
        self.assertIn("return !v || v[0] != '0';", header)


class Engines(unittest.TestCase):
    """One rule, written once (native-port/modo_hard_edges.h): MoonRay's copy is the port tool's, XPU2 includes it."""

    def test_moonray_patch(self):
        port = text('tools/port_displaced_hard_edges.py')
        self.assertIn("SHARED = ROOT / 'native-port/modo_hard_edges.h'", port)
        prim = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/geom/prim'
        if not (prim / 'PolyMesh.cc').is_file():
            self.skipTest('no MoonRay source tree here')
        self.assertEqual((prim / 'ModoHardEdges.h').read_text(encoding='utf-8'), text('native-port/modo_hard_edges.h'))
        for name in ('PolyMesh.h', 'PolyMesh.cc', 'QuadMesh.cc', 'TriMesh.cc'):
            self.assertIn('tools/port_displaced_hard_edges.py', (prim / name).read_text(encoding='utf-8'), name)
        # The corners' normals last in PolyMesh, after every member code built against MoonRay's layout reads.
        header = (prim / 'PolyMesh.h').read_text(encoding='utf-8')
        self.assertLess(header.index('mMotionBlurType;'), header.index('mModoCornerNormals;'))

    def test_xpu2_makes_them_itself(self):
        geom = text('xpu2/interactive/xpu2_geom.cc')
        self.assertIn('#include "../../native-port/modo_hard_edges.h"', geom)
        self.assertIn('modo_hard_edges::cornerNormals(', geom)
        self.assertIn('modo_hard_edges::on()', geom)
        # Its geometry library is built again when the rule changes.
        self.assertIn("'../../native-port/modo_hard_edges.h'", text('xpu2/interactive/build_session.py'))
        # A moving mesh's corners at both time steps.
        self.assertIn('if(s.normalKind==4&&!s.normals1.empty())m->normals1[3*k+j]=s.normals1[4*f+corner];', text('xpu2/interactive/cpu_scene.h'))

    def test_moonlightipr_session(self):
        loader = text('moonlightipr/session/scene_loader.cpp')
        self.assertIn('MESH_HARD_EDGES = 4096', loader)
        self.assertIn('0x65534c4d', loader)
        self.assertIn('hardEdgeVertices(indices, cornerKeys, vertexCount, pointOf, drawn)', loader)


class FlatMeshes(unittest.TestCase):
    """A displaced flat-shaded polygon mesh has no normals to tell its hard edges by: each polygon's own goes along."""

    def test_polygon_normals(self):
        made = rdla.polygon_normals(BOX, FACES)
        self.assertEqual(len(made), 24)
        self.assertEqual(made[0], [-1.0, 0.0, 0.0])
        self.assertEqual(made[4], [1.0, 0.0, 0.0])
        self.assertEqual(rdla.polygon_normals([[0, 0, 0]] * 3, [[0, 1, 2]]), [[0.0, 1.0, 0.0]] * 3)

    def test_written_for_moonray_only_with_the_override(self):
        scene = displaced_scene(smooth=False)
        with mock.patch.object(native, 'displaced_hard_edges', return_value=True):
            self.assertIn('normal_list', rdla.scene_text(scene, 64, 36, 1, 0.0))
        with mock.patch.object(native, 'displaced_hard_edges', return_value=False):
            self.assertNotIn('normal_list', rdla.scene_text(displaced_scene(smooth=False), 64, 36, 1, 0.0))

    def test_not_for_an_undisplaced_flat_mesh(self):
        scene = displaced_scene(smooth=False)
        scene['materials']['ground'] = {'color': [.5, .5, .5]}
        with mock.patch.object(native, 'displaced_hard_edges', return_value=True):
            self.assertNotIn('normal_list', rdla.scene_text(scene, 64, 36, 1, 0.0))


class MoonLightIPR(unittest.TestCase):
    """The session displaces each point once and splits the points at hard edges afterwards (MESH_HARD_EDGES)."""

    def box(self, **extra):
        normals = [n for n in rdla.polygon_normals(BOX, FACES)]
        return dict({'name': 'box', 'vertices': BOX, 'faces': FACES, 'normals': normals, 'smooth': True}, **extra)

    def test_welded_keeps_the_corners_as_keys(self):
        mesh = self.box()
        with mock.patch.object(native, 'displaced_hard_edges', return_value=True):
            made = moonlightipr_scene.welded(mesh)
        self.assertIsNone(made['normals'])
        self.assertIs(made['hard_keys'], mesh['normals'])
        with mock.patch.object(native, 'displaced_hard_edges', return_value=False):
            made = moonlightipr_scene.welded(mesh)
        self.assertIsNone(made['normals'])
        self.assertNotIn('hard_keys', made)

    def test_flat_mesh_shaded_by_its_polygons(self):
        mesh = dict(self.box(), normals=None, smooth=False)
        with mock.patch.object(native, 'displaced_hard_edges', return_value=True):
            made = moonlightipr_scene.welded(mesh)
        self.assertTrue(made['smooth'])
        self.assertEqual(made['hard_keys'], rdla.polygon_normals(BOX, FACES))
        with mock.patch.object(native, 'displaced_hard_edges', return_value=False):
            self.assertIs(moonlightipr_scene.welded(mesh), mesh)

    def test_subdivision_surfaces_unchanged(self):
        mesh = self.box(subdivision=True)
        with mock.patch.object(native, 'displaced_hard_edges', return_value=True):
            self.assertIs(moonlightipr_scene.welded(mesh), mesh)

    def test_payload_carries_each_triangle_corner(self):
        with mock.patch.object(native, 'displaced_hard_edges', return_value=True):
            mesh = moonlightipr_scene.welded(self.box())
        key, flags, payload, _ = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {})
        self.assertTrue(flags & moonlightipr_scene.MESH_HARD_EDGES)
        self.assertTrue(flags & moonlightipr_scene.MESH_SMOOTH)
        self.assertFalse(flags & moonlightipr_scene.MESH_HAS_NORMALS)
        vertices, triangles = struct.unpack('<2I', payload[:8])
        self.assertEqual((vertices, triangles), (8, 12))
        keys = struct.unpack('<%df' % (triangles * 9), payload[-triangles * 36:])
        # Each triangle's corners carry its polygon's normal: the first two triangles the first face's.
        self.assertEqual(keys[:9], (-1.0, 0.0, 0.0) * 3)
        self.assertEqual(keys[9:18], (-1.0, 0.0, 0.0) * 3)
        self.assertEqual(keys[18:21], (1.0, 0.0, 0.0))
        # Without the keys the same mesh is packed as before.
        plain = dict(mesh)
        del plain['hard_keys']
        _, plain_flags, plain_payload, _ = moonlightipr_scene.mesh_payload(plain, {'': 0}, {})
        self.assertFalse(plain_flags & moonlightipr_scene.MESH_HARD_EDGES)
        self.assertEqual(payload[:len(plain_payload)], plain_payload)
        self.assertEqual(len(payload), len(plain_payload) + triangles * 36)


if __name__ == '__main__':
    unittest.main()
