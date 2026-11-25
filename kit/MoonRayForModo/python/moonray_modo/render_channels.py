"""The render settings as channels of the Render item, so that Modo's Channels viewport lists them, its filter finds
them, and they can be keyed and linked as any channel.

Each setting of the Render item's MoonRay form (scene_settings.FIELDS, its buttons and its two camera choosers left
out) is a channel of the package PACKAGE, added to the Render item (lxserv/moonray_render_settings.py): mr_ and the
setting's key, holding what its control in the form shows (scene_settings.get): a switch, a whole number, a choice by
its place in the list, a number (Render Region's in percent), a colour, or text (a file's path, an OCIO name).

The scene's MoonRay tag stays, and stays complete: the form writes it as before, and older kits read it. What the
renders read (scene_settings()) is the tag with the channels over it (overlay), evaluated at the current time, so a
keyed setting changes over an animation. A channel left at its default (a text one empty) where the tag has not set
its setting is taken as not set: the few settings whose default is not fixed (the display's, remembered on this machine, and
MoonLightIPR's clamps, MoonRay's until set) keep following it.

What is not a channel: PBR Validity, a diagnostic of the MoonRay preferences (scene_settings.NOT_IN_FORM); the lists and records the form does not show as one control (Light Path Expressions and
their outputs, the per-object and per-light controls, the Camera Sequence's keys, the compositor's graph, the scene
variables), and the Render Camera and Dicing Camera, chosen among items (camera_choice). They stay in the tag alone.
"""
import copy
import json
from . import options, scene_settings

PACKAGE = 'moonray.renderSettings'
PREFIX = 'mr_'
# Kinds of setting and the kind of channel each is.
KINDS = {'bool': 'boolean', 'member': 'boolean', 'int': 'integer', 'choice': 'integer', 'float': 'float',
         'hex': 'color', 'file': 'string', 'text': 'string'}


def entries():
    """The settings that are channels, in the form's order."""
    return [entry for entry in scene_settings.FIELDS if entry['kind'] in KINDS and entry['path'] and entry['key'] not in scene_settings.NOT_IN_FORM]


def channel(entry):
    return PREFIX + entry['key']


def kind(entry):
    return KINDS[entry['kind']]


# Each group's name as the start of its settings' names in the Channels viewport, where they stand in one list: two
# settings may share a label (MoonRay's Sample Clamp and MoonLightIPR's), and some labels say little alone (Total).
SHORT_GROUPS = {'XPU Sampling': 'XPU', 'XPU2 Sampling': 'XPU2', 'XPU and XPU2 Outputs (AOVs)': 'AOV', 'MoonLightIPR Outputs (AOVs)': 'MoonLightIPR AOV',
                'Noise and Filtering': 'Noise', 'Camera Background': 'Background', 'Output Renders': 'Output',
                'Global Switches': 'Switches'}


def user_names():
    """{channel: name shown in the Channels viewport}: the group, shortened, and the setting's label."""
    names = {}
    for group, _, fields in scene_settings.GROUPS:
        short = SHORT_GROUPS.get(group, group)
        for entry in fields:
            if entry['kind'] not in KINDS or not entry['path'] or entry['key'] in scene_settings.NOT_IN_FORM or channel(entry) in names:
                continue
            label = entry['label']
            # A label that already starts with its group's name says it once (Render Region: Left, not Render Region:
            # Render Region).
            names[channel(entry)] = label if label.startswith(short) else '%s: %s' % (short, label)
    return names


def tips():
    """{channel: tooltip}: the setting's tip, and for a choice, which number is which (the Channels viewport shows the
    number)."""
    result = {}
    for entry in entries():
        tip = entry['tip']
        if entry['kind'] == 'choice':
            numbers = ', '.join('%d %s' % (i, label) for i, (label, _) in enumerate(entry['choices']))
            tip = (tip.rstrip('.') + '. ' if tip else '') + 'In the Channels viewport: ' + numbers
        if tip:
            result[channel(entry)] = tip
    return result


def fixed_complete():
    """complete() of a scene that has set nothing, with the defaults that are fixed: the display's as the kit ships
    them, not as last chosen on this machine."""
    from .display import DEFAULTS as display_defaults
    result = scene_settings.complete({})
    result['display'] = {key: value for key, value in display_defaults.items() if key != 'working_space'}
    return result


_DEFAULTS = {}


def defaults():
    """{key: the channel's default}: what the form shows for a scene that has set nothing."""
    if not _DEFAULTS:
        held = fixed_complete()
        for entry in entries():
            try:
                _DEFAULTS[entry['key']] = scene_settings.get(held, entry)
            except Exception:
                _DEFAULTS[entry['key']] = {'boolean': False, 'integer': 0, 'float': 0.0, 'color': [0.0, 0.0, 0.0], 'string': ''}[kind(entry)]
    return _DEFAULTS


def explicit(stored, entry):
    """Whether a scene's tag has set this setting itself (not left to complete's default)."""
    path = entry['path']
    if not isinstance(stored, dict) or path[0] not in stored:
        return False
    if len(path) == 1 or entry['kind'] == 'member' or isinstance(path[1], int):
        return True
    group = stored[path[0]]
    return isinstance(group, dict) and path[1] in group


