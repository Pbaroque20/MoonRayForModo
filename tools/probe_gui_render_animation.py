# python
"""Isolated GUI test of Render Animation, in a new scene with a cube moving fast (frames 1-3). Goes through the preview window's
own steps: the window's opening values from the scene, RT on before the render, XPU2 as what renders, the frames in one folder under
two prefixes, the framebuffer's picture as frames come, the buttons afterwards, and Render with Motion Blur on.
Writes test-results/render-animation/."""
import json
import os
import pathlib
import shutil
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/render-animation'
shutil.rmtree(out / 'frames', ignore_errors=True)
(out / 'renderer-said.txt').unlink() if (out / 'renderer-said.txt').exists() else None
(out / 'frames').mkdir(parents=True, exist_ok=True)
result = {}
held = {'seen': [], 'shots': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def guarded(step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            result['done'] = True
        save()
    return run


def later(ms, step):
    QtCore.QTimer.singleShot(ms, guarded(step))


def buttons(panel):
    return {'rt enabled': panel.rt.isEnabled(), 'rt text': panel.rt.text(), 'realtime': panel.ipr_mode.isChecked(), 'render enabled': panel.start.isEnabled(),
            'render text': panel.start.text(), 'output busy': panel._output_busy(), 'rendering': panel._rendering, 'following': panel._following}


def setup():
    scene = modo.Scene()
    mesh = scene.addMesh('Mover')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', .5), ('sizeY', .5), ('sizeZ', .5)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    # Moving a long way from frame to frame: its motion blur is plain to see.
    fps = float(scene.fps)
    locator = modo.LocatorSuperType(mesh)
    position = locator.position
    position.x.set(-1.0, time=1 / fps, key=True)
    position.x.set(1.0, time=3 / fps, key=True)
    render = scene.renderItem
    for name, value in (('first', 1), ('last', 3), ('step', 1), ('resX', 320), ('resY', 180)):
        render.channel(name).set(value)
    lx.eval('select.time %g' % (2 / fps))
    camera = scene.renderCamera
    modo.LocatorSuperType(camera).position.set((0, 0, 4))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    light = scene.addItem('sunLight')
    result['scene'] = {'fps': fps}
    later(1000, show_window)


def show_window():
    lx.eval('moonray.page preview')
    later(2000, open_window)


def find_panel():
    from moonray_modo.panel import Panel
    for widget in QtWidgets.QApplication.allWidgets():
        if isinstance(widget, Panel):
            return widget
    raise LookupError('no preview window')


def open_window():
    panel = held['panel'] = find_panel()
    result['xpu2 chosen'] = __import__('moonray_modo.native', fromlist=['xpu2']).xpu2()
    from moonray_modo import output_dialog, sequence_plan
    scene_values = panel._animation_scene()
    result['scene values'] = scene_values
    dialog = output_dialog.AnimationDialog(panel.settings, panel, sequence_plan.window_values(panel._settings_values().get('animation_output'), scene_values))
    result['window opens with'] = {'first': dialog.first.value(), 'last': dialog.last.value(), 'step': dialog.step.value(), 'fps': dialog.fps.value(), 'motion': dialog.motion.isChecked(), 'digits': dialog.digits.value()}
    panel._store(final_motion=True)
    result['motion follows scene'] = panel._animation_scene()['motion']
    # RT on, as an artist has it, then the render.
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.rt.setChecked(True)
    result['realtime on before'] = buttons(panel)
    later(9000, first_sequence)


def run_sequence(prefix, digits):
    """The steps of panel_tools.render_animation past its window, with the window answered as an artist would."""
    panel = held['panel']
    from moonray_modo import output_dialog
    real = output_dialog.AnimationDialog

    class Answered(real):
        def exec_(self):
            self.folder.setText(str(out / 'frames'))
            self.prefix.setText(prefix)
            self.digits.setValue(digits)
            self.first.setValue(1)
            self.last.setValue(3)
            self.motion.setChecked(os.environ.get('MOONRAY_PROBE_MOTION', '1') == '1')
            held['opened with'] = self.kept()
            # gamma's frames denoised, and saved as PNG beside their EXRs.
            self.type.setCurrentIndex(max(0, self.type.findData('png8' if prefix == 'gamma' else None)))
            return True
    output_dialog.AnimationDialog = Answered
    try:
        panel.render_animation()
    finally:
        output_dialog.AnimationDialog = real
    held['seen'] = []
    if 'listening' not in held:
        held['listening'] = True
        panel.renderer.image_object.connect(seen)
        panel.renderer.image_ready.connect(seen)
        panel.renderer.session.output.connect(said)


def said(text):
    # What the renderer says, without its tiles and pictures.
    with (out / 'renderer-said.txt').open('a', encoding='utf-8', errors='replace') as stream:
        for line in text.splitlines():
            if line.strip() and not line.startswith(('@@MODO_TILES', '@@MODO_WORKERS', '@@MODO_GPU_WORKERS', '@@MODO_SHARED', '@@MODO_PROGRESS', '@@MODO_BUCKET')):
                stream.write(line[:300] + '\n')


def seen(picture):
    frame = held['panel'].sequence.frame if held['panel'].sequence is not None else None
    held['seen'].append(frame)


def first_sequence():
    run_sequence('alpha', 4)
    panel = held['panel']
    result['during first'] = dict(buttons(panel), session=panel.renderer.using_session, session_xpu2=getattr(panel.renderer.session, 'xpu2_active', None))
    wait_for(after_first)


def wait_for(next_step, tries=240):
    panel = held['panel']
    (out / 'render-log.txt').write_text(panel.renderer.log, encoding='utf-8', errors='replace')
    if panel.sequence is not None and panel.sequence.running and tries > 0:
        if panel.renderer.using_session and tries % 8 == 0:
            result['session xpu2 during'] = getattr(panel.renderer.session, 'xpu2_active', None)
            if not panel.preview.image.isNull():
                panel.preview.image.save(str(out / ('during-%d.png' % (held['shots'] % 4))))
                held['shots'] += 1
        later(500, lambda: wait_for(next_step, tries - 1))
        return
    next_step()


def after_first():
    panel = held['panel']
    result['first sequence'] = {'running at the end': panel.sequence.running, 'status': panel.status.text(), 'timing': panel.render_timing.text(), 'frames shown': sorted(set(str(f) for f in held['seen'])), 'picture count': len(held['seen'])}
    result['buttons after first'] = buttons(panel)
    result['files after first'] = sorted(p.name for p in (out / 'frames').iterdir())
    result['kept with scene'] = panel._settings_values().get('animation_output')
    if not panel.preview.image.isNull():
        panel.preview.image.save(str(out / 'framebuffer-after-first.png'))
    later(1000, second_sequence)


def second_sequence():
    panel = held['panel']
    from moonray_modo import output_dialog, sequence_plan
    dialog = output_dialog.AnimationDialog(panel.settings, panel, sequence_plan.window_values(panel._settings_values().get('animation_output'), panel._animation_scene()))
    result['window opens again with'] = dialog.kept()
    run_sequence('beta', 3)
    wait_for(after_second)


def after_second():
    panel = held['panel']
    result['second sequence'] = {'status': panel.status.text()}
    result['buttons after second'] = buttons(panel)
    result['files after second'] = sorted(p.name for p in (out / 'frames').iterdir())
    if not panel.preview.image.isNull():
        panel.preview.image.save(str(out / 'framebuffer-after-second.png'))
    later(1000, still)


def still():
    # Render: the frame with the scene's Motion Blur on, as the Render button does.
    panel = held['panel']
    result['render enabled for the still'] = panel.start.isEnabled()
    panel.start.click()
    result['still has motion'] = None
    wait_still(120)


def wait_still(tries):
    panel = held['panel']
    if panel._rendering and tries > 0:
        later(500, lambda: wait_still(tries - 1))
        return
    active = (panel.renderer.active or {}).get('snapshot', {})
    result['still'] = {'status': panel.status.text(), 'session xpu2': getattr(panel.renderer.session, 'xpu2_active', None), 'motion in scene': bool(active.get('motion_blur') or active.get('_external_motion_settings'))}
    if not panel.preview.image.isNull():
        panel.preview.image.save(str(out / 'still-motion-blur.png'))
    result['buttons after still'] = buttons(panel)
    later(500, to_a_file)


def to_a_file():
    # Render to a File, its file dialog answered.
    panel = held['panel']
    target = out / 'frames' / 'still.exr'

    class Answered(QtWidgets.QFileDialog):
        def exec_(self):
            return True

        def selectedFiles(self):
            return [str(target)]

        def selectedNameFilter(self):
            return ''
    real = QtWidgets.QFileDialog
    QtWidgets.QFileDialog = Answered
    try:
        panel.render_final()
    finally:
        QtWidgets.QFileDialog = real
    result['during file'] = dict(buttons(panel), session=panel.renderer.using_session)
    wait_file(240)


def wait_file(tries):
    panel = held['panel']
    if panel._rendering and tries > 0:
        later(500, lambda: wait_file(tries - 1))
        return
    result['to a file'] = {'status': panel.status.text(), 'written': (out / 'frames' / 'still.exr').is_file()}
    result['buttons after file'] = buttons(panel)
    # Frames denoised, by XPU2.
    from moonray_modo import properties
    denoising = dict(panel._settings_values()['denoising'], engine=os.environ.get('MOONRAY_PROBE_DENOISER', 'optix'), final=True)
    panel._store(denoising=denoising)
    run_sequence('gamma', 4)
    wait_for(after_denoised)


def after_denoised():
    panel = held['panel']
    result['denoised sequence'] = {'status': panel.status.text(), 'files': sorted(p.name for p in (out / 'frames').iterdir() if p.name.startswith('gamma'))}
    panel._store(denoising=dict(panel._settings_values()['denoising'], engine='off'))
    # MoonRay XPU chosen in the preferences: a MoonRay of its own for each frame.
    panel.settings.setValue('xpu2/renderer', 'xpu')
    from moonray_modo import native
    result['xpu2 after choosing xpu'] = native.xpu2()
    held['seen'] = []
    run_sequence('delta', 4)
    result['during moonray'] = dict(buttons(panel), session=panel.renderer.using_session)
    wait_for(after_moonray)


def after_moonray():
    panel = held['panel']
    result['moonray sequence'] = {'status': panel.status.text(), 'pictures shown': len(held['seen']), 'files': sorted(p.name for p in (out / 'frames').iterdir() if p.name.startswith('delta'))}
    result['buttons after moonray'] = buttons(panel)
    if not panel.preview.image.isNull():
        panel.preview.image.save(str(out / 'framebuffer-moonray.png'))
    panel.settings.setValue('xpu2/renderer', 'xpu2')
    result['done'] = True
    save()


# Here, in the script's own command: Modo refuses a scene's edits from a timer.
guarded(setup)()
