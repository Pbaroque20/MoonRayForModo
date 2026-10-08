"""Generate the item-properties forms for native MoonRay materials.

Reads material_catalog.json and writes kit/MoonRayForModo/material_forms.cfg: one form per
shader, shown in front when a material using that shader is selected, with a section per group
of attributes. Each control is a typed command from lxserv/moonray_material_forms.py, numbered
as there: shader i among the sorted names after a blank first entry, attribute j in sorted order.
"""
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
kit = root / 'kit/MoonRayForModo'
catalog = json.loads((kit / 'python/moonray_modo/material_catalog.json').read_text(encoding='utf-8'))
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
for i, shader in enumerate([''] + sorted(catalog)):
    if not shader:
        continue
    form = sheet('MoonRayShader%d:sheet' % i, shader)
    atom(form, 'FilterCommand', 'moonray.material.filter%d' % i)
    # Without this a form shown by a command never becomes the tab in front.
    atom(form, 'FilterCommandPriorityInfluencesTabChoice', 1)
    atom(form, 'Group', 'itemprops')
    ET.SubElement(ET.SubElement(form, 'hash', type='InCategory', key='itemprops:general#head'), 'atom', type='Ordinal').text = '40'
    groups = {}
    for j, (key, spec) in enumerate(sorted(catalog[shader]['attributes'].items())):
        if spec['type'] == 'SceneObject*':
            continue
        group = plain(spec.get('group', 'Parameters')) or 'Parameters'
        if group not in groups:
            groups[group] = nested(form, 'MoonRayShader_%s_%d:sheet' % (shader, len(groups)), group, 1 if groups else 0)
        kind = spec['type']
        how = '' if kind in ('Bool', 'Int', 'Long', 'Float', 'Double', 'Rgb', 'String') else 'Type as [x, y, z]'
        control = ET.SubElement(groups[group], 'list', type='Control', val='cmd moonray.material.attr%d_%d ?' % (i, j))
        atom(control, 'Label', plain(spec.get('label', key.replace('_', ' '))))
        tip = '. '.join(part for part in (brief(spec.get('comment', '')), how) if part)
        if tip:
            atom(control, 'Tooltip', tip)
        count += 1
ET.indent(config)
ET.ElementTree(config).write(str(kit / 'material_forms.cfg'), encoding='utf-8', xml_declaration=True)
print('Generated forms for', len(catalog), 'native material types,', count, 'attributes')
