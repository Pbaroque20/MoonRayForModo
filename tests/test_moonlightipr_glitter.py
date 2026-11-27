"""MoonRay's glitter in MoonLightIPR: a Dwa material's metallic flakes are packed after its other records (MATERIAL_GLITTER,
scene form 'c'), read by the session, and drawn by FEATURE_IRIDESCENCE's kernels alone ("special paint lobes"), so that
the other kernels are as they were and the kit keeps its 128."""
import pathlib
import re
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))

from moonray_modo import moonlightipr_materials as materials


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


PAINT = {'albedo': [.02, .05, .25], 'roughness': .4, 'show_clearcoat': True, 'show_glitter': True, 'glitter': .8, 'glitter_space': 4,
         'glitter_seed': 7, 'glitter_size_A': .02, 'glitter_size_B': .03, 'glitter_density': 20.0, 'glitter_style_B_frequency': .5,
         'glitter_roughness_A': .06, 'glitter_color_A': [.8, .85, 1.0], 'glitter_color_B': [.6, .7, 1.0],
         'glitter_color_hue_variation': .2, 'glitter_layering_mode': 1, 'glitter_compensate_reference_space_deformation': False}


class GlitterRecordTests(unittest.TestCase):
    def native(self, shader, parameters):
        compiler = materials.Compiler()
        row = {'name': 'paint', 'shader': 'DwaBaseMaterial', 'color': [.5, .5, .5], 'roughness': .4, 'native_shader': shader,
               'native_parameters': parameters}
        return compiler.material({'material_stack': [row]}, 'paint'), compiler.warnings()

    def test_glitter_follows_the_record(self):
        plain, _ = self.native('DwaBaseMaterial', dict(PAINT, show_glitter=False))
        record, warnings = self.native('DwaBaseMaterial', PAINT)
        self.assertFalse(struct.unpack_from('<I', plain, 46 * 4)[0] & materials.MATERIAL_GLITTER)
        self.assertTrue(struct.unpack_from('<I', record, 46 * 4)[0] & materials.MATERIAL_GLITTER)
        self.assertEqual(len(record), len(plain) + 3 * 4 + 20 * 4)
        seed, space, switches = struct.unpack_from('<iII', record, len(plain))
        numbers = struct.unpack_from('<20f', record, len(plain) + 12)
        self.assertEqual((seed, space), (7, 4))
        self.assertEqual(switches, 2 | 4)   # bounces see the average; additive layering; no compensation
        self.assertAlmostEqual(numbers[0], .8, places=6)
        self.assertAlmostEqual(numbers[2], 20.0)
        # Style A: frequency, size, roughness, colour; then style B's; then the variation.
        self.assertAlmostEqual(numbers[6], .02, places=6)
        self.assertAlmostEqual(numbers[7], .06, places=6)
        self.assertAlmostEqual(numbers[11], .5, places=6)
        self.assertAlmostEqual(numbers[12], .03, places=6)
        self.assertAlmostEqual(numbers[17], .2, places=6)
        # Glitter is drawn now: no notice that it is left out.
        self.assertFalse([w for w in warnings if 'glitter' in w.lower()], warnings)

    def test_metal_and_off_switches(self):
        gold, _ = self.native('DwaMetalMaterial', {'metallic_color': [.6, .36, .07], 'show_glitter': True})
        self.assertTrue(struct.unpack_from('<I', gold, 46 * 4)[0] & materials.MATERIAL_GLITTER)
        none, _ = self.native('DwaBaseMaterial', dict(PAINT, glitter=0.0))
        self.assertFalse(struct.unpack_from('<I', none, 46 * 4)[0] & materials.MATERIAL_GLITTER)

    def test_unsupported_parts_are_noted(self):
        notes = []
        found = materials.glitter_surface(lambda key, missing: dict(PAINT, glitter_texture_A='flake.png', glitter_debug_mode=2).get(key, missing),
                                          notes.append)
        self.assertIsNotNone(found)
        self.assertIn('glitter flake textures, drawn as flat flakes', notes)
        self.assertIn("glitter's debug modes", notes)
        self.assertIsNone(materials.glitter_surface(lambda key, missing: PAINT.get(key, missing), notes.append, toon_highlight=True))
        self.assertIn('glitter on a toon highlight', notes)


