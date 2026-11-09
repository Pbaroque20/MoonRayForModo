# python
"""GUI: where a Scene Proxy's geometry can be read once Modo loads it.

Needs test-results/references/src.lxo (tools/probe_references.py makes it: RefCube at x=2, red). A new scene gets a
Proxy item of it, moved to z=-3 and turned 45 degrees about Y, rendering RefCube. After proxy.loadRenderItem: the
scene's sub-scenes and their items, the kit's snapshot (direct and through Modo's render cache), and Modo's own render
(proxy-modo.png). Writes test-results/references/proxy.json."""
import json
import os
import pathlib
import traceback
import lx
import lxu.select
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
src = out / 'src.lxo'
result = {}


def save():
    (out / 'proxy.json').write_text(json.dumps(result, indent=1, default=str))


def step(name, call):
    try:
        result[name] = call()
    except Exception:
        result[name] = {'error': traceback.format_exc()}
    save()


def main_scene():
    return lx.object.Scene(lxu.select.SceneSelection().current())


def scene_items(scene):
    listed = []
    for index in range(scene.ItemCount(lx.symbol.iTYPE_ANY)):
        item = scene.ItemByIndex(lx.symbol.iTYPE_ANY, index)
        kind = lx.service.Scene().ItemTypeName(item.Type())
        if kind in ('mesh', 'groupLocator', 'locator', 'mask', 'advancedMaterial', 'proxy', 'meshInst', 'sunLight'):
            listed.append((item.Ident(), kind, item.UniqueName()))
    return listed


def sub_scenes():
    scene = main_scene()
    found = {}
    for kind in (lx.symbol.iTYPE_ANY, lx.service.Scene().ItemTypeLookup('proxy'), lx.service.Scene().ItemTypeLookup('mesh')):
        try:
            count = scene.SubSceneCount(kind)
        except Exception as exc:
            found[str(kind)] = 'raised ' + str(exc)
            continue
        entries = []
        for index in range(count):
            try:
                sub = lx.object.Scene(scene.SubSceneByIndex(kind, index))
                entries.append({'file': sub.Filename(), 'items': scene_items(sub)})
            except Exception as exc:
                entries.append('raised ' + str(exc))
        found[str(kind)] = {'count': count, 'scenes': entries}
    return found


def kit_read(evaluated):
    from moonray_modo import host
    snap = host.snapshot(evaluated_geometry=evaluated)
    return {'meshes': [(m.get('name'), m.get('identity'), len(m.get('vertices') or []), (m.get('vertices') or [None])[0])
                       for m in snap.get('meshes', [])], 'materials': sorted(snap.get('materials', {}))}


def proxy_channels(proxy):
    held = {}
    for name in ('scene', 'itemRender', 'itemPreview', 'previewRender', 'replaceShader', 'render', 'visible'):
        try:
            held[name] = str(proxy.channel(name).get())
        except Exception as exc:
            held[name] = 'raised ' + str(exc)
    return held


def _graph_ok(item, name):
    try:
        item.itemGraph(name)
        return True
    except Exception:
        return False


try:
    scene = modo.Scene()
    lx.eval('item.create proxy')
    proxy = [i for i in scene.iterItems() if i.type == 'proxy'][0]
    lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (proxy.id, src))
    step('render_item', lambda: lx.eval('!proxy.renderItem item:{%s} name:{RefCube}' % proxy.id))
    lx.eval('select.item {%s} set' % proxy.id)
    lx.eval('transform.channel pos.Z -3')
    lx.eval('transform.channel rot.Y 45')
    lx.eval('select.drop item')
    step('channels', lambda: proxy_channels(proxy))
    step('before_load_sub', sub_scenes)
    step('load', lambda: lx.eval('!proxy.loadRenderItem allitem:true'))
    step('after_load_sub', sub_scenes)
    step('after_load_main', lambda: scene_items(main_scene()))
    step('kit_direct', lambda: kit_read(False))
    step('kit_cache', lambda: kit_read(True))
    step('graphs', lambda: {g: [i.id for i in proxy.itemGraph(g).forward()] + ['<-'] + [i.id for i in proxy.itemGraph(g).reverse()]
                            for g in ('shadeLoc', 'source', 'parent', 'proxyRender', 'proxy')
                            if _graph_ok(proxy, g)})
    for name, value in (('resX', 480), ('resY', 270), ('first', 1), ('last', 1)):
        scene.renderItem.channel(name).set(value)
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('transform.channel pos.X 0')
    lx.eval('transform.channel pos.Y 2')
    lx.eval('transform.channel pos.Z 6')
    lx.eval('transform.channel rot.X -15')
    lx.eval('select.drop item')
    step('modo_render', lambda: lx.eval('!render.animation {%s} PNG' % (out / 'proxy-modo')))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'proxy.lxo'))
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')

