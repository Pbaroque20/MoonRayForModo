"""Render the same snapshots in MoonRay and MoonLight and report how far apart they are.

Usage: compare_moonlight.py <moonray-runtime> [scene ...]
Run outside Modo after tools/build_moonlight.py. Each scene isolates one kind of light over
plain materials, so a brightness difference points at that light's translation. Images and
report.json go to build/moonlight/compare.
"""
import json
import math
import os
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
from moonray_modo import moonlight_scene, native, rdla
import check_moonlight_session as fixture

WIDTH, HEIGHT = fixture.WIDTH, fixture.HEIGHT
MOONLIGHT_SAMPLES, MOONRAY_GRID = 2048, 6
BLOCK = 20


def aimed(position, target):
    """A light at position whose local -Z axis, the emitting one, points at target."""
    return fixture.look_at(position, target)


def write_ppm_file(path, width, height, pixel):
    path.write_bytes(('P6\n%d %d\n255\n' % (width, height)).encode()
                     + bytes(round(255 * min(1.0, max(0.0, v))) for y in range(height) for x in range(width) for v in pixel(x / width, 1 - (y + .5) / height)))


def test_images(folder):
    """Small images with an obvious orientation: where u and v grow must show in the render."""
    images = {name: folder / (name + '.ppm') for name in ('colour', 'roughness', 'normal', 'stripes')}
    checker = lambda u, v: (int(u * 8) + int(v * 8)) % 2
    write_ppm_file(images['colour'], 256, 256, lambda u, v: [.9 * u + .05, .15 + .7 * checker(u, v), .9 * v + .05])
    write_ppm_file(images['roughness'], 256, 256, lambda u, v: [.08 + .8 * (int(u * 6) % 2)] * 3)
    def bumps(u, v):
        x, y = math.sin(u * 16 * math.pi) * .45, math.sin(v * 16 * math.pi) * .45
        z = math.sqrt(max(0.0, 1 - x * x - y * y))
        return [x * .5 + .5, y * .5 + .5, z * .5 + .5]
    write_ppm_file(images['normal'], 256, 256, bumps)
    write_ppm_file(images['stripes'], 256, 256, lambda u, v: [.2 + .8 * (int(v * 10) % 2), .5, .3])
    return {name: str(path) for name, path in images.items()}


