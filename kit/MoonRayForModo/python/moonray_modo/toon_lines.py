"""A final render's Toon lines with their own alpha (issue 134).

MoonRay gives a display filter's picture as R, G and B alone. A Toon filter set to Lines only is white on black: how much
of each pixel its lines cover. Once the render is written, its channels <name>.R, .G and .B become the lines in their ink
colour, premultiplied as the rest of the render is, and <name>.A what they cover, in whichever part of the EXR holds
them. Every other channel, part, header, data type and the compression stay as they were.
"""
import subprocess
import uuid
from pathlib import Path


def wanted(snapshot):
    """{channel prefix: ink colour} of the scene's Toon filters that give their lines alone."""
    from . import entities
    found = {}
    for entity in entities.display_filters(snapshot or {}):
        colour = entities.lines_colour(entity)
        if colour is not None and entity.get('name'):
            found[entity['name']] = colour
    return found


def arguments(parts, lines, source, target):
    """The image tool's arguments that rewrite source as target with the lines' alpha, or None where no part of it
    holds such lines (or they have an alpha already). parts: each part's channel names (composite_output.channel_parts)."""
    args, changed = [], False
    for index, names in enumerate(parts):
        args += ['--no-autopremult', str(source), '--subimage', str(index)]
        held = [prefix for prefix in lines if all('%s.%s' % (prefix, c) in names for c in 'RGB') and '%s.A' % prefix not in names]
        if held:
            changed = True
            channels = list(names) + ['%s.A=%s.R' % (prefix, prefix) for prefix in held]
            scale = []
            for name in names:
                prefix, _, channel = name.rpartition('.')
                scale.append(lines[prefix]['RGB'.index(channel)] if prefix in held and channel in ('R', 'G', 'B') else 1.0)
            scale += [1.0] * len(held)
            args += ['--ch', ','.join(channels), '--mulc', ','.join('%.6g' % float(v) for v in scale)]
        if index:
            args += ['--siappend']
    if not changed:
        return None
    return args + ['-o', str(target)]


def add_alpha(runtime, path, snapshot):
    """Give the Toon lines of the render saved at path their alpha, in place. Returns the prefixes changed (none: the
    file is left alone). Raises RuntimeError where the image tool could not."""
    from . import native
    from .composite_output import channel_parts
    lines = wanted(snapshot)
    if not lines:
        return []
    path = Path(path)
    parts = channel_parts(runtime, path)
    staged = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp.exr')
    args = arguments(parts, lines, path, staged)
    if args is None:
        return []
    try:
        done = subprocess.run([str(Path(runtime) / 'oiiotool.exe')] + args, env=native.environment(runtime), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode or not staged.is_file():
            raise RuntimeError(done.stdout.decode('utf-8', errors='replace')[-300:])
        staged.replace(path)
    finally:
        if staged.exists():
            staged.unlink()
    return sorted(prefix for prefix in lines if any(all('%s.%s' % (prefix, c) in names for c in 'RGB') for names in parts))
