# python
"""Command line: what Modo hands over for a Blob's and a Sprite's particles. Opens MOONRAY_PROBE_SCENE (default the
blob reference scene), and for each Blob and Sprite: its channels (name, type, value), its particle sources (the
'particle' graph), and each source read through lx.service.Particle().ItemToParticle: the TableauSurface's vertex
features, its bound, and the first particles sampled with every feature. Writes report.json into MOONRAY_PROBE_OUT
(default test-results/particle-read beside this checkout)."""
import json
import os
import pathlib
import time
import traceback
import lx
import lxifc
import modo

root = pathlib.Path(__file__).resolve().parents[1] if '__file__' in globals() else pathlib.Path.cwd()
out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-ab5779a40d6c39b81\test-results\particle-read')
out.mkdir(parents=True, exist_ok=True)
report = {}


class Soup(lxifc.TriangleSoup):
    def __init__(self, size):
        self.size = size
        self.points = []
        self.segments = []
        self.polys = 0

    def soup_TestBox(self, bbox):
        return True

    def soup_Segment(self, segID, stype):
        self.segments.append((segID, stype))
        return True

    def soup_Vertex(self, vbuf):
        vbuf.setType('f')
        vbuf.setSize(self.size)
        self.points.append(list(vbuf.get()))
        return len(self.points) - 1

    def soup_Polygon(self, v0, v1, v2):
        self.polys += 1

    def soup_Connect(self, kind):
        pass


def _test(name, obj):
    try:
        return bool(getattr(lx.object, name)(obj).test())
    except Exception:
        return False


try:
    report['particle service'] = [n for n in dir(lx.service.Particle()) if not n.startswith('_')]
    scene_path = os.environ.get('MOONRAY_PROBE_SCENE') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\blob-scene\blob_test.lxo'
    lx.eval('scene.open {%s} normal' % scene_path)
    scene = modo.Scene()
    report['symbols'] = {name: getattr(lx.symbol, name) for name in dir(lx.symbol) if 'TBLX' in name or 'PARTICLE' in name.upper() or 'PRTCL' in name}
    raw = lx.object.Scene(scene)
    for kind in ('blob', 'sprite'):
        for item in scene.items(kind):
            held = report.setdefault(item.name, {})
            chans = {}
            for c in item.channels():
                try:
                    chans[c.name] = [c.storageType, c.get()]
                except Exception as exc:
                    chans[c.name] = ['?', str(exc)]
            held['channels'] = chans
            held['sources'] = [i.name for i in item.itemGraph('particle').reverse()]
            held['forward'] = [i.name for i in item.itemGraph('particle').forward()]
            for source in item.itemGraph('particle').reverse():
                chan = lx.object.ChannelRead(raw.Channels(None, 0.0))
                started = time.perf_counter()
                surface = lx.object.TableauSurface(lx.service.Particle().ItemToParticle(lx.object.Item(source), chan))
                features = []
                for ftype in (lx.symbol.iTBLX_BASEFEATURE, getattr(lx.symbol, 'iTBLX_PARTICLES', 0), lx.symbol.iTBLX_DPDU if hasattr(lx.symbol, 'iTBLX_DPDU') else 0):
                    try:
                        for i in range(surface.FeatureCount(ftype)):
                            features.append([ftype, surface.FeatureByIndex(ftype, i)])
                    except Exception as exc:
                        features.append([ftype, 'error %s' % exc])
                info = {'features': features}
                try:
                    info['bound'] = list(surface.Bound())
                except Exception as exc:
                    info['bound'] = str(exc)
                try:
                    info['segments'] = surface.SegmentBox
                except Exception:
                    pass
                vertex = lx.service.Tableau().AllocVertex()
                size = 0
                layout = []
                for ftype, name in features:
                    if isinstance(name, str) and not name.startswith('error'):
                        try:
                            index = vertex.AddFeature(ftype, name)
                            layout.append([name, ftype, index])
                        except Exception as exc:
                            layout.append([name, 'add error %s' % exc])
                try:
                    size = vertex.Size()
                except Exception as exc:
                    info['size error'] = str(exc)
                info['layout'] = layout
                info['vertex size'] = size
                held.setdefault('read', {})[source.name] = info
                obj = lx.service.Particle().ItemToParticle(lx.object.Item(source), chan)
                info['interfaces'] = [n for n in dir(lx.object) if not n.startswith('_') and _test(n, obj)]
                surface.SetVertex(vertex)
                soup = Soup(max(size, 3))
                try:
                    surface.Sample(((-1e9, -1e9, -1e9), (1e9, 1e9, 1e9)), -1.0, soup)
                except Exception as exc:
                    info['sample error'] = repr(exc)
                    try:
                        surface.Sample((-1e9, -1e9, -1e9, 1e9, 1e9, 1e9), -1.0, soup)
                        info['sample at 0'] = 'ok'
                    except Exception as exc2:
                        info['sample at 0'] = repr(exc2)
                info['count'] = len(soup.points)
                info['segments'] = soup.segments[:5]
                info['polys'] = soup.polys
                info['first'] = soup.points[:5]
                info['seconds'] = time.perf_counter() - started
                held.setdefault('read', {})[source.name] = info
                try:
                    held['source matrix'] = list(modo.Matrix4(source.channel('worldMatrix').get()))
                except Exception:
                    pass
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
