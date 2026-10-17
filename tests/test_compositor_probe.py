"""The compositor's probe: each node's value at one pixel as the compositor program works it out, notes on the canvas,
and the pictures the probe reads buffers from."""
import array
import struct
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import compositor, compositor_probe


def graph(**nodes):
    return {'nodes': {identity: {'type': kind, 'parameters': held, 'inputs': inputs} for identity, (kind, held, inputs) in nodes.items()},
            'root': 'out'}


BUFFERS = {'beauty': (0.5, 0.25, 1.0), 'diffuse': (0.2, 0.1, 0.4)}


def sample(made, x=0, y=0, width=11, height=11):
    return compositor.sample(made, BUFFERS.get, x, y, width, height)


class Sample(unittest.TestCase):
    def test_a_grade_and_a_sum(self):
        made = graph(b=('input', {'buffer': 'beauty'}, {}), d=('input', {'buffer': 'diffuse'}, {}),
                     g=('grade', {'exposure': 1.0, 'tint': [1.0, 0.5, 1.0]}, {'image': 'd'}),
                     s=('sum', {}, {'in1': 'b', 'in2': 'g'}), out=('output', {}, {'image': 's'}))
        got = sample(made)
        for value, want in zip(got['g'], (0.4, 0.1, 0.8)):
            self.assertAlmostEqual(value, want)
        for value, want in zip(got['out'], (0.9, 0.35, 1.8)):
            self.assertAlmostEqual(value, want)

    def test_a_merge_with_its_mix_and_math(self):
        made = graph(b=('input', {'buffer': 'beauty'}, {}), d=('input', {'buffer': 'diffuse'}, {}),
                     m=('merge', {'mode': 'multiply', 'mix': 0.5}, {'a': 'b', 'b': 'd'}),
                     n=('math', {'operation': 'divide', 'value': 2.0}, {'image': 'm'}), out=('output', {}, {'image': 'n'}))
        got = sample(made)
        # a + (a*b - a) * 0.5, then halved.
        for value, a, b in zip(got['out'], BUFFERS['beauty'], BUFFERS['diffuse']):
            self.assertAlmostEqual(value, (a + (a * b - a) * 0.5) / 2.0)

    def test_a_ramp_and_a_vignette_follow_the_pixel(self):
        made = graph(r=('ramp', {'direction': 'left to right', 'start': [0, 0, 0], 'end': [1, 1, 1]}, {}),
                     v=('vignette', {'amount': 1.0, 'falloff': 1.0}, {'image': 'r'}), out=('output', {}, {'image': 'v'}))
        self.assertAlmostEqual(sample(made, x=5)['r'][0], 0.5)
        self.assertAlmostEqual(sample(made, x=5, y=5)['v'][0], 0.5)
        self.assertAlmostEqual(sample(made, x=0, y=5)['v'][0], 0.0)

    def test_what_needs_the_pixels_around_it_is_not_worked_out(self):
        made = graph(b=('input', {'buffer': 'beauty'}, {}), u=('blur', {'radius': 4.0}, {'image': 'b'}),
                     g=('grade', {}, {'image': 'u'}), out=('output', {}, {'image': 'g'}))
        got = sample(made)
        self.assertIsNotNone(got['b'])
        self.assertIsNone(got['u'])
        self.assertIsNone(got['g'])
        self.assertIsNone(got['out'])

    def test_a_buffer_that_cannot_be_read_is_unknown(self):
        made = graph(b=('input', {'buffer': 'missing'}, {}), out=('output', {}, {'image': 'b'}))
        self.assertIsNone(sample(made)['out'])


class Notes(unittest.TestCase):
    def test_a_note_is_kept_and_not_part_of_the_picture(self):
        made = graph(b=('input', {'buffer': 'beauty'}, {}), n=('note', {'text': 'key light too hot'}, {}), out=('output', {}, {'image': 'b'}))
        checked = compositor.validate(made)
        self.assertEqual(checked['nodes']['n']['parameters']['text'], 'key light too hot')
        self.assertEqual(compositor.buffers(made), ['beauty'])
        self.assertTrue(compositor.trivial(made))

    def test_nothing_is_wired_from_a_note(self):
        made = graph(n=('note', {'text': 'x'}, {}), g=('grade', {}, {'image': 'n'}), out=('output', {}, {'image': 'g'}))
        with self.assertRaises(ValueError):
            compositor.validate(made)

    def test_the_words_of_a_probe_note(self):
        text = compositor.probe_note([('Beauty', (0.5, 0.25, 1.0)), ('Blur', None)], 12, 34)
        self.assertEqual(text.splitlines(), ['Probe at 12, 34', 'Beauty: R 0.5000  G 0.2500  B 1.0000', 'Blur: needs the pixels around it'])


class Pictures(unittest.TestCase):
    def test_a_pfm_is_read_bottom_row_first(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'p.pfm'
            values = array.array('f', [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])   # two pixels, one row
            path.write_bytes(b'PF\n2 1\n-1.0\n' + values.tobytes())
            width, height, read = compositor_probe._read_pfm(path)
            self.assertEqual((width, height), (2, 1))
            self.assertAlmostEqual(read[3], 0.4)

    def test_a_buffer_in_memory_is_read_from_the_top(self):
        pixels = array.array('f', [1, 1, 1, 2, 2, 2]).tobytes()     # one column, two rows: bottom row first
        frame = {'linear': {'beauty': (1, 2, pixels)}}
        self.assertEqual(compositor_probe.value(frame, 'beauty', 0, 0), (2.0, 2.0, 2.0))
        self.assertEqual(compositor_probe.value(frame, 'beauty', 0, 1), (1.0, 1.0, 1.0))


if __name__ == '__main__':
    unittest.main()
