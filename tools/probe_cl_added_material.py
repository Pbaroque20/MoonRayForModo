# python
"""Command-line test: MoonLightIPR's readings of a scene (MOONRAY_PROBE_SCENE) as an artist adds a sphere and gives it
a MoonRay material: the scene read whole, then again with the sphere, again for a material edit (the meshes kept),
at the shutter's ends for motion blur (animation.capture_current), and packed for MoonLightIPR. Each step's time and
the functions it spent most in. Writes test-results/cl-export/prep/added_material.json."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\added_material.json')
result = {'steps': []}


def save():
    out.write_text(json.dumps(result, indent=1, default=str))


def step(label, call):
    profile = cProfile.Profile()
    began = time.perf_counter()
    try:
        value = profile.runcall(call)
        entry = {'step': label, 'seconds': round(time.perf_counter() - began, 3)}
    except Exception:
        value = None
        entry = {'step': label, 'seconds': round(time.perf_counter() - began, 3), 'error': traceback.format_exc()[-2000:]}
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(14)
    entry['top'] = [line.split('moonray_modo')[-1].strip()[:160] for line in text.getvalue().splitlines() if 'moonray_modo' in line or 'built-in' in line][:14]
    result['steps'].append(entry)
    save()
    return value


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host, moonlightipr_scene
    whole = step('whole', lambda: host.snapshot(evaluated_geometry=False))
    lx.eval('layer.new')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.sphere off')
    sphere = modo.Scene().selected[-1]
    result['sphere'] = (sphere.name, sphere.type)
    added = step('sphere added', lambda: host.snapshot(evaluated_geometry=False))
    from moonray_modo.animation import capture_current
    step('motion readings with sphere', lambda: capture_current(False))
    lx.eval('select.item {%s} set' % sphere.id)
    lx.eval('@{%s}' % r'C:\Users\Raphael Tobar\MoonRayForModo\tools\probe_assign_material_step.py')
    lx.eval('moonray.material.attr2_0 {0.8 0.3 0.73}')
    shaded = step('material edit', lambda: host.snapshot(evaluated_geometry=False))
    blurred = step('motion readings with material', lambda: capture_current(False))
    step('motion readings again', lambda: capture_current(False))
    from moonray_modo.scene_setup import configure
    for label, snapshot in (('pack still', shaded), ('pack blurred', blurred)):
        if snapshot is not None:
            step(label, lambda snapshot=snapshot: moonlightipr_scene.pack(snapshot, 640, 360, 0.15, (), 16, False, None))
except Exception:
    result['error'] = traceback.format_exc()
save()
