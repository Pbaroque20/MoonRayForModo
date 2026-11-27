# python
"""Command line: image sequences, clip choices and light images through Move Shader Tree Textures to MoonShine Graphs
(shader_tree_clips, shader_tree_lights). Run with tools/launch_cl_steps.py, in this order:
  probe_cl_clips_transfer.py  moonray.material.moveShaderTreeTextures  probe_cl_clips_transfer.py
Phase 1 makes the scene (MOONRAY_PROBE_OUT, default test-results/clips-transfer): a row of cubes, one material each:
  Seq      a colour image sequence of five images (seq.0001.png ...), Hold, starting at frame 0;
  Loop     the same sequence, Repeat, starting at frame 2, at 60% Multiply over a grey image;
  Alpha    an image of pink dots on a half-transparent blue, its clip's Alpha off (alphaMode 0);
  Nearest  a colour image laid on with Nearest pixel blending;
and above them a spot light with an image layer (Light Color) beside its Light Material, and a Photometric light with
an IES profile. Saves clips.lxo, and the scene as MoonRay is given it at frames 2 and 4 (before-f2.rdla, before-f4.rdla).
Phase 2 (after the command at Modo's prompt) moves the lights' images (shader_tree_lights.run), writes after-f2.rdla and
after-f4.rdla, the graphs, clips and layers, saves after.lxo, then loads the Seq sequence again from its node's record
(shader_tree_scene.restore) and the light's image (shader_tree_lights.restore), and writes what they made. report.json."""
import builtins
import json
import os
import pathlib
import struct
import traceback
import zlib
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-af3d27f0b82fde226\test-results\clips-transfer')
images = out / 'images'
images.mkdir(parents=True, exist_ok=True)
FRAME_COLOURS = {1: (230, 40, 40), 2: (240, 200, 30), 3: (40, 200, 60), 4: (40, 120, 230), 5: (200, 60, 220)}


def png(path, size, pixel, alpha=False):
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            row.extend(bytes(pixel(x, y)[:4 if alpha else 3]))
        rows.append(b'\0' + bytes(row))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    head = struct.pack('>IIBBBBB', size, size, 8, 6 if alpha else 2, 0, 0, 0)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', head) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))
    return path


