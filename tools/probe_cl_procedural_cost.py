# python
"""Command-line test: what a procedural texture with a Solid projection costs MoonLightIPR before it renders. A dense
sphere is read and packed (host.snapshot, moonlightipr_scene.pack) with a plain material, then with Modo's Noise
on its diffuse colour, each step timed and profiled. Writes test-results/cl-export/prep/procedural_cost.json."""
import cProfile
import io
import json
import pathlib
import pstats
import time
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\procedural_cost.json')
result = {'steps': []}


def step(label, call):
    profile = cProfile.Profile()
    began = time.perf_counter()
    value = profile.runcall(call)
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(12)
    result['steps'].append({'step': label, 'seconds': round(time.perf_counter() - began, 3),
                            'top': [l.split('moonray_modo')[-1].strip()[:150] for l in text.getvalue().splitlines() if 'moonray_modo' in l][:10]})
    out.write_text(json.dumps(result, indent=1))
    return value


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    lx.eval('layer.new')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.attr prim.sphere sides 256')
    lx.eval('tool.attr prim.sphere segments 128')
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.sphere off')
    result['polygons'] = len(modo.Mesh(scene.selected[-1]).geometry.polygons)
    from moonray_modo import host, moonlightipr_scene
    from moonray_modo.scene_setup import configure
    from moonray_modo import scene_settings, properties
    values = scene_settings.complete(properties.scene_settings())

    def read_and_pack(label):
        snapshot = step(label + ': read', lambda: host.snapshot(evaluated_geometry=False))
        configure(snapshot, values)
        step(label + ': pack', lambda: moonlightipr_scene.pack(snapshot, 640, 360, 0.15, (), 16, False, None))
    read_and_pack('plain')
    render = scene.renderItem
    noise = scene.addItem('noise')
    noise.setParent(render, len(render.children()))
    noise.channel('effect').set('diffColor')
    locator = next(i for i in noise.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    result['projection'] = locator.channel('projType').get()
    read_and_pack('noise')
    read_and_pack('noise again')
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1))
