"""Lower common MaterialX geometric/color nodes to native MoonRay graph nodes."""
import copy
import xml.etree.ElementTree as ET


def lower(document):
    definitions={e.get('name'):e for e in document.findall('nodedef')}
    from .materialx_definitions import select
    serial=0
    used={e.get('name') for e in document.iter()}
    def identity():
        nonlocal serial
        serial+=1;name='__modo_geometry_'+str(serial)
        while name in used:serial+=1;name='__modo_geometry_'+str(serial)
        used.add(name);return name
    def port(node,name,kind,value):
        return ET.SubElement(node,'input',name=name,type=kind,value=str(value))
    # Default geometric inputs are real connections, not missing/zero values.
    geomprops={e.get('name'):e for e in document.findall('geompropdef')}
    parents=[document]+list(document.findall('nodegraph'))
    for parent in parents:
        for node in list(parent):
            if node.tag in ('nodedef','nodegraph','geompropdef','input','output','implementation'):continue
            definition=select(node,definitions)
            ports={p.get('name'):p for p in definition.findall('input')} if definition is not None else {}
            ports.update({p.get('name'):p for p in node.findall('input')})
            for name,value in ports.items():
                default=value.get('defaultgeomprop')
                if not default or any(k in value.attrib for k in ('value','nodename','nodegraph','interfacename')):continue
                geom=geomprops.get(default)
                if geom is None:
                    if default!='UV0':raise ValueError('Missing MaterialX geometric property definition: '+default)
                    geom=ET.Element('geompropdef',geomprop='texcoord',index='0')
                kind=geom.get('geomprop')
                if kind not in ('texcoord','position','normal'):
                    raise ValueError('Unsupported default geometric property: '+str(kind))
                source=ET.SubElement(parent,kind,name=identity(),type=value.get('type','vector3'))
                if kind=='texcoord':port(source,'index','integer',geom.get('index','0'))
                else:port(source,'space','string',geom.get('space','object'))
                replacement=copy.deepcopy(value);replacement.attrib.pop('defaultgeomprop',None)
                replacement.set('nodename',source.get('name'))
                existing=node.find("input[@name='"+name+"']")
                if existing is not None:node.remove(existing)
                node.append(replacement)
    for parent in parents:
        for node in list(parent):
            if node.tag in ('nodedef','nodegraph','geompropdef','input','output','implementation'):continue
            definition=select(node,definitions)
            category=definition.get('node',node.tag) if definition is not None else node.tag
            if category not in ('position','normal','geompropvalue','transformpoint','transformvector','transformnormal','rgbtohsv','hsvtorgb'):continue
            inputs={p.get('name'):copy.deepcopy(p) for p in definition.findall('input')} if definition is not None else {}
            inputs.update({p.get('name'):copy.deepcopy(p) for p in node.findall('input')})
            def constant(name,default):
                p=inputs.get(name)
                if p is None:return default
                if 'value' not in p.attrib:raise ValueError(category+'.'+name+' must be a uniform literal')
                return p.get('value')
            allowed={'position':{'space'},'normal':{'space'},'geompropvalue':{'geomprop','default'},
                     'rgbtohsv':{'in'},'hsvtorgb':{'in'}}.get(category,{'in','fromspace','tospace'})
            if set(inputs)-allowed:raise ValueError('Unsupported '+category+' inputs: '+', '.join(sorted(set(inputs)-allowed)))
            node.attrib.pop('nodedef',None);node.attrib.pop('version',None)
            for child in list(node):node.remove(child)
            if category in ('rgbtohsv','hsvtorgb'):
                node.tag='moonray_'+('RgbToHsvMap' if category=='rgbtohsv' else 'HsvToRgbMap')
                value=inputs.get('in',ET.Element('input',type='color3',value='0,0,0'))
                value.set('name','input');node.append(value);continue
            if category=='geompropvalue':
                types={'float':0,'vector2':1,'vector3':2,'color3':3,'integer':4}
                if node.get('type') not in types:raise ValueError('Unsupported geometric property type: '+str(node.get('type')))
                node.tag='moonray_AttributeMap';port(node,'map_type','integer',0)
                port(node,'primitive_attribute_name','string',constant('geomprop',''))
                port(node,'primitive_attribute_type','integer',types[node.get('type')])
                value=inputs.get('default',ET.Element('input',type='color3',value='0,0,0'))
                value.set('name','default_value');node.append(value)
                port(node,'warn_when_unavailable','boolean','true');continue
            spaces={'object':4,'world':2}
            if category in ('position','normal'):
                space=constant('space','object')
                if space not in spaces:raise ValueError('MaterialX space has no unambiguous Modo mapping: '+space)
                raw=ET.SubElement(parent,'moonray_AttributeMap',name=identity(),type='color3')
                port(raw,'map_type','integer',1 if category=='position' else 3)
                value=ET.Element('input',name='input',type='vector3',nodename=raw.get('name'))
                source,target=0,spaces[space];input_type=0 if category=='position' else 2
            else:
                before=constant('fromspace','');after=constant('tospace','')
                value=inputs.get('in',ET.Element('input',type='vector3',value='0,0,1' if category=='transformnormal' else '0,0,0'))
                value.set('name','input')
                if not before or not after or before==after:
                    node.tag='moonray_convert';value.set('name','in');node.append(value);continue
                if before not in spaces or after not in spaces:raise ValueError('Unsupported MaterialX coordinate-space transform')
                source,target=spaces[before],spaces[after]
                input_type={'transformpoint':0,'transformvector':1,'transformnormal':2}[category]
            node.tag='moonray_TransformSpaceMap';node.append(value)
            port(node,'from_space','integer',source);port(node,'to_space','integer',target)
            port(node,'input_type','integer',input_type)
    return document
