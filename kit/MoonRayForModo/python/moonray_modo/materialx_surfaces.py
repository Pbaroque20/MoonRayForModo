"""OpenPBR and glTF surfaces, read as the Standard Surface they come closest to.

The importer translates Standard Surface. The other two surfaces most files are written with say much the same things
under other names, so each is rewritten as a Standard Surface before it is translated: its inputs renamed, the few that
differ in kind converted, and what Standard Surface has no word for left out. What is left out is listed, so the
import can say so.
"""

# This surface's name for an input, and Standard Surface's.
OPENPBR = {
    'base_weight': 'base', 'base_color': 'base_color', 'base_metalness': 'metalness', 'base_diffuse_roughness': 'diffuse_roughness',
    'specular_weight': 'specular', 'specular_color': 'specular_color', 'specular_roughness': 'specular_roughness', 'specular_ior': 'specular_IOR',
    'specular_roughness_anisotropy': 'specular_anisotropy',
    'transmission_weight': 'transmission', 'transmission_color': 'transmission_color',
    # OpenPBR's radius is a distance and its scale a colour; Standard Surface has them the other way about.
    'subsurface_weight': 'subsurface', 'subsurface_color': 'subsurface_color', 'subsurface_radius': 'subsurface_scale',
    'subsurface_radius_scale': 'subsurface_radius', 'subsurface_scatter_anisotropy': 'subsurface_anisotropy',
    'fuzz_weight': 'sheen', 'fuzz_color': 'sheen_color', 'fuzz_roughness': 'sheen_roughness',
    'coat_weight': 'coat', 'coat_color': 'coat_color', 'coat_roughness': 'coat_roughness', 'coat_ior': 'coat_IOR',
    'emission_luminance': 'emission', 'emission_color': 'emission_color',
    'geometry_opacity': 'opacity', 'geometry_thin_walled': 'thin_walled', 'geometry_normal': 'normal', 'geometry_coat_normal': 'coat_normal',
    'geometry_tangent': 'tangent'}
GLTF = {
    'base_color': 'base_color', 'metallic': 'metalness', 'roughness': 'specular_roughness', 'normal': 'normal', 'tangent': 'tangent',
    'transmission': 'transmission', 'specular': 'specular', 'specular_color': 'specular_color', 'ior': 'specular_IOR', 'alpha': 'opacity',
    'emissive': 'emission_color', 'emissive_strength': 'emission', 'sheen_color': 'sheen_color', 'sheen_roughness': 'sheen_roughness',
    'clearcoat': 'coat', 'clearcoat_roughness': 'coat_roughness', 'clearcoat_normal': 'coat_normal'}
SURFACES = {'open_pbr_surface': OPENPBR, 'gltf_pbr': GLTF}
# Standard Surface takes these as a colour, where the other surfaces give one number.
COLOURS = ('opacity',)
# A weight Standard Surface starts at nothing, which the other surface has no input for: it is on wherever its colour is given.
IMPLIED = {'gltf_pbr': (('emission_color', 'emission'), ('sheen_color', 'sheen'))}
# glTF's surface starts as a plain dielectric with these; Standard Surface starts elsewhere.
STARTS = {'gltf_pbr': (('specular_roughness', 'float', '1'), ('metalness', 'float', '1'), ('base_color', 'color3', '1, 1, 1')),
          'open_pbr_surface': (('specular_roughness', 'float', '0.3'),)}


def authored(port):
    return any(key in port.attrib for key in ('value', 'nodename', 'nodegraph', 'interfacename', 'output'))


def standardize(document):
    """Rewrite every OpenPBR and glTF surface of a MaterialX document as a Standard Surface, in place. Returns what was
    left out, as '<surface name>: <input>' for each input that was set and has no counterpart."""
    left_out = []
    for parent in [document] + list(document.findall('nodegraph')):
        for element in parent:
            names = SURFACES.get(element.tag)
            if names is None:
                continue
            kind, element.tag = element.tag, 'standard_surface'
            element.attrib.pop('nodedef', None)
            given = set()
            for port in list(element.findall('input')):
                name = port.get('name')
                if name not in names:
                    if authored(port):
                        left_out.append('%s: %s' % (element.get('name', kind), name))
                    element.remove(port)
                    continue
                port.set('name', names[name])
                given.add(names[name])
                if names[name] in COLOURS and port.get('type') == 'float' and 'value' in port.attrib:
                    port.set('type', 'color3')
                    port.set('value', ', '.join([port.get('value').strip()] * 3))
            for colour, weight in IMPLIED.get(kind, ()):
                if colour in given and weight not in given:
                    made = element.makeelement('input', {'name': weight, 'type': 'float', 'value': '1'})
                    element.append(made)
            for name, value_type, value in STARTS.get(kind, ()):
                if name not in given:
                    element.append(element.makeelement('input', {'name': name, 'type': value_type, 'value': value}))
    return left_out