def textured(folder):
    """The fixture scene with texture coordinates, and the layers each material path understands."""
    images = test_images(folder)
    scene = fixture.snapshot()
    scene.update(environments=[], render_settings={'sampling_mode': 0, 'max_depth': 4})
    ground, ball, cube = (dict(mesh) for mesh in scene['meshes'])
    segments, rings = 96, 48
    ground['uvs'] = [[0, 0], [0, 8], [8, 8], [8, 0]]
    ball['uvs'] = [uv for r in range(rings) for s in range(segments)
                   for uv in ([s / segments, 1 - r / rings], [(s + 1) / segments, 1 - r / rings],
                              [(s + 1) / segments, 1 - (r + 1) / rings], [s / segments, 1 - (r + 1) / rings])]
    cube['uvs'] = [uv for _ in cube['faces'] for uv in ([0, 0], [1, 0], [1, 1], [0, 1])]
    ball['material'] = 'ball'
    cube['face_materials'] = ['cube'] * 6
    scene['meshes'] = [ground, ball, cube]
    image = lambda name, srgb: {'path': images[name], 'srgb': srgb}
    # Plain dictionaries render through UsdPreviewSurface.
    simple = dict(scene, materials={
        '': {'color': [.5, .5, .5], 'roughness': .6, 'textures': {'diffCol': image('colour', True)}},
        'ball': {'color': [.8, .8, .8], 'roughness': .5, 'textures': {'rough': image('roughness', False)}},
        'cube': {'color': [.6, .6, .65], 'roughness': .35, 'textures': {'normal': image('normal', False)}}})

    # Material stacks, which is how the Shader Tree arrives, render through DwaBaseMaterial.
    def row(identity, color, roughness, layers=(), metallic=0.0, opacity=1.0, **extra):
        return {**extra, 'name': identity, 'base_layer_id': identity, 'shader': 'DwaBaseMaterial', 'standard_material': True,
                'color': color, 'raw_color': color, 'diffuse_amount': 1.0, 'roughness': roughness, 'metallic': metallic,
                'specular': [.04] * 3, 'raw_specular': [1, 1, 1], 'specular_amount': .04, 'emission': [0, 0, 0],
                'raw_emission': [1, 1, 1], 'emission_amount': 0.0, 'ior': 1.5, 'layer_opacity': opacity, 'layer_blend': 'normal',
                'material_groups': [], 'layers': list(layers)}
    def layer(identity, effect, name, srgb, **extra):
        return dict({'identity': identity, 'kind': 'imageMap', 'effect': effect, 'path': images[name], 'srgb': srgb,
                     'color_space': 'sRGB' if srgb else 'raw', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [],
                     'absolute_groups': [], 'coordinate_key': 'modo_uv_test', 'image_channel': 'ignore', 'tile_u': 'repeat',
                     'tile_v': 'repeat', 'corrections': {'gamma': 1.0, 'brightness': 1.0, 'contrast': 1.0}}, **extra)
    stacked = dict(scene, meshes=[dict(mesh, uv_sets={'modo_uv_test': mesh['uvs']}) for mesh in scene['meshes']])
    plain = {'': {'material_stack': [row('ground', [.5, .5, .5], .6)]},
             'ball': {'material_stack': [row('ball', [.8, .25, .1], .3)]},
             'cube': {'material_stack': [row('cube', [.1, .3, .7], .35, metallic=1.0)]},
             'gold': {'material_stack': [row('gold', [1, .77, .34], .2, metallic=1.0)]}}
    layered = {'': {'material_stack': [row('ground', [.5, .5, .5], .6, [layer('g1', 'diffCol', 'colour', True)])]},
               # Two rows: a tinted multiply over a colour image, and a roughness image.
               'ball': {'material_stack': [row('ball', [.8, .8, .8], .5, [
                   layer('b1', 'diffCol', 'colour', True),
                   layer('b2', 'diffCol', 'stripes', True, blend='multiply', opacity=.7),
                   layer('b3', 'rough', 'roughness', False)])]},
               # A half-transparent material row over another one.
               'cube': {'material_stack': [row('under', [.8, .1, .1], .6), row('cube', [.1, .3, .8], .2, opacity=.5)]},
               'gold': {'material_stack': [row('gold', [1, .77, .34], .2, metallic=1.0)]}}
    # Lobes beyond diffuse and specular, under a sky so there is something to see through the glass.
    def lobes(ball, cube):
        return dict(stacked, _environment=0.6, materials={
            '': {'material_stack': [row('ground', [.5, .5, .5], .6, [layer('g1', 'diffCol', 'colour', True)])]},
            'ball': {'material_stack': [ball]}, 'cube': {'material_stack': [cube]},
            'gold': {'material_stack': [row('gold', [1, .77, .34], .2, metallic=1.0)]}})
    glass = lobes(row('ball', [.8, .8, .8], .05, transmission=1.0, transmission_color=[.75, .95, .85], refraction_roughness=0.0),
                  row('cube', [.7, .08, .06], .6, clearcoat=1.0, clearcoat_roughness=.05))
    sheer = lobes(row('ball', [.8, .8, .8], .1, transmission=.8, transmission_color=[.9, .8, .6], thin_geometry=True),
                  row('cube', [.2, .5, .8], .5, presence=.5))
    # Masks, a group and a bump map: a striped mask decides where the ball's upper material row
    # shows, the cube's image sits in a half-opaque group, and the ground is embossed.
    group = [{'id': 'group1', 'opacity': .5, 'blend': 'normal', 'invert': False}]
    masks = dict(stacked, materials={
        '': {'material_stack': [row('ground', [.5, .5, .5], .6, [layer('g1', 'diffCol', 'colour', True),
                                                               layer('g2', 'bump', 'roughness', False)], bump_strength=.03)]},
        'ball': {'material_stack': [row('under', [.85, .15, .1], .6),
                                    row('over', [.1, .3, .85], .25, [layer('m1', 'layerMask', 'roughness', False, mask_target='over')])]},
        'cube': {'material_stack': [row('cube', [.8, .8, .8], .5, [layer('c1', 'diffCol', 'colour', True, groups=group, absolute_groups=group)])]},
        'gold': {'material_stack': [row('gold', [1, .77, .34], .2, metallic=1.0)]}})
    # Light that scatters beneath the surface, fully on the ball and half on the cube.
    skin = lobes(row('ball', [.85, .6, .5], .45, subsurface_amount=1.0, subsurface_distance=.35, subsurface_color=[1, .45, .3]),
                 row('cube', [.5, .8, .6], .5, subsurface_amount=.5, subsurface_distance=.2, subsurface_color=[.6, 1, .7]))
    # A specular lobe stretched along texture u on the ball and across it on the cube.
    brushed = lobes(row('ball', [.9, .9, .9], .4, metallic=1.0, anisotropy=.8), row('cube', [.9, .6, .3], .4, metallic=1.0, anisotropy=-.8))
    # Glass that takes its colour from the depth crossed, and glass that splits colours.
    deep = lobes(row('ball', [.8, .8, .8], .02, transmission=1.0, transmission_color=[.25, .7, .45], absorption_distance=.6),
                 row('cube', [.8, .8, .8], .02, transmission=1.0, transmission_color=[.8, .3, .2], absorption_distance=1.5))
    prism = lobes(row('ball', [.8, .8, .8], .02, transmission=1.0, dispersion_abbe=4.0),
                  row('cube', [.8, .8, .8], .02, transmission=1.0, dispersion_abbe=4.0))
    # Patterns the plugin computes rather than reads: a checker, noise, a gradient looked up by
    # a driver image, and the curves a layer can put on its value.
    def made(identity, effect, kind, **extra):
        return dict(layer(identity, effect, 'colour', False), kind=kind, **extra)
    ramp = {'input': 'driverA', 'positions': [i / 256 for i in range(257)],
            'colors': [[i / 256, .2 + .6 * abs(math.sin(i / 256 * 9)), 1 - i / 256] for i in range(257)]}
    patterns = dict(stacked, meshes=[dict(mesh, uv_sets={'modo_uv_test': [[u * 6, v * 6] for u, v in mesh['uvs']]}) if mesh['name'] == 'Ball' else mesh
                                     for mesh in stacked['meshes']], materials={
        '': {'material_stack': [row('ground', [.5, .5, .5], .6, [made('g1', 'diffCol', 'checker', color1=[.1, .1, .1], color2=[.9, .8, .6])])]},
        'ball': {'material_stack': [row('ball', [.8, .8, .8], .4, [
            made('b1', 'diffCol', 'noise', color1=[.9, .2, .1], color2=[.1, .3, .9], octaves=4, lacunarity=2.0, persistence=.5, bias=.35, gain=.7)])]},
        'cube': {'material_stack': [row('cube', [.8, .8, .8], .5, [
            layer('c1', 'driverA', 'roughness', False), made('c2', 'diffCol', 'gradient', gradient=ramp),
            layer('c3', 'rough', 'roughness', False, bias=.3, gain=.65, corrections={'gamma': 1.8, 'brightness': .9, 'contrast': 1.2})])]},
        'gold': {'material_stack': [row('gold', [1, .77, .34], .2, metallic=1.0)]}})
    # One image per unit square of the ground's coordinates.
    for number, tint in ((1001, (.9, .2, .2)), (1002, (.2, .9, .2)), (1011, (.2, .3, .9)), (1012, (.9, .8, .2))):
        write_ppm_file(folder / ('tile.%d.ppm' % number), 64, 64, lambda u, v, tint=tint: [c * (.35 + .65 * ((int(u * 4) + int(v * 4)) % 2)) for c in tint])
    tiled = dict(simple, meshes=[dict(mesh, uvs=[[0, 0], [0, 2], [2, 2], [2, 0]]) if mesh['name'] == 'Ground' else mesh for mesh in simple['meshes']],
                 materials=dict(simple['materials'], **{'': {'color': [.5, .5, .5], 'roughness': .6, 'textures': {
                     'diffCol': {'path': str(folder / 'tile.<UDIM>.ppm'), 'srgb': True}}}}))
    # Native MoonRay materials, as Assign MoonShine Material makes them: their own attributes
    # decide the look, not the Modo material they sit on.
    def native(identity, shader, **parameters):
        return dict(row(identity, [.5, .5, .5], .4), native_shader=shader, native_parameters=parameters)
    natives = lobes(native('ball', 'DwaBaseMaterial', albedo=[.1, .7, .2], roughness=.2),
                    native('cube', 'DwaMetalMaterial', metallic_color=[.95, .6, .4], roughness=.3))
    natives['materials']['gold'] = {'material_stack': [native('gold', 'DwaBaseMaterial', albedo=[.8, .8, .8], roughness=.6,
                                                              show_clearcoat=True, clearcoat_roughness=.05, show_emission=True, emission=[.2, .05, 0.0])]}
    # A native material whose inputs read images wired in its graph, as the graph editor and the
    # material's form make them: no Shader Tree image layer is involved.
    from moonray_modo import nodes as graph_nodes
    def wired(identity, **images_by_input):
        graph = graph_nodes.new('DwaBaseMaterial', {'roughness': .5})
        for index, (key, (name, srgb)) in enumerate(images_by_input.items()):
            graph['nodes']['image%d' % index] = {'type': 'image', 'parameters': {'file': images[name], 'srgb': srgb}, 'inputs': {}}
            graph['nodes']['surface']['inputs'][key] = 'image%d' % index
        return dict(native(identity, 'DwaBaseMaterial', roughness=.5), node_graph=graph, node_override=True)
    mapped = lobes(wired('ball', albedo=('colour', True)), wired('cube', albedo=('colour', True), roughness=('roughness', False)))
    mapped['meshes'] = [dict(mesh) for mesh in mapped['meshes']]
    for mesh in mapped['meshes']:
        # The image nodes read the primary UVs, baked under the name each node asks for.
        keys = {graph_nodes.image_descriptor(node)['coordinate_key'] for material in mapped['materials'].values()
                for row_ in material.get('material_stack', [material]) if row_.get('node_graph')
                for node in row_['node_graph']['nodes'].values() if node['type'] == 'image'}
        if mesh.get('uvs'):
            mesh['uv_sets'] = {key: list(mesh['uvs']) for key in keys}
    # Nodes that are not images, which MoonLight has MoonRay bake: a ramp over the ball, and on
    # the cube a checker put through a colour correction.
    def node_graph(identity, extra, wires):
        graph = graph_nodes.new('DwaBaseMaterial', {'roughness': .5})
        graph['nodes'].update(extra)
        graph['nodes']['surface']['inputs'].update(wires)
        return dict(native(identity, 'DwaBaseMaterial', roughness=.5), node_graph=graph, node_override=True)
    ramp = {'ramp': {'type': 'RampMap', 'inputs': {}, 'parameters': {
        'space': 2, 'ramp_type': 0, 'positions': [0.0, .5, 1.0], 'colors': [[.9, .1, .1], [.1, .8, .2], [.1, .2, .9]], 'interpolations': [1, 1, 1]}}}
    tinted = {'check': {'type': 'checker', 'inputs': {}, 'parameters': {'color1': [.1, .1, .1], 'color2': [.9, .9, .9], 'scale': [4, 4]}},
              'tint': {'type': 'multiply', 'inputs': {'in1': 'check'}, 'parameters': {'in2': [1.0, .6, .2]}}}
    fade = {'fade': {'type': 'GradientMap', 'inputs': {}, 'parameters': {
        'space': 4, 'start': [0.0, -1.0, 0.0], 'end': [0.0, 1.0, 0.0], 'color_A': [.9, .5, .1], 'color_B': [.1, .3, .9], 'falloff_type': 2}}}

    def projected(scene):
        """Give the meshes the coordinates of nodes laid out in space, as the plugin does when it
        reads a scene from Modo: one set per mesh, and a mesh placed several times once per place."""
        from moonray_modo import coordinates
        found = coordinates.descriptors(scene['materials'])
        spatial = {key: layer for key, layer in found.items() if layer.get('projection', 'uv') != 'uv'}
        meshes = []
        for mesh in scene['meshes']:
            places = mesh.get('instances') or [mesh.get('matrix', fixture.placed(0, 0, 0))]
            for index, place in enumerate(places):
                copy_ = {k: v for k, v in mesh.items() if k not in ('instances', 'instance_ids')}
                copy_.update(matrix=place, identity='%s|%d' % (mesh['identity'], index), uv_sets=dict(mesh.get('uv_sets') or {}))
                for key, layer in spatial.items():
                    copy_['uv_sets'][key] = [uv for face in mesh['faces'] for uv in coordinates.face(layer, [mesh['vertices'][v] for v in face], [], place)]
                meshes.append(copy_)
        return dict(scene, meshes=meshes)
    # A ramp laid out in the world on the ball and a gradient in its own space on the cube;
    # then a checker put through a multiply, which reads the UVs.
    baked = projected(lobes(node_graph('ball', ramp, {'albedo': 'ramp'}), node_graph('cube', fade, {'albedo': 'fade'})))
    baked_uv = lobes(node_graph('ball', dict(ramp, ramp=dict(ramp['ramp'], parameters=dict(ramp['ramp']['parameters'], space=6))), {'albedo': 'ramp'}),
                     node_graph('cube', tinted, {'albedo': 'tint'}))
    # The same images as Shader Tree layers, to set the wired ones against.
    layered_maps = lobes(row('ball', [1, 1, 1], .5, [layer('lb', 'diffCol', 'colour', True)]),
                         row('cube', [1, 1, 1], .5, [layer('lc', 'diffCol', 'colour', True), layer('lr', 'rough', 'roughness', False)]))
    # And as Shader Tree layers over the same native material, which leaves only the route the image takes.
    native_layer_maps = lobes(dict(native('ball', 'DwaBaseMaterial', roughness=.5), layers=[layer('nb', 'diffCol', 'colour', True)]),
                              dict(native('cube', 'DwaBaseMaterial', roughness=.5), layers=[layer('nc', 'diffCol', 'colour', True), layer('nr', 'rough', 'roughness', False)]))
    return {'graph_baked': baked, 'graph_baked_uv': baked_uv, 'graph_maps': mapped, 'layer_maps': layered_maps, 'native_layer_maps': native_layer_maps, 'native_materials': natives, 'textures_simple': simple, 'dwa_plain': dict(stacked, materials=plain), 'dwa_layers': dict(stacked, materials=layered),
            'dwa_glass_coat': glass, 'dwa_thin_presence': sheer, 'dwa_masks': masks, 'dwa_subsurface': skin,
            'dwa_anisotropy': brushed, 'dwa_absorption': deep, 'dwa_dispersion': prism, 'dwa_patterns': patterns, 'udim': tiled}