class GlitterEngineTests(unittest.TestCase):
    def test_session_and_kernel_agree(self):
        self.assertEqual(materials.MATERIAL_GLITTER, 1 << 20)
        shared = text('moonlightipr/src/device/shared.h')
        self.assertIn('const unsigned MATERIAL_GLITTER = 1u << 20;', shared)
        loader = text('moonlightipr/session/scene_loader.cpp')
        self.assertIn('materialFlags & (1u << 20)', loader)
        self.assertIn('0x64534c4d', loader)
        self.assertIn("b'MLSd'", text('kit/MoonRayForModo/python/moonray_modo/moonlightipr_scene.py'))

    def test_glitter_shares_the_iridescence_kernels(self):
        shared = text('moonlightipr/src/device/shared.h')
        # No new feature bit: the 128 kernels stay.
        self.assertIn('FEATURE_IRIDESCENCE = 64, FEATURE_ALL = 127;', shared)
        self.assertIn('ALL = 128', text('tools/compile_moonlightipr_variants.py'))
        renderer = text('moonlightipr/src/renderer.cpp')
        self.assertIn('if (m.glitter && m.glitterMask > 0.0f && !m.hair && !m.volume) features |= FEATURE_IRIDESCENCE;', renderer)
        # What glitter adds to shared.h is hidden from the other kernels, whose globals it would otherwise change.
        guarded = shared[shared.index('#if !defined(ML_FEATURES) || (ML_FEATURES & 64u)'):]
        self.assertIn('struct DeviceGlitter', guarded)

    def test_glitter_code_is_in_its_kernels_alone(self):
        kernel = text('moonlightipr/src/device/kernel.cu')
        self.assertIn('#define ML_GLITTER_CODE ((ML_FEATURES & 64u) != 0u)', kernel)
        # Every function of glitter's and every use of its lobes is inside an ML_GLITTER_CODE block.
        depth, inside = 0, []
        stack = []
        for line in kernel.splitlines():
            stripped = line.strip()
            if stripped.startswith('#if'):
                stack.append('ML_GLITTER_CODE' in stripped)
            elif stripped.startswith('#endif'):
                stack.pop()
            elif any(stack) and stripped:
                inside.append(stripped)
            elif re.search(r'\bglitter(Lobes|Eval|Sample|Search|Here)\b|MATERIAL_GLITTER|GlitterLobes', stripped):
                self.fail('glitter code outside its kernels: ' + stripped)
        self.assertTrue(any('glitterSearch(' in line for line in inside))
        # The slower calls MoonLightIPR does without (__noinline__ made every render 12-20% slower).
        self.assertNotIn('__noinline__', kernel)

    def test_instancer_placements_are_marked(self):
        # MoonRay's object space for an instancer's placement is its reference mesh's, not the placement's: the kit marks
        # them in the instance record's top bit, which the session takes off its visibility.
        from moonray_modo import moonlightipr_scene as scene
        self.assertEqual(scene.INSTANCE_FROM_INSTANCER, 1 << 31)
        loader = text('moonlightipr/session/scene_loader.cpp')
        self.assertIn('instance.visibility &= ~(1u << 31);', loader)
        self.assertIn('glitter.instancers', text('moonlightipr/src/device/kernel.cu'))

    def test_rest_positions_only_where_reference_glitter_reads_them(self):
        # A deformed mesh's base points (MoonRay's ref_P) go with it where they differ from its points and rest is
        # asked for (a glitter material in reference space): other scenes' packed meshes are as they were.
        from moonray_modo import moonlightipr_scene as scene
        self.assertEqual((scene.MESH_HAS_REST, scene.PACKED_FORM), (2048, 4))
        rest = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        bent = {'name': 'Bent', 'vertices': [[0, 0, 0], [1, .2, 0], [0, 1.3, .1]], 'faces': [[0, 1, 2]],
                'point_attributes': {'ref_P': {'kind': 'vec3', 'values': rest}}}
        index = {'': 0}
        _, flags, payload, _ = scene.mesh_payload(bent, index, {}, rest=True)
        self.assertTrue(flags & scene.MESH_HAS_REST)
        self.assertEqual(struct.unpack_from('<9f', payload, len(payload) - 36), (0, 0, 0, 1, 0, 0, 0, 1, 0))
        _, plain_flags, plain, _ = scene.mesh_payload(bent, index, {}, rest=False)
        self.assertFalse(plain_flags & scene.MESH_HAS_REST)
        self.assertEqual(len(plain), len(payload) - 36)
        same = dict(bent, point_attributes={'ref_P': {'kind': 'vec3', 'values': bent['vertices']}})
        self.assertFalse(scene.mesh_payload(same, index, {}, rest=True)[1] & scene.MESH_HAS_REST)
        loader = text('moonlightipr/session/scene_loader.cpp')
        self.assertIn('MESH_HAS_REST = 2048', loader)
        self.assertIn('glitter.rests', text('moonlightipr/src/device/kernel.cu'))

    def test_keep_metallic_flakes_reaches_the_session(self):
        from moonray_modo import moonlightipr_scene as scene
        self.assertEqual(scene.SCENE_KEEP_FLAKES, 32)
        self.assertIn('renderer.setKeepFlakes((sceneFlags & SCENE_KEEP_FLAKES) != 0);', text('moonlightipr/session/scene_loader.cpp'))
        renderer = text('moonlightipr/src/renderer.cpp')
        from moonray_modo import denoising
        # Half of the flakes' light put back as rendered, as the kit's own split for MoonRay's renders.
        self.assertEqual(denoising.FLAKES_KEPT, .5)
        self.assertIn('static constexpr float FLAKES_KEPT = 0.5f;', renderer)

    def test_host_tables_follow_moonray(self):
        host = text('moonlightipr/src/glitter_host.h')
        self.assertIn('Random noise(0xbeadceef);', host)
        self.assertIn('std::shuffle(permutation.begin(), permutation.end(), noise);', host)
        self.assertIn('Random colours(std::uint64_t(std::int64_t(seed) + 100));', host)
        tables = text('moonlightipr/src/glitter_tables.h')
        self.assertIn('Copyright 2023-2024 DreamWorks Animation LLC', tables)
        self.assertEqual(tables.count('{1.000f') + tables.count('{0.897f'), 32)
        self.assertIn('glitter_tables.h', text('moonlightipr/NOTICE.md'))


if __name__ == '__main__':
    unittest.main()
