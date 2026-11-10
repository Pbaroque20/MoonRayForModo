"""Cached, tiled/mipmapped texture preparation for MoonRay's ImageMap."""
from .cache_folder import root as cache_root
import hashlib
import re
import shutil
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
_policy=ContextVar("moonray_texture_policy",default={})
_collector=ContextVar("moonray_asset_collector",default=None)
# The textures a scene names that are not on this machine, while a scene is written (noting_missing).
_missing=ContextVar("moonray_missing_textures",default=None)

@contextmanager
def configuration(settings):
    from .assets import values
    token=_policy.set(values(settings))
    try:yield
    finally:_policy.reset(token)

@contextmanager
def collect_files(files):
    token=_collector.set(files)
    try:yield
    finally:_collector.reset(token)

@contextmanager
def noting_missing(found):
    """While a scene is written, the textures it names that cannot be found are listed in found."""
    token=_missing.set(found)
    try:yield
    finally:_missing.reset(token)

def missing(source):
    """Whether a texture (or every tile of a <UDIM> set) is not on this machine: the scene is then written with an
    empty texture path in its place, rather than not at all."""
    try:return not source_tiles(source)
    except OSError:return True

def note_missing(source):
    found=_missing.get()
    if found is not None and str(source) not in found:found.append(str(source))

def register(path):
    files=_collector.get()
    if files is not None:files.append(str(path))
    return str(path)

def asset_path(source):
    source=Path(source)
    # Windows Python 3.9 rejects the UDIM token as an actual file name.
    # Resolve its directory (including short-path aliases), retaining the pattern.
    return source.parent.resolve()/source.name if '<UDIM>' in source.name else source.resolve()


def color_rule(source):
    key=str(asset_path(source)).casefold()
    return next((r["space"] for r in _policy.get().get("rules",[]) if str(asset_path(r["path"])).casefold()==key),"")

def prepare(source,srgb=False,mipmaps=True,color_space="",light=False):
    return register(_prepare(source,srgb,mipmaps,color_space,light))

from . import native

INTERNAL_EFFECTS = {'driverA','driverB','driverC','driverD'}

EFFECTS = {**{key:key for key in INTERNAL_EFFECTS}, 'diffCol': 'diffuseColor', 'specCol': 'specularColor',
           'rough': 'roughness', 'metallic': 'metallic', 'lumiCol': 'emissiveColor',
           'coatAmt': 'clearcoat', 'coatRough': 'clearcoatRoughness',
           'tranAmt': 'transmission', 'tranCol': 'transmissionColor', 'tranRough': 'refractionRoughness',
           'normal':'normal', 'normalCoat':'coatNormal', 'coatBump':'coatBump', 'diffRough':'diffuseRoughness', 'bump':'bump', 'diffAmt':'diffuseAmount',
           'specAmt':'specularAmount', 'layerMask':'singleLayerMask', 'groupMask':'layerMask', 'aniso':'anisotropy', 'lumiAmt':'emissiveAmount', 'dissolve':'presence',
           'subsCol':'subsurfaceColor', 'subsAmt':'subsurfaceAmount', 'ior':'ior',
           # Not material attributes: displacement goes to the material's NormalDisplacement, and a stencil
           # into its presence (graph.bindings).
           'displace':'_displacement', 'stencil':'_stencil'}
COLOR_EFFECTS = {'diffCol', 'specCol', 'lumiCol', 'tranCol', 'subsCol'}

# Shader Tree effect identifiers differ from advancedMaterial channel names.
# Retain the short names in the snapshot format for existing exported scenes.
EFFECT_ALIASES = {'diffColor': 'diffCol', 'specColor': 'specCol',
                  'lumiColor': 'lumiCol', 'tranColor': 'tranCol',
                  'tranAmount': 'tranAmt', 'coatAmount': 'coatAmt',
                  'diffAmount': 'diffAmt', 'specAmount': 'specAmt', 'lumiAmount': 'lumiAmt',
                  'subsColor':'subsCol', 'subsAmount':'subsAmt', 'anisotropic':'aniso'}


def source_tiles(source):
    source = asset_path(source)
    if '<UDIM>' not in source.name:
        return {0: source} if source.is_file() else {}
    if not source.parent.is_dir(): return {}
    pattern = re.compile('^' + re.escape(source.name).replace(re.escape('<UDIM>'), r'(1[0-9]{3})') + '$')
    return {int(match.group(1)): path for path in sorted(source.parent.iterdir())
            if path.is_file() for match in [pattern.match(path.name)] if match}


