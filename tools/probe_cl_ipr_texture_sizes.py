# python
"""Command line: PROBE_SCENE packed for MoonLightIPR as realtime packs it and as a Render does (_full_textures), every
image the session is handed noted with its size: whether a Render's images are at their full size. Writes
PROBE_OUT/report.json (test-results/ipr-texture-sizes)."""
import json
import os
import pathlib
import struct
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ipr-texture-sizes'))
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ.get('PROBE_SCENE')}


def size(path):
    """An image's width and height from its header: Targa or PFM, the session's two kinds."""
    path = pathlib.Path(path)
    data = path.read_bytes()[:64]
    if path.suffix.lower() == '.tga':
        return struct.unpack_from('<HH', data, 12)
    if path.suffix.lower() == '.pfm':
        parts = data.split(b'\n')
        return tuple(int(v) for v in parts[1].split()[:2])
    return None


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host, scene_setup, moonlightipr_scene, moonlightipr_materials, native
    scene = host.snapshot()
    scene_setup.configure(scene, scene_setup.values())
    runtime = native.default_runtime() if hasattr(native, 'default_runtime') else None
    held = moonlightipr_materials.Compiler.record
    for name, full in (('realtime', False), ('render', True)):
        seen = []

        def record(self, target, flags, seen=seen):
            seen.append(str(target))
            return held(self, target, flags)
        moonlightipr_materials.Compiler.record = record
        try:
            moonlightipr_scene.pack(dict(scene, _full_textures=full), 960, 540, 0.15, set(), 16, False, runtime)
        finally:
            moonlightipr_materials.Compiler.record = held
        sizes = [size(p) for p in seen]
        result[name] = {'images': len(seen), 'largest_side': max((max(s) for s in sizes if s), default=0),
                        'sizes': sorted({tuple(s) for s in sizes if s}, key=lambda s: -max(s))[:12]}
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