def same(a, b):
    """Equal, numbers within a millionth (a float channel holds a single-precision-looking 0.3 as 0.30000001)."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, (bool, int, float)) and isinstance(b, (bool, int, float)):
        return a == b or abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)), abs(float(b)))
    return a == b


def wanted(stored):
    """{key: value} the channels are to hold for these tag settings: what the form shows, for each setting the tag has
    set itself. The others are left at their defaults, which read as not set."""
    held = scene_settings.complete(stored)
    result = {}
    for entry in entries():
        if explicit(stored, entry):
            try:
                result[entry['key']] = scene_settings.get(held, entry)
            except Exception:
                pass
    return result


def _converted(entry, value):
    """A channel's value as the tag keeps it, as put() converts a control's; None for one that cannot be."""
    kind_ = entry['kind']
    try:
        if kind_ == 'choice':
            index = int(value)
            return entry['choices'][index][1] if 0 <= index < len(entry['choices']) else None
        if kind_ == 'hex':
            return scene_settings.rgb_to_hex(list(value)[:3])
        if kind_ == 'float':
            low = entry['low'] if entry['low'] is not None else float('-inf')
            high = entry['high'] if entry['high'] is not None else float('inf')
            return min(high, max(low, float(value))) / entry['scale']
        if kind_ == 'int':
            low = entry['low'] if entry['low'] is not None else -2 ** 31
            high = entry['high'] if entry['high'] is not None else 2 ** 31 - 1
            return min(high, max(low, int(value)))
        if kind_ in ('bool', 'member'):
            return bool(value)
        return str(value).strip()
    except (TypeError, ValueError, IndexError):
        return None


def overlay(stored, values):
    """The tag's settings with the channels' values over them: values is {key: channel value}. A channel at its default
    where the tag has not set the setting is left out (not set). The tag's dict is not changed."""
    stored = stored if isinstance(stored, dict) else {}
    marks = defaults()
    base = None
    result = None
    denoising_changed = []
    for entry in entries():
        key = entry['key']
        if key not in values:
            continue
        value = values[key]
        # Not set: at its default, or, for text, empty (Modo's text channels start empty, whatever their default).
        if not explicit(stored, entry) and (same(value, marks.get(key)) or (kind(entry) == 'string' and value == '')):
            continue
        if base is None:
            base = scene_settings.complete(stored)
        try:
            if same(value, scene_settings.get(base, entry)):
                continue
        except Exception:
            pass
        converted = _converted(entry, value)
        if converted is None:
            continue
        if result is None:
            result = copy.deepcopy(stored)
        path = entry['path']
        if entry['kind'] == 'member' and path == scene_settings.CRYPTOMATTE_PATH:
            from .outputs import with_cryptomatte
            result[path[0]] = with_cryptomatte(result.get(path[0], base[path[0]]), entry['member'], converted)
            continue
        if entry['kind'] == 'member':
            held = list(result.get(path[0], base[path[0]]))
            if converted and entry['member'] not in held:
                held.append(entry['member'])
            elif not converted and entry['member'] in held:
                held.remove(entry['member'])
            result[path[0]] = held
            continue
        if len(path) == 1:
            result[path[0]] = converted
            continue
        if isinstance(path[1], int):
            group = list(result.get(path[0], base[path[0]]))
        elif path[0] == 'render':
            # The render group is kept whole (complete reads a partial one as uniform sampling).
            group = dict(base['render'], **(result.get('render') or {}))
        else:
            # One setting of the group alone: the rest stay not set, following their own defaults.
            group = dict(result.get(path[0]) or {}) if isinstance(result.get(path[0]), dict) else {}
        group[path[1]] = converted
        result[path[0]] = group
        if path[0] == 'denoising' and path[1] in ('smart', 'safe'):
            denoising_changed.append(path[1])
    if result is None:
        return stored
    if 'render' in result:
        render = dict(result['render'])
        # Adaptive sampling's fewest above its most, as a channel lets them be: the most raised to the fewest, where the
        # form would refuse it, rather than every render setting falling back to its default (complete).
        if render.get('min_adaptive_samples', 0) > render.get('max_adaptive_samples', 0):
            render['max_adaptive_samples'] = render['min_adaptive_samples']
        try:
            result['render'] = options.render_values(render)
        except ValueError:
            result['render'] = stored.get('render', {})
    for changed in denoising_changed:
        from .denoising import one_or_other
        result['denoising'] = one_or_other(dict(result['denoising']), changed)
    return result


def changed_channels(current, stored):
    """{key: value} of the channels to set so that they hold the tag settings stored: those it has set that differ
    from what the channels hold now (current, {key: value})."""
    return {key: value for key, value in wanted(stored).items() if not same(current.get(key), value)}


def key_of(text, values):
    """A key for overlay's result: the tag's text and the channels' values."""
    return (text, json.dumps(values, sort_keys=True, default=str))
