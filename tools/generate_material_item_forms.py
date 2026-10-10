"""Generate the item-properties forms for native MoonRay materials.

Reads material_catalog.json and writes kit/MoonRayForModo/material_forms.cfg: one form per
shader, shown in front when a material using that shader is selected, with a section per group
of attributes. Each control is a typed command from lxserv/moonray_material_forms.py, numbered
as there: shader i among the sorted names after a blank first entry, attribute j in sorted order.
"""
import json
import sys
import types
import re
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
kit = root / 'kit/MoonRayForModo'
catalog = json.loads((kit / 'python/moonray_modo/material_catalog.json').read_text(encoding='utf-8'))
# The package imports Modo's modules on the way in; none is used to say which inputs take an image.
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(kit / 'python'))
from moonray_modo import graph_images, ramps  # noqa: E402

config = ET.Element('configuration')
attributes = ET.SubElement(config, 'atom', type='Attributes')
TIP_LENGTH = 90


def plain(text):
    """Modo's menus and forms showed stray characters for anything outside ASCII."""
    for odd, usual in (('…', '...'), ('—', '-'), ('–', '-'), ('‘', "'"), ('’', "'"), ('“', '"'), ('”', '"')):
        text = text.replace(odd, usual)
    return text.encode('ascii', 'ignore').decode('ascii')


def brief(comment):
    """MoonRay's description cut down to a tooltip someone will read: its first sentence, kept short."""
    text = plain(' '.join(str(comment).split()))
    found = re.match(r'(.+?[.!?])(?=\s+[A-Z(]|$)', text)
    text = (found.group(1) if found else text).rstrip('.')
    if len(text) > TIP_LENGTH:
        text = text[:TIP_LENGTH + 1].rsplit(' ', 1)[0].rstrip(',;:') + '...'
    return text


def atom(parent, kind, text):
    ET.SubElement(parent, 'atom', type=kind).text = str(text)


def sheet(key, label):
    result = ET.SubElement(attributes, 'hash', type='Sheet', key=key)
    atom(result, 'Label', label)
    atom(result, 'Layout', 'properties')
    return result


def nested(parent, key, label, collapsed):
    """Modo defines a sub-sheet on its own and places it with a control that names it."""
    place = ET.SubElement(parent, 'list', type='Control', val='sub ' + key)
    atom(place, 'Label', label)
    atom(place, 'ShowLabel', 1)
    atom(place, 'StartCollapsed', collapsed)
    atom(place, 'Hash', key)
    return sheet(key, label)


