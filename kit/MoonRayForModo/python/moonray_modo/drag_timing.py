"""Where a followed drag's time goes in the kit, said in its report once the mouse is let go (panel._drag_note; the user,
2026-11-22: "add per-step timings to the Render Log: the viewport check, writing the step, sending it, and receiving and
drawing each picture"). Each part's times are gathered while a drag is followed and summed up as its count, median and
most; nothing is kept between drags, and nothing is gathered while none is followed."""
import time

_on = False
_times = {}

# The parts, in the order they happen, as the report names them.
PARTS = (('look', 'the viewport looked at'),
         ('step', 'the step made'),
         ('send', 'handed to the renderer'),
         ('dispatch', 'sent to the session'),
         ('read', 'a picture read'),
         ('ready', 'a picture read to ready to draw'),
         ('draw', 'a picture drawn'))


def begin():
    global _on
    _on = True
    _times.clear()


def add(part, seconds):
    if _on:
        _times.setdefault(part, []).append(seconds * 1000.0)


def now():
    return time.perf_counter()


def end():
    """The drag's summary (empty where nothing was timed), and the gathering stopped."""
    global _on
    _on = False
    said = []
    for key, words in PARTS:
        values = sorted(_times.get(key) or [])
        if values:
            said.append('%s %d times, median %.1f ms, most %.1f ms' % (words, len(values), values[len(values) // 2], values[-1]))
    _times.clear()
    return '; '.join(said)
