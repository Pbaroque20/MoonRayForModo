# python
"""Command line: a sphere displaced by a Displacement image layer, written for MoonRay three ways. own.rdla: as modeled,
MoonRay displacing it itself; before.rdla: Surfaces: Modo evaluated geometry as the kit wrote it before (Modo's
displaced mesh, displaced again by the material's layer: layers.material_stack without baked_effects); now.rdla: as
it is written now (displaced once, by Modo). PROBE_BUMPS the height image (bumps.png in the output folder), PROBE_SIZE
pixels wide (560, at 4:3), PROBE_SAMPLES (16), PROBE_DISP_RATE Modo's Displacement Rate (3 pixels). Writes
test-results/displace-demo/report.json, with each scene's displacements and triangles (PROBE_OUT for another folder)."""
import json
import math
import os
import pathlib
import traceback
from unittest import mock

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\displace-demo'))
out.mkdir(parents=True, exist_ok=True)
bumps = pathlib.Path(os.environ.get('PROBE_BUMPS', str(out / 'bumps.png')))
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


try:
    scene = modo.Scene()
    lx.eval('layer.new')
    lx.eval('tool.set prim.sphere on')
    # At the middle, half a metre across: the tool keeps the centre and size it was last used with.
    for attribute, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', .5), ('sizeY', .5), ('sizeZ', .5), ('sides', 48), ('segments', 24)):
        lx.eval('tool.attr prim.sphere %s %s' % (attribute, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.sphere off')
    mesh = scene.selected[-1]
    uv_maps = [m.name for m in mesh.geometry.vmaps if m.map_type == lx.symbol.i_VMAP_TEXTUREUV]
    report['mesh'] = {'points': mesh.geometry.numVertices, 'uv_maps': uv_maps}
    save()

    lx.eval('clip.addStill {%s}' % bumps)
    clip = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == bumps.name)
    base = next(i for i in scene.renderItem.children() if i.type == 'advancedMaterial')
    base.channel('displace').set(0.06)
    shader = next(i for i in scene.renderItem.children() if i.type == 'defaultShader')
    layer = scene.addItem('imageMap', name='bumps (Image)')
    layer.setParent(scene.renderItem, max(0, shader.parentIndex - 1))
    layer.channel('effect').set('displace')
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, clip._item)
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('uv')
    locator.channel('uvMap').set(uv_maps[0] if uv_maps else 'Texture')
    scene.renderItem.channel('dispRate').set(float(os.environ.get('PROBE_DISP_RATE', 3)))
    report['tree'] = [(i.type, i.name) for i in scene.renderItem.children()]

    camera = scene.renderCamera
    eye = (0.0, 0.55, 2.3)
    camera.position.set(eye)
    camera.rotation.set((-math.atan2(eye[1], math.hypot(eye[0], eye[2])), 0.0, 0.0))
    save()

    from moonray_modo import host, layers, rdla
    width = int(os.environ.get('PROBE_SIZE', 560))
    samples = int(os.environ.get('PROBE_SAMPLES', 16))
    stack, collect = layers.material_stack, layers.collect

    def unbaked(scene_, candidates, warnings, tag, membership=None, baked_effects=()):
        return stack(scene_, candidates, warnings, tag, membership)

    def unnoted(scene_, materials, warnings, baked_effects=(), layer_filter=None, material_key=None):
        # As before: nothing noted of what Modo baked, so the render cache's normals are kept.
        collect(scene_, materials, warnings, baked_effects, layer_filter, material_key)
        for material in materials.values():
            material.pop('baked_effects', None)

    def straightness(snapshot):
        """How far the normals lean from the sphere's middle on average (degrees): 0 where they are the round sphere's."""
        total, count = 0.0, 0
        for mesh in snapshot.get('meshes') or []:
            points, faces, normals = mesh.get('vertices') or [], mesh.get('faces') or [], mesh.get('normals') or []
            corner = 0
            for face in list(faces)[:20000]:
                for index in face:
                    if corner < len(normals):
                        p, n = points[index], normals[corner]
                        radial = [p[0], p[1], p[2]]
                        length = math.sqrt(sum(v * v for v in radial)) * math.sqrt(sum(v * v for v in n)) or 1.0
                        total += math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(radial, n)) / length))))
                        count += 1
                    corner += 1
        return round(total / count, 2) if count else None

    for name in ('own', 'before', 'now'):
        if name == 'own':
            snapshot = host.snapshot(evaluated_geometry=False)
        elif name == 'before':
            with host.by_engine('moonray'), mock.patch.object(layers, 'material_stack', unbaked), mock.patch.object(layers, 'collect', unnoted):
                snapshot = host.snapshot(evaluated_geometry=True)
        else:
            with host.by_engine('moonray'):
                snapshot = host.snapshot(evaluated_geometry=True)
        text = rdla.scene_text(snapshot, width, width * 3 // 4, samples, 0.15, str(out / (name + '.exr')))
        (out / (name + '.rdla')).write_text(text, encoding='utf-8')
        report[name] = {'displacements': [line for line in text.splitlines() if line.startswith('displacements[')],
                        'faces': sum(len(m.get('faces') or []) for m in snapshot.get('meshes') or []),
                        'normals_lean': straightness(snapshot),
                        'baked': {tag: m.get('baked_effects') for tag, m in (snapshot.get('materials') or {}).items()},
                        'warnings': snapshot.get('warnings'), 'bytes': len(text)}
        save()
except Exception:
    report['error'] = traceback.format_exc()
save()
