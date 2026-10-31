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


def channel_parts(runtime, path):
    """The names of the channels of each part of an EXR, in the file's order: one list where it is not multi-part."""
    done = subprocess.run([str(Path(runtime) / 'oiiotool.exe'), '-a', '--info', '-v', str(path)], env=native.environment(runtime),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return [[name.strip() for name in line.split('channel list:', 1)[1].split(',') if name.strip()]
            for line in done.stdout.decode('utf-8', errors='replace').splitlines() if 'channel list:' in line]


def channel_names(runtime, path):
    """The names of an EXR's channels, in the file's order, of all its parts."""
    return [name for part in channel_parts(runtime, path) for name in part]


def part_of(key, parts):
    """Which part of an EXR holds a buffer: selection(key, part) finds it there."""
    return next((index for index, names in enumerate(parts) if selection(key, names) is not None), None)


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
    for single in ('A' if key == 'alpha' else key, key + '.R', key + '.Y', key + '.Z', key + '.A'):
        if single in names:
            return 'R=%s,G=%s,B=%s' % (single, single, single)
    return None


def write(runtime, graph, rendered, denoised=None, scene=None):
    """Make the composite of the render saved at `rendered` and write it beside it. Returns the file written, or None
    where the graph does nothing. Raises ValueError where the graph asks for what the render has not, and OSError or
    RuntimeError where it cannot be made or written. scene is what was rendered, for the names of Cryptomatte mattes."""
    if compositor.trivial(graph):
        return None
    runtime, rendered = Path(runtime), Path(rendered)
    parts = channel_parts(runtime, rendered)
    names = [name for part in parts for name in part]
    files, channels, elsewhere = {}, {}, {}
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
        if part_of(key, parts):elsewhere[key] = part_of(key, parts)
    files.setdefault('beauty', rendered); channels.setdefault('beauty', ['--ch', 'R,G,B'])
    with tempfile.TemporaryDirectory(prefix='MoonRayComposite-') as held:
        # What the compositor reads comes from a file's first part: a multi-part render's other parts are taken out for it.
        for key, index in elsewhere.items():
            files[key] = Path(held) / ('part-%d.exr' % index)
            subprocess.run([str(runtime / 'oiiotool.exe'), '--no-autopremult', str(rendered), '--subimage', str(index), '-d', 'float', '-o', str(files[key])],
                           env=native.environment(runtime), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        # The same program as the preview's Composite, where the runtime has it: the two always agree.
        # Each Cryptomatte node is a picture of its matte, from the Cryptomatte channels of the render's EXR.
        from . import cryptomatte_pick

        def matte(category, named):
            frame = {'files': {cryptomatte_pick.buffer_of(scene, category) or 'cryptomatte': rendered}, 'runtime': runtime, 'snapshot': scene or {}}
            return cryptomatte_pick.matte_file(frame, category, named, held)
        graph, files = compositor.lowered(graph, files, matte)
        for key in files:
            channels.setdefault(key, ['--ch', 'R,G,B'])
        steps, result = compositor.jobs(graph, files, {key: 'beauty' for key in files}, held, channels=channels,
                                        composite=compositor.program(runtime))
        for args, target in steps:
            command = args[1:] if args and args[0] == '@run' else [str(runtime / 'oiiotool.exe')] + args
            done = subprocess.run(command, env=native.environment(runtime), stdout=subprocess.PIPE,
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
