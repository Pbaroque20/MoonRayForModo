# python
"""Headless: where a proxy made by proxy.convert stands, as Modo's render cache gives it to the kit (evaluated.capture,
evaluated.proxies), beside one made by hand (item.create proxy, proxy.sceneFile, moved). The proxies' own transforms,
every surface's matrix before and after the kit's proxy filter, and Modo's own render where modo_cl renders.
Written to test-results/links/place.json."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\place')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {}


def save():
    (out / 'place.json').write_text(json.dumps(result, indent=1, default=str))


def world(item):
    try:
        return [round(v, 3) for v in modo.Matrix4(item.channel('worldMatrix').get()).position]
    except Exception as exc:
        return repr(exc)


def transforms(item):
    try:
        loc = lx.object.Locator(item.internalItem)
        found = {}
        for kind, name in ((lx.symbol.iXFRM_POSITION, 'pos'), (lx.symbol.iXFRM_ROTATION, 'rot'), (lx.symbol.iXFRM_SCALE, 'scl')):
            made = loc.GetTransformItem(kind)
            found[name] = modo.Item(made).id if made else None
        return found
    except Exception as exc:
        return repr(exc)


def surfaces(data):
    return [{k: (([round(v, 3) for v in s.get('matrix')[12:15]] if k == 'matrix' and s.get('matrix') else s.get(k)))
             for k in ('id', 'source_id', 'source_item', 'instanced', 'matrix', 'shading_scene')} for s in data['surfaces']]


try:
    lx.eval('scene.new')
    lx.eval('item.create mesh {Box}')
    box = [i for i in modo.Scene().items('mesh') if i.name == 'Box'][0]
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    box.position.set([-1.2, 0.0, 0.0])
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    # A file of a cube at the origin, for the proxy made by hand.
    lx.eval('item.create mesh {Ref}')
    ref = [i for i in modo.Scene().items('mesh') if i.name == 'Ref'][0]
    lx.eval('select.item {%s} set' % ref.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % ref.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (ref.id, out / 'ref.lxo'))
    for item in [i for i in modo.Scene().items('proxy') if i.name == 'Ref']:
        lx.eval('select.item {%s} set' % item.id)
        lx.eval('!item.delete')
    # The converted one.
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (box.id, out / 'box.lxo'))
    converted = [i for i in modo.Scene().items('proxy')][0]
    # One made by hand at x = 1.2.
    lx.eval('item.create proxy')
    hand = [i for i in modo.Scene().items('proxy') if i.id != converted.id][0]
    lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (hand.id, out / 'ref.lxo'))
    lx.eval('select.item {%s} set' % hand.id)
    lx.eval('transform.channel pos.X 1.2')
    result['proxies'] = {p.name: {'id': p.id, 'world': world(p), 'transforms': transforms(p), 'file': str(p.channel('scene').get())}
                         for p in modo.Scene().items('proxy')}
    save()
    from moonray_modo import evaluated
    time = lx.service.Selection().GetTime()
    data = evaluated.capture(time)
    result['captured'] = surfaces(data)
    evaluated.proxies(data, modo.Scene(), time, [])
    result['after_filter'] = surfaces(data)
    save()
    try:
        lx.eval('!render.animation {%s} PNG' % (out / 'modo'))
        result['modo_render'] = sorted(p.name for p in out.glob('modo*'))
    except Exception:
        result['modo_render'] = traceback.format_exc()[-300:]
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
