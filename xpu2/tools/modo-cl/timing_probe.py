# python
"""Headless Modo probe: where the kit's time goes handing a scene to the preview renderer, for each scene in
MOONRAY_PROBE_SCENES (';'): host.snapshot (Modo's scene read, meshes included), rdla.scene_text with the geometry's
long lists collected as binary, and the binary file's write; with a profile of the read and the text by function
(cumulative time, the top 45; MOONRAY_PROBE_PROFILE=1); MOONRAY_PROBE_KIT: another kit's python folder (MOONRAY_PROBE_ADAPTER: its adapter), into MOONRAY_PROBE_OUT/<scene name>/timing.json and profile.txt."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx

out_root = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
# The adapter Modo loaded as a plugin (only that copy has the SDK's services set up), found before another kit is used.
from moonray_modo import evaluated as _installed
PROFILE_ADAPTER = pathlib.Path(_installed.__file__).resolve().parents[2] / 'bin/MoonRayGeometry.lx'
for source in [pathlib.Path(s) for s in os.environ['MOONRAY_PROBE_SCENES'].split(';') if s]:
    out = out_root / source.stem
    out.mkdir(parents=True, exist_ok=True)
    result = {'scene': str(source)}
    profile = cProfile.Profile()
    try:
        started = time.perf_counter()
        lx.eval('scene.open {%s} normal' % source)
        result['open'] = round(time.perf_counter() - started, 2)
        kit = os.environ.get('MOONRAY_PROBE_KIT')
        if kit:
            # Another kit's Python in place of the profile's (its package imported afresh), with the profile's adapter.
            import sys
            for name in [n for n in sys.modules if n == 'moonray_modo' or n.startswith('moonray_modo.')]:
                del sys.modules[name]
            sys.path.insert(0, kit)
            os.environ['MOONRAY_MODO_GEOMETRY'] = os.environ.get('MOONRAY_PROBE_ADAPTER') or str(PROFILE_ADAPTER)
        from moonray_modo import host, rdla, rdlb, evaluated
        result['kit'] = host.__file__
        if kit and not getattr(evaluated, '_bridge', None):
            import ctypes
            evaluated._bridge = ctypes.CDLL(os.environ['MOONRAY_MODO_GEOMETRY'])
            evaluated._bridge.MR_geometry_snapshot_file.argtypes = [ctypes.c_double, ctypes.c_int, ctypes.c_char_p]
            evaluated._bridge.MR_geometry_snapshot_file.restype = ctypes.c_char_p
            try:
                from moonray_modo import rows
                rows.adapter(evaluated._bridge)
            except ImportError:
                pass
            result['adapter'] = os.environ['MOONRAY_MODO_GEOMETRY']
        held = evaluated.capture

        def capture(*args, **kwargs):
            began = time.perf_counter()
            data = held(*args, **kwargs)
            result.setdefault('captures', []).append({'seconds': round(time.perf_counter() - began, 2), 'timing': data.get('timing'),
                                                      'handing': data.get('handing'), 'prototypes': len(data.get('prototypes', {})),
                                                      'surfaces': len(data.get('surfaces', []))})
            return data
        evaluated.capture = capture
        profiling = os.environ.get('MOONRAY_PROBE_PROFILE') == '1'
        if profiling:
            profile.enable()
        started = time.perf_counter()
        snapshot = host.snapshot()
        result['snapshot'] = round(time.perf_counter() - started, 2)
        snapshot['_geometry_revision'] = 'probe-1'
        width, height = snapshot.get('width', 640), snapshot.get('height', 360)
        started = time.perf_counter()
        with rdlb.collecting() as sink:
            split = rdla.scene_text(snapshot, width, height, 2, 0.15, str(out / 'preview.exr'))
        result['scene_text'] = round(time.perf_counter() - started, 2)
        if profiling:
            profile.disable()
        started = time.perf_counter()
        (out / 'timing.rdla').write_text(split, encoding='utf-8')
        sink.write(out / 'timing.rdlb')
        result['write'] = round(time.perf_counter() - started, 2)
        result['rdlb_bytes'] = (out / 'timing.rdlb').stat().st_size
        result['meshes'] = len(snapshot.get('meshes', []))
        stream = io.StringIO() if profiling else None
        if profiling:
            pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(45)
            (out / 'profile.txt').write_text(stream.getvalue(), encoding='utf-8')
    except Exception:
        result['error'] = traceback.format_exc()
    (out / 'timing.json').write_text(json.dumps(result, indent=1, default=str))
    try:
        lx.eval('scene.close')
    except Exception:
        pass
