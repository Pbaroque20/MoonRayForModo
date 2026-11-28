# python
"""Command line: a test scene of plain Modo materials (no texture layers) for Shader Tree -> MoonShine
(shader_tree_scene), which makes each a DwaBaseMaterial graph with its settings. A row of spheres, one material each:
  Diffuse    a coloured diffuse with diffuse roughness;
  Glossy     specular 30%, roughness 20%, a tinted specular colour;
  Metal      reflection 80% with its colour, metallic;
  Glass      transparent 90%, refraction roughness, IOR 1.4;
  Coat       a red base under a clear coat 70%;
  Skin       subsurface 60% with its colour and distance;
  Glow       luminous intensity 3 with its colour;
  Rough      roughness 80%, specular amount 0.
Saved as <out>/plain.lxo. MOONRAY_PROBE_OUT is the folder (default test-results/plain-materials in this checkout)."""
import json
import os
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results')
out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or root / 'plain-materials')
out.mkdir(parents=True, exist_ok=True)
report = {}

SETTINGS = {
    'Diffuse': {'diffCol': (.8, .35, .1), 'diffAmt': .9, 'diffRough': .5, 'specAmt': .04},
    'Glossy': {'diffCol': (.1, .2, .6), 'specAmt': .3, 'specCol': (1, .8, .6), 'rough': .2},
    'Metal': {'diffCol': (.9, .7, .3), 'reflAmt': .8, 'reflCol': (.95, .75, .35), 'specAmt': .8, 'specCol': (.95, .75, .35), 'rough': .3, 'metallic': 1.0},
    'Glass': {'diffCol': (.9, .9, .9), 'diffAmt': .1, 'tranAmt': .9, 'tranCol': (.8, 1, .9), 'tranRough': .1, 'refIndex': 1.4, 'specAmt': .05},
    'Coat': {'diffCol': (.7, .05, .05), 'coatAmt': .7, 'coatRough': .05, 'specAmt': .1, 'rough': .5},
    'Skin': {'diffCol': (.9, .6, .5), 'subsAmt': .6, 'subsCol': (1, .4, .3), 'subsDist': .05},
    'Glow': {'diffCol': (.2, .2, .2), 'lumiCol': (1, .5, .1), 'radiance': 3.0},
    'Rough': {'diffCol': (.4, .8, .4), 'specAmt': 0.0, 'rough': .8},
}


def sphere(name, x, material):
    lx.eval('item.create mesh {%s}' % name)
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.sphere on')
    for axis, value in (('cenX', x), ('cenY', 0), ('cenZ', 0), ('sizeX', .45), ('sizeY', .45), ('sizeZ', .45), ('sides', 32), ('segments', 16)):
        lx.eval('tool.attr prim.sphere %s %s' % (axis, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s}' % material)
    lx.eval('select.type item')
    return mesh


def set_channel(item, name, value):
    if isinstance(value, tuple):
        for axis, v in zip('RGB', value):
            item.channel(name + '.' + axis).set(v)
    else:
        item.channel(name).set(value)


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1280), ('resY', 240), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-6, -.46, -3), (-6, -.46, 3), (6, -.46, 3), (6, -.46, -3))]
        geo.polygons.new(points)
    names = list(SETTINGS)
    for c, name in enumerate(names):
        sphere(name, -4.2 + 1.2 * c, name)
    camera = scene.renderCamera
    camera.position.set((0.0, 0.3, 9.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    report['set'] = {}
    for mask in scene.items('mask', superType=False):
        tag = mask.channel('ptag').get()
        if tag not in SETTINGS:
            continue
        material = next(i for i in mask.children() if i.type == 'advancedMaterial')
        material.name = 'M_' + tag
        done = report['set'][tag] = []
        for channel_name, value in SETTINGS[tag].items():
            try:
                set_channel(material, channel_name, value)
                done.append(channel_name)
            except Exception as exc:
                done.append('%s: %s' % (channel_name, exc))
    report['children'] = [(i.name, i.type) for i in reversed(list(render.children()))]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'plain.lxo'))
    report['saved'] = str(out / 'plain.lxo')
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report-scene.json').write_text(json.dumps(report, indent=1, default=str))
