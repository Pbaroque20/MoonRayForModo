# python
"""Isolated GUI test: a material's subsurface neighbours are written as MoonRay's trace set.

Two balls that meet are made. The first is given a DwaBaseMaterial with subsurface scattering, and both balls are named
as its subsurface neighbours, as the material's Subsurface Neighbours dialog stores them. The scene the plugin would
hand MoonRay is written out, and what it says of the trace set is written down."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/trace-set'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    from moonray_modo import host, materials, properties, rdla, scene_settings, shader_library
    scene = modo.Scene()
    balls = []
    for x in (-.35, .35):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        for key, value in dict(cenX=x, cenY=.5, sizeX=.4, sizeY=.4, sizeZ=.4).items():
            lx.eval('tool.attr prim.sphere %s %s' % (key, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
        balls.append(scene.selected[0])
    scene.select(balls[0])
    materials.assign('DwaBaseMaterial', name='Wax', color=[.9, .7, .6])
    material = next(item for item in scene.items('advancedMaterial') if properties.read(item).get('native_shader') == 'DwaBaseMaterial')
    settings = properties.read(material)
    settings['native_parameters'] = shader_library.validate('DwaBaseMaterial', dict(settings.get('native_parameters') or {}, scattering_radius=.2, scattering_color=[.9, .4, .3]))
    settings['sss_trace_set'] = [ball.id for ball in balls]
    properties.write(material, settings)
    result['stored'] = properties.read(material).get('sss_trace_set')
    try:
        lx.service.Command().Spawn(lx.symbol.iCTAG_NULL, 'moonray.material.neighbours')
        result['command'] = True
    except Exception as exc:
        result['command'] = str(exc)
    camera = scene.renderCamera
    camera.position.set((0.0, .5, 3.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    taken = host.snapshot(refresh_materials=True)
    result['material'] = {tag: value.get('sss_trace_set') for tag, value in taken['materials'].items()}
    values = scene_settings.complete(properties.scene_settings())
    taken.update(render_settings=values['render'], scene_variables=values['scene_variables'], aovs=values['aovs'], custom_aovs=[], production=values['production'],
                 asset_settings=values['asset_settings'])
    text = rdla.scene_text(taken, 320, 180, 3, 0.3, str(out / 'check.exr'))
    (out / 'check.rdla').write_text(text, encoding='utf-8')
    result['written'] = [line.strip()[:300] for line in text.splitlines() if 'TraceSet' in line]
    from moonray_modo import moonlightipr_scene
    result['moonlightipr_says'] = [w for w in moonlightipr_scene.pack(taken, 320, 180)[2] if 'subsurface' in w]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
