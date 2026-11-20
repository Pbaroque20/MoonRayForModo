# python
"""GUI: how often a realtime preview works a sea out again. PROBE_SCENE (Downloads\\dragon_test.lxo) is opened, the
preview's engine set to PROBE_ENGINE (moonlightipr, or moonray: XPU2's realtime where XPU2 is chosen) and RT pressed.
Once the first picture is up and PROBE_SETTLE seconds (20) have passed, the render camera is moved three small steps
sideways, then dollied a third of the way in, then a light moved, PROBE_GAP seconds (10) apart, with PROBE_REST
seconds (20) after the dolly for the preview's look at the view at rest. Noted: each displaced mesh's key as
MoonLightIPR packs it (moonlightipr_scene.displaced; a key not seen before is a mesh the session displaces again),
XPU2's lines on the camera, tessellation and geometry made again, and every new picture. Writes
test-results/realtime-sea/<engine>.json (PROBE_OUT for another folder); then RT off and Modo quits."""
import json
import math
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\realtime-sea'))
out.mkdir(parents=True, exist_ok=True)
engine = os.environ.get('PROBE_ENGINE', 'moonlightipr')
scene = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\dragon_test.lxo')
SETTLE = float(os.environ.get('PROBE_SETTLE', '20'))
GAP = float(os.environ.get('PROBE_GAP', '10'))
REST = float(os.environ.get('PROBE_REST', '20'))
began, wall = time.monotonic(), time.time()
result = {'scene': scene, 'engine': engine, 'events': [], 'displaced': [], 'pictures': []}
held = {'step': 'start'}
import faulthandler
_fault = open(str(out / ('%s-fault.txt' % engine)), 'w')
faulthandler.enable(file=_fault, all_threads=True)


def now():
    return round(time.monotonic() - began, 3)


def note(kind, **extra):
    result['events'].append(dict(t=now(), step=held['step'], kind=kind, **extra))


def save():
    try:
        from moonray_modo import terminal
        result['terminal'] = ['%8.2f %s %s: %s' % (when - wall, kind, source, text[:240])
                              for _, when, kind, source, text in terminal.entries()
                              if 'XPU2' in text or 'MoonLightIPR' in text or kind in ('status', 'fail', 'end')][-500:]
    except Exception:
        result['terminal_error'] = traceback.format_exc()[-500:]
    seas = {}
    for row in result['displaced']:
        if row['sea']:
            seas.setdefault(row['mesh'], [])
            if row['key'] not in seas[row['mesh']]:
                seas[row['mesh']].append(row['key'])
    result['sea_keys'] = {name: len(keys) for name, keys in seas.items()}
    (out / ('%s.json' % engine)).write_text(json.dumps(result, indent=1, default=str))


def later(seconds, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(int(seconds * 1000), run)


def instrument():
    from moonray_modo import moonlightipr_scene, ocean
    original = moonlightipr_scene.displaced

    def displaced(*args, **kwargs):
        made = original(*args, **kwargs)
        try:
            mesh, materials = args[0], args[4]
            sea = bool(ocean.wears_ocean(mesh, materials, ocean.ocean_tags(materials)))
            if made[0] != args[1]:
                camera = args[8] if len(args) > 8 else kwargs.get('camera')
                place = (camera or {}).get('matrix')
                result['displaced'].append(dict(t=now(), step=held['step'], mesh=mesh.get('name'), sea=sea, key=made[0].hex(),
                                                limit=args[7] if len(args) > 7 else None,
                                                camera=[round(v, 3) for v in place[12:15]] if place else None))
        except Exception:
            result.setdefault('errors', []).append('displaced: ' + traceback.format_exc()[-400:])
        return made
    moonlightipr_scene.displaced = displaced


def panel():
    # The kit's own list of its panels: QApplication.allWidgets() wraps Modo's widgets too, which then crash Modo as it
    # quits (PySide invalidating them after Python is gone).
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def image_key(p):
    image = p.preview.image
    return None if image.isNull() else image.cacheKey()


def watch_pictures():
    p = panel()
    held['picture'] = image_key(p)
    timer = held['timer'] = QtCore.QTimer()
    timer.setInterval(100)

    def look():
        try:
            key = image_key(p)
            if key is not None and key != held['picture']:
                held['picture'] = key
                result['pictures'].append(dict(t=now(), step=held['step'], status=p.status.text()[:100]))
        except Exception:
            pass
    timer.timeout.connect(look)
    timer.start()


def switch_on():
    instrument()
    if os.environ.get('PROBE_KEEP_SCENES'):
        keep_scenes()
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData(engine))
    note('engine', value=p.preview_engine.currentData())
    watch_pictures()
    held['step'] = 'rt'
    note('rt on')
    p.rt.click()
    result['rt_checked'] = p.rt.isChecked()
    later(0.25, wait_first)


