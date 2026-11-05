# python
"""Command line: a Modo Mesh Light through the kit. A floor, and above it a panel made the Prototype of a Mesh Light
and hidden (the usual way), the light's radiance 3; the scene read by the kit (host.snapshot) and written for MoonRay
(rdla.scene_text) with an output file; and the MoonLightIPR light records made of it. A second case with Use
Prototype Transform off and the light moved, so that the shape stands at the light. Writes
test-results/mesh-light-render/ (report.json, scene-*.rdla); the renders are made outside by
tools/check_mesh_light_render.py."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-light-render')
out.mkdir(parents=True, exist_ok=True)
result = {}


def quad(scene, name, size, height, up):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        corners = [(-size, height, -size), (size, height, -size), (size, height, size), (-size, height, size)]
        points = [geo.vertices.new(p) for p in corners]
        geo.polygons.new(list(reversed(points)) if up else points)
    return mesh


def case(label, own_transform):
    lx.eval('scene.new')
    scene = modo.Scene()
    quad(scene, 'Floor', 3.0, 0.0, True)
    panel = quad(scene, 'Panel', 0.5, 0.0, False)
    panel.position.set((0.0, 2.0, 0.0))
    panel.channel('visible').set('off')
    lx.eval('item.create meshLight')
    light = next(i for i in scene.items('meshLight', superType=False))
    lx.eval('select.item {%s} set' % light.id)
    lx.eval('light.mesh mesh:{%s}' % panel.id)
    light.channel('radiance').set(3.0)
    light.channel('useSrcXfrm').set(1 if own_transform else 0)
    if not own_transform:
        modo.LocatorSuperType(light._item).position.set((1.5, 1.0, 0.0))
    for other in [i for i in scene.items('light') if i.type != 'meshLight']:
        other.channel('visible').set('off')
        other.channel('render').set('off')
    camera = scene.renderCamera
    camera.position.set((0.0, 3.5, 6.0))
    camera.rotation.set((-0.5, 0.0, 0.0))
    from moonray_modo import host, rdla, moonlightipr_scene
    shot = host.snapshot()
    # Lit by the mesh light alone: Modo's default environment would light the floor all over.
    shot['environments'] = []
    found = {'lights': [{k: (v if k != 'shape' else {'points': len(v['vertices']), 'faces': len(v['faces']), 'matrix': v['matrix'][12:15]})
                         for k, v in l.items()} for l in shot.get('lights') or []],
             'meshes': [m.get('name') for m in shot.get('meshes') or []],
             'warnings': shot.get('warnings')}
    text = rdla.scene_text(shot, width=320, height=180, samples=4, environment=0.0, output_file=str(out / ('render-%s.exr' % label)))
    (out / ('scene-%s.rdla' % label)).write_text(text, encoding='utf-8')
    found['rdla_mesh_light'] = [line for line in text.splitlines() if 'MeshLight' in line or '/geometry' in line][:6]
    warnings = []
    distant, local = moonlightipr_scene.lights(shot, warnings)
    found['moonlightipr'] = {'local_records': len(local), 'warnings': warnings}
    return found


for label, own in (('prototype', True), ('at-light', False)):
    try:
        result[label] = case(label, own)
    except Exception:
        result[label] = 'error: ' + traceback.format_exc()[-2000:]
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
