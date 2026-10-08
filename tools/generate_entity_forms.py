"""Generate the MoonRay menu entries and property forms for MoonRay's own scene objects.

Reads entity_catalog.json and writes kit/MoonRayForModo/entities.cfg: an "Add MoonRay Item"
submenu at the end of the MoonRay menu, and one form per class that shows in the item
properties when an item of that class is selected. The command numbering follows
lxserv/moonray_entities.py: classes and their attributes in sorted order.
"""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
kit = root / 'kit/MoonRayForModo'
catalog = json.loads((kit / 'python/moonray_modo/entity_catalog.json').read_text(encoding='utf-8'))
config = ET.Element('configuration')
attributes = ET.SubElement(config, 'atom', type='Attributes')


def atom(parent, kind, text):
    ET.SubElement(parent, 'atom', type=kind).text = str(text)


def control(parent, command, label, tip=''):
    item = ET.SubElement(parent, 'list', type='Control', val='cmd ' + command)
    atom(item, 'Label', label)
    if tip:
        atom(item, 'Tooltip', tip)


def spaced(name):
    """EnvLight -> Env Light; CookieLightFilter_v2 -> Cookie Light Filter v2."""
    if name == 'DomeMaster3DCamera':
        return 'Dome Master 3D Camera'
    words, current = [], ''
    for c in name.replace('_', ' '):
        if c.isupper() and current and not current[-1].isupper() and current[-1] != ' ':
            words.append(current)
            current = ''
        current += c
    return ' '.join((' '.join(words + [current])).split())


# The menu: a submenu per kind of object, added to the tail of the kit's MoonRay menu.
menu = ET.SubElement(attributes, 'hash', type='Sheet', key='MoonRayEntityMenu:sheet')
atom(menu, 'Label', 'Add MoonRay Item')
ET.SubElement(ET.SubElement(menu, 'hash', type='InCategory', key='MoonRayForModoMenu:sheet#tail'), 'atom', type='Ordinal').text = '60'
categories = {}
for name in sorted(catalog):
    entry = catalog[name]
    if entry['category'] not in categories:
        section = ET.SubElement(menu, 'list', type='Control', val='sub MoonRayEntityMenu_%s:sheet' % entry['category'])
        atom(section, 'Label', entry['category_label'])
        categories[entry['category']] = section
    control(categories[entry['category']], 'moonray.entity.add ' + name, spaced(name))

# The forms, each shown only while an item of its class is selected.
for i, name in enumerate(sorted(catalog)):
    sheet = ET.SubElement(attributes, 'hash', type='Sheet', key='MoonRayEntity%d:sheet' % i)
    atom(sheet, 'Label', 'MoonRay ' + spaced(name))
    atom(sheet, 'Layout', 'properties')
    atom(sheet, 'FilterCommand', 'moonray.entity.filter%d' % i)
    ET.SubElement(ET.SubElement(sheet, 'hash', type='InCategory', key='itemprops:general#head'), 'atom', type='Ordinal').text = '130'
    groups = {}
    for j, (key, spec) in enumerate(sorted(catalog[name]['attributes'].items())):
        group = spec.get('group', 'Parameters')
        if group not in groups:
            section = ET.SubElement(sheet, 'list', type='Control', val='sub MoonRayEntity_%s_%d:sheet' % (name, len(groups)))
            atom(section, 'Label', group)
            atom(section, 'ShowLabel', 1)
            groups[group] = section
        kind = spec['type']
        if kind == 'Bool' or 'enum' in spec:
            how = 'Default keeps MoonRay\'s value.'
        elif kind.startswith('SceneObject'):
            how = 'Type the name of another MoonRay item%s; blank for none.' % (' (several, separated by commas)' if kind != 'SceneObject*' else '')
        elif kind == 'String':
            how = 'Blank keeps MoonRay\'s value.'
        elif kind in ('Float', 'Double', 'Int', 'Long'):
            how = 'Blank keeps MoonRay\'s value.'
        else:
            how = 'Blank keeps MoonRay\'s value. Type colours, vectors and lists as [x, y, z].'
        default = ' MoonRay\'s default: %s.' % json.dumps(spec['default']) if 'default' in spec else ''
        control(groups[group], 'moonray.entity.param%d_%d ?' % (i, j), spec.get('label', key.replace('_', ' ')),
                ' '.join(part for part in (str(spec.get('comment', '')), default.strip(), how) if part))
ET.indent(config)
ET.ElementTree(config).write(str(kit / 'entities.cfg'), encoding='utf-8', xml_declaration=True)
print('Generated the menu and forms for', len(catalog), 'MoonRay classes')
