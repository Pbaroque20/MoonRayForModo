# python
"""Isolated GUI test: what following the scene costs Modo's own thread while something is dragged.

A scene (MOONRAY_PROBE_SCENE) with realtime on (MOONRAY_PROBE_ENGINE, MoonLightIPR unless named). For three seconds each:
nothing is touched; the render camera is moved a little every 30 ms as a drag does; a mesh is moved the same way. Every
call of the preview's own tick is timed and profiled: that time is taken from Modo, whose viewport waits for it."""
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
out = root / 'test-results/live-cost'
out.mkdir(parents=True, exist_ok=True)
result = {'phases': []}
held = {'ticks': [], 'moves': [], 'submits': 0, 'profile': None, 'mover': None, 'offset': 0.0}
SPAN = 3000
# The phases, in order (MOONRAY_PROBE_PHASES): the first touches nothing; each other drags the camera or a mesh.
NAMES = tuple(['nothing touched'] + [word + ' dragged' for word in os.environ.get('MOONRAY_PROBE_PHASES', 'camera,mesh').split(',')] + (['release settle'] if os.environ.get('MOONRAY_PROBE_SETTLE')=='1' else []))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        # Should Modo fall over, where every thread of Python stood is written down.
        import faulthandler
        held['crash'] = open(str(out / 'crash.txt'), 'wb', 0)
        faulthandler.enable(file=held['crash'], all_threads=True)
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(os.environ.get('MOONRAY_PROBE_ENGINE', 'moonlightipr')))
        QtWidgets.QApplication.processEvents()
        tick, submit = panel._live_tick, panel.renderer.submit

        def timed():
            started = time.perf_counter()
            submissions_before = held['submits']
            held['in_tick'] = True
            if held['profile'] is not None:
                held['profile'].enable()
            try:
                return tick()
            finally:
                held['in_tick'] = False
                if held['profile'] is not None:
                    held['profile'].disable()
                elapsed=time.perf_counter() - started
                held['ticks'].append(elapsed)
                if held['submits']>submissions_before:held.setdefault('update_ticks',[]).append(elapsed)

        def counted(*a, **k):
            held['submits'] += 1
            return submit(*a, **k)
        panel._live_tick, panel.renderer.submit = timed, counted
        consume = panel.changes.consume

        def told():
            full, items = consume()
            if full or items:
                held.setdefault('told', []).append([round(time.perf_counter() - held.get('began', 0), 2), bool(full), sorted(str(i) for i in items)[:6]])
            return full, items
        panel.changes.consume = told
        # What a render's beginning costs Modo's thread when it is begun from outside the tick (one render ending
        # and the next taking its place).
        begin_pass = panel.renderer._begin_pass

        def timed_pass(*a, **k):
            started = time.perf_counter()
            inside = held.get('in_tick')
            try:
                return begin_pass(*a, **k)
            finally:
                if not inside:
                    held['outside'] = held.get('outside', 0.0) + time.perf_counter() - started
                held['passes'] = held.get('passes', 0) + 1
                held['pass_time'] = held.get('pass_time', 0.0) + time.perf_counter() - started
        panel.renderer._begin_pass = timed_pass
        # Which of Modo's notices ask for the whole scene to be read again.
        kind = type(panel.changes)
        for name in [n for n in dir(kind) if n.startswith('sil_')]:
            def wrap(inner, name=name):
                def heard(self, *a):
                    was = self.full
                    value = inner(self, *a)
                    if self.full and not was:
                        held.setdefault('whole', []).append(name)
                    return value
                return heard
            setattr(kind, name, wrap(getattr(kind, name)))
        # The timers were joined to the tick as it was: joined again to the timed one.
        panel.timer.timeout.disconnect()
        panel.timer.timeout.connect(timed)
        held['mesh'] = next((m.id for m in modo.Scene().items('mesh')), None)
        held['camera'] = modo.Scene().renderCamera.id
        result['interval_ms'] = panel.timer.interval()
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(18000, lambda: phase(0))


