# python
"""GUI test: with Show Buckets on, an XPU2 preview fills the tiles where the GPU handed samples on, orange where it
deferred them to the CPU and blue where its provisional samples wait to be rendered again in full, and each goes once
it has been (viewer.py handoff, xpu2_session.cc Outlines).

The scene: two dense spheres, which XPU2_SESSION_GPU_GEOMETRY_MB=1 (set for the test Modo by the caller) leaves to the CPU
lane, so that the GPU defers the samples that meet them; and, where PROBE_TEXTURE names a large image, a plane in front
wearing it as its diffuse colour, read a level up while its tiles land (provisional; XPU2_SESSION_FINE_BUDGET_MB makes the
texture cache small). Every 100 ms the preview's handed-on tiles are noted; pictures of the preview are saved at the
most of each kind and once all have gone. Writes test-results/handoff-overlay/report.json and *.png.
Run with tools/launch_gui_probe.py --kit-source <a kit whose runtime-xpu2 holds the new session>."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui

root = pathlib.Path(os.environ.get('PROBE_ROOT', r'C:\Users\Raphael Tobar\MoonRayForModo'))
out = root / 'test-results/handoff-overlay'
out.mkdir(parents=True, exist_ok=True)
result = {'began': time.strftime('%H:%M:%S'), 'env': {k: os.environ.get(k) for k in ('XPU2_SESSION_GPU_GEOMETRY_MB', 'XPU2_SESSION_FINE_BUDGET_MB', 'PROBE_TEXTURE')},
          'samples': []}
held = {'most': {}, 'seen': {}}
SECONDS = float(os.environ.get('PROBE_SECONDS', '150'))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import live_panels
    return next(iter(live_panels()))


def said(*words):
    from moonray_modo import terminal
    lines = []
    for serial, _, kind, source, text in terminal.entries(held.get('mark', 0)):
        for line in str(text).splitlines():
            if any(w in line for w in words) and not line.startswith('@@'):
                lines.append(line.strip()[:240])
    return lines[:60]


def told():
    """How many of XPU2's handed-on lines the kit's terminal record holds, by kind: with tiles, and with none."""
    from moonray_modo import terminal
    counts = {}
    for serial, _, kind, source, text in terminal.entries(held.get('mark', 0)):
        for line in str(text).splitlines():
            for word in ('@@MODO_DEFERRED_TILES', '@@MODO_PROVISIONAL_TILES'):
                if line.startswith(word + ' '):
                    key = word[7:].lower() + (' with tiles' if len(line.split()) > 4 else ' empty')
                    counts[key] = counts.get(key, 0) + 1
    return counts


def picture(name):
    """The preview as drawn (its own frame buffer), and the picture with the handed-on tiles laid over it as the
    preview lays them (for a window that cannot be read back while minimized)."""
    panel = panel_widget()
    view = panel.preview
    try:
        view.grabFramebuffer().save(str(out / (name + '-widget.png')))
    except Exception:
        result.setdefault('picture_errors', []).append(traceback.format_exc()[-300:])
    if not view.image.isNull():
        laid = view.image.convertToFormat(QtGui.QImage.Format_ARGB32)
        painter = QtGui.QPainter(laid)
        width, height = laid.width(), laid.height()
        for kind in ('provisional', 'deferred'):
            told_ = view.handoff.get(kind)
            if not told_ or (told_[0], told_[1]) != (width, height):
                continue
            colour = QtGui.QColor(*view.HANDOFF_COLOURS[kind])
            for x0, y0, x1, y1 in told_[2]:
                painter.fillRect(QtCore.QRectF(x0, height - y1, x1 - x0, y1 - y0), colour)
        painter.end()
        laid.save(str(out / (name + '-laid.png')))


try:
    scene = modo.Scene()
    for x in (-.55, .55):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        for name, value in (('cenX', x), ('cenY', 0), ('cenZ', 0), ('sizeX', .5), ('sizeY', .5), ('sizeZ', .5), ('sides', 384), ('segments', 192)):
            lx.eval('tool.attr prim.sphere %s %s' % (name, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    texture = os.environ.get('PROBE_TEXTURE')
    if texture:
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        plane = scene.selected[0]
        lx.eval('tool.set prim.cube on')
        for name, value in (('cenX', 0), ('cenY', -0.3), ('cenZ', 0.7), ('sizeX', 1.6), ('sizeY', 0.5), ('sizeZ', 0.02)):
            lx.eval('tool.attr prim.cube %s %s' % (name, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        uv = None
        maps = modo.Mesh(plane).geometry.vmaps.uvMaps
        if maps:
            uv = maps[0].name
        lx.eval('clip.addStill {%s}' % texture)
        clip = [c for c in scene.items('videoStill')][-1]
        render = scene.renderItem
        image = scene.addItem('imageMap')
        image.setParent(render, len(render.children()))
        image.channel('effect').set('diffColor')
        locator = scene.addItem('txtrLocator')
        image.itemGraph('shadeLoc') >> locator.itemGraph('shadeLoc')
        locator.channel('projType').set('uv')
        if uv:
            locator.channel('uvMap').set(uv)
        lx.eval('select.item {%s} set' % image.id)
        lx.eval('texture.setIMap {%s}' % clip.name)
        result['texture'] = {'clip': clip.name, 'uv': uv}
    lx.eval('moonray.render.xpu2_samples %s' % os.environ.get('PROBE_SAMPLES', '64'))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def first():
    try:
        panel = panel_widget()
        from moonray_modo import native, terminal
        result['xpu2_chosen'] = [native.xpu2(), str(native.xpu2_runtime())]
        panel.preferences.set('xpu2/renderer', 'xpu2')
        panel.preferences.set('idle_release_minutes', 0)
        if panel._rendering or panel._following:
            panel.stop()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.show_buckets.setChecked(True)
        panel.worker_tiles.setChecked(True)
        result['buckets_tip'] = panel.show_buckets.toolTip()
        entries = terminal.entries()
        held['mark'] = entries[-1][0] if entries else 0
        held['t0'] = time.monotonic()
        panel.start.click()
    except Exception:
        result['first_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(100, finish)
        return
    save()
    QtCore.QTimer.singleShot(100, watch)


def watch():
    try:
        panel = panel_widget()
        view = panel.preview
        t = round(time.monotonic() - held['t0'], 2)
        now = {kind: len(view.handoff[kind][2]) if kind in view.handoff else 0 for kind in ('deferred', 'provisional')}
        if any(now.values()) or held.get('last') != now:
            result['samples'].append({'t': t, **now, 'shown': bool(view.handoff_rects())})
        held['last'] = now
        for kind, n in now.items():
            if n:
                held['seen'].setdefault(kind, t)
                held['seen'][kind + ' last'] = t
                if n > held['most'].get(kind, 0):
                    held['most'][kind] = n
                    if not held.get('pictured_' + kind) or n >= 2 * held.get('pictured_' + kind):
                        held['pictured_' + kind] = n
                        picture('most-' + kind)
        result['seen'] = held['seen']
        result['most'] = held['most']
        ended = not panel._rendering and t > 5
        if ended or t > SECONDS:
            result['ended'] = {'t': t, 'by_itself': ended, 'status': panel.status.text(), 'handoff_left': {k: len(v[2]) for k, v in view.handoff.items()}}
            if not ended:
                panel.start.click()
            QtCore.QTimer.singleShot(3000, closing)
            return
        if len(result['samples']) % 50 == 0:
            save()
    except Exception:
        result['watch_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(100, finish)
        return
    QtCore.QTimer.singleShot(100, watch)


def closing():
    try:
        panel = panel_widget()
        view = panel.preview
        result['after_end'] = {'handoff_left': {k: len(v[2]) for k, v in view.handoff.items()}, 'status': panel.status.text()}
        picture('after-end')
        result['lines'] = told()
        result['xpu2_said'] = said('deferred to the CPU', 'provisional samples', 'cells by suitability', 'left to the CPU', 'FALLBACK',
                                   'fallback', 'generation', 'geometry', 'rror')
    except Exception:
        result['closing_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, finish)


def finish():
    if result.get('finished'):
        return
    result['finished'] = time.strftime('%H:%M:%S')
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, first)
