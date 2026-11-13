"""The groups a material's inputs start with open are the same in Modo's form for it (material_forms.cfg, made by
tools/generate_material_item_forms.py) and in the graph editor's list (node_editor.default_folds): both from
form_groups, Diffuse and Specular, or a material's first group where it has neither."""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import form_groups  # noqa: E402

FORMS = (ROOT / 'kit/MoonRayForModo/material_forms.cfg').read_text(encoding='utf-8')


def form_open(shader):
    rows = re.findall(r'val="sub MoonRayShader_%s_\d+:sheet">\s*<atom type="Label">([^<]*)</atom>\s*<atom type="ShowLabel">1</atom>'
                      r'\s*<atom type="StartCollapsed">(\d)</atom>' % shader, FORMS)
    return {label for label, collapsed in rows if collapsed == '0'}, [label for label, _ in rows]


class FormGroups(unittest.TestCase):
    def test_dwabase_opens_diffuse_and_specular_in_its_form(self):
        opened, groups = form_open('DwaBaseMaterial')
        self.assertEqual(opened, {'Diffuse', 'Specular'})
        self.assertIn('Common', groups)

    def test_every_form_opens_what_the_rule_opens(self):
        shaders = set(re.findall(r'val="sub MoonRayShader_(\w+?)_\d+:sheet"', FORMS))
        self.assertGreater(len(shaders), 5)
        for shader in shaders:
            opened, groups = form_open(shader)
            with self.subTest(shader=shader):
                self.assertEqual(opened, form_groups.opened(groups))

    def test_the_editor_and_the_generator_use_it(self):
        self.assertIn('from moonray_modo.form_groups import opened', (ROOT / 'kit/MoonRayForModo/python/moonray_modo/node_editor.py').read_text(encoding='utf-8'))
        self.assertIn('from moonray_modo.form_groups import opened', (ROOT / 'tools/generate_material_item_forms.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
