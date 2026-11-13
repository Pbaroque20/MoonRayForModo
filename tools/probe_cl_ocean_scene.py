# python
"""Command line: a scene for the MoonShine graph's Ocean nodes. An 800 m sea of 200 x 200 quads with a UV map from 0 to 1,
its MoonShine material's graph displaced by an Ocean node (80 m tiles, ten across, 512 points, 12 m/s wind), white foam
mixed into its colour and its roughness by Ocean Foam, a physical sky lit by a low sun, and a camera a few metres above
the water looking towards the sun. Saved as test-results/ocean/ocean_demo.lxo (PROBE_OUT for another file)."""
import json
import os
import pathlib
import traceback
import lx
import lxu
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean')
out.mkdir(parents=True, exist_ok=True)
target = pathlib.Path(os.environ.get('PROBE_OUT', str(out / 'ocean_demo.lxo')))
report = {}
SIZE, SEGMENTS = 800.0, 200   # MoonLightIPR splits it once more for its displacement; MoonRay dices it by the pixels

try:
    lx.eval('scene.new')
    scene = modo.Scene()
    sea = scene.addMesh('Sea')
    with sea.geometry as geo:
        rows = []
        for j in range(SEGMENTS + 1):
            z = SIZE / 2 - SIZE * j / SEGMENTS
            rows.append([geo.vertices.new((-SIZE / 2 + SIZE * i / SEGMENTS, 0.0, z)) for i in range(SEGMENTS + 1)])
        for j in range(SEGMENTS):
            for i in range(SEGMENTS):
                geo.polygons.new([rows[j][i], rows[j + 1][i], rows[j + 1][i + 1], rows[j][i + 1]])
    report['polygons'] = sea.geometry.numPolygons
    # UVs from 0 to 1 across the plane: Modo's UV Create, a planar projection down Y fitted to the mesh.
    lx.eval('select.item {%s} set' % sea.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('vertMap.new Texture txuv')
    lx.eval('tool.set uv.create on')
    lx.eval('tool.reset')
    lx.eval('tool.attr uv.create proj planar')
    lx.eval('tool.attr uv.create axis 1')
    lx.eval('tool.doApply')
    lx.eval('tool.set uv.create off')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')

    from moonray_modo import materials, nodes, properties
    from moonray_modo.material_override import synchronize
    lx.eval('select.item {%s} set' % sea.id)
    # A material as the kit makes one today: Modo's own, its form by the package of its MoonRay shader.
    material = materials.assign('DwaBaseMaterial', name='Sea Water')
    if material is None:
        material = next(i for i in scene.iterItems('advancedMaterial') if i.name == 'MoonShine Material')
    material = modo.Item(material) if not isinstance(material, modo.Item) else material
    material.name = 'Sea Water'
    graph = nodes.new('DwaBaseMaterial', {'albedo': [0.004, 0.018, 0.026], 'roughness': 0.03, 'refractive_index': 1.33,
                                           'metallic': 0.0})
    # The sea: 80 m tiles, ten across the 800 m plane, the wind at 30 degrees so no wave runs along an edge.
    graph['nodes']['sea'] = {'type': 'ocean', 'position': [-300, 300], 'inputs': {},
                             'parameters': {'size': 80.0, 'repeat': [10.0, 10.0], 'resolution': 512, 'wind_speed': 12.0,
                                            'wind_direction': 30.0, 'choppiness': 1.2, 'small_waves': 0.05,
                                            'against_wind': 0.3, 'foam_threshold': 0.8}}
    graph['displacement'] = 'sea'
    # Foam, following the Ocean node: white over the water's colour, and rough where it is.
    graph['nodes']['foam'] = {'type': 'ocean_foam', 'position': [-300, 0], 'inputs': {}, 'parameters': {}}
    graph['nodes']['colour'] = {'type': 'mix', 'position': [0, 0], 'inputs': {'mix': 'foam'},
                                'parameters': {'bg': [0.004, 0.018, 0.026], 'fg': [0.85, 0.88, 0.9], 'mix': 0.0}}
    graph['nodes']['rough'] = {'type': 'mix', 'position': [0, 120], 'inputs': {'mix': 'foam'},
                               'parameters': {'bg': [0.03, 0.03, 0.03], 'fg': [0.5, 0.5, 0.5], 'mix': 0.0}}
    graph['nodes']['surface']['inputs'].update(albedo='colour', roughness='rough')
    settings = properties.read(material)
    settings.update(native_shader='DwaBaseMaterial', node_graph=graph, node_override=True)
    settings = synchronize(settings, graph)
    properties.write(material, settings)
    properties.mark_shader(material, settings)
    report['packages'] = [p for p in ('moonray.shader.DwaBaseMaterial',) if material.PackageTest(p)]
    report['material'] = material.id

    # Daylight: Modo's physical sky, lit by the scene's sun, low and ahead of the camera, a little to the right.
    sun = next(iter(scene.items('sunLight')), None)
    if sun is None:
        lx.eval('item.create sunLight')
        sun = next(iter(scene.items('sunLight')))
    sun.rotation.set((-0.14, 2.95, 0.0))
    environment = next(iter(scene.items('environment')))
    env_material = next(i for i in environment.children(recursive=True) if i.type == 'envMaterial')
    env_material.channel('type').set('physical')
    report['sun'] = sun.name

    camera = scene.renderCamera
    camera.position.set((0.0, 14.0, 300.0))
    camera.rotation.set((-0.13, 0.0, 0.0))
    camera.channel('focalLen').set(0.035)
    render = scene.renderItem
    for name, value in (('resX', 1280), ('resY', 720), ('first', 1), ('last', 120)):
        render.channel(name).set(value)
    lx.eval('!scene.saveAs {%s} $LXOB false' % target)
    report['saved'] = str(target)
except Exception:
    report['error'] = traceback.format_exc()
(out / 'ocean_scene_report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
