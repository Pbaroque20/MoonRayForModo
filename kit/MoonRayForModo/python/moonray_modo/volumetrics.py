"""Modo's light volumetrics and environment fog, as MoonRay fog.

A light with Volumetrics on lights a shape of fog of its own: a point light's sphere, a spot light's cone, a
directional light's cylinder. Each becomes a mesh filled with an even MoonRay fog (a BaseVolume), lit by that light
alone, from the light material's Scattering, Scattering Color, Density, Attenuation and Shift. The Environment
Material's fog becomes an even fog around the camera, lit by the environment alone, which in time turns what lies
behind it to the environment's colour, as Modo's fog does: Exponential at its density, Linear from Fog Start, thick by
Fog End, and Layered as a slab up to its height. MoonRay and MoonLightIPR both draw these (rdla.material_volume,
entities.even_fog)."""
import math

# Marks the meshes, materials and items made here, so that a reading done again replaces rather than adds to them.
PREFIX = 'modo_volumetrics:'


def light_shape(kind, item, channel):
    """(vertices, faces) of the fog a light lights, in the light's own space (it shines down its -Z), or None."""
    from .entities import sphere
    if kind == 'pointLight':
        return sphere(max(1e-3, float(channel(item, 'vrad', 1.0))), 32, 16)
    if kind == 'spotLight':
        length = max(1e-3, float(channel(item, 'height', 10.0)))
        base = max(0.0, float(channel(item, 'base', 0.0)))
        half = min(math.radians(89.0), max(1e-3, float(channel(item, 'cone', math.pi / 4)) / 2))
        return frustum(base, base + length * math.tan(half), length)
    if kind == 'sunLight':
        radius = max(1e-3, float(channel(item, 'radius', 0.5)))
        return frustum(radius, radius, max(1e-3, float(channel(item, 'height', 10.0))))
    return None


def frustum(near, far, length, segments=32):
    """A closed cone cut short, from radius near at the origin to radius far at length down -Z; faces outward."""
    ring = [(math.cos(2 * math.pi * s / segments), math.sin(2 * math.pi * s / segments)) for s in range(segments)]
    vertices = [[max(near, 1e-4) * x, max(near, 1e-4) * y, 0.0] for x, y in ring]
    vertices += [[far * x, far * y, -length] for x, y in ring]
    vertices += [[0.0, 0.0, 0.0], [0.0, 0.0, -length]]
    top, bottom = 2 * segments, 2 * segments + 1
    faces = [[s, segments + s, segments + (s + 1) % segments, (s + 1) % segments] for s in range(segments)]
    faces += [[top, s, (s + 1) % segments] for s in range(segments)]
    faces += [[bottom, segments + (s + 1) % segments, segments + s] for s in range(segments)]
    return vertices, faces


def shell(outer, inner):
    """One closed shape with another taken out of it: inner's faces turned to face into the hole."""
    vertices, faces = outer
    hole_vertices, hole_faces = inner
    start = len(vertices)
    return vertices + hole_vertices, faces + [[start + i for i in reversed(face)] for face in hole_faces]


def placed(shape, offset):
    vertices, faces = shape
    return [[v[0] + offset[0], v[1] + offset[1], v[2] + offset[2]] for v in vertices], faces


def fog_parameters(extinction, albedo, anisotropy):
    """A BaseVolume's values for an even fog that stops extinction (per channel) in a unit of distance and scatters
    albedo of that."""
    strength = max(extinction)
    if strength <= 0:
        return None
    return {'attenuation_color': [v / strength for v in extinction], 'attenuation_intensity': strength, 'attenuation_factor': 1.0,
            'diffuse_color': [min(1.0, max(0.0, v)) for v in albedo], 'anisotropy': min(0.95, max(-0.95, float(anisotropy))),
            'emission_color': [0.0, 0.0, 0.0]}


def light_fog(item, channel, color):
    """The fog a light's material asks for: Density thickens it, Scattering and its colour are what of it scatters
    light, Attenuation what it takes in, Shift whether it sends light on (above 0) or back (below), Volumetric
    Dissolve thins it."""
    material = item.material
    density = max(0.0, float(channel(material, 'density', 0.5))) if material else 0.5
    density *= max(0.0, 1.0 - float(channel(item, 'vdissolve', 0.0)))
    scattering = max(0.0, float(channel(material, 'scattering', 1.0))) if material else 1.0
    tint = color(material, 'scatteringColor') if material else [1.0, 1.0, 1.0]
    absorbing = max(0.0, float(channel(material, 'attenuate', 0.1))) if material else 0.1
    shift = float(channel(material, 'shift', 0.0)) if material else 0.0
    scattered = [density * scattering * max(0.0, v) for v in tint]
    extinction = [s + density * absorbing for s in scattered]
    return fog_parameters(extinction, [s / e if e > 0 else 0.0 for s, e in zip(scattered, extinction)], shift)


