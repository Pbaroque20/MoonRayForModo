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

    def read():
        from moonray_modo import animation
        return animation.capture_current(True)
    held = step('read with motion', read)
    if held:
        rows = []
        for m in held.get('meshes') or []:
            close = m.get('vertices_close')
            rows.append({'name': m.get('name'), 'identity': m.get('identity'), 'instances': len(m.get('instances') or []),
                         'instances_close': len(m.get('instances_close') or []), 'faces': len(m.get('faces') or []),
                         'subdivision': bool(m.get('subdivision')), 'material': m.get('material'),
                         'deforms': close is not None and close != m.get('vertices')})
        result['meshes'] = rows
        result['read_warnings'] = [w for w in held.get('warnings', []) if 'renderOutput' not in w][:10]
        save()

        def pack():
            from moonray_modo import moonlightipr_scene
            payload, keys, warnings = moonlightipr_scene.pack(held, 320, 180, 0.15, (), 16, False, None)
            result['pack_warnings'] = warnings[:10]
            result['pack_bytes'] = len(payload)
            # Each mesh record starts with its 8-byte key and its flags (moonlightipr_scene: key + <I flags).
            flags = []
            for key in keys:
                at = bytes(payload).find(bytes(key))
                if at >= 0:
                    flags.append(struct.unpack_from('<I', payload, at + len(key))[0])
            result['mesh_flags'] = flags
            result['displaced_meshes'] = sum(1 for f in flags if f & 1024)
        step('pack', pack)
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
