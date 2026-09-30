"""Cached, tiled/mipmapped texture preparation for MoonRay's ImageMap."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from . import native

EFFECTS = {'diffCol': 'diffuseColor', 'specCol': 'specularColor',
           'rough': 'roughness', 'metallic': 'metallic', 'lumiCol': 'emissiveColor',
           'coatAmt': 'clearcoat', 'coatRough': 'clearcoatRoughness',
           'tranAmt': 'transmission', 'tranCol': 'transmissionColor', 'tranRough': 'refractionRoughness'}
COLOR_EFFECTS = {'diffCol', 'specCol', 'lumiCol', 'tranCol'}


def prepare(source, srgb=False):
    source = Path(source).resolve()
    stat = source.stat()
    key = hashlib.sha256(('%s|%d|%d|%s|v1' %
        (source, stat.st_size, stat.st_mtime_ns, srgb)).encode('utf-8')).hexdigest()
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
    args = [str(converter), '--oiio', '--threads', '2', '-d', 'float']
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
