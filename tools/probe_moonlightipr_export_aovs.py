# python
"""GUI: Export AOVs with MoonLightIPR (panel_tools._moonlightipr_fetch). A Render of 64 samples a pixel, realtime off,
then the preview's right-click menu checked for its Export AOVs entry (enabled), and Export AOVs run with every output
ticked: once as EXRs, once as PNGs, once as one multilayer EXR. The dialog is the real one, answered by the probe. For
each: the files written, and each EXR's mean beside the mean of the numbers MoonLightIPR sent for it. Writes
test-results/moonlightipr-export-aovs/report.json. PROBE_SCENE picks the scene."""
import json
import os
import pathlib
import shutil
import struct
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-export-aovs')
if out.exists():
    shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
result = {'exports': {}}
SAMPLES = 64
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def begin():
    try:
        p = panel()
        result['kept_samples'] = p.preferences.get('moonlightipr/render_samples')
        p.preferences.set('moonlightipr/render_samples', SAMPLES)
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        QtCore.QTimer.singleShot(1500, lambda: (p.start.click(), QtCore.QTimer.singleShot(500, wait_render)))
        state['began'] = time.monotonic()
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def wait_render():
    try:
        p = panel()
        r = p.renderer
        said = getattr(r.moonlightipr, 'samples_now', None)
        done = said and said[1] >= SAMPLES and not r.buffers.busy() and not getattr(p, '_rendering', False)
        if not done and time.monotonic() - state['began'] < 120:
            QtCore.QTimer.singleShot(200, wait_render); return
        result['render'] = {'seconds': round(time.monotonic() - state['began'], 2), 'samples': said, 'status': p.status.text()}
        # What MoonLightIPR has sent so far, by its key: width, height and bytes.
        result['sent'] = {}
        for key, f in r.buffers.progressive_frames.items():
            held = f.get('linear', {}).get(key)
            result['sent'][key] = [held[0], held[1], len(bytes(held[2]))] if held else None
        save()
        QtCore.QTimer.singleShot(500, check_menu)
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def check_menu():
    """The right-click menu, as the preview makes it: its Export AOVs entry and whether it is enabled."""
    try:
        p = panel()
        menu = p._image_menu()
        entries = [(a.text(), a.isEnabled(), a.toolTip()) for a in menu.actions() if a.text()]
        result['menu'] = [e for e in entries if 'Export' in e[0]] or entries
        menu.deleteLater()
        save()
    except Exception:
        result['menu_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(300, lambda: export('exr32', False))


def export(kind, layered):
    label = kind + (' layered' if layered else '')
    folder = out / label.replace(' ', '_')
    folder.mkdir(parents=True, exist_ok=True)
    try:
        from moonray_modo import export_dialog
        real = export_dialog.ExportAOVs
        seen = {}

        class Answered(real):
            def exec_(self):
                seen['offered'] = [(box.key, box.text()) for box in self.items]
                # The PNGs: only three ticked, which alone must be asked of the session and written.
                some = ('beauty', 'moonlightipr_glossy', 'normal')
                for box in self.items:
                    box.setChecked(kind != 'png8' or box.key in some)
                self.kind.setCurrentIndex(self.kind.findData(kind))
                self.folder.setText(str(folder))
                self.prefix.setText('probe')
                self.layers.setChecked(layered)
                self.open_after.setChecked(False)
                seen['chosen'] = self.chosen()
                return QtWidgets.QDialog.Accepted
        export_dialog.ExportAOVs = Answered
        p = panel()
        shown = p.buffer.currentData()
        changes = []
        follow = lambda index: changes.append(p.buffer.itemData(index))
        p.buffer.currentIndexChanged.connect(follow)
        asked = []
        session = p.renderer.moonlightipr
        real_aov = session.aov
        session.aov = lambda kind_, key_: (asked.append(key_), real_aov(kind_, key_))[1]
        started = time.monotonic()
        try:
            p.export_buffers()
        finally:
            export_dialog.ExportAOVs = real
            session.aov = real_aov
            p.buffer.currentIndexChanged.disconnect(follow)
        seen['buffer_list_changes'] = changes
        seen['asked_of_session'] = asked
        # The numbers MoonLightIPR sent for each output (the beauty's and the denoised beauty's under the beauty's name,
        # the last of them), kept as PFMs beside the export, for check_moonlightipr_export_aovs.py.
        if kind == 'exr32' and not layered:
            for key, f in p.renderer.buffers.progressive_frames.items():
                held = f.get('linear', {}).get(key)
                if held:
                    width, height, pixels = held
                    (out / ('sent_%s.pfm' % key)).write_bytes(('PF\n%d %d\n-1.0\n' % (width, height)).encode('ascii') + bytes(pixels))
        entry = dict(seen, seconds=round(time.monotonic() - started, 2), status=p.status.text(),
                     shown_before=shown, shown_after=p.buffer.currentData(),
                     files=sorted(f.name for f in folder.iterdir()))
        result['exports'][label] = entry
        save()
    except Exception:
        result['exports'][label] = {'error': traceback.format_exc()}
        save()
    nxt = {('exr32', False): ('png8', False), ('png8', False): ('exr32', True)}.get((kind, layered))
    if nxt:
        QtCore.QTimer.singleShot(500, lambda: export(*nxt))
    else:
        QtCore.QTimer.singleShot(500, finish)


def finish():
    try:
        p = panel()
        p.preferences.set('moonlightipr/render_samples', result.get('kept_samples') or 500)
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\src.lxo'))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
