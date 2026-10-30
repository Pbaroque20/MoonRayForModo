"""Modo's render cache read again for the edited meshes alone (evaluated.capture with only and before): the other
surfaces' prototypes are taken from the reading before by their item, material and part, and where one is not there
to take, the cache is read whole."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated


def reading(prototypes):
    return {'surfaces': [{'id': int(key), 'source_id': int(key)} for key in prototypes], 'prototypes': prototypes}


class Adapter:
    """Writes what it is given to write, and says which call it was."""
    def __init__(self, some, whole):
        self.calls = []
        adapter = self

        def write(text, out):
            pathlib.Path(out.decode('utf-8')).write_text(json.dumps(text), encoding='utf-8')

        def merged(time, displaced, out, rows):
            adapter.calls.append('whole')
            pathlib.Path(rows.decode('utf-8')).write_bytes(b'')
            write(whole, out)

        def partial(time, displaced, out, rows, only):
            adapter.calls.append(('some', only.decode('utf-8')))
            pathlib.Path(rows.decode('utf-8')).write_bytes(b'')
            write(some, out)
        self.MR_geometry_snapshot_merged = merged
        self.MR_geometry_snapshot_some = partial


class Some(unittest.TestCase):
    def setUp(self):
        self.held = evaluated._bridge

    def tearDown(self):
        evaluated._bridge = self.held

    def test_kept_surfaces_come_from_the_reading_before(self):
        table = {'item': 'table', 'material': 'wood', 'part': '', 'segments': [], 'features': []}
        chair = {'item': 'chair', 'material': 'cloth', 'part': '', 'segments': [], 'features': []}
        before = reading({'1': table, '2': chair})
        edited = {'item': 'table', 'material': 'wood', 'part': '', 'segments': [], 'features': [], 'new': True}
        evaluated._bridge = Adapter(reading({'7': edited, '8': {'kept': 1, 'item': 'chair', 'material': 'cloth', 'part': ''}}), None)
        data = evaluated.capture(0.0, only={'table'}, before=before)
        self.assertEqual(evaluated._bridge.calls, [('some', 'table')])
        self.assertIs(data['prototypes']['8'], chair)
        self.assertTrue(data['prototypes']['7']['new'])

    def test_a_surface_not_there_to_take_reads_the_cache_whole(self):
        before = reading({'1': {'item': 'table', 'material': 'wood', 'part': '', 'segments': [], 'features': []}})
        whole = reading({'5': {'item': 'lamp', 'material': 'metal', 'part': '', 'segments': [], 'features': []}})
        evaluated._bridge = Adapter(reading({'5': {'kept': 1, 'item': 'lamp', 'material': 'metal', 'part': ''}}), whole)
        data = evaluated.capture(0.0, only={'table'}, before=before)
        self.assertEqual(evaluated._bridge.calls, [('some', 'table'), 'whole'])
        self.assertEqual(data['prototypes']['5']['item'], 'lamp')
        self.assertNotIn('kept', data['prototypes']['5'])


if __name__ == '__main__':
    unittest.main()
