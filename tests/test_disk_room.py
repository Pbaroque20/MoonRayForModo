"""Room on the drives a render writes to, as the preview says it (disk_room): a tester's XPU2 render of a car seemed to
hang with 90 MB left on C:, and a car's reading failed with Modo's "basic_ios::clear: iostream error". A drive nearly
full is a notice while a render is on (not an error), a render that shows nothing new for a while with one is held up
(an error, in the status), and a failure with one says the room left first."""
import ast
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import disk_room  # noqa: E402

GB = 1024 ** 3


def notice_errors():
    """The words that make a notice an error (panel.NOTICE_ERRORS), read from panel.py: it needs Qt to import."""
    text = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel.py').read_text(encoding='utf-8')
    line = next(line for line in text.splitlines() if line.startswith('NOTICE_ERRORS'))
    return ast.literal_eval(line.split('=', 1)[1].strip())


def is_error(message):
    return any(word in message.lower() for word in notice_errors())


class Drives(unittest.TestCase):
    def check(self, rooms, folders):
        usage = lambda path: SimpleNamespace(free=rooms[disk_room.drive(path)])
        with mock.patch.object(disk_room, 'folders', return_value=folders), \
                mock.patch.object(disk_room.os.path, 'exists', return_value=True), \
                mock.patch.object(disk_room.shutil, 'disk_usage', side_effect=usage):
            return disk_room.short()

    def test_drives_nearly_full_each_once_the_fullest_first(self):
        found = self.check({'C:': int(0.09 * GB), 'D:': int(1.5 * GB), 'E:': 300 * GB},
                           ['D:\\Cache', 'C:\\Users\\me\\AppData\\Local\\Temp', 'C:\\', 'E:\\renders'])
        self.assertEqual([name for name, _ in found], ['C:', 'D:'])

    def test_drives_with_room_say_nothing(self):
        self.assertEqual(self.check({'C:': 40 * GB}, ['C:\\Cache', 'C:\\Temp', 'C:\\']), [])

    def test_the_limit_is_the_one_set_when_asked(self):
        # Read when the drives are asked, not when the module was loaded: a probe raises it to try what is said.
        with mock.patch.object(disk_room, 'LOW_BYTES', 100 * GB):
            self.assertEqual([name for name, _ in self.check({'C:': 40 * GB}, ['C:\\'])], ['C:'])

    def test_a_drive_that_cannot_be_asked_says_nothing(self):
        with mock.patch.object(disk_room, 'folders', return_value=['Q:\\nowhere']), \
                mock.patch.object(disk_room.shutil, 'disk_usage', side_effect=OSError('no drive')):
            self.assertEqual(disk_room.short(), [])

    def test_a_folder_not_made_yet_is_asked_by_the_nearest_one_there_is(self):
        made = {'C:\\Users', 'C:\\'}
        with mock.patch.object(disk_room.os.path, 'exists', side_effect=lambda path: path in made), \
                mock.patch.object(disk_room.os.path, 'abspath', side_effect=lambda path: path), \
                mock.patch.object(disk_room.shutil, 'disk_usage', return_value=SimpleNamespace(free=5)) as usage:
            self.assertEqual(disk_room.free('C:\\Users\\me\\Cache\\Ocean'), 5)
        usage.assert_called_once_with('C:\\Users')


class Said(unittest.TestCase):
    found = [('C:', 90 * 1024 ** 2)]

    def test_nothing_is_said_with_room_or_with_no_render_on(self):
        self.assertEqual(disk_room.said([], True, 60.0), (None, None))
        self.assertEqual(disk_room.said(self.found, False, 60.0), (None, None))

    def test_a_drive_nearly_full_is_a_notice_while_a_render_goes_on(self):
        notice, status = disk_room.said(self.found, True, 3.0, 'XPU2')
        self.assertIsNone(status)
        self.assertIn('C: (90 MB free)', notice)
        self.assertIn('XPU2', notice)
        self.assertIn('Cache folder', notice)
        self.assertFalse(is_error(notice))

    def test_a_render_showing_nothing_new_with_a_drive_nearly_full_is_held_up(self):
        notice, status = disk_room.said(self.found, True, disk_room.HELD_UP + 1, 'XPU2')
        self.assertEqual(notice, status)
        self.assertIn('Nothing new for 21 s', status)
        self.assertIn('C: (90 MB free)', status)
        self.assertTrue(is_error(status))

    def test_a_failure_with_a_drive_nearly_full_says_the_room_first(self):
        said = disk_room.failed('Modo evaluated geometry: basic_ios::clear: iostream error', self.found, 'XPU2')
        self.assertTrue(said.startswith('Low disk space: C: (90 MB free)'))
        self.assertIn('basic_ios::clear', said)
        self.assertEqual(disk_room.failed('Scene missing', [], 'XPU2'), 'Scene missing')

    def test_a_full_drives_errors_are_known(self):
        for text in ('Modo evaluated geometry: basic_ios::clear: iostream error', '[Errno 28] No space left on device',
                     '[WinError 112] There is not enough space on the disk', '[WinError 1455] The paging file is too small'):
            self.assertTrue(disk_room.full_error(text), text)
        self.assertFalse(disk_room.full_error('Scene missing'))

    def test_room_is_said_as_a_person_reads_it(self):
        self.assertEqual(disk_room.amount(90 * 1024 ** 2), '90 MB')
        self.assertEqual(disk_room.amount(int(1.42 * GB)), '1.4 GB')


if __name__ == '__main__':
    unittest.main()
