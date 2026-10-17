import copy
import struct
import unittest
from xpu2 import ray_image as r
from xpu2.shading_exchange import material_status
from xpu2.cuda_samples import checksum


class RayImageTests(unittest.TestCase):
    def test_nearest_sphere_and_secondary_visibility_control(self):
        origin, direction = (-.6, .65, 4.), (0., 0., -1.)
        hit = r.trace(origin, direction)
        self.assertEqual(hit[1], 0)
        self.assertAlmostEqual(hit[0], 3.55, places=5)
        self.assertEqual(r.trace(origin, direction, True)[1], 4)

    def test_inside_sphere_exit_and_miss(self):
        center = r.SPHERES[0][0]
        self.assertAlmostEqual(r.trace(center, (1., 0., 0.))[0], .65)
        self.assertIsNone(r.trace((0., 5., 4.), (0., 1., 0.)))

    def test_emitter_bounds_and_parallel_planes(self):
        hit = r.trace((0., 2., 0.), (0., 1., 0.))
        self.assertEqual(hit[1], 3)
        self.assertEqual(hit[5], (4., 3.5, 3.))
        self.assertIsNone(r.trace((5., 2., 0.), (0., 1., 0.)))

    def test_sampler_addresses_are_unique_and_cache_aware(self):
        records = [r.sample_state(i) for i in range(r.WIDTH*r.HEIGHT*r.SPP)]
        self.assertEqual(len(set(records)), len(records))
        for data in records:
            words = struct.unpack('<16I', data)
            self.assertEqual(checksum(data[:60]), words[15])
            self.assertEqual(words[5]-words[14], 6)
            self.assertIn(words[5], (1014, 1022))

    def test_surface_packets_expose_actual_geometry(self):
        state = r.shade_packet(r.sample_state(0), (0., 1., 0.), (0., 1., 0.), (.3, .2, .1))
        self.assertEqual(len(state), 208)
        self.assertEqual(material_status(state[80:176]), 0)
        self.assertEqual(struct.unpack_from('<3f', state, 88), (0., 1., 0.))
        self.assertEqual(struct.unpack_from('<4I', state, 160), (1, 1, 0, 0))

    def test_film_preserves_fixed_sample_order(self):
        samples = [(0., 0., 0.) for _ in range(r.WIDTH*r.HEIGHT*r.SPP)]
        samples[:4] = [(1., 2., 3.), (3., 4., 5.), (5., 6., 7.), (7., 8., 9.)]
        result = r.film(samples)
        self.assertEqual(struct.unpack('<3f', result[:12]), (4., 5., 6.))
        with self.assertRaises(ValueError): r.film(samples[:-1])
        samples[0] = (float('nan'), 0., 0.)
        with self.assertRaises(ValueError): r.film(samples)

    def test_comparison_detects_bits_events_coverage_and_missing_paths(self):
        base = (struct.pack('<3f', 0., 1., 2.), {'0:0': {'result': [1, 2]}}, {'emitter': 1})
        self.assertTrue(r.compare(base, base)['passed'])
        other = (struct.pack('<3f', -0., 1., 2.), base[1], base[2])
        self.assertFalse(r.compare(base, other)['passed'])
        self.assertEqual(r.compare(base, other)['different_rgb_components'], 1)
        altered = copy.deepcopy(base)
        altered[1]['0:0']['result'][0] = 3
        self.assertEqual(r.compare(base, altered)['different_path_events'], 1)
        self.assertFalse(r.compare(base, (base[0], {}, base[2]))['passed'])
        self.assertFalse(r.compare(base, (base[0], base[1], {'emitter': 0}))['passed'])

    def test_render_rejects_truncated_or_unresolved_shader_results(self):
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            r.render(lambda b, bounce: (b'', []))
        def declined(batch, bounce):
            return b''.join(row['input'] for row in batch), [v for row in batch for v in [1]+[0]*11]
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            r.render(declined)

    def test_invalid_and_zero_pdf_samples_terminate_without_secondary_rays(self):
        for invalid, pdf, counter in ((1, 1., 'invalid'), (0, 0., 'zero_pdf')):
            calls = []
            def dispatch(batch, bounce):
                calls.append(bounce)
                words = [0, 123, 0, 0, 0, 0x3f800000, 0, 0x3f800000, 0x3f800000, 0x3f800000,
                         struct.unpack('<I', struct.pack('<f', pdf))[0], invalid]
                return b''.join(row['input'] for row in batch), words*len(batch)
            image, records, coverage = r.render(dispatch)
            self.assertEqual(calls, [0])
            self.assertGreater(coverage[counter], 0)
            self.assertTrue(all(key.endswith(':0') for key in records))


if __name__ == '__main__': unittest.main()
