"""The MoonRay preview window: the image, and what is used while looking at it.

Render settings live on the scene's Render item and are edited in its MoonRay properties
(scene_settings.py); what the window remembers about previewing on this machine is in
preferences.py; output renders, exports and the scene dialogs are in panel_tools.py.
"""
from PySide2 import QtCore, QtGui, QtWidgets
from . import host, options, properties, scene_settings
import functools
import lx
from .render import Renderer
from .viewer import Preview
from .preferences import Preferences
from .panel_tools import Tools

RENDER_TIP = 'Render the current scene. The previous image stays until its replacement is ready.'
STOP_TIP = 'Stop the render in progress and stop following scene changes.'
# Always offered in the buffer list; choosing one adds the output to the scene if it lacks it.
# Modo's own style draws menu entries hard against the edge.
MENU_STYLE = 'QMenu::item { padding: 5px 24px 5px 24px; } QMenu::separator { height: 1px; margin: 4px 10px; }'
CRYPTOMATTES = (('object', 'Cryptomatte: Objects'), ('material', 'Cryptomatte: Materials'))
NO_COMPOSITE = "Open the scene's compositor (Options > Compositor) and build a non-default node network."


# The Notices button when there is something to read: a background and the colour of its words.
NOTICE_STYLE = 'QToolButton{background-color:%s;color:%s;border-radius:3px;padding:1px 6px;}'
# Words that make a notice an error and not a remark.
NOTICE_ERRORS = ('error', 'failed', 'could not', 'cannot', 'unavailable', 'unsupported', 'missing', 'not found', 'invalid')


def notice_is_error(message):
    lowered = str(message).lower()
    return any(word in lowered for word in NOTICE_ERRORS)


def scene_display(stored):
    from .display import values
    return values(stored['display'])


# How long the scene's time must stand still before a preview that follows the scene renders it: longer than the gap
# between two frames of an animation played slowly.
PLAYBACK_REST=0.35
# The most pixels a draft is drawn at. A picture is handed over as twelve bytes a pixel, in at most 64 MB.
DRAFT_MOST=4500000
# How long Modo's thread is left alone after an update of a followed scene, in lengths of that update.
LIVE_REST=2.0


