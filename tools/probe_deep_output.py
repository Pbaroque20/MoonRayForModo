# python
"""Isolated GUI test: Save a Deep EXR, ticked in the Render item's form, puts a deep file beside a Render EXR.

A cube is rendered to a file from the preview window, as Render EXR does, once with the setting off and once with it
on. Which files are beside each render, and what kind of image the deep one is, are written down."""
import json
import pathlib
import subprocess
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/deep-output'
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*.exr'):
    old.unlink()
result = {}
held = {}
runtime = root / 'runtime/steady-0350-pool'


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    result['setting_starts'] = lx.eval('moonray.render.deep ?')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def render(name, then):
    try:
        panel = panel_widget()
        held.setdefault('stored', {key: panel.preferences.store.value(key, '') for key in ('runtime',)})
        panel.preferences.set('runtime', str(runtime))
        panel.stop()
        panel._submit(panel._capture_output(), str(out / (name + '.exr')))
    except Exception:
        result[name + '_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(60000, then)


def first():
    render('plain', second)


def second():
    try:
        result['after_plain'] = sorted(p.name for p in out.glob('*.exr'))
        lx.eval('moonray.render.deep 1')
        result['setting_on'] = lx.eval('moonray.render.deep ?')
    except Exception:
        result['second_error'] = traceback.format_exc()
    render('with_deep', last)


def last():
    try:
        panel = panel_widget()
        result['after_deep'] = sorted(p.name for p in out.glob('*.exr'))
        result['status'] = [panel.status.text(), panel.warnings.toPlainText()[:400]]
        from moonray_modo import native
        for name in ('with_deep.exr', 'with_deep.deep.exr'):
            if (out / name).is_file():
                done = subprocess.run([str(runtime / 'oiiotool.exe'), '--info', str(out / name)], env=native.environment(runtime), capture_output=True, text=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                result[name] = (done.stdout + done.stderr).strip()[-160:]
        # The window's choices are shared with the user's own Modo: put back what was stored.
        for key, value in held.get('stored', {}).items():
            panel.preferences.store.setValue(key, value)
    except Exception:
        result['last_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, first)
