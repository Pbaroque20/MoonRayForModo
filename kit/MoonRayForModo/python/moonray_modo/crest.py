"""MoonRay's crest, drawn where the preview has no picture yet: the shape in the kit's assets/mooncrest.svg.

The shape is read from the file's one path by a reader of its own, since Modo's Qt comes without the SVG module. It
knows the commands that file uses: move, line, the two cubic curves and close, each absolute or relative. A file it
cannot read gives no shape, and the view then says in words what a click does.
"""
import re
from pathlib import Path

from PySide2 import QtCore, QtGui

FILE = Path(__file__).resolve().parents[2] / 'assets/mooncrest.svg'
_held = {}


def outline(text):
    """The path of an SVG file's first path element, in the file's own units; None if it has none this can read."""
    found = re.search(r'<path\b[^>]*\bd="([^"]+)"', text, re.S)
    if not found:
        return None
    tokens = re.findall(r'[MmLlHhVvCcSsZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?', found.group(1))
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


def shape():
    """The crest's path, read once; None where the file is missing or is not one this reads."""
    if 'shape' not in _held:
        try:
            _held['shape'] = outline(FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _held['shape'] = None
    return _held['shape']


def draw(painter, area, share=.34, opacity=.5):
    """Draw the crest in the middle of an area, a share of its smaller side across, half seen through. Returns whether
    there was a crest to draw."""
    path = shape()
    if path is None:
        return False
    bounds = path.boundingRect()
    if bounds.width() <= 0 or bounds.height() <= 0:
        return False
    scale = share * min(area.width(), area.height()) / max(bounds.width(), bounds.height())
    painter.save()
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.translate(area.center())
        painter.scale(scale, scale)
        painter.translate(-bounds.center())
        painter.setOpacity(opacity)
        painter.fillPath(path, QtGui.QColor(255, 255, 255))
    finally:
        painter.restore()
    return True
