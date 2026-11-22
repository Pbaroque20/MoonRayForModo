"""Only the weight and colour maps the scene reads go to the engines (vertex_maps.named_in, vertex_maps.read's names,
host.painted_wanted). A tester's rigged model carried dozens of weight maps that no material read; each went to MoonRay
as a value at every point or corner of its meshes, and MoonRay, its realtime and the machine slowed to a crawl."""
import os
import struct
import sys
import types
import unittest
from array import array
from pathlib import Path
from unittest import mock

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
from moonray_modo import vertex_maps  # noqa: E402

WEIGHT, RGBA = lx.symbol.i_VMAP_WEIGHT, lx.symbol.i_VMAP_RGBA
# A rigged arm's maps: bone weights nothing reads, a painted mask a material reads, and a colour map with alpha.
MAPS = [('Paint', RGBA, 3), ('Shoulder', WEIGHT, 1), ('Spine', WEIGHT, 2), ('Wear', WEIGHT, 4)]


class Mesh:
    def PointCount(self):
        return 500

    def __peekobj__(self):
        return 1


class Wanted(unittest.TestCase):
    def test_every_word_of_the_materials(self):
        materials = {'skin': {'material_stack': [{'layers': [{'vmap': 'Wear', 'kind': 'weight'}]}],
                              'node_graph': {'nodes': {'a': {'type': 'AttributeMap', 'parameters': {'primitive_attribute_name': 'Paint_alpha'}}}}}}
        found = vertex_maps.named_in(materials, {}, ['dirt'])
        self.assertTrue({'Wear', 'Paint_alpha', 'dirt', 'AttributeMap'} <= found)
        self.assertNotIn('Shoulder', found)

    def test_an_rgba_map_by_its_name_or_its_alpha(self):
        self.assertEqual([m[0] for m in vertex_maps.chosen(MAPS, {'Paint_alpha', 'Wear'})], ['Paint', 'Wear'])
        self.assertEqual([m[0] for m in vertex_maps.chosen(MAPS, {'Paint'})], ['Paint'])
        self.assertEqual(vertex_maps.chosen(MAPS, None), MAPS)
        self.assertEqual(vertex_maps.chosen(MAPS, {'Arm'}), [])

    def test_the_names_maps_go_under(self):
        with mock.patch.object(vertex_maps, 'listed', lambda mesh: MAPS):
            self.assertEqual(vertex_maps.names_of(Mesh()), ['Paint', 'Paint_alpha', 'Shoulder', 'Spine', 'Wear'])


class Reading(unittest.TestCase):
    def test_nothing_read_where_nothing_is_wanted(self):
        reader = mock.Mock(return_value={})
        with mock.patch.object(vertex_maps, 'listed', lambda mesh: MAPS), \
                mock.patch.object(vertex_maps, 'read_natively', reader), mock.patch.object(vertex_maps, 'read_by_python', reader):
            self.assertEqual(vertex_maps.read(Mesh(), set()), {})
            self.assertEqual(vertex_maps.read(Mesh(), {'Hand', 'skin'}), {})
        reader.assert_not_called()

    def test_the_names_reach_the_reader(self):
        reader = mock.Mock(return_value={'Wear': {'kind': 'float', 'points': []}})
        with mock.patch.object(vertex_maps, 'listed', lambda mesh: MAPS), mock.patch.object(vertex_maps, 'read_natively', reader):
            vertex_maps.read(Mesh(), {'Wear', 'skin'})
        self.assertEqual(reader.call_args[0][1], {'Wear', 'skin'})

    def test_every_map_read_without_names(self):
        reader = mock.Mock(return_value={})
        with mock.patch.object(vertex_maps, 'read_natively', reader):
            vertex_maps.read(Mesh())
        self.assertIsNone(reader.call_args[0][1])

    def test_an_older_adapter_reads_all_and_the_rest_are_let_go(self):
        def entry(name, kind, width, values):
            data = name.encode('utf-8')
            return struct.pack('<i', len(data)) + data + struct.pack('<3i', kind, width, 0) + array('f', values).tobytes()
        file = (b'MVM1' + struct.pack('<2i', 2, 1) + array('i', [3]).tobytes() + struct.pack('<i', 5)
                + entry('Paint', 1, 3, [.1] * 6) + entry('Paint_alpha', 0, 1, [.5, .5]) + entry('Shoulder', 0, 1, [1, 0])
                + entry('Spine', 0, 1, [0, 1]) + entry('Wear', 0, 1, [.2, .3]))

        def every(address, path):
            Path(path.decode('utf-8')).write_bytes(file)
            return None
        with mock.patch.object(vertex_maps, 'listed', lambda mesh: MAPS), \
                mock.patch.object(vertex_maps, '_library', lambda named=False: None if named else every):
            found = vertex_maps.read_natively(Mesh(), {'Paint_alpha', 'Wear'})
        self.assertEqual(sorted(found), ['Paint', 'Paint_alpha', 'Wear'])

    def test_the_adapter_reads_by_name(self):
        source = (ROOT / 'native-modo/vertex_maps.cpp').read_text(encoding='utf-8')
        self.assertIn('MR_vertex_maps_named(void* object, const char* path, const char* names)', source)
        self.assertIn("wanted->count(name + \"_alpha\")", source)


class SceneReading(unittest.TestCase):
    def source(self):
        return (ROOT / 'kit/MoonRayForModo/python/moonray_modo/host.py').read_text(encoding='utf-8')

    def test_only_wanted_maps_read(self):
        source = self.source()
        self.assertIn('wanted_maps = painted_wanted(result)', source)
        self.assertIn('painted = vertex_maps.read(mesh, wanted_maps)', source)
        self.assertIn("result['meshes'][-1]['_vertex_maps'] = map_names", source)
        # Primitive attribute outputs read maps by name too.
        self.assertIn("properties.scene_settings().get('custom_aovs')", source)

    def test_a_map_newly_read_has_its_mesh_read_again(self):
        # host.maps_newly_wanted, as it is written there, run on its own.
        source = self.source()
        start = source.index('def maps_newly_wanted(')
        code = source[start:source.index('\ndef ', start + 1)]
        space = {}
        exec(code, space)
        newly = space['maps_newly_wanted']
        meshes = [{'_vertex_maps': ['Shoulder', 'Wear'], 'point_attributes': {'Wear': {}}}, {'_vertex_maps': []}]
        self.assertFalse(newly({'Wear', 'skin'}, meshes))
        self.assertTrue(newly({'Wear', 'Shoulder'}, meshes))
        self.assertFalse(newly({'Elbow'}, meshes))
        self.assertIn('or maps_newly_wanted(painted_wanted(result), reuse_geometry[\'meshes\'])', source)


if __name__ == '__main__':
    unittest.main()
