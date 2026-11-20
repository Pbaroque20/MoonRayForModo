# python
"""Headless: Modo's own render of a red box at x = -1.2 and a blue one at x = 1.2, embedded, then the red one made a
proxy by proxy.convert; and what Modo's render cache gives the kit for it then (evaluated.capture). Whether Modo itself
places a converted proxy where its mesh stood. Written to test-results/links/modo-render."""
import json
import pathlib
import shutil
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\modo-render')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {}


def save():
    (out / 'render.json').write_text(json.dumps(result, indent=1, default=str))


def cube(name, x, colour):
    lx.eval('item.create mesh {%s}' % name)
    item = [i for i in modo.Scene().items('mesh') if i.name == name][0]
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s} {%s} 0.8 0.04 true false' % (name, colour))
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    item.position.set([x, 0.5, 0.0])
    return item


def render(name):
    lx.eval('!render.animation {%s} PNG' % (out / name))


try:
    lx.eval('scene.new')
    red = cube('Red', -1.2, '0.8 0.1 0.1')
    cube('Blue', 1.2, '0.1 0.2 0.8')
    scene = modo.Scene()
    for name, value in (('resX', 320), ('resY', 180), ('first', 1), ('last', 1)):
        scene.renderItem.channel(name).set(value)
    lx.eval('time.range scene 0.0 0.0')
    lx.eval('select.item {%s} set' % scene.renderCamera.id)
    for channel, value in (('pos.X', 0), ('pos.Y', 2.0), ('pos.Z', 6.0), ('rot.X', -12), ('rot.Y', 0)):
        lx.eval('transform.channel %s %s' % (channel, value))
    lx.eval('select.drop item')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    render('embedded')
    lx.eval('select.item {%s} set' % red.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (red.id, out / 'red.lxo'))
    proxy = list(modo.Scene().items('proxy'))[0]
    result['proxy_world'] = [round(v, 3) for v in modo.Matrix4(proxy.channel('worldMatrix').get()).position]
    render('converted')
    from moonray_modo import evaluated
    data = evaluated.capture(lx.service.Selection().GetTime())
    result['surfaces'] = [(s.get('source_item'), s.get('instanced'), [round(v, 3) for v in (s.get('matrix') or [])[12:15]]) for s in data['surfaces']]
    result['files'] = sorted(p.name for p in out.glob('*.png'))
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
# Closed before quitting: Modo crashes on quit with a proxy's scene open (scene-proxy-references-round).
try:
    lx.eval('!scene.close')
except Exception:
    pass
