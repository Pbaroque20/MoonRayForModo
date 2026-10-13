import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import texture_controls


def channels(**held):
    return lambda item, name, default=None: held.get(name, default)


class LowAndHigh(unittest.TestCase):
    def test_left_as_they_are_nothing_is_added(self):
        controls = texture_controls.capture(None, channels())
        self.assertEqual(controls, {'gamma': 1.0, 'brightness': 1.0, 'contrast': 1.0})
        self.assertEqual(texture_controls.remap(controls), (1.0, 0.0))

    def test_set_they_are_a_gain_and_an_offset(self):
        controls = texture_controls.capture(None, channels(min=0.25, max=0.75))
        self.assertEqual(texture_controls.remap(controls), (0.5, 0.25))

    def test_low_over_high_turns_the_image_over(self):
        controls = texture_controls.capture(None, channels(min=1.0, max=0.0))
        gain, offset = texture_controls.remap(controls)
        self.assertEqual((offset, gain + offset), (1.0, 0.0))

    def test_the_moonray_graph_gets_one_more_node(self):
        made = []

        def node(kind, values):
            made.append((kind, values))
            return 'node%d' % len(made)
        texture_controls.emit('image', texture_controls.capture(None, channels(max=0.2)), node, str)
        self.assertEqual(made, [('ColorCorrectGainOffsetMap', {'input': 'image', 'gain': '0.2', 'offset': '0.0'})])


if __name__ == '__main__':
    unittest.main()
