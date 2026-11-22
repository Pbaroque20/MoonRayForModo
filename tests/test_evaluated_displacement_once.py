"""Surfaces: Modo evaluated geometry, for MoonRay and XPU2, takes meshes Modo has already displaced (host.by_engine):
their materials' Displacement layers are in the geometry, and are not to be laid on again. evaluated.assign_materials
left them out of each material's own layers (collect's baked_effects) but not out of its material_stack, which rdla
reads, so MoonRay displaced the displaced meshes a second time (a tester's model with a UDIM displacement map)."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
from moonray_modo import layers  # noqa: E402

SOURCE = ROOT / 'kit/MoonRayForModo/python/moonray_modo'


class Item:
    def __init__(self, identity):
        self.id = identity
        self.type = 'advancedMaterial'


class MaterialStack(unittest.TestCase):
    def test_baked_effects_reach_collect(self):
        base = Item('material')
        scene = types.SimpleNamespace(renderItem=None)
        seen = []
        with mock.patch.object(layers, 'ordered', lambda root: [base]), \
                mock.patch.object(layers, 'collect', lambda *a, **k: seen.append(k.get('baked_effects'))), \
                mock.patch.object(layers, 'texture_groups', lambda item, channel: []), \
                mock.patch.object(layers, 'layer_mask_target', lambda layer, channel: None), \
                mock.patch.dict(sys.modules, {'moonray_modo.host': types.SimpleNamespace(
                    material_values=lambda item, warnings: {}, channel=lambda *a: None)}):
            layers.material_stack(scene, [base], [], 'tag', {'material'}, baked_effects=('displace',))
            layers.material_stack(scene, [base], [], 'tag', {'material'})
        self.assertEqual(seen, [('displace',), ()])

    def test_evaluated_stacks_leave_out_modos_displacement(self):
        source = (SOURCE / 'evaluated.py').read_text(encoding='utf-8')
        self.assertIn("baked=('displace',) if modo_displaces() else ()", source)
        self.assertIn('material_stack(where,candidates,warnings,tag,set(stack),baked_effects=baked)', source)


if __name__ == '__main__':
    unittest.main()
