# python
"""Headless: which proxy layout renders a linked mesh where it stood, in Modo's renderer and in the render cache the kit
reads (evaluated.capture). Three red boxes at x = -1.5, 0 (raised, turned) and 1.5, each linked another way:
  A: proxy.convert as it is (the file's mesh keeps its place, the proxy too).
  B: proxy.convert, then the file's mesh put at the origin (its place zeroed in the file) and the proxy told to read it
     again (proxy.sceneFile to the same file).
  C: B's file, and a proxy made by hand (item.create proxy) given the mesh's place.
Also what proxy.restore makes of B and C (where the mesh comes back). A grey reference box at each place, embedded,
rendered first. Written to test-results/links/layout."""
import json
import math
import pathlib
import shutil
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\layout')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {}


def save():
    (out / 'layout.json').write_text(json.dumps(result, indent=1, default=str))


def find(name, kind=None):
    return [i for i in modo.Scene().items() if i.name == name and (kind is None or i.type == kind)]


def world(item):
    return [round(v, 3) for v in modo.Matrix4(item.channel('worldMatrix').get()).position]


PLACES = {'A': ([-1.5, 0.5, 0.0], [0.0, 0.0, 0.0]), 'B': ([0.0, 1.0, 0.0], [0.0, math.radians(30), 0.0]), 'C': ([1.5, 0.5, 0.0], [0.0, 0.0, math.radians(20)])}


def cube(name, place, turn, colour):
    lx.eval('item.create mesh {%s}' % name)
    item = find(name, 'mesh')[0]
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
        lx.eval('tool.attr prim.cube size%s 0.8' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s} {%s} 0.8 0.04 true false' % (colour[0], colour[1]))
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    item.position.set(place)
    item.rotation.set(turn)
    return item


def zero_file(path, name):
    lx.eval('!scene.open {%s} normal' % path)
    mesh = find(name, 'mesh')[0]
    mesh.position.set([0.0, 0.0, 0.0])
    mesh.rotation.set([0.0, 0.0, 0.0])
    mesh.scale.set([1.0, 1.0, 1.0])
    lx.eval('!scene.save')
    lx.eval('!scene.close')


def render(name):
    lx.eval('!render.animation {%s} PNG' % (out / name))


def surfaces():
    from moonray_modo import evaluated
    data = evaluated.capture(lx.service.Selection().GetTime())
    found = [(s.get('source_item'), s.get('instanced'), [round(v, 3) for v in (s.get('matrix') or [])[12:15]]) for s in data['surfaces']]
    evaluated.proxies(data, modo.Scene(), lx.service.Selection().GetTime(), [])
    kept = [(s.get('source_item'), s.get('instanced'), [round(v, 3) for v in (s.get('matrix') or [])[12:15]]) for s in data['surfaces']]
    return {'captured': found, 'kept': kept}


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    for name, value in (('resX', 480), ('resY', 270), ('first', 1), ('last', 1)):
        scene.renderItem.channel(name).set(value)
    lx.eval('time.range scene 0.0 0.0')
    camera = scene.renderCamera
    camera.position.set([0.0, 2.0, 7.0])
    camera.rotation.set([math.radians(-12), 0.0, 0.0])
    for key, (place, turn) in PLACES.items():
        cube(key, place, turn, ('Red', '0.8 0.1 0.1'))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    render('0-embedded')
    result['embedded'] = surfaces()
    save()
    for key in 'ABC':
        mesh = find(key, 'mesh')[0]
        lx.eval('select.drop item')
        lx.eval('select.item {%s} set' % mesh.id)
        lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (mesh.id, out / (key + '.lxo')))
    for key in 'BC':
        zero_file(out / (key + '.lxo'), key)
    proxy = find('B', 'proxy')[0]
    lx.eval('select.item {%s} set' % proxy.id)
    lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (proxy.id, out / 'B.lxo'))
    old = find('C', 'proxy')[0]
    place, turn = PLACES['C']
    lx.eval('select.item {%s} set' % old.id)
    lx.eval('!item.delete')
    lx.eval('item.create proxy')
    made = [i for i in modo.Scene().items('proxy') if i.name not in ('A', 'B')][0]
    lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (made.id, out / 'C.lxo'))
    made.name = 'C'
    lx.eval('select.item {%s} set' % made.id)
    for axis, value in zip('XYZ', place):
        lx.eval('transform.channel pos.%s %s' % (axis, value))
    for axis, value in zip('XYZ', turn):
        lx.eval('transform.channel rot.%s %s' % (axis, math.degrees(value)))
    result['proxies'] = {p.name: world(p) for p in modo.Scene().items('proxy')}
    render('1-linked')
    result['linked'] = surfaces()
    save()
    for key in 'BC':
        proxy = find(key, 'proxy')[0]
        lx.eval('select.item {%s} set' % proxy.id)
        lx.eval('!proxy.restore item:{%s}' % proxy.id)
    result['restored'] = {m.name: {'world': world(m), 'pos': [round(v, 3) for v in m.position.get()],
                                   'rot': [round(math.degrees(v), 2) for v in m.rotation.get()]} for m in modo.Scene().items('mesh') if m.name in 'BC'}
    render('2-restored')
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
try:
    lx.eval('!scene.close')
except Exception:
    pass
