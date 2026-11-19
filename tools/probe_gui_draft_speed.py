# python
"""GUI: how long Draft takes to show an edit on a simple scene. A new scene with one cube, the preview opened, Draft
on; once its first lines are up, the cube is moved PROBE_EDITS times (5), one move at a time, and each step of the
redraw is timed: the edit, the draft tick that saw it, reading the scene (_capture), handing it on (_submit), the
session's packing, the picture arriving (_image), and every change of _rendering in between.
Written to test-results/draft-speed/timeline.json; Modo then quits."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\draft-speed')
out.mkdir(parents=True, exist_ok=True)
EDITS = int(os.environ.get('PROBE_EDITS', '5'))
start = time.monotonic()
import faulthandler
_fault = open(str(out / 'fault.txt'), 'w')
faulthandler.enable(file=_fault, all_threads=True)
events = []
state = {'edit': 0, 'cube': None}


def note(kind, **extra):
    events.append(dict(t=round(time.monotonic() - start, 3), kind=kind, edit=state['edit'], **extra))


def save(**extra):
    (out / 'timeline.json').write_text(json.dumps(dict(events=events, **extra), indent=1, default=str))


def wrap(owner, name, label=None, after=False):
    original = getattr(owner, name)

    def timed(*args, **kwargs):
        note((label or name) + ' begin')
        try:
            return original(*args, **kwargs)
        finally:
            note((label or name) + ' end')
    setattr(owner, name, timed)


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def instrument():
    from moonray_modo import moonlightipr_session
    p = panel()
    for name in ('_draft_submit', '_capture', '_submit', '_image'):
        wrap(p, name)
    original_rendering = p._set_rendering

    def set_rendering(value, *args, **kwargs):
        note('_set_rendering', value=bool(value))
        return original_rendering(value, *args, **kwargs)
    p._set_rendering = set_rendering
    from moonray_modo import ocean, moonlightipr_scene
    from moonray_modo import moonlightipr_detail
    for owner, name in ((ocean, 'native_tile'), (ocean, 'fields'), (ocean, 'fitted'), (moonlightipr_scene, 'pack'),
                        (moonlightipr_detail, 'plan'), (moonlightipr_scene, 'mesh_payload')):
        if hasattr(owner, name):
            wrap(owner, name, name)
    def said(text):
        for line in text.splitlines():
            if line.startswith('@@MODO_SESSION') or line.startswith('MoonLightIPR'):
                note('session says', value=line.strip()[:120])
    p.renderer.moonlightipr.output.connect(said)
    run = moonlightipr_session.Packer.run

    def packed(self):
        note('pack begin')
        try:
            return run(self)
        finally:
            note('pack end')
    moonlightipr_session.Packer.run = packed
    for name in ('submit', '_dispatch', '_packed'):
        wrap(moonlightipr_session.Session, name, 'session.' + name)


def draft_on():
    note('instrument'); save()
    instrument()
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    note('draft on')
    p.draft.setChecked(True)
    note('draft checked'); save()
    QtCore.QTimer.singleShot(8000, edit)


DRAG = bool(os.environ.get('PROBE_DRAG'))


def drag_step():
    # PROBE_DRAG: the kit is told a mouse button is down (interaction.dragging), and the cube moved a little every 0.15 s,
    # as a drag moves it; each step should be drawn while the button is still "down".
    from moonray_modo import interaction
    if state.get('steps', 0) == 0:
        interaction.dragging = lambda: True
        note('button down')
        watch = state['watch'] = QtCore.QTimer()
        watch.setInterval(50)
        def look():
            try:
                p = panel()
                note('state', value=dict(held=interaction.dragging(), items=len(p.changes.items), full=bool(p.changes.full),
                                         rendering=bool(p._rendering), following=bool(p._following), draft=p.draft.isChecked(),
                                         timer=p.draft_timer.isActive(), status=p.status.text()[:80]))
            except Exception as exc:
                note('state', value=repr(exc)[:120])
        watch.timeout.connect(look)
        watch.start()
    state['steps'] = state.get('steps', 0) + 1
    state['edit'] = state['steps']
    note('edit')
    lx.eval('select.item {%s} set' % state['cube'])
    lx.eval('transform.channel pos.X %s' % (0.1 * state['steps']))
    lx.eval('select.drop item')
    if state['steps'] < 12:
        QtCore.QTimer.singleShot(150, drag_step)
    else:
        QtCore.QTimer.singleShot(150, release)


def release():
    from moonray_modo import interaction
    interaction.dragging = lambda: False
    note('button up')
    save()
    QtCore.QTimer.singleShot(3000, lambda: (save(done=True), lx.eval('!app.quit')))


CAMERA = os.environ.get('PROBE_DRAG') == 'camera'


def camera_matrix():
    import modo
    from moonray_modo.host import world_matrix
    return list(world_matrix(modo.Scene().renderCamera))


def camera_drag_step():
    # PROBE_DRAG=camera: a viewport looking through the camera is navigated (its place moved a little every 0.15 s) while
    # the camera item stays where it is, as Modo does until the mouse is let go. Each scene sent should carry the
    # viewport's place.
    from moonray_modo import interaction
    p = panel()
    if state.get('steps', 0) == 0:
        base = state['base'] = camera_matrix()
        state['view'] = list(base)
        p._view_matrices = lambda: [list(state['view'])]
        original = p._submit

        def submit(scene, *args, **kwargs):
            matrix = (scene.get('camera') or {}).get('matrix')
            note('submitted camera x', value=round(matrix[12], 3) if matrix else None)
            note('scene detail', value=dict(detail=scene.get('_geometry_detail'), keep=scene.get('_detail_keep')))
            return original(scene, *args, **kwargs)
        p._submit = submit
        QtCore.QTimer.singleShot(1200, camera_drag_step)   # the view watched while the button is up (_camera_watch)
        state['steps'] = -1
        return
    if state['steps'] == -1:
        state['steps'] = 0
        interaction.dragging = lambda: True
        note('button down', value=round(state['base'][12], 3))
    state['steps'] += 1
    state['edit'] = state['steps']
    state['view'][12] = state['base'][12] + 0.2 * state['steps']
    note('view moved', value=round(state['view'][12], 3))
    if state['steps'] < 10:
        QtCore.QTimer.singleShot(150, camera_drag_step)
    else:
        QtCore.QTimer.singleShot(150, release)


def edit():
    if CAMERA:
        return camera_drag_step()
    if DRAG:
        return drag_step()
    if state['edit'] >= EDITS:
        save(done=True)
        QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))
        return
    state['edit'] += 1
    note('edit')
    save()
    try:
        lx.eval('select.item {%s} set' % state['cube'])
        lx.eval('transform.channel pos.X %s' % (0.3 * state['edit']))
        lx.eval('select.drop item')
    except Exception:
        note('edit failed', error=traceback.format_exc()[-300:])
    save()
    QtCore.QTimer.singleShot(9000, edit)


try:
    SCENE = os.environ.get('PROBE_SCENE')
    if SCENE:
        lx.eval('scene.open {%s} normal' % SCENE)
    else:
        lx.eval('scene.new')
    lx.eval('item.create mesh {Probe Cube}')
    import modo
    cube = next(i for i in modo.Scene().items('mesh') if i.name == 'Probe Cube')
    state['cube'] = cube.id
    lx.eval('select.item {%s} set' % cube.id)
    lx.eval('tool.set prim.cube on'); lx.eval('tool.apply'); lx.eval('tool.set prim.cube off')
    lx.eval('select.drop item')
    lx.eval('moonray.open')
    QtCore.QTimer.singleShot(3000, draft_on)
except Exception:
    save(error=traceback.format_exc())