def phase(index):
    names = NAMES
    if index:
        close(names[index - 1])
    if index == len(names):
        if os.environ.get('MOONRAY_PROBE_SETTLE')=='1':
            panel=panel_widget()
            result['release_digest_pending']=getattr(panel,'_live_digest_pending',False)
            result['release_digest_is_string']=isinstance(panel.last_digest,str)
            from moonray_modo.host import world_matrix
            mismatches=[]
            for mesh in panel._geometry_cache['meshes']:
                identity=mesh.get('source_item') or mesh['identity'].split('|')[0]
                actual=world_matrix(modo.Scene().item(identity))
                if any(abs(a-b)>1e-5 for a,b in zip(actual,mesh['matrix'])):mismatches.append(identity)
            result['transform_mismatches']=mismatches
        panel_widget().stop()
        save()
        lx.eval('!app.quit')
        return
    held['ticks'], held['moves'], held['submits'], held['update_ticks'] = [], [], 0, []
    # Should Modo's thread stop answering, where every thread stands is written down.
    import faulthandler
    held['stuck'] = open(str(out / ('stuck_%d.txt' % index)), 'wb', 0)
    faulthandler.dump_traceback_later(2 if index == 0 else 9, file=held['stuck'])
    held['profile'] = cProfile.Profile()
    held['began'] = time.perf_counter()
    try:
        drag(index)
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
        save()
    QtCore.QTimer.singleShot(SPAN, lambda: phase(index + 1))


def drag(index):
    if NAMES[index]=='release settle':return
    if index:
        from moonray_modo import interaction
        interaction.dragging = lambda: True
        what = held['camera'] if NAMES[index].startswith('camera') else held['mesh']
        lx.eval('select.item {%s} set' % what)
        held['here'] = lx.eval('transform.channel pos.X ?')
        held['offset'] = 0.0

        def move():
            started = time.perf_counter()
            held['offset'] += 0.002
            lx.eval('transform.channel pos.X %s' % (held['here'] + held['offset']))
            held['moves'].append(time.perf_counter() - started)
        held['mover'] = QtCore.QTimer()
        held['mover'].setInterval(30)
        held['mover'].timeout.connect(move)
        held['mover'].start()


def close(name):
    import faulthandler
    faulthandler.cancel_dump_traceback_later()
    if held['mover'] is not None:
        held['mover'].stop()
        held['mover'] = None
    from moonray_modo import interaction
    interaction.dragging = lambda: False
    span = time.perf_counter() - held['began']
    ticks = sorted(held['ticks'])
    text = io.StringIO()
    pstats.Stats(held['profile'], stream=text).sort_stats('cumulative').print_stats(32)
    (out / ('profile_%s.txt' % name.replace(' ', '_'))).write_text(text.getvalue())
    held['profile'] = None
    result['phases'].append({'phase': name, 'seconds': round(span, 2), 'ticks': len(ticks), 'in_ticks_seconds': round(sum(ticks), 3),
                             'share_of_modo_thread': round(sum(ticks) / span, 3), 'tick_median_ms': round(1000 * ticks[len(ticks) // 2], 1) if ticks else None,
                             'update_tick_median_ms': round(1000 * sorted(held['update_ticks'])[len(held['update_ticks'])//2], 1) if held.get('update_ticks') else None,
                             'tick_longest_ms': round(1000 * ticks[-1], 1) if ticks else None, 'renders_asked': held['submits'],
                             'moonray_passes_begun': held.pop('passes', 0), 'pass_begin_seconds': round(held.pop('pass_time', 0.0), 3), 'of_which_outside_ticks': round(held.pop('outside', 0.0), 3),
                             'whole_asked_by': held.pop('whole', [])[:12],
                             'told_of': held.pop('told', [])[:12], 'time_now': lx.service.Selection().GetTime(),
                             'moves_made': len(held['moves']), 'moves_expected': int(span / 0.03),
                             'move_command_median_ms': round(1000 * sorted(held['moves'])[len(held['moves']) // 2], 1) if held['moves'] else None})
    save()


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
