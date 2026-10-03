"""Bounded local MaterialX library loading with relative asset resolution."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET


def load(path):
    dependencies=[];total=[0];cache={}
    def visit(filename, trail):
        filename=Path(filename).resolve()
        if filename in trail:raise ValueError('MaterialX include cycle: '+str(filename))
        if len(trail)>32:raise ValueError('MaterialX include depth exceeds 32')
        if filename in cache:return copy.deepcopy(cache[filename])
        raw=filename.read_bytes();total[0]+=len(raw)
        if len(raw)>4*1024*1024 or total[0]>32*1024*1024:raise ValueError('MaterialX library size limit exceeded')
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('MaterialX document entities are not supported')
        root=ET.fromstring(raw)
        if root.tag!='materialx':raise ValueError('Expected a MaterialX document: '+str(filename))
        dependencies.append(str(filename))
        def asset_prefix(element,inherited):
            prefix=inherited/element.get('fileprefix','')
            for port in element:
                if port.tag in ('input','parameter') and port.get('type')=='filename' and port.get('value'):
                    port.set('value',str((prefix/port.get('value')).resolve()))
                asset_prefix(port,prefix)
            element.attrib.pop('fileprefix',None)
        asset_prefix(root,filename.parent)
        for child in list(root):
            if child.tag not in ('{http://www.w3.org/2001/XInclude}include','include'):continue
            href=child.get('href','')
            if not href or '://' in href or child.get('parse','xml')!='xml':raise ValueError('MaterialX includes must name local XML files')
            included=visit(filename.parent/href,trail+(filename,));at=list(root).index(child);root.remove(child)
            for entry in reversed(list(included)):root.insert(at,entry)
        cache[filename]=copy.deepcopy(root)
        return root
    document=visit(path,())
    seen={}
    for child in list(document):
        name=child.get('name')
        if not name:continue
        if name in seen:
            if ET.tostring(child)!=ET.tostring(seen[name]):raise ValueError('Conflicting MaterialX library definition: '+name)
            document.remove(child)
        else:seen[name]=child
    return document,dependencies
