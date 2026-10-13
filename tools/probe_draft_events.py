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
        # MOONRAY_PROBE_ENGINE chooses the engine (MoonRay unless named); MOONRAY_PROBE_RT=1 switches realtime on first.
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(os.environ.get('MOONRAY_PROBE_ENGINE', 'moonray')))
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
        session.failed.connect(lambda *a: event('engine failed', str(a)[:120]))
        session.acknowledged.connect(lambda *a: event('engine applied', a[0] if a else ''))
        renderer.finished.connect(lambda *a: event('render finished', str(a)[:40]))
        renderer.failed.connect(lambda *a: event('render failed', str(a)[:160]))
        sent, packed = session.submit, session._packed

        def told_submit(*a, **k):
            event('engine given a scene', a[5] if len(a) > 5 else k.get('generation'), 'running %s' % session.running(), 'stopping %s' % session.stopping)
            return sent(*a, **k)

        def told_packed():
            worker = session.packer
            event('scene made ready', getattr(worker, 'abandoned', None), str((worker.outcome or [None, None, None])[2])[:100] if worker is not None else None)
            return packed()
        session.submit, session._packed = told_submit, told_packed
        for name in ('stop', 'release', 'finish'):
            def wrap(inner=getattr(session, name), name=name):
                def told(*a, **k):
                    event('engine told to ' + name)
                    return inner(*a, **k)
                return told
            setattr(session, name, wrap())
        result['signals'] = [n for n in dir(buffers) if isinstance(getattr(type(buffers), n, None), QtCore.Signal)]
        result['view'] = [panel.preview.width(), panel.preview.height(), panel.preview.devicePixelRatioF()]
        # A mesh with something in it: a scene opened from a MoonRay file has an empty one first.
        held['mesh'] = next((m.id for m in modo.Scene().items('mesh') if len(m.geometry.polygons)), None)
        from moonray_modo import rdl_import_dialog
        if rdl_import_dialog._dialog is not None:
            rdl_import_dialog._dialog.close()
        # MOONRAY_PROBE_PERSISTENT=0 has Keep MoonRay Loaded switched off, and put back at the end.
        held['loaded'] = panel.preferences.get('persistent_preview')
        if os.environ.get('MOONRAY_PROBE_PERSISTENT') == '0':
            panel.preferences.set('persistent_preview', False)
        result['keep_loaded'] = panel.preferences.get('persistent_preview')
        held['camera'] = modo.Scene().renderCamera.id
        if os.environ.get('MOONRAY_PROBE_RT') == '1':
            panel.start.click()
            QtWidgets.QApplication.processEvents()
        panel.draft.click()
        result['state'] = {'engine': panel.preview_engine.currentText(), 'following': panel._following, 'draft': panel.draft.isChecked()}
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(7000, lambda: edit(0))


def edit(count):
    if not count:
        result['start'] = held['events']
        save()
    if count:
        result['edits'][-1]['events'] = held['events']
        panel = panel_widget()
        result['edits'][-1]['after'] = {'rendering': panel._rendering, 'following': panel._following, 'draft': panel.draft.isChecked(), 'busy': panel._output_busy(),
                                        'status': panel.status.text()[:80], 'pending': [bool(panel.changes.full), len(panel.changes.items)]}
        panel_widget().preview.grab().save(str(out / ('after_%d.png' % count)))
        save()
    if count == 3:
        panel_widget().preview.grab().save(str(out / 'last.png'))
        panel_widget().stop()
        panel_widget().preferences.set('persistent_preview', held.get('loaded', True))
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
# MOONRAY_PROBE_WAIT: seconds before beginning, for a scene that takes a while to come in.
QtCore.QTimer.singleShot(int(float(os.environ.get('MOONRAY_PROBE_WAIT', '8')) * 1000), begin)
