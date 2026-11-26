"""MoonLightIPR's scene-wide coordinate slots (64, form 'b'): layers each with its own repeat all get one, as a car's
Shader Tree needs (the Cobra's tyre sidewalls went untextured at 8); the ones past them are named in a notice; and an
image the card refuses is kept in the computer's memory, not left out."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))

from moonray_modo import moonlightipr_materials as materials


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class UvSlotTests(unittest.TestCase):
    def test_sixty_four_slots_everywhere(self):
        self.assertEqual(materials.UV_SLOTS, 64)
        self.assertIn('const unsigned UV_SLOTS = 64;', text('moonlightipr/src/device/shared.h'))
        header = text('moonlightipr/include/moonlightipr/moonlightipr.h')
        self.assertIn('const uint32_t UV_SLOT_COUNT = 64;', header)
        self.assertIn('uint32_t tangentSlot = 64;', header)
        self.assertIn('0x63534c4d', text('moonlightipr/session/scene_loader.cpp'))
        scene = text('kit/MoonRayForModo/python/moonray_modo/moonlightipr_scene.py')
        self.assertIn("b'MLSc'", scene)
        self.assertIn('PACKED_FORM = 4', scene)

    def test_sixty_four_coordinate_sets_get_slots(self):
        compiler = materials.Compiler()
        slots = [compiler.slot('modo_uv_test%02d' % i) for i in range(64)]
        self.assertEqual(slots, list(range(64)))
        self.assertIsNone(compiler.slot('one too many'))

    def test_notice_names_what_a_set_is(self):
        self.assertIn('64 texture coordinate sets', materials.SLOTS_NOTE)
        compiler = materials.Compiler()
        compiler.note(materials.SLOTS_NOTE, 'm64')
        self.assertTrue(compiler.warnings()[0].startswith('MoonLightIPR leaves out image layers past its 64 texture coordinate sets'))

    def test_refused_image_is_kept_in_memory(self):
        loader = text('moonlightipr/session/scene_loader.cpp')
        self.assertIn("kept whole in the computer's memory, the graphics card refusing it", loader)


if __name__ == '__main__':
    unittest.main()
