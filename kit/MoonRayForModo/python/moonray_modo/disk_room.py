"""Room on the drives a render writes to, and what the preview says of it.

A render writes as it goes: Modo's evaluated geometry read through a temporary file, the scene handed to the renderer
(in memory backed by Windows' paging file, else in the temporary folder), the Cache folder's geometry, textures and
seas, and the preview's pictures. A drive left without room holds a render up or ends it with an error that says nothing
of room (Modo's geometry reader's "basic_ios::clear: iostream error"): a tester's C: drive came to 90 MB free, and XPU2's
render of a car seemed to hang. The preview looks at the drives while it renders (panel._watch_room): one nearly full is
said among the notices, and a render that has shown nothing new for a while with a drive so, or that fails, is said to
be held up by it."""
import os
import shutil
import tempfile

# Below this a drive is nearly full: reading a heavy car alone writes about a gigabyte.
LOW_BYTES = 2 * 1024 ** 3
# How often the drives are looked at while a render is on (seconds), and how long a render may show nothing new, with a
# drive nearly full, before it is said to be held up for room.
EVERY = 5.0
HELD_UP = 20.0
# What an error says when a drive had no room: Python's and Windows' words, and a C++ stream's (Modo's geometry reader).
FULL_WORDS = ('no space left on device', 'not enough space on the disk', 'errno 28', 'winerror 112', 'disk is full',
              'paging file is too small', 'winerror 1455', 'basic_ios::clear')


def folders():
    """The folders a render writes to: the Cache folder, the temporary folder (the renderer's session and Modo's
    geometry reader write there), and Windows' own drive (its paging file holds what is handed over in memory)."""
    found = []
    try:
        from . import cache_folder
        found.append(str(cache_folder.root()))
    except Exception:
        pass
    found.append(tempfile.gettempdir())
    found.append((os.environ.get('SystemDrive') or 'C:') + os.sep)
    return found


def drive(path):
    """The drive a path is on, as Windows names it (C:), or the path itself where it has none."""
    name = os.path.splitdrive(os.path.abspath(path))[0]
    return name.upper() if name else path


def free(path):
    """The bytes free on the drive a path is on (the nearest folder of it there is), or None where it cannot be told."""
    probe = os.path.abspath(path)
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def short(extra=(), low=None):
    """The drives a render writes to (folders, and extra: an output folder) with less than low free (LOW_BYTES unless
    given), each once: [(drive, bytes free)], the fullest first. Empty where each has room, or where it cannot be told."""
    low = LOW_BYTES if low is None else low
    seen = {}
    for path in list(folders()) + [path for path in extra if path]:
        name = drive(path)
        if name in seen:
            continue
        seen[name] = free(path)
    return sorted(((name, room) for name, room in seen.items() if room is not None and room < low), key=lambda entry: entry[1])


def amount(room):
    """Bytes as a person reads them: 1.4 GB, or 90 MB under a tenth of a gigabyte."""
    if room >= 0.1 * 1024 ** 3:
        return '%.1f GB' % (room / 1024 ** 3)
    return '%d MB' % (room // 1024 ** 2)


def _drives(found):
    return ', '.join('%s (%s free)' % (name, amount(room)) for name, room in found)


def _remedy(found):
    names = ', '.join(name for name, _ in found)
    return 'Free some space on %s, or choose a Cache folder on another drive (MoonRay Preview Preferences > Cache folder).' % names


def nearly_full(found, renderer='XPU2'):
    """The notice for drives nearly full (short): said while a render is on."""
    return ('Low disk space: %s. %s writes the scene, its caches and the picture as it renders, and holds up or stops '
            'without room. %s' % (_drives(found), renderer, _remedy(found)))


def held_up(found, quiet, renderer='XPU2'):
    """The status for a render that has shown nothing new for quiet seconds with drives nearly full (short)."""
    return ('Low disk space: %s. Nothing new for %d s: %s cannot go on without room to write. %s'
            % (_drives(found), int(quiet), renderer, _remedy(found)))


def full_error(text):
    """Whether an error's text is one a drive with no room gives."""
    lowered = str(text).lower()
    return any(word in lowered for word in FULL_WORDS)


def failed(message, found, renderer='XPU2'):
    """A render's failure said with the room left, where a drive is nearly full (short): first what to do, then the
    error as the renderer gave it. The message as it was where each drive has room."""
    if not found:
        return message
    return 'Low disk space: %s. %s cannot write without room. %s (%s)' % (_drives(found), renderer, _remedy(found), message)


def said(found, rendering, quiet, renderer='XPU2'):
    """What the preview says of the room left, while it renders: (notice, status). The notice for drives nearly full,
    the status where the render has also shown nothing new for HELD_UP seconds (quiet), else None for either."""
    if not found or not rendering:
        return None, None
    if quiet >= HELD_UP:
        message = held_up(found, quiet, renderer)
        return message, message
    return nearly_full(found, renderer), None
