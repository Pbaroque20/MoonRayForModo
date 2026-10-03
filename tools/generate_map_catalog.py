"""Generate native map sockets from the exact vendored MoonRay declarations."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
catalog={}
for package in ('moonshine','moonray'):
    base=root/'upstream/openmoonray/moonray'/package
    def read(path,trail=()):
        path=path.resolve();path.relative_to(base.resolve())
        if path in trail:raise ValueError('Cyclic schema includes')
        data=json.loads(path.read_text(encoding='utf-8'));attributes={}
        for include in data.get('directives',{}).get('include',[]):attributes.update(read(base/include,trail+(path,)))
        attributes.update(data.get('attributes',{}));return attributes
    for category in (('map','normalmap','displacement') if package=='moonray' else ('map','normalmap')):
        for path in sorted((base/'dso'/category).rglob('*.json')):
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('type') not in ('Map','NormalMap','Displacement') or data.get('name','').startswith(('Test','Template')):continue
            attrs={a['name']:a for a in read(path).values()}
            if data['type']=='Displacement':attrs['bound_padding']={'name':'bound_padding','type':'Float','default':'0.0f','min':'0','comment':'Object-space bound padding for displaced geometry; keep close to the maximum displacement.'}
            catalog[data['name']]={'attributes':attrs,'type':data['type'],
                'source':path.relative_to(root).as_posix(),'package':package}
target=root/'kit/MoonRayForModo/python/moonray_modo/map_catalog.json'
target.write_bytes((json.dumps(catalog,sort_keys=True,indent=2)+'\n').encode('utf-8'))
print('Generated',len(catalog),'map schemas')
