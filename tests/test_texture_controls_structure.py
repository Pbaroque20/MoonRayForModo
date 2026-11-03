"""A texture's corrections (gamma, brightness, contrast, Low Value, High Value) are the same nodes whatever their values:
a change of them is a value MoonRay's session takes as it is (scene_delta), not a new scene to load whole."""
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import texture_controls, scene_delta


def written(controls):
    lines = []

    def node(kind, attributes):
        name = '/n%d' % len(lines)
        lines.append('%s("%s") {' % (kind, name))
        lines.extend('  ["%s"] = %s,' % item for item in attributes.items())
        lines.append('}')
        return 'bind(%s("%s"))' % (kind, name)
    texture_controls.emit('bind(ImageMap("/i"))', controls, node, lambda v: repr(float(v)))
    return '\n'.join(lines) + '\n'


class Structure(unittest.TestCase):
    def test_a_change_of_any_correction_is_a_value(self):
        plain = written({'gamma': 1, 'brightness': 1, 'contrast': 1})
        for changed in ({'low': .2, 'high': .8}, {'gamma': 2.2}, {'brightness': 1.5}, {'contrast': .7}):
            text = written(dict({'gamma': 1, 'brightness': 1, 'contrast': 1}, **changed))
            self.assertEqual(len(text.splitlines()), len(plain.splitlines()), changed)
            self.assertIsNotNone(scene_delta.difference(plain, text), changed)

    def test_the_one_gain_and_offset_is_the_three_in_turn(self):
        controls = {'contrast': .7, 'brightness': 1.5, 'low': .2, 'high': .8}
        x = .3
        stepped = .7 * x + .5 * (1 - .7)
        stepped *= 1.5
        stepped = stepped * .6 + .2
        gain, offset = texture_controls.affine(controls)
        self.assertAlmostEqual(gain * x + offset, stepped)
        self.assertEqual(texture_controls.affine({}), (1, 0.0))


if __name__ == '__main__':
    unittest.main()