def sky_image(folder):
    """A latitude-longitude sky whose sides are told apart by colour, with one bright patch."""
    width, height = 512, 256
    def pixel(u, v):     # v runs upwards, as MoonRay reads the file
        up = v * 2 - 1
        tint = [(.9, .25, .2), (.2, .8, .3), (.2, .35, .95), (.9, .8, .2)][int(u * 4) % 4]
        base = [.25 + .5 * max(0.0, up)] * 3 if up > 0 else [.12, .1, .08]
        color = [b * (.5 + .5 * t) for b, t in zip(base, tint)]
        if (u - .62) ** 2 + ((v - .78) * .5) ** 2 < .0006:
            color = [60.0, 55.0, 45.0]
        return color
    path = folder / 'sky.pfm'
    rows = [struct.pack('<%df' % (width * 3), *[c for x in range(width) for c in pixel((x + .5) / width, (y + .5) / height)]) for y in range(height)]
    path.write_bytes(('PF\n%d %d\n-1.0\n' % (width, height)).encode() + b''.join(rows))
    return str(path)


def scenes(folder):
    base = fixture.snapshot()
    base.update(lights=[], environments=[], render_settings={'sampling_mode': 0, 'max_depth': 4})
    turn = math.radians(40)
    sky = {'kind': 'image', 'name': 'Sky image', 'intensity': 1.2, 'path': sky_image(folder), 'srgb': False, 'color_space': 'raw',
           'camera': True, 'indirect': True, 'reflection': True, 'refraction': True,
           'matrix': [math.cos(turn), 0, -math.sin(turn), 0, 0, 1, 0, 0, math.sin(turn), 0, math.cos(turn), 0, 0, 0, 0, 1]}
    lamp = dict(identity='lamp', name='Lamp', color=[1, .95, .85])
    # Enough lights that MoonLight samples one per bounce instead of all of them.
    many = [dict(lamp, identity='lamp%d' % i, kind='SphereLight' if i % 2 else 'RectLight', color=[1, .5 + .1 * (i % 4), .3 + .1 * (i % 5)],
                 intensity=6.0 + 9.0 * (i % 3), radius=.25, width=.8, height=.5,
                 matrix=aimed([-4.5 + 1.2 * i, 4.0 + .4 * (i % 3), 2.0 + (i % 2)], [-3 + .8 * i, .5, 0])) for i in range(9)]
    # A layered environment: a gradient with a colour multiplied over it; and a physical sky.
    seen = {'camera': True, 'indirect': True, 'reflection': True, 'refraction': True}
    row = {'effect': 'envColor', 'groups': [], 'opacity': 1.0, 'blend': 'normal', 'invert': False}
    gradient = dict(row, kind='grad4', zenith=[.2, .4, .9], sky=[.6, .75, 1], ground=[.3, .25, .2], nadir=[.1, .1, .1],
                    sky_exponent=4, ground_exponent=4, layer_identity='e1')
    layered = dict(seen, kind='stack', name='Layered', intensity=1.0, identity='env', layers=[
        gradient, dict(row, kind='color', color=[1, .7, .5], blend='multiply', opacity=.6, layer_identity='e2')])
    daylight = dict(seen, kind='stack', name='Daylight', intensity=1.0, identity='env', layers=[
        dict(gradient, kind='physical', sun_direction=[.4, .6, .5], normalize=False, sky_gamma=1.0, haze=1.0, ground_albedo=[.2, .2, .2])])
    # A lit panel, which is an object in the scene.
    panel = {'name': 'Panel', 'identity': 'panel', 'vertices': [[-.8, 0, -.5], [.8, 0, -.5], [.8, 0, .5], [-.8, 0, .5]],
             'faces': [[0, 1, 2, 3]], 'material': '', 'smooth': False, 'matrix': aimed([-1, 4, 2.5], [0, .5, 0])}
    emitting = dict(base, meshes=base['meshes'] + [panel],
                    production={'objects': {'panel': {'mesh_light': True, 'light_intensity': 60.0, 'light_color': [1, .85, .7]}}})
    return {'image_environment': dict(base, environments=[sky]), 'many_lights': dict(base, lights=many), **textured(folder),
        # MoonRay light items with what MoonLight applies to them: a decay and a tint on one
        # light and a colour ramp on another; a picture on a rect light; a box that is a mesh light.
        'entity_filters': dict(base, entities=[
            {'identity': 'f_decay', 'name': 'Decay', 'class': 'DecayLightFilter', 'parameters': {'falloff_far': True, 'far_start': 4.5, 'far_end': 7.5}},
            {'identity': 'f_tint', 'name': 'Tint', 'class': 'IntensityLightFilter', 'parameters': {'color': [1.0, .6, .3], 'intensity': 1.5}},
            {'identity': 'f_ramp', 'name': 'Ramp', 'class': 'ColorRampLightFilter', 'matrix': fixture.placed(0, 0, 0), 'parameters': {
                'begin_distance': 4.0, 'end_distance': 9.0, 'distances': [0.0, .5, 1.0], 'colors': [[1, .1, .1], [.1, 1, .1], [.1, .1, 1]],
                'interpolation_types': [1, 4, 1]}},
            {'identity': 'l_key', 'name': 'Key', 'class': 'SphereLight', 'matrix': fixture.placed(-3, 4, 2),
             'parameters': {'intensity': 60.0, 'radius': .3, 'light_filters': ['Decay', 'Tint']}},
            {'identity': 'l_fill', 'name': 'Fill', 'class': 'RectLight', 'matrix': aimed([3, 5, 3], [1, .5, 0]),
             'parameters': {'intensity': 60.0, 'width': 1.5, 'height': 1.0, 'light_filters': ['Ramp']}}]),
        # MoonRay's own cameras, standing where the scene's camera is, with a light and a sky to see by.
        **{name: dict(base, _environment=0.5, entities=[
            {'identity': 'l_key', 'name': 'Key', 'class': 'SphereLight', 'matrix': fixture.placed(-3, 4, 2), 'parameters': {'intensity': 60.0, 'radius': .3}},
            {'identity': 'c_lens', 'name': 'Lens', 'class': kind, 'matrix': base['camera']['matrix'],
             'parameters': dict(lens, modo_render_camera=True)}])
           for name, kind, lens in (('fisheye_camera', 'FisheyeCamera', {}),
                                    ('fisheye_equidistant', 'FisheyeCamera', {'mapping': 1, 'format': 1, 'fov': 140.0}),
                                    ('spherical_camera', 'SphericalCamera', {}))},
        'entity_textured_light': dict(base, entities=[
            {'identity': 'l_panel', 'name': 'Panel', 'class': 'RectLight', 'matrix': aimed([0, 2.2, 3.5], [0, .8, 0]),
             'parameters': {'intensity': 40.0, 'width': 3.0, 'height': 1.5, 'texture': test_images(folder)['colour']}}]),
        'entity_mesh_light': dict(base, meshes=base['meshes'] + [panel], entities=[
            {'identity': 'l_lamp', 'name': 'Glow', 'class': 'MeshLight', 'parameters': {'intensity': 60.0, 'color': [1.0, .85, .7], 'geometry': 'Panel'}}]),
        # Subdivision surfaces: the cube rounded off, and a second one with two creased edges and an open top.
        'subdivision': dict(base, lights=fixture.snapshot()['lights'], _environment=.3, meshes=[
            base['meshes'][0], base['meshes'][1],
            dict(base['meshes'][2], subdivision=True, subdivision_level=3, smooth=True),
            dict(base['meshes'][2], identity='cube2', name='Cube2', subdivision=True, subdivision_level=3, smooth=True,
                 faces=base['meshes'][2]['faces'][:3] + base['meshes'][2]['faces'][4:], face_materials=['red'] * 5,
                 creases=[[0, 1, 10.0], [1, 3, 2.0]], matrix=fixture.placed(-4.6, .8, 1.5, .8))]),
        'layered_environment': dict(base, environments=[layered]),
        'physical_sky': dict(base, environments=[daylight]),
        'cylinder_light': dict(base, lights=[dict(lamp, kind='CylinderLight', intensity=60.0, radius=.15, height=2.5, matrix=aimed([-1, 4, 2], [0, .5, 0]))]),
        'portal_light': dict(base, _environment=1.0, lights=[dict(lamp, kind='PortalLight', intensity=12.0, width=3.0, height=2.0, matrix=aimed([1, 5, 3], [0, .5, 0]))]),
        'mesh_light': emitting,
        # MoonRay's own items: a tinted environment, a sphere light, and a box and a ball as shapes.
        'entities': dict(base, entities=[
            {'identity': 'e_env', 'name': 'Sky', 'class': 'EnvLight', 'matrix': fixture.placed(0, 0, 0), 'parameters': {'color': [.4, .5, .7], 'intensity': .6}},
            {'identity': 'e_key', 'name': 'Key', 'class': 'SphereLight', 'matrix': fixture.placed(-1, 5, 3), 'parameters': {'intensity': 50.0, 'radius': .4, 'color': [1.0, .9, .8]}},
            {'identity': 'e_box', 'name': 'Block', 'class': 'BoxGeometry', 'matrix': fixture.placed(-4.2, .6, 1.5), 'parameters': {'size': [1.2, 1.2, 1.2], 'modo_material': 'red'}},
            {'identity': 'e_ball', 'name': 'Globe', 'class': 'SphereGeometry', 'matrix': fixture.placed(4.3, .7, 1.8), 'parameters': {'radius': .7, 'modo_material': 'blue'}}]),
        'depth_of_field': dict(base, lights=fixture.snapshot()['lights'], _environment=.3,
                               camera=dict(base['camera'], dof=True, f_stop=.3, focus_distance=6.5)),
        'bokeh_blades': dict(base, lights=fixture.snapshot()['lights'], _environment=.3,
                             camera=dict(base['camera'], dof=True, f_stop=.3, focus_distance=11.0, iris_blades=5, iris_rotation=.3)),
        'sun': dict(base, lights=fixture.snapshot()['lights']),
        # Curves: MoonRay's own curve geometry against MoonLight's tubes. Thick tapered strands on the ground and a few leaning ones.
        'curves': dict(base, lights=fixture.snapshot()['lights'], _environment=.3, meshes=[base['meshes'][0]], extra_geometry=[
            {'kind': 'curves', 'identity': 'strands|curves|gold', 'source_item': 'strands', 'name': 'Strands', 'material': 'gold', 'curve_type': 0,
             'matrix': fixture.placed(0, 0, 0),
             'vertices': [[-3 + .5 * i + .05 * j * j * math.sin(i), .25 * j, .3 * math.cos(i * 1.7) + .04 * j * j * math.cos(i)]
                          for i in range(13) for j in range(9)],
             'counts': [9] * 13, 'radii': [.12 * (1 - j / 8.0) ** .7 for i in range(13) for j in range(9)]},
            {'kind': 'curves', 'identity': 'rods|curves|red', 'source_item': 'rods', 'name': 'Rods', 'material': 'red', 'curve_type': 0,
             'matrix': fixture.placed(0, 0, 1.6), 'radius': .08,
             'vertices': [[-2.5 + i, .08 + .6 * j, .3 * j] for i in range(6) for j in range(3)], 'counts': [3] * 6}]),
        'uniform_sky': dict(base, _environment=1.0),
        'gradient_sky': dict(base, environments=fixture.snapshot()['environments']),
        'sphere_light': dict(base, lights=[dict(lamp, kind='SphereLight', intensity=60.0, radius=.4, matrix=fixture.placed(-1, 5, 3))]),
        'rect_light': dict(base, lights=[dict(lamp, kind='RectLight', intensity=60.0, width=2.0, height=1.0, matrix=aimed([2, 5, 3], [0, .5, 0]))]),
        'disk_light': dict(base, lights=[dict(lamp, kind='DiskLight', intensity=60.0, radius=.7, matrix=aimed([-3, 4, 2], [0, .5, 0]))]),
        'spot_light': dict(base, lights=[dict(lamp, kind='SpotLight', intensity=80.0, radius=.05, cone=50.0, soft_edge=8.0, matrix=aimed([0, 6, 4], [0, .5, 0]))]),
    }


