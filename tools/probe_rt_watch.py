# python
"""GUI: what the preview window does after RT is switched on. Opens MOONRAY_PROBE_SCENE, opens the preview, chooses
MoonRay (MOONRAY_PROBE_ENGINE) with the renderer in MOONRAY_PROBE_RENDERER (xpu2 by default), switches RT on, and every
5 s for MOONRAY_PROBE_WATCH seconds writes down the status lines, whether it renders, and the kit's log lines since the
last look, with a grab of the window every 30 s. Writes MOONRAY_PROBE_OUT (report.json, window-*.png)."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
result = {'looks': [], 'log': []}
held = {'zero': time.monotonic(), 'seen': 0}
WATCH = int(os.environ.get('MOONRAY_PROBE_WATCH', '240'))


def now():
    return round(time.monotonic() - held['zero'], 1)


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def log_lines():
    try:
        from moonray_modo import terminal
        entries = list(terminal.entries())
        fresh = entries[held['seen']:]
        held['seen'] = len(entries)
        return [(e[1], e[2], e[3], str(e[4])[:300]) for e in fresh]
    except Exception:
        return [traceback.format_exc()[-300:]]


def begin():
    try:
        p = panel()
        p.preferences.set('xpu2/renderer', os.environ.get('MOONRAY_PROBE_RENDERER', 'xpu2'))
        # MOONRAY_PROBE_CACHE: a cache folder of its own (empty, for a first run), the test profile's put back at the end.
        if os.environ.get('MOONRAY_PROBE_CACHE'):
            held['cache'] = p.preferences.store.value('cache_folder', '')
            p.preferences.set('cache_folder', os.environ['MOONRAY_PROBE_CACHE'])
            from moonray_modo import cache_folder
            cache_folder.forget()
            result['cache'] = str(cache_folder.root())
        p.preview_engine.setCurrentIndex(p.preview_engine.findData(os.environ.get('MOONRAY_PROBE_ENGINE', 'moonray')))
        QtWidgets.QApplication.processEvents()
        result['rt_enabled_before'] = p.rt.isEnabled()
        try:
            from moonray_modo import native
            result['rt_checks'] = {'engine_choice': p.preview_engine.currentData(), 'engine': p._engine(), 'xpu2': native.xpu2(),
                                   'renderer_setting': p.preferences.get('xpu2/renderer'), 'capable': p._rt_capable(),
                                   'output_busy': p._output_busy(), 'blocked': p._rt_blocked(), 'rendering': getattr(p, '_rendering', None)}
        except Exception:
            result['rt_checks_error'] = traceback.format_exc()[-800:]
        result['rt_tip'] = p.rt.toolTip()
        # The renderers' own lines (MoonRay's session, XPU2's, MoonLightIPR's), as they come.
        for name in ('session', 'moonlightipr', 'xpu2'):
            try:
                getattr(p.renderer, name).output.connect(lambda text, name=name: result['log'].extend(
                    (now(), name, line[:300]) for line in text.splitlines() if line.strip() and not line.startswith('@@')))
                result.setdefault('listening', []).append(name)
            except Exception:
                pass
        held['zero'] = time.monotonic()
        p.rt.click()
        result['rt_checked_after_click'] = p.rt.isChecked()
    except Exception:
        result['begin_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1000, look)


def look():
    try:
        p = panel()
        entry = {'t': now(), 'status': p.status.text(), 'info': p.image_info.text(), 'timing': p.render_timing.text(),
                 'rendering': getattr(p, '_rendering', None), 'following': getattr(p, '_following', None),
                 'rt': p.rt.isChecked(), 'image': [p.preview.image.width(), p.preview.image.height()]}
        result['looks'].append(entry)
        result['log'] += [(now(),) + tuple(line) if isinstance(line, tuple) else (now(), line) for line in log_lines()]
        if int(now()) // 30 != held.get('grabbed', -1):
            held['grabbed'] = int(now()) // 30
            p.window().grab().save(str(out / ('window-%03d.png' % int(now()))))
    except Exception:
        result.setdefault('look_errors', []).append(traceback.format_exc()[-600:])
    save()
    if now() < WATCH:
        QtCore.QTimer.singleShot(5000, look)
    else:
        try:
            if panel().rt.isChecked():
                panel().rt.click()
        except Exception:
            pass
        held['done'] = True
        if 'cache' in held:
            try:
                panel().preferences.set('cache_folder', held['cache'] or '')
            except Exception:
                pass
        save()
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))


def sample():
    """Every 2 s, where Modo's thread and the kit's other threads are in the kit: what a wait is spent on."""
    import sys
    import threading
    names = {t.ident: t.name for t in threading.enumerate()}
    while not held.get('done'):
        time.sleep(2.0)
        try:
            for ident, frame in sys._current_frames().items():
                if ident == threading.get_ident():
                    continue
                where = []
                while frame is not None and len(where) < 40:
                    code = frame.f_code
                    if 'moonray_modo' in code.co_filename:
                        where.append('%s:%d %s' % (pathlib.Path(code.co_filename).stem, frame.f_lineno, code.co_name))
                    frame = frame.f_back
                if where:
                    result.setdefault('stacks', []).append((now(), names.get(ident, str(ident))[:20], where[:8]))
        except Exception:
            pass


import threading as _threading
_threading.Thread(target=sample, name='sampler', daemon=True).start()
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    result['opened'] = now()
    lx.eval('moonray.open')
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
