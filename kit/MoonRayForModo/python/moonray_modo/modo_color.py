"""Modo's own colour management, for a preview shown as Modo would show it.

A Modo scene names an OCIO configuration (one of Modo's own, or one added in its system preferences), the colour space
its renders are in, and the colour space its Final Color Output is viewed in. Read here on Modo's main thread, each
time a scene is read for a render, and kept: the display code, which also runs where Modo may not be asked anything,
takes what was last read.
"""
import re
from pathlib import Path

# What was last read: {'config': path of the configuration, 'source': the scene's linear space, 'display': a display of
# the configuration, 'view': the view of it that is the output's colour space, 'name': the configuration's name}; None
# where the scene has no colour management or it could not be read.
RESOLVED = None
# What it was read from, so that a configuration's file is read again only when something of that has changed.
_FROM = None


def space(value):
    """The colour space in what Modo stores, 'nuke-default:sRGB' as 'sRGB'."""
    return str(value or '').split(':', 1)[-1].strip()


def views(text):
    """The displays of an OCIO configuration's text, each with its views as (name, colour space), in the order given;
    the display Modo would use is the first of active_displays where that is set, else the first there is."""
    displays, current, inside = {}, None, False
    for line in text.splitlines():
        if re.match(r'^displays\s*:', line):
            inside = True
            continue
        if inside:
            if line.strip() and not line.startswith((' ', '\t')):
                break
            named = re.match(r'^\s+([^\s:#][^:]*?)\s*:\s*$', line)
            if named:
                current = named.group(1).strip().strip('"\'')
                displays[current] = []
                continue
            view = re.search(r'name\s*:\s*([^,}]+)\s*,\s*colorspace\s*:\s*([^,}]+)', line)
            if view and current is not None:
                displays[current].append((view.group(1).strip().strip('"\''), view.group(2).strip().strip('"\'')))
    active = re.search(r'^active_displays\s*:\s*\[([^\]]*)\]', text, re.M)
    order = [name.strip().strip('"\'') for name in active.group(1).split(',')] if active else []
    first = next((name for name in order if name in displays), next(iter(displays), None))
    return displays, first


def resolve(config, source, target):
    """What the display code needs to show a render through a configuration as Modo does: the scene's linear space to
    the view whose colour space is the output's. None where the configuration has no such view."""
    try:
        text = Path(config).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    displays, first = views(text)
    for display in ([first] if first else []) + [name for name in displays if name != first]:
        for name, held in displays[display]:
            if held == target or name == target:
                return {'config': str(config), 'source': source, 'display': display, 'view': name}
    return None


def refresh():
    """Read Modo's colour management for the scene that is open. On Modo's main thread only."""
    global RESOLVED, _FROM
    try:
        import lx
        import modo
        scene = modo.Scene()
        item = scene.sceneItem
        name = item.channel('ocioConfig').get()
        if not name or str(name).startswith('('):
            RESOLVED = _FROM = None
            return None
        service = lx.service.ColorMapping()
        config = next((service.ConfigFullPath(i) for i in range(service.ConfigCount()) if service.ConfigName(i) == name), '')
        if not config:
            RESOLVED = _FROM = None
            return None
        source = space(item.channel('defFloatColorspace').get()) or 'linear'
        target = ''
        for output in scene.items('renderOutput'):
            try:
                if output.channel('effect').get() != 'shade.color':
                    continue
                target = output.channel('colorspace').get()
                break
            except (LookupError, RuntimeError, AttributeError):
                continue
        if not target or str(target).startswith('(') or target == 'auto':
            target = item.channel('def8bitColorspace').get()
        read = (config, source, space(target))
        if read == _FROM:
            return RESOLVED
        held = resolve(config, source, space(target))
        RESOLVED = dict(held, name=str(name)) if held else None
        _FROM = read
    except Exception:
        RESOLVED = _FROM = None
    return RESOLVED
