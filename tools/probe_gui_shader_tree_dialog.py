# python
"""Modo with its window (tools/launch_gui_probe.py): MoonRay > Shader Tree -> MoonShine (shader_tree_dialog) on
MOONRAY_PROBE_SCENE, its questions answered beforehand: Cancel pressed while the third material is read (the scene must
be as it was), then Convert the Current Scene, then Open a Scene and Convert. The progress bar's stages and values are
written down at each step. Writes <MOONRAY_PROBE_OUT>/dialog.json and quits."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
report = {}


def state():
    from moonray_modo import properties, material_override
    scene = modo.Scene()
    graphs = 0
    for item in scene.items('advancedMaterial', superType=True):
        settings = properties.read(item)
        if material_override.enabled(settings) and settings.get('node_graph'):
            graphs += 1
    return {'clips': sorted(c.name for c in scene.items('videoStill')), 'graphs': graphs,
            'layers on': sum(1 for layer in scene.items('imageMap') if layer.channel('enable').get()), 'file': scene.filename}


try:
    from moonray_modo import shader_tree_dialog
    original = shader_tree_dialog.Progress.step
    seen = []
    cancel_at = {'text': None}

    def step(self, text, done=None, total=None):
        if cancel_at['text'] and cancel_at['text'] in text and self.cancellable:
            seen.append((text, 'Cancel pressed'))
            raise shader_tree_dialog.Cancelled()
        original(self, text, done, total)
        seen.append((text, self.dialog.value() if self.dialog is not None else None, self.dialog.isVisible() if self.dialog is not None else None))
    shader_tree_dialog.Progress.step = step
    lx.eval('scene.open {%s} normal' % source)
    report['opened'] = state()
    cancel_at['text'] = 'Materials: 3 of'
    report['cancel lines'] = shader_tree_dialog.run('current', show=False)
    report['after cancel'] = state()
    report['after cancel is as opened'] = report['after cancel'] == report['opened']
    report['cancel steps'] = list(seen)
    del seen[:]
    cancel_at['text'] = None
    report['convert lines'] = shader_tree_dialog.run('current', show=False)
    report['after convert'] = state()
    report['convert steps'] = list(seen)
    del seen[:]
    report['open lines'] = shader_tree_dialog.run('open', str(source), show=False)
    report['after open'] = state()
    report['open steps'] = list(seen)
except Exception:
    report['error'] = traceback.format_exc()
(out / 'dialog.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('app.quit')
