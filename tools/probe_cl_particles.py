# python
"""Command line: how Modo hands over particles. A mesh of a few points, a Blob item; the scene's graphs with 'particle'
or 'source' in their names; Modo's particle service asked for the mesh's particles (ItemToParticle) and what interfaces
the object it gives has. Writes test-results/particles/report.json."""
import json
import pathlib
import traceback
import lx
import lxu
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\particles')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    cloud = scene.addMesh('Cloud')
    with cloud.geometry as geo:
        for x in range(4):
            for z in range(4):
                geo.vertices.new((x * 0.5, 0.0, z * 0.5))
    blob = scene.addItem('blob', name='Blob')
    raw = lx.object.Scene(scene.internalScene if hasattr(scene, 'internalScene') else lxu.select.SceneSelection().current())
    graphs = []
    for index in range(raw.GraphCount()):
        try:
            name = raw.GraphByIndex(index).Name()
        except Exception:
            continue
        graphs.append(name)
    report['graphs'] = [g for g in graphs if any(w in g.lower() for w in ('particle', 'source', 'blob', 'sprite', 'repl'))]
    report['all graphs'] = graphs
    # The blob's own channels that take an item.
    report['blob channels'] = [c.name for c in blob.channels() if 'particle' in c.name.lower() or 'source' in c.name.lower()]
    # Linked as a particle source, as Modo's Particle Source does.
    for command in ('item.link particle {%s} {%s}' % (cloud.id, blob.id), 'item.link particle {%s} {%s} replace:false' % (cloud.id, blob.id)):
        try:
            lx.eval(command)
            report['linked by'] = command
            break
        except Exception as exc:
            report.setdefault('link errors', []).append('%s: %s' % (command, exc))
    service = lx.service.Particle()
    tries = {}
    item = lx.object.Item(cloud)
    for label, reader in (('edit', lambda: raw.Channels(lx.symbol.s_ACTIONLAYER_EDIT, 0.0)),
                          ('evaluated', lambda: raw.Channels(None, 0.0)),
                          ('anim', lambda: raw.Channels(lx.symbol.s_ACTIONLAYER_ANIM, 0.0))):
        try:
            chan = lx.object.ChannelRead(reader())
            held = service.ItemToParticle(item, chan)
            found = []
            for name in dir(lx.object):
                kind = getattr(lx.object, name)
                try:
                    if kind(held).test():
                        found.append(name)
                except Exception:
                    pass
            tries[label] = found
            if 'TriangleGroup' in found:
                group = lx.object.TriangleGroup(held)
                tries[label + ' surfaces'] = group.Count()
        except Exception as exc:
            tries[label] = 'error: %s' % exc
    report['item to particle'] = tries
    # The blob's particle channel, evaluated.
    try:
        chan = lx.object.ChannelRead(raw.Channels(None, 0.0))
        value = chan.ValueObj(blob, blob.channel('particleObj').index)
        found = []
        for name in dir(lx.object):
            kind = getattr(lx.object, name)
            try:
                if kind(value).test():
                    found.append(name)
            except Exception:
                pass
        report['blob particleObj interfaces'] = found
    except Exception as exc:
        report['blob particleObj error'] = str(exc)
    report['blob links'] = [i.name for i in blob.itemGraph('particle').forward()] + [i.name for i in blob.itemGraph('particle').reverse()]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
