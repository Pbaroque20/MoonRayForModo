"""MoonShine -> Shader Tree (shader_tree_revert): which nodes of a converted graph the conversion made, a MoonRay
material's graph with them taken out, effect names written back in Modo's spelling, and the report. The Modo side (layers
put back, images loaded, a new layer from an added node, undo) is tools/probe_cl_shader_tree_revert.py's: on the round-3
scene every layer back as it was but for the opacity edited in the graph, a new layer from an added image node, the node
the Shader Tree cannot hold named; on the plain-materials scene all nine materials Modo materials again."""
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from unittest import mock  # noqa: E402

# Modo's modules stood in for while the module is imported only (sys.modules as it was afterwards).
_stubs = {name: types.ModuleType(name) for name in ('lx', 'modo', 'lxu', 'lxu.utils', 'lxu.object', 'lxu.command', 'lxifc')}
with mock.patch.dict(sys.modules, _stubs):
    from moonray_modo import shader_tree_revert as revert, shader_tree_transfer as transfer  # noqa: E402


def ours(layer):
    return {'type': 'modo_texture', 'parameters': {'kind': 'imageMap', 'file': 'C:/t/%s.png' % layer},
            transfer.NODE_KEY: {'layer': layer, 'role': 'texture'}}


def graph():
    return {'root': 'out', 'nodes': {
        'out': {'type': 'DwaBaseMaterial', 'inputs': {'albedo': 'st_a_texture', 'roughness': 'mine'}},
        'st_a_texture': ours('a'),
        'mine': {'type': 'ConstantScalarMap', 'inputs': {'input': 'st_a_texture'}}},
        transfer.META_KEY: {'profile': 'native', 'inputs': ['albedo']}}


class Graphs(unittest.TestCase):
    def test_the_conversions_nodes_are_told_from_the_users(self):
        g = graph()
        if not transfer.ours('st_a_texture', g['nodes']['st_a_texture']):
            self.skipTest('transfer.ours names nodes otherwise')
        self.assertEqual(set(revert.foreign(g)), {'mine'})

    def test_a_moonray_materials_graph_keeps_its_own_nodes(self):
        g = graph()
        if not transfer.ours('st_a_texture', g['nodes']['st_a_texture']):
            self.skipTest('transfer.ours names nodes otherwise')
        kept = revert.without_ours(g)
        self.assertEqual(set(kept['nodes']), {'out', 'mine'})
        self.assertNotIn('albedo', kept['nodes']['out']['inputs'])        # wired by the conversion
        self.assertEqual(kept['nodes']['out']['inputs']['roughness'], 'mine')
        self.assertEqual(kept['nodes']['mine']['inputs'], {})             # its wire to a removed node let go
        self.assertNotIn(transfer.META_KEY, kept)
        self.assertIn('st_a_texture', g['nodes'])                          # the graph given is not changed


class Effects(unittest.TestCase):
    def test_modo_names_for_the_kits_short_ones(self):
        self.assertEqual(revert.MODO_EFFECTS['diffCol'], 'diffColor')
        self.assertEqual(revert.MODO_EFFECTS['tranAmt'], 'tranAmount')
        self.assertNotIn('rough', revert.MODO_EFFECTS)                     # the same in both


class Reporting(unittest.TestCase):
    def test_nothing_to_revert_is_said(self):
        lines = revert.Report().lines()
        self.assertIn('Nothing to revert', lines[1])

    def test_what_was_done_is_said(self):
        report = revert.Report()
        report.materials.append('Wood')
        report.restored += ['Grain', 'Bump']
        report.added.append(('colour (2)', 'Wood'))
        report.dropped.append(('Wood', ['user_add']))
        lines = report.lines()
        self.assertTrue(lines[0].startswith('MoonShine -> Shader Tree: 1 material back to Modo materials, 2 layers back'))
        self.assertIn('New layer colour (2) on Wood, from a node added in the graph.', lines)
        self.assertIn('Wood: graph nodes the Shader Tree cannot hold, left out: user_add.', lines)
        self.assertIs(report.left, report.missing)                         # shader_tree_environment.put_back reports there


if __name__ == '__main__':
    unittest.main()
