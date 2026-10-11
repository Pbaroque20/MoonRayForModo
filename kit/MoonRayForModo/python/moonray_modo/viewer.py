"""Qt OpenGL image viewer hosted by Modo's CustomView, independent of PView."""
from PySide2 import QtCore, QtGui, QtWidgets


class _PreviewBody:
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QtGui.QImage()
        self.buckets=None
        self.workers=None
        self.show_workers=True
        self.show_buckets=True
        self.bucket_timeout=QtCore.QTimer(self)
        self.bucket_timeout.setSingleShot(True)
        self.bucket_timeout.timeout.connect(lambda:self.set_buckets(None))
        self.zoom = 1.0
        self.pan = QtCore.QPointF()
        self._drag = None
        # Which of the picture is shown: all of it, or one of red, green and blue as greys.
        self.channel = 'rgb'
        self._single = None
        # A gamma for looking at the picture, over and above its view transform: 1 leaves it as it is.
        self.gamma = 1.0
        self._curved = None
        # The part of the frame that is rendered, as (left, top, right, bottom) from 0 to 1, where a region is on; and
        # whether a drag of the left button draws a new one, in place of moving the picture.
        self.region = None
        self.region_tool = False
        # Whether the whole frame stays in view when a region is set, as it does over the draft's lines.
        self.whole = False
        self._drawing = None
        self.setMouseTracking(True)
        self.setMinimumSize(256, 192)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    @QtCore.Slot(str)
    def load(self, path):
        image = QtGui.QImage(str(path))
        self.set_image(image)

    @QtCore.Slot(object)
    def set_image(self,image):
        if image.isNull():
            raise ValueError('MoonRay output could not be decoded as an image.')
        if image.size() != self.image.size():
            self.fit()
        # Beauty includes camera-visible environment RGB even where coverage
        # alpha is zero. Display RGB without compositing over the widget; keep
        # the renderer output and its alpha channel untouched on disk.
        self.image = image.convertToFormat(QtGui.QImage.Format_RGB32)
        self._single = None
        self._curved = None
        self.update()

    def set_channel(self, channel):
        """Show all of the picture ('rgb') or one of its channels ('r', 'g', 'b') as greys."""
        self.channel = channel if channel in ('r', 'g', 'b') else 'rgb'
        self._single = None
        self.update()

    def set_gamma(self, gamma):
        """Brighten or darken the middle of the picture for looking at: above 1 lifts it, below 1 lowers it."""
        self.gamma = min(5.0, max(.1, float(gamma)))
        self._curved = None
        self._single = None
        self.update()

    def looked_at(self):
        """The picture with the viewing gamma on it."""
        if abs(self.gamma - 1.0) < 1e-6 or self.image.isNull():
            return self.image
        if self._curved is None:
            try:
                # Every byte of the picture through one table: its colours, and a spare byte that stays as it is.
                table = bytes(min(255, int(round(255.0 * (value / 255.0) ** (1.0 / self.gamma)))) for value in range(256))
                data = bytes(self.image.constBits())[:self.image.width() * self.image.height() * 4].translate(table)
                self._curved = (data, QtGui.QImage(data, self.image.width(), self.image.height(), self.image.width() * 4, QtGui.QImage.Format_RGB32))
            except (TypeError, ValueError, RuntimeError):
                return self.image
        return self._curved[1]

    def shown(self):
        """The picture as it is drawn: itself, or the one channel asked for."""
        if self.channel == 'rgb' or self.image.isNull():
            return self.looked_at()
        if self._single is None:
            try:
                # A pixel is held as blue, green, red and a spare byte: every fourth byte from the channel's place.
                data = bytes(self.looked_at().constBits())[:self.image.width() * self.image.height() * 4]
                one = data['bgr'.index(self.channel)::4]
                self._single = (one, QtGui.QImage(one, self.image.width(), self.image.height(), self.image.width(), QtGui.QImage.Format_Grayscale8))
            except (TypeError, ValueError, RuntimeError):
                return self.looked_at()
        return self._single[1]

    def set_region(self, region, tool):
        """Show the region that is rendered, or none; and say whether a left drag draws a new one."""
        before = self.region
        self.region = tuple(region) if region else None
        self.region_tool = bool(tool)
        # The view follows: onto a region newly set, and back to the whole frame when there is none.
        if self.region != before:
            self.fit()
        self.update()

    def pixel_at(self, point):
        """The pixel of the picture under a point of the widget, from its top left, or None outside it."""
        area = self.image_rect()
        if self.image.isNull() or area.width() <= 0 or not area.contains(QtCore.QPointF(point)):
            return None
        x = int((point.x() - area.left()) / area.width() * self.image.width())
        y = int((point.y() - area.top()) / area.height() * self.image.height())
        return min(self.image.width() - 1, max(0, x)), min(self.image.height() - 1, max(0, y))

    def fit(self):
        """Fill the view with the picture, or with the region of it that is rendered."""
        self.zoom = 1.0
        self.pan = QtCore.QPointF()
        region = getattr(self, 'region', None)
        if region and not getattr(self, 'whole', False) and tuple(region) != (0.0, 0.0, 1.0, 1.0) and not self.image.isNull() and self.width() > 0 and self.height() > 0:
            left, top, right, bottom = region
            wide, high = self.image.width() * (right - left), self.image.height() * (bottom - top)
            if wide > 0 and high > 0:
                whole = min(self.width() / self.image.width(), self.height() / self.image.height())
                # A little room is left around it, so that its edge is seen.
                scale = min(32.0 * whole, .94 * min(self.width() / wide, self.height() / high))
                self.zoom = scale / whole
                self.pan = QtCore.QPointF(-((left + right) / 2 - .5) * self.image.width() * scale,
                                          -((top + bottom) / 2 - .5) * self.image.height() * scale)
        self.update()

    def actual_size(self):
        if not self.image.isNull():
            scale=min(self.width()/self.image.width(),self.height()/self.image.height())
            if scale>0:self.zoom=1./scale;self.pan=QtCore.QPointF();self.update()

    @QtCore.Slot(object)
    def set_buckets(self,packet):
        self.buckets=packet
        if packet is None:self.workers=None
        if packet:self.bucket_timeout.start(1500)
        else:self.bucket_timeout.stop()
        self.update()

    def set_workers(self,packet):
        self.workers=packet
        self.update()

    def set_worker_overlay(self,enabled):
        self.show_workers=enabled
        self.update()

    def set_show_buckets(self,enabled):
        self.show_buckets=enabled
        self.update()

    def image_rect(self):
        if self.image.isNull():
            return QtCore.QRectF()
        scale = min(self.width() / self.image.width(), self.height() / self.image.height()) * self.zoom
        size = QtCore.QSizeF(self.image.width() * scale, self.image.height() * scale)
        center = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.pan
        return QtCore.QRectF(center - QtCore.QPointF(size.width() / 2, size.height() / 2), size)

    def paintGL(self):
        # QPainter uses Qt's OpenGL paint engine on this widget. Qt owns the
        # context and framebuffer; no dependency on Modo's external-render queue.
        painter = QtGui.QPainter(self)
        try:
            painter.fillRect(self.rect(), QtGui.QColor('#191b20'))
            if self.image.isNull():
                painter.setPen(QtGui.QColor('#b9bec9'))
                painter.drawText(self.rect(), QtCore.Qt.AlignCenter, 'Rendering…' if self.buckets else 'Click here to render the scene.')
            else:
                painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
                painter.drawImage(self.image_rect(), self.shown())
                area = self.image_rect()
                box = None
                if self._drawing is not None:
                    box = QtCore.QRectF(QtCore.QPointF(self._drawing[0]), QtCore.QPointF(self._drawing[1])).normalized()
                elif self.region is not None and tuple(self.region) != (0.0, 0.0, 1.0, 1.0):
                    left, top, right, bottom = self.region
                    box = QtCore.QRectF(area.left() + left * area.width(), area.top() + top * area.height(), (right - left) * area.width(), (bottom - top) * area.height())
                if box is not None:
                    # The region: a red rectangle, as render buffers draw it.
                    pen = QtGui.QPen(QtGui.QColor('#ff5a4d'))
                    pen.setWidthF(1.0)
                    if self._drawing is not None:
                        pen.setStyle(QtCore.Qt.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(QtCore.Qt.NoBrush)
                    painter.drawRect(box)
                    if self._drawing is not None and area.width() > 0:
                        # How many pixels of the picture the rectangle takes in, written by the pointer.
                        kept = box.intersected(area)
                        text = '%d x %d' % (round(kept.width() / area.width() * self.image.width()), round(kept.height() / area.height() * self.image.height()))
                        at = QtCore.QPointF(self._drawing[1]) + QtCore.QPointF(14, 18)
                        plate = QtCore.QRectF(painter.fontMetrics().boundingRect(text)).adjusted(-5, -3, 5, 3)
                        plate.moveTopLeft(QtCore.QPointF(min(at.x(), self.width() - plate.width() - 2), min(at.y(), self.height() - plate.height() - 2)))
                        painter.fillRect(plate, QtGui.QColor(0, 0, 0, 190))
                        painter.setPen(QtGui.QColor(255, 255, 255))
                        painter.drawText(plate, QtCore.Qt.AlignCenter, text)
            overlay=self.workers if self.show_workers and self.workers is not None else self.buckets
            if (self.show_buckets and overlay and
                    (self.image.isNull() or (self.image.width(),self.image.height())==overlay[1:3])):
                _,width,height,rectangles=overlay
                scale=min(self.width()/width,self.height()/height)*self.zoom
                left=(self.width()-width*scale)/2+self.pan.x()
                top=(self.height()-height*scale)/2+self.pan.y()
                pen=QtGui.QPen(QtGui.QColor('#ffd166'));pen.setWidthF(1.0)
                painter.setPen(pen);painter.setBrush(QtCore.Qt.NoBrush)
                for x0,y0,x1,y1 in rectangles:
                    painter.drawRect(QtCore.QRectF(left+x0*scale,top+(height-y1)*scale,(x1-x0)*scale,(y1-y0)*scale))
        finally:
            painter.end()

    def wheelEvent(self, event):
        if self.image.isNull():
            return
        old = self.zoom
        self.zoom = max(.1, min(32.0, old * 1.2 ** (event.angleDelta().y() / 120.0)))
        anchor = QtCore.QPointF(event.pos()) - QtCore.QPointF(self.width() / 2, self.height() / 2)
        self.pan = anchor - (anchor - self.pan) * (self.zoom / old)
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if self.image.isNull() and not self.buckets and event.button()==QtCore.Qt.LeftButton:
            self.start_requested.emit();event.accept();return
        if self.region_tool and event.button() == QtCore.Qt.LeftButton and not self.image.isNull():
            # With the region tool on, the left button draws the region; the middle one still moves the picture.
            self._drawing = (event.pos(), event.pos())
            self.setCursor(QtCore.Qt.CrossCursor)
            event.accept()
            return
        if event.button() in (QtCore.Qt.LeftButton, QtCore.Qt.MiddleButton):
            self._drag = event.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drawing is not None:
            self._drawing = (self._drawing[0], event.pos())
            self.update()
            return
        found = self.pixel_at(event.pos())
        self.hovered.emit(*(found or (-1, -1)))
        if self._drag is not None:
            self.pan += QtCore.QPointF(event.pos() - self._drag)
            self._drag = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drawing is not None:
            area, drawn = self.image_rect(), QtCore.QRectF(QtCore.QPointF(self._drawing[0]), QtCore.QPointF(self._drawing[1])).normalized()
            self._drawing = None
            self.unsetCursor()
            kept = drawn.intersected(area)
            # A click, or a rectangle too small to be meant, is no region.
            if area.width() > 0 and kept.width() >= 4 and kept.height() >= 4:
                self.region_drawn.emit((kept.left() - area.left()) / area.width(), (kept.top() - area.top()) / area.height(),
                                       (kept.right() - area.left()) / area.width(), (kept.bottom() - area.top()) / area.height())
            self.update()
            return
        self._drag = None
        self.unsetCursor()

    def leaveEvent(self, event):
        self.hovered.emit(-1, -1)

    def mouseDoubleClickEvent(self, event):
        if self.region_tool and event.button() == QtCore.Qt.LeftButton:
            return
        self._drag = None
        self.unsetCursor()
        self.fit()


class Preview(_PreviewBody,QtWidgets.QOpenGLWidget):
    start_requested=QtCore.Signal()
    region_drawn=QtCore.Signal(float,float,float,float)
    hovered=QtCore.Signal(int,int)


class SoftwarePreview(_PreviewBody,QtWidgets.QWidget):
    """Embedded graph thumbnails need no additional OpenGL context in Modo."""
    start_requested=QtCore.Signal()
    region_drawn=QtCore.Signal(float,float,float,float)
    hovered=QtCore.Signal(int,int)

    def paintEvent(self,event):
        self.paintGL()
