"""Generate the MoonRay menu entries and property forms for MoonRay's own scene objects.

Reads entity_catalog.json and writes kit/MoonRayForModo/entities.cfg: the "Add MoonRay Item"
submenu that layout.cfg places in the MoonRay menu, and one form per class that shows in the item
properties when an item of that class is selected. The item types and their channels are those
lxserv/moonray_entities.py registers, both taken from entities.channels.
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


TIP_LENGTH = 90


def brief(comment):
    """MoonRay's description cut down to a tooltip someone will read: its first sentence, kept short."""
    import re
    text = ' '.join(str(comment).split())
    # The first sentence; a full stop inside a number or an abbreviation does not end it.
    found = re.match(r'(.+?[.!?])(?=\s+[A-Z(]|$)', text)
    text = (found.group(1) if found else text).rstrip('.')
    text = re.sub(r'\s*\((?:[^()]*)\)$', '', text)
    if len(text) > TIP_LENGTH:
        text = text[:TIP_LENGTH + 1].rsplit(' ', 1)[0].rstrip(',;:') + '...'
    return text


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

# The forms, each shown only while an item of its type is selected and placed ahead of the
# locator's own tabs, with a section per group of attributes; all but the first start closed.
# Every control is the item's own channel, so Modo draws what suits it.
import sys
sys.path.insert(0, str(kit / 'python'))
from moonray_modo import entities

for i, name in enumerate(sorted(catalog)):
    form = sheet('MoonRayEntity%d:sheet' % i, 'MoonRay ' + spaced(name))
    atom(form, 'FilterCommand', 'item.withTypeIsSelected {%s} testSupertypes:true' % entities.item_type(name))
    # Without this a form shown by a command never becomes the tab in front.
    atom(form, 'FilterCommandPriorityInfluencesTabChoice', 1)
    atom(form, 'Group', 'itemprops')
    ET.SubElement(ET.SubElement(form, 'hash', type='InCategory', key='itemprops:general#head'), 'atom', type='Ordinal').text = '40'
    groups = {}
    for j, (key, channel, kind, default, choices) in enumerate(entities.channels(name)):
        spec = catalog[name]['attributes'][key]
        group = spec.get('group', 'Parameters')
        if group not in groups:
            groups[group] = nested(form, 'MoonRayEntity_%s_%d:sheet' % (name, len(groups)), group, collapsed=1 if groups else 0)
        label = spec.get('label', key.replace('_', ' '))
        tip = brief(spec.get('comment', ''))
        channel_control = 'item.channel %s$%s ?' % (entities.item_type(name), channel)
        category = entities.reference_category(spec)
        if choices:
            # Named values: a popup drawn by a command.
            control(groups[group], 'moonray.entity.choice%d_%d ?' % (i, j), label, tip)
        elif category and spec['type'] == 'SceneObject*':
            # One other MoonRay item: a popup of those in the scene.
            control(groups[group], 'moonray.entity.pick%d_%d ?' % (i, j), label, tip)
        elif category:
            # Several: the list as text, and a popup that adds to it.
            control(groups[group], channel_control, label, tip)
            control(groups[group], 'moonray.entity.append%d_%d ?' % (i, j), 'add to ' + label, 'Add a MoonRay item to the list above')
        elif spec.get('filename'):
            control(groups[group], channel_control, label, tip)
            control(groups[group], 'moonray.entity.browse%d_%d' % (i, j), 'Browse for ' + label + '...', '')
        else:
            how = ''
            if kind == 'string' and spec['type'].startswith('SceneObject'):
                how = 'Type its name'
            elif kind == 'string' and spec['type'] != 'String':
                element = spec['type'][:-6]
                how = ('Type as 1 0 0; 0 1 0' if element in ('Rgb', 'Vec2f', 'Vec3f') else 'Separate with commas' if element == 'String'
                       else 'Type as 0 0.5 1')
            elif kind != 'string' and 'default' not in spec:
                how = ''
            control(groups[group], channel_control, label, '. '.join(part for part in (tip, how) if part))
ET.indent(config)
ET.ElementTree(config).write(str(kit / 'entities.cfg'), encoding='utf-8', xml_declaration=True)
print('Generated the menu and forms for', len(catalog), 'MoonRay classes')
