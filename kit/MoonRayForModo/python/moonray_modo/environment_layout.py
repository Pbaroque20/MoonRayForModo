"""A latitude-longitude HDRI laid out for the engines as Modo shows it.

Modo's spherical projection along Y (an environment image layer, as tools/probe_cl_hdri_compass.py renders it through a
perspective camera) puts the image's middle (u 0.5) at +Z, u growing toward +X (u = 0.5 + atan2(x, z) / 2 pi, the
projection of coordinates.py). The engines are handed a plain image with its Texture Locator's world matrix, which
MoonRay's EnvLight (environments.emit), XPU2 (the same scene) and MoonLightIPR (moonlightipr_scene.environment_section)
each turn half a turn about the vertical: so placed, an image shows its middle at -Z, u growing toward +X
(u = 0.5 + atan2(x, -z) / 2 pi): Modo's picture mirrored front to back. Up to 0.5.6.2 every plain HDRI rendered so,
and a turn of it showed the mirror of Modo's turn: a sun set behind a backplate's car in Modo lit it from the front.

A mirror is not a turn, and MoonRay's EnvLight makes its transform a turn (Mat4f::orthonormalize): the image itself is
laid out anew, once, kept in the texture cache, its column u showing what Modo shows at 0.5 - u. Placed as before, it
then shows what Modo shows, in every engine, turned the way Modo turns it."""
import hashlib
import subprocess
import uuid
from pathlib import Path

from .cache_folder import root as cache_root

# Raised when the way the file is laid out changes (the file's name in the cache).
FORM = 'modo-layout-v1'


def oiiotool_arguments(width):
    """The image tool's steps from Modo's layout to the engines': mirrored left to right (u to 1 - u), then moved half its
    width (to 0.5 - u)."""
    return ['--flop', '--cshift', '+%d+0' % (int(width) // 2)]


def image(path):
    """The engines' copy of an environment image (path, Modo's layout), made once with the runtime's oiiotool and kept
    in the texture cache, named by the image's path, size and time: an HDR one (.hdr, .exr, .tx) as a float EXR, any
    other as a PNG of its own depth, so that how its colours are read does not change."""
    from . import native
    path = Path(path).resolve()
    stat = path.stat()
    key = hashlib.sha256(repr((str(path), stat.st_size, stat.st_mtime_ns, FORM)).encode('utf-8')).hexdigest()
    hdr = path.suffix.lower() in ('.exr', '.hdr', '.tx')
    folder = cache_root() / 'Textures'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (key + ('.exr' if hdr else '.png'))
    if target.is_file() and target.stat().st_size:
        return target
    tool = native.tool('oiiotool.exe')
    env = native.environment(tool.parent)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    info = subprocess.run([str(tool), '--info', str(path)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          timeout=600, creationflags=flags)
    import re
    found = re.search(r':\s*(\d+)\s*x\s*(\d+)', info.stdout or '')
    if info.returncode or not found:
        raise ValueError('Could not read the environment image %s: %s' % (path.name, (info.stdout or '')[-400:]))
    staged = folder / (key + '-' + uuid.uuid4().hex + target.suffix)
    try:
        # (A .tx's first subimage, its full size, alone.)
        result = subprocess.run([str(tool), str(path)] + oiiotool_arguments(int(found.group(1))) + (['-d', 'float'] if hdr else [])
                                + ['-o', str(staged)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600,
                                creationflags=flags)
        if result.returncode or not staged.is_file():
            raise ValueError('Could not lay out the environment image %s: %s' % (path.name, result.stdout[-600:]))
        staged.replace(target)
    finally:
        if staged.exists():
            staged.unlink()
    return target


def laid_out(entry):
    """A plain environment image entry (kind image, environments.collect or the Backplate's HDRI) with its file laid out
    for the engines (image), the file it was made from kept as laid_out_from; any other entry as it is. Where the file
    cannot be made, the entry as it is (the engines show it mirrored, as before)."""
    if entry.get('kind') != 'image' or entry.get('laid_out_from') or not entry.get('path'):
        return entry
    try:
        made = image(entry['path'])
        stat = made.stat()
    except (OSError, ValueError, subprocess.SubprocessError):
        return entry
    return dict(entry, path=str(made), mtime=stat.st_mtime_ns, size=stat.st_size, laid_out_from=str(entry['path']))
