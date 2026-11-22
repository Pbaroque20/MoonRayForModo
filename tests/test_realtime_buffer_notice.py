"""MoonRay's realtime (CPU, XPU or XPU2) says nothing of buffers to come: its picture comes on as it renders, and
"Buffers will be available after the first preview pass completes." stood in the status line all through it. A Render
with no finished pass yet still says it. The behaviour needs PySide2 (Modo's Python: tools/check_realtime_buffer_notice.py);
here, the wiring."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python/moonray_modo'


class Wiring(unittest.TestCase):
    def test_the_cache_holds_its_word_when_quiet(self):
        source = (KIT / 'buffer_cache.py').read_text(encoding='utf-8')
        self.assertIn('self.quiet=False', source)
        self.assertIn("if not self.quiet:self.notice.emit('Buffers will be available after the first preview pass completes.')", source)

    def test_realtime_scenes_make_it_quiet(self):
        source = (KIT / 'render.py').read_text(encoding='utf-8')
        at = source.index("self.buffers.quiet=bool(snapshot.get('_realtime') or snapshot.get('_ipr'))")
        # Set before the buffer is chosen for the scene.
        self.assertLess(at, source.index('self.buffers.select(chosen,shown)'))
        # MoonRay's realtime scenes are the ones marked so (panel._submit).
        self.assertIn("if engine=='moonray' and self._following and not output:scene=dict(scene,_realtime=True)",
                      (KIT / 'panel.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
