"""Pictures handed over in shared memory have no size limit (modo_shared_image.h, shared_image.py): a 4K render's
progressive picture is 99.5 MB of float RGB, past the 64 MB there was, and was not handed over at all, so the preview
stayed black until the render was done. Here a 4K picture is published as the renderers publish one (a named mapping
and its acknowledgement event) and read back whole, and no step a picture passes through keeps a byte limit."""
import ctypes
import os
import pathlib
import struct
import sys
import unittest
from ctypes import wintypes

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import shared_image  # noqa: E402


@unittest.skipUnless(sys.platform == 'win32', 'Windows shared memory')
class LargeFrames(unittest.TestCase):
    def publish(self, width, height, serial):
        """A picture as modo_shared_image.h publishes it: its mapping and event, and the protocol line."""
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
        api.CreateFileMappingW.restype = wintypes.HANDLE
        api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        api.CreateEventW.restype = wintypes.HANDLE
        api.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        api.MapViewOfFile.restype = ctypes.c_void_p
        api.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        size = width * height * 12
        name = 'Local\\MoonRayForModo_%d_%d' % (os.getpid(), serial)
        ack = api.CreateEventW(None, True, False, name + '_ack')
        mapping = api.CreateFileMappingW(wintypes.HANDLE(-1), None, 0x04, size >> 32, size & 0xffffffff, name)
        self.assertTrue(ack and mapping, 'the mapping is made')
        view = api.MapViewOfFile(mapping, 0x0002, 0, 0, size)
        self.assertTrue(view, 'the mapping is mapped')
        # The first pixel and the last, marked.
        ctypes.memmove(view, struct.pack('<3f', 1.0, 2.0, 3.0), 12)
        ctypes.memmove(view + size - 12, struct.pack('<3f', 4.0, 5.0, 6.0), 12)
        api.UnmapViewOfFile(view)
        self.addCleanup(api.CloseHandle, mapping)
        self.addCleanup(api.CloseHandle, ack)
        return '@@MODO_SHARED 7 beauty %d %d %s' % (width, height, name), ack, api

    def test_a_4k_picture_is_taken_whole(self):
        line, ack, api = self.publish(3840, 2160, 1)
        generation, key, width, height, pixels = shared_image.receive(line, os.getpid())
        self.assertEqual((generation, key, width, height), (7, 'beauty', 3840, 2160))
        self.assertEqual(len(pixels), 3840 * 2160 * 12)
        self.assertEqual(struct.unpack('<3f', pixels[:12]), (1.0, 2.0, 3.0))
        self.assertEqual(struct.unpack('<3f', pixels[-12:]), (4.0, 5.0, 6.0))
        self.assertEqual(api.WaitForSingleObject(ack, 0), 0, 'the picture is acknowledged')

    def test_its_sides_are_still_those_of_a_render(self):
        line = '@@MODO_SHARED 1 beauty 16385 16 Local\\MoonRayForModo_%d_9' % os.getpid()
        with self.assertRaises(ValueError):
            shared_image.receive(line, os.getpid())


class NoByteLimit(unittest.TestCase):
    def test_no_step_a_picture_passes_through_keeps_a_byte_limit(self):
        steps = ['kit/MoonRayForModo/python/moonray_modo/shared_image.py', 'kit/MoonRayForModo/python/moonray_modo/buffer_cache.py',
                 'kit/MoonRayForModo/python/moonray_modo/display_stream.py', 'kit/MoonRayForModo/python/moonray_modo/memory_display.py',
                 'native-port/modo_shared_image.h', 'native-port/modo_display.cpp', 'native-port/modo_display_stream.cpp']
        for step in steps:
            text = (ROOT / step).read_text(encoding='utf-8')
            for limit in ('64*1024*1024', '64 * 1024 * 1024', 'MAX_BYTES'):
                self.assertNotIn(limit, text, step)
        header = (ROOT / 'native-port/modo_shared_image.h').read_text(encoding='utf-8')
        self.assertIn('DWORD(uint64_t(bytes)>>32),DWORD(bytes)', header, 'a picture past 4 GB is mapped whole')


if __name__ == '__main__':
    unittest.main()
