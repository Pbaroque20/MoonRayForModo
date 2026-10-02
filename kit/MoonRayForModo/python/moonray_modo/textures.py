"""Cached, tiled/mipmapped texture preparation for MoonRay's ImageMap."""
import hashlib
import re
import shutil
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from . import native

EFFECTS = {'diffCol': 'diffuseColor', 'specCol': 'specularColor',
           'rough': 'roughness', 'metallic': 'metallic', 'lumiCol': 'emissiveColor',
           'coatAmt': 'clearcoat', 'coatRough': 'clearcoatRoughness',
           'tranAmt': 'transmission', 'tranCol': 'transmissionColor', 'tranRough': 'refractionRoughness',
           'normal':'normal', 'bump':'bump', 'diffAmt':'diffuseAmount',
           'specAmt':'specularAmount', 'groupMask':'layerMask', 'aniso':'anisotropy', 'lumiAmt':'emissiveAmount', 'dissolve':'presence',
           'subsCol':'subsurfaceColor', 'subsAmt':'subsurfaceAmount'}
COLOR_EFFECTS = {'diffCol', 'specCol', 'lumiCol', 'tranCol', 'subsCol'}

# Shader Tree effect identifiers differ from advancedMaterial channel names.
# Retain the short names in the snapshot format for existing exported scenes.
EFFECT_ALIASES = {'diffColor': 'diffCol', 'specColor': 'specCol',
                  'lumiColor': 'lumiCol', 'tranColor': 'tranCol',
                  'tranAmount': 'tranAmt', 'coatAmount': 'coatAmt',
                  'diffAmount': 'diffAmt', 'specAmount': 'specAmt', 'lumiAmount': 'lumiAmt',
                  'subsColor':'subsCol', 'subsAmount':'subsAmt'}


def source_tiles(source):
    source = Path(source).resolve()
    if '<UDIM>' not in source.name:
        return {0: source} if source.is_file() else {}
    if not source.parent.is_dir(): return {}
    pattern = re.compile('^' + re.escape(source.name).replace(re.escape('<UDIM>'), r'(1[0-9]{3})') + '$')
    return {int(match.group(1)): path for path in sorted(source.parent.iterdir())
            if path.is_file() for match in [pattern.match(path.name)] if match}


def prepare(source, srgb=False, mipmaps=True):
    if '<UDIM>' in str(source):
        tiles = source_tiles(source)
        if not tiles:
            raise ValueError('No UDIM tiles found: ' + str(source))
        signature = [(n, str(p), p.stat().st_size, p.stat().st_mtime_ns) for n,p in sorted(tiles.items())]
        digest = hashlib.sha256(repr((signature,srgb,mipmaps)).encode()).hexdigest()
        cache = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo/Textures' / digest
        cache.mkdir(parents=True, exist_ok=True)
        for tile,path in tiles.items():
            target = cache / ('tile.%d.tx' % tile)
            if not target.is_file():
                prepared = prepare(path, srgb, mipmaps)
                staged = target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
                try:
                    shutil.copyfile(prepared, staged)
                    staged.replace(target)
                finally:
                    if staged.exists(): staged.unlink()
        return str(cache/'tile.<UDIM>.tx')

    source = Path(source).resolve()
    stat = source.stat()
    key_data = '%s|%d|%d|%s|v3-alpha-color-conversion' % (source, stat.st_size, stat.st_mtime_ns, srgb)
    if not mipmaps:
        key_data += '|no-mips'
    key = hashlib.sha256(key_data.encode('utf-8')).hexdigest()
    cache = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo/Textures'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (key + '.tx')
    if target.is_file() and target.stat().st_size:
        return str(target)
    runtime = Path(native.default_runtime())
    converter = runtime / 'maketx.exe'
    if not converter.is_file():
        raise ValueError('Texture conversion needs maketx.exe in the MoonRay runtime. Reinstall the kit.')
    staged = cache / (key + '-' + uuid.uuid4().hex + '.tx')
    args = [str(converter), '--oiio', '--threads', '2', '-d', 'float', '--unpremult']
    if not mipmaps:
        args += ['--nomipmap']
    if srgb:
        args += ['--colorconvert', 'sRGB', 'linear']
    args += ['-o', str(staged), str(source)]
    try:
        result = subprocess.run(args, env=native.environment(runtime), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=120,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not staged.is_file():
            raise ValueError('Texture conversion failed for %s: %s' % (source.name, result.stdout[-1200:]))
        staged.replace(target)
    finally:
        if staged.exists():
            staged.unlink()
    return str(target)


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
