# python
"""Command-line test: a scene packed for MoonLightIPR as the preview packs it (host.snapshot, scene_setup.configure,
moonlightipr_scene.pack with the kit's runtime), written to a file a MoonLightIPR session can be given on its own.
PROBE_SCENE the .lxo, PROBE_OUT the folder (test-results/moonlightipr-pack), PROBE_EVALUATED=1 for realtime from
Modo's evaluated geometry. Writes scene.mls and report.json."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-pack'))
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host, scene_setup, moonlightipr_scene, native
    scene = host.snapshot()
    scene_setup.configure(scene, scene_setup.values())
    result['meshes'] = len(scene.get('meshes', []))
    result['extra'] = len(scene.get('extra_geometry') or [])
    result['lights'] = len(scene.get('lights', []))
    result['entities'] = sorted({e.get('class') for e in scene.get('entities') or []})
    result['extra_kinds'] = [{'kind': e.get('kind'), 'name': e.get('name'), 'points': len(e.get('vertices') or []),
                              'strands': len(e.get('counts') or []), 'fur_file': bool(e.get('fur_file')),
                              'keys': sorted(k for k in e if not isinstance(e[k], list))[:40]}
                             for e in scene.get('extra_geometry') or []]
    result['settings'] = {k: scene.get(k) for k in ('moonlightipr', 'denoising', 'samples', 'execution_mode') if k in scene}
    runtime = native.default_runtime() if hasattr(native, 'default_runtime') else None
    # As a render (still) and as realtime (each mesh cut by its size on screen, moonlightipr_detail), with denoising.
    # PROBE_EVALUATED=1: realtime from Modo's evaluated geometry, as a preview set to it reads the scene.
    live = scene
    if os.environ.get('PROBE_EVALUATED') == '1':
        live = host.snapshot(evaluated_geometry=True)
        scene_setup.configure(live, scene_setup.values())
    for name, variant in (('scene', dict(scene)), ('realtime', dict(live, _geometry_detail='some', _realtime=True))):
        try:
            payload, keys, warnings = moonlightipr_scene.pack(variant, 960, 540, 0.15, set(), 16, name == 'realtime', runtime)
            (out / (name + '.mls')).write_bytes(payload)
            result[name] = {'bytes': len(payload), 'warnings': warnings}
        except Exception:
            result[name] = {'error': traceback.format_exc()[-1500:]}
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
