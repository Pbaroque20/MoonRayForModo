"""A native material's metallic setting must reach MoonRay."""
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import shader_library


class NativeMetal(unittest.TestCase):
    def test_metallic_is_bound_with_a_value_of_one(self):
        # MoonRay multiplies a bound map by the attribute's own value, and metallic's default is 0.
        lines = []
        material = {'native_shader': 'DwaBaseMaterial', 'native_parameters': {'metallic': 1.0, 'metallic_color': [.6, .2, 0.0]}}
        shader_library.emit(material, '/test/material', [0], lines, {})
        text = '\n'.join(lines)
        self.assertIn('["metallic"] = bind(OpMap("/test/material/limits/metallic/high"), 1)', text)
        self.assertIn('["metallic_color"] = bind(OpMap("/test/material/limits/metallic_color/high"), Rgb(1,1,1))', text)


if __name__ == '__main__':
    unittest.main()
