"""Only the materials something rendered wears are read at a material edit and handed on (host.worn_tags): a hidden
mesh's materials and their images are left alone."""
import ast
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'kit/MoonRayForModo/python/moonray_modo/host.py'


def worn_tags():
    # host imports Modo; the function is taken from its source, as it stands alone.
    tree = ast.parse(HOST.read_text(encoding='utf-8'))
    found = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'worn_tags')
    import sys
    sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
    from moonray_modo import face_tags
    space = {'face_tags': face_tags}
    exec(compile(ast.Module(body=[found], type_ignores=[]), str(HOST), 'exec'), space)
    return space['worn_tags']


class Worn(unittest.TestCase):
    def test_meshes_extras_and_shapes_wear_their_tags(self):
        found = {'meshes': [{'material': 'body', 'face_materials': ['body', 'glass']}, {'material': 'chrome'}],
                 'extra_geometry': [{'kind': 'curves', 'material': 'fur'}],
                 'entities': [{'parameters': {'modo_material': 'shape'}}, {'parameters': {}}]}
        self.assertEqual(worn_tags()(found), {'', 'body', 'glass', 'chrome', 'fur', 'shape'})

    def test_the_base_material_is_always_worn(self):
        self.assertEqual(worn_tags()({}), {''})

    def test_the_reading_skips_and_prunes_the_unworn(self):
        source = HOST.read_text(encoding='utf-8')
        self.assertIn("if tag is None or (worn is not None and tag not in worn):", source)
        self.assertIn("result['materials'] = {tag: material for tag, material in result['materials'].items() if tag in worn}", source)


    def test_a_list_of_tags_is_made_a_set_once(self):
        import sys
        sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
        from moonray_modo import face_tags
        faces = ['body', 'glass', 'body']
        first = face_tags.worn({'face_materials': faces})
        self.assertEqual(first, {'body', 'glass'})
        self.assertIs(face_tags.worn({'face_materials': faces}), first)
        self.assertEqual(face_tags.worn({'face_materials': list(faces) + ['tyre']}), {'body', 'glass', 'tyre'})
        self.assertEqual(face_tags.worn({'material': 'chrome'}), {'chrome'})


if __name__ == '__main__':
    unittest.main()
