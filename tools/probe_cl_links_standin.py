# python
"""Headless: a stand-in for a linked mesh (links.py, the stand-in library). A box linked; a small pyramid (OBJ) imported
into its link file (scene.open import), named '<mesh> Stand-in', saved; the proxy told its preview item is the stand-in
and its render item the box (proxy.previewItem, proxy.renderItem). Then what the kit reads to render (host.snapshot: the
stand-in must not be there), the proxy's channels, and what the file holds. Written to test-results/links/standin."""
import json
import pathlib
import shutil
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\links-manager\test-results\links\standin')
if out.exists():
    shutil.rmtree(str(out))
out.mkdir(parents=True)
result = {}


def save():
    (out / 'standin.json').write_text(json.dumps(result, indent=1, default=str))


def rendered():
    from moonray_modo import host
    snap = host.snapshot()
    return sorted((m.get('name'), m.get('identity'), len(m.get('vertices') or [])) for m in snap.get('meshes', []))


(out / 'pyramid.obj').write_text('\n'.join([
    'o Pyramid', 'v -0.5 0 -0.5', 'v 0.5 0 -0.5', 'v 0.5 0 0.5', 'v -0.5 0 0.5', 'v 0 1 0',
    'f 1 2 3 4', 'f 1 5 2', 'f 2 5 3', 'f 3 5 4', 'f 4 5 1', '']))
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
    proxy = list(modo.Scene().items('proxy'))[0]
    path = pathlib.Path(links.read_tag(proxy)['file'])
    result['rendered_linked'] = rendered()
    save()
    main = modo.Scene()
    lx.eval('!scene.open {%s} normal' % path)
    before = {m.id for m in modo.Scene().items('mesh')}
    try:
        lx.eval('!scene.open {%s} import' % (out / 'pyramid.obj'))
        result['import'] = 'scene.open import'
    except Exception:
        result['import_error'] = traceback.format_exc()[-300:]
    made = [m for m in modo.Scene().items('mesh') if m.id not in before]
    result['imported'] = [(m.name, m.geometry.numVertices, m.parent.name if m.parent else None) for m in made]
    result['file_scene'] = modo.Scene().filename
    if made:
        made[0].name = 'Box Stand-in'
        made[0].scale.set([1.0, 1.0, 1.0])
    lx.eval('!scene.save')
    lx.eval('!scene.close')
    links._back_to(main)
    save()
    links.reload(proxy, path)
    lx.eval('select.item {%s} set' % proxy.id)
    for command in ('!proxy.previewItem item:{%s} name:{Box Stand-in}' % proxy.id, '!proxy.renderItem item:{%s} name:{Box}' % proxy.id):
        try:
            lx.eval(command)
            result.setdefault('commands', []).append(command)
        except Exception:
            result.setdefault('command_errors', []).append(command + ': ' + traceback.format_exc()[-200:])
    result['proxy_channels'] = {n: str(proxy.channel(n).get()) for n in proxy.channelNames
                                if any(w in n.lower() for w in ('item', 'scene', 'preview', 'render', 'draw', 'display'))}
    result['rendered_with_standin'] = rendered()
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
save()
try:
    lx.eval('!scene.close')
except Exception:
    pass
