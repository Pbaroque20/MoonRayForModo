"""Generate the inspector schema from the vendored upstream material declarations."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
catalog={}
for package in ('moonshine','moonray'):
    base=root/'upstream/openmoonray/moonray'/package
    def read(path,trail=()):
        path=path.resolve()
        path.relative_to(base.resolve())
        if path in trail: raise ValueError('Cyclic schema includes')
        data=json.loads(path.read_text(encoding='utf-8'))
        attributes={}
        for include in data.get('directives',{}).get('include',[]):
            attributes.update(read(base/include,trail+(path,)))
        attributes.update(data.get('attributes',{}))
        return attributes
    for path in sorted((base/'dso/material').rglob('*.json')):
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('type')!='Material': continue
        attrs={a['name']:a for a in read(path).values()}
        catalog[data['name']]={'attributes':attrs,'interface':data.get('interface_flags','INTERFACE_MATERIAL'),
            'source':path.relative_to(root).as_posix(), 'package':package}
target=root/'kit/MoonRayForModo/python/moonray_modo/material_catalog.json'
target.write_text(json.dumps(catalog,sort_keys=True,indent=2)+'\n',encoding='utf-8')
print('Generated',len(catalog),'material schemas')
