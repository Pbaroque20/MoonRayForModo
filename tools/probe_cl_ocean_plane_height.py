# python
"""Command line: an Ocean Plane moved up and down, and read with motion blur. A new scene, an Ocean Plane added as the
MoonRay menu adds it, the render camera 4 m up looking out to sea. For each height (PROBE_HEIGHTS, 0 and 2.5 by
default), the plane's item moved there (transform.channel pos.Y), then: its MoonRay item's matrix as entities.collect
reads it, the sea's mesh height as host.snapshot gives it (for MoonRay and for MoonLightIPR), the same after a move read
the way a followed edit reads it (the meshes kept, host.snapshot reuse_geometry, then incremental.refresh_transforms),
and the scene read with motion blur as MoonLightIPR reads it (animation.capture_frame under host.by_engine), its sea's
meshes and material, packed as MoonLightIPR packs it (moonlightipr_scene.pack: whether the sea is displaced). Writes
report.json in PROBE_OUT (test-results/ocean-plane-height)."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean-plane-height'))
out.mkdir(parents=True, exist_ok=True)
report = {'steps': [], 'heights': {}}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def step(name, work):
    try:
        value = work()
        report['steps'].append([name, 'ok'])
        return value
    except Exception:
        report['steps'].append([name, traceback.format_exc()[-1500:]])
        save()
        return None


def seas(snap):
    """The sea meshes of a reading: their count, each one's height (its centre's, through its matrix) and material."""
    found = []
    for mesh in snap.get('meshes') or []:
        if not mesh.get('_ocean_plane'):
            continue
        m = mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        v = mesh['vertices'][0]
        found.append({'identity': mesh.get('identity'), 'centre': [round(c, 4) for c in v],
                      'world_height': round(v[0] * m[1] + v[1] * m[5] + v[2] * m[9] + m[13], 4),
                      'matrix_translation': [round(c, 4) for c in m[12:15]], 'material': mesh.get('material'),
                      'close_centre': [round(c, 4) for c in mesh['vertices_close'][0]] if mesh.get('vertices_close') else None,
                      'has_graph': bool(((snap.get('materials') or {}).get(mesh.get('material')) or {}).get('node_graph'))})
    return found


try:
    import modo
    # PROBE_SCENE: a scene of one's own, opened (never saved), its plane left where it is unless PROBE_HEIGHTS names
    # heights to move it to.
    given = os.environ.get('PROBE_SCENE')
    if given:
        lx.eval('!scene.open {%s} normal' % given)
    else:
        lx.eval('scene.new')
    scene = modo.Scene()
    if not given:
        step('add the Ocean Plane', lambda: lx.eval('moonray.entity.add OceanPlaneGeometry'))
    plane = [i for i in scene.items() if i.type == 'moonray.OceanPlaneGeometry'][0]
    report['plane'] = [plane.name, plane.id, plane.type]
    report['camera_blur'] = [scene.renderCamera.channel('motionBlur').get(), scene.renderCamera.channel('blurLen').get(),
                             scene.renderCamera.channel('blurOff').get()]

    def camera_motion():
        # Where the render camera stands at the frame and a quarter frame either side, and whether anything of it is keyed.
        from moonray_modo import host as host_module, incremental as moves
        cam = scene.renderCamera
        now, fps = lx.service.Selection().GetTime(), float(scene.fps)
        report['camera_places'] = [[round(v, 4) for v in host_module.world_matrix(cam, now + k / fps)[12:15]] for k in (-0.25, 0.0, 0.25)]
        held = modo.LocatorSuperType(cam)
        report['camera_animated'] = moves.animated(scene, [cam.id] + [t.id for t in (held.position, held.rotation) if t is not None])
        report['time'] = now
    step('camera motion', camera_motion)

    def camera():
        cam = scene.renderCamera
        lx.eval('select.item {%s} set' % cam.id)
        lx.eval('transform.channel pos.X 0.0')
        lx.eval('transform.channel pos.Y 4.0')
        lx.eval('transform.channel pos.Z 0.0')
        lx.eval('transform.channel rot.X -4.0')
        cam.channel('focalLen').set(0.035)
        scene.renderItem.channel('resX').set(320)
        scene.renderItem.channel('resY').set(180)
    if not given:
        step('camera', camera)
    from moonray_modo import animation, entities, host, incremental, moonlightipr_scene
    heights = os.environ.get('PROBE_HEIGHTS', '' if given else '0 2.5').split() or [None]
    # The reading made before each move, as the preview window keeps it (its _geometry_cache) for the edit that follows.
    previous = {}
    for height in [None if h is None else float(h) for h in heights]:
        row = report['heights'].setdefault(str(height), {})

        def move(height=height):
            if height is not None:
                lx.eval('select.item {%s} set' % plane.id)
                lx.eval('transform.channel pos.Y %s' % height)
            lx.eval('select.item {%s} set' % plane.id)
            row['pos_Y_channel'] = lx.eval('transform.channel pos.Y ?')
            row['world_matrix'] = host.world_matrix(plane)
            row['parent'] = getattr(plane.parent, 'name', None)
        step('move to %s' % height, move)

        def collected(row=row):
            held = [e for e in entities.collect(scene, []) if e.get('class') == 'OceanPlaneGeometry']
            row['entity_matrix'] = held[0].get('matrix') if held else None
        step('collect at %s' % height, collected)

        def followed(row=row):
            # The move as the preview window follows it once it is let go (panel._capture_read): the edit's items are
            # the plane's position, classified (incremental.classify); a move reads the scene with its meshes kept
            # (host.snapshot reuse_geometry), then places each where its item now stands (refresh_transforms).
            cache = previous.get('moonlightipr')
            if cache is None:
                return
            import modo as modo_module
            moved = [modo_module.LocatorSuperType(plane).position.id]
            reuse = incremental.classify(scene, moved, cache)
            row['followed_reuse'] = reuse if not isinstance(reuse, dict) else sorted(reuse)
            with host.by_engine('moonlightipr'):
                again = host.snapshot(reuse_geometry=cache, refresh_materials=reuse == 'materials' or isinstance(reuse, dict),
                                      dirty_meshes=reuse.get('dirty_meshes') if isinstance(reuse, dict) else None)
            if reuse == 'transforms':
                incremental.refresh_transforms(scene, again, moved)
            row['followed'] = seas(again)
            # The same move followed while it is dragged (incremental.move_only), from the scene last sent.
            fast = incremental.move_only(scene, cache, moved)
            row['dragged'] = seas(fast) if fast is not None else 'refused: %s' % incremental.REFUSED[:1]
            # MoonLightIPR's reading for its motion vectors after the move (animation.shutter_moves, its ends asked of
            # where the items stand in a scene found rigid).
            try:
                with host.by_engine('moonlightipr'):
                    row['followed_shutter_moves'] = animation.shutter_moves(dict(again))
            except Exception as exc:
                row['followed_shutter_moves'] = '%s: %s' % (type(exc).__name__, exc)
        step('followed to %s' % height, followed)

        def read(row=row):
            snap = host.snapshot()
            row['moonray'] = seas(snap)
            with host.by_engine('moonlightipr'):
                light = host.snapshot()
            row['moonlightipr'] = seas(light)
            previous['moonlightipr'] = light
            row['rigid'] = incremental.rigid(scene, light)
        step('read at %s' % height, read)

        def blurred(row=row):
            fps = float(scene.fps)
            try:
                with host.by_engine('moonlightipr'):
                    snap = animation.capture_frame(lx.service.Selection().GetTime(), False, True, fps, preview=True)
            except Exception as exc:
                row['motion_error'] = '%s: %s' % (type(exc).__name__, exc)
                return
            row['motion'] = seas(snap)
            row['motion_steps'] = snap.get('motion_steps')
            # Kept for rendering outside Modo (tools/check_moonlightipr_ocean_motion.py), with the still reading beside it.
            import pickle
            (out / ('motion_%s.pickle' % height)).write_bytes(pickle.dumps(snap, protocol=4))
            if previous.get('moonlightipr') is not None:
                (out / ('still_%s.pickle' % height)).write_bytes(pickle.dumps(previous['moonlightipr'], protocol=4))
            row['motion_warnings'] = [w for w in snap.get('warnings') or [] if 'renderOutput' not in w][:8]
            payload, keys, warnings = moonlightipr_scene.pack(snap, 320, 180, 0.15, (), 4, False, None)
            row['motion_pack_warnings'] = warnings[:8]
            import struct
            flags = []
            for key in keys:
                at = bytes(payload).find(bytes(key))
                flags.append(struct.unpack_from('<I', payload, at + len(key))[0])
            row['motion_mesh_flags'] = flags
            row['motion_displaced'] = any(f & moonlightipr_scene.MESH_DISPLACE for f in flags)
        step('motion at %s' % height, blurred)
        save()
except Exception:
    report['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
