# python
"""Command line: Modo's own renders of the rebuilt tyre (tools/probe_cl_tyre_group_mask.py) in variants, frame 1
alone: as built ('as_built'), its group's mask image switched off ('no_mask'), and the purple group moved to the top of
the tread's material group if it is not there ('top'). Writes test-results/tyre-group-mask/variants/<name>.*.exr and
report.json with each variant's Shader Tree order."""
import json
import pathlib
import traceback
import lx
import modo

source = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo'
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\variants')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


def render(name):
    scene = modo.Scene()
    for channel, value in (('first', 1), ('last', 1)):
        scene.renderItem.channel(channel).set(value)
    tread = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Reifen_Laufflaeche')
    report[name] = {'children': [(c.name, c.type) for c in tread.children()],
                    'group': [(c.name, c.type, c.channel('enable').get()) for c in next(c for c in tread.children() if c.name == 'Purple Group').children()]}
    save()
    lx.eval('!render.animation {%s} openexr' % str(out / name))
    report[name]['files'] = sorted(p.name for p in out.glob(name + '*'))
    save()


try:
    lx.eval('scene.open {%s} normal' % source)
    render('as_built')
    scene = modo.Scene()
    image = next(i for i in scene.iterItems() if i.type == 'imageMap' and i.name.startswith('tire dirt mask'))
    image.channel('enable').set(0)
    render('no_mask')
except Exception:
    report['error'] = traceback.format_exc()
save()
