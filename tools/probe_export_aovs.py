# python
"""Isolated GUI test: the outputs of a finished MoonRay preview are exported as images, and not under MoonLightIPR.

A cube is previewed with MoonRay with a few outputs ticked. When the preview has finished, what it holds is listed and
written out as PNG and as OpenEXR, and the files and their sizes are written down. The menu entry is looked at with
each engine chosen."""
import json
import pathlib
import subprocess
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/export-aovs'
out.mkdir(parents=True, exist_ok=True)
for old in list(out.glob('*.png')) + list(out.glob('*.exr')):
    old.unlink()
result = {}
held = {}
runtime = root / 'runtime/steady-0350-pool'


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def entry(panel):
    menu = panel._image_menu()
    action = next(a for a in menu.actions() if a.text().startswith('Export AOVs'))
    return action.isEnabled()


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    for key in ('albedo', 'diffuse_direct', 'depth', 'normal'):
        lx.eval('moonray.render.aov_%s 1' % key)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def start():
    try:
        panel = panel_widget()
        held['stored'] = panel.preferences.store.value('runtime', '')
        held['engine'] = panel.preview_engine.currentData()
        held['ipr'] = panel.preferences.get('ipr')
        panel.preferences.set('runtime', str(runtime))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        result['entry_with_moonlightipr'] = entry(panel)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        result['entry_with_moonray'] = entry(panel)
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result['start_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(70000, export)


def export():
    try:
        from moonray_modo import native
        panel = panel_widget()
        frame = panel.renderer.buffers.frame
        result['status'] = panel.status.text()
        result['held'] = panel.buffer_names(frame) if frame else None
        if frame:
            keys = [key for key, _ in panel.buffer_names(frame)]
            for kind in ('png', 'exr'):
                saved, failed = panel.write_buffers(frame, keys, out, 'check', kind)
                result[kind] = {'saved': [pathlib.Path(p).name for p in saved], 'failed': failed}
            info = subprocess.run([str(runtime / 'oiiotool.exe'), '--info'] + [str(p) for p in sorted(out.glob('check_*'))], env=native.environment(runtime),
                                  capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            result['files'] = [line.split('check_', 1)[1].strip() for line in info.stdout.splitlines() if 'check_' in line]
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
    except Exception:
        result['export_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, start)
