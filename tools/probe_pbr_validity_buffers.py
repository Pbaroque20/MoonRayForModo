# python
"""GUI: where the preview's PBR validity picture goes. A cube rendered with PBR validity on (test settings), by MoonRay
XPU and then XPU2; after each, what the render asked for (preview files), what exists on disk, what the buffer cache's
frame holds, and the picture shown for the pbr_validity buffer. Writes test-results/pbr-validity-buffers/."""
import json
import pathlib
import subprocess
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/pbr-validity-buffers'
out.mkdir(parents=True, exist_ok=True)
OIIO = root / 'toolchain/msys64/ucrt64/bin/oiiotool.exe'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def settings():
    from moonray_modo import native
    return QtCore.QSettings('MoonRayForModo', native.settings_name())


try:
    s = settings()
    for key in ('pbr_validity', 'xpu2/renderer'):
        held[key] = s.value(key)
    s.setValue('pbr_validity', True); s.setValue('xpu2/renderer', 'xpu'); s.sync()
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on'); lx.eval('tool.apply'); lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def channels(path):
    try:
        said = subprocess.run([str(OIIO), '--info', '-v', str(path)], capture_output=True, text=True, timeout=30,
                              creationflags=0x08000000).stdout
        return [l.strip() for l in said.splitlines() if 'channel list' in l]
    except Exception as exc:
        return str(exc)


def look(label):
    p = panel()
    r = p.renderer
    seen = {'buffer': p.buffer.currentData(), 'status': p.status.text(), 'info': p.image_info.text()}
    files = getattr(r, 'preview_files', {}) or {}
    seen['preview_files'] = {k: [str(v), pathlib.Path(v).is_file(), channels(v) if k in ('beauty', 'pbr_validity') and pathlib.Path(v).is_file() else None]
                             for k, v in files.items() if k in ('beauty', 'pbr_validity', 'albedo')}
    cache = r.buffers
    seen['cache_key'] = getattr(cache, 'key', None)
    frames = getattr(cache, 'progressive_frames', {}) or {}
    seen['progressive'] = {k: sorted((v or {}).keys()) if isinstance(v, dict) else str(type(v)) for k, v in frames.items()}
    frame = getattr(cache, 'frame', None)
    if isinstance(frame, dict):
        seen['frame_files'] = {k: str(v) for k, v in (frame.get('files') or {}).items() if k in ('beauty', 'pbr_validity')}
        seen['frame_linear'] = sorted((frame.get('linear') or {}).keys())
    p.window().grab().save(str(out / (label + '.png')))
    result[label] = seen
    save()


def render(label, then):
    p = panel()
    engine = p.preview_engine.findData('moonray')
    if engine >= 0: p.preview_engine.setCurrentIndex(engine)
    p._preferences_followed_now()
    p.render_once()
    began = time.monotonic()

    def wait():
        try:
            if (getattr(panel(), '_rendering', False) and time.monotonic() - began < 240) or time.monotonic() - began < 4:
                QtCore.QTimer.singleShot(1500, wait); return
            QtCore.QTimer.singleShot(2000, lambda: (look(label), then()))
        except Exception:
            result[label + '_error'] = traceback.format_exc(); save(); finish()
    QtCore.QTimer.singleShot(2000, wait)


def second():
    s = settings(); s.setValue('xpu2/renderer', 'xpu2'); s.sync()
    render('xpu2', finish)


def finish():
    try:
        s = settings()
        for key, value in held.items():
            if value is None: s.remove(key)
            else: s.setValue(key, value)
        s.sync()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(6000, lambda: render('xpu', second))
