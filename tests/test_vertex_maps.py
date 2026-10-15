"""Modo's weight and colour vertex maps as values a MoonRay shape carries for its materials: a value at each point
(MoonRay's rate 4) or at each corner of each face (rate 6). No Modo or renderer launch."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla


def quad(**extra):
    mesh = {'name': 'Quad', 'identity': 'quad', 'matrix': rdla.IDENTITY, 'material': '',
            'vertices': [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [3, -1, 0], [3, 1, 0]],
            'faces': [[0, 1, 2, 3], [1, 4, 5, 2]], 'face_materials': ['', '']}
    mesh.update(extra)
    return {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36}, 'materials': {'': {'color': [.5, .5, .5]}},
            'meshes': [mesh], 'lights': []}


def block(text, name):
    start = text.index('UserData("%s")' % name)
    return text[start:text.index('}', start)]


class VertexMapTests(unittest.TestCase):
    def test_point_maps_are_one_value_for_each_point(self):
        text = rdla.scene_text(quad(point_attributes={'Heat': {'kind': 'float', 'values': [[i / 10] for i in range(6)]},
                                                      'Paint': {'kind': 'color', 'values': [[1, 0, 0]] * 6}}))
        heat = block(text, '/modo/mesh/0/map/point_attributes/0')
        self.assertIn('["float_key"] = "Heat"', heat)
        self.assertIn('["rate"] = 4', heat)
        self.assertIn('["float_values_0"] = {0, 0.1, 0.2, 0.3, 0.4, 0.5', heat)
        paint = block(text, '/modo/mesh/0/map/point_attributes/1')
        self.assertIn('["color_key"] = "Paint"', paint)
        self.assertIn('Rgb(1, 0, 0)', paint)
        self.assertIn('UserData("/modo/mesh/0/map/point_attributes/0")', text[text.index('["primitive_attributes"]'):])

    def test_corner_maps_keep_each_face_its_own(self):
        corners = [[1, 0, 0]] * 4 + [[0, 0, 1]] * 4
        text = rdla.scene_text(quad(corner_attributes={'Faces': {'kind': 'color', 'values': corners}}))
        faces = block(text, '/modo/mesh/0/map/corner_attributes/0')
        self.assertIn('["rate"] = 6', faces)
        self.assertEqual(faces.count('Rgb(1, 0, 0)'), 4)
        self.assertEqual(faces.count('Rgb(0, 0, 1)'), 4)

    def test_counts_must_match(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            rdla.scene_text(quad(point_attributes={'Heat': {'kind': 'float', 'values': [[0]] * 5}}))

    def test_pieces_cut_their_own_values(self):
        mesh = quad(point_attributes={'Heat': {'kind': 'float', 'values': [[i] for i in range(6)]}},
                    corner_attributes={'Faces': {'kind': 'float', 'values': [[1]] * 4 + [[2]] * 4}},
                    face_materials=['', 'fog'])['meshes'][0]
        pieces = dict(rdla._pieces(mesh, ['fog']))
        second = pieces['fog']
        self.assertEqual(second['faces'], [[0, 1, 2, 3]])
        self.assertEqual(second['point_attributes']['Heat']['values'], [[1], [4], [5], [2]])
        self.assertEqual(second['corner_attributes']['Faces']['values'], [[2]] * 4)
        self.assertEqual(pieces[None]['corner_attributes']['Faces']['values'], [[1]] * 4)



class AttributeOutputTests(unittest.TestCase):
    def test_written_as_moonray_primitive_attribute_outputs(self):
        from moonray_modo import outputs
        scene = quad(point_attributes={'Heat': {'kind': 'float', 'values': [[0]] * 6}})
        scene['custom_aovs'] = [{'name': 'heat', 'kind': 'attribute', 'expression': 'Heat'},
                                {'name': 'paint', 'kind': 'attribute_color', 'expression': ' Paint '}]
        text = rdla.scene_text(scene, output_file='final.exr')
        heat = text[text.index('RenderOutput("/modo/aov/heat")'):]
        heat = heat[:heat.index('}')]
        self.assertIn('["result"] = 4', heat)
        self.assertIn('["primitive_attribute"] = "Heat"', heat)
        self.assertIn('["primitive_attribute_type"] = 0', heat)
        paint = text[text.index('RenderOutput("/modo/aov/paint")'):]
        self.assertIn('["primitive_attribute"] = "Paint"', paint[:paint.index('}')])
        self.assertIn('["primitive_attribute_type"] = 3', paint[:paint.index('}')])
        self.assertEqual(outputs.display_kind(scene, 'heat'), 'alpha')
        self.assertEqual(outputs.display_kind(scene, 'paint'), 'beauty')

    def test_a_name_is_needed(self):
        from moonray_modo import outputs
        with self.assertRaisesRegex(ValueError, 'name of the primitive attribute'):
            outputs.values([{'name': 'heat', 'kind': 'attribute', 'expression': ' '}])


if __name__ == '__main__':
    unittest.main()
