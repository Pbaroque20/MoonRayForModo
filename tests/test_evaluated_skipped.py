"""Modo's fur in evaluated geometry: Modo gives its strands' pieces no corner indices (LXe_NOTAVAILABLE), so the
geometry adapter makes them from each point's place along its strand; a piece it still cannot read is left out and
counted, with a notice, rather than stopping the render. A fur's strands stand with their mesh, so moving an item
follows it without reading every mesh again."""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated, incremental

MATRIX = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1]


class Skipped(unittest.TestCase):
    def test_pieces_left_out_give_a_notice(self):
        warnings = []
        evaluated.meshes({'surfaces': [], 'prototypes': {}, 'skipped': 2}, {}, warnings)
        self.assertTrue(any('could not read' in w for w in warnings))

    def test_the_adapter_counts_rather_than_fails(self):
        source = (ROOT / 'native-modo/render_cache.cpp').read_text(encoding='utf-8')
        self.assertIn('LXe_NOTAVAILABLE', source)
        self.assertNotIn('check(segment.GetPolygonVertexInds', source)

    def test_fur_strands_are_made_from_their_points(self):
        source = (ROOT / 'native-modo/render_cache.cpp').read_text(encoding='utf-8')
        self.assertIn('LXiRENDERCACHE_GEOVERT_FUR', source)
        self.assertIn('perFace==2 && strands(', source)


class Stands(unittest.TestCase):
    def stands(self, extra):
        scene = mock.Mock()
        scene.items.return_value = []
        snapshot = {'meshes': [{'identity': 'mesh038|0', 'source_item': 'mesh038', 'matrix': MATRIX}], 'extra_geometry': extra}
        # The plugin's host module needs Modo; only where an item stands is asked of it.
        with mock.patch.dict(sys.modules, {'moonray_modo.host': mock.Mock(world_matrix=lambda item: MATRIX)}):
            return incremental.stands_with_items(scene, snapshot)

    def test_fur_with_its_mesh_stands_with_the_item(self):
        self.assertTrue(self.stands([{'kind': 'curves', 'source_item': 'mesh038', 'matrix': MATRIX}]))

    def test_fur_elsewhere_does_not(self):
        self.assertFalse(self.stands([{'kind': 'curves', 'source_item': 'mesh038', 'matrix': MATRIX[:12] + [5, 0, 0, 1]}]))

    def test_other_extra_geometry_does_not(self):
        self.assertFalse(self.stands([{'kind': 'vdb', 'matrix': MATRIX}]))


if __name__ == '__main__':
    unittest.main()
