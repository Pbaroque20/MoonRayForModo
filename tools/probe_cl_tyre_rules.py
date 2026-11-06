# python
"""Command line: which items of the rebuilt tyre's tread group Modo's render follows (test-results/tyre-group-mask/
tyre_group_mask.lxo), at 320 x 240, frame 1 alone, each from the saved scene with Dirt_for_tread off:
'm2_red' Material (2) red; 'mr_red' M_Reifen_Laufflaeche red; 'purple_nomask' the purple group's mask image off;
'm2_off' Material (2) off. Writes test-results/tyre-group-mask/rules/<name>.*.exr and report.json, which also holds
each tread item's every channel that differs between Purple and Material (2)."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\rules')
out.mkdir(parents=True, exist_ok=True)
source = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo'
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


def named(name):
    return next(i for i in modo.Scene().iterItems() if i.name == name)


def chan(item, kind, name, value):
    lx.eval('item.channel %s$%s %s item:{%s}' % (kind, name, value, item.id))


def red(name):
    item = named(name)
    for axis, value in zip('RGB', (1, 0, 0)):
        chan(item, 'advancedMaterial', 'diffCol.' + axis, value)


def channels(item):
    held = {}
    for c in item.channels():
        try:
            v = c.get()
            if isinstance(v, (int, float, str)):
                held[c.name] = v
        except Exception:
            pass
    return held


def top_of_tread(item):
    tread = next(m for m in modo.Scene().items('mask', superType=False) if m.channel('ptag').get() == 'Reifen_Laufflaeche')
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('texture.parent {%s} %d' % (tread.id, len(list(tread.children()))))


def white_on_top():
    tread = next(m for m in modo.Scene().items('mask', superType=False) if m.channel('ptag').get() == 'Reifen_Laufflaeche')
    before = {i.id for i in modo.Scene().iterItems()}
    lx.eval('select.item {%s} set' % tread.id)
    lx.eval('shader.create constant')
    made = next(i for i in modo.Scene().iterItems() if i.id not in before and i.type == 'constant')
    made.channel('effect').set('diffColor')
    for axis in 'RGB':
        made.channel('color.' + axis).set(1.0)
    report['white_tree'] = [c.name for c in reversed(list(tread.children()))]


def m2_top_red():
    red('Material (2)')
    top_of_tread(named('Material (2)'))
    tread = named('Reifen_Laufflaeche (Material)')
    report['m2_top_tree'] = [c.name for c in reversed(list(tread.children()))]


def purple_index(index):
    def move():
        tread = named('Reifen_Laufflaeche (Material)')
        lx.eval('select.item {%s} set' % named('Purple Group').id)
        lx.eval('texture.parent {%s} %d' % (tread.id, index))
        report['purple_index_%d' % index] = [c.name for c in tread.children()]
    return move


VARIANTS = {
    'purple_at_0': purple_index(0),
    'white_top': white_on_top,
    'm2_top_red': m2_top_red,
    'm2_red': lambda: red('Material (2)'),
    'mr_red': lambda: red('M_Reifen_Laufflaeche'),
    'purple_nomask': lambda: chan(next(i for i in modo.Scene().iterItems() if i.type == 'imageMap' and i.name.startswith('tire dirt mask')), 'imageMap', 'enable', 'false'),
    'm2_off': lambda: chan(named('Material (2)'), 'advancedMaterial', 'enable', 'false'),
}
try:
    lx.eval('scene.open {%s} normal' % source)
    a, b = channels(named('Purple')), channels(named('Material (2)'))
    report['purple_vs_m2'] = {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}
    lx.eval('!scene.close')
    save()
    for name in (os.environ.get('PROBE_VARIANTS') or ','.join(VARIANTS)).split(','):
        try:
            lx.eval('scene.open {%s} normal' % source)
            scene = modo.Scene()
            if not os.environ.get('PROBE_DIRT_ON'):
                chan(named('Dirt_for_tread (Image)'), 'imageMap', 'enable', 'false')
            VARIANTS[name]()
            for channel, value in (('first', 1), ('last', 1), ('resX', 320), ('resY', 240)):
                scene.renderItem.channel(channel).set(value)
            lx.eval('!render.animation {%s} openexr' % str(out / name))
            lx.eval('!scene.close')
            report.setdefault('done', []).append(name)
        except Exception:
            report[name] = traceback.format_exc()
        save()
except Exception:
    report['error'] = traceback.format_exc()
save()
