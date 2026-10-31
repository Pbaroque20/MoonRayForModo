"""A conversion's path comes back before its file exists, inside a scene being written: what reads it waits for it."""
import tempfile
import threading
import unittest
from pathlib import Path
from moonray_modo import conversions


class Finished(unittest.TestCase):
    def test_a_file_being_made_is_waited_for(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'made.tx'
            release = threading.Event()

            def work():
                release.wait(5)
                target.write_bytes(b'x')

            with conversions.together():
                conversions.run(str(target), work)
                self.assertFalse(target.exists())
                threading.Timer(0.05, release.set).start()
                conversions.finished(target)
                self.assertTrue(target.exists())

    def test_what_went_wrong_is_raised(self):
        def work():
            raise ValueError('it failed')

        with self.assertRaises(ValueError):
            with conversions.together():
                conversions.run('a.tx', work)
                conversions.finished('a.tx')

    def test_outside_a_scene_or_for_another_file_nothing_waits(self):
        conversions.finished('none.tx')
        with conversions.together():
            conversions.finished('none.tx')


if __name__ == '__main__':
    unittest.main()
