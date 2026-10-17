"""MoonRay's crest, drawn where the preview has no picture yet: the shapes in the kit's assets/mooncrest.svg, the
MOONRAY wordmark between its two arcs.

The shapes are read from the file's paths by a reader of its own, which keeps each path apart so that the crest can
move part by part (Qt's SVG module, which Modo's Python has, plays almost none of SVG's own animation). It knows the
commands that file uses: move, line, the two cubic curves and close, each absolute or relative. A file it cannot read
gives no shape, and the view then says in words what a click does.

The crest moves (poses): it comes in as the preview first opens, its arcs from above and below and the letters one
after another from the left; it breathes, letter by letter, while a render is on its way with nothing yet to show; and
it fades out over the first picture, and back in when the picture is cleared (viewer.py keeps the time).
"""
import math
import re
from pathlib import Path

from PySide2 import QtCore, QtGui

FILE = Path(__file__).resolve().parents[2] / 'assets/mooncrest.svg'
_held = {}


def outline(text):
    """The paths of an SVG file, together, in the file's own units; None if it has none this can read."""
    whole = QtGui.QPainterPath()
    for data in re.findall(r'<path\b[^>]*\bd="([^"]+)"', text, re.S):
        path = one(data)
        if path is None:
            return None
        whole.addPath(path)
    return whole if not whole.isEmpty() else None


def one(data):
    """One path element's outline, from its d attribute; None if it uses what this does not read."""
    tokens = re.findall(r'[MmLlHhVvCcSsZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?', data)
    path, at, last, command, i = QtGui.QPainterPath(), QtCore.QPointF(), None, None, 0
    take = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4}
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in 'Zz':
                path.closeSubpath()
                at, last = path.currentPosition(), None
                continue
        kind = command.upper() if command else None
        if kind not in take or i + take[kind] > len(tokens):
            return None
        try:
            values = [float(v) for v in tokens[i:i + take[kind]]]
        except ValueError:
            return None
        i += take[kind]
        away = command.islower()
        point = lambda x, y: QtCore.QPointF(x + at.x(), y + at.y()) if away else QtCore.QPointF(x, y)
        if kind == 'M':
            at = point(*values)
            path.moveTo(at)
            last = None
            # Further pairs after a move are lines.
            command = 'l' if away else 'L'
        elif kind == 'L':
            at = point(*values)
            path.lineTo(at)
            last = None
        elif kind == 'H':
            at = QtCore.QPointF(values[0] + (at.x() if away else 0.0), at.y())
            path.lineTo(at)
            last = None
        elif kind == 'V':
            at = QtCore.QPointF(at.x(), values[0] + (at.y() if away else 0.0))
            path.lineTo(at)
            last = None
        else:
            if kind == 'C':
                first, second, end = point(*values[0:2]), point(*values[2:4]), point(*values[4:6])
            else:
                # A smooth curve sets out the way the one before came in.
                first = QtCore.QPointF(2 * at.x() - last.x(), 2 * at.y() - last.y()) if last is not None else QtCore.QPointF(at)
                second, end = point(*values[0:2]), point(*values[2:4])
            path.cubicTo(first, second, end)
            at, last = end, second
    return path if not path.isEmpty() else None


def parts():
    """The crest's paths one by one, read once, each with its kind: 'letter' (MOONRAY's, numbered from the left) or
    'arc' (numbered from the top). None where the file is missing or is not one this reads."""
    if 'parts' not in _held:
        _held['parts'] = None
        try:
            paths = [one(data) for data in re.findall(r'<path\b[^>]*\bd="([^"]+)"', FILE.read_text(encoding='utf-8'), re.S)]
        except (OSError, ValueError):
            paths = []
        if paths and all(path is not None for path in paths):
            # The letters stand side by side on one line; the arcs lie above and below it.
            middle = sorted(path.boundingRect().center().y() for path in paths)[len(paths) // 2]
            tall = max(path.boundingRect().height() for path in paths)
            letters = sorted((path for path in paths if abs(path.boundingRect().center().y() - middle) < tall / 4),
                             key=lambda path: path.boundingRect().left())
            arcs = sorted((path for path in paths if path not in letters), key=lambda path: path.boundingRect().top())
            _held['parts'] = [(path, 'letter', n) for n, path in enumerate(letters)] + [(path, 'arc', n) for n, path in enumerate(arcs)]
    return _held['parts']


# How the crest moves: each pose gives, for a part, how much of it shows (0 to 1) and how far it is moved, across and
# down, in the file's units.
ENTRANCE = 1.4          # seconds the crest takes to come in
FADE = 0.45             # seconds to fade out over the first picture, or back in
BREATH = 1.8            # seconds of one breath while a render is on its way


def _eased(x):
    """0 to 1, slowing to a stop (cubic)."""
    x = min(1.0, max(0.0, x))
    return 1.0 - (1.0 - x) ** 3


def still(kind, number):
    return 1.0, 0.0, 0.0


def entrance(seconds):
    """The crest coming in, seconds after the preview opened: the arcs slide in from above and below as they show, then
    the letters rise into place one after another from the left."""
    def pose(kind, number):
        if kind == 'arc':
            x = _eased(seconds / 0.8)
            return x, 0.0, (1.0 - x) * (-60.0 if number == 0 else 60.0)
        x = _eased((seconds - 0.3 - 0.08 * number) / 0.55)
        return x, 0.0, (1.0 - x) * 40.0
    return pose


def entered(seconds):
    return seconds >= ENTRANCE


def breathing(seconds, depth=1.0):
    """The crest breathing while a render is on its way: a wave of fading out and in that runs along the letters, the
    arcs with it. depth, from 0 to 1, eases the breath in and out."""
    def pose(kind, number):
        phase = 2.0 * math.pi * seconds / BREATH - (number * 0.45 if kind == 'letter' else 1.4)
        wave = 0.5 + 0.5 * math.cos(phase)
        return 1.0 - depth * 0.7 * (1.0 - wave), 0.0, 0.0
    return pose


def shape():
    """The crest's path, read once; None where the file is missing or is not one this reads."""
    if 'shape' not in _held:
        try:
            _held['shape'] = outline(FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _held['shape'] = None
    return _held['shape']


def draw(painter, area, share=.34, across=.5, opacity=.5, pose=still):
    """Draw the crest in the middle of an area, half seen through: at most a share of the area's height tall and of its
    width (across) wide, so that a wide wordmark is as big as it fits; each part as pose has it. Returns whether there
    was a crest to draw."""
    path, pieces = shape(), parts()
    if path is None:
        return False
    bounds = path.boundingRect()
    if bounds.width() <= 0 or bounds.height() <= 0:
        return False
    scale = min(across * area.width() / bounds.width(), share * area.height() / bounds.height())
    painter.save()
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.translate(area.center())
        painter.scale(scale, scale)
        painter.translate(-bounds.center())
        if not pieces:
            painter.setOpacity(opacity)
            painter.fillPath(path, QtGui.QColor(255, 255, 255))
            return True
        for piece, kind, number in pieces:
            shown, across_, down = pose(kind, number)
            if shown <= 0.0:
                continue
            painter.setOpacity(opacity * min(1.0, shown))
            painter.fillPath(piece.translated(across_, down) if (across_ or down) else piece, QtGui.QColor(255, 255, 255))
    finally:
        painter.restore()
    return True
