# python
"""Isolated GUI test: where Draft's time goes, and how many renders MoonLightIPR makes for it.

A scene (MOONRAY_PROBE_SCENE, else a cube) is opened with MoonRay chosen, so that nothing renders by itself. Reading the
scene out of Modo is timed by itself. Draft is then switched on, off and on again, and each time the wait for the
outlines is timed and the renders MoonLightIPR was asked for and finished are counted. Last, a region is dragged with
MoonLightIPR chosen, to count the renders that makes."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-cost'
out.mkdir(parents=True, exist_ok=True)
result = {'drafts': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def counted():
    """How many scenes MoonLightIPR has been sent and has finished, by what it printed."""
    return held['asked'], held['done']


def begin():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0350-pool')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        held['asked'] = held['done'] = 0
        session = panel.renderer.moonlightipr
        original = session.submit

        def submit(*args, **kwargs):
            held['asked'] += 1
            return original(*args, **kwargs)
        session.submit = submit
        session.ready.connect(lambda *args: held.__setitem__('done', held['done'] + 1))
        # Reading the scene out of Modo, which every render begins with.
        t = time.perf_counter()
        scene = panel._capture_preview()
        result['read_scene_seconds'] = round(time.perf_counter() - t, 2)
        result['meshes'] = len(scene.get('meshes', []))
        result['triangles'] = sum(len(m.get('faces', [])) for m in scene.get('meshes', []))
        from moonray_modo import moonlightipr_scene
        t = time.perf_counter()
        moonlightipr_scene.pack(dict(scene, _draft=2), 1920, 1080, 0.15, (), 12, False, panel.runtime_path())
        result['pack_scene_seconds_first'] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        moonlightipr_scene.pack(dict(scene, _draft=2), 1920, 1080, 0.15, (), 12, False, panel.runtime_path())
        result['pack_scene_seconds_again'] = round(time.perf_counter() - t, 2)
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: draft_on('first'))


def draft_on(name):
    panel = panel_widget()
    held.update(name=name, began=time.perf_counter(), before=counted())
    panel._draft_image = None
    panel.draft.click()
    QtCore.QTimer.singleShot(20, wait_lines)


def wait_lines():
    panel = panel_widget()
    waited = time.perf_counter() - held['began']
    if getattr(panel, '_draft_image', None) is not None and not panel._rendering or waited > 120:
        asked, done = counted()
        result['drafts'].append({'which': held['name'], 'seconds_to_outlines': round(waited, 2), 'renders_asked': asked - held['before'][0], 'renders_finished': done - held['before'][1],
                                 'drawn_at': list(panel._draft_fine), 'status': panel.status.text()})
        save()
        if held['name'] == 'first':
            panel.draft.click()
            QtCore.QTimer.singleShot(1500, lambda: draft_on('again'))
        elif held['name'] == 'again':
            QtCore.QTimer.singleShot(500, region)
        return
    QtCore.QTimer.singleShot(20, wait_lines)


def region():
    """A region in the draft with MoonLightIPR chosen: the outlines, then the region by the engine."""
    try:
        panel = panel_widget()
        panel.draft.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        # Choosing a realtime engine switches it on: wait for that to settle, then count from there.
    except Exception:
        result['region_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(6000, region_draft)


def region_draft():
    try:
        panel = panel_widget()
        held.update(began=time.perf_counter(), before=counted())
        panel.draft.click()
    except Exception:
        result['region_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(6000, region_set)


def region_set():
    try:
        panel = panel_widget()
        asked, done = counted()
        result['draft_with_realtime_on'] = {'renders_asked': asked - held['before'][0], 'renders_finished': done - held['before'][1], 'status': panel.status.text(), 'following': panel._following}
        held.update(began=time.perf_counter(), before=counted())
        panel.preview.region = (.3, .3, .7, .7)
        panel.region_enabled.setChecked(True)
        if hasattr(panel, '_region_changed'):
            panel._region_changed()
        else:
            panel.render_once()
    except Exception:
        result['region_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(8000, finish)


def finish():
    try:
        panel = panel_widget()
        asked, done = counted()
        result['region_in_draft'] = {'renders_asked': asked - held['before'][0], 'renders_finished': done - held['before'][1], 'status': panel.status.text()}
        panel.window().grab().save(str(out / 'region.png'))
        panel.stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    else:
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
