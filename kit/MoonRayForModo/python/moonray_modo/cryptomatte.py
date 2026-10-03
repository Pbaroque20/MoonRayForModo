"""Stable MurmurHash3 object IDs and standard Cryptomatte EXR metadata."""
import json,struct
from .rdla import string,number,array

def hash32(text):
    data=text.encode('utf-8');h=0
    def rot(v,n):return ((v<<n)|(v>>(32-n)))&0xffffffff
    for i in range(0,len(data)-3,4):
        k=int.from_bytes(data[i:i+4],'little');k=k*0xcc9e2d51&0xffffffff;k=rot(k,15);k=k*0x1b873593&0xffffffff
        h^=k;h=rot(h,13);h=(h*5+0xe6546b64)&0xffffffff
    tail=data[len(data)//4*4:]
    if tail:
        k=int.from_bytes(tail,'little');k=k*0xcc9e2d51&0xffffffff;k=rot(k,15);k=k*0x1b873593&0xffffffff;h^=k
    h^=len(data);h^=h>>16;h=h*0x85ebca6b&0xffffffff;h^=h>>13;h=h*0xc2b2ae35&0xffffffff;h^=h>>16
    return h

def float_id(name):
    value=hash32(name);exponent=(value>>23)&255
    if exponent in (0,255):value^=1<<23
    return struct.unpack('<f',struct.pack('<I',value))[0]

def enabled(scene):return any(v.get('kind')=='cryptomatte' for v in scene.get('custom_aovs',[]))

def category(scene):
    return next((v.get('category','object') for v in scene.get('custom_aovs',[]) if v.get('kind')=='cryptomatte'),'object')


def name(geometry,category='object',scene=None,identity=None):
    from .lighting import owner
    item=identity or owner(geometry)
    if category=='material':return material_name(geometry.get('material',''),scene)
    if category=='asset':return (scene or {}).get('production',{}).get('objects',{}).get(item.split('|')[0],{}).get('asset_label') or item
    return geometry.get('name','Object')+' ['+item+']'


def material_name(tag,scene):
    material=(scene or {}).get('materials',{}).get(tag,{})
    name=material.get('name')
    return (name+' ['+tag+']') if name else tag or 'Base Material'


def labels(geometry,category='object',scene=None,instances=False):
    if instances:return [name(geometry,category,scene,str(identity)) for identity in geometry.get('instance_ids',[])]
    if category=='material' and geometry.get('face_materials'):
        return [material_name(tag,scene) for tag in geometry['face_materials']]
    return [name(geometry,category,scene)]


def userdata(geometry,lines,category='object',scene=None,instances=False):
    values=labels(geometry,category,scene,instances)
    if not values:raise ValueError('Cryptomatte instances require stable identities')
    import hashlib
    path='/modo/crypto/'+hashlib.sha256(json.dumps([values,instances]).encode()).hexdigest()[:24]
    rate=0 if instances else 3 if len(values)>1 else 1
    lines.append('UserData(%s) { ["float_key"] = "modo_object_id", ["float_values_0"] = %s, ["rate"] = %d }'%(string(path),array(number(float_id(value)) for value in values),rate))
    return 'UserData(%s)'%string(path)


def metadata(geometries,lines,crypto=False,scene=None):
    from .working_space import label
    names=['MoonRayForModo/workingSpace'];types=['string'];values=[label((scene or {}).get('asset_settings',{}))]
    if crypto:
        cat=category(scene or {});manifest={}
        for g in geometries:
            if g.get('kind')=='vdb':continue
            entries=labels(g,cat,scene,instances='instances' in g and cat!='material')
            for value in entries:manifest[value]='%08x'%hash32(value)
        prefix='cryptomatte/'+('%08x'%hash32('Cryptomatte'))[:7]+'/'
        fields={'name':'Cryptomatte','hash':'MurmurHash3_32','conversion':'uint32_to_float32','manifest':json.dumps(manifest,separators=(',',':'),sort_keys=True)}
        for key,value in fields.items():names.append(prefix+key);types.append('string');values.append(value)
        names.append('MoonRayForModo/cryptomatteCategory');types.append('string');values.append(cat)
    lines.append('Metadata("/modo/outputMetadata") '+array(array(string(v) for v in row) for row in zip(names,types,values)))
