"""Generate original MoonRay menu and mesh-property controls."""
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
path = root / 'kit/MoonRayForModo/layout.cfg'
tree = ET.parse(path)
attributes = tree.getroot().find("atom[@type='Attributes']")
sheet = attributes.find("hash[@key='MoonRayForModoMenu:sheet']")
for control in list(sheet.findall('list')):
    sheet.remove(control)
for page, label in [('render', 'Render Setup'), ('preview', 'Open Live Preview'),
                    ('object', 'Object Properties'), ('lighting', 'Shading and Lighting'),
                    ('aovs', 'Render Passes (AOVs)'), ('system', 'Runtime and CPU'),
                    ('final', 'Render EXR…'), ('export', 'Export MoonRay Scene…'),
                    ('stop', 'Stop Rendering'), ('log', 'Render Log')]:
    control = ET.SubElement(sheet, 'list', type='Control', val='cmd moonray.page ' + page)
    ET.SubElement(control, 'atom', type='Label').text = label
    ET.SubElement(control, 'atom', type='Hash').text = 'MoonRayMenu_' + page + ':control'
old = attributes.find("hash[@key='MoonRayMeshProperties:sheet']")
if old is not None:
    attributes.remove(old)
sheet = ET.SubElement(attributes, 'hash', type='Sheet', key='MoonRayMeshProperties:sheet')
ET.SubElement(sheet, 'atom', type='Label').text = 'MoonRay'
ET.SubElement(sheet, 'atom', type='Filter').text = 'Meshes'
category = ET.SubElement(sheet, 'hash', type='InCategory', key='itemprops:general#head')
ET.SubElement(category, 'atom', type='Ordinal').text = '128'
for key, label in [('override', 'Use Object Overrides'), ('subdivision', 'Subdivide in MoonRay'),
                    ('level', 'Subdivision Level'), ('smooth', 'Smooth Shading')]:
    control = ET.SubElement(sheet, 'list', type='Control', val='cmd moonray.object.' + key + ' ?')
    ET.SubElement(control, 'atom', type='Label').text = label
    ET.SubElement(control, 'atom', type='Tooltip').text = ('Settings are saved with this mesh. Enable object overrides to use them. '
        'Subdivision level is 1–5. Applies to selected meshes and supports Undo.')
ET.indent(tree, space='  ')
tree.write(path, encoding='utf-8', xml_declaration=True)
print(path)
