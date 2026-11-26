"""The kit's shadow catcher in MoonLightIPR (backplate.py; MoonRay's tools/port_shadow_catcher.py): the material record
carries MATERIAL_SHADOW_CATCHER, MATERIAL_CATCHER_MATTE and its strength (scene form 'Z'), which the session reads."""
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))

from moonray_modo import moonlightipr_materials as materials


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class ShadowCatcherRecordTests(unittest.TestCase):
    def record(self, **extra):
        return materials.Compiler().material(dict({'color': [.2, .4, .6], 'emission': [.2, .4, .6], 'roughness': 1.0}, **extra), 'ground')

    def test_plain_material_is_unchanged(self):
        plain = self.record()
        self.assertEqual(len(plain), 46 * 4 + 4 * 4)
        self.assertFalse(struct.unpack_from('<I', plain, 46 * 4)[0] & (materials.MATERIAL_SHADOW_CATCHER | materials.MATERIAL_CATCHER_MATTE))

    def test_catcher_flags_and_strength(self):
        caught = self.record(shadow_catcher={'strength': 0.7, 'matte': False})
        flags = struct.unpack_from('<I', caught, 46 * 4)[0]
        self.assertTrue(flags & materials.MATERIAL_SHADOW_CATCHER)
        self.assertFalse(flags & materials.MATERIAL_CATCHER_MATTE)
        self.assertEqual(len(caught), 46 * 4 + 4 * 4 + 4)
        self.assertAlmostEqual(struct.unpack_from('<f', caught, len(caught) - 4)[0], 0.7, places=6)
        matte = self.record(shadow_catcher={'strength': 3, 'matte': True})
        self.assertTrue(struct.unpack_from('<I', matte, 46 * 4)[0] & materials.MATERIAL_CATCHER_MATTE)
        self.assertEqual(struct.unpack_from('<f', matte, len(matte) - 4)[0], 1.0)

    def test_backplate_photo_reaches_moonlightipr_as_emission(self):
        # The card and the catcher's ground wear the photo as emission: MoonLightIPR reads the switch from
        # native_parameters, which are the graph root's (it showed neither, the card left out and the ground black).
        from moonray_modo import backplate
        for emissive, catcher, effects in ((True, False, {'lumiCol'}), (False, True, {'diffCol', 'lumiCol'})):
            made = backplate.plate_material('photo.jpg', emissive, catcher)
            self.assertTrue(made['native_parameters']['show_emission'])
            self.assertEqual(made['native_parameters'], made['node_graph']['nodes']['surface']['parameters'])
            self.assertEqual({layer['effect'] for layer in materials.graph_layers(made, lambda what: None)}, effects)

    def test_session_and_kernel_agree(self):
        self.assertEqual((materials.MATERIAL_SHADOW_CATCHER, materials.MATERIAL_CATCHER_MATTE), (1 << 18, 1 << 19))
        self.assertIn('MATERIAL_SHADOW_CATCHER = 1u << 18, MATERIAL_CATCHER_MATTE = 1u << 19', text('moonlightipr/src/device/shared.h'))
        loader = text('moonlightipr/session/scene_loader.cpp')
        self.assertIn('materialFlags & (1u << 18)', loader)
        self.assertIn('0x63534c4d', loader)
        self.assertIn("b'MLSc'", text('kit/MoonRayForModo/python/moonray_modo/moonlightipr_scene.py'))
        kernel = text('moonlightipr/src/device/kernel.cu')
        self.assertIn('catcherShare(', kernel)
        self.assertIn('MATERIAL_CATCHER_MATTE', kernel)


if __name__ == '__main__':
    unittest.main()
