"""Keep Metallic Flakes (Render Settings > Denoising): with glitter in the scene, the render writes the light its flakes
reflect (a light path expression), and the denoiser is given the picture without it, that light on its own, and puts
half of it back as rendered, so that flakes a pixel or smaller keep their sparkle in place of a plastic sheen."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import denoising, rdla, scene_settings  # noqa: E402

GLITTER = {'native_shader': 'DwaBaseMaterial', 'native_parameters': {'show_glitter': True}}


class Steps(unittest.TestCase):
    def steps(self, flakes=True, fine=False, detail='some', alpha=False):
        with tempfile.TemporaryDirectory() as folder:
            runtime = pathlib.Path(folder)
            for name in ('denoise.exe', 'oiiotool.exe'):
                (runtime / name).write_bytes(b'')
            guides = {'albedo': 'a.exr', 'normal': 'n.exr'}
            if flakes:
                guides['flakes'] = 'flakes.exr'
            if fine:
                guides['fine'] = 'f.exr'
            return denoising.jobs(runtime, runtime / 'beauty.exr', runtime / 'result', 'optix', guides, detail, alpha=alpha)

    @staticmethod
    def denoiser_steps(steps):
        return [step for step in steps if pathlib.Path(step[0]).name == 'denoise.exe']

    def test_without_the_flakes_light_one_denoising_as_before(self):
        steps = self.steps(flakes=False)
        self.assertEqual(len(steps), 3)
        self.assertEqual(len(self.denoiser_steps(steps)), 1)

    def test_the_picture_without_its_flakes_and_the_flakes_are_denoised_apart(self):
        steps = self.steps()
        denoised = self.denoiser_steps(steps)
        self.assertEqual(len(denoised), 2)
        inputs = [step[1][step[1].index('-in') + 1] for step in denoised]
        # The flakes' light first made a picture of its own, and taken out of the rendered one.
        light = next(step for step in steps if 'flakes.exr' in step[1])
        self.assertIn(str(light[2]), inputs)
        rest = next(step for step in steps if str(light[2]) in step[1] and '--sub' in step[1])
        self.assertIn(str(rest[2]), inputs)
        # Each with the albedo and normal guides.
        for step in denoised:
            self.assertIn('a.exr', step[1])
            self.assertIn('n.exr', step[1])

    def test_half_the_flakes_light_goes_back_as_rendered(self):
        steps = self.steps()
        light = next(step for step in steps if 'flakes.exr' in step[1])[2]
        combine = next(step for step in steps if step[1].count('--add') == 2)
        args = combine[1]
        # The rendered light by FLAKES_KEPT, its denoised copy by the rest.
        at = args.index(str(light))
        self.assertEqual(args[args.index('--mulc', at) + 1], str(denoising.FLAKES_KEPT))
        self.assertEqual(float(args[len(args) - 1 - args[::-1].index('--mulc') + 1]), 1 - denoising.FLAKES_KEPT)
        self.assertEqual(denoising.FLAKES_KEPT, .5)
        # And the result is what the rest of the steps take as the denoised picture.
        self.assertTrue(str(combine[2]).endswith('.denoise-filtered.exr'))
        self.assertTrue(str(steps[-1][2]).endswith('.denoised.exr'))

    def test_every_step_writes_a_file_of_its_own(self):
        steps = self.steps(fine=True, alpha=True)
        outputs = [str(step[2]) for step in steps]
        self.assertEqual(len(outputs), len(set(outputs)))

    def test_with_fur_too_its_detail_goes_over_the_flakes_result(self):
        steps = self.steps(fine=True)
        self.assertEqual(len(self.denoiser_steps(steps)), 2)
        self.assertIn('f.exr', ' '.join(' '.join(step[1]) for step in steps))
        self.assertTrue(str(steps[-1][2]).endswith('.denoised.exr'))

    def test_alpha_is_kept(self):
        steps = self.steps(alpha=True)
        self.assertIn('--chappend', steps[-1][1])


class Setting(unittest.TestCase):
    def test_off_unless_said(self):
        self.assertFalse(denoising.settings({})['flakes'])
        self.assertIs(scene_settings.DEFAULTS['denoising']['flakes'], False)
        with self.assertRaises(ValueError):
            denoising.settings({'flakes': 'yes'})

    def test_in_the_denoising_group(self):
        group = next(entries for name, _, entries in scene_settings.GROUPS if name == 'Denoising')
        entry = next(e for e in group if e['key'] == 'denoise_flakes')
        self.assertEqual(entry['path'], ('denoising', 'flakes'))
        self.assertEqual(entry['label'], 'Keep Metallic Flakes')
        self.assertEqual(entry['kind'], 'bool')
        self.assertTrue(entry['tip'])

    def test_the_render_form_has_it(self):
        form = (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.render.denoise_flakes ?', form)
        command = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_render_settings.py').read_text(encoding='utf-8')
        self.assertIn("'denoise_flakes'", command)


class Glitter(unittest.TestCase):
    def test_glitter_is_found_where_a_material_can_hold_it(self):
        self.assertTrue(denoising.glittering({'paint': GLITTER}))
        self.assertTrue(denoising.glittering({'paint': {'material_stack': [{'color': [1, 1, 1]}, GLITTER]}}))
        self.assertTrue(denoising.glittering({'paint': {'node_graph': {'nodes': {'n': {'type': 'DwaMetalMaterial', 'parameters': {'show_glitter': True}}}}}}))
        self.assertTrue(denoising.glittering({'paint': {'native_dependencies': [GLITTER]}}))

    def test_no_glitter_no_flakes(self):
        self.assertFalse(denoising.glittering({'paint': {'native_shader': 'DwaBaseMaterial', 'native_parameters': {'show_glitter': False}}}))
        self.assertFalse(denoising.glittering({'paint': {'native_shader': 'UsdPreviewSurface', 'native_parameters': {'show_glitter': True}}}))
        self.assertFalse(denoising.glittering({}))
        self.assertFalse(denoising.glittering(None))

    def test_kept_only_when_asked_and_there_is_glitter(self):
        on = {'denoising': {'flakes': True}}
        self.assertTrue(denoising.keeps_flakes(dict(on, materials={'paint': GLITTER})))
        self.assertTrue(denoising.keeps_flakes(dict(on, materials={}, native_materials={'lib': GLITTER})))
        self.assertFalse(denoising.keeps_flakes(dict(on, materials={'paint': {'color': [1, 1, 1]}})))
        self.assertFalse(denoising.keeps_flakes({'denoising': {'flakes': False}, 'materials': {'paint': GLITTER}}))
        self.assertFalse(denoising.keeps_flakes({'materials': {'paint': GLITTER}}))


class SceneText(unittest.TestCase):
    def scene(self, guides):
        return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                'materials': {'': {'color': [.5, .5, .5]}}, 'meshes': [], 'lights': [], 'environments': [],
                '_denoise_guides': guides}

    def test_the_flakes_light_is_a_light_path_expression_of_the_glitter_lobes(self):
        text = rdla.scene_text(self.scene({'albedo': 'a.exr', 'normal': 'n.exr', 'flakes': 'k.exr'}), 64, 36, 1, 0.0, 'out.exr')
        block = text[text.index('RenderOutput("/modo/denoise/flakes")'):]
        block = block[:block.index('}')]
        self.assertIn('["result"] = 8', block)
        self.assertIn("C<R.'glitter'>", block)
        self.assertIn('k.exr', block)
        self.assertEqual(denoising.FLAKES_LPE, "C<R.'glitter'>.*[<L.>O]")

    def test_none_without_the_setting(self):
        text = rdla.scene_text(self.scene({'albedo': 'a.exr', 'normal': 'n.exr'}), 64, 36, 1, 0.0, 'out.exr')
        self.assertNotIn('/modo/denoise/flakes', text)
        self.assertIn('/modo/denoise/albedo', text)


if __name__ == '__main__':
    unittest.main()
