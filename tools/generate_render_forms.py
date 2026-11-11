"""Generate the Render item's MoonRay properties form.

Reads moonray_modo/scene_settings.py and writes kit/MoonRayForModo/render_settings.cfg (or the path given): one form,
in front when the Render item is selected, with a section per group of settings. Each control is
a command from lxserv/moonray_render_settings.py; buttons open the preview window's dialogs.
"""
import sys
import types
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
kit = root / 'kit/MoonRayForModo'
# The package imports Modo's modules on the way in; none is used to list the settings.
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(kit / 'python'))
from moonray_modo import scene_settings  # noqa: E402

config = ET.Element('configuration')
attributes = ET.SubElement(config, 'atom', type='Attributes')


def atom(parent, kind, text):
    ET.SubElement(parent, 'atom', type=kind).text = str(text)


def sheet(key, label):
    result = ET.SubElement(attributes, 'hash', type='Sheet', key=key)
    atom(result, 'Label', label)
    atom(result, 'Layout', 'properties')
    return result


def control(parent, command, label, tip=''):
    result = ET.SubElement(parent, 'list', type='Control', val='cmd ' + command)
    atom(result, 'Label', label)
    if tip:
        atom(result, 'Tooltip', tip)


form = sheet('MoonRayRender:sheet', 'MoonRay')
# Modo's own filter, which is also what lets the form come to the front.
atom(form, 'FilterCommand', 'item.withTypeIsSelected {polyRender}')
atom(form, 'FilterCommandPriorityInfluencesTabChoice', 1)
atom(form, 'Group', 'itemprops')
ET.SubElement(ET.SubElement(form, 'hash', type='InCategory', key='itemprops:general#head'), 'atom', type='Ordinal').text = '40'
count = 0
numbered = 0
for group, collapsed, entries in scene_settings.GROUPS:
    # A group named in SHEET_KEYS has its sheet under that name; the rest are numbered in order without them.
    if group in scene_settings.SHEET_KEYS:
        key = scene_settings.SHEET_KEYS[group] + ':sheet'
    else:
        key = 'MoonRayRender_%d:sheet' % numbered
        numbered += 1
    place = ET.SubElement(form, 'list', type='Control', val='sub ' + key)
    atom(place, 'Label', group)
    atom(place, 'ShowLabel', 1)
    atom(place, 'StartCollapsed', int(collapsed))
    atom(place, 'Hash', key)
    section = sheet(key, group)
    for entry in entries:
        if entry['key'] in scene_settings.NOT_IN_FORM:
            continue
        if entry['kind'] == 'command':
            # A command of its own, kept elsewhere: the camera chooser.
            control(section, 'moonray.%s ?' % entry['key'], entry['label'], entry['tip'])
            continue
        if entry['kind'] == 'button':
            control(section, 'moonray.page ' + entry['key'], entry['label'], entry['tip'])
            continue
        control(section, 'moonray.render.%s ?' % entry['key'], entry['label'], entry['tip'])
        if entry['kind'] == 'file':
            control(section, 'moonray.render.browse_' + entry['key'], 'Browse...', 'Choose a file for ' + entry['label'])
        count += 1
ET.indent(config)
assert ET.tostring(config, encoding='unicode').isascii(), 'Modo draws anything outside ASCII as stray characters'
target = Path(sys.argv[1]) if len(sys.argv) > 1 else kit / 'render_settings.cfg'
ET.ElementTree(config).write(str(target), encoding='utf-8', xml_declaration=True)
print('Generated the Render item form:', len(scene_settings.GROUPS), 'groups,', count, 'settings')
