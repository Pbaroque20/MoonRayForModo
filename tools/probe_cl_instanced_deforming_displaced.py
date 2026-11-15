# python
"""Command line: MoonLightIPR with instances of a mesh that deforms and is displaced. A cube split into a grid of faces
gets a morph map (its top raised) and a Morph Influence whose strength is keyed from 0 at frame 0 to 1 at frame 2, a
material with a Shader Tree displacement (a Noise layer as Displacement, Displacement Distance set), and two instances
(item.duplicate instance); the render camera's Motion Blur on, the time at frame 1. The scene is read as the preview
reads it with motion blur (animation.capture_current, Modo's evaluated geometry), then packed for MoonLightIPR: for each
mesh, whether it has instances, whether its points differ at the shutter's ends, and the packed mesh's flags (1024 a
displaced one). Each step's outcome is kept, so a step Modo refuses says so. Writes PROBE_OUT/report.json
(test-results/instanced-deforming-displaced)."""
import json
import os
import pathlib
import struct
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\instanced-deforming-displaced'))
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def step(name, work):
    try:
        value = work()
        result['steps'].append([name, 'ok'])
        return value
    except Exception as exc:
        result['steps'].append([name, '%s: %s' % (type(exc).__name__, str(exc)[:300])])
        save()
        return None


