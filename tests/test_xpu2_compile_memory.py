"""The shader compile's memory meter in the Shaders preferences: free RAM against the compile guard's thresholds. No Modo."""
import unittest
from test_xpu2_compile_button import load

GB = 1024.0 ** 3


class CompileMemory(unittest.TestCase):
    def setUp(self):
        self.module = load()

    def reading(self, total, free, **kw):
        return self.module.memory_reading(total * GB, free * GB, **kw)

    def test_enough(self):
        level, text = self.reading(64, 40)
        self.assertEqual(level, 0)
        self.assertTrue(text.startswith('40.0 GB free of 64 GB: enough'), text)

    def test_tight_between_need_and_peak(self):
        # 64 GB machine: floor 3.2 GB, so under 11 + 3.2 free is tight, from 8 free on.
        self.assertEqual(self.reading(64, 9)[0], 1)
        self.assertEqual(self.reading(64, 14)[0], 1)
        self.assertEqual(self.reading(64, 14.5)[0], 0)

    def test_not_enough_under_need(self):
        level, text = self.reading(64, 7.9)
        self.assertEqual(level, 2)
        self.assertIn('close other programs', text)

    def test_small_machine(self):
        level, text = self.reading(8, 7)
        self.assertEqual(level, 2)
        self.assertIn('too little RAM', text)

    def test_measured_peak_from_log(self):
        lines = ['MoonRay XPU2 shaders: compiled in 480 s (memory at most 4.2 GB, the machine\'s least free 30.1 GB)']
        self.assertAlmostEqual(self.module._measured_peak(lines), 4.2)
        self.assertIsNone(self.module._measured_peak(['nothing']))

    def test_reads_this_machine(self):
        text = self.module.memory_state()
        self.assertIn('GB free of', text)


if __name__ == '__main__':
    unittest.main()
