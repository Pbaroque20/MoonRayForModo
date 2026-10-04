"""Resolve inherited MaterialX interfaces and explicit/default NodeDef versions."""
import copy


def normalize(document):
 definitions={e.get('name'):e for e in document.findall('nodedef')};resolved={}
 def visit(name,trail=()):
  if name in trail or len(trail)>=64:raise ValueError('MaterialX NodeDef inheritance cycle/depth: '+str(name))
  if name in resolved:return resolved[name]
  if name not in definitions:raise ValueError('Missing inherited MaterialX NodeDef: '+str(name))
  source=definitions[name];parent=source.get('inherit')
  if parent:
   result=copy.deepcopy(visit(parent,trail+(name,)))
   result.attrib.update(source.attrib);result.attrib.pop('inherit',None)
   # Version selection flags belong to this definition, not its parent.
   for key in ('version','isdefaultversion'):
    if key not in source.attrib:result.attrib.pop(key,None)
   for child in source:
    old=next((v for v in result if v.tag==child.tag and v.get('name')==child.get('name')),None)
    if old is not None:
     replacement=copy.deepcopy(old);replacement.attrib.update(child.attrib)
     if any(k in child.attrib for k in ('value','nodename','nodegraph')):
      for key in ('value','nodename','nodegraph','output','interfacename','defaultgeomprop'):
       if key not in child.attrib:replacement.attrib.pop(key,None)
     result.remove(old);result.append(replacement)
    else:result.append(copy.deepcopy(child))
  else:result=copy.deepcopy(source)
  resolved[name]=result;return result
 for name,source in definitions.items():
  result=visit(name);at=list(document).index(source);document.remove(source);document.insert(at,result)
 return document


def select(element,definitions):
 explicit=element.get('nodedef')
 if explicit:
  if explicit not in definitions:raise ValueError('Missing explicit MaterialX NodeDef: '+explicit)
  return definitions[explicit]
 def compatible(definition):
  if definition.get('node')!=element.tag:return False
  outputs=definition.findall('output')
  if element.get('type')=='multioutput':return len(outputs)>1
  if len(outputs)!=1 or outputs[0].get('type')!=element.get('type'):return False
  ports={p.get('name'):p.get('type') for p in definition.findall('input')}
  return all(p.get('name') in ports and (not p.get('type') or p.get('type')==ports[p.get('name')]) for p in element.findall('input'))
 candidates=[d for d in definitions.values() if compatible(d)]
 if element.get('version'):candidates=[d for d in candidates if d.get('version')==element.get('version')]
 else:
  defaults=[d for d in candidates if d.get('isdefaultversion') in ('true','1')]
  if defaults:candidates=defaults
 if len(candidates)>1:raise ValueError('Ambiguous MaterialX NodeDef for '+element.tag+'; specify nodedef/version')
 if not candidates and element.get('version'):raise ValueError('Unavailable MaterialX node version: '+element.tag+' '+element.get('version'))
 return candidates[0] if candidates else None
