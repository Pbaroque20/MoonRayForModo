# python
"""Isolated GUI test: everything that happens between an edit and the draft's pictures of it, in order, with times.

A scene (MOONRAY_PROBE_SCENE) with Draft on and MoonRay chosen. A mesh is moved, then the render camera, then the mesh
again; after each, every render asked for (its size and samples), every picture MoonLightIPR hands over, every
conversion for display begun and ended, and every picture put in the view is written down with the time since the edit."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-events'
out.mkdir(parents=True, exist_ok=True)
result = {'edits': []}
held = {'base': time.perf_counter(), 'events': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def event(name, *more):
    held['events'].append([round(time.perf_counter() - held['base'], 3), name] + list(more))


def begin():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        renderer, buffers, session = panel.renderer, panel.renderer.buffers, panel.renderer.moonlightipr
        capture, submit, start, done, image, show = panel._capture, renderer.submit, buffers._start, buffers._memory_finished, panel._image, panel.preview.set_image

        def timed_capture(*a, **k):
            event('read begins', repr(a[0] if a else k.get('reuse', False))[:40]); value = capture(*a, **k); event('read ends'); return value

        def timed_submit(scene, runtime, width, height, *a, **k):
            event('render asked', width, height, 'samples %s' % scene.get('_draft_samples'), 'hasty' if getattr(panel, '_draft_hasty', False) else 'fine')
            return submit(scene, runtime, width, height, *a, **k)

        def timed_start(*a, **k):
            event('display conversion begins'); return start(*a, **k)

        def timed_image(path):
            size = [path.width(), path.height()] if hasattr(path, 'width') else str(path)[-20:]
            event('picture to the window', size); value = image(path); event('picture inked'); return value

        def timed_show(picture):
            value = show(picture); event('picture in the view', picture.width(), picture.height()); return value
        panel._capture, renderer.submit, buffers._start, panel.preview.set_image = timed_capture, timed_submit, timed_start, timed_show
        buffers.image_object.connect(lambda im: event('picture converted', im.width(), im.height()) if hasattr(im, 'width') else event('picture converted'))
        session.memory_image.connect(lambda *a: event('engine hands over a picture', a[0][2] if a and isinstance(a[0], (tuple, list)) and len(a[0]) > 2 else ''))
        session.ready.connect(lambda *a: event('engine done'))
        result['signals'] = [n for n in dir(buffers) if isinstance(getattr(type(buffers), n, None), QtCore.Signal)]
        result['view'] = [panel.preview.width(), panel.preview.height(), panel.preview.devicePixelRatioF()]
        held['mesh'] = next((m.id for m in modo.Scene().items('mesh')), None)
        held['camera'] = modo.Scene().renderCamera.id
        panel.draft.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(7000, lambda: edit(0))


def edit(count):
    if count:
        result['edits'][-1]['events'] = held['events']
        panel_widget().preview.grab().save(str(out / ('after_%d.png' % count)))
        save()
    if count == 3:
        panel_widget().preview.grab().save(str(out / 'last.png'))
        panel_widget().stop()
        lx.eval('!app.quit')
        return
    what = ('mesh', 'camera', 'mesh')[count]
    try:
        held['events'] = []
        result['edits'].append({'moved': what})
        lx.eval('select.item {%s} set' % held[what])
        # A little way from where it stands, so that what the camera sees stays in its frame.
        here = lx.eval('transform.channel pos.X ?')
        lx.eval('transform.channel pos.X %s' % (here + 0.02))
        held['base'] = time.perf_counter()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(6000, lambda: edit(count + 1))


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
