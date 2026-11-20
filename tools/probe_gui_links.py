# python
"""GUI: the Links panel (links.py, links_window.py) in a test Modo, end to end.

A scene of a red box and a blue pillar on a floor, saved; the panel opened (MoonRay > Links). Rendered embedded with
MoonLightIPR and with XPU2; the box and the pillar linked (proxies), rendered again and compared; the box brought back
to edit (Edit in Scene), its points moved up; the scene saved with Modo's own scene.save, which should write the box's
file (links.watch_saves, after_save); the box made a proxy again (Done Editing) and rendered. The panel is pictured at
each state. PROBE_HIDE=1 also hides a polygon of the box being edited and updates it (the round trip). Modo then quits:
its exit code says whether it quit cleanly with proxies in the scene.

Written to test-results/links/gui (PROBE_OUT): gui.json, panel-*.png and the renders."""
import json
import os
import pathlib
import shutil
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\gui'))
if out.exists():
    shutil.rmtree(str(out), ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
began = time.monotonic()
wall = time.time()
result = {'steps': []}
held = {}
import faulthandler
_fault = open(str(out / 'fault.txt'), 'w')
faulthandler.enable(file=_fault, all_threads=True)


def save():
    try:
        from moonray_modo import terminal
        result['terminal'] = ['%8.2f %s %s: %s' % (when - wall, kind, source, text[:260]) for _, when, kind, source, text in terminal.entries()
                              if kind in ('status', 'fail', 'end', 'command', 'note') or 'MoonLightIPR' in text or 'rror' in text][-300:]
    except Exception:
        result['terminal_error'] = traceback.format_exc()[-300:]
    (out / 'gui.json').write_text(json.dumps(result, indent=1, default=str))


def note(step, **extra):
    from moonray_modo import links
    rows = links.rows()
    result['steps'].append(dict(t=round(time.monotonic() - began, 2), step=step,
                                rows=[(r['name'], r['state'], r['status'], r['file']) for r in rows],
                                selected=[i.name for i in modo.Scene().selected], **extra))
    _fault.write(step + '\n')
    _fault.flush()
    save()


def later(seconds, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(int(seconds * 1000), run)


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def window():
    from moonray_modo import links_window
    return links_window._window


def picture(name):
    w = window()
    if w is not None:
        w.refresh()
        w.grab().save(str(out / ('panel-%s.png' % name)))


def mesh(name):
    found = [i for i in modo.Scene().items() if i.name == name and i.type in ('mesh', 'proxy')]
    return found[0] if found else None


def cube(name, place, size, colour):
    lx.eval('item.create mesh {%s}' % name)
    item = [i for i in modo.Scene().items('mesh') if i.name == name][0]
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 4' % axis)
    for axis, value in zip('XYZ', size):
        lx.eval('tool.attr prim.cube size%s %s' % (axis, value))
    lx.eval('tool.attr prim.cube cenY %s' % (size[1] / 2.0))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s} {%s} 0.8 0.04 true false' % (name, colour))
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    item.position.set(place)
    return item


def difference(a, b):
    """Mean difference of two pictures' colours (0-255) and the share of pixels differing by more than 24."""
    one, two = QtGui.QImage(str(a)), QtGui.QImage(str(b))
    if one.isNull() or two.isNull() or one.size() != two.size():
        return None
    total, far, count = 0, 0, 0
    for y in range(0, one.height(), 2):
        for x in range(0, one.width(), 2):
            p, q = one.pixel(x, y), two.pixel(x, y)
            d = (abs(((p >> 16) & 255) - ((q >> 16) & 255)) + abs(((p >> 8) & 255) - ((q >> 8) & 255)) + abs((p & 255) - (q & 255))) / 3.0
            total += d
            far += d > 24
            count += 1
    return {'mean': round(total / count, 2), 'far': round(far / count, 4)}


def render(engine, name, then):
    p = panel()
    if engine == 'xpu2':
        p.preferences.set('xpu2/renderer', 'xpu2')
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray'))
    else:
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    before = None if p.preview.image.isNull() else p.preview.image.cacheKey()
    p.render_once()
    started = time.monotonic()

    def wait():
        q = panel()
        spent = time.monotonic() - started
        # A new picture, and the render ended (MoonLightIPR packs a changed scene first, its flag down meanwhile).
        fresh = not q.preview.image.isNull() and q.preview.image.cacheKey() != before
        if ((getattr(q, '_rendering', False) or not fresh) and spent < 120) or spent < 6:
            later(1.0, wait)
            return

        def grab():
            path = out / ('%s-%s.png' % (name, engine))
            q.preview.image.save(str(path))
            result.setdefault('renders', {})['%s-%s' % (name, engine)] = {'seconds': round(spent, 1), 'status': q.status.text()[:120]}
            save()
            then()
        later(2.0, grab)
    later(2.0, wait)


# ---- The steps. ----------------------------------------------------------------------------------------------------

def start():
    lx.eval('moonray.links')
    note('panel opened', window=window() is not None)
    picture('embedded')
    render('moonlightipr', 'embedded', lambda: render('xpu2', 'embedded', link))


def link():
    from moonray_modo import links
    started = time.monotonic()
    if os.environ.get('PROBE_NATIVE'):
        # Modo's own Convert to Proxy alone, none of the panel's steps (whether Modo quits cleanly then).
        made = []
        folder = links.default_folder(modo.Scene().filename)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('Box', 'Pillar'):
            item = mesh(name)
            lx.eval('select.item {%s} set' % item.id)
            lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (item.id, folder / (name + '.lxo')))
            made.append(name)
    else:
        made = links.run('link', [mesh('Box').id, mesh('Pillar').id], links.default_folder(modo.Scene().filename))
    note('linked', seconds=round(time.monotonic() - started, 2), made=made)
    picture('linked')
    # PROBE_STOP=link: quit once the linked scene is rendered (whether Modo quits cleanly without Edit in Scene).
    render('moonlightipr', 'linked', lambda: render('xpu2', 'linked', finish if os.environ.get('PROBE_STOP') == 'link' else edit))


