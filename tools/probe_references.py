# python
"""GUI: what Modo shows of a referenced scene and of a Scene Proxy, and what the kit reads of each.

A small scene (src.lxo: a cube 'RefCube' at x=2 with a red material 'RefRed') is saved; a new scene imports it as a
reference (scene.importReference), and a third holds a Scene Proxy item pointing at it. For each: the items Modo lists,
their methods and channels where they tell what is referenced, and the meshes the kit's snapshot finds, read directly
and through Modo's render cache. Writes test-results/references/report.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def step(name, call):
    try:
        result[name] = call()
    except Exception:
        result[name] = {'error': traceback.format_exc()}
    save()


def cube(scene, name, x):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        corners = [geo.vertices.new((x + (i & 1) - .5, ((i >> 1) & 1) - .5 + .5, ((i >> 2) & 1) - .5)) for i in range(8)]
        for face in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
            geo.polygons.new([corners[k] for k in face])
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial RefRed {0.8 0.1 0.1} 0.8 0.04 true false')
    lx.eval('select.type item')
    lx.eval('select.drop item')
    return mesh


def items(scene):
    listed = []
    for item in scene.iterItems():
        raw = item._item
        entry = {'id': item.id, 'type': item.type, 'name': item.name}
        for method in ('IsReferenced', 'Reference', 'Source', 'WasLoaded'):
            if hasattr(raw, method):
                try:
                    value = getattr(raw, method)()
                    entry[method] = value if isinstance(value, (bool, int, str)) else repr(value)
                except Exception as exc:
                    entry[method] = 'raised ' + str(exc)
        try:
            entry['scene'] = lx.object.Scene(raw.Context()).Filename() if hasattr(raw, 'Context') else None
        except Exception as exc:
            entry['scene'] = 'raised ' + str(exc)
        if item.type == 'mesh':
            try:
                entry['polygons'] = modo.meshgeometry.MeshProvider.meshFromMeshChannel(raw, 'deformed').PolygonCount()
            except Exception as exc:
                entry['polygons'] = 'raised ' + str(exc)
        if item.type == 'proxy':
            entry['channels'] = {}
            for name in item.channelNames:
                try:
                    entry['channels'][name] = str(item.channel(name).get())
                except Exception:
                    pass
        listed.append(entry)
    return listed


def kit_read(evaluated):
    from moonray_modo import host
    snap = host.snapshot(evaluated_geometry=evaluated)
    return {'meshes': [(m.get('name'), m.get('identity'), len(m.get('vertices') or [])) for m in snap.get('meshes', [])],
            'materials': sorted(snap.get('materials', {})), 'lights': len(snap.get('lights', []))}


def scene_methods():
    scene = lx.object.Scene(modo.Scene().GetScene() if hasattr(modo.Scene(), 'GetScene') else lx.service.Scene())
    return [m for m in dir(scene) if 'Sub' in m or 'Ref' in m]


src = out / 'src.lxo'
try:
    if not src.is_file():
        # The first run only makes the source scene: one open in Modo cannot be referenced.
        scene = modo.Scene()
        cube(scene, 'RefCube', 2.0)
        lx.eval('!scene.saveAs {%s} $LXOB false' % src)
        save()
        lx.eval('!app.quit')
        raise SystemExit
    # A scene referencing it.
    lx.eval('!scene.importReference {%s} true true true true true' % src)
    master = modo.Scene()
    cube(master, 'LocalCube', -2.0)
    result['reference_items'] = items(master)
    save()
    step('reference_scene_methods', lambda: [m for m in dir(lx.object.Scene) if 'Sub' in m or 'Ref' in m or 'Load' in m])
    step('reference_item_methods', lambda: [m for m in dir(lx.object.Item) if 'Ref' in m or 'Source' in m or 'Load' in m])
    step('reference_kit_direct', lambda: kit_read(False))
    step('reference_kit_cache', lambda: kit_read(True))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'referencing.lxo'))
    # A scene with a Scene Proxy of it.
    lx.eval('!scene.new')
    proxy_scene = modo.Scene()
    cube(proxy_scene, 'LocalCube', -2.0)
    lx.eval('item.create proxy')
    proxy = [i for i in proxy_scene.iterItems() if i.type == 'proxy'][0]
    step('proxy_scene_file', lambda: lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (proxy.id, src)))
    step('proxy_items', lambda: items(proxy_scene))
    step('proxy_kit_direct', lambda: kit_read(False))
    step('proxy_kit_cache', lambda: kit_read(True))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'proxy.lxo'))
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