def environment_fog(layer, channel, camera):
    """(shape in the world, fog values, notice) of an Environment Material's fog, or None. The shape is about the
    camera, out to where the fog has all but hidden what lies behind it, with the camera itself left outside it."""
    kind = str(channel(layer, 'fogType', 'none'))
    if kind == 'none':
        return None
    from .entities import sphere, box
    where = camera[12:15] if camera and len(camera) == 16 else [0.0, 0.0, 0.0]
    density = max(0.0, float(channel(layer, 'fogDensity', 0.1)))
    start = max(0.0, float(channel(layer, 'fogStart', 0.0)))
    end = max(start + 1e-3, float(channel(layer, 'fogEnd', 10.0)))
    near = 0.01
    if kind == 'linear':
        # Even fog from Fog Start that has hidden 95% of what lies behind it by Fog End.
        density, inner, outer = 3.0 / (end - start), max(near, start), end * 1.5 + 1.0
        notice = 'Environment fog %s: Linear fog is drawn as an even fog from Fog Start, thick by Fog End.'
    elif kind in ('exp', 'exponential'):
        if density <= 0:
            return None
        inner, outer = near, 6.0 / density
        notice = None
    elif kind == 'layered':
        if density <= 0:
            return None
        height = float(channel(layer, 'fogHeight', 0.0)) + 0.5 * max(0.0, float(channel(layer, 'fogFalloff', 0.5)))
        reach = 6.0 / density
        bottom = min(where[1], height) - reach
        if height <= bottom:
            return None
        slab = placed(box([2 * reach, height - bottom, 2 * reach]), [where[0], (height + bottom) / 2, where[2]])
        if where[1] < height:
            slab = shell(slab, placed(box([2 * near] * 3), where))
        return slab, fog_parameters([density] * 3, [1.0] * 3, 0.0), \
            'Environment fog %s: Layered fog is drawn as an even fog up to its height, without its falloff.' % layer.name
    else:
        return None, None, 'Environment fog %s: %s fog is not translated.' % (layer.name, kind.capitalize())
    shape = placed(shell(sphere(outer, 48, 24), sphere(inner, 16, 8)), where)
    return shape, fog_parameters([density] * 3, [1.0] * 3, 0.0), (notice % layer.name if notice else None)


def capture(scene, result, warnings):
    """Add each volumetric light's fog, and the environment's, to a snapshot: a mesh, the material that fills it
    with fog and links it to the light that lights it, and the fog itself as a MoonRay item."""
    from .host import channel, color
    result['meshes'] = [mesh for mesh in result.get('meshes', []) if not str(mesh.get('identity', '')).startswith(PREFIX)]
    result['entities'] = [entity for entity in result.get('entities', []) if not str(entity.get('identity', '')).startswith(PREFIX)]
    materials = result.setdefault('materials', {})
    for tag in [tag for tag in materials if tag.startswith(PREFIX)]:
        del materials[tag]
    base = materials.get('', {})
    identity = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]

    def add(name, owner, shape, fog, matrix, lights):
        tag = PREFIX + owner
        vertices, faces = shape
        result['entities'].append({'identity': tag, 'name': tag, 'class': 'BaseVolume', 'matrix': list(identity), 'parameters': fog})
        material = {key: value for key, value in base.items() if key not in ('material_stack', 'native_dependencies', 'node_graph')}
        material.update(name=name, moonray_volume=tag, volume_only=True,
                        rdl_layer_links={'link_enabled': True, 'lights': lights})
        materials[tag] = material
        result['meshes'].append({'name': name, 'identity': tag, 'source_item': owner if lights != ['__environment__'] else None,
                                 'vertices': vertices, 'faces': faces, 'matrix': list(matrix), 'material': tag,
                                 'face_materials': [tag] * len(faces), 'uvs': [], 'normals': [], 'uv_sets': {},
                                 'smooth': False, 'subdivision': False, 'subdivision_level': 1, 'object_override': False,
                                 'geometry_settings': {}, 'volumetric': True})

    lights = {light['identity']: light for light in result.get('lights', [])}
    for item in scene.items('light'):
        if item.id not in lights or not channel(item, 'volumetrics', False):
            continue
        shape = light_shape(item.type, item, channel)
        if shape is None:
            warnings.append('Volumetrics of %s are not translated for this kind of light.' % item.name)
            continue
        fog = light_fog(item, channel, color)
        if fog is None:
            continue
        add(item.name + ' volumetrics', item.id, shape, fog, lights[item.id]['matrix'], [item.id])
    for layer in scene.items('envMaterial', superType=False):
        if not channel(layer, 'enable', True):
            continue
        found = environment_fog(layer, channel, (result.get('camera') or {}).get('matrix'))
        if found is None:
            continue
        shape, fog, notice = found
        if notice:
            warnings.append(notice)
        if shape is None or fog is None:
            continue
        add(layer.name + ' fog', layer.id, shape, fog, identity, ['__environment__'])
    for shader in scene.items('defaultShader', superType=False):
        if channel(shader, 'fogEnable', False) and str(channel(shader, 'fogType', 'none')) != 'none':
            warnings.append('The fog of shader %s is not translated; the Environment Material\'s fog is.' % shader.name)