def edit():
    from moonray_modo import links
    shaders = len(links._shaders())
    links.run('edit', [mesh('Box').id])
    box = mesh('Box')
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('select.type vertex')
    lx.eval('select.all')
    # Its points raised 0.4 and stretched up (the move tool: vert.move sets where points are, in the GUI).
    lx.eval('tool.set xfrm.move on')
    lx.eval('tool.attr xfrm.move Y 0.4')
    lx.eval('tool.doApply')
    lx.eval('tool.set xfrm.move off')
    lx.eval('select.drop vertex')
    lx.eval('select.type item')
    note('edited in the scene', shaders_before=shaders, shaders_after=len(links._shaders()))
    picture('editing')
    held['stamp'] = links.stamp(links.read_tag(mesh('Box'))['file'])
    lx.eval('scene.save')
    note('scene.save run')
    later(3.0, saved)


def saved():
    from moonray_modo import links
    record = links.read_tag(mesh('Box'))
    note('after the save', file_written=links.stamp(record['file']) != held['stamp'])
    picture('saved')
    if os.environ.get('PROBE_HIDE'):
        box = mesh('Box')
        geometry = box.geometry
        lx.eval('select.drop item')
        lx.eval('select.item {%s} set' % box.id)
        lx.eval('select.type polygon')
        geometry.polygons.select([geometry.polygons[0]], replace=True)
        del geometry
        lx.eval('hide.sel')
        lx.eval('select.type item')
        box = mesh('Box')
        lx.eval('select.item {%s} set' % box.id)
        lx.eval('transform.channel pos.Z 0.2')
        kept = box.id
        written = links.run('update', [box.id])
        note('hidden polygon, updated', written=written, new_item=written != [kept])
    render('moonlightipr', 'editing', done)


def done():
    from moonray_modo import links
    links.run('done', [mesh('Box').id])
    note('done editing')
    picture('done')
    render('moonlightipr', 'done', compare)


def compare():
    for engine in ('moonlightipr', 'xpu2'):
        result.setdefault('compare', {})['embedded-vs-linked-' + engine] = difference(out / ('embedded-%s.png' % engine), out / ('linked-%s.png' % engine))
    result['compare']['editing-vs-done-moonlightipr'] = difference(out / 'editing-moonlightipr.png', out / 'done-moonlightipr.png')
    result['compare']['embedded-vs-done-moonlightipr'] = difference(out / 'embedded-moonlightipr.png', out / 'done-moonlightipr.png')
    save()
    finish()


def finish():
    if result.get('done'):
        return
    result['done'] = True
    try:
        panel().stop()
    except Exception:
        pass
    save()
    # Let quit, not killed: whether Modo quits cleanly with proxies in the scene.
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.new')
    floor = cube('Floor', [0.0, -0.05, 0.0], [8.0, 0.1, 8.0], '0.6 0.6 0.6')
    cube('Box', [-1.2, 0.0, 0.0], [1.0, 1.0, 1.0], '0.8 0.1 0.1')
    cube('Pillar', [1.2, 0.0, 0.0], [0.6, 2.0, 0.6], '0.1 0.2 0.8')
    render_item = modo.Scene().renderItem
    for name, value in (('resX', 480), ('resY', 270)):
        render_item.channel(name).set(value)
    camera = modo.Scene().renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    for channel, value in (('pos.X', 0), ('pos.Y', 2.2), ('pos.Z', 6.5), ('rot.X', -14), ('rot.Y', 0)):
        lx.eval('transform.channel %s %s' % (channel, value))
    lx.eval('select.drop item')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    lx.eval('moonray.open')
    p = panel()
    p.preferences.set('preview_fraction', 1)
    note('made')
except Exception:
    result['error'] = traceback.format_exc()
    save()
later(8.0, start)
