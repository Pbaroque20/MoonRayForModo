"""An environment image flipped left to right (Horizontal Wrap -1, nothing else) is sent whole, mirrored, rather than
baked small with the layered environments. No Modo."""
import pathlib
import sys
import unittest

KIT = pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))

from moonray_modo import environments  # noqa: E402


class EnvironmentFlip(unittest.TestCase):
    def test_a_flip_alone(self):
        self.assertTrue(environments.flipped_across({'scale': [-1, 1], 'uv_matrix': [1, 0, 0, 0, 1, 0], 'rotation': 0}))
        self.assertTrue(environments.flipped_across({'scale': [-1.0, 1.0]}))

    def test_anything_more_is_baked_as_before(self):
        self.assertFalse(environments.flipped_across({'scale': [1, 1]}))
        self.assertFalse(environments.flipped_across({'scale': [-1, -1]}))
        self.assertFalse(environments.flipped_across({'scale': [2, 1]}))
        self.assertFalse(environments.flipped_across({'scale': [-1, 1], 'rotation': 0.5}))
        self.assertFalse(environments.flipped_across({'scale': [-1, 1], 'uv_matrix': [1, 0, 0.25, 0, 1, 0]}))

    def test_the_capture_mirrors_and_clears_the_transform(self):
        source = (KIT / 'moonray_modo/environments.py').read_text(encoding='utf-8')
        self.assertIn("scale=[1.0,1.0],transformed=False,mirrored_from=str(path.resolve())", source)
        self.assertIn("'--flop'", source)


if __name__ == '__main__':
    unittest.main()
