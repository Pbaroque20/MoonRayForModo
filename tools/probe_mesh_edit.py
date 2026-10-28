# python
"""Isolated GUI test (tools/launch_gui_probe.py, a test profile): what a realtime preview does between a mesh edit and
its picture changing. The scene in MOONRAY_PROBE_SCENE is followed by MOONRAY_PROBE_ENGINE (moonlightipr, or moonray
with IPR on); a mesh's points are moved five times through Modo's mesh editing, as a tool does; each time the edit's
classification (incremental.classify), the reading of the scene (panel._capture and host.snapshot), its digest, the
packing, the submit, and the wait until the picture changes are written down, into MOONRAY_PROBE_OUT/report.json."""
import json
import os
import pathlib
import threading
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonlightipr')
result = {'edits': [], 'kit': None, 'engine': ENGINE}
held = {'events': []}
lock = threading.Lock()


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def note(kind, seconds=None, detail=None):
    with lock:
        held['events'].append((round(time.perf_counter() - held.get('at', 0.0), 4), kind, None if seconds is None else round(seconds, 4),
                               threading.current_thread().name[:20], detail))


def wrap(owner, name, kind, show=None):
    original = getattr(owner, name)

    def timed(*a, **k):
        began = time.perf_counter()
        value = None
        try:
            value = original(*a, **k)
            return value
        finally:
            note(kind, time.perf_counter() - began, show(value) if show else None)
    setattr(owner, name, timed)


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def key():
    image = panel_widget().preview.image
    return None if image.isNull() else image.cacheKey()


def kind(value):
    if isinstance(value, dict):
        return {k: len(v) if hasattr(v, '__len__') else v for k, v in value.items()}
    return value


def begin():
    try:
        panel = panel_widget()
        from moonray_modo import moonlightipr_scene, incremental, host
        result['kit'] = moonlightipr_scene.__file__
        scene = modo.Scene()
        meshes = [(len(modo.Mesh(m).geometry.vertices), m) for m in scene.items('mesh')]
        try:
            deformers = bool(incremental.deformers(scene))
        except Exception:
            deformers = 'unknown'
        result['scene'] = {'meshes': len(meshes), 'meshInst': len(scene.items('meshInst', superType=False)),
                           'replicator': len(scene.items('replicator', superType=False)), 'deformers': deformers}
        chosen = os.environ.get('MOONRAY_PROBE_MESH')
        sized = sorted(((n, m) for n, m in meshes if n >= 500), key=lambda entry: entry[0])
        target = next((m for n, m in sized if m.name == chosen), None) if chosen else None
        if target is None:
            target = sized[len(sized) // 2][1] if sized else meshes[0][1]
        held['mesh'] = target.id
        result['mesh'] = {'name': target.name, 'vertices': len(modo.Mesh(target).geometry.vertices),
                          'polygons': len(modo.Mesh(target).geometry.polygons)}
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
        QtWidgets.QApplication.processEvents()
        if ENGINE != 'moonlightipr' and not panel.ipr_mode.isChecked():
            panel.ipr_mode.setChecked(True)
        wrap(panel, '_capture', 'read scene')
        wrap(panel, '_capture_preview', 'read scene (motion)')
        wrap(panel, '_digest', 'digest')
        wrap(panel, '_submit', 'submit')
        submit = panel._submit

        def marked(*a, **k):
            try:
                return submit(*a, **k)
            finally:
                held['submitted'] = key()
        panel._submit = marked
        wrap(moonlightipr_scene, 'pack', 'pack')
        wrap(incremental, 'classify', 'classify', kind)
        wrap(host, 'snapshot', 'snapshot')
        from moonray_modo import evaluated
        wrap(evaluated, 'capture', 'render cache', lambda data: {'timing': data.get('timing'), 'handing': data.get('handing')} if isinstance(data, dict) else None)
        if hasattr(panel, 'rt') and ENGINE == 'moonlightipr':
            panel.rt.click()
        else:
            panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_SETTLE', '90')) * 1000, lambda: edit(0))


def edit(count):
    try:
        with lock:
            held['events'] = []
        held.pop('submitted', None)
        if count == 0:
            panel = panel_widget()
            cache = panel._geometry_cache or {}
            extra = cache.get('extra_geometry') or []
            result['cache'] = {'held': panel._geometry_cache is not None, 'evaluated': cache.get('_evaluated_data') is not None,
                               'surface': panel._settings_values()['surface'],
                               'extra': [{k: (v if isinstance(v, (str, int, float, bool)) else type(v).__name__) for k, v in list(e.items())[:12]}
                                         if isinstance(e, dict) else type(e).__name__ for e in extra[:8]],
                               'extra_count': len(extra)}
        # Its points moved by Modo's move tool, in vertex mode with none selected (so all of them), as a drag lets go.
        lx.eval('select.item {%s} set' % held['mesh'])
        lx.eval('select.typeFrom vertex')
        lx.eval('select.drop vertex')
        held['at'] = time.perf_counter()
        lx.eval('tool.set TransformMove on')
        lx.eval('tool.attr xfrm.transform TY %s' % (0.002 * (count + 1)))
        lx.eval('tool.doApply')
        lx.eval('tool.set TransformMove off')
        note('edit done')
        lx.eval('select.typeFrom item')
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(5, lambda: edited(count))


def edited(count):
    waited = time.perf_counter() - held['at']
    # The picture of the edit: one shown after the scene was submitted for it.
    submitted = held.get('submitted')
    if (submitted is not None and key() != submitted) or waited > 60:
        with lock:
            events = list(held['events'])
        result['edits'].append({'to_new_picture': round(waited, 3), 'submitted': submitted is not None, 'events': events})
        save()
        if count < int(os.environ.get('MOONRAY_PROBE_EDITS', '5')) - 1:
            QtCore.QTimer.singleShot(6000, lambda: edit(count + 1))
        else:
            finish()
        return
    QtCore.QTimer.singleShot(5, lambda: edited(count))


def finish():
    try:
        panel = panel_widget()
        if hasattr(panel, 'rt') and panel.rt.isChecked():
            panel.rt.click()
        panel.stop()
    except Exception:
        pass
    save()
    lx.eval('!app.quit')


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error_open'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
