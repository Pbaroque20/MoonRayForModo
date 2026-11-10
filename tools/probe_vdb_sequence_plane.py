# python
"""GUI: a tester's report. A VDB sequence (EmberGen's explosion, static unticked) renders, but with a plane added an error
comes and nothing is rendered; and XPU2 falls back to XPU for the sequence where a static file stays on XPU2. A VDB shape
and volume as Load VDB File makes them, the sequence's frame 40, a plane beneath it; rendered at frame 40 with MoonRay
(XPU2) and then MoonLightIPR, each status and the Render Log's last lines kept. PLANE=0 leaves the plane out.
Writes test-results/vdb-plane/report.json."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\vdb-plane')
out.mkdir(parents=True, exist_ok=True)
result = {'runs': {}}
CHOSEN = r'C:\Users\Raphael Tobar\Downloads\Midair_Explosion_01\Midair_Explosion_01\embergen_midair_explosion_a_40.vdb'
ENGINES = ['moonray', 'moonlightipr']
state = {'index': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def build():
    import modo
    from moonray_modo import entities
    scene = modo.Scene()
    prefix = entities.CHANNEL_PREFIX
    shape = scene.addItem(entities.item_type('VdbGeometry'), name='Explosion')
    volume = scene.addItem(entities.item_type('VdbVolume'), name='Fire')
    for key, value in (('model', CHOSEN.replace('\\', '/')), ('emission_grid', 'temperature'), ('density_grid', 'density'),
                       ('modo_volume', volume.name), ('static', int(os.environ.get('STATIC', '0'))),
                       ('modo_blackbody', int(os.environ.get('BLACKBODY', '0')))):
        shape.channel(prefix + key).set(value)
    if os.environ.get('PLANE', '1') != '0':
        plane = scene.addMesh('Plane')
        with plane.geometry as geometry:
            size = 400.0
            points = [geometry.vertices.new((x, -50.0, z)) for x, z in ((-size, -size), (size, -size), (size, size), (-size, size))]
            geometry.polygons.new(points)
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    for channel, value in (('pos.X', 0), ('pos.Y', 80), ('pos.Z', 500), ('rot.X', -5)):
        lx.eval('transform.channel %s %s' % (channel, value))
    lx.eval('select.drop item')
    for name, value in (('resX', 480), ('resY', 270)):
        scene.renderItem.channel(name).set(value)
    lx.eval('select.time %s' % (40 / float(scene.fps)))
    result['plane'] = os.environ.get('PLANE', '1') != '0'
    result['shape'] = {key: shape.channel(prefix + key).get() for key in ('model', 'static')}


def enabled(name):
    """Whether a command (a render setting's) is enabled now, as its form control shows it."""
    try:
        service = lx.service.Command()
        command = lx.object.Command(service.Spawn(lx.symbol.iCTAG_NULL, name))
        command.Enable(lx.object.Message(lx.service.Message().Allocate()))
        return True
    except Exception:
        return False


def sampling_state():
    return {key: enabled('moonray.render.' + key) for key in ('xpu2_samples', 'xpu2_noise', 'samples', 'max_adaptive_samples')}


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def begin():
    try:
        p = panel()
        engine = ENGINES[state['index']]
        p.preview_engine.setCurrentIndex(p.preview_engine.findData(engine))
        if engine == 'moonlightipr':
            p.preferences.set('moonlightipr/render_samples', 32)
        state['began'] = time.monotonic()
        state['statuses'] = []
        result.setdefault('sampling_before', sampling_state())
        QtCore.QTimer.singleShot(1500, lambda: (p.start.click(), QtCore.QTimer.singleShot(1000, watch)))
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def watch():
    try:
        p = panel()
        text = p.status.text()
        if not state['statuses'] or state['statuses'][-1] != text:
            state['statuses'].append(text)
        if getattr(p, '_rendering', False) and time.monotonic() - state['began'] < 300:
            QtCore.QTimer.singleShot(500, watch); return
        engine = ENGINES[state['index']]
        entry = {'sampling_enabled': sampling_state(), 'seconds': round(time.monotonic() - state['began'], 1), 'statuses': state['statuses'],
                 'label': p.image_info.text(), 'backend': getattr(p.renderer, 'backend_status', None),
                 'fallback': getattr(p.renderer, 'fallback_mode', None)}
        try:
            from moonray_modo import terminal
            lines = [str(e[4]) for e in terminal.entries() if not str(e[4]).startswith('@@')]
            entry['log'] = [line[:300] for line in lines if any(w in line.lower() for w in ('error', 'fall', 'xpu', 'vdb', 'cannot', 'fail'))][-25:]
        except Exception as error:
            entry['log'] = str(error)
        if p.preview.image is not None and not p.preview.image.isNull():
            p.preview.image.save(str(out / ('%s%s.png' % (engine, '' if result.get('plane') else '-noplane'))))
        result['runs'][engine] = entry
        save()
        state['index'] += 1
        if state['index'] >= len(ENGINES):
            finish(); return
        QtCore.QTimer.singleShot(2000, begin)
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def finish():
    try:
        panel().preferences.set('moonlightipr/render_samples', 500)
    except Exception:
        pass
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    build()
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
