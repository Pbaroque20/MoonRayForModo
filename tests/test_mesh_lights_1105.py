"""Mesh lights in every engine (2026-11-05): checked against Modo's own renders (tools/probe_cl_mesh_light_modo.py) and
the preview window's engines (tools/probe_mesh_light_all_engines.py).

Modo lights from a Mesh Light only while its Prototype is shown, never renders the Prototype as a surface, and shines
and is seen from the polygons' front alone. MoonRay read a mesh light's faces in steps of one size, so n-gons, or quads
beside triangles, shone from the wrong triangles; and a mesh emitting by its Object controls got a copy of its geometry
that, in the binary scene file, held no points. MoonLightIPR shone from both faces."""
import math
import struct
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))
from moonray_modo import lighting, rdla, moonlightipr_scene  # noqa: E402


def host_helper(name):
    """One plain function of host.py, which itself needs Modo to import."""
    source = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
    found = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    space = {}
    exec(compile(ast.Module([found], []), 'host.py', 'exec'), space)
    return space[name]

OCTAGON = [[0.35 * math.cos(math.pi * k / 4), 0, 0.35 * math.sin(math.pi * k / 4)] for k in range(8)]


def mixed_shape():
    vertices = OCTAGON + [[0.5, 0, -0.3], [0.9, 0, -0.3], [0.9, 0, 0.3], [0.5, 0, 0.3], [1.0, 0, -0.3], [1.4, 0, 0.0], [1.0, 0, 0.3]]
    faces = [list(range(8)), [8, 9, 10, 11], [12, 13, 14]]
    return vertices, faces


def light(seen=True):
    vertices, faces = mixed_shape()
    shape = {'vertices': vertices, 'faces': faces, 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 2, 0, 1]}
    return {'kind': 'MeshLight', 'identity': 'meshLight1', 'name': 'Mesh Light', 'color': [1, 1, 1], 'intensity': 3.0,
            'matrix': shape['matrix'], 'shape': shape, 'area': 1.0, 'camera_visible': seen}


class FacesAsTriangles(unittest.TestCase):
    def test_every_face_cut_into_its_own_triangles(self):
        vertices, faces = mixed_shape()
        triangles = lighting.light_triangles(vertices, faces)
        self.assertEqual(len(triangles), 6 + 2 + 1)
        self.assertTrue(all(len(t) == 3 for t in triangles))
        # Each triangle is of one face's corners.
        for t in triangles:
            self.assertTrue(any(set(t) <= set(face) for face in faces), t)

    def test_a_modo_mesh_light_is_written_as_triangles(self):
        lines = []
        lighting.emit({'lights': [light()]}, [], 0, lines)
        text = '\n'.join(lines)
        counts = next(line for line in text.splitlines() if '["face_vertex_count"]' in line)
        self.assertNotIn('4', counts.split('=')[1].replace('3', ''))
        self.assertEqual(counts.count('3'), 9)

    def test_an_emitting_mesh_gets_its_own_points_and_triangles(self):
        vertices, faces = mixed_shape()
        data = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                'materials': {'': {'color': [.5, .5, .5]}}, 'lights': [], 'environments': [],
                'meshes': [{'name': 'Panel', 'identity': 'panel', 'vertices': vertices, 'faces': faces, 'material': ''}],
                'production': {'objects': {'panel': {'mesh_light': True, 'light_intensity': 3}}}}
        # Written as the preview and renders write it, the mesh's lists in the binary file (rdlb).
        from moonray_modo import rdlb
        with rdlb.collecting():
            text = rdla.scene_text(data)
        self.assertIn('-- rdlb ["vertex_list_0"]', text)
        block = text[text.index('  RdlMeshGeometry("/modo/meshLight/geometry/0") {'):]
        block = block[:block.index('  }')]
        self.assertIn('["vertex_list_0"] = {Vec3(', block)
        self.assertNotIn('-- rdlb', block)
        counts = next(line for line in block.splitlines() if '["face_vertex_count"]' in line)
        self.assertEqual(counts.split('=')[1].strip(' {},').replace(' ', '').split(','), ['3'] * 9)


class ModoRules(unittest.TestCase):
    def test_prototypes_left_out_of_the_meshes(self):
        meshes = [{'identity': 'proto|0|'}, {'identity': 'floor'}, {'identity': 'x', 'source_item': 'proto'}]
        without = host_helper('without_mesh_light_prototypes')
        self.assertEqual(without(meshes, {'proto'}), [{'identity': 'floor'}])
        self.assertIs(without(meshes, set()), meshes)

    def test_hidden_prototype_gives_no_light(self):
        source = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
        self.assertIn('if not render_visible(prototype):', source)
        self.assertIn("result['meshes']=without_mesh_light_prototypes(result['meshes'],mesh_light_prototypes(scene))", source)


class MoonLightIPRFront(unittest.TestCase):
    def test_modo_light_record_is_alone(self):
        for seen, word in ((True, 3), (False, 2)):
            distant, local = moonlightipr_scene.lights({'lights': [light(seen)]}, [])
            self.assertEqual(len(local), 1)
            # type, 20 floats, texture: the seen word follows.
            self.assertEqual(struct.unpack_from('<I', local[0], 4 + 80 + 4)[0], word)

    def test_an_emitting_mesh_is_a_surface(self):
        vertices, faces = mixed_shape()
        record = moonlightipr_scene.emitter({'name': 'Panel', 'vertices': vertices, 'faces': faces}, {'light_intensity': 1}, [])
        self.assertEqual(struct.unpack_from('<I', record, 4 + 80 + 4)[0], 1)

    def test_the_engine_shines_from_the_front(self):
        kernel = (ROOT / 'moonlightipr/src/device/kernel.cu').read_text(encoding='utf-8')
        self.assertIn('const float cosine = -dot(wi, n) / normalLength;', kernel)
        self.assertIn('const bool lightFront = hit.light >= 0 && dot(direction, hit.ng) < 0.0f;', kernel)
        self.assertIn('(lights[hit.light].pad & LIGHT_ALONE)', kernel)
        loader = (ROOT / 'moonlightipr/session/scene_loader.cpp').read_text(encoding='utf-8')
        self.assertIn('light.alone = (seen & 2u) != 0;', loader)


class MissingUVMapIsANotice(unittest.TestCase):
    """A tester's scene stopped with "Mesh Reifen_RL is missing UV values in map TireSidewall": a material's texture
    set up on another mesh's UV map, worn by a mesh without it. Now the render goes on and a notice says so."""

    def test_the_scene_reader_goes_on(self):
        source = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
        self.assertNotIn("is missing UV values in map", source)
        self.assertIn('face_uv = missing_uvs(uv_name, tag, len(face))', source)
        self.assertIn('uv_of(source_name) or missing_uvs(source_name, tag, len(face))', source)

    def test_the_render_cache_reader_goes_on(self):
        source = (KIT / 'moonray_modo/evaluated.py').read_text(encoding='utf-8')
        self.assertNotIn("raise ValueError('Evaluated mesh is missing UV map", source)
        found = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'missing_uv_map')
        space = {}
        exec(compile(ast.Module([found], []), 'evaluated.py', 'exec'), space)
        warnings = []
        space['missing_uv_map'](warnings, 'Reifen_RL', 'TireSidewall', 'Tire')
        space['missing_uv_map'](warnings, 'Reifen_RL', 'TireSidewall', 'Tire')
        self.assertEqual(len(warnings), 1)
        self.assertIn('Reifen_RL has no UV map TireSidewall, which material Tire reads', warnings[0])


if __name__ == '__main__':
    unittest.main()
