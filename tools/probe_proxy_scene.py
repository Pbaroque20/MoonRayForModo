# python
"""GUI: whether Python can reach the scene a Scene Proxy loads (its materials are items of that scene, named in the
render cache's shader layers). Opens test-results/references/proxy.lxo, reads the render cache, then asks for sub-scenes
and tries loading the proxy's file as a sub-scene. Writes test-results/references/proxy_scene.json."""
import json
import os
import pathlib
import traceback
import lx
import lxu.select
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {}


def save():
    (out / 'proxy_scene.json').write_text(json.dumps(result, indent=1, default=str))


def step(name, call):
    try:
        result[name] = call()
    except Exception:
        result[name] = {'error': traceback.format_exc()}
    save()


def main_scene():
    return lx.object.Scene(lxu.select.SceneSelection().current())


def listing(scene):
    found = []
    for index in range(scene.ItemCount(lx.symbol.iTYPE_ANY)):
        item = scene.ItemByIndex(lx.symbol.iTYPE_ANY, index)
        kind = lx.service.Scene().ItemTypeName(item.Type())
        if kind in ('mesh', 'mask', 'advancedMaterial', 'defaultShader', 'groupLocator', 'proxy'):
            found.append((item.Ident(), kind, item.UniqueName()))
    return found


def subs():
    scene = main_scene()
    found = []
    for index in range(scene.SubSceneCount(lx.symbol.iTYPE_ANY)):
        sub = lx.object.Scene(scene.SubSceneByIndex(lx.symbol.iTYPE_ANY, index))
        found.append({'file': sub.Filename(), 'items': listing(sub)})
    return found


lx.eval('!scene.open {%s} normal' % (out / 'proxy.lxo'))
step('service', lambda: [m for m in dir(lx.service.Scene()) if not m.startswith('_')])
step('objects', lambda: [m for m in dir(lx.object) if 'Cache' in m or 'Proxy' in m or 'Scene' in m])
step('subs_before', subs)
from moonray_modo import evaluated
step('capture', lambda: len(evaluated.capture(0.0)['surfaces']))
step('subs_after_cache', subs)
proxy = [i for i in modo.Scene().iterItems() if i.type == 'proxy'][0]
lx.eval('select.item {%s} set' % proxy.id)
step('load_selected', lambda: lx.eval('!proxy.loadRenderItem'))
step('subs_after_load', subs)
step('main_items', lambda: listing(main_scene()))
step('graphs', lambda: [(lx.service.Scene().GraphName(g) if hasattr(lx.service.Scene(), 'GraphName') else g) for g in []])


def sub_load():
    service = lx.service.Scene()
    scene = main_scene()
    sub = service.SubSceneLoad(scene, proxy.channel('scene').get(), None)
    sub = lx.object.Scene(sub)
    return {'file': sub.Filename(), 'items': listing(sub), 'subs_now': subs()}


step('sub_load', sub_load)
save()
lx.eval('!app.quit')
