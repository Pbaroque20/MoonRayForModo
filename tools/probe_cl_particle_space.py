# python
"""Command line: in which space Modo hands a Blob's particles over, how long reading many takes, and what other
particle sources give. A mesh of 100,000 points moved to x = 5 and scaled 2 as a Blob's source: the first particles read
through ItemToParticle and the seconds the read takes (Python's TriangleSoup). Then the item types whose names speak of
particles, and a Particle Generator / Surface Generator where they can be made, read the same way (their features).
Writes report.json into MOONRAY_PROBE_OUT (default test-results/particle-space in this checkout)."""
import json
import os
import pathlib
import time
import traceback
import lx
import lxifc
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-ab5779a40d6c39b81\test-results\particle-space')
out.mkdir(parents=True, exist_ok=True)
report = {}


class Soup(lxifc.TriangleSoup):
    def __init__(self, size):
        self.size = size
        self.points = []

    def soup_TestBox(self, bbox):
        return True

    def soup_Segment(self, segID, stype):
        return True

    def soup_Vertex(self, vbuf):
        vbuf.setType('f')
        vbuf.setSize(self.size)
        self.points.append(vbuf.get())
        return len(self.points) - 1

    def soup_Polygon(self, v0, v1, v2):
        pass

    def soup_Connect(self, kind):
        pass


def read(scene, source, time_at=0.0, names=None):
    chan = lx.object.ChannelRead(lx.object.Scene(scene).Channels(None, time_at))
    surface = lx.object.TableauSurface(lx.service.Particle().ItemToParticle(lx.object.Item(source), chan))
    have = [surface.FeatureByIndex(lx.symbol.iTBLX_PARTICLES, i) for i in range(surface.FeatureCount(lx.symbol.iTBLX_PARTICLES))]
    vertex = lx.service.Tableau().AllocVertex()
    for name in (names or have):
        if name in have:
            vertex.AddFeature(lx.symbol.iTBLX_PARTICLES, name)
    surface.SetVertex(vertex)
    soup = Soup(vertex.Size())
    started = time.perf_counter()
    surface.Sample(((-1e9, -1e9, -1e9), (1e9, 1e9, 1e9)), -1.0, soup)
    return have, soup.points, time.perf_counter() - started


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Many')
    started = time.perf_counter()
    with mesh.geometry as geo:
        for i in range(100000):
            geo.vertices.new(((i % 100) * 0.01, ((i // 100) % 100) * 0.01, (i // 10000) * 0.01))
    report['made seconds'] = time.perf_counter() - started
    mesh.position.set((5.0, 0.0, 0.0))
    mesh.scale.set((2.0, 2.0, 2.0))
    blob = scene.addItem('blob', name='Blob')
    lx.eval('select.item {%s} set' % blob.id)
    lx.eval('volume.particle {%s}' % mesh.id)
    have, points, seconds = read(scene, mesh, names=['pos', 'id', 'size'])
    report['many'] = {'features': have, 'count': len(points), 'first': [list(p) for p in points[:3]], 'last': list(points[-1]), 'seconds': seconds}
    have, points, seconds = read(scene, mesh, names=['pos'])
    report['many pos only seconds'] = seconds
    # The Blob's own evaluated particle channel: what it renders from.
    try:
        chan = lx.object.ChannelRead(lx.object.Scene(scene).Channels(None, 0.0))
        value = chan.ValueObj(lx.object.Item(blob), lx.object.Item(blob).ChannelLookup('particleObj'))
        kinds = []
        for name in dir(lx.object):
            if name.startswith('_'):
                continue
            try:
                if getattr(lx.object, name)(value).test():
                    kinds.append(name)
            except Exception:
                pass
        report['particleObj interfaces'] = kinds
        if 'ValueReference' in kinds:
            reference = lx.object.ValueReference(value)
            report['reference set'] = reference.IsSet()
            value = reference.GetObject()
            kinds = []
            for name in dir(lx.object):
                if name.startswith('_'):
                    continue
                try:
                    if getattr(lx.object, name)(value).test():
                        kinds.append(name)
                except Exception:
                    pass
            report['particleObj referenced interfaces'] = kinds
        if 'TableauSurface' in kinds:
            surface = lx.object.TableauSurface(value)
            have = [surface.FeatureByIndex(lx.symbol.iTBLX_PARTICLES, i) for i in range(surface.FeatureCount(lx.symbol.iTBLX_PARTICLES))]
            vertex = lx.service.Tableau().AllocVertex()
            for name in have:
                vertex.AddFeature(lx.symbol.iTBLX_PARTICLES, name)
            surface.SetVertex(vertex)
            soup = Soup(vertex.Size())
            surface.Sample(((-1e9, -1e9, -1e9), (1e9, 1e9, 1e9)), -1.0, soup)
            report['particleObj read'] = {'features': have, 'count': len(soup.points), 'first': [list(p) for p in soup.points[:2]]}
    except Exception:
        report['particleObj error'] = traceback.format_exc()
    service = lx.service.Scene()
    types = []
    for i in range(service.ItemTypeCount()):
        try:
            name = service.ItemTypeName(service.ItemTypeByIndex(i))
        except Exception:
            continue
        if any(w in name.lower() for w in ('partic', 'emit', 'gen', 'sim', 'cache', 'cloud', 'pcache', 'csv')):
            types.append(name)
    report['types'] = sorted(types)
    for kind in report['types']:
        if kind in ('particleGen', 'surfGen', 'pSource', 'particleSim', 'particle.generator', 'surfaceGenerator', 'pgen', 'csvCache', 'pcache.cache', 'particleCache'):
            try:
                item = scene.addItem(kind)
                try:
                    have, points, seconds = read(scene, item, time_at=1.0)
                    report.setdefault('generators', {})[kind] = {'features': have, 'count': len(points), 'first': [list(p) for p in points[:2]]}
                except Exception as exc:
                    report.setdefault('generators', {})[kind] = 'read: %s' % exc
            except Exception as exc:
                report.setdefault('generators', {})[kind] = 'add: %s' % exc
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