def moonray(scene, runtime, folder, name):
    output = folder / (name + '_moonray.exr')
    text = rdla.scene_text(scene, WIDTH, HEIGHT, MOONRAY_GRID, scene.get('_environment', 0.0), str(output))
    source = folder / (name + '.rdla')
    # MoonRay takes minutes per scene on the CPU; keep its image while the scene text is unchanged.
    fresh = source.is_file() and source.read_text(encoding='utf-8') == text and output.with_suffix('.pfm').is_file()
    source.write_text(text, encoding='utf-8')
    for args in () if fresh else ([str(runtime / 'moonray.exe')] + native.arguments(source, output, 0, 'auto'),
                 [str(runtime / 'oiiotool.exe'), str(output), '--ch', 'R,G,B', '-d', 'float', '-o', str(output.with_suffix('.pfm'))]):
        done = subprocess.run(args, env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode:
            raise RuntimeError('%s failed for %s:\n%s' % (pathlib.Path(args[0]).name, name, done.stdout.decode(errors='replace')[-2000:]))
    data = output.with_suffix('.pfm').read_bytes()
    header = data.split(b'\n', 3)
    if header[0] != b'PF' or header[1].split() != [str(WIDTH).encode(), str(HEIGHT).encode()]:
        raise RuntimeError('Unexpected MoonRay image for ' + name)
    values = struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (WIDTH * HEIGHT * 3), header[3])
    return values


