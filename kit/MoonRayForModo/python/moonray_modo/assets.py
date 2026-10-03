"""Input color policy, asset inventory and self-contained RDLA packages."""
import copy,hashlib,json,os,re,shutil,tempfile
from pathlib import Path

# Modo channel graphs evaluate in Rec.709. Renderer-facing colors may use AP1.
# Input OCIO targets name the Rec.709 graph space, not the chosen render primaries.
def values(settings):
    v=dict(settings);v.setdefault('working_space','rec709')
    if v['working_space'] not in ('rec709','acescg'):raise ValueError('Choose linear Rec.709 or ACEScg working primaries')
    v.setdefault('config','');v.setdefault('linear_space','Linear Rec.709 (sRGB)');v.setdefault('texture_cache_mb',4000);v.setdefault('rules',[])
    v['texture_cache_mb']=int(v['texture_cache_mb'])
    if not 64<=v['texture_cache_mb']<=131072:raise ValueError('Texture cache must be between 64 and 131072 MB')
    if len(v['rules'])>256:raise ValueError('Use at most 256 input color rules')
    for rule in v['rules']:
        if not rule.get('path') or not rule.get('space'):raise ValueError('Color rules need a file path and input color space')
    return v

def paths(value):
    found=set()
    def visit(node):
        if isinstance(node,dict):
            for key,child in node.items():
                if key not in ('warnings','production','preview_buffer_files','_recovery','vertices','vertices_close','faces','uvs','uv_sets','normals','radii','velocities','counts','instances','matrix','matrix_close','position'):visit(child)
        elif isinstance(node,(list,tuple)):
            for child in node:visit(child)
        elif isinstance(node,str) and (re.match(r'^[A-Za-z]:[/\\]',node) or node.startswith('//')) and Path(node).suffix:found.add(node)
    visit(value)
    for settings in value.get('production',{}).get('lights',{}).values() if isinstance(value,dict) else []:
        for key in ('cookie_file','filter_vdb'):visit(settings.get(key,''))
    return sorted(found)

def inventory(scene):
    from .textures import source_tiles
    result=[]
    for name in paths(scene):
        files=source_tiles(name)
        result.append({'path':name,'missing':not bool(files),'tiles':len(files),'bytes':sum(p.stat().st_size for p in files.values())})
    return result

def signature(scene):
    from .textures import source_tiles
    return [(name,[(tile,p.stat().st_size,p.stat().st_mtime_ns) for tile,p in source_tiles(name).items()]) for name in paths(scene)]

def package(scene,destination,width,height,samples,environment,asset_store=None):
    from . import rdla,textures
    from .working_space import label as working_label
    from .package_store import copy as collect_asset
    destination=Path(destination).expanduser().resolve()
    if destination.exists():raise ValueError('Choose a new package folder; existing folders are preserved')
    missing=[entry['path'] for entry in inventory(scene) if entry['missing']]
    if missing:raise ValueError('Missing assets:\n'+'\n'.join(missing))
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix=destination.name+'.partial-',dir=str(destination.parent)))
    try:
        converted=[]
        scene=copy.deepcopy(scene);scene.pop('_recovery',None);scene.pop('_denoise_guides',None);scene.pop('preview_buffer_files',None)
        # All emitted filenames, including generated environment maps and mipmaps,
        # are collected at the serializer boundary. No parser guesses Lua strings.
        with textures.collect_files(converted):text=rdla.scene_text(scene,width,height,samples,environment,'output/beauty.exr')
        (staging/'assets').mkdir();(staging/'output').mkdir();replacements={};manifest=[]
        for original in sorted(set(converted)):
            tiles=textures.source_tiles(original)
            if not tiles:raise ValueError('Missing prepared asset: '+original)
            digest=hashlib.sha256(str(original).encode()).hexdigest()[:16]
            subfolder=staging/'assets'/digest;subfolder.mkdir()
            for tile,path in tiles.items():
                target=subfolder/path.name;collect_asset(path,target,asset_store)
                manifest.append({'source':str(path),'file':target.relative_to(staging).as_posix(),'bytes':target.stat().st_size,'sha256':file_hash(target)})
            replacements[rdla.string(original)]=rdla.string('assets/'+digest+'/'+Path(original).name)
        # Geometry filenames do not pass through texture preparation.
        for geometry in scene.get('extra_geometry',[]):
            if geometry.get('kind')!='vdb':continue
            original=geometry['file'];digest=hashlib.sha256(original.encode()).hexdigest()[:16];subfolder=staging/'assets'/digest;subfolder.mkdir(exist_ok=True);target=subfolder/Path(original).name;collect_asset(original,target,asset_store)
            replacements[rdla.string(original)]=rdla.string(target.relative_to(staging).as_posix());manifest.append({'source':original,'file':target.relative_to(staging).as_posix(),'bytes':target.stat().st_size,'sha256':file_hash(target)})
        for old,new in replacements.items():text=text.replace(old,new)
        (staging/'scene.rdla').write_text(text,encoding='utf-8')
        display=dict(scene.get('display',{}))
        # LUTs are file assets; an OCIO config may refer to external files.
        for key in ('lut','config'):
            source=display.get(key)
            if not source:continue
            target=staging/'assets'/('display-'+Path(source).name);shutil.copy2(source,str(target));display[key]=target.relative_to(staging).as_posix()
            if key=='config':
                config=Path(source).read_text(encoding='utf-8');search=[Path(source).parent]
                match=re.search(r'^search_path:\s*(.+)$',config,re.M)
                if match:
                    for part in match.group(1).strip("'\"[] " ).split(':'):
                        if part.strip():search.append(Path(source).parent/os.path.expandvars(part.strip("'\" ")))
                def dependency(match):
                    raw=match.group(1).strip();name=raw.strip("'\"");expanded=os.path.expandvars(name)
                    found=next((folder/expanded for folder in search if (folder/expanded).is_file()),None)
                    if found is None:raise ValueError('Cannot package OCIO dependency '+name)
                    dest=staging/'assets'/('ocio-'+hashlib.sha256(str(found).encode()).hexdigest()[:12]+found.suffix);shutil.copy2(str(found),str(dest))
                    return 'src: '+dest.name
                config=re.sub(r'\bsrc:\s*([^,}\n]+)',dependency,config)
                config=re.sub(r'^search_path:.*$', 'search_path: .',config,flags=re.M);target.write_text(config,encoding='utf-8')
        listed={v['file'] for v in manifest}
        for path in (staging/'assets').rglob('*'):
            if path.is_file() and path.relative_to(staging).as_posix() not in listed:manifest.append({'file':path.relative_to(staging).as_posix(),'bytes':path.stat().st_size,'sha256':file_hash(path)})
        (staging/'manifest.json').write_text(json.dumps({'format':1,'working_space':working_label(scene.get('asset_settings',{})),'assets':manifest,'runtime_required':'MoonRayForModo matching native runtime','display':display},indent=2),encoding='utf-8')
        (staging/'README.txt').write_text('Open a command prompt in this folder. Set RDL2_DSO_PATH to the matching MoonRayForModo runtime, then run moonray.exe -in scene.rdla -out output/beauty.exr. Material texture inputs use the linear graph space and convert to render primaries at shader boundaries; prepared environment images already use render primaries. Display transforms are not baked into linear render outputs. This is a frame package; animated sequences must be packaged frame by frame.\n',encoding='utf-8')
        staging.rename(destination)
        return str(destination)
    except Exception:
        # Keep the failed package for inspection; never delete an unknown folder.
        raise

def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
