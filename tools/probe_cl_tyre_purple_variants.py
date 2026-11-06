# python
"""Command line: why Modo ignores the purple group on the rebuilt tyre (test-results/tyre-group-mask/
tyre_group_mask.lxo), each from the saved scene, frame 1 alone: Purple moved out of its group to the top of the tread's
group ('loose'); the group's type set to Material ('ptyp'); the tread's Dirt_for_tread layer off ('nodirt'); the
group's mask image off and Purple at full opacity, the group re-made with shader.group from Purple ('regroup').
Renders to test-results/tyre-group-mask/purple/<name>.*.exr; report.json has each tree."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\purple')
out.mkdir(parents=True, exist_ok=True)
source = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo'
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


def named(name):
    return next(i for i in modo.Scene().iterItems() if i.name == name)


def tree(item, depth=0):
    rows = []
    for child in reversed(list(item.children())):
        rows.append('  ' * depth + '%s (%s)' % (child.name, child.type))
        rows += tree(child, depth + 1)
    return rows


def run(name, change):
    try:
        lx.eval('scene.open {%s} normal' % source)
        scene = modo.Scene()
        tread = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Reifen_Laufflaeche')
        change(scene, tread)
        for channel, value in (('first', 1), ('last', 1)):
            scene.renderItem.channel(channel).set(value)
        report[name] = {'tree': tree(tread)}
        save()
        lx.eval('!render.animation {%s} openexr' % str(out / name))
        lx.eval('!scene.close')
    except Exception:
        report[name] = {'error': traceback.format_exc()}
        save()


def loose(scene, tread):
    lx.eval('select.item {%s} set' % named('Purple').id)
    lx.eval('texture.parent {%s} %d' % (tread.id, len(list(tread.children()))))


def ptyp(scene, tread):
    lx.eval('item.channel mask$ptyp Material item:{%s}' % named('Purple Group').id)


def nodirt(scene, tread):
    lx.eval('item.channel imageMap$enable false item:{%s}' % named('Dirt_for_tread (Image)').id)


def regroup(scene, tread):
    image = next(i for i in scene.iterItems() if i.type == 'imageMap' and i.name.startswith('tire dirt mask'))
    lx.eval('item.channel imageMap$enable false item:{%s}' % image.id)
    lx.eval('select.item {%s} set' % named('Purple').id)
    lx.eval('texture.parent {%s} %d' % (tread.id, len(list(tread.children()))))
    lx.eval('select.item {%s} set' % named('Purple').id)
    lx.eval('shader.group')


for name, change in (('loose', loose), ('ptyp', ptyp), ('nodirt', nodirt), ('regroup', regroup)):
    run(name, change)
report['files'] = sorted(p.name for p in out.glob('*RAW*.exr'))
save()
