# python
"""Command-line test: how long MoonLightIPR takes to read a scene (MOONRAY_PROBE_SCENE) with motion blur, as its
preview does (animation.capture_frame at the frame and both ends of the shutter), and to pack it for the GPU. Read
once as the scene allows (where nothing in it bends a mesh, only where things stand is read at the shutter's ends:
incremental.rigid) and once reading every mesh three times, as before; both are compared, and their packed scenes.
Writes test-results/cl-export/motion-prep/<scene name>.json."""
import hashlib
import json
import os
import pathlib
import time
import traceback
import lx

result = {}
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\motion-prep')
out.mkdir(parents=True, exist_ok=True)
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])


def packed(scene):
    from moonray_modo import moonlightipr_scene
    began = time.perf_counter()
    value = moonlightipr_scene.pack(scene, 320, 180)
    seconds = round(time.perf_counter() - began, 2)
    digest = hashlib.blake2b()

    def walk(v):
        if isinstance(v, (bytes, bytearray, memoryview)):
            digest.update(bytes(v))
        elif isinstance(v, dict):
            for k in sorted(v, key=str):
                digest.update(repr(k).encode()); walk(v[k])
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, (set, frozenset)):
            for x in sorted(map(repr, v)):
                digest.update(x.encode())
        else:
            digest.update(repr(v).encode())
    walk(value)
    return seconds, digest.hexdigest()[:24]


def plain(scene):
    """A scene as data to compare: without its notices."""
    return json.dumps({k: v for k, v in scene.items() if k not in ('warnings',)}, sort_keys=True, default=repr)


try:
    began = time.perf_counter()
    lx.eval('scene.open {%s} normal' % source)
    result['open_seconds'] = round(time.perf_counter() - began, 2)
    import modo
    from moonray_modo import animation, incremental, motion, properties
    evaluated = properties.scene_settings().get('surface', 2) == 2
    result['evaluated_geometry'] = evaluated
    moment, fps = lx.service.Selection().GetTime(), float(modo.Scene().fps)
    steady_test = incremental.rigid
    found = []

    def watched(*args):
        value = steady_test(*args)
        found.append(value)
        return value

    def capture(steady):
        incremental.rigid = watched if steady else (lambda *args: False)
        try:
            began = time.perf_counter()
            scene = animation.capture_frame(moment, evaluated, True, fps)
            return scene, round(time.perf_counter() - began, 2)
        finally:
            incremental.rigid = steady_test
    # Why a scene is not taken to hold still, where it is not.
    from moonray_modo import host
    document = modo.Scene()
    service = lx.service.Scene()
    kinds = [service.ItemTypeLookup(name) for name in ('light', 'textureLayer')]
    result['unsteady_kinds'] = sorted({item.type for item in document.iterItems() if not (item.type in incremental.STEADY
                                       or item.type.startswith(('material.', 'moonray.')) or any(item.TestType(k) for k in kinds))})
    result['deformers'] = incremental.deformers(document)
    first, result['steady_cold_seconds'] = capture(True)
    result['steady'] = found[-1] if found else None
    from moonray_modo.coordinates import descriptors
    result['projected'] = sorted({d.get('projection', 'uv') for d in descriptors(first.get('materials') or {}).values()} - {'uv'})
    result['stands_with_items'] = incremental.stands_with_items(document, first)
    result['extra_geometry'] = len(first.get('extra_geometry') or [])
    result['steady_cold_pack_seconds'], first_pack = packed(first)
    full, result['three_readings_seconds'] = capture(False)
    result['three_readings_pack_seconds'], full_pack = packed(full)
    second, result['steady_warm_seconds'] = capture(True)
    result['moves'] = [motion.moves(full), motion.moves(second)]
    result['same_scene'] = plain(full) == plain(second)
    result['same_packed'] = full_pack == first_pack
    if not result['same_scene']:
        a, b = json.loads(plain(full)), json.loads(plain(second))
        result['differs'] = [key for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)][:20]
        if 'meshes' in result['differs']:
            result['mesh_keys_differ'] = sorted({k for m, n in zip(a['meshes'], b['meshes']) for k in set(m) | set(n) if m.get(k) != n.get(k)})
    result['warnings'] = [sorted(set(full.get('warnings', [])) - set(second.get('warnings', []))),
                          sorted(set(second.get('warnings', [])) - set(full.get('warnings', [])))]
    result['meshes'] = len(full.get('meshes', []))
except SystemExit:
    pass
except Exception:
    result['error'] = traceback.format_exc()
(out / (source.stem + '.json')).write_text(json.dumps(result, indent=1))
print(json.dumps(result, indent=1))
