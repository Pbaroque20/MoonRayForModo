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
    from .denoising import beside as named
    return named(path, 'composite')


def layout(info):
    """Each part's channels as (name, data type), in the file's order, from the image tool's --info -v of an EXR. Where
    its channels are not all of one type, the tool writes each one's after its name ("R (half)"): left on, the names of a
    16-bit render with a Cryptomatte were never found (its Environment background among them)."""
    import re
    parts, kinds = [], []
    for line in info.splitlines():
        if 'channel list:' in line:
            part = []
            for index, held in enumerate(name.strip() for name in line.split('channel list:', 1)[1].split(',') if name.strip()):
                typed = re.match(r'^(.*?)\s*\((\w+)\)$', held)
                if typed:
                    part.append((typed.group(1), typed.group(2)))
                else:
                    part.append((held, kinds[index] if index < len(kinds) else (kinds[0] if kinds else 'float')))
            parts.append(part)
            continue
        # A part's size line: "160 x 120, 8 channel, half/half/float/... openexr", or one type for them all.
        found = re.search(r'\b\d+ channels?, ([\w/]+) ', line)
        if found:
            kinds = found.group(1).split('/')
    return parts


def channel_layout(runtime, path):
    """Each part of an EXR as its channels' (name, data type), in the file's order: one list where it is not multi-part."""
    done = subprocess.run([str(Path(runtime) / 'oiiotool.exe'), '-a', '--info', '-v', str(path)], env=native.environment(runtime),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return layout(done.stdout.decode('utf-8', errors='replace'))


def channel_parts(runtime, path):
    """The names of the channels of each part of an EXR, in the file's order: one list where it is not multi-part."""
    return [[name for name, _ in part] for part in channel_layout(runtime, path)]


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
            # In its own file beside the render where it was written there (Cryptomatte in Its Own File).
            from .cryptomatte import kept_in
            frame = {'files': {cryptomatte_pick.buffer_of(scene, category) or 'cryptomatte': kept_in(rendered)}, 'runtime': runtime,
                     'snapshot': scene or {}}
            return cryptomatte_pick.matte_file(frame, category, named, held)
        graph, files = compositor.lowered(graph, files, matte)
        for key in files:
            channels.setdefault(key, ['--ch', 'R,G,B'])
        steps, result = compositor.jobs(graph, files, {key: 'beauty' for key in files}, held, channels=channels,
                                        composite=compositor.program(runtime))
        for args, target in steps:
            if args and args[0] == '@pfm':
                # A TIFF the image tool just wrote, made the PFM the compositor program reads (pfm_files).
                from .pfm_files import run_step
                try:
                    run_step(args, target)
                except (OSError, ValueError) as exc:
                    raise RuntimeError('The image tool could not make the composite: ' + str(exc))
                continue
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
