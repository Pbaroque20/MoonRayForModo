# python
"""GUI: whether the kit can load a Scene Proxy's file into a private scene of its own (not the user's), to read the
proxy's materials from: CreateScene, then SubSceneLoad of the proxy's file into it. Opens
test-results/references/proxy.lxo. Writes test-results/references/proxy_layers.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {}
held = {}


def save():
    (out / 'proxy_layers.json').write_text(json.dumps(result, indent=1, default=str))


def step(name, call):
    try:
        result[name] = call()
    except Exception:
        result[name] = {'error': traceback.format_exc()}
    save()


def listing(scene):
    found = []
    for index in range(scene.ItemCount(lx.symbol.iTYPE_ANY)):
        item = scene.ItemByIndex(lx.symbol.iTYPE_ANY, index)
        kind = lx.service.Scene().ItemTypeName(item.Type())
        if kind in ('mesh', 'mask', 'advancedMaterial', 'proxy', 'defaultShader', 'polyRender'):
            found.append((item.Ident(), kind, item.UniqueName()))
    return found


def scenes():
    root = lx.object.Scene(lx.service.Scene().Root())
    return [lx.object.Scene(root.SubSceneByIndex(lx.symbol.iTYPE_ANY, i)).Filename() for i in range(root.SubSceneCount(lx.symbol.iTYPE_ANY))]


lx.eval('!scene.open {%s} normal' % (out / 'proxy.lxo'))
path = str(out / 'src.lxo')


def create():
    held['private'] = lx.object.Scene(lx.service.Scene().CreateScene())
    return {'file': held['private'].Filename(), 'items': listing(held['private']), 'scenes': scenes()}


def load(monitor):
    sub = lx.service.Scene().SubSceneLoad(held['private'], path, monitor)
    held['sub'] = lx.object.Scene(sub)
    return {'file': held['sub'].Filename(), 'items': listing(held['sub']), 'scenes': scenes(),
            'private_items': listing(held['private']), 'current': modo.Scene().scene.Filename()}


def wrapped():
    scene = modo.Scene(held['sub'])
    material = [i for i in scene.iterItems() if i.type == 'advancedMaterial' and 'RefRed' in i.name][0]
    return {'material': material.name, 'diffCol': str(material.channel('diffCol').get()),
            'render_item': scene.renderItem.id if scene.renderItem else None, 'current': modo.Scene().scene.Filename()}


step('create', create)
step('load_none', lambda: load(None))
if 'sub' not in held:
    step('load_monitor', lambda: load(lx.object.Monitor()))
step('wrapped', wrapped)
step('destroy', lambda: (lx.service.Scene().DestroyScene(held['private']), scenes())[1])
save()
lx.eval('!app.quit')
