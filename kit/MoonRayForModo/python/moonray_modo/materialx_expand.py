"""Expand local, named-output MaterialX NodeDef graph implementations safely."""
import copy

CONNECTION=('value','nodename','nodegraph','output','interfacename','channels')

def expand(document):
    definitions={e.get('name'):e for e in document.findall('nodedef')}
    graphs={e.get('name'):e for e in document.findall('nodegraph')}
    implementations={e.get('nodedef'):e for e in graphs.values() if e.get('nodedef')}
    for implementation in document.findall('implementation'):
        if implementation.get('nodegraph') in graphs:
            implementations[implementation.get('nodedef')]=graphs[implementation.get('nodegraph')]
    templates={id(e) for e in implementations.values()}
    queue=[(document,'',())]+[(g,name,()) for name,g in graphs.items() if id(g) not in templates]
    count=0
    while queue:
        parent,scope,trail=queue.pop(0)
        for node in list(parent):
            if node.tag in ('input','output','nodedef','nodegraph','implementation','surfacematerial'):continue
            name=node.get('nodedef');definition=definitions.get(name)
            # Infer a local definition only when category and output type identify it uniquely.
            if definition is None:
                matches=[d for d in definitions.values() if d.get('node')==node.tag and d.get('name') in implementations
                    and (node.get('type')=='multioutput' or any(o.get('type')==node.get('type') for o in d.findall('output')))]
                if len(matches)==1:definition=matches[0];name=definition.get('name')
            template=implementations.get(name)
            if template is None:continue
            if name in trail or len(trail)>=32:raise ValueError('Recursive MaterialX NodeDef graph: '+str(name))
            outputs=template.findall('output')
            if not outputs:raise ValueError('MaterialX NodeDef implementation has no outputs: '+str(name))
            count+=1
            if count>1000:raise ValueError('MaterialX expansion exceeds 1000 graph instances')
            clone=copy.deepcopy(template);clone_name='__moonray_expanded_'+str(count)
            while clone_name in graphs:clone_name+='x'
            clone.set('name',clone_name);clone.attrib.pop('nodedef',None)
            values={p.get('name'):p for p in definition.findall('input')}
            values.update({p.get('name'):p for p in template.findall('input')})
            values.update({p.get('name'):p for p in node.findall('input')})
            for port in clone.iter():
                if not port.get('interfacename'):continue
                source=values.get(port.get('interfacename'))
                if source is None:raise ValueError('Missing MaterialX interface value: '+port.get('interfacename'))
                source=copy.deepcopy(source)
                if source.get('interfacename'):
                    inherited=next((p for p in parent.findall('input') if p.get('name')==source.get('interfacename')),None)
                    if inherited is None:raise ValueError('Missing enclosing MaterialX interface')
                    source=inherited
                for attr in CONNECTION:port.attrib.pop(attr,None)
                for attr in CONNECTION:
                    if attr in source.attrib:port.set(attr,source.get(attr))
                if scope and port.get('nodename') and '/' not in port.get('nodename'):
                    port.set('nodename',scope+'/'+port.get('nodename'))
            document.append(clone);graphs[clone_name]=clone
            queue.append((clone,clone_name,trail+(name,)))
            # Keep the original instance name as a connection alias.
            identity=node.get('name');xtype=node.get('type');node.clear();node.tag='output'
            node.set('name',identity);node.set('type',xtype or outputs[0].get('type','color3'))
            node.set('nodegraph',clone_name)
            if len(outputs)==1:node.set('output',outputs[0].get('name','out'))
    return document
