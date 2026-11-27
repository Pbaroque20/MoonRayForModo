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
        # 64 GB machine: floor 3.2 GB, so under 9 + 3.2 free is tight, from 8 free on.
        self.assertEqual(self.reading(64, 9)[0], 1)
        self.assertEqual(self.reading(64, 12)[0], 1)
        self.assertEqual(self.reading(64, 12.5)[0], 0)

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

    def test_low_memory_by_itself(self):
        low = lambda total, free, peak=None: self.module.compile_low_memory(total * GB, free * GB, peak)
        # The last whole compile's own peak, where it was larger.
        self.assertTrue(low(64, 22, 21.0))
        # Automatic: free RAM short of the whole compile's peak above the floor (9 GB + 2 or more) goes one module at a time...
        self.assertTrue(low(8, 6))
        self.assertTrue(low(16, 10))
        # ...and a machine with room does not.
        self.assertTrue(low(32, 6))
        self.assertFalse(low(16, 12))
        self.assertFalse(low(32, 25))
        self.assertFalse(low(64, 40))

    def test_automatic_goes_again_one_module_at_a_time(self):
        retry = self.module.retry_low
        whole = ['MoonRay XPU2 shaders: compiling', 'MoonRay XPU2 shaders: graphics card 0 (RTX)']
        self.assertTrue(retry(whole + ['MoonRay XPU2 shaders: stopped: memory ran low (1.9 GB free); the modules compiled so far are kept']))
        self.assertTrue(retry(['MoonRay XPU2 shaders: not compiled: not enough free memory (5.0 GB free of 8.0 GB)']))
        # Not a second time, and not after a compile that ended well.
        self.assertFalse(retry(whole + ['MoonRay XPU2 shaders: low memory: 10 modules, one at a time',
                                        'MoonRay XPU2 shaders: stopped: memory ran low (1.9 GB free)']))
        self.assertFalse(retry(whole + ['MoonRay XPU2 shaders: compiled in 900 s (memory at most 7.0 GB)']))

    def test_low_memory_reading_on_a_small_machine(self):
        m = self.module
        # 16 GB with 7 free: no whole compile at once, but enough one module at a time.
        level, text = self.reading(16, 7, need=m.LOW_NEED_GB, peak=m.LOW_PEAK_GB, low=True)
        self.assertLess(level, 2)
        self.assertIn('low memory', text)
        self.assertEqual(self.reading(16, 5, need=m.LOW_NEED_GB, peak=m.LOW_PEAK_GB, low=True)[0], 2)

    def test_measured_peak_of_the_same_kind(self):
        low_log = ['MoonRay XPU2 shaders: low memory: 10 modules, one at a time',
                   'MoonRay XPU2 shaders: compiled in 900 s (memory at most 2.4 GB, the machine\'s least free 30.1 GB)']
        self.assertAlmostEqual(self.module._measured_peak(low_log, True), 2.4)
        self.assertIsNone(self.module._measured_peak(low_log, False))
        full_log = low_log[1:]
        self.assertIsNone(self.module._measured_peak(full_log, True))
        self.assertAlmostEqual(self.module._measured_peak(full_log, False), 2.4)

    def test_reads_this_machine(self):
        text = self.module.memory_state()
        self.assertIn('GB free of', text)


if __name__ == '__main__':
    unittest.main()
