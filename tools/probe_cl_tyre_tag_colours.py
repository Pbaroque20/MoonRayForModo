# python
"""Command line: which of the rebuilt tyre's material groups Modo draws where (test-results/tyre-group-mask/
tyre_group_mask.lxo). Every advancedMaterial in the tread's group (Reifen_Laufflaeche) made red and in Reifenmaterial's
made green, the purple group switched off ('tags'); then everything restored and only the purple group left as built
but its Purple's colour made pure blue ('blue'). Modo renders frame 1 alone of each to
test-results/tyre-group-mask/tags/<name>.*.exr; report.json lists the materials changed."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tags')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


def materials_under(group):
    found = []
    for child in group.children():
        if child.type == 'advancedMaterial':
            found.append(child)
        if child.type == 'mask':
            found += materials_under(child)
    return found


def set_colour(item, rgb):
    for axis, value in zip('RGB', rgb):
        lx.eval('item.channel advancedMaterial$diffCol.%s %s item:{%s}' % (axis, value, item.id))


def render(name):
    scene = modo.Scene()
    for channel, value in (('first', 1), ('last', 1)):
        scene.renderItem.channel(channel).set(value)
    lx.eval('!render.animation {%s} openexr' % str(out / name))


try:
    source = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo'
    lx.eval('scene.open {%s} normal' % source)
    scene = modo.Scene()
    masks = {m.channel('ptag').get(): m for m in scene.items('mask', superType=False)}
    tread, wall = masks['Reifen_Laufflaeche'], masks['Reifenmaterial']
    group = next(i for i in scene.iterItems() if i.name == 'Purple Group')
    report['tread_ptyp'] = tread.channel('ptyp').get()
    report['wall_ptyp'] = wall.channel('ptyp').get()
    lx.eval('item.channel mask$enable false item:{%s}' % group.id)
    report['red'] = [m.name for m in materials_under(tread) if m.parent.id == tread.id]
    for item in materials_under(tread):
        if item.parent.id == tread.id:
            set_colour(item, (1, 0, 0))
    report['green'] = [m.name for m in materials_under(wall)]
    for item in materials_under(wall):
        set_colour(item, (0, 1, 0))
    save()
    render('tags')
    lx.eval('scene.close')
    lx.eval('scene.open {%s} normal' % source)
    scene = modo.Scene()
    purple = next(i for i in scene.iterItems() if i.name == 'Purple')
    set_colour(purple, (0, 0, 1))
    render('blue')
    report['files'] = sorted(p.name for p in out.glob('*.exr'))
except Exception:
    report['error'] = traceback.format_exc()
save()
