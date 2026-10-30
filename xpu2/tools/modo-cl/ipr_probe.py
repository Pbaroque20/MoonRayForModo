# python
"""Headless Modo probe: MoonLightIPR's readings of each scene in MOONRAY_PROBE_SCENES (';') as the preview makes them,
timed: a first reading and its packing (moonlightipr_scene.pack), then an item moved and the scene read and packed
again (whole, and with the geometry kept, as on a mouse release), into MOONRAY_PROBE_OUT/<scene name>/ipr.json.
MOONRAY_PROBE_KIT: another kit's python folder (the profile's adapter used)."""
import json
import os
import pathlib
import time
import traceback
import lx

out_root = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
from moonray_modo import evaluated as _installed
PROFILE_ADAPTER = pathlib.Path(_installed.__file__).resolve().parents[2] / 'bin/MoonRayGeometry.lx'
kit = os.environ.get('MOONRAY_PROBE_KIT')
if kit:
    import sys
    for name in [n for n in sys.modules if n == 'moonray_modo' or n.startswith('moonray_modo.')]:
        del sys.modules[name]
    sys.path.insert(0, kit)
    os.environ['MOONRAY_MODO_GEOMETRY'] = str(PROFILE_ADAPTER)
from moonray_modo import host, evaluated, moonlightipr_scene, scene_settings, properties
if kit:
    import ctypes
    evaluated._bridge = ctypes.CDLL(str(PROFILE_ADAPTER))
    evaluated._bridge.MR_geometry_snapshot_file.argtypes = [ctypes.c_double, ctypes.c_int, ctypes.c_char_p]
    evaluated._bridge.MR_geometry_snapshot_file.restype = ctypes.c_char_p
    try:
        from moonray_modo import rows
        rows.adapter(evaluated._bridge)
    except ImportError:
        pass


def timed(result, key, work):
    began = time.perf_counter()
    value = work()
    result[key] = round(time.perf_counter() - began, 3)
    return value


for source in [pathlib.Path(s) for s in os.environ['MOONRAY_PROBE_SCENES'].split(';') if s]:
    out = out_root / source.stem
    out.mkdir(parents=True, exist_ok=True)
    result = {'scene': str(source), 'kit': host.__file__}
    try:
        lx.eval('scene.open {%s} normal' % source)
        import modo
        scene = modo.Scene()
        evaluated_geometry = scene_settings.complete(properties.scene_settings()).get('surface') == 2
        result['evaluated'] = evaluated_geometry
        runtime = None
        first = timed(result, 'read_1', lambda: host.snapshot(evaluated_geometry=evaluated_geometry))
        timed(result, 'pack_1', lambda: moonlightipr_scene.pack(first, 640, 360))
        meshes = [i for i in scene.items('mesh')]
        moved = meshes[0] if meshes else None
        result['moved'] = moved.name if moved else None
        for step in range(3):
            if moved is not None:
                moved.position.x.set(moved.position.x.get() + 0.01)
            if step == 2 and os.environ.get('MOONRAY_PROBE_PROFILE') == '1':
                import cProfile, io, pstats
                profile = cProfile.Profile();profile.enable()
            again = timed(result, 'read_whole_%d' % step, lambda: host.snapshot(evaluated_geometry=evaluated_geometry))
            if step == 2 and os.environ.get('MOONRAY_PROBE_PROFILE') == '1':
                profile.disable();stream = io.StringIO()
                pstats.Stats(profile, stream=stream).sort_stats('tottime').print_stats(30)
                (out / 'profile.txt').write_text(stream.getvalue(), encoding='utf-8')
            timed(result, 'pack_whole_%d' % step, lambda: moonlightipr_scene.pack(again, 640, 360))
            kept = timed(result, 'read_kept_%d' % step, lambda: host.snapshot(evaluated_geometry=evaluated_geometry, reuse_geometry=first))
            timed(result, 'pack_kept_%d' % step, lambda: moonlightipr_scene.pack(kept, 640, 360))
    except Exception:
        result['error'] = traceback.format_exc()[-2000:]
    (out / 'ipr.json').write_text(json.dumps(result, indent=1, default=str))
    try:
        lx.eval('scene.close')
    except Exception:
        pass
