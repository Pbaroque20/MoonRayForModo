# python
"""Isolated GUI test: a MoonRay material's main colour and Modo's diffuse. A material made starts on its diffuse; a colour
written goes to the diffuse; a diffuse edited comes back, in Traditional and Principled, as a render reads it; one undo
takes both back and leaves redo; a saved scene whose two differ is left as it is when opened, until one is edited. Writes test-results/material-diffuse/report.json."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/material-diffuse'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def rounded(values):
    return None if values is None else [round(float(v), 4) for v in values]


def note(name):
    from moonray_modo import material_diffuse, properties
    from moonray_modo.host import material_values
    item = held['material']
    result['steps'].append({'step': name, 'diffuse': rounded(material_diffuse.diffuse(item)),
                            'albedo': rounded(material_diffuse.stored_colour(properties.read(item))[1]),
                            'rendered': rounded(material_values(item).get('native_parameters', {}).get('albedo')),
                            'brdf': item.channel('brdfType').get()})
    save()


def set_diffuse(rgb):
    lx.eval('select.item {%s} set' % held['material'].id)
    # Each channel is a step of its own here; a colour picker's is one.
    for axis, value, was in zip('RGB', rgb, held['material'] and [held['material'].channel('diffCol.' + a).get() for a in 'RGB']):
        if abs(value - was) > 1e-6:
            lx.eval('item.channel advancedMaterial$diffCol.%s %f' % (axis, value))


def steps():
    from moonray_modo import properties
    # Each step, then a wait longer than the watcher's, for the colour to come back.
    yield lambda: note('made, on its diffuse')

    def typed():
        settings = properties.read(held['material'])
        settings['native_parameters'] = dict(settings.get('native_parameters') or {}, albedo=[.9, .1, .1])
        lx.eval('moonray.material.applyGraph {%s} %s' % (held['material'].id, properties.encode(settings)))
    yield typed
    yield lambda: note('albedo written 0.9 0.1 0.1')
    yield lambda: set_diffuse((.1, .8, .2))
    yield lambda: note('Traditional diffuse edited 0.1 0.8 0.2')
    yield lambda: lx.eval('item.channel advancedMaterial$brdfType principled')
    yield lambda: set_diffuse((.7, .8, .2))
    yield lambda: note('Principled diffuse edited 0.7 0.8 0.2')
    yield lambda: lx.eval('app.undo')
    yield lambda: note('one undo of the diffuse edit')
    yield lambda: lx.eval('app.redo')
    yield lambda: note('redo')
    yield lambda: lx.eval('app.undo')

    def typed_again():
        settings = properties.read(held['material'])
        settings['native_parameters'] = dict(settings.get('native_parameters') or {}, albedo=[.4, .4, .9])
        lx.eval('moonray.material.applyGraph {%s} %s' % (held['material'].id, properties.encode(settings)))
    yield typed_again
    yield lambda: note('albedo written 0.4 0.4 0.9')
    yield lambda: lx.eval('app.undo')
    yield lambda: note('one undo of the albedo edit')

    def mismatch():
        # As a scene saved before this: the two differ. Opening it must leave them.
        from moonray_modo import material_diffuse
        settings = properties.read(held['material'])
        settings['native_parameters'] = dict(settings.get('native_parameters') or {}, albedo=[.5, .5, .5])
        settings.pop(material_diffuse.LINKED, None)
        kept = material_diffuse.to_diffuse
        material_diffuse.to_diffuse = lambda *_: False
        try:
            lx.eval('moonray.material.applyGraph {%s} %s' % (held['material'].id, properties.encode(settings)))
        finally:
            material_diffuse.to_diffuse = kept
        held['id'] = held['material'].id
        path = str(out / 'differ.lxo')
        lx.eval('!scene.saveAs {%s} $LXOB false' % path)
        note('saved with the two differing')
        lx.eval('!scene.close')
        lx.eval('!scene.open {%s}' % path)
    yield mismatch

    def reopened():
        from moonray_modo import properties as p
        held['material'] = next(i for i in modo.Scene().items() if p.is_material(i) and p.read(i).get('native_shader'))
        note('opened again: still as saved')
    yield reopened
    yield lambda: set_diffuse((.3, .8, .2))
    yield lambda: note('older scene, diffuse edited: linked now')
    yield lambda: result.__setitem__('finished', True)


def run(plan):
    try:
        next(plan)()
    except StopIteration:
        save()
        lx.eval('!scene.close')
        lx.eval('app.quit')
        return
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
        save()
    QtCore.QTimer.singleShot(1200, lambda: run(plan))


try:
    from moonray_modo import materials, properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    mesh = [i for i in modo.Scene().items('mesh')][-1]
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['material'] = [i for i in modo.Scene().items() if properties.is_material(i)][-1]
    held['material'] = next(i for i in modo.Scene().items() if properties.is_material(i) and properties.read(i).get('native_shader'))
    # Add Layer's way: an entry made into a material, with no mesh.
    entry = modo.Scene().addItem('material.moonrayAddDwaMetalMaterial')
    QtCore.QTimer.singleShot(500, lambda: result.__setitem__('added', [(i.type, rounded([i.channel('diffCol.' + a).get() for a in 'RGB']), properties.read(i).get('native_parameters')) for i in modo.Scene().items() if i.type == 'material.dw.DwaMetalMaterial']))
    QtCore.QTimer.singleShot(1500, lambda: run(steps()))
except Exception:
    result['error'] = traceback.format_exc()
    save()
    lx.eval('app.quit')
