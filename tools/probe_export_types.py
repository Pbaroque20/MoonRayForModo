# python
"""Isolated GUI test: the Export AOVs window, and saving in the standard picture types.

A ball is rendered with MoonRay. The Export AOVs window is filled as the panel fills it, shown and pictured, its
choices noted; outputs are exported as 16-bit PNG and as JPEG, and what was written read back. Then the ball is
rendered to a file asked for as JPEG, as Render to a File does: the JPEG and the EXR kept beside it are noted."""
import json
import pathlib
import subprocess
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/export-types'
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    if old.is_file():
        old.unlink()
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def described(path):
    from moonray_modo import native
    done = subprocess.run([str(runtime / 'oiiotool.exe'), '--info', str(path)], env=native.environment(runtime), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    return done.stdout.decode(errors='replace').strip().split(':', 1)[-1].strip()


def render():
    panel = panel_widget()
    held['runtime'] = panel.preferences.store.value('runtime')
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


def window():
    from moonray_modo import outputs
    from moonray_modo.export_dialog import ExportAOVs, group_of
    panel = panel_widget()
    frame = panel.renderer.buffers.frame
    snapshot = frame.get('snapshot') or {}
    customs = {entry.get('name'): entry.get('kind') for entry in snapshot.get('custom_aovs') or []}
    entries = [(key, label, group_of(key, outputs.display_kind(snapshot, key), customs.get(key)), outputs.display_kind(snapshot, key))
               for key, label in panel.buffer_names(frame)]
    result['groups'] = sorted({group for _, _, group, _ in entries})
    dialog = ExportAOVs(panel, entries, panel.settings, 'Output Resolution: %d x %d based on Camera' % (snapshot['width'], snapshot['height']))
    dialog.folder.setText(str(out))
    dialog.kind.setCurrentIndex(dialog.kind.findData('png16'))
    dialog.show()
    QtWidgets.QApplication.processEvents()
    result['window'] = {'chosen': dialog.chosen(), 'files': dialog.names.text(), 'colour': dialog.colour.text(),
                        'quality_enabled': dialog.quality.isEnabled(), 'export_enabled': dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()}
    dialog.grab().save(str(out / 'window.png'))
    dialog.kind.setCurrentIndex(dialog.kind.findData('jpg'))
    QtWidgets.QApplication.processEvents()
    result['window_jpeg'] = {'quality_enabled': dialog.quality.isEnabled(), 'files': dialog.names.text()}
    dialog.close()
    for kind in ('png16', 'jpg', 'tif32', 'tga'):
        saved, failed = panel.write_buffers(frame, ['beauty', 'depth', 'albedo'], out, 'probe_' + kind, kind, 90)
        result['written_' + kind] = {pathlib.Path(path).name: described(path) for path in saved}
        result['failed_' + kind] = failed


def final():
    panel = panel_widget()
    scene = panel._capture_output()
    scene['_export_as'] = {'type': 'jpg', 'path': str(out / 'final.jpg'), 'quality': 90}
    panel._submit(scene, str(out / 'final.exr'))


def finished():
    result['final'] = {name: described(out / name) for name in ('final.jpg', 'final.exr') if (out / name).is_file()}
    panel = panel_widget()
    if held.get('runtime') is None:
        panel.preferences.store.remove('runtime')
    else:
        panel.preferences.store.setValue('runtime', held['runtime'])


def run(steps, index=0):
    if index >= len(steps):
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([(render, 40000), (window, 1000), (final, 60000), (finished, 500)]))
