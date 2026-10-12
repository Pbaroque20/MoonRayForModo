# python
"""Isolated GUI test: what a draft's time is spent on, step by step, on a scene (MOONRAY_PROBE_SCENE).

Draft is switched on with MoonRay chosen and realtime off. An item is then moved a little, several times, and each
redraw is timed in its parts: reading the scene out of Modo (profiled, with the functions that take longest), handing it
to MoonLightIPR, MoonLightIPR's own work until its first and last picture, and showing the picture."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-profile'
out.mkdir(parents=True, exist_ok=True)
result = {'redraws': []}
held = {'marks': {}}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def mark(name):
    held['marks'].setdefault(name, time.perf_counter())


def begin():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        # Where the time of one reading of the scene goes.
        profile = cProfile.Profile()
        profile.enable()
        scene = panel._capture_preview()
        profile.disable()
        text = io.StringIO()
        pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(28)
        (out / 'read_scene_profile.txt').write_text(text.getvalue())
        result['meshes'] = len(scene.get('meshes', []))
        result['triangles'] = sum(len(m.get('faces', [])) for m in scene.get('meshes', []))
        result['surface'] = panel._settings_values().get('surface')
        # The parts of a redraw, by wrapping what does each.
        session = panel.renderer.moonlightipr
        capture, submit, sent = panel._capture, panel._submit, session.submit

        def timed_capture(*a, **k):
            held['reuse'] = repr(a[0] if a else k.get('reuse', False))[:60]
            mark('read_begin'); value = capture(*a, **k); mark('read_end'); return value

        def timed_submit(*a, **k):
            mark('submit_begin'); value = submit(*a, **k); mark('submit_end'); return value

        def timed_sent(*a, **k):
            mark('session_asked'); return sent(*a, **k)
        panel._capture, panel._submit, session.submit = timed_capture, timed_submit, timed_sent
        cache = panel._geometry_cache or {}
        def count(kind, over):
            try:
                return len(modo.Scene().items(kind, superType=over))
            except Exception as exc:
                return 'cannot be asked: ' + type(exc).__name__
        result['why_whole'] = {'evaluated': cache.get('_evaluated_data') is not None, 'extra_geometry': len(cache.get('extra_geometry') or []),
                               'deformers': count('deform', True), 'stand_with_items': cache.get('_item_transforms'), 'instances': count('meshInst', False), 'replicators': count('replicator', False)}
        session.acknowledged.connect(lambda *a: mark('session_applied')) if hasattr(session, 'acknowledged') else None
        session.memory_image.connect(lambda *a: mark('first_picture'))
        session.ready.connect(lambda *a: mark('session_done'))
        held['item'] = next((m.id for m in modo.Scene().items('mesh')), None)
        result['item'] = held['item']
        panel.draft.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(6000, lambda: edit(0))


def edit(count):
    """Move an item a little and time the redraw that follows by itself."""
    try:
        panel = panel_widget()
        # With MOONRAY_PROBE_DRAG set, the first three edits are made as though a mouse button were held down.
        if os.environ.get('MOONRAY_PROBE_DRAG'):
            from moonray_modo import interaction
            interaction.dragging = (lambda: True) if count < 3 else (lambda: False)
        held['dragged'] = bool(os.environ.get('MOONRAY_PROBE_DRAG')) and count < 3
        held['marks'] = {}
        held['shown_before'] = panel.preview.image.cacheKey() if not panel.preview.image.isNull() else None
        lx.eval('select.item {%s} set' % held['item'])
        lx.eval('transform.channel pos.X %s' % (0.02 * (count + 1)))
        held['marks']['edit'] = time.perf_counter()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(10, lambda: wait(count))


def wait(count):
    panel = panel_widget()
    marks = held['marks']
    waited = time.perf_counter() - marks['edit']
    key = panel.preview.image.cacheKey() if not panel.preview.image.isNull() else None
    if 'session_done' in marks and key != held['shown_before'] and 'shown' not in marks:
        marks['shown'] = time.perf_counter()
    if 'shown' in marks or waited > 30:
        base = marks['edit']
        span = lambda a, b: round(marks[b] - marks[a], 3) if a in marks and b in marks else None
        result['redraws'].append({'during_drag': held.get('dragged'), 'read_how': held.get('reuse'), 'noticed_after': span('edit', 'read_begin'), 'read_scene': span('read_begin', 'read_end'),
                                  'pack_and_send': span('submit_begin', 'submit_end'), 'session_asked_to_applied': span('session_asked', 'session_applied'),
                                  'asked_to_first_picture': span('session_asked', 'first_picture'), 'asked_to_last_picture': span('session_asked', 'session_done'),
                                  'last_picture_to_shown': span('session_done', 'shown'), 'whole': span('edit', 'shown'), 'drawn_at': list(panel._draft_fine)})
        save()
        if count < 4:
            QtCore.QTimer.singleShot(1500, lambda: edit(count + 1))
        else:
            panel.stop()
            lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(10, lambda: wait(count))


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
