# python
"""Isolated GUI test: a MoonRay preview with Safe Denoising on comes out as one without it does, and begins empty.

A scene is opened (the path in MOONRAY_PROBE_SCENE, else two balls are made) and previewed with MoonRay twice with a
denoiser on: first with Safe Denoising off, then with it on. Each time the view is looked at once a second: whether it
is empty just after Render is pressed, how many different pictures it shows, and how rough the beauty is at the end.
The two final beauties are saved and compared."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/safe-converges'
out.mkdir(parents=True, exist_ok=True)
result = {'runs': {}}
held = {}
# name:safe, comma separated.
RUNS = [(n, int(s)) for n, s in (entry.split(':') for entry in os.environ.get('MOONRAY_PROBE_RUNS', 'plain:0,safe:1').split(','))]
SAMPLES = int(os.environ.get('MOONRAY_PROBE_SAMPLES', '0'))
LIMIT = int(os.environ.get('MOONRAY_PROBE_LIMIT', '300'))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def rough(image):
    """How grainy a picture is: the mean difference between each pixel and the mean of its four neighbours."""
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())
    total = count = 0
    for y in range(2, h - 2, 3):
        row = y * stride
        for x in range(2, w - 2, 3):
            i = row + x * 3 + 1
            total += abs(4 * data[i] - data[i - 3] - data[i + 3] - data[i - stride] - data[i + stride])
            count += 1
    return total / max(count, 1) / 4.0


RING = [(6, 0), (6, 2), (4, 4), (2, 6), (0, 6), (-2, 6), (-4, 4), (-6, 2), (-6, 0), (-6, -2), (-4, -4), (-2, -6), (0, -6), (2, -6), (4, -4), (6, -2)]


def blotch(image):
    """The deepest dark mark in a picture: how far the darkest pixel lies below the mean of a ring of pixels six away
    from it. A smooth picture has none to speak of; a pixel the denoiser smeared from one caught too dark stands out."""
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())
    worst = count = 0
    for y in range(8, h - 8, 2):
        row = y * stride
        for x in range(8, w - 8, 2):
            i = row + x * 3 + 1
            ring = [data[i + dx * 3 + dy * stride] for dx, dy in RING]
            # Only where the whole ring around is itself even: an edge is not a mark, nor is a line running through.
            if max(ring) - min(ring) > 10:
                continue
            dip = sum(ring) / len(ring) - data[i]
            if dip > 6:
                count += 1
            worst = max(worst, dip)
    return [round(worst, 1), count]


def apart(a, b):
    a = a.convertToFormat(QtGui.QImage.Format_RGB888); b = b.convertToFormat(QtGui.QImage.Format_RGB888)
    if a.size() != b.size():
        return None
    x, y = bytes(a.constBits()), bytes(b.constBits())
    return sum(abs(p - q) for p, q in zip(x[::7], y[::7])) / max(len(x[::7]), 1)


try:
    scene = os.environ.get('MOONRAY_PROBE_SCENE', '')
    if scene:
        lx.eval('scene.open {%s} normal' % scene)
    else:
        for x in (-.6, .6):
            lx.eval('select.typeFrom item')
            lx.eval('item.create mesh')
            lx.eval('tool.set prim.sphere on')
            lx.eval('tool.attr prim.sphere cenX %s' % x)
            lx.eval('tool.apply')
            lx.eval('tool.set prim.sphere off')
    if SAMPLES:
        lx.eval('moonray.render.samples %d' % SAMPLES)
    lx.eval('moonray.render.denoiser 2')
    lx.eval('moonray.render.denoise_preview 1')
    result['settings'] = {'samples': lx.eval('moonray.render.samples ?'), 'sampling_mode': lx.eval('moonray.render.sampling_mode ?'), 'denoiser': lx.eval('moonray.render.denoiser ?')}
    lx.eval('moonray.render.denoise_safe 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def first():
    try:
        panel = panel_widget()
        held['stored'] = panel.preferences.store.value('runtime', '')
        held['engine'] = panel.preview_engine.currentData()
        held['live'] = panel.ipr_mode.isChecked()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0350-pool')))
        panel.ipr_mode.setChecked(False)
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
    except Exception:
        result['first_error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(1500, begin)


def begin():
    try:
        panel = panel_widget()
        name, safe = RUNS[len(result['runs'])]
        lx.eval('moonray.render.denoise_safe %d' % safe)
        held['saves'] = []
        held.update(name=name, began=time.time(), seen=[], last=None, idle=0)
        held['before'] = None if panel.preview.image.isNull() else panel.preview.image.cacheKey()
        result['runs'][name] = run = {'buffer_at_start': panel.buffer.currentData(), 'button_at_start': panel.start.text()}
        panel.start.click()
        QtWidgets.QApplication.processEvents()
        run['empty_after_click'] = panel.preview.image.isNull()
    except Exception:
        result['begin_error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(1000, watch)


def watch():
    try:
        panel = panel_widget()
        run = result['runs'][held['name']]
        now = round(time.time() - held['began'], 1)
        image = panel.preview.image
        key = None if image.isNull() else image.cacheKey()
        if key != held['last']:
            held['last'] = key
            stale = key is not None and key == held['before']
            held['seen'].append([now, panel.buffer.currentData(), 'stale' if stale else 'empty' if key is None else round(rough(image), 2)])
        files = [pathlib.Path(str(p) + '.safe.exr') for p in getattr(panel.renderer, 'safe_files', [])]
        times = [p.stat().st_mtime for p in files if p.is_file()]
        if times and len(times) == len(files):
            # When a save ended, and how long its files took to write.
            entry = [round(max(times) - held['began'], 1), round(max(times) - min(times), 1)]
            if not held['saves'] or held['saves'][-1][0] != entry[0]:
                held['saves'].append(entry)
        held['idle'] = 0 if panel._rendering else held['idle'] + 1
        # Three seconds after the render has ended, so that the denoised picture has come.
        if held['idle'] >= 4 or now > LIMIT:
            run['seen'] = held['seen']
            run['pictures'] = len(held['seen'])
            run['saves'] = held['saves']
            run['files'] = len(files)
            run['timing_before_stop'] = panel.render_timing.text()
            run['ended'] = [now, panel.status.text(), panel.render_timing.text(), panel.start.text(), panel.buffer.currentData(), panel._buffer_picked]
            run['interval'] = getattr(panel.renderer, 'safe_minutes', None) if RUNS[len(result['runs']) - 1][1] else None
            if panel._rendering:
                # Stopped as the user stops it, so that what is kept of a render part way is seen too.
                panel.start.click()
                run['at_stop'] = panel.status.text()
                held['stop_at'] = time.time(); held['stop_took'] = None
            panel.window().grab().save(str(out / (held['name'] + '-window.png')))
            def until_stopped():
                if held.get('stop_at') and held.get('stop_took') is None:
                    if not panel_widget()._rendering:
                        held['stop_took'] = round(time.time() - held['stop_at'], 2)
                    else:
                        QtCore.QTimer.singleShot(50, until_stopped)
            until_stopped()
            QtCore.QTimer.singleShot(40000, stopped)
            return
    except Exception:
        result['watch_error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    save()
    QtCore.QTimer.singleShot(1000, watch)


def stopped():
    # (How long the stop took is taken by the watcher below, which runs till the window says it has stopped.)
    """Well after the stop: what the window has kept, and whether the denoised picture is the render's own."""
    try:
        panel = panel_widget()
        run = result['runs'][held['name']]
        frame = panel.renderer.buffers.frame or {}
        run['kept'] = {'status': panel.status.text(), 'button': panel.start.text(), 'buffer': panel.buffer.currentData(), 'rendering': panel._rendering,
                       'info': panel.image_info.text(), 'loaded': bool(getattr(panel.renderer, 'using_session', False)), 'behind': getattr(panel.renderer, 'kept_behind', None),
                       'saving': 'saving the picture as it renders' in str(getattr(panel.renderer, 'log', '')),
                       'files': sorted(frame.get('files', {}))[:6], 'denoised': 'denoised_beauty' in frame.get('files', {}), 'timing': panel.render_timing.text()}
        shown = panel.preview.image.copy()
        held['shown'] = shown
        run['shown'] = [panel.buffer.currentData(), None if shown.isNull() else round(rough(shown), 2)]
        run['marks'] = None if shown.isNull() else blotch(shown)
        if not shown.isNull():
            shown.save(str(out / ('%s-shown-%s.png' % (held['name'], os.environ.get('MOONRAY_MODO_STOP_TAKES', '5')))))
        run['stop_took'] = held.get('stop_took')
        # What was kept, each buffer as a file of its own, to see which a mark is in.
        import shutil
        for key, path in (frame.get('files') or {}).items():
            try:
                shutil.copyfile(str(path), str(out / ('%s-kept-%s%s' % (held['name'], key, pathlib.Path(str(path)).suffix))))
            except Exception as exc:
                run.setdefault('kept_copy_errors', []).append(str(exc)[:80])
        panel.window().grab().save(str(out / (held['name'] + '-stopped.png')))
        # The beauty itself, apart from the denoiser, is what the runs are compared by.
        panel.buffer.setCurrentIndex(panel.buffer.findData('beauty'))
    except Exception:
        result['stopped_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, beauty)


def beauty():
    try:
        panel = panel_widget()
        run = result['runs'][held['name']]
        image = panel.preview.image.copy()
        held[held['name'] + '_beauty'] = image
        image.save(str(out / (held['name'] + '-beauty.png')))
        run['beauty'] = [image.width(), image.height(), round(rough(image), 3)]
        # The denoised picture is of this beauty, the same way up: far nearer to it than to it turned over.
        shown = held.get('shown')
        if shown is not None and not shown.isNull() and shown.size() == image.size():
            run['denoised_against_beauty'] = [round(apart(shown, image), 2), round(apart(shown, image.mirrored(False, True)), 2)]
        log = str(getattr(panel.renderer, 'log', ''))
        (out / (held['name'] + '-log.txt')).write_text('\n'.join(line for line in log.splitlines() if 'Rendering [' not in line and not line.startswith('@@')), encoding='utf-8', errors='replace')
        run['log'] = [line[:160] for line in log.splitlines() if ('ample' in line or 'heckpoint' in line) and 'Rendering [' not in line and not line.startswith('@@')][-12:]
        if len(result['runs']) < len(RUNS):
            # Back to how a finished render leaves the window, then the same again with Safe Denoising on.
            panel.buffer.setCurrentIndex(panel.buffer.findData('denoised_beauty'))
            panel._buffer_picked = None
            save()
            QtCore.QTimer.singleShot(2500, begin)
            return
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
        panel.ipr_mode.setChecked(held['live'])
    except Exception:
        result['beauty_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


def switch():
    try:
        lx.eval('moonray.render.denoise_safe 1')
        result['safe_on'] = lx.eval('moonray.render.denoise_safe ?')
    except Exception:
        result['switch_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, begin)


QtCore.QTimer.singleShot(6000, first)
