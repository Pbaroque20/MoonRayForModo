"""Device Management (Preferences > MoonRay > Device Management): the processors and graphics cards XPU2 finds, each
switched on or off.

XPU2's runtime lists them (moonray_xpu2 --list-devices): a processor group is known by its number, a graphics card by
its UUID, so a card keeps its switch when the cards are numbered otherwise. What is switched off is kept; a device
found for the first time is on. XPU2 is handed the cards and groups switched on (XPU2_CARD_LIST, XPU2_GROUP_LIST, by
the numbers it lists them under) and renders with the processor, the cards or both as some of each are on
(XPU2_SESSION_MODE). One device at least stays on.

Before Device Management, Preferences > MoonRay > XPU2 > Devices chose the processor, the graphics card or both; a
choice of one of them is taken over until a device is switched here."""
import os
import subprocess
import time
from pathlib import Path

# The slots the preferences page has: more devices than these still render, switched on.
CARD_SLOTS = 8
GROUP_SLOTS = 4

_listed = [0.0, None]


def _store():
    try:
        from PySide2 import QtCore
    except ImportError:
        return None
    from . import native
    return QtCore.QSettings('MoonRayForModo', native.settings_name())


def _get(key, default=''):
    store = _store()
    return default if store is None else store.value(key, default)


def _set(key, value):
    store = _store()
    if store is not None: store.setValue(key, value)


def parse(text):
    """--list-devices' lines: (groups, cards), each a list of dicts."""
    groups, cards = [], []
    for line in text.splitlines():
        part = line.rstrip('\r').split('\t')
        try:
            if part[0] == 'group' and len(part) >= 4:
                groups.append({'number': int(part[1]), 'processors': int(part[2]), 'name': part[3]})
            elif part[0] == 'card' and len(part) >= 5:
                cards.append({'index': int(part[1]), 'uuid': part[2], 'bytes': int(part[3]), 'name': part[4]})
        except ValueError:
            continue
    return groups, cards


def listed(again=False):
    """(groups, cards) as XPU2's runtime finds them, asked once a Modo session (again: asked now). Without a runtime:
    one group of this machine's processors, and no cards."""
    if _listed[1] is not None and not again:
        return _listed[1]
    from . import native
    exe = native.xpu2_runtime() / 'moonray_xpu2.exe'
    found = ([], [])
    if exe.is_file():
        env = dict(os.environ)
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'): env.pop(key, None)
        try:
            done = subprocess.run([str(exe), '--list-devices'], cwd=str(exe.parent), env=env, capture_output=True,
                                  timeout=30, creationflags=0x08000000)
            found = parse(done.stdout.decode('utf-8', 'replace'))
        except (OSError, subprocess.SubprocessError):
            pass
    if not found[0]:
        found = ([{'number': 0, 'processors': os.cpu_count() or 1, 'name': 'Processor'}], found[1])
    _listed[0], _listed[1] = time.monotonic(), found
    return found


def _off(key):
    return {v for v in str(_get(key, '') or '').split(',') if v}


def _chosen():
    return str(_get('devices/chosen', 'false')).lower() in ('true', '1')


def _former():
    """Preferences > MoonRay > XPU2 > Devices, as chosen before Device Management: 'both', 'gpu' or 'cpu'."""
    value = str(_get('xpu2/devices', 'both'))
    return value if value in ('both', 'gpu', 'cpu') else 'both'


def card_on(card):
    if not _chosen(): return _former() != 'cpu'
    return card['uuid'] not in _off('devices/off_cards')


def group_on(group):
    if not _chosen(): return _former() != 'gpu'
    return str(group['number']) not in _off('devices/off_groups')


def switch(kind, place, on):
    """Switch slot place of kind ('card' or 'group') on or off. Refused, with False, where it would leave no device on."""
    groups, cards = listed()
    devices = cards if kind == 'card' else groups
    if not 0 <= place < len(devices): return False
    now = {('card', c['uuid']): card_on(c) for c in cards}
    now.update({('group', str(g['number'])): group_on(g) for g in groups})
    key = (kind, devices[place]['uuid'] if kind == 'card' else str(devices[place]['number']))
    now[key] = bool(on)
    if not any(now.values()): return False
    # Kept as what is off, every device's switch at once (the choice before Device Management is taken over here); a
    # card off and not found now (taken out for a while) stays off.
    for what, found in (('card', {c['uuid'] for c in cards}), ('group', {str(g['number']) for g in groups})):
        off = (_off('devices/off_%ss' % what) - found) | {name for (k, name), value in now.items() if k == what and not value}
        _set('devices/off_%ss' % what, ','.join(sorted(off)))
    _set('devices/chosen', 'true')
    return True


def mode():
    """'both', 'gpu' or 'cpu': what XPU2 renders with by the devices on."""
    groups, cards = listed()
    gpu = any(card_on(c) for c in cards)
    cpu = any(group_on(g) for g in groups)
    return 'both' if gpu and cpu else 'gpu' if gpu else 'cpu'


def environment():
    """What XPU2 is started with for the devices on: the cards and groups, where any are off."""
    groups, cards = listed()
    env = {}
    if cards and not all(card_on(c) for c in cards):
        env['XPU2_CARD_LIST'] = ','.join(str(c['index']) for c in cards if card_on(c))
    if groups and not all(group_on(g) for g in groups):
        env['XPU2_GROUP_LIST'] = ','.join(str(g['number']) for g in groups if group_on(g))
    return env


def state():
    """What a session started with depends on: a session started otherwise is started again."""
    return (mode(),) + tuple(sorted(environment().items()))


def card_label(card):
    gb = card['bytes'] / float(1 << 30)
    return '%s, %.0f GB' % (card['name'], gb) if gb >= 1 else card['name']


def group_label(group, groups):
    threads = '%d threads' % group['processors']
    return '%s, %s' % (group['name'], threads) if len(groups) == 1 else '%s, group %d, %s' % (group['name'], group['number'], threads)


def summary():
    """One line for the page: what is found and what is on."""
    groups, cards = listed()
    on_cards = sum(1 for c in cards if card_on(c))
    on_groups = sum(1 for g in groups if group_on(g))
    said = ['%d of %d graphics card%s on' % (on_cards, len(cards), '' if len(cards) == 1 else 's') if cards else 'No NVIDIA graphics card found']
    said.append(('processor on' if on_groups else 'processor off') if len(groups) == 1 else '%d of %d processor groups on' % (on_groups, len(groups)))
    return ', '.join(said)
