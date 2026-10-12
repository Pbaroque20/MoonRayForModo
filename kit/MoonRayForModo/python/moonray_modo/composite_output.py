"""The compositor's picture of a render written to a file: saved beside the EXR, as the denoised copy is.

A render to a file keeps its buffers as channels of the one EXR, where a preview keeps each as a file of its own; so
the graph's buffers are found here by the names of the EXR's channels. The same graph and the same nodes as the
preview's Composite buffer (compositor.py).
"""
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from . import compositor, native


def beside(path):
    """Where the composite of a render saved at path is written."""
    path = Path(path)
    return path.with_name(path.stem + '.composite.exr')


def channel_names(runtime, path):
    """The names of an EXR's channels, in the file's order."""
    done = subprocess.run([str(Path(runtime) / 'oiiotool.exe'), '--info', '-v', str(path)], env=native.environment(runtime),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for line in done.stdout.decode('utf-8', errors='replace').splitlines():
        if 'channel list:' in line:
            return [name.strip() for name in line.split('channel list:', 1)[1].split(',') if name.strip()]
    return []


def selection(key, names):
    """What picks a buffer out of the EXR's channels as three numbers a pixel, or None where the file has none of
    that name."""
    if key == 'beauty':
        return 'R,G,B' if all(c in names for c in 'RGB') else None
    parts = [key + '.' + c for c in 'RGB']
    if all(part in names for part in parts):
        return ','.join(parts)
    pair = [key + '.' + c for c in ('R', 'G')]
    if all(part in names for part in pair):
        return ','.join(pair) + ',B=0'
    for single in (key, key + '.R', key + '.Y', key + '.Z', key + '.A'):
        if single in names:
            return 'R=%s,G=%s,B=%s' % (single, single, single)
    return None


def write(runtime, graph, rendered, denoised=None):
    """Make the composite of the render saved at `rendered` and write it beside it. Returns the file written, or None
    where the graph does nothing. Raises ValueError where the graph asks for what the render has not, and OSError or
    RuntimeError where it cannot be made or written."""
    if compositor.trivial(graph):
        return None
    runtime, rendered = Path(runtime), Path(rendered)
    names = channel_names(runtime, rendered)
    files, channels = {}, {}
    for key in compositor.buffers(graph):
        if key == 'denoised_beauty':
            if denoised is None or not Path(denoised).is_file():
                raise ValueError('The graph takes the denoised beauty, and this render was not denoised')
            files[key] = Path(denoised); channels[key] = ['--ch', 'R,G,B']
            continue
        chosen = selection(key, names)
        if chosen is None:
            raise ValueError('The render has no %s buffer for the compositor to take' % key)
        files[key] = rendered; channels[key] = ['--ch', chosen]
    files.setdefault('beauty', rendered); channels.setdefault('beauty', ['--ch', 'R,G,B'])
    with tempfile.TemporaryDirectory(prefix='MoonRayComposite-') as held:
        steps, result = compositor.jobs(graph, files, {key: 'beauty' for key in files}, held, channels=channels)
        for args, target in steps:
            done = subprocess.run([str(runtime / 'oiiotool.exe')] + args, env=native.environment(runtime), stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if done.returncode or not Path(target).is_file():
                raise RuntimeError('The image tool could not make the composite: ' + done.stdout.decode('utf-8', errors='replace')[-300:])
        destination = beside(rendered)
        staged = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            shutil.copyfile(str(result), str(staged)); staged.replace(destination)
        finally:
            if staged.exists():
                staged.unlink()
    return destination
