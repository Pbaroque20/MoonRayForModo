"""Generate the MoonRay menu entries and property forms for MoonRay's own scene objects.

Reads entity_catalog.json and writes kit/MoonRayForModo/entities.cfg: the "Add MoonRay Item"
submenu that layout.cfg places in the MoonRay menu, and one form per class that shows in the item
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


def sheet(key, label):
    result = ET.SubElement(attributes, 'hash', type='Sheet', key=key)
    atom(result, 'Label', label)
    atom(result, 'Layout', 'properties')
    return result


def nested(parent, key, label, collapsed=0, menu=False):
    """Modo defines a sub-sheet on its own and places it with a control that names it."""
    place = ET.SubElement(parent, 'list', type='Control', val='sub ' + key)
    atom(place, 'Label', label)
    atom(place, 'ShowLabel', 1)
    if menu:
        atom(place, 'PopupFace', 'option')
    atom(place, 'StartCollapsed', collapsed)
    atom(place, 'Hash', key)
    return sheet(key, label)


# The menu: a submenu per kind of object. layout.cfg places this sheet in the kit's MoonRay menu.
menu = sheet('MoonRayEntityMenu:sheet', 'Add MoonRay Item')
categories = {}
ORDER = ('light', 'lightfilter', 'camera', 'geometry', 'volume')
for name in sorted(catalog, key=lambda name: (ORDER.index(catalog[name]['category']), name)):
    entry = catalog[name]
    if entry['category'] not in categories:
        categories[entry['category']] = nested(menu, 'MoonRayEntityMenu_%s:sheet' % entry['category'], entry['category_label'], menu=True)
    control(categories[entry['category']], 'moonray.entity.add ' + name, spaced(name))

# The forms, each shown only while an item of its class is selected, with a section per group
# of attributes; all but the first start closed.
for i, name in enumerate(sorted(catalog)):
    form = sheet('MoonRayEntity%d:sheet' % i, 'MoonRay ' + spaced(name))
    atom(form, 'FilterCommand', 'moonray.entity.filter%d' % i)
    ET.SubElement(ET.SubElement(form, 'hash', type='InCategory', key='itemprops:general#head'), 'atom', type='Ordinal').text = '130'
    groups = {}
    for j, (key, spec) in enumerate(sorted(catalog[name]['attributes'].items())):
        group = spec.get('group', 'Parameters')
        if group not in groups:
            groups[group] = nested(form, 'MoonRayEntity_%s_%d:sheet' % (name, len(groups)), group, collapsed=1 if groups else 0)
        kind = spec['type']
        if kind == 'Bool' or 'enum' in spec:
            how = 'Default keeps MoonRay\'s value.'
        elif kind.startswith('SceneObject'):
            how = 'Type the name of another MoonRay item%s; blank for none.' % (' (several, separated by commas)' if kind != 'SceneObject*' else '')
        elif kind in ('String', 'Float', 'Double', 'Int', 'Long'):
            how = 'Blank keeps MoonRay\'s value.'
        else:
            how = 'Blank keeps MoonRay\'s value. Type colours, vectors and lists as [x, y, z].'
        default = 'MoonRay\'s default: %s.' % json.dumps(spec['default']) if 'default' in spec else ''
        control(groups[group], 'moonray.entity.param%d_%d ?' % (i, j), spec.get('label', key.replace('_', ' ')),
                ' '.join(part for part in (str(spec.get('comment', '')), default, how) if part))
ET.indent(config)
ET.ElementTree(config).write(str(kit / 'entities.cfg'), encoding='utf-8', xml_declaration=True)
print('Generated the menu and forms for', len(catalog), 'MoonRay classes')
