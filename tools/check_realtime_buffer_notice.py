"""In Modo's Python (PySide2): the buffer cache says "Buffers will be available..." for a preview with no finished pass,
and nothing for a realtime one (render.submit sets quiet). Run with Modo's python.exe -S and its Qt set up, as
check_moonlightipr_qt_session.py is; prints OK or what went wrong."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from PySide2 import QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from moonray_modo.buffer_cache import BufferCache  # noqa: E402

heard = []
cache = BufferCache()
cache.notice.connect(heard.append)
cache.select('beauty', {})
assert heard == ['Buffers will be available after the first preview pass completes.'], heard
heard.clear()
cache.quiet = True
cache.select('beauty', {})
cache.select('diffuse', {})
assert heard == [], heard
cache.close() if hasattr(cache, 'close') else None
print('OK', flush=True)
os._exit(0)