class Panel(Tools, QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.preferences = Preferences()
        self.settings = self.preferences.store
        self.renderer = Renderer(self)
        from .changes import Changes
        self.changes=Changes();self._geometry_cache=None;self._last_time=None;self._live_settings=None;self._asset_signature=[];self._asset_scene={};self._last_full_capture=0
        self.last_digest = None
        self._pending_preview=False
        self._surroundings=None
        self._rendering=False
        # IPR is a choice of how Render behaves; following is Render having been pressed with it on.
        self._following=False
        self._scene_id=None
        self._shown=None
        self._asset_check_time=0
        self._ipr_refine_scene=None
        self.disposed = False
        self.sequence = None
        self.release_timer=QtCore.QTimer(self);self.release_timer.setSingleShot(True);self.release_timer.setInterval(80)
        self.release_timer.timeout.connect(self._after_drag)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._live_tick)
        self.refine_timer=QtCore.QTimer(self);self.refine_timer.setSingleShot(True);self.refine_timer.setInterval(750)
        self.refine_timer.timeout.connect(self._refine_ipr)
        self.display_timer=QtCore.QTimer(self);self.display_timer.setSingleShot(True);self.display_timer.setInterval(200)
        self.display_timer.timeout.connect(self._commit_exposure)
        self.preview_timer=QtCore.QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(150)
        self.preview_timer.timeout.connect(lambda:self._preview_changed(0))
        # Draft follows the scene by itself, whatever the engine and whether or not realtime is on: its outlines cost
        # next to nothing. This looks, thirty times a second, for something to redraw them for, and finds it at once
        # where Modo has told of nothing: only then is the scene looked into.
        self.draft_timer=QtCore.QTimer(self);self.draft_timer.setInterval(33)
        self.draft_timer.timeout.connect(self._draft_tick)
        self.poll_timer=QtCore.QTimer(self);self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self._poll)

        layout = QtWidgets.QVBoxLayout(self);layout.setContentsMargins(4,4,4,4);layout.setSpacing(3)
        layout.addLayout(self._toolbar())
        self.preview = Preview()
        # A line at the foot of the picture, in the middle, for a mode worth knowing of. It takes no clicks: they go
        # to the picture.
        self.hud=QtWidgets.QLabel(self.preview)
        self.hud.setStyleSheet('QLabel{color:#f2e3c4;background-color:rgba(20,22,26,170);border-radius:3px;padding:3px 7px;font-weight:bold;}')
        self.hud.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents);self.hud.hide()
        self.preview.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.preview.customContextMenuRequested.connect(lambda point:self._image_menu(point).exec_(self.preview.mapToGlobal(point)))
        self.preview.installEventFilter(self)
        self.preview.start_requested.connect(self.start_render)
        self.preview.region_drawn.connect(self._region_drawn)
        self.preview.hovered.connect(self._probe)
        self.preview.set_gamma(self.preferences.get('display_gamma'))
        self.preview.set_worker_overlay(self.preferences.get('worker_tiles'))
        self.preview.set_show_buckets(self.preferences.get('show_buckets'))
        layout.addWidget(self.preview, 1)
        self.render_progress=QtWidgets.QProgressBar()
        self.render_progress.setRange(0,100);self.render_progress.setValue(0)
        self.render_progress.setTextVisible(False);self.render_progress.setFixedHeight(4)
        layout.addWidget(self.render_progress)
        layout.addLayout(self._status_line())
        self.warnings=QtWidgets.QPlainTextEdit();self.warnings.setReadOnly(True);self.warnings.setMaximumHeight(150);self.warnings.hide()
        self.warnings.setPlaceholderText('What the renderer could not carry over from the scene is listed here after a render.')
        layout.addWidget(self.warnings)

        self.renderer.buckets.connect(self.preview.set_buckets)
        self.renderer.workers.connect(self.preview.set_workers)
        self.renderer.progress.connect(self._render_progress)
        self.renderer.status.connect(self._renderer_status)
        self.renderer.failed.connect(self._failed)
        self.renderer.image_ready.connect(self._image)
        self.renderer.image_object.connect(self._image)
        self.renderer.finished.connect(self._finished)
        self.renderer.stopped.connect(self._stopped_plain)
        self.renderer.kept.connect(self._kept)
        self.renderer.settled_clean.connect(self._smart_settled)
        self.renderer.notices.connect(self._engine_notices)
        self._engine_changed(0)
        self._poll()
        self.buffer.setCurrentIndex(max(0,self.buffer.findData(self._settings_values_stored().get('preview_buffer','beauty'))))
        self.buffer.currentIndexChanged.connect(self._buffer_changed)
        # What the user last chose from the list themselves, as against what the panel showed for them.
        self._buffer_picked=None
        self.buffer.activated.connect(lambda index:setattr(self,'_buffer_picked',self.buffer.itemData(index)))
        self._limit_buffers()
        self.preview_engine.currentIndexChanged.connect(self._engine_changed)
        self.preview_engine.currentIndexChanged.connect(self._preview_changed)
        self.ipr_mode.toggled.connect(self._ipr_changed)
        self.poll_timer.start()
        # Where the preferences ask for it, a preview starts as the window opens.
        # The window opens showing the crest and renders nothing, whatever engine it opens on, unless Preferences
        # says to render on opening. A realtime engine is switched on with its button, never by being chosen.
        if self.preferences.get('render_on_open'):QtCore.QTimer.singleShot(800,lambda:None if self.disposed or self._rendering or self._following else self.start_render())
        self._set_rendering(self._rendering)

    # The window's own controls

    def _toolbar(self):
        row = QtWidgets.QHBoxLayout();row.setSpacing(4)
        self.start = QtWidgets.QPushButton('Render')
        self.start.setToolTip(RENDER_TIP)
        # One button: it starts a preview, and while one runs or IPR is watching, it stops it.
        self.start.clicked.connect(self._render_or_stop)
        # Pressed in, as it is while realtime is on, it is lit in Modo's own orange, so that on is told from off at a glance.
        self.start.setStyleSheet('QPushButton:checked{background-color:#f49c1c;color:#1a1a1a;border:1px solid #ffb84d;border-radius:3px;font-weight:bold;}')
        row.addWidget(self.start)
        # Three ways to preview. MoonRay renders the picture once, in full. MoonRay LS renders it once too, small
        # and at few samples: it is too slow to follow a scene of any size. MoonLightIPR is realtime: switched on
        # with the button, it follows the scene as it is edited. Whether the engine chosen is the realtime one is
        # kept in a switch of its own, which is not shown.
        self.preview_engine=QtWidgets.QComboBox()
        self.preview_engine.addItem('MoonRay', 'moonray')
        self.preview_engine.addItem('MoonRay LS', 'moonray_ls')
        self.preview_engine.addItem('MoonLightIPR', 'moonlightipr')
        # The window opens on the engine named in Preferences, MoonRay unless that is changed. The engine it was
        # last left on is not remembered: a window that opened on a realtime engine would be one that renders
        # before it is asked to.
        stored=self.preferences.get('open_engine')
        self.preview_engine.setCurrentIndex(max(0,self.preview_engine.findData(stored)))
        self.preview_engine.setToolTip('MoonRay: the full render, once, as an output render would be.\n'
                                       'MoonRay LS (low sample): a quick MoonRay render, once, at fewer samples and a smaller size.\n'
                                       'MoonLightIPR: a fast GPU preview that follows the scene and approximates materials and lighting; Notices lists what it leaves out.\n'
                                       'Output renders always use MoonRay.')
        self.ipr_mode=QtWidgets.QCheckBox('Live',self);self.ipr_mode.hide()
        self.ipr_mode.setChecked(self._live())
        row.addWidget(self.preview_engine)
        # The camera rendered through: Modo's, or a MoonRay camera item such as a fisheye.
        self.camera=QtWidgets.QComboBox()
        self.camera.setToolTip('The camera the scene is rendered through. MoonRay camera items are added from MoonRay > Add MoonRay Item.')
        # A long camera name is cut short in a narrow window: the whole of it is in the tip.
        self.camera.currentTextChanged.connect(lambda text:self.camera.setToolTip((text+'\n' if text else '')+'The camera the scene is rendered through. MoonRay camera items are added from MoonRay > Add MoonRay Item.'))
        self.camera.activated.connect(self._camera_chosen)
        row.addWidget(self.camera)
        self.buffer = QtWidgets.QComboBox()
        self.buffer.addItem('Beauty','beauty')
        self.buffer.addItem('Denoised Beauty','denoised_beauty')
        for key,(label,attributes,channel) in options.AOVS.items():
            self.buffer.addItem(label,key)
        self.buffer.setToolTip('The render buffer shown. Switching does not restart the render.')
        row.addWidget(self.buffer)
        row.addSpacing(5)
        # Exposure and gamma: each a button that puts it back as it was, and its value beside it.
        reset=QtWidgets.QToolButton();reset.setText('EV');reset.setToolTip('Exposure, in stops. Click to put it back to 0.')
        reset.clicked.connect(lambda:self.exposure.setValue(0.0));row.addWidget(reset)
        self.exposure=QtWidgets.QDoubleSpinBox();self.exposure.setRange(-20,20);self.exposure.setSingleStep(.25)
        self.exposure.setKeyboardTracking(False)
        self.exposure.setToolTip('Display exposure in stops. The rendered values are not changed.')
        self.exposure.valueChanged.connect(lambda value:self.display_timer.start())
        row.addWidget(self.exposure)
        reset=QtWidgets.QToolButton();reset.setText('Gamma');reset.setToolTip('Viewing gamma. Click to put it back to 1.')
        reset.clicked.connect(lambda:self.gamma.setValue(1.0));row.addWidget(reset)
        self.gamma=QtWidgets.QDoubleSpinBox();self.gamma.setRange(.1,5.0);self.gamma.setSingleStep(.05);self.gamma.setDecimals(2)
        self.gamma.setValue(self.preferences.get('display_gamma'))
        self.gamma.setToolTip('A gamma for looking at the picture, after its view transform: above 1 lifts the shadows, below 1 deepens them.\nIt is kept with this window, not with the scene, and changes neither the render nor a saved EXR.')
        self.gamma.valueChanged.connect(self._gamma_changed)
        row.addWidget(self.gamma)
        row.addSpacing(5)
        # One channel of the picture at a time: its red, green or blue as greys, or its alpha. A button pressed is
        # lit in its own colour; pressed again it goes out and the whole picture is back.
        self.channels={}
        for key,label,lit,ink,tip in (('r','R','#c0392b','#ffffff','Show the red channel alone, as greys. Click again for the whole picture.'),
                                      ('g','G','#2e9e4f','#ffffff','Show the green channel alone, as greys. Click again for the whole picture.'),
                                      ('b','B','#2f6fd0','#ffffff','Show the blue channel alone, as greys. Click again for the whole picture.'),
                                      ('a','A','#e8e8e8','#101010','Show the alpha channel. Click again for the whole picture.')):
            button=QtWidgets.QToolButton();button.setText(label);button.setCheckable(True);button.setToolTip(tip)
            button.setStyleSheet('QToolButton:checked { background-color: %s; color: %s; border: 1px solid %s; border-radius: 3px; }'%(lit,ink,lit))
            button.clicked.connect(functools.partial(self._channel_clicked,key))
            self.channels[key]=button;row.addWidget(button)
        self._before_alpha=None
        row.addSpacing(5)
        # Draft: the scene as plain lines, which costs nothing to show, for a region to be drawn on and rendered.
        self.draft=QtWidgets.QToolButton();self.draft.setText('Draft');self.draft.setCheckable(True)
        self.draft.setStyleSheet('QToolButton:checked { background-color: #b7a6d9; color: #101010; border: 1px solid #b7a6d9; border-radius: 3px; }')
        self.draft.setToolTip('Show the scene as simple outlines, drawn by MoonLightIPR on the graphics card, and render nothing until a region is drawn with Region: then only that region is rendered, by the engine chosen, among the lines.')
        self.draft.toggled.connect(self._draft_toggled)
        self._draft_image=None;self._draft_render=None;self._draft_engine=False;self._draft_size=(0,0);self._draft_fine=(0,0)
        # The last whole frame shown and the last region rendered, to put back without rendering; and whether
        # pictures the engine goes on sending are kept off the view until something is rendered anew.
        self._whole=None;self._part=None;self._held=False
        row.addWidget(self.draft)
        # A button as the channels' are: lit while only a region is rendered and a drag in the picture draws it.
        self.region_enabled=QtWidgets.QToolButton();self.region_enabled.setText('Region');self.region_enabled.setCheckable(True)
        self.region_enabled.setStyleSheet('QToolButton:checked { background-color: #e08a1e; color: #101010; border: 1px solid #e08a1e; border-radius: 3px; }')
        self.region_enabled.setToolTip('Render only a region of the frame: drag in the picture to draw it. Click again for the whole frame.')
        self.region_enabled.toggled.connect(self._region_toggled)
        row.addWidget(self.region_enabled)
        self.focus_pick=QtWidgets.QToolButton();self.focus_pick.setText('Focus');self.focus_pick.setCheckable(True)
        self.focus_pick.setToolTip('Click, then click a point in the image: the camera focuses on that surface. Right-click the image for Focus Here.')
        self.focus_pick.toggled.connect(self._focus_armed)
        row.addWidget(self.focus_pick)
        gear=self.options_button=QtWidgets.QToolButton();gear.setText('Options');gear.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        gear.setMenu(self._options_menu())
        # Everything stands together from the left, in groups; what room is over is at the right.
        row.addSpacing(5)
        row.addWidget(gear)
        row.addStretch(1)
        # One height for everything in the row, and no more width than each needs: a button is as wide as its word,
        # a channel's is square, and the lists give way first when the window is narrow.
        high=24
        def wide(widget,text,room=14):return widget.fontMetrics().horizontalAdvance(text)+room
        for i in range(row.count()):
            widget=row.itemAt(i).widget()
            if widget is None:continue
            widget.setFixedHeight(high)
            if isinstance(widget,QtWidgets.QToolButton):
                widget.setFixedWidth(high if len(widget.text())==1 else wide(widget,widget.text()))
            elif isinstance(widget,QtWidgets.QDoubleSpinBox):widget.setFixedWidth(62)
        # Wide enough for the longest thing it says.
        self.start.setFixedWidth(wide(self.start,'Continue',28))
        # Room for the menu arrow beside the word, which it otherwise covers.
        gear.setFixedWidth(wide(gear,'Options',34))
        for combo,least,most in ((self.camera,96,170),(self.buffer,96,150)):
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
            combo.setMinimumWidth(least);combo.setMaximumWidth(most)
        # The engines are few and their names short: the list is as wide as the longest, with room for its arrow, and
        # never gives way, so that no name is cut off.
        engine=self.preview_engine
        engine.setFixedWidth(max(wide(engine,engine.itemText(i),40) for i in range(engine.count())))
        return row

    def _options_menu(self):
        menu=self.options_menu=QtWidgets.QMenu(self);menu.setStyleSheet(MENU_STYLE)
        def checkable(target,label):
            # Made here and then added: in Modo's Qt the action a menu makes for a label cannot
            # be used afterwards (it reports as deleted), which stopped IPR from starting.
            action=QtWidgets.QAction(label,self);action.setCheckable(True);target.addAction(action)
            return action
        menu.addAction('Render Settings',self.open_settings)
        menu.addAction('Preview Preferences...',self.edit_preferences)
        menu.addSeparator()
        self.preview_lock=checkable(menu,'Lock Preview')
        self.preview_lock.setToolTip('Hold automatic updates; the current render continues.')
        self.preview_lock.toggled.connect(self._lock_changed)
        from .clay import CHOICES
        clay=self.clay_menu=QtWidgets.QMenu('Preview Material',self);clay.setStyleSheet(MENU_STYLE);menu.addMenu(clay);self.clay_group=QtWidgets.QActionGroup(self)
        for label,key in CHOICES:
            action=checkable(clay,label.replace(' — ',': '));action.setData(key)
            action.setChecked(key==self.preferences.get('clay'));self.clay_group.addAction(action)
        if self.clay_group.checkedAction() is None:self.clay_group.actions()[0].setChecked(True)
        self.clay_group.triggered.connect(self._clay_changed)
        self.show_buckets=checkable(menu,'Show Buckets')
        self.show_buckets.setChecked(self.preferences.get('show_buckets'))
        self.show_buckets.toggled.connect(self._overlay_changed)
        self.worker_tiles=checkable(menu,'Show Worker Tiles')
        self.worker_tiles.setChecked(self.preferences.get('worker_tiles'))
        self.worker_tiles.toggled.connect(self._overlay_changed)
        menu.addSeparator()
        menu.addAction('Compositor...',self.open_compositor)
        menu.addSeparator()
        menu.addAction('Render EXR...',self.render_final)
        menu.addAction('Render Animation...',self.render_animation)
        menu.addAction('MoonLightIPR Playblast...',self.render_playblast)
        menu.addAction('Export Scene...',self.export)
        menu.addSeparator()
        menu.addAction('Render Log...',self.show_log)
        return menu

    def _image_menu(self,point=None):
        menu=QtWidgets.QMenu(self);menu.setStyleSheet(MENU_STYLE)
        if point is not None:
            menu.addAction('Focus Here',lambda:self.focus_at(point))
            menu.addSeparator()
        menu.addAction('Fit',self.preview.fit)
        menu.addAction('Actual Size',self.preview.actual_size)
        menu.addSeparator()
        # Smart Render, chosen here as in the scene's render settings.
        smart=QtWidgets.QMenu('Smart Render',menu);smart.setStyleSheet(MENU_STYLE);smart.setToolTipsVisible(True)
        try:level=self._settings_values()['denoising'].get('smart','off')
        except Exception:level='off'
        from .smart_render import CHOICES as SMART_CHOICES
        for words,key in SMART_CHOICES:
            action=QtWidgets.QAction(words,smart);action.setCheckable(True);action.setChecked(key==level)
            action.setToolTip('MoonRay renders to the end.' if key=='off' else 'The render is stopped once its picture is clean enough for the denoiser, and denoised.')
            action.triggered.connect(lambda checked=False,key=key:self._smart_chosen(key));smart.addAction(action)
        menu.addMenu(smart);self._smart_menu=smart
        # Safe Denoising itself, chosen here as in the scene's render settings: off, or on with one denoiser or the
        # other. The foot of the picture says when it is on. (The menu and its actions are made first and then added:
        # what a menu makes for a label cannot be used afterwards in Modo's Qt.)
        safe=QtWidgets.QMenu('Safe Denoising',menu);safe.setStyleSheet(MENU_STYLE);safe.setToolTipsVisible(True)
        try:chosen=self._settings_values()['denoising']
        except Exception:chosen={}
        now=chosen.get('engine','off') if chosen.get('safe') else 'off'
        for words,engine,tip in (('Off','off','MoonRay renders as usual. A render stopped by hand keeps its beauty and its denoised picture.'),
                                 ('OptiX','optix','MoonRay saves its picture as it renders, so that a render stopped by hand is kept with all its buffers and can be continued; denoised on the graphics card.'),
                                 ('Open Image Denoise','oidn_cpu','The same, denoised on the processor.')):
            action=QtWidgets.QAction(words,safe);action.setCheckable(True);action.setChecked(engine==now);action.setToolTip(tip)
            action.triggered.connect(lambda checked=False,engine=engine:self._safe_chosen(engine));safe.addAction(action)
        menu.addMenu(safe);self._safe_menu=safe
        menu.addSeparator()
        menu.addAction('Copy Image',self.copy_image)
        menu.addAction('Save Image...',self.save_preview)
        # The outputs of the last finished MoonRay preview, each as a picture of its own. MoonLightIPR has the one.
        batch=menu.addAction('Export AOVs as Images...',self.export_buffers)
        batch.setEnabled(self._engine()!='moonlightipr')
        if not batch.isEnabled():batch.setToolTip('MoonLightIPR renders the one picture; choose MoonRay for its outputs.')
        if getattr(self,'_continuable',None) is not None and not self._rendering:
            # Continue is what the button offers; this is the other choice. It throws the stopped render away, so it
            # stands last and apart, and asks before it does.
            menu.addSeparator()
            menu.addAction('Restart Render...',self._render_afresh)
        menu.setToolTipsVisible(True)
        return menu

    def _status_line(self):
        # Two lines. The first is the status, across the whole window, so that a long message is read whole. The
        # second is three cells of one width, as a table of one row: the probe, how the render is getting on, and the
        # picture's details. What is written in one never moves another.
        lines=QtWidgets.QVBoxLayout();lines.setSpacing(2);lines.setContentsMargins(0,0,0,0)
        row=QtWidgets.QHBoxLayout();row.setSpacing(10)
        cells=[]
        for _ in range(3):
            cell=QtWidgets.QWidget();cell.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Preferred)
            inside=QtWidgets.QHBoxLayout(cell);inside.setContentsMargins(0,0,0,0);inside.setSpacing(8)
            row.addWidget(cell,1);cells.append(inside)
        left,middle,right=cells
        self.status = QtWidgets.QLabel('Ready')
        # Each thing it says is noted in the MoonRay Terminal too.
        from . import terminal
        terminal.follow_status(self.status)
        # A long message is cut short rather than widening the window.
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Preferred)
        # What is under the pointer: its place in the picture and its values, at the row's left end.
        self.probe=QtWidgets.QLabel('');self.probe.setTextFormat(QtCore.Qt.RichText)
        self.probe.setToolTip('The pixel under the pointer: its place from the top left, then red, green, blue and alpha.\nLinear values are the render\'s own, before the view transform; display values are what is on screen.')
        # And its colour as it is on screen, in a small square beside the numbers.
        self.swatch=QtWidgets.QLabel('');self.swatch.setFixedSize(14,14);self.swatch.setVisible(False)
        left.addWidget(self.swatch)
        left.addWidget(self.probe)
        left.addStretch(1)
        self.status.setAlignment(QtCore.Qt.AlignCenter)
        lines.addWidget(self.status)
        lines.addLayout(row)
        # How the render is getting on is in the middle of the second line, between the probe and the picture's details.
        self.render_timing=QtWidgets.QLabel('');self.render_timing.setEnabled(False)
        self.render_timing.setAlignment(QtCore.Qt.AlignCenter)
        self.render_timing.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Preferred)
        middle.addWidget(self.render_timing,1)
        self.image_info=QtWidgets.QLabel('');self.image_info.setEnabled(False)
        right.addStretch(1)
        right.addWidget(self.image_info)
        self.notice_toggle=QtWidgets.QToolButton();self.notice_toggle.setText('Notices (0)');self.notice_toggle.setCheckable(True);self.notice_toggle.setAutoRaise(True)
        self.notice_toggle.setToolTip('What the renderer could not carry over from the scene')
        self.notice_toggle.toggled.connect(lambda visible:self.warnings.setVisible(visible))
        right.addWidget(self.notice_toggle)
        return lines

    def _focus_armed(self,armed):
        if armed:
            self.preview.setCursor(QtCore.Qt.CrossCursor)
            self.status.setText('Click the point to focus on.')
        else:self.preview.unsetCursor()

    def eventFilter(self,watched,event):
        # The mode's line keeps its place at the foot of the picture as the picture is made larger or smaller.
        if watched is self.preview and event.type()==QtCore.QEvent.Resize and hasattr(self,'hud') and self.hud.isVisible():self._hud_place()
        # While Focus is armed, the next click in the image picks instead of panning.
        if watched is self.preview and self.focus_pick.isChecked() and event.type()==QtCore.QEvent.MouseButtonPress and event.button()==QtCore.Qt.LeftButton:
            point=event.pos()
            self.focus_pick.setChecked(False)
            self.focus_at(point)
            return True
        return super().eventFilter(watched,event)

    def focus_at(self,point):
        """Set the render camera's focus distance to the surface under a point of the image."""
        try:
            rect=self.preview.image_rect()
            if rect.isEmpty() or not rect.contains(QtCore.QPointF(point)):
                self.status.setText('Click inside the rendered image to set focus.');return
            scene=self._asset_scene
            if not scene or not scene.get('camera'):
                self.status.setText('Render once, then pick the focus point.');return
            from .focus import depth
            distance=depth(scene,(point.x()-rect.left())/rect.width(),(point.y()-rect.top())/rect.height())
            if distance is None:
                self.status.setText('Nothing to focus on there.');return
            camera=scene['camera']
            lx.eval('channel.value %.6f channel:{%s:focusDist}'%(distance,camera['identity']))
            message='Focus distance %.3f m.'%distance
            if not camera.get('dof'):message+=' Depth of field is off on this camera.'
            elif not self._following:message+=' Render to see it.'
            self.status.setText(message)
        except Exception as exc:
            self.status.setText('Cannot set focus: '+str(exc))

    def _clay(self):
        action=self.clay_group.checkedAction()
        return action.data() if action is not None else 'materials'

    def _clay_changed(self,action):
        self.preferences.set('clay',action.data());self._preview_changed(0)

    def _overlay_changed(self,*args):
        self.preferences.set('show_buckets',self.show_buckets.isChecked())
        self.preferences.set('worker_tiles',self.worker_tiles.isChecked())
        self.preview.set_worker_overlay(self.worker_tiles.isChecked())
        self.preview.set_show_buckets(self.show_buckets.isChecked() and not self._following)

    def _preferences_changed(self):
        self.status.setText('Preview preferences saved.')
        self.refine_timer.stop()
        if self._following:self.preview_timer.start()

    def _gamma_changed(self,value):
        self.preferences.set('display_gamma',float(value))
        self.preview.set_gamma(value)

    def _channel_clicked(self,key,*_):
        """A channel's button pressed: lit, it shows that channel; pressed again, the whole picture."""
        self._channel_chosen(key if self.channels[key].isChecked() else 'rgb')

    def _channel_chosen(self,channel):
        """One colour is the picture's own channel shown as greys; alpha is the render's alpha output, shown in the
        picture's place; 'rgb' is the whole picture again."""
        if channel=='a':
            index=self.buffer.findData('alpha')
            if index<0 or self.buffer.view().isRowHidden(index):
                self.status.setText('This engine gives the preview no alpha; choose MoonRay to see it.')
                channel='rgb'
            elif self.buffer.currentData()!='alpha':
                self._before_alpha=self.buffer.currentData()
        # Only the one chosen is lit.
        for key,button in self.channels.items():button.setChecked(key==channel)
        if channel=='a':
            self.buffer.setCurrentIndex(self.buffer.findData('alpha'));self.preview.set_channel('rgb');return
        if self._before_alpha is not None and self.buffer.currentData()=='alpha':
            self.buffer.setCurrentIndex(max(0,self.buffer.findData(self._before_alpha)))
        self._before_alpha=None
        self.preview.set_channel(channel)

    def _region_drawn(self,left,top,right,bottom):
        """A rectangle dragged in the picture is the region to render."""
        region=[round(min(1.0,max(0.0,v)),4) for v in (left,top,right,bottom)]
        if region[2]-region[0]<.005 or region[3]-region[1]<.005:return
        # Marking a region renders nothing: with realtime on it is switched off first, so that the region is not
        # rendered until it is asked for.
        if self._following:self._follow(False)
        self._store(region=region,region_enabled=True)
        self.preview.set_region(region,True)
        self.status.setText('Region set: %d%% to %d%% across, %d%% to %d%% down.'%(region[0]*100,region[2]*100,region[1]*100,region[3]*100))
        # It is only marked, its outline moving round it: Render, or RT, is what renders it.
        self.status.setText('Region marked. Press %s to render it.'%('RT Off' if self._live() else 'Render'))

    def _draft_toggled(self,enabled):
        """Draft on: lines in place of a render, and the whole frame kept in view. Off: the render again."""
        from . import draft
        self.preview.whole=bool(enabled)
        self.preview.paper=draft.PAPER if enabled else None
        if enabled:
            try:self._draft_time=lx.service.Selection().GetTime()
            except Exception:self._draft_time=None
            self._draft_hasty=True
            self._draft_render=None
            self.draft_timer.start()
        else:self.draft_timer.stop()
        if enabled:
            # Draft and realtime are one or the other: Draft switched on takes realtime off, as realtime switched
            # on takes Draft off.
            if self._following:
                self.stop()
                if self._following:self._follow(False)
            self.render_once()
            return
        self._draft_image=self._draft_render=None;self._draft_engine=False;self.preview.nominal=None
        # The render made before the draft is of the scene as it was then. Where the draft has since drawn another
        # scene, or Modo tells of a change not yet looked at, that render is stale and is not put back.
        stale=self._whole is not None and (getattr(self,'_whole_digest',None)!=self.last_digest or self.changes.full or bool(self.changes.items))
        if self._whole is not None and not stale:
            # Shown again as it was; nothing is rendered, the scene being the same.
            self._paste()
            self.status.setText('Draft off.');return
        # Nothing to put back: the lines are not left standing as though they were a render.
        self._whole=None;self._part=None
        self._held=True
        self.preview.clear();self.image_info.setText('')
        if self._following:self.preview_timer.start()
        else:self.status.setText('Draft off. The scene has changed since it was rendered: press Render for the picture.' if stale
                                 else 'Draft off. Press Render for the picture.')

    def _draft_tick(self):
        """While Draft is on: redraw its outlines when the scene changes, without being asked. With realtime on the
        scene is being followed already and this has nothing to do."""
        if self.disposed or not self.draft.isChecked():
            self.draft_timer.stop();return
        if self._following or self.preview_lock.isChecked() or self._output_busy() or not self.changes.registered:return
        try:
            from .interaction import dragging
            # A drag is waited out, and the scene drawn as it is when the button comes up: what is shown is then always
            # the outcome of an edit, never something part way through one.
            if dragging():return
            held=False
            if not held:self._draft_drag_read=False
            # One picture at a time: the next is begun when this one is shown, so that each is seen and none piles up
            # behind another.
            if self._rendering:return
            # Nor is an animation playing in Modo drawn frame by frame: the frame it stops on is.
            if not self._time_settled():return
            time=lx.service.Selection().GetTime()
            moved=time!=getattr(self,'_draft_time',time)
            if not (self.changes.full or self.changes.items or moved):
                # Nothing new. Outlines drawn in haste during a drag are drawn again with care once it is over.
                if not held and getattr(self,'_draft_hasty',False) and getattr(self,'_kept_capture',None) is not None:
                    self._draft_hasty=False
                    self._draft_submit(self._kept_capture)
                return
            if self._engine()=='moonlightipr' and self.preferences.get('preview_motion'):
                if held:return
                self._draft_time=time
                self.render_once();return
            # Reading every mesh out of Modo again is most of what a redraw takes (a second of 1.3 on a scene of 266
            # meshes), and most edits leave the meshes as they are. As when a scene is followed, only what the
            # edit touched is read again: where things stand, a material, the meshes named, or all of it.
            import modo
            full,items=self.changes.consume()
            reuse=not full and not moved and bool(items) and self._geometry_cache is not None and modo.Scene().renderItem.id==self._scene_id
            if reuse:
                from .incremental import classify
                reuse=classify(modo.Scene(),items,self._geometry_cache)
            if held and reuse not in (True,'transforms','materials'):
                if getattr(self,'_draft_drag_read',False):
                    # A drag is followed as it goes, picture after picture, where that takes only asking where things
                    # now stand or how they are shaded. One that needs the meshes read again waits for the button
                    # to come up: what Modo told of is put back to be looked at then.
                    self.changes.full=self.changes.full or full;self.changes.items.update(items);return
                # But the first step of a drag often makes something new in the scene (an item's first move gives it
                # a place of its own), which needs the scene read whole. That is done once in a drag, so that the
                # rest of it can be followed.
                self._draft_drag_read=True
            self._draft_time=time
            # In the middle of a drag the outlines are drawn in fewer passes, so that more pictures of it are shown.
            # A change is shown first in a quick, small picture, and then, once that is up and nothing more has
            # changed, in a fine one.
            self._draft_hasty=True
            self._draft_submit(self._capture(reuse))
        except Exception as exc:
            self._draft_quiet=False
            self.status.setText('Draft could not follow the scene: '+str(exc))

    def _draft_submit(self,scene):
        """Redraw the draft for a change it followed by itself. Nothing in the window but the picture changes: no
        status, bar or button comes and goes with each picture, which made following look like starting over."""
        self._draft_quiet_asked=True
        try:self._submit(scene)
        except Exception:
            self._draft_quiet=False;raise

    def _draft_region(self):
        values=self._settings_values()
        region=values['region'] if values['region_enabled'] else None
        return tuple(region) if region and tuple(region)!=(0.0,0.0,1.0,1.0) else None

    def _draft_show(self):
        """The lines, with the last render of the region now set laid on them."""
        from . import draft
        region=self._draft_region()
        rendered=self._draft_render[1] if self._draft_render and self._draft_render[0]==region else None
        self.preview.set_image(draft.over(self._draft_image,rendered,region))
        # A draft is not of a size worth naming: it is drawn small and then finely, and is not the render.
        self.image_info.setText('Draft')

    def _probe(self,x,y):
        """Say what is under the pointer: the render's own linear values where they are held, else what is on screen."""
        if x<0 or self.preview.image.isNull():
            self.probe.setText('');self.swatch.setVisible(False);return
        # A draft is drawn finer than it is spoken of: the place given is found again in the picture as it is drawn.
        named=self.preview.nominal or (self.preview.image.width(),self.preview.image.height())
        shown=QtGui.QColor(self.preview.image.pixel(min(self.preview.image.width()-1,x*self.preview.image.width()//named[0]),min(self.preview.image.height()-1,y*self.preview.image.height()//named[1])))
        self.swatch.setStyleSheet('background-color: %s; border: 1px solid #101010;'%shown.name());self.swatch.setVisible(True)
        import struct
        frame=self.renderer.buffers.displayed or {}
        def linear(key,count):
            # A buffer held in memory is rows of three floats, the bottom row first.
            held=(frame.get('linear') or {}).get(key) or ((self.renderer.buffers.progressive_frames.get(key) or {}).get('linear') or {}).get(key)
            if not held or (held[0],held[1])!=(self.preview.image.width(),self.preview.image.height()):return None
            try:return struct.unpack_from('<3f',held[2],((held[1]-1-y)*held[0]+x)*12)[:count]
            except struct.error:return None
        values=linear(frame.get('key','beauty'),3)
        alpha=linear('alpha',1)
        kind='linear'
        if values is None:
            values,kind=(shown.redF(),shown.greenF(),shown.blueF()),'display'
        # Each value in its own colour: red, green, blue, and alpha in white.
        parts=['<span style="color:#8a8f99">%d, %d</span>'%(x,y)]
        parts+=['<span style="color:%s">%s&nbsp;%.4f</span>'%(ink,name,value) for name,ink,value in zip('RGB',('#ff5f52','#55d27a','#5b9bff'),values)]
        if alpha:parts.append('<span style="color:#ffffff">A&nbsp;%.4f</span>'%alpha[0])
        parts.append('<span style="color:#8a8f99">%s</span>'%kind)
        self.probe.setText('&nbsp;&nbsp;'.join(parts))

    def _region_toggled(self,enabled):
        # Switched on, the button only readies the drag: nothing is rendered anew until a region is drawn.
        # Switched off, the region is forgotten, so that the next one is drawn from nothing.
        self._region_armed=bool(enabled)
        # The Region tool takes realtime off: a region is marked and then rendered when asked, not as it is drawn.
        if enabled and self._following:
            self._follow(False)
            self.status.setText('Realtime is off while a region is marked. Press RT Off to render it.')
        self.preview.set_region(None,enabled)
        if enabled or not self._settings_values()['region_enabled']:return
        self._store(region=[0.0,0.0,1.0,1.0],region_enabled=False)
        self._settled()
        if self.draft.isChecked():
            # The lines are drawn over where the region was, which costs nothing.
            if self._following:self.preview_timer.start()
            else:self.render_once()
        # Nothing is rendered for it: the whole frame as it last was comes back, with the region as it was rendered.
        else:self._paste()

    def _settled(self):
        """Take the scene's settings as they now are for seen, so that following does not render for them."""
        self._live_settings={k:v for k,v in self._settings_values().items() if k not in ('display','preview_buffer','aovs','recovery','denoising','compositor')}

    def _paste(self):
        """Show the last whole frame with the last region rendered laid in it, and keep it until something is rendered."""
        from . import draft
        whole,part=self._whole,self._part
        if whole is None:return
        self._held=True
        self.preview.set_image(draft.over(whole,part[1],part[0]) if part is not None and part[1].size()==whole.size() else whole)
        self.image_info.setText('%d x %d'%(whole.width(),whole.height()))

    def _camera_chosen(self,index):
        try:lx.eval('moonray.camera %d'%index)
        except Exception as exc:self.status.setText('Cannot change the camera: '+str(exc));return
        self._sync_cameras()
        if self._following:self.preview_timer.start()
        else:self.status.setText('Applies to the next render.')

    def _sync_cameras(self):
        """List the cameras the scene can be rendered through, with the one in use chosen."""
        from . import camera_choice
        try:entries,current=camera_choice.choices(),camera_choice.current()
        except Exception:return
        if entries==getattr(self,'_cameras',None) and current==self.camera.currentData():return
        self._cameras=entries;blocker=QtCore.QSignalBlocker(self.camera)
        self.camera.clear()
        for label,identity in entries:self.camera.addItem(label,identity)
        self.camera.setCurrentIndex(max(0,self.camera.findData(current)));del blocker

    def _commit_exposure(self):
        if self.disposed:return
        display=self._settings_values()['display']
        if abs(display['exposure']-self.exposure.value())<1e-9:return
        self._store(display=dict(display,exposure=self.exposure.value()))
        self._buffer_changed(0)

    # Settings: the scene's, and how the window follows them

    def _view_words(self):
        """How the picture is shown, in a few words: the view transform and the LUT, for the foot of the window."""
        try:
            from pathlib import Path
            from . import modo_color
            held=self._settings_values()['display'];view=held.get('view','modo')
            if view=='modo':
                read=modo_color.RESOLVED
                words='Modo: %s, %s'%(read.get('name',''),read['view']) if read else 'sRGB'
            elif view=='ocio':words='OCIO: %s, %s'%(held.get('display',''),held.get('ocio_view',''))
            else:words={'aces':'ACES','srgb':'sRGB','reinhard':'Highlight compression','raw':'Raw linear'}.get(view,str(view))
            if held.get('lut'):words+=' + LUT '+Path(held['lut']).name
            return words
        except Exception:return ''

    def _smart_on(self):
        """Whether Smart Render is on for the scene."""
        try:return self._settings_values()['denoising'].get('smart','off')!='off'
        except Exception:return False

    def _settings_values_stored(self):
        try:return properties.scene_settings()
        except Exception:return {}

    def _settings_values(self):
        # Modo's own colour management is read here, where Modo may be asked: the display code takes what was read.
        try:
            from . import modo_color
            modo_color.refresh()
        except Exception:pass
        values=scene_settings.complete(self._settings_values_stored())
        values['preview_buffer']=self.buffer.currentData()
        return values

    def runtime_path(self):
        return self.preferences.get('runtime')

    def _poll(self):
        """Follow the scene's settings, which are edited in Modo's properties, not here."""
        if self.disposed:return
        try:
            import modo
            scene_id=modo.Scene().renderItem.id
            values=self._settings_values()
        except Exception:return
        if scene_id!=self._scene_id:
            self._scene_id=scene_id;self._geometry_cache=None;self._shown=None
        self._sync_cameras()
        self._hud_update()
        from . import modo_color
        # With what was read of Modo's own colour management: changed in Modo, the picture is shown again by it.
        filters=self._display_filter_buffers()
        watched=(values['display'],values['denoising'],values['custom_aovs'],values['asset_settings'].get('working_space'),values['region_enabled'],repr(values['compositor']),repr(modo_color.RESOLVED),filters)
        if watched==self._shown:return
        previous,self._shown=self._shown,watched
        self._sync_output_menu(values['custom_aovs'],filters)
        # The Composite buffer is made again by the graph as it now is, of the render that is kept.
        self.renderer.buffers.compositor.request(values['compositor'])
        if not self.display_timer.isActive():
            blocker=QtCore.QSignalBlocker(self.exposure);self.exposure.setValue(values['display']['exposure']);del blocker
        # The button is lit by a region being rendered, or by its being ready for one to be drawn.
        armed=values['region_enabled'] or getattr(self,'_region_armed',False)
        blocker=QtCore.QSignalBlocker(self.region_enabled);self.region_enabled.setChecked(armed);del blocker
        self.preview.set_region(values['region'] if values['region_enabled'] else None,armed)
        if previous is None:return
        if previous[1]!=watched[1]:self._denoising_changed()
        # The graph changed while the Composite is the buffer chosen: it is shown, or said to be nothing yet.
        if previous[0]!=watched[0] or previous[3]!=watched[3] or previous[6]!=watched[6] or (previous[5]!=watched[5] and self.buffer.currentData()=='composite'):self._buffer_changed(0)

    def _smart_chosen(self,level):
        """Smart Render chosen from the picture's menu: written to the scene's settings."""
        try:
            from .denoising import one_or_other
            stored=dict(self._settings_values()['denoising']);was=stored.get('safe');stored['smart']=level
            one_or_other(stored,'smart')
            if not self._store(denoising=stored):return
        except Exception as exc:
            self.status.setText('Cannot set Smart Render: '+str(exc));return
        self._hud_update()
        self.status.setText('Smart Render is off.' if level=='off' else 'Smart Render is on: a MoonRay render stops once it is clean enough for the denoiser.'
                            +(' Safe Denoising is switched off.' if was else ''))

    def _safe_chosen(self,engine):
        """Safe Denoising chosen from the picture's menu: off, or on with a denoiser. Written to the scene's settings,
        as its render settings write them: the denoiser itself is left as it is when Safe Denoising is switched off."""
        try:
            from .denoising import one_or_other
            stored=dict(self._settings_values()['denoising']);was=stored.get('smart','off')!='off'
            if engine=='off':stored['safe']=False
            else:stored.update(engine=engine,safe=True)
            one_or_other(stored,'safe')
            if not self._store(denoising=stored):return
        except Exception as exc:
            self.status.setText('Cannot set Safe Denoising: '+str(exc));return
        self._hud_update()
        self.status.setText('Safe Denoising is off.' if engine=='off' else 'Safe Denoising is on, with %s.'%('OptiX' if engine=='optix' else 'Open Image Denoise')+(' Smart Render is switched off.' if was else ''))

    def _hud_words(self):
        """The modes worth saying at the foot of the picture: each a line."""
        words=[]
        try:
            values=self._settings_values()
            if self.preview_engine.currentData()=='moonray' and values['denoising'].get('safe') and values['denoising'].get('engine','off')!='off':
                words.append('Safe Denoiser')
            level=values['denoising'].get('smart','off')
            if self.preview_engine.currentData()=='moonray' and level!='off':
                from .smart_render import LEVELS
                watch=getattr(self.renderer,'smart',None)
                read=getattr(watch,'noise',None) if self._rendering else None
                # While it renders: how noisy the picture reads now, and at what it will be stopped.
                # Before there is a reading (a pass's first seconds, while the picture is still coarse), it says so.
                words.append('Smart Render: noise %.1f%%, stops at %.1f%%'%(100*read,100*LEVELS[level]) if read is not None
                             else 'Smart Render: stops at %.1f%% noise'%(100*LEVELS[level]) if self._rendering and watch is not None
                             else 'Smart Render')
        except Exception:pass
        return words

    def _hud_update(self):
        if self.disposed or not hasattr(self,'hud'):return
        words=self._hud_words()
        text='\n'.join(words)
        if text!=self.hud.text():self.hud.setText(text);self.hud.adjustSize()
        self.hud.setVisible(bool(words))
        if words:self._hud_place();self.hud.raise_()

    def _hud_place(self):
        """At the foot of the picture, in the middle."""
        self.hud.move(max(0,(self.preview.width()-self.hud.width())//2),max(0,self.preview.height()-self.hud.height()-12))

    def open_compositor(self):
        """The scene's compositor: a graph over the buffers of a finished render, whose output is the Composite buffer."""
        try:
            from .compositor_editor import open_editor
            open_editor(self)
        except Exception as exc:
            self.status.setText('Cannot open the compositor: '+str(exc))

    def _display_filter_buffers(self):
        """The scene's display filters that render, as (name, buffer): each is a picture of its own."""
        import modo
        from . import entities
        from .host import render_visible
        result=[]
        for name in entities.classes('displayfilter'):
            try:result+=[(item.name,entities.filter_key({'identity':item.id})) for item in modo.Scene().items(entities.item_type(name),superType=False) if render_visible(item)]
            except (LookupError,RuntimeError,TypeError,AttributeError):pass
        return tuple(sorted(result))

    def _sync_output_menu(self,custom_aovs,filters=()):
        names=[(v['name'],v['name']) for v in custom_aovs if v['kind']!='cryptomatte']
        names+=list(filters)
        held={v.get('category','object'):v['name'] for v in custom_aovs if v['kind']=='cryptomatte'}
        names+=[(label,held.get(category,'crypto_'+category)) for category,label in CRYPTOMATTES]
        # The compositor's picture, first after MoonRay's own buffers. It is always listed; chosen while the scene's
        # graph does nothing, it says where to make one that does.
        names.insert(0,('Composite','composite'))
        if 'asset' in held:names.append(('Cryptomatte: Assets',held['asset']))
        base=2+len(options.AOVS)
        if names==[(self.buffer.itemText(i),self.buffer.itemData(i)) for i in range(base,self.buffer.count())]:return
        key=self.buffer.currentData();blocker=QtCore.QSignalBlocker(self.buffer)
        while self.buffer.count()>base:self.buffer.removeItem(self.buffer.count()-1)
        for label,name in names:self.buffer.addItem(label,name)
        gone=self.buffer.findData(key)<0
        self.buffer.setCurrentIndex(max(0,self.buffer.findData(key)));del blocker
        # The buffer that was shown is no longer in the list (the Composite, its graph emptied): the beauty is shown.
        if gone:self._buffer_changed(self.buffer.currentIndex())
        self._limit_buffers()

    def _engine(self):
        """The renderer behind the engine chosen: MoonRay LS is MoonRay."""
        chosen=self.preview_engine.currentData()
        return 'moonray' if chosen=='moonray_ls' else chosen

    def _live(self):
        """Whether the engine chosen is the realtime one, which follows the scene as it is edited."""
        return self.preview_engine.currentData()=='moonlightipr'

    def _low(self):
        """Whether the engine chosen is MoonRay LS: MoonRay rendering once, small and at few samples."""
        return self.preview_engine.currentData()=='moonray_ls'

    def _engine_changed(self,index):
        live=self._live()
        # Whatever was rendering or being followed is stopped: nothing renders for a change of engine. A realtime
        # engine is chosen with realtime off, and is switched on with its button, so that none starts by accident.
        if not self.disposed and not self._output_busy() and (self._following or self._rendering):self.stop()
        # Choosing an engine never switches realtime on, whatever is rendering as it is chosen (a draft's lines may
        # be): only its button does. Chosen with a render still stopping, a realtime engine took that render for
        # one to carry on from, and came on with Draft still on.
        self._choosing_engine=True
        try:
            if self.ipr_mode.isChecked()!=live:self.ipr_mode.setChecked(live)
        finally:self._choosing_engine=False
        if self._following and not self.disposed:self._follow(False)
        if live and not self.disposed:self.status.setText('Realtime is off. Press RT Off to switch it on.')
        if not self.disposed and self.draft.isChecked() and not self._output_busy():
            # A draft's region is rendered by the engine chosen: with another engine it is drawn again.
            self._draft_hasty=True
            QtCore.QTimer.singleShot(0,lambda:None if self.disposed or not self.draft.isChecked() else self.render_once())
        self._set_rendering(self._rendering)
        # MoonLightIPR follows edits as they happen, so look for them more often.
        self.timer.setInterval(60 if self._engine()=='moonlightipr' else 150)
        self._limit_buffers()

    def _limit_buffers(self):
        """MoonLightIPR makes the beauty and, where it is asked for, a denoised beauty: the list then holds those two.
        It shows the beauty unless the denoised one is chosen by hand, and choosing it is what has MoonLightIPR
        denoise. The other buffers are MoonRay's."""
        only=self._engine()=='moonlightipr'
        denoises=self._moonlightipr_denoises()
        self.buffer.setItemText(0,'Beauty')
        # MoonRay LS is a quick look: the beauty alone.
        low=self._low()
        for row in range(1,self.buffer.count()):
            self.buffer.view().setRowHidden(row,low or (only and not (denoises and self.buffer.itemData(row)=='denoised_beauty')))
        if low:
            if self.buffer.currentData()!='beauty':self.buffer.setCurrentIndex(self.buffer.findData('beauty'))
            return
        if not only:return
        shown=self.buffer.currentData()
        # The beauty is what is shown. The denoised picture is for whoever is looking to choose, and stays chosen
        # for as long as there is one.
        wanted='denoised_beauty' if denoises and shown=='denoised_beauty' and self._buffer_picked=='denoised_beauty' else 'beauty'
        if shown!=wanted:self.buffer.setCurrentIndex(self.buffer.findData(wanted))

    def _moonlightipr_denoises(self):
        """Whether MoonLightIPR's list has the denoised beauty in it: always. It denoises with the graphics card's own
        denoiser, whatever the scene's denoiser is set to, when that buffer is the one chosen."""
        return True

    def _engine_notices(self,messages):
        """Add what the preview engine left out to the notices of the scene it is showing."""
        snapshot=(self.renderer.active or {}).get('snapshot',{})
        self._set_notices(list(snapshot.get('warnings',[]))+list(messages))

    def _set_notices(self,messages):
        unique=list(dict.fromkeys(str(message) for message in messages if message))
        text='\n\n'.join(unique)
        if text!=self.warnings.toPlainText():self.warnings.setPlainText(text)
        self.notice_toggle.setText('Notices (%d)'%len(unique))
        # The button says at a glance that there is something to read: pastel yellow for notices, red where one
        # of them is an error or a render has failed.
        failed=bool(getattr(self,'_failure',None)) or any(notice_is_error(message) for message in unique)
        self.notice_toggle.setStyleSheet(NOTICE_STYLE%(('#e9938c','#2a0f0d') if failed else ('#f2e3a3','#2b2610')) if unique or failed else '')
        self.notice_toggle.setToolTip('A render failed, or a notice is an error: open to read it.' if failed else
                                      'The renderer has something to say about the scene: open to read it.' if unique else 'Nothing to report.')
        # Where the preferences ask for it, the notices open by themselves when there is something to read.
        if unique and not self.notice_toggle.isChecked() and self.preferences.get('notices_open'):self.notice_toggle.setChecked(True)

    def _ipr_changed(self,enabled):
        self.preferences.set('ipr',bool(enabled))
        if enabled:
            if self._rendering and not self._output_busy() and not getattr(self,'_choosing_engine',False):
                # Turned on during a preview: carry on from it.
                self._follow(True)
                self.status.setText('Following the scene.')
            else:self.status.setText('Realtime: the preview follows the scene.')
        else:
            was=self._following
            self._follow(False)
            self.status.setText('IPR off.' + (' The current pass may finish.' if was and self._rendering else ''))

    def _follow(self,following):
        """Start or stop following the scene's edits."""
        self._following=bool(following)
        self.refine_timer.stop();self.preview_timer.stop();self.timer.stop()
        self._pending_preview=False;self.release_timer.stop()
        self.preview.set_show_buckets(self.show_buckets.isChecked() and not self._following)
        if self._following:
            self.renderer.buffers.denoiser.close()
            if self.buffer.currentData()=='denoised_beauty' and self._engine()!='moonlightipr':
                self.buffer.setCurrentIndex(self.buffer.findData('beauty'))
            if not self.preview_lock.isChecked():self.timer.start()
        self._set_rendering(self._rendering)

    def _output_busy(self):
        return (self.sequence is not None and self.sequence.running) or bool(self.renderer.pending and self.renderer.pending.get('output')) or bool(self.renderer.active and self.renderer.active.get('output') and self.renderer.process.state()!=QtCore.QProcess.NotRunning)

    def _lock_changed(self,locked):
        if locked:
            self.timer.stop();self.preview_timer.stop()
            self.status.setText('Preview locked.')
        else:
            self.status.setText('Preview unlocked.')
            if self._following:self.timer.start();self._live_tick()

    # Capturing the scene

    def _playblasting(self):
        """The playblast that is running, if one is."""
        from .playblast import Playblast
        return self.sequence if isinstance(self.sequence,Playblast) and self.sequence.running else None

    def _time_settled(self):
        """Whether the scene's time has stood still for a moment. While Modo plays an animation it has not, and
        the preview waits: it shows the frame the playing stops on, not each one it passes."""
        import time as clock
        time=lx.service.Selection().GetTime();now=clock.monotonic()
        if time!=getattr(self,'_seen_time',time):self._time_moved=now
        self._seen_time=time
        return now-getattr(self,'_time_moved',0.0)>=PLAYBACK_REST

    def _dimensions(self, scene, final=False):
        """The size a render is made at. MoonRay, chosen as the engine, renders the picture itself: at the camera's
        resolution, or the scene's where the camera does not override it. MoonRay LS and MoonLightIPR are previews, at the
        preview size and never wider than it, however large the picture is to be."""
        scene_w, scene_h = scene['width'], scene['height']
        size=self.preferences.get('preview_size')
        if size<=0:size=640
        width = scene_w if final or not (self._live() or self._low()) else min(scene_w,size)
        # A playblast has a width of its own, whichever engine is chosen.
        blast=None if final else self._playblasting()
        if blast is not None:width=min(scene_w,blast.width)
        return width, max(16, round(width * scene_h / max(1, scene_w)))

    def _capture(self,reuse=False,transform_items=None):
        import modo
        if modo.Scene().renderItem.id != self._scene_id:
            self._scene_id=modo.Scene().renderItem.id;self._geometry_cache=None
        scene = host.snapshot(evaluated_geometry=self._settings_values()['surface'] == 2,reuse_geometry=self._geometry_cache if reuse else None,refresh_materials=reuse=='materials' or isinstance(reuse,dict),dirty_meshes=reuse.get('dirty_meshes') if isinstance(reuse,dict) else None)
        if reuse=='transforms':
            from .incremental import refresh_transforms
            refresh_transforms(modo.Scene(),scene,transform_items)
        import copy,time
        full_capture=scene.pop('_full_capture',not reuse)
        if not reuse or reuse in ('materials','transforms') or isinstance(reuse,dict):
            # What was found of the meshes when they were last read whole holds while they are only moved or shaded anew.
            stand=self._geometry_cache.get('_item_transforms') if self._geometry_cache is not None and reuse in ('materials','transforms') else None
            self._geometry_cache=dict(scene,meshes=[dict(m) for m in scene['meshes']],materials=copy.deepcopy(scene['materials']),native_materials=copy.deepcopy(scene.get('native_materials',{})))
            if stand:self._geometry_cache['_item_transforms']=True
        if full_capture or isinstance(reuse,dict):self._last_full_capture=time.monotonic()
        if full_capture and self._geometry_cache is not None and scene.get('_evaluated_data') is not None:
            # Whether each evaluated mesh stands where its item does, which lets a later move of an item be followed
            # without evaluating every mesh again. Not so for copies Modo generates, which are no item's.
            self._geometry_cache['_item_transforms']=self._stand_with_items(modo.Scene(),scene)
        scene.pop('_evaluated_data',None)
        scene['_geometry_revision']=str(id(self))+':'+str(self._last_full_capture)
        configured=self._configure_snapshot(scene)
        self._asset_scene=configured
        # Which files the scene names, and how they stand on disk, is looked into when the scene was read: not when
        # only where things stand was asked again, which names no new file. Looking walks the whole scene.
        if reuse not in (True,'transforms') or not self._asset_signature:
            from .assets import signature
            self._asset_signature=signature(configured)
        return configured

    def _stand_with_items(self,document,scene):
        from .host import world_matrix
        try:
            if document.items('replicator',superType=False) or document.items('meshInst',superType=False):return False
            if scene.get('extra_geometry'):return False
            where={}
            for mesh in scene['meshes']:
                if 'instances' in mesh:return False
                identity=mesh.get('source_item') or mesh['identity'].split('|')[0]
                if identity not in where:where[identity]=world_matrix(document.item(identity))
                held=mesh.get('matrix')
                if not held or len(held)!=16 or any(abs(a-b)>1e-5*max(1.0,abs(b)) for a,b in zip(held,where[identity])):return False
            return bool(where)
        except Exception:return False

    def _capture_output(self):
        values=self._settings_values()
        if not values['final_motion']:return self._capture()
        from .animation import capture_current
        return self._configure_snapshot(capture_current(values['surface']==2))

    def _capture_preview(self):
        if self._engine()!='moonlightipr' or not self.preferences.get('preview_motion'):return self._capture()
        from .animation import capture_current
        scene=self._configure_snapshot(capture_current(self._settings_values()['surface']==2))
        # Stepping through the shutter is not an edit for IPR to follow.
        self.changes.consume()
        return scene

    def _configure_snapshot(self, scene):
        values = self._settings_values()
        scene['render_settings'] = values['render']
        scene['scene_variables'] = values['scene_variables']
        # The compositor's graph goes with the scene so that a render to a file can write its composite beside it.
        scene['compositor'] = values['compositor']
        scene['aovs'] = values['aovs']
        scene['production']=values['production']
        scene['asset_settings']=values['asset_settings']
        from .extra_geometry import attach as attach_geometry
        attach_geometry(scene,values['production'])
        scene['custom_aovs']=values['custom_aovs']
        scene['recovery']=values['recovery']
        # Kept out of a scene that does not ask for it, so that a checkpoint saved before still matches.
        if values['deep']['enabled']:scene['deep']=values['deep']
        # Likewise the EXR's compression, where it is not MoonRay's zip.
        if values['exr']!={'compression':1,'dwa_level':85.0}:scene['exr']=values['exr']
        scene['preview_buffer'] = values['preview_buffer']
        scene['execution_mode'] = values['execution_mode']
        scene['denoising'] = values['denoising']
        from .display import values as display_values
        scene['display'] = display_values(dict(values['display'],working_space=values['asset_settings'].get('working_space','rec709')))
        if scene['display']['working_space']=='acescg':
            if scene['display']['view']=='ocio' and scene['display']['source']=='Linear Rec.709 (sRGB)':scene['display']['source']='ACEScg'
            scene['warnings'].append('ACEScg color boundaries are enabled. Native spectral presets and volume color grids must be authored for this working space; color parity is not yet validated.')
        if values['region_enabled']:
            scene['region'] = values['region']
        if not values['modo_environment']:
            scene['environments']=[]
        for environment in scene.get('environments',[]):
            environment['intensity'] *= values['environment_multiplier']
        from .background import apply as apply_background
        apply_background(scene,values['background'])
        for light in scene['lights']:
            light['intensity'] *= values['light_multiplier']
        for mesh in scene['meshes']:
            if mesh.get('object_override'):
                continue
            # Dormant UI settings must not change the rendered-scene digest.
            if 'geometry_settings' in mesh:mesh['geometry_settings']={'override':False}
            if values['surface'] == 1:
                mesh['subdivision'] = True
            mesh['subdivision_level'] = values['subdivision_level']
        if values['surface'] == 1:
            scene['warnings'].append('Smooth subdivision rounds all exported meshes, including sharp edges.')
        # A mesh light with no mesh, or a name several meshes share, lights nothing in either engine: say so.
        from . import entities
        entities.mesh_lights(scene,scene['warnings'])
        self._set_notices(scene['warnings'])
        return scene

    # Rendering

    def _render_or_stop(self):
        if self._rendering or self._following:self.stop()
        else:self.start_render()

    def start_render(self):
        """What the Render button does: one render, or with IPR on, a render that keeps following."""
        if self._output_busy():
            self.status.setText('Output render is running. Press Stop before starting a preview.');return
        # Render, or realtime switched on, is asking for the picture itself: Draft, where it is on, goes off first.
        if self.draft.isChecked():self.draft.setChecked(False)
        if self.ipr_mode.isChecked():self._follow(True)
        # What failed before is no longer the news.
        self._failure=None
        # A render begun by hand begins from an empty view, unless it turns out to be one continued.
        self._clear_first=True
        self.render_once()

    def _set_rendering(self,rendering):
        """Keep the Render button saying what pressing it will do."""
        self._rendering=bool(rendering)
        # The crest breathes while a render is on its way and nothing is shown yet.
        if hasattr(self.preview,'set_waiting'):self.preview.set_waiting(self._rendering)
        from . import terminal
        terminal.working(self._rendering)
        if getattr(self,'_draft_quiet',False):return
        active=self._rendering or self._following
        again=not active and getattr(self,'_continuable',None) is not None
        if self._live():
            # A realtime engine is switched on and off, not started and stopped.
            # RT for realtime. While it is on the button stays pressed in, as a switch that is on does.
            # A draft's lines, or its region, being rendered is not realtime being on: with Draft on the button
            # says only whether the scene is being followed.
            if self.draft.isChecked():active=self._following
            self.start.setText('RT On' if active else 'RT Off')
            self.start.setCheckable(True);self.start.setChecked(active)
            self.start.setToolTip('Realtime is on: the preview follows the scene as you edit it. Press to switch it off.' if active
                                  else 'Realtime is off: the preview is not following the scene. Press to switch it on.')
            return
        self.start.setChecked(False);self.start.setCheckable(False)
        self.start.setText('Stop' if active else 'Continue' if again else 'Render')
        self.start.setToolTip(STOP_TIP if active else 'Take the stopped render up again from where it was stopped. If the scene has changed since, it is rendered from the start. '
                              'Right-click the picture for Restart Render.' if again else RENDER_TIP)

    def _submit(self, scene, output=None, refining=False, digest=None):
        # MoonLightIPR denoises when its denoised beauty is the buffer chosen, as of now.
        self.renderer.moonlightipr_wanted=self.buffer.currentData()=='denoised_beauty'
        # And gathers as many samples a pixel as the preferences say; a playblast has its own number.
        self.renderer.moonlightipr_preview_samples=self.preferences.get('moonlightipr/samples')
        # Whether this is a draft redrawing by itself, for which the window is left as it is. The region that follows
        # a draft's lines is of the same redraw; anything else asked for is not.
        asked=getattr(self,'_draft_quiet_asked',False);self._draft_quiet_asked=False
        if output or not getattr(self,'_draft_pass',False):self._draft_quiet=bool(asked and not output)
        self.refine_timer.stop()
        if not output and not refining:
            # The newest reading of the scene, whichever way it was come by (a render asked for, or an edit
            # followed): the one that may be used again while nothing changes. Kept only from here, so that it is
            # never an older one than the picture on screen was made from.
            try:self._kept_capture=scene;self._kept_key=self._capture_key()
            except Exception:self._kept_capture=None
        if not output:
            self._held=False;self._draft_engine=self._draft_lines=False
            region_pass,self._draft_pass=getattr(self,'_draft_pass',False),False
            if not region_pass:self._draft_then=None
        if not output and not self.draft.isChecked():self._draft_fine=(0,0)
        if not output and self.draft.isChecked() and not region_pass:
            # The draft is always MoonLightIPR's: outlines of what the camera sees first, found on the graphics
            # card at no cost however heavy the scene, and drawn finer than the preview. The lines are drawn
            # first, over the whole frame; the engine chosen then renders the region at the preview's own size,
            # and that is laid on them.
            self._draft_engine=self._draft_lines=True
            # The region is rendered after the fine picture, not after the quick one before it.
            # A region marked on a draft is not rendered by the draft: it waits for Render or RT.
            self._draft_then=None
        if not output:
            from .incremental import surroundings
            self._surroundings=surroundings(scene)
        self._set_rendering(True)
        self._ipr_refine_scene=scene if not output else None
        values=self._settings_values();get=self.preferences.get
        width, height = self._dimensions(scene, bool(output))
        original_digest=digest or self._digest(scene)
        if not output:scene=dict(scene,_clay_preview=self._clay())
        if self._draft_engine:scene=dict(scene,_draft=2,_draft_samples=3 if (getattr(self,'_draft_hasty',False) and not self._following) else 12)
        if not output and self.draft.isChecked():
            # The picture is spoken of at the size the camera renders it, however finely its lines are drawn.
            self._draft_size=(width,height);self.preview.nominal=(width,height)
        engine='moonray' if output else 'moonlightipr' if self._draft_engine or self._playblasting() is not None else self._engine()
        # Continue: the same scene as the render that was stopped and kept, taken up where it stood.
        resume=bool(not output and not refining and engine=='moonray' and getattr(self,'_continuable',None) is not None and self._continuable==original_digest)
        if not output:self._continuable=None;self._kept_note=''
        if not output and getattr(self,'_clear_first',False):
            self._clear_first=False
            if not resume and not self.draft.isChecked():
                self.preview.clear();self.image_info.setText('');self._whole=None;self._part=None
                self.renderer.buffers.forget()
        if self._draft_engine:
            # A draft is drawn twice. First quickly and small, 640 pixels wide unless Preferences says otherwise, so
            # that it is up at once. Then finely: as many pixels as the view has and half as many again, so that
            # its lines are as clean as a drawing's and stay so when looked at closely. Either is told from the
            # region rendered among the lines by its size, so neither is ever just the size of the preview.
            if (getattr(self,'_draft_hasty',False) and not self._following):fine=max(64,min(3200,int(self.preferences.get('draft/width') or 640)))
            # Twice as many pixels across as the picture has in the view: clean lines, and clean still when looked at
            # closely, and no more than that, since every pixel drawn is one to hand over and show. The picture is
            # fitted into the view, so an upright one is narrower there than the view is: sized by the view's
            # width alone it came out several times too tall.
            else:
                scale=self.preview.devicePixelRatioF()
                across=min(self.preview.width()*scale,self.preview.height()*scale*width/max(1,height))
                fine=min(3200,max(640,int(2*across)))
            # And never more pixels than MoonLightIPR hands over at one go (DRAFT_MOST): asked for more, it handed
            # over nothing and the window waited on it for good.
            fine=max(64,min(fine,int((DRAFT_MOST*width/max(1,height))**.5)))
            if fine==width:fine+=2
            height=max(16,round(height*fine/width));width=fine
            # The quick picture may still be on its way when the fine one is asked for: it is a draft's too.
            if self._draft_fine!=(width,height):self._draft_quick=self._draft_fine
            self._draft_fine=(width,height)
        # MoonRay LS is MoonRay within its quality limits. A draft's region is not held to them.
        if self._low() and not output and not scene.get('_draft'):
            from .ipr import prepare
            scene,width,height=prepare(scene,width,height,values['samples'],get('ipr/width'),get('ipr/samples'),get('ipr/error'))
        if refining:
            from .ipr import refine
            scene=refine(scene)
        self.renderer.timeout_seconds = values['timeout']*60
        grid=(4 if refining else 1) if scene.get('_ipr') and not output else values['samples']
        # Kept with the picture, for its sampling to be said beside its size.
        if engine=='moonray':scene=dict(scene,_pixel_samples=int(grid)**2)
        self.renderer.submit(scene, self.runtime_path(), width, height, grid,
                             values['environment'], values['threads'], output, persistent_preview=get('persistent_preview'), engine=engine, resume=resume)
        if resume:self.status.setText('Continuing the stopped render.')
        self.last_digest = original_digest

    def _digest(self, scene):
        render_scene={key:value for key,value in scene.items() if key not in ('preview_buffer','display','aovs','recovery','_geometry_revision','denoising','compositor')}
        stored=self._settings_values();get=self.preferences.get
        values = [render_scene, self._clay(), self.runtime_path(), get('preview_size'), stored['samples'], stored['environment'], stored['threads'], get('persistent_preview'), self._following, get('ipr/width'), get('ipr/samples'), get('ipr/error'), get('moonlightipr/samples'), self._engine()]
        # Geometry is hashed once per list; a streaming JSON pass over every vertex took seconds per update.
        from .scene_digest import digest
        return digest(*values)

    def _preview_denoiser(self):
        denoising=self._settings_values()['denoising']
        if self._following or self._low():return 'off'
        if denoising['engine']!='off' and denoising['preview']:return denoising['engine']
        # Smart Render stops a render for the denoiser to finish: with none chosen, whichever will run.
        if denoising.get('smart','off')!='off' and self._engine()!='moonlightipr':return denoising['engine'] if denoising['engine']!='off' else 'auto'
        # The scene asks for none, and the denoised beauty is chosen in the list all the same: it is denoised with
        # the graphics card's denoiser, or the processor's where that will not run.
        return 'auto' if self.buffer.currentData()=='denoised_beauty' and self._engine()!='moonlightipr' else 'off'

    def _denoising_changed(self,*args):
        if self.disposed:return
        engine=self._preview_denoiser()
        self._buffer_picked=None
        if self._engine()=='moonlightipr':
            # MoonLightIPR denoises for itself, when its denoised picture is chosen: the scene's setting is MoonRay's.
            self._limit_buffers()
            return
        self.renderer.buffers.denoiser.request(engine)
        self.buffer.setCurrentIndex(self.buffer.findData('beauty' if engine=='off' else 'denoised_beauty'))

    def _buffer_changed(self,index):
        if self.disposed:return
        # MoonRay LS is a quick look and is not denoised. MoonLightIPR denoises as it goes.
        if self._low() and self.buffer.currentData()=='denoised_beauty':
            self.buffer.setCurrentIndex(self.buffer.findData('beauty'));return
        try:
            from .display import values
            stored=self._settings_values();key=self.buffer.currentData()
            if self._add_cryptomatte(key,stored):return
            if key=='composite':
                from . import compositor
                if compositor.trivial(stored.get('compositor')):
                    self.status.setText(NO_COMPOSITE);return
            if key=='denoised_beauty' and self._engine()!='moonlightipr':
                # Chosen with no denoiser set in the scene: the kept render is denoised now.
                engine=self._preview_denoiser()
                if engine=='auto':self.renderer.buffers.denoiser.request(engine)
            self.renderer.buffers.select(key,values(stored['display']))
            if key=='denoised_beauty' and self._engine()=='moonlightipr' and not getattr(self.renderer,'moonlightipr_denoises',False):
                # MoonLightIPR has not been denoising: it renders again, denoising this time.
                if self._following or self._rendering or not self.preview.image.isNull():self.render_once()
            if not self._rendering and any(v['name']==key and v['kind']=='cryptomatte' for v in stored['custom_aovs']):
                self.status.setText('Cryptomatte: each color is one ID. The EXR holds the mattes.')
        except Exception as exc:
            self.status.setText('Cannot update buffer display: '+str(exc))

    def _add_cryptomatte(self,key,stored):
        """Choosing a Cryptomatte the scene does not output yet adds it and renders; True if it did."""
        category=next((c for c,_ in CRYPTOMATTES if key=='crypto_'+c),None)
        entries=list(stored['custom_aovs'])
        if category is None or any(v['name']==key for v in entries):return False
        if self._engine()!='moonray':
            self.status.setText('Cryptomatte needs the MoonRay engine.');return True
        from . import native,outputs
        if not native.supports_crypto_categories(self.runtime_path()):
            # This runtime writes one Cryptomatte at a time.
            entries=[v for v in entries if v['kind']!='cryptomatte']
        entries=outputs.values(entries+[{'name':key,'kind':'cryptomatte','category':category,'depth':6}])
        if not self._store(custom_aovs=entries):return True
        self.renderer.buffers.select(key,scene_display(stored))
        self.status.setText('Cryptomatte added to the scene outputs. Rendering.')
        self.render_once()
        return True

    def _preview_changed(self, index):
        if self.disposed: return
        if not self._following:
            self.status.setText('Realtime is off. Press RT Off to switch it on.' if self._live() else 'Applies to the next render.');return
        if self.preview_lock.isChecked():
            self.status.setText('Preview locked. Applies when unlocked.');return
        if self._output_busy():
            self.status.setText('Applies after the output render finishes.')
            return
        self.render_once()

    def _after_drag(self):
        if self.disposed:return
        from .interaction import dragging
        if dragging():self.release_timer.start();return
        if self._pending_preview:
            self._pending_preview=False;self.render_once()
        elif self._following:self._live_tick()

    def render_once(self):
        from .interaction import dragging
        if dragging():
            self._pending_preview=True;self.release_timer.start();return
        if self._output_busy():
            self.status.setText('Output render is running. Press Stop before starting a preview.');return
        try:
            scene=self._unchanged_scene()
            if scene is None:
                scene=self._capture_preview()
                # What Modo has told of up to now is in this reading of the scene.
                self.changes.consume()
            self._submit(scene)
        except Exception as exc:
            self._failed(str(exc))

    def _capture_key(self):
        """What, beside the scene's own contents, a reading of the scene depends on."""
        import modo
        settings={k:v for k,v in self._settings_values().items() if k not in ('display','preview_buffer','aovs','recovery','compositor')}
        return (repr(sorted(settings.items(),key=lambda entry:entry[0])),lx.service.Selection().GetTime(),modo.Scene().renderItem.id,self._engine(),
                self.preferences.get('preview_motion'),self.runtime_path())

    def _unchanged_scene(self):
        """The scene as it was last read out of Modo, where nothing has changed since: reading it is most of the wait
        for a draft's outlines, and switching Draft on or off or drawing a region changes nothing in the scene.
        None where anything may have changed. Modo's word that nothing has is trusted for a quarter of a minute,
        as it is while a scene is followed, unless the safety re-reading is switched off in the preferences."""
        scene=getattr(self,'_kept_capture',None)
        # Only while the scene is being followed: the reading kept is then the one the picture on screen was made
        # from, brought up to date at every edit. With realtime off nothing keeps it so, and the scene is read anew.
        if not self._following:return None
        if scene is None or not self.changes.registered or self.changes.full or self.changes.items:return None
        try:
            if self._capture_key()!=self._kept_key:return None
        except Exception:return None
        return scene

    def _live_tick(self):
        if self.disposed or not self._following:return
        from .interaction import dragging
        held=dragging()
        if self.disposed or self.preview_lock.isChecked() or self._output_busy():
            return
        # An animation playing in Modo is not followed frame by frame: the frame it stops on is rendered. A time
        # dragged by hand is another matter, and is followed as any drag is.
        if not self._time_settled() and not held:return
        import time as clock
        began=clock.monotonic()
        if began<getattr(self,'_live_rest',0.0):return
        # Keep host reads from competing with the Python writer during a drag. Notices stay queued.
        if held and self.preview_engine.currentData()=='moonray_ls' and getattr(self.renderer,'writer',None) is not None:return
        if not held:self._live_drag_read=False
        try:
            import modo
            full,items=self.changes.consume();time=lx.service.Selection().GetTime()
            from .assets import signature
            # Periodic reconciliation covers host notifications omitted by some
            # procedural mesh providers. Normal idle ticks do not capture geometry.
            now=clock.monotonic()
            asset_changed=False
            # The periodic checks wait for the button too; they would turn a drag that can be
            # followed into a full capture.
            if not held and now-self._asset_check_time>=1:
                self._asset_check_time=now;asset_changed=signature(self._asset_scene)!=self._asset_signature
            full=full or asset_changed
            settings={k:v for k,v in self._settings_values().items() if k not in ('display','preview_buffer','aovs','recovery','denoising','compositor')}
            changed=settings!=self._live_settings or time!=self._last_time or modo.Scene().renderItem.id!=self._scene_id
            settling=not held and getattr(self,'_live_digest_pending',False)
            if not (full or items or changed or settling):return
            reuse=not full and not changed and bool(items or settling) and self._geometry_cache is not None
            if reuse:
                from .incremental import classify
                reuse=classify(modo.Scene(),items,self._geometry_cache) if items else True
            sky=False
            if held and reuse is True:
                # A physically based sky is painted again for every place its sun is put, which a drag cannot keep
                # up with: the sun of such a sky is shown where it was let go.
                from .incremental import moves_sky
                if moves_sky(modo.Scene(),items,self._geometry_cache):reuse=False;sky=True
            if held and reuse not in (True,'transforms','materials') and not sky and not getattr(self,'_live_drag_read',False):
                # The first step of a drag often makes something new in the scene (an item's first move gives it a
                # place of its own), which needs the scene read whole. That is done once in a drag, so that the rest
                # of it can be followed; a drag that goes on needing it waits for the release, as below.
                self._live_drag_read=True
            elif held and reuse not in (True,'transforms','materials'):
                # Modo reports some drags as they happen (the transform tool) and others only on
                # release (viewport navigation). Of those it reports, only light, transform and
                # material edits are followed live; reading meshes or the whole scene in the
                # middle of a tool waits for the release.
                self.changes.full=self.changes.full or full;self.changes.items.update(items)
                self.release_timer.start();return
            # MoonLightIPR with motion blur: once an edit is let go, the scene is read at both ends of the shutter as well
            # (three readings in all). Only a material edit to a scene last found to hold nothing that moves skips that:
            # any other edit may have keyed something to move. While dragging, it is followed sharp, as fast as it can be.
            blurred=False
            if not held and self._engine()=='moonlightipr' and self.preferences.get('preview_motion'):
                still=(time,modo.Scene().renderItem.id,repr(sorted(settings.items(),key=lambda entry:entry[0])))
                if full or changed or reuse!='materials' or getattr(self,'_live_still',None)!=still:
                    from .motion import moves
                    scene=self._capture_preview();blurred=True
                    # The meshes are read whole again on the next edit: a reading at the shutter's ends leaves none to reuse.
                    self._geometry_cache=None
                    self._live_still=None if moves(scene) else still
            if not blurred:
                scene = self._capture(reuse,items if reuse=='transforms' else None)
            if held:
                # Whatever was dragged, if it changed what lights the scene from all around (an environment, one of
                # its layers or where that sits, a sky's sun, a MoonRay environment light), it is shown on release.
                from .incremental import surroundings
                if self._surroundings is not None and surroundings(scene)!=self._surroundings:
                    self.changes.items.update(items);self.release_timer.start();return
            self._last_time=time;self._live_settings=settings
            if held and self.preview_engine.currentData()=='moonray_ls':
                # Host notices already establish a drag edit. Hash once after release, not on every move.
                self._live_digest_pending=True
                self.release_timer.start()
                self._submit(scene,digest=('live-drag',object()))
            else:
                digest=self._digest(scene)
                self._live_digest_pending=False
                if digest != self.last_digest:self._submit(scene,digest=digest)
        except Exception as exc:
            self.changes.invalidate();self._failed(str(exc))
        finally:
            # Following is done on Modo's own thread, which cannot move the view while it is at it. After each
            # update the thread is left to Modo for twice as long as the update took, so that a drag stays Modo's.
            done=clock.monotonic()
            if done-began>0.004:self._live_rest=done+min(LIVE_REST*(done-began),0.2)

    def stop(self):
        self._draft_quiet=False
        self.refine_timer.stop()
        self._pending_preview=False;self.release_timer.stop()
        self.preview_timer.stop()
        if self.sequence is not None:
            self.sequence.stop()
        self._following=False;self.timer.stop()
        # A draft's region is not gone on to once its lines have been stopped.
        self._draft_then=None;self._draft_pass=False
        self.preview.set_show_buckets(self.show_buckets.isChecked())
        # A preview stopped by hand is taken as finished where it stands: the picture so far is kept, and what
        # follows a finished render, the denoiser among it, follows this.
        rendering=self._rendering and not self._output_busy()
        if rendering and self.renderer.settle():
            self.status.setText('Stopping: finishing with what is rendered.');self._await_settle(5000);return
        # MoonRay under Safe Denoising: the picture it last saved is finished with, a preview or an output alike.
        if self._rendering and not (self.sequence is not None and self.sequence.running) and self.renderer.settle_moonray():
            self.status.setText('Stopping: keeping what is rendered.');self._await_settle(30000);return
        # MoonRay kept loaded hands over the picture as it stands, with what the denoiser needs, and is then stopped.
        if rendering and not self.draft.isChecked() and self.renderer.keep_progress():
            self.status.setText('Stopping: keeping what is rendered.');self._await_settle(16000);return
        self.renderer.stop()
        self._set_rendering(False)
        self.status.setText('Stopped.')
        if rendering:self._settle_stopped()

    def _render_afresh(self):
        """Let go of the stopped render and render the scene from the start, once the user has said so."""
        asked=QtWidgets.QMessageBox.question(self,'Restart Render','Are you sure you want to restart render? Current progress will be lost.',
                                             QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.Cancel,QtWidgets.QMessageBox.Cancel)
        if asked!=QtWidgets.QMessageBox.Yes:return
        self._continuable=None
        self._set_rendering(self._rendering)
        self.start_render()

    def _stopped_plain(self):
        """A render stopped before MoonRay had saved anything of it."""
        self._settle_token=None
        self._continuable=self.last_digest if getattr(self.renderer,'resumable',None) else None
        self._set_rendering(False)
        self.status.setText('Stopped before anything of the render was saved.')

    def _await_settle(self,wait):
        """A render asked to finish with what it has is given so long to say that it has; past that it is stopped
        outright, so that the window is never left waiting."""
        self._settle_token=token=object()
        def late():
            if self.disposed or getattr(self,'_settle_token',None) is not token or not self._rendering:return
            self._settle_token=None
            self.renderer.stop();self._set_rendering(False)
            self.status.setText('Stopped.')
        QtCore.QTimer.singleShot(wait,late)

    def _smart_settled(self,noise):
        """Smart Render: the picture is clean enough for the denoiser. The render is stopped as Stop stops it."""
        if self.disposed or not self._rendering or self._following or self._output_busy() or self.preview_engine.currentData()!='moonray':return
        self._smart_note='Smart Render stopped the render at %.1f%% noise.'%(100*noise)
        self.stop()
        if not self._rendering:
            # Stopped outright, with nothing handed over: say why it stopped all the same.
            self.status.setText(self._smart_note);self._smart_note=''

    def _kept(self,done):
        """MoonRay has been stopped, having handed over the picture as it stood (or not, if it could not)."""
        if self.disposed:return
        self._settle_token=None
        self._set_rendering(False)
        note=getattr(self,'_smart_note','');self._smart_note=''
        self.status.setText((note+' The picture is kept and denoised.' if note else 'Stopped. The picture is kept as it stood.') if done else 'Stopped.')
        self._settle_stopped(done)

    def _settle_stopped(self,standing=False):
        """After MoonRay is stopped: the last pass it finished is the picture, and is denoised if that is asked for.
        A pass cut short leaves nothing of its own; MoonRay hands over a picture only when a pass ends."""
        engine=self._preview_denoiser()
        frame=self.renderer.buffers.frame
        # MoonLightIPR denoises for itself, and which of its pictures is shown is chosen in the list.
        if engine=='off' or not frame or frame.get('snapshot',{}).get('_ipr') or self._engine()=='moonlightipr':return
        if not all(key in frame.get('files',{}) for key in ('beauty','denoise_albedo','denoise_normal')):return
        self.renderer.buffers.denoiser.request(engine)
        # The beauty is what is shown, whatever the engine. Smart Render alone turns to the denoised picture, which
        # is what it stopped the render for.
        if self._smart_on() and self.buffer.currentData()=='beauty' and self._buffer_picked!='beauty':
            self.buffer.setCurrentIndex(self.buffer.findData('denoised_beauty'))
        self.status.setText('Stopped. The picture as it stood is kept and denoised.' if standing else 'Stopped. The last finished pass is kept and denoised.')

    def _failed(self, message):
        self._draft_quiet=False
        self.refine_timer.stop()
        self._following=False;self.timer.stop()
        self.renderer.stop()
        self._set_rendering(False)
        self.status.setText('Render unavailable: ' + message)
        self.status.setToolTip(message)
        # Said among the notices too, with the button gone red, so that it is not missed once the status moves on.
        self._failure=str(message)
        snapshot=(self.renderer.active or {}).get('snapshot',{})
        self._set_notices(['Render unavailable: '+str(message)]+list(snapshot.get('warnings',[])))

    def _image(self, path):
        try:
            if self._held:return
            if self.draft.isChecked():
                from . import draft
                frame=path if isinstance(path,QtGui.QImage) else QtGui.QImage(str(path))
                if frame.isNull():raise ValueError('MoonRay output could not be decoded as an image.')
                # The lines and the region's render come one after the other, and the last picture of the one may
                # arrive after the other has begun: they are told apart by size, the lines being drawn finer.
                if (frame.width(),frame.height()) in (self._draft_fine,getattr(self,'_draft_quick',None)):
                    self._draft_image=draft.inked(frame,None)
                else:
                    region=self._draft_region()
                    if region is None:return
                    self._draft_render=(region,frame.copy());self._part=self._draft_render
                if self._draft_image is not None:self._draft_show()
                return
            if self._draft_fine!=(0,0):
                # Draft is off, and its lines may still arrive or be shown again by a change of buffer or engine: they
                # are known by their size, and are not a render to show or to keep.
                late=path if isinstance(path,QtGui.QImage) else QtGui.QImage(str(path))
                if (late.width(),late.height()) in (self._draft_fine,getattr(self,'_draft_quick',None)):return
            if isinstance(path,QtGui.QImage):self.preview.set_image(path)
            else:self.preview.load(path)
            # Kept, to be put back when Region or Draft is switched off, without rendering.
            if not self.draft.isChecked():
                region=self._draft_region()
                # Copies of their own: the picture shown may rest on memory the renderer takes back.
                if region:self._part=(region,self.preview.image.copy())
                else:
                    # With which scene it is of, so that it is not put back once the scene is another.
                    self._whole=self.preview.image.copy();self._part=None;self._whole_digest=self.last_digest
            active=self.renderer.active or {};frame=self.renderer.buffers.displayed or {}
            snapshot=frame.get('snapshot',active.get('snapshot',{}))
            text='%d x %d'%(self.preview.image.width(),self.preview.image.height())
            if snapshot.get('_pixel_samples') and not snapshot.get('_draft') and not frame.get('moonlightipr'):
                # How a MoonRay picture was sampled: uniform with its samples a pixel, or adaptive with the fewest and most.
                from .options import render_values
                settings=render_values(snapshot.get('render_settings',{}))
                text+=' | '+('LS ' if snapshot.get('_ipr') else '')+('Adaptive %d-%d ps'%(settings['min_adaptive_samples'],settings['max_adaptive_samples'])
                             if settings['sampling_mode']==2 else 'Uniform %d ps'%snapshot['_pixel_samples'])
            # And how it is shown: the view transform, and a LUT where there is one.
            shown=self._view_words()
            if shown:text+=' | '+shown
            self.image_info.setText(text)
            self._image_note()
            self.image_info.setToolTip(str(frame.get('backend',self.renderer.backend_status)))
        except ValueError as exc:
            self.status.setText('Cannot display cached preview: '+str(exc))

    def _renderer_status(self,text):
        # Left as it is while a draft redraws by itself.
        if getattr(self,'_draft_quiet',False):return
        self.status.setText(text)

    def _render_progress(self,value,label):
        if getattr(self,'_draft_quiet',False):return
        if self.sequence is not None and self.sequence.running:
            label='Frame %d (%d/%d) | %s'%(self.sequence.frame,len(self.sequence.completed)+1,self.sequence.total,label)
        self.render_progress.setRange(0,0 if value<0 else 100)
        if value>=0: self.render_progress.setValue(value)
        # Under Safe Denoising: how long ago MoonRay last saved, which is what a stop now would keep.
        saved=getattr(self.renderer,'saved_at',None)
        if (self._rendering and saved is not None and getattr(self.renderer,'safe_files',None) and not getattr(self.renderer,'settling',False)
                and not label.startswith(('Complete','Stopped')) and 'Denoising' not in label):
            import time
            from .progress import duration
            label+=' · Saved %s ago'%duration(time.monotonic()-saved)
        self.render_timing.setText(label.replace(' · ',' | '))

    def _kept_status(self):
        """What to say of a render stopped under Safe Denoising: it is kept as MoonRay last saved it, which may be
        some way behind what was on screen at the stop. The picture's own line says so for as long as it is shown."""
        from .progress import duration
        behind=getattr(self.renderer,'kept_behind',None)
        if behind is None or behind<1.5:
            self._kept_note='';return 'Stopped and kept. Continue takes the render up again.'
        self._kept_note='as saved %s before the stop'%duration(behind)
        self._image_note()
        return 'Stopped: the picture is the last save, %s before the stop. Continue takes it up from there.'%duration(behind)

    def _image_note(self):
        """Mark the picture's line where the picture is not what was last on screen."""
        note=getattr(self,'_kept_note','')
        text=self.image_info.text().split(' | as saved ')[0]
        if text:self.image_info.setText(text+(' | '+note if note else ''))
        self.image_info.setStyleSheet('QLabel,QLabel:disabled{color:#ffd166;}' if note else '')

    def _finished(self, output):
        step = (getattr(self, '_stereo_after', None) or {}).pop(output, None) if output else None
        if step and step[0] == 'render':
            # The left eye is saved: now the right (panel_tools.render_final).
            try:self._submit(step[1], step[2])
            except Exception as exc:self._failed(str(exc))
            return
        if step and step[0] == 'composite':
            # Both eyes are saved: their composite in the file chosen.
            from . import stereo
            try:
                from .native import find_runtime
                stereo.composite(find_runtime(self.runtime_path()), step[1], step[2][0], step[2][1], step[3])
                output = step[3]
            except Exception as exc:
                self._failed(str(exc));return
        if not output and getattr(self,'_draft_then',None) is not None and self.draft.isChecked():
            # The draft's lines are drawn: now the region, by the engine chosen.
            scene,self._draft_then=self._draft_then,None
            self._draft_pass=True
            try:self._submit(scene)
            except Exception as exc:self._failed(str(exc))
            return
        self._settle_token=None
        # A preview stopped under Safe Denoising can be taken up again while the scene stays as it was.
        self._continuable=self.last_digest if not output and getattr(self.renderer,'resumable',None) else None
        self._set_rendering(False)
        self._draft_quiet=False
        self.status.setToolTip('')
        self.status.setText(('Saved ' + output) if output else ('Following the scene' if self._following else self._kept_status() if self._continuable
                             else 'Draft: press Region and drag in the picture to mark a part of it.' if self.draft.isChecked() and self._draft_region() is None
                             else 'Draft: region marked. Press %s to render it.'%('RT Off' if self._live() else 'Render') if self.draft.isChecked() else 'Done'))
        if not output and getattr(self.renderer,'draining',False):
            # Stopped by hand, or by Smart Render: MoonRay finished the tiles it had in hand and ended the render
            # there, so the picture is whole and has all its buffers.
            self.renderer.draining=False
            note=getattr(self,'_smart_note','');self._smart_note=''
            self.status.setText(note+' The picture is kept with all its buffers.' if note else 'Stopped. The picture is kept with all its buffers.')
        if not output and self._engine()!='moonlightipr' and self._playblasting() is None:
            engine=self._preview_denoiser()
            self.renderer.buffers.denoiser.request(engine)
            # The finished picture shown is the beauty: the denoised one is made and is there in the list to choose.
            # Smart Render alone turns to it, unless Beauty was chosen by hand.
            if engine!='off' and self._smart_on() and self.buffer.currentData()=='beauty' and self._buffer_picked!='beauty':
                self.buffer.setCurrentIndex(self.buffer.findData('denoised_beauty'))
            snapshot=(self.renderer.active or {}).get('snapshot',{})
            if self._following and self.preferences.get('ipr/refine') and snapshot.get('_ipr') and not snapshot.get('_ipr_refined') and snapshot.get('render_settings',{}).get('max_adaptive_samples',1)<16:
                self.refine_timer.start()

    def _refine_ipr(self):
        if self.disposed or not self._following or not self.preferences.get('ipr/refine') or self.preview_lock.isChecked() or self._output_busy():return
        from .interaction import dragging
        if dragging() or self.preview_timer.isActive():self.refine_timer.start();return
        generation=self.renderer.generation
        self._live_tick()  # A pending edit takes priority over quality refinement.
        if self.renderer.generation!=generation or not self._following:return
        if self._ipr_refine_scene is not None:
            try:self._submit(self._ipr_refine_scene,refining=True)
            except Exception as exc:self._failed(str(exc))

    def dispose(self):
        if not self.disposed:
            self.disposed = True
            self.refine_timer.stop()
            self.changes.close()
            self.release_timer.stop()
            self.display_timer.stop()
            self.preview_timer.stop()
            self.timer.stop()
            self.poll_timer.stop()
            if self.sequence is not None:
                self.sequence.stop()
            self.renderer.close()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
