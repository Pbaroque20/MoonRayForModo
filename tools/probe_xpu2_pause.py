# python
"""GUI test: XPU2 renders a preview with Safe Denoising on; Pause saves it where it stands, and Continue takes it up.

Two balls are previewed by XPU2 at many samples, so that the render takes a while, with Safe Denoising on. Paused some
seconds in, then continued. What the window says, what was saved, and what XPU2 says of saving and taking up are
written to test-results/xpu2-pause/report.json. Run with tools/launch_gui_probe.py --kit-source <installed kit>."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/xpu2-pause'
out.mkdir(parents=True, exist_ok=True)
result = {'began': time.strftime('%H:%M:%S')}
held = {'said': []}
# Seconds after XPU2's first checkpoint of the render that Pause is pressed.
PAUSE_AFTER = float(os.environ.get('MOONRAY_PROBE_PAUSE', '3'))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import live_panels
    return next(iter(live_panels()))


def state(panel):
    renderer = panel.renderer
    active = getattr(renderer, 'active', None) or {}
    snapshot = active.get('snapshot', {})
    base = getattr(renderer, 'current_base', None)
    folder = pathlib.Path(base).parent if base else None
    files = sorted(p.name for p in folder.iterdir()) if folder and folder.is_dir() else []
    return {'t': round(time.monotonic() - held.get('t0', time.monotonic()), 1), 'status': panel.status.text(), 'button': panel.start.text(),
            'tip': panel.start.toolTip(), 'timing': panel.render_timing.text(), 'rendering': panel._rendering,
            'pausing': getattr(panel, '_pausing', None), 'continuable': getattr(panel, '_continuable', None) is not None,
            'xpu2': snapshot.get('_xpu2'), 'safe': snapshot.get('_safe'), 'ipr': snapshot.get('_ipr'),
            'session': getattr(renderer, 'using_session', None), 'phase': getattr(renderer, 'phase', None),
            'draining': getattr(renderer, 'draining', None), 'safe_files': [str(p) for p in getattr(renderer, 'safe_files', None) or []],
            'resumable': getattr(renderer, 'resumable', None), 'folder': str(folder), 'files': files[:60]}


def said(*words, after=0):
    """What the renderers said, from the kit's terminal record, since serial after."""
    from moonray_modo import terminal
    lines = []
    for serial, _, kind, source, text in terminal.entries(after):
        for line in str(text).splitlines():
            if any(w in line for w in words) and not line.startswith('@@'):
                lines.append(line.strip()[:220])
    return lines[:40]


def mark():
    from moonray_modo import terminal
    entries = terminal.entries()
    return entries[-1][0] if entries else 0


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    if os.environ.get('MOONRAY_PROBE_DENOISER'):
        lx.eval('moonray.render.denoiser 2')
        lx.eval('moonray.render.denoise_preview 1')
    lx.eval('moonray.render.denoise_safe 1')
    lx.eval('moonray.render.xpu2_samples 4096')
    lx.eval('moonray.render.xpu2_noise 0')
    result['settings'] = {'safe': lx.eval('moonray.render.denoise_safe ?'), 'samples': lx.eval('moonray.render.xpu2_samples ?'),
                          'noise': lx.eval('moonray.render.xpu2_noise ?'), 'mode': lx.eval('moonray.render.execution_mode ?')}
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def first():
    try:
        panel = panel_widget()
        from moonray_modo import native
        result['xpu2_chosen'] = [native.xpu2(), str(native.xpu2_runtime())]
        result['engine'] = panel.preview_engine.currentData()
        if panel._rendering or panel._following:
            panel.stop()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        result['before_render'] = {'button': panel.start.text(), 'pauses_rule': panel._pauses()}
        held['t0'] = time.monotonic()
        held['mark0'] = mark()
        panel.start.click()
        result['at_render'] = state(panel)
    except Exception:
        result['first_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1000, watch)


def watch():
    try:
        panel = panel_widget()
        held['ticks'] = held.get('ticks', 0) + 1
        if held['ticks'] in (3, 8):
            result['rendering_%d' % held['ticks']] = state(panel)
        # Paused a few seconds after XPU2 has saved a checkpoint of the render.
        if not held.get('saved_tick') and said('XPU2: checkpoint', after=held['mark0']):
            held['saved_tick'] = held['ticks']
        if not panel._rendering and held['ticks'] > 5:
            result['ended_by_itself'] = state(panel)
            result['said_before_pause'] = said('XPU2', 'heckpoint', 'esum', after=held['mark0'])
            save()
            QtCore.QTimer.singleShot(100, finish)
            return
        if (held.get('saved_tick') and held['ticks'] >= held['saved_tick'] + PAUSE_AFTER) or held['ticks'] > 150:
            result['before_pause'] = state(panel)
            result['said_before_pause'] = said('heckpoint', 'esum', 'drain', 'generation 1:', 'taken up', 'begun anew', after=held['mark0'])
            held['mark_pause'] = mark()
            held['paused_at'] = time.time()
            result['keep_wait_ms'] = panel.renderer.keep_wait()
            panel.start.click()
            result['at_pause'] = state(panel)
            result['keep_wait_ms_after'] = panel.renderer.keep_wait()
            save()
            QtCore.QTimer.singleShot(1000, pausing)
            return
    except Exception:
        result['watch_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(100, finish)
        return
    QtCore.QTimer.singleShot(1000, watch)


def timed(after, *words):
    """The renderers' lines since serial after, each with its seconds since Pause was pressed."""
    from moonray_modo import terminal
    lines = []
    for serial, when, kind, source, text in terminal.entries(after):
        for line in str(text).splitlines():
            if any(w in line for w in words) and not line.startswith('@@'):
                lines.append('%+.1f s %s' % (when - held['paused_at'], line.strip()[:200]))
    return lines[:60]


def pausing():
    """Every second until the render has ended: how long the pause took to save and end."""
    try:
        panel = panel_widget()
        held['pausing'] = held.get('pausing', 0) + 1
        if held['pausing'] == 2:
            result['two_seconds_after_pause'] = state(panel)
        if panel._rendering and held['pausing'] < 300:
            QtCore.QTimer.singleShot(1000, pausing)
            return
        result['pause_took_s'] = round(time.time() - held['paused_at'], 1)
        result['pause_lines'] = timed(held['mark_pause'], 'XPU2', 'Wrote', 'Stopped', 'rror')
    except Exception:
        result['pausing_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, paused)


def paused():
    try:
        panel = panel_widget()
        result['after_pause'] = state(panel)
        result['said_at_pause'] = said('heckpoint', 'esum', 'drain', 'Drain', 'stopped', 'Stopped', 'XPU2:', after=held['mark_pause'])
        panel.window().grab().save(str(out / 'paused.png'))
        held['mark_continue'] = mark()
        panel.start.click()
        result['at_continue'] = state(panel)
    except Exception:
        result['paused_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(12000, continued)


def continued():
    try:
        panel = panel_widget()
        result['continuing'] = state(panel)
        result['said_after_continue'] = said('taken up', 'begun anew', 'esum', 'heckpoint', 'generation 1:', 'rror', after=held.get('mark_continue', 0))
        panel.window().grab().save(str(out / 'continued.png'))
        if panel._rendering:
            panel.start.click()
    except Exception:
        result['continued_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(15000, finish)


def finish():
    try:
        result['end'] = state(panel_widget())
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(6000, first)