def moonlight(scene, session, name):
    payload, keys, warnings = moonlight_scene.pack(scene, WIDTH, HEIGHT, scene.get('_environment', 0.0), session.known,
                                                   MOONLIGHT_SAMPLES, denoise=False, runtime=session.runtime)
    session.send(payload)
    result = session.wait()
    if result['event'] != 'DONE':
        raise RuntimeError('MoonLight rejected the scene')
    session.known = keys
    (session.folder / (name + '_moonlight.pfm')).write_bytes(('PF\n%d %d\n-1.0\n' % (WIDTH, HEIGHT)).encode() + result['pixels'])
    return struct.unpack('<%df' % (WIDTH * HEIGHT * 3), result['pixels']), warnings


def blocks(values):
    """Mean luminance of BLOCK x BLOCK tiles, which averages away sampling noise."""
    columns, rows = WIDTH // BLOCK, HEIGHT // BLOCK
    sums = [0.0] * (columns * rows)
    for y in range(rows * BLOCK):
        row = values[y * WIDTH * 3:(y + 1) * WIDTH * 3]
        for x in range(columns * BLOCK):
            sums[(y // BLOCK) * columns + x // BLOCK] += .2126 * row[x * 3] + .7152 * row[x * 3 + 1] + .0722 * row[x * 3 + 2]
    return [v / (BLOCK * BLOCK) for v in sums]


def write_ppm(path, left, right):
    """MoonRay on the left, MoonLight on the right, under the same exposure."""
    encode = lambda v: round(255 * (12.92 * v if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055))
    rows = []
    for y in reversed(range(HEIGHT)):
        rows.append(bytes(encode(min(1.0, max(0.0, v))) for image in (left, right) for v in image[y * WIDTH * 3:(y + 1) * WIDTH * 3]))
    path.write_bytes(('P6\n%d %d\n255\n' % (WIDTH * 2, HEIGHT)).encode() + b''.join(rows))


def main():
    runtime = native.find_runtime(sys.argv[1])
    folder = fixture.BUILD / 'compare'
    folder.mkdir(parents=True, exist_ok=True)
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)     # the texture converters come from this runtime
    chosen = scenes(folder)
    if len(sys.argv) > 2:
        chosen = {name: chosen[name] for name in sys.argv[2:]}
    session = fixture.Session(folder)
    session.runtime = runtime
    report = {}
    try:
        for name, scene in chosen.items():
            reference = moonray(scene, runtime, folder, name)
            preview, warnings = moonlight(scene, session, name)
            if not all(math.isfinite(v) for v in reference) or not all(math.isfinite(v) for v in preview):
                raise RuntimeError('Non-finite pixels in ' + name)
            a, b = blocks(reference), blocks(preview)
            lit = [(x, y) for x, y in zip(a, b) if x > 1e-3] or [(1.0, 0.0)]
            ratios = sorted(y / x for x, y in lit)
            entry = {'mean_ratio': sum(b) / max(sum(a), 1e-12), 'median_tile_ratio': ratios[len(ratios) // 2],
                     'tiles_within_10_percent': sum(1 for r in ratios if .9 <= r <= 1.1) / len(ratios),
                     'moonray_mean': sum(a) / len(a), 'moonlight_mean': sum(b) / len(b), 'warnings': warnings}
            report[name] = entry
            write_ppm(folder / (name + '_moonray_left_moonlight_right.ppm'), reference, preview)
            print('%-13s MoonLight/MoonRay brightness %.3f (median tile %.3f), %3.0f%% of tiles within 10%%'
                  % (name, entry['mean_ratio'], entry['median_tile_ratio'], 100 * entry['tiles_within_10_percent']), flush=True)
        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        session.process.wait(timeout=10)
    finally:
        if session.process.poll() is None:
            session.process.kill()
    (folder / 'report.json').write_text(json.dumps({'runtime': str(runtime), 'scenes': report}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
