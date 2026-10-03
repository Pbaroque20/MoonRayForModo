"""Qt OpenGL image viewer hosted by Modo's CustomView, independent of PView."""
from PySide2 import QtCore, QtGui, QtWidgets


class Preview(QtWidgets.QOpenGLWidget):
    start_requested=QtCore.Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QtGui.QImage()
        self.buckets=None
        self.show_buckets=True
        self.bucket_timeout=QtCore.QTimer(self)
        self.bucket_timeout.setSingleShot(True)
        self.bucket_timeout.timeout.connect(lambda:self.set_buckets(None))
        self.zoom = 1.0
        self.pan = QtCore.QPointF()
        self._drag = None
        self.setMinimumSize(256, 192)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setToolTip('Click empty preview to render. Wheel: zoom. Middle drag: pan. Double-click: fit image.')

    def load(self, path):
        image = QtGui.QImage(str(path))
        if image.isNull():
            raise ValueError('MoonRay output could not be decoded as an image.')
        if image.size() != self.image.size():
            self.fit()
        # Beauty includes camera-visible environment RGB even where coverage
        # alpha is zero. Display RGB without compositing over the widget; keep
        # the renderer output and its alpha channel untouched on disk.
        self.image = image.convertToFormat(QtGui.QImage.Format_RGB32)
        self.update()

    def fit(self):
        self.zoom = 1.0
        self.pan = QtCore.QPointF()
        self.update()

    def actual_size(self):
        if not self.image.isNull():
            scale=min(self.width()/self.image.width(),self.height()/self.image.height())
            if scale>0:self.zoom=1./scale;self.pan=QtCore.QPointF();self.update()

    def set_buckets(self,packet):
        self.buckets=packet
        if packet:self.bucket_timeout.start(1500)
        else:self.bucket_timeout.stop()
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
                painter.drawImage(self.image_rect(), self.image)
            if self.show_buckets and self.buckets:
                _,width,height,rectangles=self.buckets
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
        if event.button() in (QtCore.Qt.LeftButton, QtCore.Qt.MiddleButton):
            self._drag = event.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.pan += QtCore.QPointF(event.pos() - self._drag)
            self._drag = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event):
        self._drag = None
        self.unsetCursor()
        self.fit()
