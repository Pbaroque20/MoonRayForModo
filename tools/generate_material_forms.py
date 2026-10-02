"""Generate filtered native Modo forms from the material catalog."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
kit=root/'kit/MoonRayForModo'
catalog=json.loads((kit/'python/moonray_modo/material_catalog.json').read_text(encoding='utf-8'))
config=ET.Element('configuration');attributes=ET.SubElement(config,'atom',type='Attributes')
def atom(parent,kind,text): ET.SubElement(parent,'atom',type=kind).text=str(text)
def control(parent,command,label,tip=''):
    item=ET.SubElement(parent,'list',type='Control',val='cmd '+command)
    atom(item,'Label',label)
    if tip: atom(item,'Tooltip',tip)
for i,shader in enumerate(['']+sorted(catalog)):
    if not shader: continue
    sheet=ET.SubElement(attributes,'hash',type='Sheet',key='MoonRayNative%d:sheet'%i)
    atom(sheet,'Label',shader);atom(sheet,'Layout','properties')
    atom(sheet,'FilterCommand','moonray.material.filter'+str(i))
    category=ET.SubElement(sheet,'hash',type='InCategory',key='itemprops:general#head');atom(category,'Ordinal',130)
    control(sheet,'moonray.material.editNative','Material inputs / searchable editor...')
    groups={}
    for j,(key,spec) in enumerate(sorted(catalog[shader]['attributes'].items())):
        if spec['type']=='SceneObject*': continue
        group=spec.get('group','Parameters')
        if group not in groups:
            section=ET.SubElement(sheet,'list',type='Control',val='sub MoonRay_'+shader+'_'+str(len(groups))+':sheet')
            atom(section,'Label',group);atom(section,'ShowLabel',1)
            groups[group]=section
        control(groups[group],'moonray.material.param%d_%d ?'%(i,j),spec.get('label',key),
                str(spec.get('comment',''))+' Default: '+str(spec.get('default',''))+'. Blank/Default uses native value. Arrays and vectors use JSON [x, y, z].')
ET.indent(config)
ET.ElementTree(config).write(str(kit/'material_properties.cfg'),encoding='utf-8',xml_declaration=True)
print('Generated forms for',len(catalog),'native material types')
