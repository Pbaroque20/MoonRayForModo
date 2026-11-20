# python
"""Headless: what Modo's Scene Proxy commands do when run from Python, for the Links panel (links.py). A new scene with
a red cube 'Box' (tagged, moved, a material of its own), saved; then proxy.convert writes it to a file of its own and
puts a proxy in its place, proxy.restore brings it back, proxy.sceneFile points a proxy at another file. After each:
the items, their types, names, places and tags, the scene's own file name, the selection, and the files on disk.
Written to test-results/links/commands.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links'))
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*.lxo'):
    old.unlink()
result = {'steps': []}


def items():
    found = []
    for item in modo.Scene().items():
        if item.type in ('mesh', 'sceneProxy', 'proxy') or 'proxy' in item.type.lower():
            row = {'name': item.name, 'id': item.id, 'type': item.type}
            try:
                row['position'] = [round(v, 3) for v in item.position.get()] if hasattr(item, 'position') else None
            except Exception:
                row['position'] = None
            try:
                row['tag'] = item.readTag('MRLK')
            except Exception as exc:
                row['tag'] = 'unreadable: %s' % exc
            try:
                if item.type == 'mesh':
                    row['points'] = item.geometry.numVertices
                    row['materials'] = sorted({p.materialTag for p in item.geometry.polygons})
            except Exception:
                pass
            try:
                row['channels'] = [n for n in item.channelNames if any(w in n.lower() for w in ('scene', 'file', 'proxy', 'display', 'source'))]
                for name in row['channels']:
                    try:
                        row.setdefault('values', {})[name] = str(item.channel(name).get())
                    except Exception:
                        pass
            except Exception:
                pass
            found.append(row)
    return found


def note(step, **extra):
    row = dict(step=step, items=items(), scene_file=modo.Scene().filename,
               selected=[i.name for i in modo.Scene().selected], files=sorted(p.name for p in out.glob('*.lxo')), **extra)
    result['steps'].append(row)
    (out / 'commands.json').write_text(json.dumps(result, indent=1, default=str))


def attempt(step, command):
    try:
        lx.eval(command)
        note(step, command=command)
        return True
    except Exception:
        note(step, command=command, error=traceback.format_exc()[-600:])
        return False


try:
    lx.eval('scene.new')
    lx.eval('item.create mesh {Box}')
    box = next(i for i in modo.Scene().items('mesh') if i.name == 'Box')
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {BoxMat} {0.8 0.1 0.1} 0.8 0.04 true false')
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % box.id)
    lx.eval('transform.channel pos.X 1.5')
    lx.eval('transform.channel pos.Z -2.0')
    box.setTag('MRLK', 'linked-box')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'main.lxo'))
    note('made and saved')
    target = out / 'box.lxo'
    lx.eval('select.item {%s} set' % box.id)
    attempt('convert', '!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (box.id, target))
    proxies = [i for i in modo.Scene().items() if 'proxy' in i.type.lower()]
    result['proxy_types'] = sorted({i.type for i in proxies})
    if proxies:
        proxy = proxies[0]
        try:
            proxy.setTag('MRLK', 'linked-proxy')
        except Exception as exc:
            result['proxy_tag_error'] = str(exc)
        note('proxy tagged')
        attempt('restore', '!proxy.restore item:{%s}' % proxy.id)
        meshes = [i for i in modo.Scene().items('mesh') if i.name.startswith('Box')]
        if meshes:
            lx.eval('select.item {%s} set' % meshes[0].id)
            lx.eval('transform.channel pos.Y 0.75')
            note('restored mesh moved up')
            attempt('convert again', '!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (meshes[0].id, target))
            proxies = [i for i in modo.Scene().items() if 'proxy' in i.type.lower()]
            if proxies:
                other = out / 'box-relinked.lxo'
                import shutil
                shutil.copyfile(str(target), str(other))
                attempt('relink', '!proxy.sceneFile item:{%s} filename:{%s}' % (proxies[0].id, other))
    lx.eval('!scene.save')
    note('saved again')
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
(out / 'commands.json').write_text(json.dumps(result, indent=1, default=str))