def color_conversion(source, srgb=False, color_space=""):
    """How an image's colours are taken to the renderer's linear space, as prepare takes them: (its colour space, the
    converter's arguments for it, a key for what decides it). The same arguments serve maketx and oiiotool."""
    policy=_policy.get();space=color_rule(source) or color_space
    aliases={"(default)":"","(none)":"raw","Linear":"linear","lin_rec709":"linear","srgb_texture":"sRGB"}
    space=aliases.get(space,space)
    if not space:space="sRGB" if srgb else "raw"
    custom=space not in ("sRGB","linear","raw")
    config=policy.get("config","")
    if custom and (not config or not Path(config).is_file()):raise ValueError("An input OCIO config is required for color space "+space)
    config_key=(str(Path(config).resolve()),Path(config).stat().st_mtime_ns) if custom else None
    transform_key=(space,config_key,policy.get("linear_space","Linear Rec.709 (sRGB)"))
    args=['--colorconfig',config,'--colorconvert',space,policy.get('linear_space','Linear Rec.709 (sRGB)')] if custom else          ['--colorconvert','sRGB','linear'] if space=='sRGB' else []
    return space,args,transform_key


def _prepare(source, srgb=False, mipmaps=True, color_space="", light=False):
    space,colour_args,transform_key=color_conversion(source,srgb,color_space)
    if '<UDIM>' in str(source):
        tiles = source_tiles(source)
        if not tiles:
            raise ValueError('No UDIM tiles found: ' + str(source))
        signature = [(n, str(p), p.stat().st_size, p.stat().st_mtime_ns) for n,p in sorted(tiles.items())]
        digest = hashlib.sha256(repr((signature,transform_key,mipmaps)).encode()).hexdigest()
        cache = cache_root() / 'Textures' / digest
        cache.mkdir(parents=True, exist_ok=True)
        from . import conversions
        for tile,path in tiles.items():
            target = cache / ('tile.%d.tx' % tile)
            if not target.is_file():
                def tile_work(path=path, target=target):
                    prepared = prepare(path, srgb, mipmaps, space)
                    staged = target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
                    try:
                        shutil.copyfile(prepared, staged)
                        staged.replace(target)
                    finally:
                        if staged.exists(): staged.unlink()
                conversions.run(str(target), tile_work)
        return str(cache/'tile.<UDIM>.tx')

    source = Path(source).resolve()
    if source.suffix.lower()=='.tx' and space in ('raw','linear') and mipmaps:
        # Already a texture made for the renderer, and nothing to change in its colours: it is used as it is.
        return str(source)
    stat = source.stat()
    key_data = repr((str(source),stat.st_size,stat.st_mtime_ns,transform_key,'v5-monochrome'))
    if not mipmaps:
        key_data += '|no-mips'
    if light:
        key_data += '|light'
    key = hashlib.sha256(key_data.encode('utf-8')).hexdigest()
    cache = cache_root() / 'Textures'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (key + '.tx')
    if target.is_file() and target.stat().st_size:
        return str(target)
    # Where the runtime's maketx is (native.tool: the chosen runtime, then the kit's), its folder the runtime it runs in.
    converter = native.tool('maketx.exe')
    runtime = converter.parent
    def convert():
        staged = cache / (key + '-' + uuid.uuid4().hex + '.tx')
        _convert(args + ['-o', str(staged), str(source)], staged, target, source, runtime)
    # A grey image (red, green and blue alike throughout) as one channel: renderers read it grey in all three as before, and
    # XPU2 holds a third of it. Not an image that lights the scene (light): MoonRay's lights read its first channel into red
    # alone (Distribution.cc's flip into three channels), and a grey environment lit a tester's scene red.
    args = [str(converter), '--oiio', '--threads', '2', '-d', 'float', '--unpremult'] + ([] if light else ['--monochrome-detect'])
    if not mipmaps:
        args += ['--nomipmap']
    args += colour_args
    # Inside a scene being written (conversions.together), alongside the scene's other textures.
    from . import conversions
    conversions.run(str(target), convert)
    return str(target)


