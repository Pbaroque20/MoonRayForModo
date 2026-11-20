"""The Asset Library's stand-ins (standins.py, tools/make_standins.py): low-res everyday objects a linked mesh is drawn as
in Modo's viewport (the Links panel, links.py). Each fitted to the unit box, wound outward and light; a mesh's name finds
its stand-in; the library lists them as Proxy stand-ins; the files are what the maker makes."""
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
sys.path.insert(0, str(ROOT / 'tools'))
for _name in ('lx', 'lxu', 'lxifc', 'modo'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import asset_library, links, standins  # noqa: E402


def volume(points, faces):
    """The signed volume a closed mesh's polygons bound (fanned into triangles): positive where they face outward."""
    total = 0.0
    for face in faces:
        a = points[face[0]]
        for b, c in zip((points[i] for i in face[1:-1]), (points[i] for i in face[2:])):
            total += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return total


class Library(unittest.TestCase):
    def test_everyday_objects_light_and_fitted_to_the_unit_box(self):
        held = standins.catalog()
        names = [entry['name'] for entry in held]
        self.assertGreaterEqual(len(held), 20)
        for wanted in ('Box', 'Chair', 'Table', 'Sofa', 'Bed', 'Floor lamp', 'Bottle', 'Potted plant', 'Tree', 'Person', 'Car', 'Door'):
            self.assertIn(wanted, names)
        for entry in held:
            points, faces = standins.read(entry['file'])
            self.assertLessEqual(len(faces), 300, entry['name'])
            low = [min(p[k] for p in points) for k in range(3)]
            high = [max(p[k] for p in points) for k in range(3)]
            for got, want in zip(low + high, [-0.5, 0.0, -0.5, 0.5, 1.0, 0.5]):
                self.assertAlmostEqual(got, want, places=4, msg=entry['name'])
            for face in faces:
                self.assertGreaterEqual(len(face), 3)
                self.assertTrue(all(0 <= i < len(points) for i in face))

    def test_every_part_wound_outward(self):
        # A part wound inward takes its volume away: the whole stays positive, and the simple shapes bound what they are.
        for entry in standins.catalog():
            points, faces = standins.read(entry['file'])
            self.assertGreater(volume(points, faces), 0.0, entry['name'])
        box = standins.read(standins.find('Box')['file'])
        self.assertAlmostEqual(volume(*box), 1.0, places=6)
        column = standins.read(standins.find('Column')['file'])
        # A 16-sided prism in the unit box: 16 / (2 pi) sin(2 pi / 16) of the circle's area.
        self.assertAlmostEqual(volume(*column), 0.25 * 16 * 0.5 * __import__('math').sin(2 * 3.141592653589793 / 16), places=3)

    def test_the_files_are_what_the_maker_makes(self):
        import make_standins
        with tempfile.TemporaryDirectory() as held:
            make_standins.write(held)
            for made in sorted(pathlib.Path(held).iterdir()):
                kept = standins.folder() / made.name
                self.assertTrue(kept.is_file(), made.name)
                self.assertEqual(made.read_bytes(), kept.read_bytes(), made.name)

    def test_the_library_lists_them_as_proxy_stand_ins(self):
        found = [row for batch in asset_library.scan([asset_library.bundled()]) for row in batch
                 if row['category'] == asset_library.STANDIN_CATEGORY]
        self.assertEqual(len(found), len(standins.catalog()))
        self.assertIn('Floor lamp', [row['name'] for row in found])
        self.assertIn('Proxy stand-ins', (KIT / 'python/moonray_modo/asset_browser.py').read_text(encoding='utf-8'))


class Choosing(unittest.TestCase):
    def test_a_names_words(self):
        self.assertEqual(standins.words('OfficeChair_02'), ['office', 'chair'])
        self.assertEqual(standins.words('TV_Stand'), ['tv', 'stand'])
        self.assertIn('chair', standins.words('Chairs'))

    def test_a_mesh_by_its_name(self):
        for name, wanted in (('OfficeChair_02', 'Chair'), ('Table Lamp', 'Table lamp'), ('floor_lamp', 'Floor lamp'),
                             ('Lamborghini_body', 'Car'), ('BookShelf', 'Bookshelf'), ('Wine_Bottle', 'Bottle'),
                             ('pine_tree', 'Pine'), ('oak tree', 'Tree'), ('PottedPlant', 'Potted plant'), ('Cupboard', 'Cabinet'),
                             ('Character_Body', 'Person'), ('TV_Stand', 'Screen'), ('sofa3', 'Sofa'), ('Chairs', 'Chair')):
            self.assertEqual(standins.choose(name)['name'], wanted, name)

    def test_a_box_where_nothing_fits(self):
        for name in ('mesh027', 'carpet', 'Mesh', '', None, 'manhole'):
            self.assertEqual(standins.choose(name)['name'], 'Box', name)

    def test_stretched_to_a_meshs_bounds(self):
        placed = standins.fitted([(-0.5, 0.0, -0.5), (0.5, 1.0, 0.5), (0.0, 0.5, 0.0)], (2.0, -1.0, 4.0), (6.0, 1.0, 5.0))
        self.assertEqual(placed, [(2.0, -1.0, 4.0), (6.0, 1.0, 5.0), (4.0, 0.0, 4.5)])

    def test_what_link_is_given(self):
        self.assertEqual(links.standin_for('Office chair', 'auto'), 'Chair')
        self.assertEqual(links.standin_for('Office chair', 'Car'), 'Car')
        self.assertIsNone(links.standin_for('Office chair', 'none'))
        self.assertIsNone(links.standin_for('Office chair', ''))
        self.assertIsNone(links.standin_for('Office chair', 'No such thing'))


class Wiring(unittest.TestCase):
    def test_the_panel_offers_them(self):
        window = (KIT / 'python/moonray_modo/links_window.py').read_text(encoding='utf-8')
        self.assertIn("'Stand-in...'", window)
        self.assertIn('Link with stand-ins from the Asset Library', window)
        self.assertIn("'standin': 'auto' if self.with_standins.isChecked() else 'none'", window)
        self.assertIn('standin', links.ACTIONS)
        source = pathlib.Path(links.__file__).read_text(encoding='utf-8')
        # Drawn as its stand-in, rendered as itself.
        self.assertIn("!proxy.renderItem item:{%s} name:{%s}", source)
        self.assertIn("!proxy.previewItem item:{%s} name:{%s}", source)


if __name__ == '__main__':
    unittest.main()
