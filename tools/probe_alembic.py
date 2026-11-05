# python
"""Command line: Alembic in the kit. A small mesh made and bent over time (a morph deformer keyed 0 -> 1), saved as
Alembic, then loaded back each way Modo's Alembic loader offers: as Modo meshes with an Alembic streaming deformer, as
Alembic Mesh items (streamed), and static. For each, what items Modo makes and what the kit reads of them at two times
(host.snapshot, evaluated or not) and with motion blur (animation.capture_frame). Writes
test-results/alembic/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\alembic')
out.mkdir(parents=True, exist_ok=True)
ABC = out / 'bent.abc'
result = {}


def attempt(name, fn):
    try:
        result[name] = fn()
    except Exception:
        result[name] = 'error: ' + traceback.format_exc()[-1800:]


def make():
    scene = modo.Scene()
    mesh = scene.addMesh('Bent')
    with mesh.geometry as geo:
        points = [geo.vertices.new((x * .5, y * .5, 0.0)) for y in range(3) for x in range(3)]
        for y in range(2):
            for x in range(2):
                a = y * 3 + x
                geo.polygons.new((points[a], points[a + 1], points[a + 4], points[a + 3]))
    with mesh.geometry as geo:
        morph = geo.vmaps.addMorphMap('bend', False)
        for index in range(9):
            morph[index] = (0.0, 0.0, 0.25 * (index % 3))
    deformer = scene.addItem('morphDeform', name='Bend over time')
    deformer.channel('mapName').set('bend')
    deformer.itemGraph('deformers') >> mesh.itemGraph('deformers')
    deformer.channel('strength').set(0.0, time=0.0, key=True)
    deformer.channel('strength').set(1.0, time=1.0, key=True)
    scene.sceneRange = (0.0, 1.0) if hasattr(scene, 'sceneRange') else None
    for key, value in (('animRange', 'SceneRange'),):
        try:lx.eval('user.value sceneio.alembic.save.%s %s' % (key, value))
        except Exception:pass
    before = items_seen(scene)
    from moonray_modo import host
    shot = host.snapshot()
    lx.eval('scene.saveAs {%s} Alembic true' % ABC)
    return {'saved': ABC.is_file(), 'bytes': ABC.stat().st_size if ABC.is_file() else 0, 'items': before,
            'kit_meshes_before': [(m.get('name'), len(m.get('vertices') or [])) for m in shot.get('meshes') or []]}


def items_seen(scene):
    seen = []
    for item in scene.items():
        if item.type in ('mesh', 'AlembicMesh', 'AlembicCurves', 'AlembicCloud', 'AlembicFile', 'ABCStreamingDeformer', 'morphDeform'):
            entry = [item.type, item.name]
            if item.type == 'mesh':
                try:entry.append(len(item.geometry.vertices))
                except Exception as exc:entry.append(str(exc))
            seen.append(entry)
    return seen


def kinds(scene):
    return sorted({item.type for item in scene.items()})


def reading(label):
    from moonray_modo import host, animation
    scene = modo.Scene()
    found = {'items': items_seen(scene), 'types': kinds(scene), 'alembic_items': [i.type for i in host.alembic_items(scene)]}
    selection = lx.service.Selection()
    for time in (0.0, 1.0):
        selection.SetTime(time)
        for evaluated in (False, True):
            try:
                shot = host.snapshot(evaluated_geometry=evaluated)
                meshes = shot.get('meshes') or []
                found['t%s_eval%s' % (time, evaluated)] = [
                    {'name': m.get('name'), 'points': len(m.get('vertices') or []),
                     'z': sorted({round(v[2], 3) for v in (m.get('vertices') or [])})[:6]} for m in meshes]
                found['t%s_eval%s_extra' % (time, evaluated)] = [g.get('kind') for g in shot.get('extra_geometry') or []]
            except Exception:
                found['t%s_eval%s' % (time, evaluated)] = 'error: ' + traceback.format_exc()[-1200:]
    try:
        shot = animation.capture_frame(0.5, motion=True)
        found['motion'] = [{'name': m.get('name'), 'motion': sorted(k for k in m if 'motion' in k or 'velocit' in k or 'close' in k)}
                           for m in shot.get('meshes') or []]
    except Exception:
        found['motion'] = 'error: ' + traceback.format_exc()[-1200:]
    return found


def load(option, static=False):
    lx.eval('scene.new')
    tried = []
    every = ('asStatic:%s makeInstances:false allFrames:true loadFrame:0 polyMeshStreamingOptions:%s subdLevel:2 '
             'loadMorphs:false useXfrmName:false geometryScale:1.0') % ('true' if static else 'false', option)
    for command in ('!loaderOptions.Alembic ' + every,):
        try:lx.eval(command);tried.append([command, 'ok'])
        except Exception as exc:tried.append([command, str(exc)])
    try:lx.eval('!scene.open {%s} import' % ABC);tried.append(['open', 'ok'])
    except Exception as exc:tried.append(['open', str(exc)])
    found = reading(option)
    found['options'] = tried
    return found


attempt('make', make)
if ABC.is_file():
    attempt('deformer', lambda: load('MeshesAndStreamingDeformers'))
    attempt('streamed', lambda: load('StreamingItems'))
    attempt('streamed_all', lambda: load('ForceStreamingItems'))
    attempt('static', lambda: load('MeshesAndStreamingDeformers', static=True))
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
