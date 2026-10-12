# python
"""Isolated GUI test: how fast a realtime engine follows a moved item, and what MoonLightIPR's denoiser costs.

A scene (MOONRAY_PROBE_SCENE) is followed with the engine in MOONRAY_PROBE_ENGINE (moonray_ls or moonlightipr), realtime
on. An item is moved a little five times; each time, how the scene was read again and how long until the picture
changed are written down. For MoonLightIPR the time it takes to finish its picture is then taken with the scene's
denoiser off and on, Beauty being shown both times."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonlightipr')
out = root / ('test-results/realtime-cost-' + ENGINE)
out.mkdir(parents=True, exist_ok=True)
result = {'engine': ENGINE, 'moves': [], 'denoiser': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def key():
    image = panel_widget().preview.image
    return None if image.isNull() else image.cacheKey()


def begin():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
        QtWidgets.QApplication.processEvents()
        capture = panel._capture

        def timed(*a, **k):
            held['reuse'] = repr(a[0] if a else k.get('reuse', False))[:40]
            t = time.perf_counter(); value = capture(*a, **k); held['read'] = time.perf_counter() - t
            return value
        panel._capture = timed
        panel.renderer.finished.connect(lambda *a: held.__setitem__('finished', time.perf_counter()))
        held['item'] = next(m.id for m in modo.Scene().items('mesh'))
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_SETTLE', '40')) * 1000, lambda: move(0))


def move(count):
    try:
        panel = panel_widget()
        held.update(before=key(), reuse=None, read=None)
        lx.eval('select.item {%s} set' % held['item'])
        lx.eval('transform.channel pos.X %s' % (0.02 * (count + 1)))
        held['at'] = time.perf_counter()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(10, lambda: moved(count))


def moved(count):
    waited = time.perf_counter() - held['at']
    if key() != held['before'] or waited > 30:
        result['moves'].append({'read_how': held.get('reuse'), 'read_scene': round(held['read'], 3) if held.get('read') else None, 'to_first_new_picture': round(waited, 3),
                                'following': panel_widget()._following})
        save()
        if count < 4:
            QtCore.QTimer.singleShot(4000, lambda: move(count + 1))
        elif ENGINE == 'moonlightipr':
            QtCore.QTimer.singleShot(6000, lambda: denoiser(0))
        else:
            finish()
        return
    QtCore.QTimer.singleShot(10, lambda: moved(count))


def denoiser(turn):
    """MoonLightIPR to its last sample, the scene's denoiser off, then on, then off again."""
    try:
        panel = panel_widget()
        on = turn % 2 == 1
        held.pop('finished', None)
        held['at'] = time.perf_counter()
        lx.eval('moonray.render.denoiser %d' % (1 if on else 0))
        lx.eval('moonray.render.denoise_preview 1')
        held['denoiser'] = on
        # The setting alone renders again where it changes; where it does not, a nudge does.
        if turn == 0:
            lx.eval('select.item {%s} set' % held['item'])
            lx.eval('transform.channel pos.X 0.2')
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(50, lambda: denoised(turn))


def denoised(turn):
    waited = time.perf_counter() - held['at']
    panel = panel_widget()
    if ('finished' in held and held['finished'] > held['at'] + .3) or waited > 60:
        result['denoiser'].append({'denoiser_on': held['denoiser'], 'buffer': panel.buffer.currentText(), 'seconds_to_finished_picture': round((held.get('finished') or 0) - held['at'], 3) if 'finished' in held else None,
                                   'status': panel.status.text()[:60]})
        save()
        if turn < 3:
            QtCore.QTimer.singleShot(3000, lambda: denoiser(turn + 1))
        else:
            finish()
        return
    QtCore.QTimer.singleShot(20, lambda: denoised(turn))


def finish():
    try:
        panel_widget().stop()
    except Exception:
        pass
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
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
