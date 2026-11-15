"""No kit module defines one top-level function or class twice: the second replaces the first without a word. On
2026-11-12 rdla's and MoonLightIPR's scene writers each got a wrapper named as the function it wraps, which replaced
it: their textures were converted one after another, and the scene's colour settings were not applied, for two days."""
import ast
import collections
import pathlib
import unittest

KIT = pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo'


class NoShadowedDefinitions(unittest.TestCase):
    def test_each_top_level_name_is_defined_once(self):
        found = []
        for path in sorted(list((KIT / 'python/moonray_modo').glob('*.py')) + list((KIT / 'lxserv').glob('*.py'))):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            names = collections.Counter(node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)))
            found += ['%s: %s' % (path.name, name) for name, count in names.items() if count > 1]
        self.assertEqual(found, [])

    def test_the_scene_writers_open_their_settings(self):
        rdla = (KIT / 'python/moonray_modo/rdla.py').read_text(encoding='utf-8')
        self.assertIn('return _configured_scene_text(', rdla)
        ipr = (KIT / 'python/moonray_modo/moonlightipr_scene.py').read_text(encoding='utf-8')
        self.assertIn('return _configured(', ipr)


if __name__ == '__main__':
    unittest.main()
