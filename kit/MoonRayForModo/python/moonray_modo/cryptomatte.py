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

def bits(value):
    """An ID as the bits of the float it is written as: one that would be no number, or too small for one, is moved off."""
    value&=0xffffffff;exponent=(value>>23)&255
    return value^(1<<23) if exponent in (0,255) else value


def as_float(value):
    return struct.unpack('<f',struct.pack('<I',bits(value)))[0]


def float_id(name):
    return as_float(hash32(name))


def own(scene,category,key):
    """The Cryptomatte name and ID an object (by item) or a material (by tag) is given, {'name', 'id'}; empty where none."""
    if category=='material':
        material=(scene or {}).get('materials',{}).get(key,{})
        # A material made of layers is called what its top-most layer given a name is.
        for held in [material]+list(reversed(material.get('material_stack') or [])):
            if held.get('crypto_name') or held.get('crypto_id'):return {'name':held.get('crypto_name') or '','id':int(held.get('crypto_id') or 0)}
        return {}
    return ((scene or {}).get('cryptomatte_objects') or {}).get(str(key).split('|')[0]) or {}


def value(label,category,scene,key):
    """The ID a matte is written with: the number it is given, else the hash of its name, as the bits of its float."""
    number=int(own(scene,category,key).get('id') or 0) if key is not None else 0
    return bits(number if number>0 else hash32(label))

def enabled(scene):return any(v.get('kind')=='cryptomatte' for v in scene.get('custom_aovs',[]))

def multiple(scene):return sum(v.get('kind')=='cryptomatte' for v in scene.get('custom_aovs',[]))>1


def userdata_set(geometry,lines,scene,instances=False):
    cats=('object','material','asset') if multiple(scene) else (category(scene),)
    return [userdata(geometry,lines,cat,scene,instances) for cat in cats if not (instances and cat=='material')]


def instance_userdata(geometry,lines,scene):
    return ', '.join(userdata_set(geometry,lines,scene,instances=True))


def category(scene):
    return next((v.get('category','object') for v in scene.get('custom_aovs',[]) if v.get('kind')=='cryptomatte'),'object')


def volumes():
    """Whether fog has mattes of its own (MoonRay with the plugin's patch, and the preference on)."""
    from .native import crypto_volumes
    return crypto_volumes()


def owner_of(geometry,identity=None):
    from .lighting import owner
    return identity or owner(geometry)


def name(geometry,category='object',scene=None,identity=None):
    item=owner_of(geometry,identity)
    # Fog given no material is its own matte in the material category, not the scene's base material.
    if category=='material' and not geometry.get('material') and (geometry.get('kind')=='vdb' or geometry.get('volume')):category='object'
    if category=='material':return material_name(geometry.get('material',''),scene)
    if category=='asset':return (scene or {}).get('production',{}).get('objects',{}).get(item.split('|')[0],{}).get('asset_label') or item
    return own(scene,'object',item).get('name') or geometry.get('name','Object')+' ['+item+']'


def material_name(tag,scene):
    given=own(scene,'material',tag).get('name')
    if given:return given
    material=(scene or {}).get('materials',{}).get(tag,{})
    name=material.get('name')
    return (name+' ['+tag+']') if name else tag or 'Base Material'


def entries(geometry,category='object',scene=None,instances=False):
    """The mattes a geometry makes in a category, [(name, ID, what it is of)]: the item for an object, the material's tag
    for a material, and None for an asset, which has no ID of its own to give."""
    if instances:
        keys=[str(identity) for identity in geometry.get('instance_ids',[])]
        return [(name(geometry,category,scene,key),value(name(geometry,category,scene,key),category,scene,key),key) for key in keys]
    if category=='material':
        fog=not geometry.get('material') and (geometry.get('kind')=='vdb' or geometry.get('volume'))
        if not fog:
            tags=geometry.get('face_materials') or [geometry.get('material','')]
            return [(material_name(tag,scene),value(material_name(tag,scene),'material',scene,tag),tag) for tag in tags]
        category='object'
    key=owner_of(geometry) if category=='object' else None
    label=name(geometry,category,scene)
    return [(label,value(label,category,scene,key),key)]


def labels(geometry,category='object',scene=None,instances=False):
    if instances:return [name(geometry,category,scene,str(identity)) for identity in geometry.get('instance_ids',[])]
    if category=='material' and geometry.get('face_materials'):
        return [material_name(tag,scene) for tag in geometry['face_materials']]
    return [name(geometry,category,scene)]


def userdata(geometry,lines,category='object',scene=None,instances=False):
    found=entries(geometry,category,scene,instances)
    if not found:raise ValueError('Cryptomatte instances require stable identities')
    values=[label for label,_,_ in found]
    import hashlib
    key='modo_'+category+'_id' if multiple(scene or {}) else 'modo_object_id'
    path='/modo/crypto/'+hashlib.sha256(json.dumps([key,values,instances]).encode()).hexdigest()[:24]
    rate=0 if instances else 3 if len(values)>1 else 1
    lines.append('UserData(%s) { ["float_key"] = %s, ["float_values_0"] = %s, ["rate"] = %d }'%(string(path),string(key),array(number(as_float(held)) for _,held,_ in found),rate))
    return 'UserData(%s)'%string(path)


def mattes(geometries,category,scene):
    """Every matte the geometries make in a category, {name: ID}: what the manifest lists and the preview picks from."""
    found={}
    for g in geometries:
        if g.get('kind')=='vdb' and not volumes():continue
        for label,held,_ in entries(g,category,scene,instances='instances' in g and category!='material'):found[label]=held
    return found


def owners(geometries,category,scene):
    """What each matte is of, {name: [item or material tag]}: what clicking it selects in Modo."""
    found={}
    for g in geometries:
        for label,_,key in entries(g,category,scene,instances='instances' in g and category!='material'):
            if key is not None and key not in found.setdefault(label,[]):found[label].append(key)
    return found


def metadata(geometries,lines,crypto=False,scene=None,category_override=None):
    from .working_space import label
    names=['MoonRayForModo/workingSpace'];types=['string'];values=[label((scene or {}).get('asset_settings',{}))]
    if crypto:
        cat=category_override or category(scene or {})
        manifest={label:'%08x'%held for label,held in mattes(geometries,cat,scene).items()}
        prefix='cryptomatte/'+('%08x'%hash32('Cryptomatte'))[:7]+'/'
        fields={'name':'Cryptomatte','hash':'MurmurHash3_32','conversion':'uint32_to_float32','manifest':json.dumps(manifest,separators=(',',':'),sort_keys=True)}
        for key,value in fields.items():names.append(prefix+key);types.append('string');values.append(value)
        names.append('MoonRayForModo/cryptomatteCategory');types.append('string');values.append(cat)
    path='/modo/outputMetadata'+('/'+category_override if category_override else '')
    lines.append('Metadata('+string(path)+') '+array(array(string(v) for v in row) for row in zip(names,types,values)))
