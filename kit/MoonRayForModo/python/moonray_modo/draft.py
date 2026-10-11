"""The draft picture: the scene as plain outlines from the render camera, to draw a region on.

MoonLightIPR draws the outlines itself, on the graphics card, and sends them white on black. Here they are put in
ink with nothing between them, so that the view's paper shows through, and what was rendered of a region is laid
among them.
"""
from PySide2 import QtCore, QtGui

# The paper, from the head of the view to its foot, and the ink. The paper is the view's own: it stays where it is
# while the picture is moved and magnified over it, and the picture holds the lines alone.
PAPER = ('#f5f2ec', '#b4b6bc')
INK = '#a08467'
# The inks to choose from on the MoonRay page of Modo's Preferences.
INKS = {'tan': INK, 'purple': '#9f8fc9', 'grey': '#7c8088'}


def ink():
    """The ink chosen in the preferences."""
    try:
        from .preferences import Preferences
        return INKS.get(Preferences().get('draft/ink'), INK)
    except Exception:
        return INK

def inked(frame, region):
    """MoonLightIPR's own draft made into the picture shown: its lines, which it sends white on black, in ink with
    nothing between them, and inside the region (left, top, right, bottom as fractions) what it rendered there."""
    made = QtGui.QImage(frame.size(), QtGui.QImage.Format_ARGB32)
    made.fill(QtGui.QColor(ink()))
    made.setAlphaChannel(frame.convertToFormat(QtGui.QImage.Format_Grayscale8))
    if region:
        left, top, right, bottom = region
        part = QtCore.QRectF(left * frame.width(), top * frame.height(), (right - left) * frame.width(), (bottom - top) * frame.height())
        painter = QtGui.QPainter(made)
        try:
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
            painter.drawImage(part, frame.convertToFormat(QtGui.QImage.Format_ARGB32), part)
        finally:
            painter.end()
    return made


def over(draft, rendered, region):
    """The draft picture with what was rendered laid on it inside the region (left, top, right, bottom as fractions)."""
    made = QtGui.QImage(draft)
    if rendered is None or rendered.isNull() or not region:
        return made
    left, top, right, bottom = region
    painter = QtGui.QPainter(made)
    try:
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawImage(QtCore.QRectF(left * made.width(), top * made.height(), (right - left) * made.width(), (bottom - top) * made.height()), rendered,
                          QtCore.QRectF(left * rendered.width(), top * rendered.height(), (right - left) * rendered.width(), (bottom - top) * rendered.height()))
    finally:
        painter.end()
    return made
