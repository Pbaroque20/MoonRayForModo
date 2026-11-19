# python
"""GUI: Modo's own render of the tyre Group Mask scene (tools/probe_cl_tyre_group_mask.py), as the tester's Modo drew
it: Modo's command line drew no purple at all on it, even with the mask off. Renders frame 1 to
test-results/tyre-group-mask/gui/modo.*.exr, with the mask on ('masked') and off ('unmasked'), lists the render
outputs, then quits."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

source = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo'
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\gui')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


def run():
    try:
        lx.eval('scene.open {%s} normal' % source)
        scene = modo.Scene()
        report['outputs'] = [(o.name, o.channel('effect').get(), o.channel('enable').get()) for o in scene.items('renderOutput')]
        # One frame (the scene's range is longer): through Modo's own command, which the GUI takes where a channel write
        # from Python was refused.
        lx.eval('select.item {%s} set' % scene.renderItem.id)
        for channel in ('first', 'last'):
            lx.eval('item.channel polyRender$%s 1' % channel)
        report['range'] = [scene.renderItem.channel('first').get(), scene.renderItem.channel('last').get()]
        save()
        lx.eval('!render.animation {%s} openexr' % str(out / 'masked'))
        image = next(i for i in scene.iterItems() if i.type == 'imageMap' and '_checkHere' in i.name)
        image.channel('enable').set(0)
        lx.eval('!render.animation {%s} openexr' % str(out / 'unmasked'))
        report['files'] = sorted(p.name for p in out.glob('*.exr'))
    except Exception:
        report['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(2000, run)