def wait_first(tries=[0]):
    tries[0] += 1
    if not result['pictures'] and tries[0] < 2400:
        later(0.25, wait_first)
        return
    result['first_picture'] = result['pictures'][0]['t'] if result['pictures'] else None
    save()
    later(SETTLE, sideways)


def camera():
    import modo
    return modo.Scene().renderCamera


def channel(item, name):
    lx.eval('select.item {%s} set' % item.id)
    return float(lx.eval('transform.channel %s ?' % name))


def place(item, values):
    lx.eval('select.item {%s} set' % item.id)
    for name, value in values.items():
        lx.eval('transform.channel %s %s' % (name, value))
    lx.eval('select.drop item')


def sideways(step=[0]):
    cam = camera()
    if 'start' not in held:
        held['start'] = {k: channel(cam, k) for k in ('pos.X', 'pos.Y', 'pos.Z')}
        held['distance'] = max(math.sqrt(sum(v * v for v in held['start'].values())), 1e-3)
        result['camera_start'] = held['start']
    step[0] += 1
    held['step'] = 'sideways %d' % step[0]
    x = held['start']['pos.X'] + 0.04 * held['distance'] * step[0]
    note('camera moved', value=round(x, 3))
    place(cam, {'pos.X': x})
    save()
    later(GAP, sideways if step[0] < 3 else dolly)


def dolly():
    cam = camera()
    held['step'] = 'dolly'
    values = {k: round(0.65 * held['start'][k] + (0.12 * held['distance'] if k == 'pos.X' else 0.0), 4) for k in held['start']}
    note('camera dollied', value=values)
    place(cam, values)
    save()
    later(REST, light)


def light():
    import modo
    held['step'] = 'light'
    lights = [i for i in modo.Scene().items() if 'light' in i.type.lower() and i.type.lower() not in ('lightmaterial',)]
    if lights:
        item = lights[0]
        y = channel(item, 'pos.Y')
        note('light moved', value=item.name)
        place(item, {'pos.Y': y + 0.02 * held['distance']})
    else:
        note('no light')
    save()
    later(GAP, finish)


def keep_scenes():
    """PROBE_KEEP_SCENES: every scene text the session hands its renderer (XPU2's realtime), kept in
    <engine>-scenes/NNN-<suffix>.rdla, for telling what changed from one to the next."""
    from moonray_modo import persistent
    kept = out / ('%s-scenes' % engine)
    kept.mkdir(exist_ok=True)
    for old in kept.glob('*.rdla'):
        old.unlink()
    write_scene = persistent.Session._write_scene
    count = [0]

    def _write_scene(self, request, suffix, text, payload=None):
        count[0] += 1
        if count[0] <= 60:
            try:
                (kept / ('%03d-%s.rdla' % (count[0], suffix))).write_bytes(payload if payload is not None else text.encode('utf-8'))
                note('scene written', value='%03d-%s %s' % (count[0], suffix, held['step']))
            except Exception:
                result.setdefault('errors', []).append('keep: ' + traceback.format_exc()[-300:])
        return write_scene(self, request, suffix, text, payload)
    persistent.Session._write_scene = _write_scene


def finish():
    if result.get('done'):
        return
    held['step'] = 'end'
    # The picture watch stopped before Modo quits: a timer reading the panel while Modo takes its windows down.
    timer = held.pop('timer', None)
    if timer is not None:
        timer.stop()
    try:
        p = panel()
        result['status_at_end'] = p.status.text()
        p.preview.image.save(str(out / ('%s-end.png' % engine)))
        if p.rt.isChecked():
            p.rt.click()
    except Exception:
        result.setdefault('errors', []).append('finish: ' + traceback.format_exc()[-400:])
    result['done'] = True
    save()
    # Let quit, not killed: a test Modo killed asks at its next start about the work it lost.
    QtCore.QTimer.singleShot(4000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % scene)
    result['opened_at'] = now()
    lx.eval('moonray.page preview')
    later(8, switch_on)
except Exception:
    result['errors'] = [traceback.format_exc()]
    result['done'] = True
save()