count = 0
ramp_count = 0
for i, shader in enumerate([''] + sorted(catalog)):
    if not shader:
        continue
    # The controls, shown by two tabs: one for a material assigned to a mesh, which carries a
    # package named for its shader, and one for a layer added from Add Layer, whose type is the
    # shader. Both use Modo's own filters, which also tell it how well a form fits the
    # selection; a filter written in Python cannot, and Modo's material form stayed in front.
    form = sheet('MoonRayShaderBody%d:sheet' % i, shader)
    for tab, test in (('MoonRayShader%d:sheet' % i, 'item.withPackageIsSelected moonray.shader.%s' % shader),
                      ('MoonRayShaderLayer%d:sheet' % i, 'item.withTypeIsSelected {material.dw.%s}' % shader)):
        shown = sheet(tab, shader)
        atom(shown, 'FilterCommand', test)
        atom(shown, 'FilterCommandPriorityInfluencesTabChoice', 1)
        atom(shown, 'Group', 'itemprops')
        ET.SubElement(ET.SubElement(shown, 'hash', type='InCategory', key='itemprops:general#head'), 'atom', type='Ordinal').text = '40'
        inside = ET.SubElement(shown, 'list', type='Control', val='ref MoonRayShaderBody%d:sheet' % i)
        atom(inside, 'ShowLabel', 0)
        atom(inside, 'Hash', 'MoonRayShaderBody%d:sheet' % i)
    # The same material as a graph: its inputs can be wired to maps there.
    graph = ET.SubElement(form, 'list', type='Control', val='cmd moonray.material.nodes')
    atom(graph, 'Label', 'Open Graph Editor...')
    atom(graph, 'Tooltip', 'Edit this material as a node graph, where its inputs can be connected to maps')
    groups = {}
    texturable = graph_images.offered(shader)

    def chooser(parent, key, spec, j):
        # The image on this input: a node wired to it in the material's graph.
        made = ET.SubElement(parent, 'list', type='Control', val='cmd moonray.material.map%d_%d ?' % (i, j))
        atom(made, 'Label', plain(spec.get('label', key.replace('_', ' '))) + ' image')
        atom(made, 'Tooltip', 'Load an image for this input, or remove it. It appears as a node in the graph editor')
    found = ramps.groups(catalog[shader]['attributes'])
    members = {member: positions for positions, held in found.items() for member in held[1:]}
    for j, (key, spec) in enumerate(sorted(catalog[shader]['attributes'].items())):
        group = plain(spec.get('group', 'Parameters')) or 'Parameters'
        if spec['type'] == 'SceneObject*' and key not in texturable:
            continue
        if group not in groups:
            groups[group] = nested(form, 'MoonRayShader_%s_%d:sheet' % (shader, len(groups)), group, 1 if groups else 0)
        if spec['type'] == 'SceneObject*':
            # A normal map has no value of its own to edit, only its image.
            chooser(groups[group], key, spec, j)
            continue
        if key in members:
            # A ramp is three lists that go together. They are one button, where its positions would be, that opens
            # the ramp editor; none of the lists is a row to type numbers into.
            if key == members[key]:
                title = ' '.join(word.capitalize() for word in found[key][0].split())
                made = ET.SubElement(groups[group], 'list', type='Control', val='cmd moonray.material.ramp%d_%d' % (i, j))
                atom(made, 'Label', 'Edit ' + title + '...')
                atom(made, 'Tooltip', 'Edit the stops of this ramp: where each is, its colour or value, and how it blends to the next')
                ramp_count += 1
            continue
        kind = spec['type']
        how = '' if kind in ('Bool', 'Int', 'Long', 'Float', 'Double', 'Rgb', 'String') else 'Type as [x, y, z]'
        control = ET.SubElement(groups[group], 'list', type='Control', val='cmd moonray.material.attr%d_%d ?' % (i, j))
        atom(control, 'Label', plain(spec.get('label', key.replace('_', ' '))))
        tip = '. '.join(part for part in (brief(spec.get('comment', '')), how) if part)
        if tip:
            atom(control, 'Tooltip', tip)
        count += 1
        if key in texturable:
            chooser(groups[group], key, spec, j)
# Where the layer types sit in the Shader Tree's Add Layer list, and what they are called.
categories = ET.SubElement(ET.SubElement(config, 'atom', type='Categories'), 'hash', type='Category', key='itemtype:textureLayer')
for shader in sorted(catalog):
    ET.SubElement(categories, 'hash', type='C', key='material.dw.' + shader).text = 'dwMaterials'
table = ET.SubElement(ET.SubElement(config, 'atom', type='Messages'), 'hash', type='Table', key='itemtype:textureLayer:category.en_US')
ET.SubElement(table, 'hash', type='T', key='dwMaterials').text = 'MoonRay Materials'
names = ET.SubElement(config, 'atom', type='CommandHelp')
for shader in sorted(catalog):
    atom(ET.SubElement(names, 'hash', type='Item', key='material.dw.%s@en_US' % shader), 'UserName', shader)
ET.indent(config)
ET.ElementTree(config).write(str(kit / 'material_forms.cfg'), encoding='utf-8', xml_declaration=True)
print('Generated forms for', len(catalog), 'native material types,', count, 'attributes,', ramp_count, 'ramps')
