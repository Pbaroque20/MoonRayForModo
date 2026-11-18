"""Group masks naming a Group of the Groups list are for its members only (mask_types.covered, mask_items). A report: a
material in a group masked to a Group went over every surface, as if the mask named nothing, while Modo put it on the
group's members alone. What Modo does is from its own render of tools/probe_cl_item_mask_kinds.py: a Group covers
its members and the members of the groups inside it, a Group Locator what is under it, and a plain Locator nothing (a
mask naming one is for every surface); a Group holding a plain Locator does not reach what is under the locator."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo.mask_types import covered, mask_items  # noqa: E402


class Graph:
    def __init__(self, items):
        self.items = items

    def forward(self):
        return list(self.items)


class Item:
    def __init__(self, ident, kind, parent=None, members=(), linked=()):
        self.id, self.type, self.kids = ident, kind, []
        self.members, self.linked = list(members), list(linked)
        if parent is not None:
            parent.kids.append(self)

    def children(self):
        return list(self.kids)

    def itemGraph(self, name):
        return Graph({'itemGroups': self.members, 'shadeLoc': self.linked}[name])


class Covered(unittest.TestCase):
    def test_group_covers_its_members_only(self):
        mesh, other = Item('mesh', 'mesh'), Item('other', 'mesh')
        group = Item('group', 'group', members=[mesh])
        self.assertIn('mesh', covered(group))
        self.assertNotIn('other', covered(group))

    def test_groups_inside_a_group(self):
        mesh = Item('mesh', 'mesh')
        outer = Item('outer', 'group')
        Item('inner', 'group', parent=outer, members=[mesh])
        self.assertIn('mesh', covered(outer))

    def test_group_locator_under_a_group(self):
        holder = Item('holder', 'groupLocator')
        Item('mesh', 'mesh', parent=holder)
        deeper = Item('deeper', 'groupLocator', parent=holder)
        Item('deep mesh', 'mesh', parent=deeper)
        group = Item('group', 'group', members=[holder])
        self.assertTrue({'mesh', 'deep mesh'} <= covered(group))

    def test_plain_locator_in_a_group_reaches_nothing_under_it(self):
        locator = Item('locator', 'locator')
        Item('mesh', 'mesh', parent=locator)
        group = Item('group', 'group', members=[locator])
        self.assertNotIn('mesh', covered(group))

    def test_a_group_in_itself_ends(self):
        group = Item('group', 'group')
        group.members.append(group)
        self.assertEqual(covered(group), {'group'})

    def test_kept_for_a_reading(self):
        group = Item('group', 'group', members=[Item('mesh', 'mesh')])
        cache = {}
        first = covered(group, cache)
        group.members.clear()
        self.assertIs(covered(group, cache), first)


class MaskItems(unittest.TestCase):
    def test_groups_count_and_plain_locators_do_not(self):
        group, locator, mesh = Item('group', 'group'), Item('locator', 'locator'), Item('mesh', 'mesh')
        mask = Item('mask', 'mask', linked=[group, locator, mesh])
        self.assertEqual([item.id for item in mask_items(mask)], ['group', 'mesh'])

    def test_only_a_plain_locator_is_for_every_surface(self):
        mask = Item('mask', 'mask', linked=[Item('locator', 'locator')])
        self.assertEqual(mask_items(mask), [])


if __name__ == '__main__':
    unittest.main()
