"""What the preview's pictures take in memory at the render's size, said in the MoonRay Terminal and among the notices.

The renderers hand their pictures to the preview whole, of any size (modo_shared_image.h, shared_image.py): each is the
render's width x height in float RGB, 12 bytes a pixel, so 94.9 MB at 4K, 379.7 MB at 8K and 3.0 GB at 16384 a side (MB
and GB of 1024, as Windows counts them). The
renderer holds one until the preview has taken it, and the preview its copy and the copy it shows (4 bytes a pixel);
a render stopped part way keeps its last three of the beauty and of the denoiser's two guides. Every picture's size is
said in the Terminal once a render (render._persistent_memory); a picture past PAST (the 64 MB pictures were once held
to) is said among the notices too, with the memory the machine has free, and as a warning where that is short."""
import ctypes
import time

# Past this a picture's memory is said among the notices: the size pictures were once held to, a 4K one past it.
PAST = 64 * 1024 ** 2
# How often the memory free is looked at again while pictures that size come (seconds).
EVERY = 5.0
# Memory is short when less is free than this many pictures and SPARE more: the renderer's, the preview's two copies
# and a stopped render's kept ones, and room for Modo and the render itself.
PICTURES = 12
SPARE = 2 * 1024 ** 3


def picture_bytes(width, height):
    """One picture as it is handed over: float RGB, 12 bytes a pixel."""
    return int(width) * int(height) * 12


def held_bytes(width, height):
    """What the pictures of one render take at most while it renders: the renderer's, the preview's copy, the copy shown
    (4 bytes a pixel), and a stopped render's last three of the beauty and its two guides."""
    one = picture_bytes(width, height)
    return one * 2 + int(width) * int(height) * 4 + one * 9


def free_bytes():
    """The machine's memory free (Windows' available physical memory), or None where it cannot be read."""
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong), ('available', ctypes.c_ulonglong),
                    ('page_total', ctypes.c_ulonglong), ('page_available', ctypes.c_ulonglong), ('virtual_total', ctypes.c_ulonglong),
                    ('virtual_available', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]
    try:
        status = Status()
        status.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.available)
    except Exception:
        return None


def size(value):
    """Bytes as an artist reads them: MB below a gigabyte, GB above."""
    value = float(value)
    return '%.1f GB' % (value / 1024 ** 3) if value >= 1024 ** 3 else '%.1f MB' % (value / 1024 ** 2)


def short(width, height, free):
    """Whether the memory free is short for pictures this size (PICTURES of them and SPARE more)."""
    return free is not None and free < picture_bytes(width, height) * PICTURES + SPARE


def terminal_line(width, height, free=None):
    """The Terminal's line for a render's pictures: their size, and the memory free."""
    line = 'Preview pictures %d x %d: %s each in memory, up to %s with the preview\'s copies' % (
        width, height, size(picture_bytes(width, height)), size(held_bytes(width, height)))
    if free is not None:
        line += '; %s of memory free' % size(free)
    return line + ('. Memory is short for pictures this size.' if short(width, height, free) else '.')


def notice(width, height, free=None):
    """The notice for pictures past PAST, a warning where memory is short for them; None for smaller ones."""
    if picture_bytes(width, height) <= PAST:
        return None
    one, held = size(picture_bytes(width, height)), size(held_bytes(width, height))
    if short(width, height, free):
        return ('Memory is short for this render\'s preview: each %d x %d picture takes %s, up to %s with the preview\'s copies, '
                'and %s is free. Close other programs, or render at a smaller size, before memory runs out.' % (width, height, one, held, size(free)))
    said = 'This render\'s preview pictures are large: %d x %d, %s each in memory, up to %s with the preview\'s copies' % (width, height, one, held)
    return said + ('; %s of memory free.' % size(free) if free is not None else '.')


class Watch:
    """A render's pictures as they come (render._persistent_memory): said in the Terminal when their size is new, and
    among the notices while they are past PAST, looked at again every EVERY seconds for the memory free."""

    def __init__(self):
        self.render = None
        self.told = None
        self.last = 0.0
        self.said = None

    def seen(self, render, width, height, now=None):
        """A picture of a render arrived. Returns (Terminal line or None, notice or None, whether the notice changed)."""
        now = time.monotonic() if now is None else now
        # A new render's size is said anew; what the notices show (said) is kept, so that its small pictures take a
        # render before's notice away.
        if render != self.render:
            self.render, self.told, self.last = render, None, 0.0
        new = (width, height) != self.told
        if not new and now - self.last < EVERY:
            return None, self.said, False
        self.last = now
        free = free_bytes()
        line = terminal_line(width, height, free) if new else None
        self.told = (width, height)
        said = notice(width, height, free)
        changed = said != self.said
        self.said = said
        return line, said, changed
