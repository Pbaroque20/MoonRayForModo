# python
"""Command line: a scene's turning parts as MoonLightIPR reads them, at the frame and with the shutter's ends, for
renders outside Modo (tools/check_moonlightipr_wheels.py). PROBE_SCENE the .lxo (the Lamborghini unless named). Each
mesh that turns during the shutter (its matrix at the closing turned from the opening's) and each instanced mesh is
kept, thinned to at most PROBE_FACES faces (40000) the same way in both readings, with the scene's camera, lights,
environments and materials. Writes test-results/wheel-motion/wheels.pickle ({'frame', 'moving'}) and report.json: how
long each reading took, whether the scene was taken as rigid (its shutter's ends read as where the items stand), and
each part kept with how far it turns during the shutter."""
import json
import math
import os
import pathlib
import pickle
import time
import traceback
import lx

scene_path = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\Lamborghini_Moonray.lxo')
out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\wheel-motion'))
out.mkdir(parents=True, exist_ok=True)
limit = int(os.environ.get('PROBE_FACES', '40000'))
report = {'scene': scene_path}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def turn(a, b):
    """The angle (degrees) between two matrices' turns, by their normalised basis vectors."""
    def basis(m):
        rows = []
        for r in range(3):
            v = m[r * 4:r * 4 + 3]
            length = math.sqrt(sum(c * c for c in v)) or 1.0
            rows.append([c / length for c in v])
        return rows
    ra, rb = basis(a), basis(b)
    trace = sum(sum(ra[i][k] * rb[i][k] for k in range(3)) for i in range(3))
    return round(math.degrees(math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))), 2)


def thinned(mesh, step):
    if step <= 1:
        return mesh
    faces = mesh['faces'][::step]
    used = sorted({i for face in faces for i in face})
    where = {old: new for new, old in enumerate(used)}
    value = dict(mesh)
    value['faces'] = [[where[i] for i in face] for face in faces]
    for key in ('vertices', 'vertices_close', 'normals'):
        if isinstance(mesh.get(key), list) and len(mesh[key]) == len(mesh['vertices']):
            value[key] = [mesh[key][i] for i in used]
    for key in ('uvs', 'uv_sets', 'face_materials', 'velocities', 'point_attributes', 'creases', 'attributes'):
        value.pop(key, None)
    return value


try:
    lx.eval('!scene.open {%s} normal' % scene_path)
    from moonray_modo import host, animation, incremental
    began = time.monotonic()
    with host.by_engine('moonlightipr'):
        frame = host.snapshot(evaluated_geometry=False)
        report['frame_seconds'] = round(time.monotonic() - began, 2)
        import modo
        report['rigid'] = incremental.rigid(modo.Scene(), frame)
        reads = []
        original = host.snapshot

        def counted(*args, **kwargs):
            clock = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                reads.append({'seconds': round(time.monotonic() - clock, 3), 'kept_meshes': kwargs.get('reuse_geometry') is not None})
        host.snapshot = counted
        began = time.monotonic()
        try:
            moving = animation.capture_current(False)
        finally:
            host.snapshot = original
        report['moving_seconds'] = round(time.monotonic() - began, 2)
        report['moving_reads'] = reads
    frame.pop('_evaluated_data', None)
    moving.pop('_evaluated_data', None)
    by_identity = {mesh['identity']: mesh for mesh in frame['meshes']}
    kept_frame, kept_moving, parts = [], [], []
    for mesh in moving['meshes']:
        still = by_identity.get(mesh['identity'])
        if still is None:
            continue
        angles = []
        if mesh.get('matrix_close') is not None and mesh.get('matrix') is not None:
            angles.append(turn(mesh['matrix'], mesh['matrix_close']))
        for a, b in zip(mesh.get('instances') or [], mesh.get('instances_close') or []):
            angles.append(turn(a, b))
        if 'instances' not in mesh and not any(angle > 1.0 for angle in angles):
            continue
        step = max(1, math.ceil(len(mesh['faces']) / limit))
        kept_frame.append(thinned(still, step))
        kept_moving.append(thinned(mesh, step))
        parts.append({'identity': mesh['identity'], 'faces': len(mesh['faces']), 'step': step, 'turns': angles[:6],
                      'instances': len(mesh.get('instances') or []), 'vertices_close': mesh.get('vertices_close') is not None})
    report['parts'] = parts
    report['motion_steps'] = moving.get('motion_steps')
    keep = ('camera', 'lights', 'environments', 'materials', 'native_materials', 'render_settings', 'motion_steps', 'warnings')
    held = {'frame': dict({k: frame[k] for k in keep if k in frame}, meshes=kept_frame),
            'moving': dict({k: moving[k] for k in keep if k in moving}, meshes=kept_moving)}
    (out / 'wheels.pickle').write_bytes(pickle.dumps(held, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
report['done'] = True
save()
