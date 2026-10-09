# python
"""Isolated GUI test: with a beauty denoiser set in the render settings, a finished MoonRay preview shows the denoised picture.

PROBE_RDL_DOCUMENT names a scene as MoonRay's reader gave it (tools/check_rdl_import.py --documents); without one a
cube is rendered. What the panel says along the way, and what the finished frame holds, are written down."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/denoise-preview'
out.mkdir(parents=True, exist_ok=True)
result = {'said': [], 'notices': []}
SOURCE = os.environ.get('PROBE_RDL_DOCUMENT', '')
ENGINE = os.environ.get('PROBE_DENOISER', 'oidn_cpu')
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def restore(panel):
    """The preview's preferences are shared with the user's own Modo: put back what was stored."""
    for key, value in held.items():
        if value == '':
            panel.preferences.store.remove(key)
        else:
            panel.preferences.store.setValue(key, value)


try:
    from moonray_modo import properties, rdl_import
    if SOURCE:
        document = json.loads(pathlib.Path(SOURCE).read_text(encoding='utf-8'))
        result['import'] = rdl_import.apply(rdl_import.plan(document, document['_path'])).splitlines()[0]
    else:
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
    scene = modo.Scene()
    stored = dict(properties.scene_settings())
    if os.environ.get('PROBE_ORDER', 'before') == 'before':
        stored['denoising'] = {'engine': ENGINE, 'preview': True, 'final': True}
    stored['samples'] = 3
    stored['render'] = dict(stored.get('render') or {}, sampling_mode=0)
    properties.write(scene.renderItem, stored)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
ticks = [0]


def begin():
    try:
        panel = panel_widget()
        for key in ('preview_engine', 'ipr'):
            held[key] = panel.preferences.store.value(key, '')
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.ipr_mode.setChecked(False)
        panel.renderer.buffers.notice.connect(lambda text: result['notices'].append(text))
        if os.environ.get('PROBE_ORDER', 'before') == 'after':
            # As the user does it: the denoiser chosen in the render settings while the preview is open.
            from moonray_modo import properties, scene_settings
            known = [value for _, value in scene_settings.DENOISERS]
            lx.eval('moonray.render.denoiser %d' % known.index(ENGINE))
            lx.eval('moonray.render.denoise_preview 1')
            result['set'] = properties.scene_settings().get('denoising')
    except Exception:
        result['begin_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, press)


def press():
    try:
        panel = panel_widget()
        result['before_render'] = panel.buffer.currentData()
        panel.start.click()
        result['started'] = [panel.start.text(), panel.buffer.currentData()]
    except Exception:
        result['begin_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, watch)


def watch():
    try:
        panel = panel_widget()
        ticks[0] += 1
        text = panel.status.text()
        if not result['said'] or result['said'][-1] != text:
            result['said'].append(text)
        frame = panel.renderer.buffers.frame
        if text.startswith('Render unavailable'):
            result['failed'] = text
            restore(panel)
            save()
            QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))
            return
        done = not panel._rendering and frame is not None
        if done and 'done_at' not in result and os.environ.get('PROBE_ORDER') == 'later':
            # The render is finished; only now is a denoiser chosen in the render settings.
            from moonray_modo import properties, scene_settings
            known = [value for _, value in scene_settings.DENOISERS]
            result['finished_with'] = [panel.buffer.currentData(), sorted(frame['files'])[:6]]
            lx.eval('moonray.render.denoiser %d' % known.index(ENGINE))
            lx.eval('moonray.render.denoise_preview 1')
            result['set'] = properties.scene_settings().get('denoising')
        if done:
            result.setdefault('done_at', ticks[0])
        if (done and ticks[0] - result['done_at'] >= 12) or ticks[0] > 240:
            result['buffer'] = panel.buffer.currentData()
            result['buffers'] = [panel.buffer.itemData(i) for i in range(panel.buffer.count())]
            result['frame'] = None if frame is None else {'files': sorted(frame['files']), 'engine': frame.get('denoise_engine'), 'partial': frame.get('partial')}
            result['denoiser'] = [panel.renderer.buffers.denoiser.requested, panel.renderer.buffers.denoiser.job is not None]
            result['displayed'] = sorted((panel.renderer.buffers.displayed or {}).keys()) if isinstance(panel.renderer.buffers.displayed, dict) else str(panel.renderer.buffers.displayed)
            result['key'] = getattr(panel.renderer.buffers, 'key', None)
            panel.window().grab().save(str(out / 'panel.png'))
            restore(panel)
            save()
            QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))
            return
    except Exception:
        result['watch_error'] = traceback.format_exc()
        try:
            from PySide2 import QtCore as _core
            store = _core.QSettings('MoonRayForModo', 'NativePreview')
            for key, value in held.items():
                store.remove(key) if value == '' else store.setValue(key, value)
        except Exception:
            pass
        save()
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))
        return
    save()
    QtCore.QTimer.singleShot(1000, watch)


QtCore.QTimer.singleShot(5000, begin)
