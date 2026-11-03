"""A material node's long list of inputs in its groups, as the Properties panel has them (node_editor.port_rows): a folded
group shows only its connected inputs, so every wire keeps its socket; a kind in one group keeps its plain list."""
import ast
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / 'kit/MoonRayForModo/python/moonray_modo/node_editor.py'
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))


def port_rows(groups):
    # node_editor needs Qt; port_rows is taken from its source with grouped() given.
    tree = ast.parse(EDITOR.read_text(encoding='utf-8'))
    found = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'port_rows')
    space = {'grouped': lambda kind: groups}
    exec(compile(ast.Module(body=[found], type_ignores=[]), str(EDITOR), 'exec'), space)
    return space['port_rows']


GROUPS = [('albedo', ('Diffuse',)), ('roughness', ('Specular',)), ('ior', ('Specular',)), ('fuzz', ('Fuzz',)), ('fuzz_color', ('Fuzz',))]
PORTS = ['albedo', 'roughness', 'ior', 'fuzz', 'fuzz_color']


class Rows(unittest.TestCase):
    def test_a_folded_group_keeps_its_connected_inputs(self):
        rows = port_rows(GROUPS)('DwaBaseMaterial', PORTS, ['fuzz_color'], {'Fuzz', 'Specular'})
        self.assertEqual(rows, [('group', 'Diffuse', 0, 1), ('port', 'albedo'),
                                ('group', 'Specular', 0, 2),
                                ('group', 'Fuzz', 1, 2), ('port', 'fuzz_color')])

    def test_open_groups_show_every_input(self):
        rows = port_rows(GROUPS)('DwaBaseMaterial', PORTS, [], set())
        self.assertEqual([row[1] for row in rows if row[0] == 'port'], PORTS)

    def test_one_group_keeps_the_plain_list(self):
        self.assertIsNone(port_rows([(key, (None,)) for key in PORTS])('ImageMap', PORTS, [], set()))


if __name__ == '__main__':
    unittest.main()
