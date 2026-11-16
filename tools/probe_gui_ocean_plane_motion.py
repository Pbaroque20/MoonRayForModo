# python
"""GUI: an Ocean Plane in MoonLightIPR, with motion blur on the Modo camera, then moved up and down while realtime
follows it. A new scene, an Ocean Plane added as the MoonRay menu adds it, the render camera 4 m up looking out to sea, a
low sun. The preview opened on MoonLightIPR, Motion Blur switched on on the camera (PROBE_BLUR=0 leaves it off), a Render
pressed; then realtime switched on, and the plane's item moved to each of PROBE_HEIGHTS (1.5 -1 by default) as its form's
Position Y is typed in. At each stage: the picture, the status line and the notices, and the seas of the scene sent (how
many, at what height, whether the reading had the shutter's ends, whether its sea wears its graph). Writes
test-results/ocean-plane-motion-gui/report.json and the pictures (PROBE_OUT for another folder)."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean-plane-motion-gui'))
out.mkdir(parents=True, exist_ok=True)
report = {'stages': []}
state = {'heights': [float(h) for h in os.environ.get('PROBE_HEIGHTS', '1.5 -1').split()]}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def later(fn, wait):
    def run():
        try:
            fn()
        except Exception:
            report.setdefault('errors', []).append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(wait, run)


def seas(snapshot):
    found = []
    for mesh in (snapshot or {}).get('meshes') or []:
        if not mesh.get('_ocean_plane'):
            continue
        m = mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        v = mesh['vertices'][0]
        graph = ((snapshot.get('materials') or {}).get(mesh.get('material')) or {}).get('node_graph') or {}
        found.append({'height': round(v[1] * m[5] + m[13], 4), 'matrix_y': round(m[13], 4), 'moves': bool(mesh.get('vertices_close')),
                      'ocean': any(n.get('type') == 'ocean' for n in (graph.get('nodes') or {}).values())})
    return found


def stage(name):
    p = panel()
    snapshot = (p.renderer.active or {}).get('snapshot') or {}
    picture = out / (name + '.png')
    if not p.preview.image.isNull():
        p.preview.image.save(str(picture))
    report['stages'].append({'stage': name, 'status': p.status.text(), 'notices': p.warnings.toPlainText()[:1500],
                             'motion': bool(snapshot.get('motion_steps')), 'time': snapshot.get('time'), 'seas': seas(snapshot),
                             'seconds': round(time.monotonic() - state['t0'], 1)})
    save()


def begin():
    state.setdefault('t0', time.monotonic())
    from moonray_modo.panel import live_panels
    report.setdefault('looked', []).append([round(time.monotonic() - state['t0'], 1), [w.isVisible() for w in live_panels()]])
    if not live_panels():
        # The preview window, opened once (moonray.open: the test Modo may be minimized, its window not shown): looked
        # for again for up to a minute.
        if time.monotonic() - state['t0'] > 150:
            raise RuntimeError('The preview window did not open')
        if not state.get('asked'):
            state['asked'] = True
            lx.eval('moonray.open')
        later(begin, 1000)
        return
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    if p.ipr_mode.isChecked():
        p.ipr_mode.setChecked(False)
    report['blur'] = {'wanted': p._motion_wanted(), 'moonlightipr': p._moonlightipr_blur()}
    state['began'] = time.monotonic()
    p.start.click()
    later(watch_render, 500)


def watch_render():
    p = panel()
    if getattr(p, '_rendering', False) and time.monotonic() - state['began'] < 120:
        later(watch_render, 500)
        return
    stage('render')
    state['began'] = time.monotonic()
    p.rt.click()
    later(watch_realtime, 500)


def watch_realtime():
    if time.monotonic() - state['began'] < 20:
        later(watch_realtime, 500)
        return
    stage('realtime at %s' % state.get('height', 0.0))
    if not state['heights']:
        finish()
        return
    height = state['height'] = state['heights'].pop(0)
    import modo
    plane = [i for i in modo.Scene().items() if i.type == 'moonray.OceanPlaneGeometry'][0]
    lx.eval('select.item {%s} set' % plane.id)
    lx.eval('transform.channel pos.Y %s' % height)
    state['began'] = time.monotonic()
    later(watch_realtime, 500)


def finish():
    try:
        panel().rt.setChecked(False)
    except Exception:
        pass
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    # The preview window's making, written down: a window that fails to make itself says why here.
    import moonray_modo.panel as panel_module
    made_panel = panel_module.Panel.__init__

    def making(self, *args, **kwargs):
        report.setdefault('panels_made', []).append(round(time.monotonic(), 1))
        try:
            made_panel(self, *args, **kwargs)
        except Exception:
            report.setdefault('panel_errors', []).append(traceback.format_exc()[-2000:])
            save()
            raise
    panel_module.Panel.__init__ = making
    import modo
    lx.eval('scene.new')
    scene = modo.Scene()
    lx.eval('moonray.entity.add OceanPlaneGeometry')
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('transform.channel pos.X 0.0')
    lx.eval('transform.channel pos.Y 4.0')
    lx.eval('transform.channel pos.Z 0.0')
    lx.eval('transform.channel rot.X -4.0')
    camera.channel('focalLen').set(0.035)
    if os.environ.get('PROBE_BLUR', '1') != '0':
        # Motion Blur on the Modo camera, as the user switches it on (set here: a scene edit from a timer fails).
        camera.channel('motionBlur').set(1)
    scene.renderItem.channel('resX').set(640)
    scene.renderItem.channel('resY').set(360)
    lights = [i for i in scene.items() if i.type == 'sunLight']
    light = lights[0] if lights else scene.addItem('sunLight')
    lx.eval('select.item {%s} set' % light.id)
    lx.eval('transform.channel rot.X -12.0')
    lx.eval('transform.channel rot.Y 180.0')
except Exception:
    report['error'] = traceback.format_exc()
save()
later(begin, 8000)
