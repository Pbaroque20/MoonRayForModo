"""Qt OpenGL image viewer hosted by Modo's CustomView, independent of PView."""
from PySide2 import QtCore, QtGui, QtWidgets

# Whether the crest has come in once in this Modo session: it does so the first time a preview is seen, and a window
# opened after that shows it still, as it rests.
_crest_shown = False


class _PreviewBody:
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QtGui.QImage()
        self.buckets=None
        self.workers=None
        self.gpu_workers=None  # XPU2: the cells the GPU's launches hold
        self.show_workers=True
        self.show_buckets=True
        self.bucket_timeout=QtCore.QTimer(self)
        self.bucket_timeout.setSingleShot(True)
        self.bucket_timeout.timeout.connect(lambda:self.set_buckets(None))
        # The outlines on screen, each with when it was first and last told of, and how long it is held for.
        self._fading={}
        self._fade_clock=QtCore.QElapsedTimer();self._fade_clock.start()
        self._fade_timer=QtCore.QTimer(self);self._fade_timer.setInterval(33)
        self._fade_timer.timeout.connect(self._fade_step)
        self.zoom = 1.0
        self.pan = QtCore.QPointF()
        self._drag = None
        # Where the left button went down, to tell a click from a drag; and a picture laid over the render, such as
        # the Cryptomatte mattes picked, at the render's size.
        self._press = None
        self.overlay = None
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
        # The region's outline is dotted and its dots move round it, as a selection's do, for as long as there is a
        # region: it says a part of the picture is marked, whether or not anything has been rendered of it.
        self._ants = 0
        self._ants_timer = QtCore.QTimer(self)
        self._ants_timer.setInterval(90)
        self._ants_timer.timeout.connect(self._march)
        # Whether the whole frame stays in view when a region is set, as it does over the draft's lines.
        self.whole = False
        # The draft's paper: two colours the frame is filled with, head to foot, under a picture that is then
        # lines with nothing between them. None for the ordinary dark surround.
        self.paper = None
        # The size the picture is spoken of at, where it is drawn finer than it is rendered: a draft's. None for its own.
        self.nominal = None
        self._drawing = None
        # The crest's motion (crest.py): its clock, when it came in, when a render began waiting with nothing to show
        # and when it stopped, and a fade of the whole crest (when it began, from, to). A timer repaints while it moves.
        self._crest_clock = QtCore.QElapsedTimer()
        self._crest_clock.start()
        self._crest_entered = None
        self._crest_waiting = None
        self._crest_settling = None
        self._crest_fade = None
        self._crest_timer = QtCore.QTimer(self)
        self._crest_timer.setInterval(16)
        self._crest_timer.timeout.connect(self._crest_step)
        self.setMouseTracking(True)
        self.setMinimumSize(256, 192)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def showEvent(self, event):
        super().showEvent(event)
        if self._crest_entered is None:
            # The crest comes in the first time a preview is seen in this Modo session; after that it rests.
            global _crest_shown
            if _crest_shown:
                self._crest_entered = self._crest_now() - 3600.0
            else:
                _crest_shown = True
                self._crest_entered = self._crest_now()
                self._crest_timer.start()

    def _crest_now(self):
        return self._crest_clock.elapsed() / 1000.0

    def set_waiting(self, waiting):
        """A render is on its way (True) or not: with nothing yet to show, the crest breathes meanwhile."""
        now = self._crest_now()
        if waiting and self._crest_waiting is None:
            self._crest_waiting, self._crest_settling = now, None
        elif not waiting and self._crest_waiting is not None:
            self._crest_settling = (now, self._crest_depth(now))
            self._crest_waiting = None
        self._crest_timer.start()

    def _crest_depth(self, now):
        """How deep the crest breathes: eased in over half a second of waiting, and out again once the wait is over."""
        if self._crest_waiting is not None:
            return min(1.0, (now - self._crest_waiting) / 0.5)
        if self._crest_settling is not None:
            began, depth = self._crest_settling
            return max(0.0, depth * (1.0 - (now - began) / 0.4))
        return 0.0

    def _crest_pose(self, now):
        from . import crest
        if self._crest_entered is not None and not crest.entered(now - self._crest_entered):
            return crest.entrance(now - self._crest_entered)
        depth = self._crest_depth(now)
        if depth > 0.0:
            # The breath runs on one clock, so that easing it in and out does not jump the wave along.
            return crest.breathing(now, depth)
        return crest.still

    def _crest_shown(self, now):
        """How much of the crest shows as a whole: all of it, but while it fades over a picture or back in."""
        from . import crest
        if self._crest_fade is None:
            return 1.0
        began, start, end = self._crest_fade
        x = min(1.0, (now - began) / crest.FADE)
        return start + (end - start) * (1.0 - (1.0 - x) ** 2)

    def _crest_step(self):
        from . import crest
        now = self._crest_now()
        if self._crest_fade is not None and now - self._crest_fade[0] >= crest.FADE:
            self._crest_fade = None
        moving = (self._crest_entered is not None and not crest.entered(now - self._crest_entered)) or self._crest_depth(now) > 0.0
        fading = self._crest_fade is not None and now - self._crest_fade[0] < crest.FADE
        if not (fading or (moving and self.image.isNull())):
            self._crest_timer.stop()
            if self._crest_settling is not None and self._crest_depth(now) <= 0.0:
                self._crest_settling = None
        self.update()

    @QtCore.Slot(str)
    def load(self, path):
        image = QtGui.QImage(str(path))
        self.set_image(image)

    @QtCore.Slot(object)
    def set_image(self,image):
        if image.isNull():
            raise ValueError('MoonRay output could not be decoded as an image.')
        # The view is set to the picture anew only when its shape is another than the last picture's. Zoom and place
        # are kept as shares of the picture, so one of another size and the same shape (a region's, a coarser one
        # while the scene is followed) is looked at just as the last was, and so is a view cleared for a new render.
        sized = getattr(self, '_sized', None)
        if not sized or abs(image.width() * sized[1] - image.height() * sized[0]) > 2 * max(sized):
            self.fit()
        self._sized = (image.width(), image.height())
        if self.image.isNull():
            # The first picture: the crest fades out over it.
            self._crest_fade = (self._crest_now(), self._crest_shown(self._crest_now()), 0.0)
            self._crest_timer.start()
        # Beauty includes camera-visible environment RGB even where coverage
        # alpha is zero. Display RGB without compositing over the widget; keep
        # the renderer output and its alpha channel untouched on disk.
        self.image = image.convertToFormat(QtGui.QImage.Format_ARGB32 if self.paper else QtGui.QImage.Format_RGB32)
        self._single = None
        self._curved = None
        self.update()

    def clear(self):
        """Show no picture, as before the first render."""
        if not self.image.isNull():
            # The crest fades back in.
            self._crest_fade = (self._crest_now(), 0.0, 1.0)
            self._crest_timer.start()
        self.image = QtGui.QImage()
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
                self._curved = (data, QtGui.QImage(data, self.image.width(), self.image.height(), self.image.width() * 4, self.image.format()))
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

    def _march(self):
        """Move the dots of the region's outline on by one."""
        self._ants = (self._ants + 1) % 8
        self.update()

    def set_region(self, region, tool):
        """Show the region that is rendered, or none; and say whether a left drag draws a new one."""
        self.region = tuple(region) if region else None
        self.region_tool = bool(tool)
        marked = self.region is not None and tuple(self.region) != (0.0, 0.0, 1.0, 1.0)
        if marked and not self._ants_timer.isActive():
            self._ants_timer.start()
        elif not marked:
            self._ants_timer.stop()
        # The view stays as it is being looked at.
        self.update()

    def pixel_at(self, point):
        """The pixel of the picture under a point of the widget, from its top left, or None outside it."""
        area = self.image_rect()
        if self.image.isNull() or area.width() <= 0 or not area.contains(QtCore.QPointF(point)):
            return None
        width, height = self.nominal or (self.image.width(), self.image.height())
        x = int((point.x() - area.left()) / area.width() * width)
        y = int((point.y() - area.top()) / area.height() * height)
        return min(width - 1, max(0, x)), min(height - 1, max(0, y))

    def fit(self):
        """Fill the view with the picture. A region does not change how the picture is looked at: zooming in on it
        is for whoever is looking to do."""
        self.zoom = 1.0
        self.pan = QtCore.QPointF()
        self.update()

    def actual_size(self):
        if not self.image.isNull():
            scale=min(self.width()/self.image.width(),self.height()/self.image.height())
            if scale>0:self.zoom=1./scale;self.pan=QtCore.QPointF();self.update()

    # Outlines are eased, not switched. One comes up over APPEAR seconds. MoonRay comes back to a tile many times as
    # a picture comes on, and between its visits the tile is not in what it reports: so an outline it has left
    # stands for HOLD seconds, in case it is come back to, and only then fades, over FADE seconds. It fades when
    # its tile is done with, not each time it is left. A worker's own small square is left for good far sooner.
    APPEAR=.12
    HOLD=.7
    HOLD_WORKER=.12
    FADE=.45

    def _outlines(self):
        """The outlines now being told of: the workers' own where there are any, else the tiles'."""
        return self.workers if self.show_workers and self.workers is not None else self.buckets

    def _note_outlines(self,told=None,kind='cpu'):
        """Take in what MoonRay last told of: each outline is new, or has been seen again just now. XPU2's GPU cells
        (kind 'gpu') are told of apart from the rest."""
        told=told if told is not None else self._outlines()
        if not told or not self.show_buckets:return
        _,width,height,rectangles=told
        now=self._fade_clock.elapsed()/1000.
        # Whether these are the workers' squares: they are let go of sooner than a tile is.
        hold=self.HOLD_WORKER if told is self.workers or kind=='gpu' else self.HOLD
        for rectangle in rectangles:
            key=(width,height,rectangle,kind)
            seen=self._fading.get(key)
            # One that had begun to fade and is come back to comes up again from where it had got to.
            if seen is None or now-seen[1]>seen[2]+self.FADE:self._fading[key]=[now,now,hold]
            else:
                faded=max(0.0,now-seen[1]-seen[2])/self.FADE
                if faded>0:seen[0]=now-self.APPEAR*(1.0-faded)
                seen[1]=now;seen[2]=hold
        if len(self._fading)>4096:
            for key in sorted(self._fading,key=lambda key:self._fading[key][1])[:len(self._fading)-4096]:del self._fading[key]
        if self._fading and not self._fade_timer.isActive():self._fade_timer.start()

    def _fade_step(self):
        now=self._fade_clock.elapsed()/1000.
        self._fading={key:seen for key,seen in self._fading.items() if now-seen[1]<seen[2]+self.FADE}
        if not self._fading:self._fade_timer.stop()
        self.update()

    @QtCore.Slot(object)
    def set_buckets(self,packet):
        self.buckets=packet
        if packet is None:self.workers=self.gpu_workers=None
        if packet:self.bucket_timeout.start(1500)
        else:self.bucket_timeout.stop()
        # Only what is new is taken in: while the workers' squares are shown, that is not the tiles.
        if self._outlines() is self.buckets:self._note_outlines()

    def set_workers(self,packet):
        if packet and packet[0]=='gpu':
            # XPU2: the GPU's cells, beside the CPU's workers.
            self.gpu_workers=packet[1:]
            if self.show_workers:self._note_outlines(self.gpu_workers,'gpu')
            return
        self.workers=packet
        if self._outlines() is self.workers:self._note_outlines()

    def set_worker_overlay(self,enabled):
        self.show_workers=enabled
        self.update()

    def set_show_buckets(self,enabled):
        self.show_buckets=enabled
        if not enabled:self._fading={}
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
            if self.paper:
                # The draft's paper is the frame the camera renders, and no more: what of the view lies outside the
                # frame is black, so that where the picture ends is plain to see.
                painter.fillRect(self.rect(), QtGui.QColor('#000000'))
                frame = self.image_rect()
                if not frame.isEmpty():
                    paper = QtGui.QLinearGradient(0, frame.top(), 0, frame.bottom())
                    paper.setColorAt(0.0, QtGui.QColor(self.paper[0]))
                    paper.setColorAt(1.0, QtGui.QColor(self.paper[1]))
                    painter.fillRect(frame, paper)
            else:
                painter.fillRect(self.rect(), QtGui.QColor('#191b20'))
            if self.image.isNull():
                # No picture yet: MoonRay's crest, half seen through, which a click on the view starts a render from. It
                # stays while a first render is on its way: how that is going is for the status line below to say.
                # Words take its place only where the crest cannot be drawn.
                from . import crest
                now = self._crest_now()
                if not crest.draw(painter, QtCore.QRectF(self.rect()), opacity=.5 * self._crest_shown(now), pose=self._crest_pose(now)):
                    painter.setPen(QtGui.QColor('#b9bec9'))
                    painter.drawText(self.rect(), QtCore.Qt.AlignCenter, 'Click here to render the scene.')
            else:
                painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
                painter.drawImage(self.image_rect(), self.shown())
                if self.overlay is not None and not self.overlay.isNull():
                    painter.drawImage(self.image_rect(), self.overlay)
                if self._crest_fade is not None and self._crest_fade[2] <= 0.0:
                    # The crest fading out over the first picture.
                    from . import crest
                    now = self._crest_now()
                    shown = self._crest_shown(now)
                    if shown > 0.0:
                        crest.draw(painter, QtCore.QRectF(self.rect()), opacity=.5 * shown, pose=self._crest_pose(now))
                area = self.image_rect()
                box = None
                if self._drawing is not None:
                    box = QtCore.QRectF(QtCore.QPointF(self._drawing[0]), QtCore.QPointF(self._drawing[1])).normalized()
                elif self.region is not None and tuple(self.region) != (0.0, 0.0, 1.0, 1.0):
                    left, top, right, bottom = self.region
                    box = QtCore.QRectF(area.left() + left * area.width(), area.top() + top * area.height(), (right - left) * area.width(), (bottom - top) * area.height())
                if box is not None:
                    # The region: a dotted outline whose dots move round it, light on dark so that it shows over
                    # any picture. While it is being dragged out the dots stand still.
                    painter.setBrush(QtCore.Qt.NoBrush)
                    under = QtGui.QPen(QtGui.QColor('#101010'))
                    under.setWidthF(1.0)
                    painter.setPen(under)
                    painter.drawRect(box)
                    pen = QtGui.QPen(QtGui.QColor('#ffffff'))
                    pen.setWidthF(1.0)
                    pen.setDashPattern([4, 4])
                    pen.setDashOffset(0 if self._drawing is not None else -self._ants)
                    painter.setPen(pen)
                    painter.drawRect(box)
                    if self._drawing is not None and area.width() > 0:
                        # How many pixels of the picture the rectangle takes in, written by the pointer.
                        kept = box.intersected(area)
                        width, height = self.nominal or (self.image.width(), self.image.height())
                        text = '%d x %d' % (round(kept.width() / area.width() * width), round(kept.height() / area.height() * height))
                        at = QtCore.QPointF(self._drawing[1]) + QtCore.QPointF(14, 18)
                        plate = QtCore.QRectF(painter.fontMetrics().boundingRect(text)).adjusted(-5, -3, 5, 3)
                        plate.moveTopLeft(QtCore.QPointF(min(at.x(), self.width() - plate.width() - 2), min(at.y(), self.height() - plate.height() - 2)))
                        painter.fillRect(plate, QtGui.QColor(0, 0, 0, 190))
                        painter.setPen(QtGui.QColor(255, 255, 255))
                        painter.drawText(plate, QtCore.Qt.AlignCenter, text)
            # Each outline with how strongly it is drawn.
            drawn=[]
            if self.show_buckets and self._fading:
                now=self._fade_clock.elapsed()/1000.
                # Coming up, standing, or fading: each by how long since it was first and last told of.
                drawn=[(width,height,rectangle,kind,min(1.0,(now-first)/self.APPEAR)*(1.0-max(0.0,now-last-hold)/self.FADE))
                       for (width,height,rectangle,kind),(first,last,hold) in self._fading.items()]
            painter.setBrush(QtCore.Qt.NoBrush)
            for width,height,(x0,y0,x1,y1),kind,strength in drawn:
                if strength<=0 or not (self.image.isNull() or (self.image.width(),self.image.height())==(width,height)):continue
                scale=min(self.width()/width,self.height()/height)*self.zoom
                left=(self.width()-width*scale)/2+self.pan.x()
                top=(self.height()-height*scale)/2+self.pan.y()
                colour=QtGui.QColor('#bfaef5' if kind=='gpu' else '#a9cdf2');colour.setAlphaF(min(1.0,strength))
                pen=QtGui.QPen(colour);pen.setWidthF(1.0)
                painter.setPen(pen)
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
            self._press = event.pos() if event.button() == QtCore.Qt.LeftButton else None
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
            # The rectangle ends where the button came up.
            area, drawn = self.image_rect(), QtCore.QRectF(QtCore.QPointF(self._drawing[0]), QtCore.QPointF(event.pos())).normalized()
            self._drawing = None
            self.unsetCursor()
            kept = drawn.intersected(area)
            # A click, or a rectangle too small to be meant, is no region.
            if area.width() > 0 and kept.width() >= 4 and kept.height() >= 4:
                self.region_drawn.emit((kept.left() - area.left()) / area.width(), (kept.top() - area.top()) / area.height(),
                                       (kept.right() - area.left()) / area.width(), (kept.bottom() - area.top()) / area.height())
            self.update()
            return
        # A press and release with the picture hardly moved is a click on the pixel under it.
        if self._press is not None and event.button() == QtCore.Qt.LeftButton and (event.pos() - self._press).manhattanLength() < 4:
            found = self.pixel_at(event.pos())
            if found is not None:
                self.clicked.emit(found[0], found[1], int(event.modifiers()))
        self._press = None
        self._drag = None
        self.unsetCursor()

    def set_overlay(self, image):
        """Lay a picture over the render, at its size, or take it away with None."""
        self.overlay = image
        self.update()

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
    clicked=QtCore.Signal(int,int,int)


class SoftwarePreview(_PreviewBody,QtWidgets.QWidget):
    """Embedded graph thumbnails need no additional OpenGL context in Modo."""
    start_requested=QtCore.Signal()
    region_drawn=QtCore.Signal(float,float,float,float)
    hovered=QtCore.Signal(int,int)
    clicked=QtCore.Signal(int,int,int)

    def paintEvent(self,event):
        self.paintGL()
