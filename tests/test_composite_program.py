import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import compositor


def graph(**nodes):
    return {'nodes': {key: {'type': kind, 'parameters': held, 'inputs': inputs, 'position': [0, 0]} for key, (kind, held, inputs) in nodes.items()},
            'root': 'out'}


class CompositeProgram(unittest.TestCase):
    """The steps the compositor program is given for a graph, as the plugin writes them."""

    def plan(self, built):
        with tempfile.TemporaryDirectory() as folder:
            steps, result = compositor.jobs(built, {'beauty': 'B.exr'}, {'beauty': 'beauty'}, folder, composite='modo_composite.exe')
            text = (pathlib.Path(folder) / 'composite.txt').read_text(encoding='utf-8').splitlines()
        return steps, result, text

    def test_a_blur_is_a_row_then_a_column_with_the_image_tools_kernel(self):
        steps, result, text = self.plan(graph(a=('input', {'buffer': 'beauty'}, {}), b=('blur', {'radius': 1.0}, {'image': 'a'}),
                                              out=('output', {}, {'image': 'b'})))
        kernel = [line for line in text if line.startswith('kernel')]
        self.assertEqual(len(kernel), 1)
        weights = [float(v) for v in kernel[0].split()[2:]]
        self.assertEqual(len(weights), 5)                       # a radius of 1: 4 pixels, made odd
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        self.assertEqual([line.split()[1] for line in text if line.startswith('step')], ['10', '11'])
        self.assertEqual(steps[0][0][:2], ['--no-autopremult', 'B.exr'])        # the buffer read by the image tool
        self.assertEqual(steps[1][0][:2], ['@run', 'modo_composite.exe'])       # then the program
        self.assertTrue(str(result).endswith('composite.exr'))                 # its picture made an EXR

    def test_the_image_tools_kernel_matches_what_was_measured(self):
        # tools/measure_oiiotool_ops.py: a 3x3 blur's middle row of a lit pixel is 0.1238102, 0.30116, 0.1238102.
        weights = compositor.gaussian_taps(3)
        self.assertAlmostEqual(weights[1] * weights[1], 0.30116, places=5)
        self.assertAlmostEqual(weights[0] * weights[1], 0.1238102, places=5)

    def test_a_merge_with_nothing_laid_over_is_what_is_beneath(self):
        steps, result, text = self.plan(graph(a=('input', {'buffer': 'beauty'}, {}), m=('merge', {'mode': 'add', 'mix': 1.0}, {'a': 'a'}),
                                              out=('output', {}, {'image': 'm'})))
        self.assertFalse([line for line in text if line.startswith('step')])
        self.assertTrue(text[-1].startswith('save 0 '))

    def test_a_graph_of_made_pictures_still_reads_a_buffer_for_its_size(self):
        steps, result, text = self.plan(graph(c=('constant', {'color': [0.1, 0.2, 0.3]}, {}), out=('output', {}, {'image': 'c'})))
        self.assertEqual(len([line for line in text if line.startswith('load')]), 1)
        self.assertEqual(text[0], 'size 0 0')

    def test_without_the_program_the_image_tool_does_it_as_before(self):
        built = graph(a=('input', {'buffer': 'beauty'}, {}), g=('invert', {}, {'image': 'a'}), out=('output', {}, {'image': 'g'}))
        with tempfile.TemporaryDirectory() as folder:
            steps, result = compositor.jobs(built, {'beauty': 'B.exr'}, {'beauty': 'beauty'}, folder)
        self.assertFalse(any(args[0] == '@run' for args, _ in steps))


if __name__ == '__main__':
    unittest.main()
