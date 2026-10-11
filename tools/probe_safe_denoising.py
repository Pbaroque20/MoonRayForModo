# python
"""Isolated GUI test: with Safe Denoising on, a MoonRay preview stopped part way is kept and denoised.

Two balls are previewed with MoonRay at many samples, so that the render takes a while, with a denoiser and Safe
Denoising switched on. It is stopped some seconds into its long pass. What the window then says, what the kept frame
holds, and the picture are written down."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/safe-denoising'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.sampling_mode 0')
    lx.eval('moonray.render.samples 40')
    lx.eval('moonray.render.denoiser 2')
    lx.eval('moonray.render.denoise_preview 1')
    lx.eval('moonray.render.denoise_safe 1')
    result['settings'] = [lx.eval('moonray.render.denoiser ?'), lx.eval('moonray.render.denoise_safe ?'), lx.eval('moonray.render.samples ?')]
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def first():
    try:
        panel = panel_widget()
        held['stored'] = panel.preferences.store.value('runtime', '')
        held['engine'] = panel.preview_engine.currentData()
        held['live'] = panel.ipr_mode.isChecked()
        panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
        panel.ipr_mode.setChecked(False)
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        panel.start.click()
    except Exception:
        result['first_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1000, watch)


def watch():
    """Stop once the long pass has been going long enough to have saved its picture."""
    try:
        panel = panel_widget()
        held['ticks'] = held.get('ticks', 0) + 1
        text = panel.status.text()
        if '1600' in text:
            held['long'] = held.get('long', 0) + 1
        # The long pass is the last one: nothing is left to follow it.
        if panel._rendering and not panel.renderer.passes and getattr(panel.renderer, 'phase', '') == 'render':
            held['long'] = held.get('long', 0) + 1
        if held.get('long', 0) >= 10 or held['ticks'] > 150:
            result['before_stop'] = [text, panel.render_timing.text(), held['ticks'], [p.name for p in panel.renderer.safe_files][:4]]
            panel.start.click()
            result['at_stop'] = [panel.status.text(), panel.start.text()]
            save()
            QtCore.QTimer.singleShot(30000, last)
            return
    except Exception:
        result['watch_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(100, last)
        return
    QtCore.QTimer.singleShot(1000, watch)


def last():
    try:
        panel = panel_widget()
        frame = panel.renderer.buffers.frame or {}
        result['after_stop'] = {'status': panel.status.text(), 'button': panel.start.text(), 'rendering': panel._rendering, 'buffer': panel.buffer.currentText(),
                                'denoised': 'denoised_beauty' in frame.get('files', {}), 'files': len(frame.get('files', {})), 'notices': panel.warnings.toPlainText()[:200],
                                'timing': panel.render_timing.text()}
        result['log'] = [line[:200] for line in str(getattr(panel.renderer, 'log', '')).splitlines() if line.strip() and not line.startswith('@@') and 'Rendering [' not in line][-25:]
        panel.window().grab().save(str(out / 'stopped.png'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
        panel.ipr_mode.setChecked(held['live'])
    except Exception:
        result['last_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, first)