try:
    import modo
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Blob')
    with mesh.geometry as geometry:
        # A 6 x 6 grid of quads in XZ, raised into a slab: enough points to bend and displace.
        n = 6
        points = {}
        for i in range(n + 1):
            for j in range(n + 1):
                points[i, j] = geometry.vertices.new((i / n - .5, 0.0, j / n - .5))
        for i in range(n):
            for j in range(n):
                geometry.polygons.new([points[i, j], points[i, j + 1], points[i + 1, j + 1], points[i + 1, j]])

    def morph():
        with mesh.geometry as geometry:
            vmap = geometry.vmaps.addMorphMap('Raise')
            for vertex in geometry.vertices:
                x, y, z = vertex.position
                vmap[vertex.index] = (0.0, 0.5 * (1.0 - (x * x + z * z) * 2.0), 0.0)
    step('morph map', morph)

    def influence():
        deformer = scene.addItem('morphDeform', name='Raise influence')
        lx.eval('select.item {%s} set' % deformer.id)
        for name in ('mapName', 'morphMap'):
            try:
                deformer.channel(name).set('Raise')
                break
            except Exception:
                continue
        deformer.itemGraph('deformers') >> mesh.itemGraph('deformers')
        strength = deformer.channel('strength')
        strength.set(0.0, time=0.0, key=True)
        strength.set(1.0, time=2.0 / float(scene.fps), key=True)
        return deformer
    deformer = step('morph influence keyed', influence)

    def material():
        lx.eval('select.item {%s} set' % mesh.id)
        lx.eval('poly.setMaterial Blobby')
        mask = [i for i in scene.items('mask') if 'Blobby' in i.name][0]
        found = [i for i in scene.items('advancedMaterial') if i.parent and i.parent.id == mask.id][0]
        found.channel('displace').set(0.1)
        lx.eval('select.item {%s} set' % mask.id)
        lx.eval('shader.create noise')
        noise = [i for i in scene.items('noise')][-1]
        noise.channel('effect').set('displace')
        return noise.id
    result['displacement_layer'] = step('displacement', material)

    def instances():
        made = []
        for k in (1, 2):
            lx.eval('select.item {%s} set' % mesh.id)
            lx.eval('item.duplicate instance:true type:locator')
            held = scene.selected[0]
            lx.eval("transform.channel pos.X %f" % (1.5 * k))
            made.append(held.id)
        return made
    result['instances'] = step('instances', instances)

    def camera():
        cam = scene.renderCamera
        cam.channel('motionBlur').set(1)
        cam.position.set((0.75, 1.5, 4.0))
        lx.service.Selection().SetTime(1.0 / float(scene.fps))
    step('camera', camera)
    from moonray_modo import incremental
    result['deformers'] = step('deformers found', lambda: sorted(str(i) for i in (incremental.deformers(scene) or [])))
    save()

    def baked():
        # Whether Modo's evaluated geometry carries the displacement already: its render cache read displaced and not.
        from moonray_modo import evaluated
        now = lx.service.Selection().GetTime()
        rows = {}
        for displaced in (True, False):
            data = evaluated.capture(now, displaced=displaced)
            surfaces = data.get('surfaces') or []
            ys = [p[1] for s in surfaces for p in (s.get('vertices') or [])]
            rows['displaced' if displaced else 'plain'] = {'surfaces': len(surfaces), 'points': len(ys),
                                                           'top': max(ys) if ys else None, 'bottom': min(ys) if ys else None}
        return rows
    result['render_cache'] = step('render cache displaced or not', baked)
    save()

    from moonray_modo import animation, host, moonlightipr_scene
    def ends():
        # Each mesh at the shutter's ends and the frame, read as MoonLightIPR reads: its faces and points, alike or not.
        fps = float(scene.fps); now = lx.service.Selection().GetTime(); rows = {}
        try:
            for label, moment in (('open', now - .25 / fps), ('frame', now), ('close', now + .25 / fps)):
                lx.service.Selection().SetTime(moment)
                with host.by_engine('moonlightipr'):
                    snap = host.snapshot(evaluated_geometry=True)
                for m in snap.get('meshes') or []:
                    rows.setdefault(m.get('name'), {})[label] = {'faces': len(m.get('faces') or []), 'points': len(m.get('vertices') or []),
                                                               'faces_hash': hash(repr(m.get('faces'))) % 100000,
                                                               'top': round(max(v[1] for v in m['vertices']), 4) if m.get('vertices') else None}
        finally:
            lx.service.Selection().SetTime(now)
        return rows
    result['ends'] = step('shutter ends read for MoonLightIPR', ends)

    def compared():
        # What capture_frame hands apply_motion for MoonLightIPR: each mesh at the frame and the shutter's ends compared.
        from moonray_modo import motion
        real = motion.apply_motion; seen = {}
        def watch(scene_, start, end, endpoints, preview=False):
            for m in scene_.get('meshes') or []:
                key = m.get('identity'); row = {}
                for label, other in (('open', start), ('close', end)):
                    o = next((x for x in other.get('meshes') or [] if x.get('identity') == key), None)
                    row[label] = None if o is None else {'faces_equal': not (o['faces'] != m['faces']), 'points': [len(o['vertices']), len(m['vertices'])],
                                                         'types': [type(o['faces']).__name__, type(m['faces']).__name__],
                                                         'first': [list(o['faces'][k]) for k in range(8)], 'frame_first': [list(m['faces'][k]) for k in range(8)],
                                                         'differing': [[k, list(o['faces'][k]), list(m['faces'][k])] for k in range(len(m['faces'])) if list(o['faces'][k]) != list(m['faces'][k])][:6],
                                                         'same_surface': motion.same_surface(o, m)}
                seen[str(key)] = row
            return real(scene_, start, end, endpoints, preview=preview)
        animation.apply_motion = watch
        try:
            with host.by_engine('moonlightipr'):
                animation.capture_current(True)
        finally:
            animation.apply_motion = real
        return seen
    result['compared'] = step('frame and ends compared', compared)
    save()
    save()
    # Read as MoonRay and XPU2 take it (Modo's displaced geometry), and as MoonLightIPR does (undisplaced, host.by_engine).
    for engine in ('moonray', 'moonlightipr'):
        held = None
        with host.by_engine(engine):
            held = step(engine + ': read with motion', lambda: animation.capture_current(True))
        if not held:
            continue
        rows = []
        for m in held.get('meshes') or []:
            close = m.get('vertices_close')
            ys = [v[1] for v in m.get('vertices') or []]
            rows.append({'name': m.get('name'), 'instances': len(m.get('instances') or []), 'faces': len(m.get('faces') or []),
                         'material': m.get('material'), 'deforms': close is not None and close != m.get('vertices'),
                         'top': round(max(ys), 4) if ys else None, 'bottom': round(min(ys), 4) if ys else None})
        report = {'meshes': rows, 'read_warnings': [w for w in held.get('warnings', []) if 'renderOutput' not in w][:10]}

        def pack():
            payload, keys, warnings = moonlightipr_scene.pack(held, 320, 180, 0.15, (), 16, False, None)
            flags = []
            for key in keys:
                at = bytes(payload).find(bytes(key))
                if at >= 0:
                    flags.append(struct.unpack_from('<I', payload, at + len(key))[0])
            report.update(pack_warnings=warnings[:10], pack_bytes=len(payload), mesh_flags=flags,
                          displaced_meshes=sum(1 for f in flags if f & 1024), moving_meshes=sum(1 for f in flags if f & 32))
        step(engine + ': pack', pack)
        result[engine] = report
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
