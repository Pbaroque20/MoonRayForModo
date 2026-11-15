# python
"""Command line: the Ocean Plane in Modo. A new scene, an Ocean Plane added as the MoonRay menu adds it (moonray.entity.add
OceanPlaneGeometry), the render camera 4 m above the water looking out to sea a little down, a low sun. The scene is read
as the preview reads it (host.snapshot) and its plane's mesh and sea reported, then saved
(test-results/ocean-plane/ocean_plane.lxo) and exported for MoonRay as the kit's scripts/export_moonray.py does
(ocean_plane.rdla), for rendering outside Modo. Writes report.json there (PROBE_OUT for another folder)."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean-plane'))
out.mkdir(parents=True, exist_ok=True)
report = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def step(name, work):
    try:
        value = work()
        report['steps'].append([name, 'ok'])
        return value
    except Exception:
        report['steps'].append([name, traceback.format_exc()[-1200:]])
        save()
        return None


try:
    import modo
    lx.eval('scene.new')
    scene = modo.Scene()
    step('add the Ocean Plane', lambda: lx.eval('moonray.entity.add OceanPlaneGeometry'))
    # PROBE_CASCADES=0: the sea on one tile, as before cascades; PROBE_HEIGHT and PROBE_TILT: the camera higher and
    # looking further down, where a repeating tile shows.
    if os.environ.get('PROBE_CASCADES') == '0':
        def one_tile():
            held = [i for i in scene.items() if i.type == 'moonray.OceanPlaneGeometry'][0]
            from moonray_modo import entities
            held.channel(entities.CHANNEL_PREFIX + 'cascades').set(0)
        step('cascades off', one_tile)
    report['items'] = [[i.name, i.type] for i in scene.items() if i.type.startswith('moonray.')]

    def camera():
        cam = scene.renderCamera
        lx.eval('select.item {%s} set' % cam.id)
        lx.eval('transform.channel pos.X 0.0')
        lx.eval('transform.channel pos.Y %s' % os.environ.get('PROBE_HEIGHT', '4.0'))
        lx.eval('transform.channel pos.Z 0.0')
        lx.eval('transform.channel rot.X %s' % os.environ.get('PROBE_TILT', '-4.0'))
        lx.eval('transform.channel rot.Y 0.0')
        cam.channel('focalLen').set(0.035)
        render = scene.renderItem
        render.channel('resX').set(640)
        render.channel('resY').set(360)
    step('camera', camera)

    def sun():
        lights = [i for i in scene.items() if i.type == 'sunLight']
        light = lights[0] if lights else scene.addItem('sunLight')
        lx.eval('select.item {%s} set' % light.id)
        lx.eval('transform.channel rot.X -12.0')
        lx.eval('transform.channel rot.Y 180.0')
    step('sun', sun)

    def read():
        from moonray_modo import host
        snap = host.snapshot()
        planes = [m for m in snap.get('meshes') or [] if m.get('_ocean_plane')]
        report['planes'] = [{'name': m['name'], 'faces': len(m['faces']), 'points': len(m['vertices']), 'material': m['material'],
                             'sea': ((snap['materials'].get(m['material']) or {}).get('node_graph') or {}).get('nodes', {}).get('sea')}
                            for m in planes]
        report['entities_left'] = [e.get('class') for e in snap.get('entities') or []]
        report['warnings'] = [w for w in snap.get('warnings') or [] if 'renderOutput' not in w][:10]
    step('read', read)
    save()
    lxo = out / 'ocean_plane.lxo'
    step('save', lambda: lx.eval('!scene.saveAs {%s} $LXOB false' % lxo))
    step('export', lambda: lx.eval('@{kit_MoonRayForModo:scripts/export_moonray.py} "%s" "%s"' % (lxo, out / 'ocean_plane.rdla')))
except Exception:
    report['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
