import pathlib
import struct
import sys
import unittest
from array import array

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, rdlb


def read_vl(data, at):
    """scene_rdl2's ValueContainerUtil::variableLengthDecoding, as MoonRay reads it."""
    value, shift = 0, 0
    while True:
        byte = data[at]
        at += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return value, at
        shift += 7


def read_int_list(data):
    count, at = read_vl(data, 0)
    values = []
    for _ in range(count):
        u, at = read_vl(data, at)
        values.append((u >> 1) ^ -(u & 1))
    return values, at


def read_text(data, at):
    size, at = read_vl(data, at)
    return data[at:at + size].decode('utf-8'), at + size


def scene():
    return {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36},
            'meshes': [{'name': 'quad', 'vertices': [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                        'faces': [[0, 1, 2, 3]], 'uvs': [[0, 0], [1, 0], [1, 1], [0, 1]], 'material': ''}]}


class RdlbTests(unittest.TestCase):
    def test_int_lists_read_back_as_moonray_reads_them(self):
        for values in ([], [0], [3, 4, 3], list(range(0, 300000, 7)), [rdlb.FIXED_LIMIT - 1, 5],
                       [-1, 2, -300], [rdlb.FIXED_LIMIT, 1]):
            encoded = rdlb.int_list(array('l', values) if all(-2**31 <= v < 2**31 for v in values) else values)
            decoded, end = read_int_list(encoded)
            self.assertEqual(decoded, values)
            self.assertEqual(end, len(encoded))

    def test_float_lists_hold_the_floats(self):
        encoded = rdlb.float_list([[0.5, 1.0, -2.0], [3.25, 0.0, 1e-3]], 3)
        count, at = read_vl(encoded, 0)
        self.assertEqual(count, 2)
        self.assertEqual(array('f', encoded[at:]).tolist(), array('f', [0.5, 1.0, -2.0, 3.25, 0.0, 1e-3]).tolist())

    def test_file_has_manifest_and_one_record_per_object(self):
        sink = rdlb.Sink()
        sink.object('RdlMeshGeometry', '/a').add(rdlb.INT_VECTOR, 'face_vertex_count', rdlb.int_list([4]))
        sink.object('RdlMeshGeometry', '/b').add(rdlb.VEC3F_VECTOR, 'vertex_list_0', rdlb.float_list([[1, 2, 3]], 3))
        data = sink.payload()
        manifest_size, payload_size = struct.unpack('>QQ', data[:16])
        self.assertEqual(16 + manifest_size + payload_size, len(data))
        manifest = data[16:16 + manifest_size]
        self.assertEqual(struct.unpack('<Q', manifest[:8])[0], manifest_size)
        count, at = read_vl(manifest, 8)
        self.assertEqual(count, 2)
        payload, offset = data[16 + manifest_size:], 0
        for name in ('/a', '/b'):
            kind, at = read_vl(manifest, at)
            size, at = read_vl(manifest, at)
            self.assertEqual(kind, rdlb.SCENE_OBJECT_2)
            record = payload[offset:offset + size]
            self.assertEqual(struct.unpack('<Q', record[:8])[0], size)
            klass, inner = read_text(record, 8)
            self.assertEqual((klass, read_text(record, inner)[0]), ('RdlMeshGeometry', name))
            self.assertEqual(record[-2:], b'\x00\x00')   # end of values, end of bindings
            offset += size
        self.assertEqual(offset, len(payload))

    def test_scene_geometry_goes_to_the_binary_file_while_collecting(self):
        text = rdla.scene_text(scene())
        self.assertIn('["vertex_list_0"]', text)
        self.assertIn('["uv_list"]', text)
        with rdlb.collecting() as sink:
            split = rdla.scene_text(scene())
        for attribute in ('vertex_list_0', 'vertices_by_index', 'face_vertex_count', 'uv_list'):
            self.assertNotIn('["%s"] =' % attribute, split)
            self.assertRegex(split, r'-- rdlb \["%s"\] [0-9a-f]{24}\n' % attribute)
        self.assertIn('RdlMeshGeometry("/modo/mesh/0")', split)
        held = sink.objects['/modo/mesh/0']
        self.assertEqual(held.klass, 'RdlMeshGeometry')
        names = [read_text(part, read_vl(part, 0)[1] + 1)[0] for part in held.parts]
        self.assertEqual(sorted(names), sorted(['vertex_list_0', 'vertices_by_index', 'face_vertex_count', 'uv_list']))
        self.assertIsNone(rdlb.active())


    def test_a_changed_list_in_the_binary_file_enters_the_delta_as_text(self):
        from moonray_modo.scene_delta import difference
        with rdlb.collecting() as before:
            old = rdla.scene_text(scene())
        moved = scene()
        moved['meshes'][0]['vertices'] = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]
        with rdlb.collecting() as after:
            new = rdla.scene_text(moved)
        with rdlb.collecting() as same:
            again = rdla.scene_text(scene())
        self.assertEqual(difference(old, again, same.text_of), '\n')
        delta = difference(old, new, after.text_of)
        self.assertIn('RdlMeshGeometry("/modo/mesh/0") {', delta)
        self.assertIn('["vertex_list_0"] = {Vec3(0, 0, 0), Vec3(2, 0, 0), Vec3(2, 2, 0), Vec3(0, 2, 0)},', delta)
        self.assertIsNone(difference(old, new))                      # without the lists' text: a full reload
        faces = scene()
        faces['meshes'][0]['faces'] = [[0, 1, 2], [0, 2, 3]]
        faces['meshes'][0]['uvs'] = [[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]]
        with rdlb.collecting() as split:
            other = rdla.scene_text(faces)
        self.assertIsNone(difference(old, other, split.text_of))    # new faces: a full reload, as in text


    def test_each_changed_list_is_its_own_mesh_s(self):
        from moonray_modo.scene_delta import difference
        def two():
            data = scene()
            other = dict(data['meshes'][0], name='other', vertices=[[5, 0, 0], [6, 0, 0], [6, 1, 0], [5, 1, 0]],
                         uvs=[[.5, .5], [.6, .5], [.6, .6], [.5, .6]])
            data['meshes'].append(other)
            return data
        with rdlb.collecting():
            old = rdla.scene_text(two())
        moved = two()
        moved['meshes'][0]['vertices'] = [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]]
        moved['meshes'][0]['uvs'] = [[0, 0], [.5, 0], [.5, .5], [0, .5]]
        with rdlb.collecting() as sink:
            new = rdla.scene_text(moved)
        delta = difference(old, new, sink.text_of)
        self.assertIn('Vec3(0, 0, 1), Vec3(1, 0, 1)', delta)        # the first mesh's own points
        self.assertIn('Vec2(0.5, 0), Vec2(0.5, 0.5)', delta)        # and its own UVs
        self.assertNotIn('Vec3(5, 0, 0)', delta)
        self.assertNotIn('Vec2(0.6, 0.5)', delta)
        self.assertNotIn('/modo/mesh/1', delta)


if __name__ == '__main__':
    unittest.main()