def _convert(args, staged, target, source, runtime):
    try:
        result = subprocess.run(args, env=native.environment(runtime), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=600,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not staged.is_file():
            raise ValueError('Texture conversion failed for %s: %s' % (source.name, result.stdout[-1200:]))
        staged.replace(target)
    finally:
        if staged.exists():
            staged.unlink()


def resolve_scene_source(filename,scene_filename=None):
    """Recover relocated directory suffixes only when exactly one match exists."""
    text=str(filename).replace('\\','/')
    path=Path(text)
    folder=Path(scene_filename).parent if scene_filename else None
    direct=(folder/path) if folder and not path.is_absolute() else path
    if source_tiles(direct): return direct,False
    if folder is None: return direct,False
    parts=[p for p in text.split('/') if p and p not in ('.','..') and ':' not in p]
    candidates={}
    # Preserve at least the immediate parent directory, e.g. textures/body.png.
    # Do not recursively search drives or guess from a basename alone.
    for count in range(2,len(parts)+1):
        candidate=folder.joinpath(*parts[-count:])
        if source_tiles(candidate): candidates[str(candidate.resolve()).casefold()]=candidate
    if len(candidates)>1:
        raise ValueError('Ambiguous relocated texture; relink the image in Modo: '+str(filename))
    return (next(iter(candidates.values())),True) if candidates else (direct,False)


# What a graph's parameter names when it names an image: a file ending as an image does, or a set of <UDIM> tiles.
GRAPH_IMAGE_SUFFIXES=('.jpg','.jpeg','.png','.tif','.tiff','.exr','.hdr','.tga','.tx','.bmp','.psd','.webp','.dds')


def graph_image_value(value):
    """Whether a node's parameter value is an image's path."""
    if not isinstance(value,str) or not value.strip():return False
    lowered=value.strip().lower()
    return lowered.endswith(GRAPH_IMAGE_SUFFIXES) or '<udim>' in lowered


def image_folders(scene):
    """The folders a scene's image clips are found in, as they are resolved for rendering (resolve_scene_source): where
    a node graph's image that is nowhere else is looked for by its name (resolve_graph_image)."""
    from .host import channel
    folders=[]
    for clip in scene.items('videoStill',superType=False):
        filename=channel(clip,'filename','')
        if not filename:continue
        try:path,_=resolve_scene_source(filename,getattr(scene,'filename',None))
        except (ValueError,OSError):continue
        try:found=bool(source_tiles(path))
        except OSError:found=False
        if found and str(path.parent).casefold() not in [str(f).casefold() for f in folders]:folders.append(path.parent)
    return folders


def resolve_graph_image(filename,scene_filename=None,folders=()):
    """A node graph's image found: (its path, how) where how is None where it is where the graph says, 'relocated' where
    its last folders are found beside the scene (resolve_scene_source, as image clips are), and 'same name' where a file
    of its name is in exactly one of folders, the folders the scene's own images are in (image_folders); (None, why)
    where it is not found, or found in more than one of them."""
    try:
        path,recovered=resolve_scene_source(filename,scene_filename)
    except ValueError as exc:
        return None,str(exc)
    try:
        if source_tiles(path):return path,('relocated' if recovered else None)
    except OSError:
        pass
    name=Path(str(filename).replace('\\','/')).name
    if not name:return None,'no file name'
    matches={}
    for folder in folders:
        candidate=Path(folder)/name
        try:
            if source_tiles(candidate):matches[str(candidate).casefold()]=candidate
        except OSError:
            continue
    if len(matches)==1:return next(iter(matches.values())),'same name'
    if len(matches)>1:return None,'a file of its name is in more than one of the scene\'s image folders: '+', '.join(str(p.parent) for p in matches.values())
    return None,'not found'


def relink_graph(graph,scene_filename=None,folders=()):
    """The graph with each image a node names that is not where it says found as resolve_graph_image finds it: (the
    graph, a copy only where something changed, and [(node, parameter, old, new, how)])."""
    if not isinstance(graph,dict) or not isinstance(graph.get('nodes'),dict):return graph,[]
    changes=[]
    nodes=None
    for key,node in graph['nodes'].items():
        parameters=node.get('parameters') if isinstance(node,dict) else None
        if not isinstance(parameters,dict):continue
        for name,value in parameters.items():
            if not graph_image_value(value):continue
            found,how=resolve_graph_image(value,scene_filename,folders)
            if found is None or how is None:continue
            new=str(found).replace('\\','/')
            if nodes is None:nodes=dict(graph['nodes'])
            node=nodes[key]=dict(nodes[key]);node['parameters']=dict(node['parameters']);node['parameters'][name]=new
            changes.append((key,name,value,new,how))
    return (dict(graph,nodes=nodes) if nodes is not None else graph),changes


def missing_graph_images(graph,scene_filename=None,folders=()):
    """[(node, parameter, path as the graph has it, what it would be relinked to or None, how or why)] for each image a
    graph names that is not where it says: for Relink Images."""
    found=[]
    if not isinstance(graph,dict) or not isinstance(graph.get('nodes'),dict):return found
    for key,node in graph['nodes'].items():
        parameters=node.get('parameters') if isinstance(node,dict) else None
        if not isinstance(parameters,dict):continue
        for name,value in parameters.items():
            if not graph_image_value(value):continue
            path,how=resolve_graph_image(value,scene_filename,folders)
            if path is not None and how is None:continue
            found.append((key,name,value,None if path is None else str(path).replace('\\','/'),how))
    return found
