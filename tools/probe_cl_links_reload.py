# python
"""Headless: a proxy shown with its file as it is on disk after the file is written again (Done Editing). A cube linked
(8 points), brought back to edit, subdivided (26 points), made a proxy again; then the points the kit reads for the
proxy (host.snapshot) after each way of telling Modo to read the file again: PROBE_RELOAD=samefile (proxy.sceneFile to
the same file, as links did), unload (proxy.unload, then proxy.sceneFile), none. Written to
test-results/links/reload-<way>.json."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo

way = os.environ.get('PROBE_RELOAD', 'unload')
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\reload-' + way)
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {'way': way}


def save():
    (out / 'reload.json').write_text(json.dumps(result, indent=1, default=str))


def modo_counts():
    # Modo's own render cache, from plain Python: each surface's vertex count.
    flags = lx.symbol.fRENDERCACHE_TRACK_CURRENT_SCENE | lx.symbol.fRENDERCACHE_TURN_OFF_AUTO_UPDATES | lx.symbol.fRENDERCACHE_FORCE_FULL_UPDATE
    cache = lx.object.RenderCache(lx.service.RenderCache().CreateRenderCache(flags))
    cache.Update(float(lx.service.Selection().GetTime()), 0)
    found = []
    for index in range(cache.GeoSurfaceCount()):
        surface = lx.object.GeoCacheSurface(cache.GeoSurfaceAt(index)) if hasattr(cache, 'GeoSurfaceAt') else None
        if surface is None:
            found.append('no GeoSurfaceAt')
            break
        try:
            found.append(surface.GetVertexCount())
        except Exception as exc:
            found.append(repr(exc)[:80])
    del cache
    return found


def points():
    save()
    try:
        result.setdefault('modo', []).append(modo_counts())
    except Exception:
        result.setdefault('modo', []).append(traceback.format_exc()[-200:])
    from moonray_modo import host
    snap = host.snapshot()
    return sorted((m.get('name'), len(m.get('vertices') or [])) for m in snap.get('meshes', []))


try:
    from moonray_modo import links
    lx.eval('scene.new')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    lx.eval('item.create mesh {Box}')
    box = [i for i in modo.Scene().items('mesh') if i.name == 'Box'][0]
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('tool.set prim.cube on')
    for axis in 'XYZ':
        lx.eval('tool.attr prim.cube segments%s 1' % axis)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    box.position.set([1.0, 0.0, 0.0])
    links.run('link', [box.id], out / 'links')
    result['linked'] = points()
    save()
    proxy = [i for i in modo.Scene().items('proxy')][0]
    links.run('edit', [proxy.id])
    box = [i for i in modo.Scene().items('mesh') if i.name == 'Box'][0]
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.subdivide flat')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    result['editing'] = points()
    save()
    if way in ('unload', 'release', 'none'):
        # links._convert reloads by proxy.sceneFile to the same file; this probe replaces that step.
        original = links._convert

        def convert(mesh, path):
            lx_, modo_ = links._modo()
            scene = modo.Scene()
            name = mesh.name
            before = {item.id for item in scene.items('proxy')}
            links._only(mesh.id)
            lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (mesh.id, path))
            made = [item for item in scene.items('proxy') if item.id not in before][0]
            made.name = name
            links.settle(pathlib.Path(path), dict(links.read_tag(made) or {}, file=str(path)), name, scene)
            if way == 'release':
                from moonray_modo import evaluated
                evaluated.release_proxies()
            if way in ('unload', 'release'):
                links._only(made.id)
                lx.eval('!proxy.unload item:{%s} allitem:false' % made.id)
                lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (made.id, path))
            return made
        links._convert = convert
    box = [i for i in modo.Scene().items('mesh') if i.name == 'Box'][0]
    links.run('done', [box.id])
    result['done'] = points()
    save()
    if way == 'dot':
        made = [i for i in modo.Scene().items('proxy')][0]
        source = pathlib.Path(links.proxy_file(made))
        back = chr(92)
        for label, form in (('dot', str(source.parent) + back + '.' + back + source.name), ('slashes', str(source).replace(back, '/'))):
            lx.eval('select.item {%s} set' % made.id)
            lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (made.id, form))
            result[label] = {'form': form, 'channel': links.proxy_file(made), 'points': points()}
            save()
    if way == 'copy':
        made = [i for i in modo.Scene().items('proxy')][0]
        source = pathlib.Path(links.proxy_file(made))
        copy = source.with_name('Box copy.lxo')
        shutil.copyfile(str(source), str(copy))
        lx.eval('item.create proxy')
        other = [i for i in modo.Scene().items('proxy') if i.id != made.id][0]
        lx.eval('select.item {%s} set' % other.id)
        lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (other.id, copy))
        result['copy'] = points()
        save()
    if way == 'reopen':
        lx.eval('!scene.save')
        lx.eval('!scene.close')
        lx.eval('!scene.open {%s} normal' % (out / 'main.lxo'))
        result['reopened'] = points()
        lx.eval('!proxy.unload allitem:true')
        result['unloaded_all'] = points()
    result['finished'] = True
except Exception:
    result['error'] = traceback.format_exc()
(out / 'reload.json').write_text(json.dumps(result, indent=1, default=str))
try:
    lx.eval('!scene.close')
except Exception:
    pass
