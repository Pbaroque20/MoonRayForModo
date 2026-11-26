# python
"""Command line: a scene with Blobs and Sprites (MOONRAY_PROBE_SCENE) read by the plugin and exported as RDLA, as Export
as MoonRay Scene writes it, for MoonRay, XPU2 and MoonLightIPR to be run on outside Modo. At MOONRAY_PROBE_FRAMES (a
comma list, default the scene's current frame) each frame is exported to <out>/<scene>.<frame>.rdla. Noted per frame in
report.json: the seconds the reading took, the particle meshes and volumes made (points, faces, file) and the notices.
MOONRAY_PROBE_OUT is the folder (default test-results/blob-render in this checkout)."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-ab5779a40d6c39b81\test-results\blob-render')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('scene.open {%s} normal' % source)
    scene = modo.Scene()
    frames = [int(f) for f in os.environ.get('MOONRAY_PROBE_FRAMES', '').split(',') if f.strip()]
    from moonray_modo import host, particles, scene_export
    fps = float(scene.fps)
    for frame in frames or [round(lx.service.Selection().GetTime() * fps)]:
        lx.service.Selection().SetTime(frame / fps)
        held = report.setdefault(str(frame), {})
        started = time.perf_counter()
        snapshot = host.snapshot()
        held['read seconds'] = round(time.perf_counter() - started, 3)
        held['made'] = [{'name': m['name'], 'points': len(m['vertices']), 'faces': len(m['faces']), 'cell': m.get('_cell'),
                         'velocities': 'velocities' in m} for m in snapshot['meshes'] if m.get('_particles')]
        held['volumes'] = [{'name': e['name'], 'file': e['file'], 'velocity grid': e.get('velocity_grid')} for e in snapshot.get('extra_geometry', []) if e.get('_particles')]
        held['points entries'] = [e['name'] for e in snapshot.get('extra_geometry', []) if e.get('kind') == 'points']
        held['warnings'] = snapshot.get('warnings')
        held['particle seconds'] = snapshot.get('_particle_seconds')
        # Read again: what the session keeps answers from.
        started = time.perf_counter()
        host.snapshot()
        held['read again seconds'] = round(time.perf_counter() - started, 3)
        warnings = []
        started = time.perf_counter()
        written = scene_export.export({'path': out / ('%s.%04d.rdla' % (source.stem, frame)), 'format': 'rdla', 'outputs': True, 'collect': False,
                                       'frames': False}, warnings)
        held['export seconds'] = round(time.perf_counter() - started, 3)
        held['written'] = [str(p) for p in written]
        held['export warnings'] = warnings
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