def make_images():
    for frame, colour in FRAME_COLOURS.items():
        png(images / ('seq.%04d.png' % frame), 64, lambda x, y, c=colour: c if (x // 16 + y // 16) % 2 else (245, 245, 245))
        png(images / ('loop.%04d.png' % frame), 64, lambda x, y, c=colour: c if (y // 8) % 2 else (30, 30, 30))
    png(images / 'grey.png', 64, lambda x, y: (150, 150, 150))
    png(images / 'dots.png', 64, lambda x, y: (255, 40, 200, 255) if ((x % 16 - 8) ** 2 + (y % 16 - 8) ** 2) < 30 else (40, 90, 220, 110), alpha=True)
    png(images / 'pixels.png', 8, lambda x, y: (250, 200, 30) if (x + y) % 2 else (20, 20, 120))
    (images / 'profile.ies').write_text('IESNA:LM-63-2002\nTILT=NONE\n1 1000 1 3 1 1 2 0 0 0\n1 1 100\n0 45 90\n0\n1000 800 0\n')


def cube(name, x, material, size=0.8):
    lx.eval('item.create mesh {%s}' % name)
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    for axis, value in (('cenX', x), ('cenY', size / 2), ('cenZ', 0), ('sizeX', size), ('sizeY', size), ('sizeZ', size)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s}' % material)
    lx.eval('select.type item')
    return mesh


def mask_of(tag):
    return next(m for m in modo.Scene().items('mask', superType=False) if m.channel('ptag').get() == tag)


def link(layer, target):
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, target._item)


def new_clip(path, sequence=False):
    scene = modo.Scene()
    kind = 'videoSequence' if sequence else 'videoStill'
    before = {i.id for i in scene.items(kind)}
    lx.eval('clip.%s {%s}' % ('addSequence' if sequence else 'addStill', path))
    made = [i for i in scene.items(kind) if i.id not in before]
    if made:
        return made[0]
    # Loaded already: Modo gives the clip that is there.
    return next(i for i in scene.items(kind) if pathlib.Path(str(i.channel('filename').get())) == pathlib.Path(path))


def image_layer(under, effect, clip, name, uv='Texture', index=None):
    scene = modo.Scene()
    made = scene.addItem('imageMap', name=name)
    made.setParent(under, len(list(under.children())) if index is None else index)
    link(made, clip)
    made.channel('effect').set(effect)
    locator = next(i for i in made.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    if uv:
        locator.channel('projType').set('uv')
        locator.channel('uvMap').set(uv)
    return made


def export(name, frame):
    from moonray_modo import host, rdla
    scene = modo.Scene()
    selection = lx.service.Selection()
    selection.SetTime(frame / float(scene.fps))
    with host.by_engine('moonray'):
        snapshot = host.snapshot(evaluated_geometry=True)
    render = scene.renderItem
    text = rdla.scene_text(snapshot, int(render.channel('resX').get()), int(render.channel('resY').get()), 6, frame / float(scene.fps),
                           str(out / (name + '.exr')))
    (out / (name + '.rdla')).write_text(text, encoding='utf-8')
    report[name + ' warnings'] = snapshot.get('warnings')
    # MoonLightIPR: each material compiled as its packer compiles it, and the images it reads (their sources).
    try:
        from moonray_modo import moonlightipr_materials
        read = {}
        original = moonlightipr_materials.Compiler.texture

        def texture(self, layer, source=None, wrap=None):
            read.setdefault(self._probe_name, []).append(pathlib.Path(str(source or layer['path'])).name)
            return original(self, layer, source, wrap)
        moonlightipr_materials.Compiler.texture = texture
        try:
            compiler = moonlightipr_materials.Compiler(runtime=os.environ.get('MOONRAY_PROBE_RUNTIME') or None)
            for key, material in sorted(snapshot['materials'].items()):
                compiler._probe_name = material.get('name', key)
                try:
                    compiler.material(material, key)
                except Exception as exc:
                    read.setdefault(compiler._probe_name, []).append('error: %s' % exc)
        finally:
            moonlightipr_materials.Compiler.texture = original
        report[name + ' moonlightipr images'] = {k: sorted(set(v)) for k, v in read.items()}
    except Exception:
        report[name + ' moonlightipr error'] = traceback.format_exc()


def state():
    from moonray_modo import properties, material_override, shader_tree_transfer as transfer
    scene = modo.Scene()
    held = {'clips': sorted('%s (%s)' % (c.name, c.type) for kind in ('videoStill', 'videoSequence') for c in scene.items(kind)),
            'layers': {layer.name: bool(layer.channel('enable').get()) for layer in scene.items('imageMap')}, 'graphs': {}}
    for item in scene.items('advancedMaterial', superType=True):
        settings = properties.read(item)
        graph = settings.get('node_graph') if material_override.enabled(settings) else None
        if graph:
            held['graphs'][item.name] = {identity: {'type': node['type'], 'parameters': node.get('parameters'), 'record': node.get(transfer.NODE_KEY)}
                                         for identity, node in graph['nodes'].items() if transfer.ours(identity, node)}
    held['light settings'] = (properties.scene_settings().get('production') or {}).get('lights')
    return held


held = getattr(builtins, '_clips_probe', None)
if held is None:
    held = builtins._clips_probe = {'phase': 0, 'report': {}}
held['phase'] += 1
phase = held['phase']
report = held['report']
try:
    if phase == 1:
        make_images()
        lx.eval('scene.new')
        scene = modo.Scene()
        render = scene.renderItem
        for name, value in (('resX', 720), ('resY', 300), ('first', 0), ('last', 10)):
            render.channel(name).set(value)
        floor = scene.addMesh('Floor')
        with floor.geometry as geo:
            points = [geo.vertices.new(p) for p in ((-8, 0, -4), (-8, 0, 4), (8, 0, 4), (8, 0, -4))]
            geo.polygons.new(points)
        names = ['Seq', 'Loop', 'Alpha', 'Nearest']
        for index, name in enumerate(names):
            cube(name, -1.8 + 1.2 * index, name)
        camera = scene.renderCamera
        camera.position.set((0.0, 2.2, 6.5))
        camera.rotation.set((-0.25, 0.0, 0.0))
        sequence = new_clip(images / 'seq.0001.png', sequence=True)
        report['sequence clip'] = {k: sequence.channel(k).get() for k in ('pattern', 'firstFrame', 'lastFrame', 'startFrame', 'endBehavior')}
        image_layer(mask_of('Seq'), 'diffColor', sequence, 'seq (Image)')
        loop = new_clip(images / 'loop.0001.png', sequence=True)
        loop.channel('endBehavior').set('repeat')
        loop.channel('startFrame').set(2)
        image_layer(mask_of('Loop'), 'diffColor', new_clip(images / 'grey.png'), 'grey (Image)')
        over = image_layer(mask_of('Loop'), 'diffColor', loop, 'loop (Image)')
        over.channel('opacity').set(.6)
        over.channel('blend').set('multiply')
        dots = new_clip(images / 'dots.png')
        dots.channel('alphaMode').set(0)
        image_layer(mask_of('Alpha'), 'diffColor', dots, 'dots (Image)')
        nearest = image_layer(mask_of('Nearest'), 'diffColor', new_clip(images / 'pixels.png'), 'pixels (Image)')
        nearest.channel('pixBlend').set('nearest')
        # The lights: a spot with an image beside its Light Material, a Photometric light with an IES profile.
        lx.eval('item.create spotLight')
        spot = next(iter(scene.items('spotLight')))
        spot.position.set((0.0, 4.0, 1.0))
        spot.rotation.set((-1.3, 0.0, 0.0))
        material = spot.material
        siblings = list(spot.children())
        light_image = image_layer(spot, 'lightColor', new_clip(images / 'grey.png'), 'spot picture (Image)', uv=None,
                                  index=siblings.index(next(s for s in siblings if s.id == material.id)) + 1)
        lx.eval('item.create photometryLight')
        photometric = next(iter(scene.items('photometryLight')))
        photometric.channel('filename').set(str(images / 'profile.ies'))
        photometric.position.set((2.0, 3.0, 1.0))
        report['spot tree'] = [(c.type, c.name) for c in spot.children()]
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'clips.lxo'))
        held['initial'] = state()
        report['initial'] = held['initial']
        for frame in (2, 4):
            export('before-f%d' % frame, frame)
    elif phase == 2:
        from moonray_modo import shader_tree_scene, shader_tree_lights
        report['materials report'] = list(shader_tree_scene.LAST_REPORT)
        lights = shader_tree_lights.run()
        report['lights report'] = lights.lines()
        report['after'] = state()
        for frame in (2, 4):
            export('after-f%d' % frame, frame)
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'after.lxo'))
    elif phase == 3:
        # After the command again: nothing to change.
        from moonray_modo import shader_tree_scene, shader_tree_lights
        report['again report'] = list(shader_tree_scene.LAST_REPORT)
        report['lights again'] = shader_tree_lights.run().lines()
        again = state()
        report['again unchanged'] = json.dumps(again['graphs'], sort_keys=True, default=str) == json.dumps(report['after']['graphs'], sort_keys=True, default=str) \
            and again['clips'] == report['after']['clips'] and again['layers'] == report['after']['layers']
        # Loaded again from the records: the Seq sequence as its node has it, the spot's picture as its record has it.
        scene = modo.Scene()
        layer = next(i for i in scene.items('imageMap') if i.name == 'seq (Image)')
        record = next(node['record'] for graph in report['after']['graphs'].values() for identity, node in graph.items()
                      if node['record'] and node['record'].get('role') == 'image' and node['record'].get('layer') == layer.id)
        report['seq record'] = record['source']
        report['seq restored'] = shader_tree_scene.restore(scene, layer, record['source'])
        clip, folder = shader_tree_scene.image_of(layer)
        report['seq clip again'] = None if clip is None else {
            'type': clip.type, **{k: clip.channel(k).get() for k in ('pattern', 'firstFrame', 'lastFrame', 'startFrame', 'endBehavior', 'alphaMode')}}
        report['lights restored'] = shader_tree_lights.restore().lines()
        report['restored'] = state()
except Exception:
    report['error phase %d' % phase] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
