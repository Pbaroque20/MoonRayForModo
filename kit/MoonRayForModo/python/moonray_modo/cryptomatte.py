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

def name(geometry):
    from .lighting import owner
    return geometry.get('name','Object')+' ['+owner(geometry)+']'

def userdata(geometry,lines):
    label=name(geometry);path='/modo/crypto/'+str(hash32(label))
    lines.append('UserData(%s) { ["float_key"] = "modo_object_id", ["float_values_0"] = {%s}, ["rate"] = 1 }'%(string(path),number(float_id(label))))
    return 'UserData(%s)'%string(path)

def metadata(geometries,lines,crypto=False):
    names=['MoonRayForModo/workingSpace'];types=['string'];values=['linear Rec.709']
    if crypto:
        manifest={name(g):'%08x'%hash32(name(g)) for g in geometries if g.get('kind')!='vdb'}
        prefix='cryptomatte/'+('%08x'%hash32('Cryptomatte'))[:7]+'/'
        fields={'name':'Cryptomatte','hash':'MurmurHash3_32','conversion':'uint32_to_float32','manifest':json.dumps(manifest,separators=(',',':'),sort_keys=True)}
        for key,value in fields.items():names.append(prefix+key);types.append('string');values.append(value)
    lines.append('Metadata("/modo/outputMetadata") '+array(array(string(v) for v in row) for row in zip(names,types,values)))
