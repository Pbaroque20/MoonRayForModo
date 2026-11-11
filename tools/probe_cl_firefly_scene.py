# python
"""Command-line: a scene with fireflies, read as the kit captures it, for check_moonlightipr_fireflies.py: its render
settings (the clamps, depths and samples), its materials (refraction, roughness, glass) and lights, and the capture
itself as scene.pickle. PROBE_SCENE names the scene. Writes test-results/fireflies/report.json and scene.pickle."""
import json
import os
import pathlib
import pickle
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\fireflies')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host
    from moonray_modo.presence_shadows import render_values
    snapshot = host.snapshot()
    settings = render_values(snapshot)
    report['render'] = {k: settings.get(k) for k in ('sample_clamping_value', 'sample_clamping_depth', 'roughness_clamping_factor',
                                                      'max_depth', 'max_diffuse_depth', 'max_glossy_depth', 'pixel_samples',
                                                      'russian_roulette_threshold', 'max_subsurface_per_path')}
    report['moonlightipr'] = (snapshot.get('scene_settings') or {}).get('moonlightipr')
    report['camera'] = {k: snapshot['camera'].get(k) for k in ('width', 'height', 'focal_mm', 'film_mm')} if snapshot.get('camera') else None
    report['size'] = [snapshot.get('width'), snapshot.get('height')]
    report['materials'] = {}
    for tag, material in (snapshot.get('materials') or {}).items():
        keys = ('shader', 'transmission', 'transmission_color', 'refraction_roughness', 'roughness', 'ior', 'metallic', 'specular',
                'clearcoat', 'thin', 'dispersion_abbe', 'presence', 'emission', 'color', 'native_shader')
        report['materials'][tag or '(base)'] = {k: material.get(k) for k in keys if material.get(k) is not None}
        report['materials'][tag or '(base)']['layers'] = [(l.get('kind'), l.get('effect')) for l in material.get('layers') or []][:8]
    report['lights'] = [{k: light.get(k) for k in ('kind', 'name', 'intensity', 'radius', 'width', 'height', 'angle')} for light in snapshot.get('lights', [])]
    report['environments'] = [{k: e.get(k) for k in ('kind', 'name', 'intensity')} for e in snapshot.get('environments', [])]
    report['meshes'] = len(snapshot.get('meshes', []))
    report['warnings'] = snapshot.get('warnings', [])[:12]
    (out / 'scene.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
