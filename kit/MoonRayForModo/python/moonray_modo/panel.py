"""The MoonRay preview window: the image, and what is used while looking at it.

Render settings live on the scene's Render item and are edited in its MoonRay properties
(scene_settings.py); what the window remembers about previewing on this machine is in
preferences.py; output renders, exports and the scene dialogs are in panel_tools.py.
"""
from PySide2 import QtCore, QtGui, QtWidgets
from . import host, options, properties, scene_settings
import lx
from .render import Renderer
from .viewer import Preview
from .preferences import Preferences
from .panel_tools import Tools

RENDER_TIP = 'Render the current scene. The previous image stays until its replacement is ready.'
STOP_TIP = 'Stop the render in progress and stop following scene changes.'
# Always offered in the buffer list; choosing one adds the output to the scene if it lacks it.
CRYPTOMATTES = (('object', 'Cryptomatte: Objects'), ('material', 'Cryptomatte: Materials'))


def scene_display(stored):
    from .display import values
    return values(stored['display'])


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
        self.poll_timer=QtCore.QTimer(self);self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self._poll)

        layout = QtWidgets.QVBoxLayout(self);layout.setContentsMargins(4,4,4,4);layout.setSpacing(3)
        layout.addLayout(self._toolbar())
        self.preview = Preview()
        self.preview.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.preview.customContextMenuRequested.connect(lambda point:self._image_menu(point).exec_(self.preview.mapToGlobal(point)))
        self.preview.installEventFilter(self)
        self.preview.start_requested.connect(self.start_render)
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
        self.renderer.status.connect(self.status.setText)
        self.renderer.failed.connect(self._failed)
        self.renderer.image_ready.connect(self._image)
        self.renderer.image_object.connect(self._image)
        self.renderer.finished.connect(self._finished)
        self.renderer.notices.connect(self._engine_notices)
        self._engine_changed(0)
        self._poll()
        self.buffer.setCurrentIndex(max(0,self.buffer.findData(self._settings_values_stored().get('preview_buffer','beauty'))))
        self.buffer.currentIndexChanged.connect(self._buffer_changed)
        self.preview_engine.currentIndexChanged.connect(self._engine_changed)
        self.preview_engine.currentIndexChanged.connect(self._preview_changed)
        self.ipr_mode.toggled.connect(self._ipr_changed)
        self.poll_timer.start()

    # The window's own controls

    def _toolbar(self):
        row = QtWidgets.QHBoxLayout();row.setSpacing(6)
        self.start = QtWidgets.QPushButton('Render')
        self.start.setToolTip(RENDER_TIP)
        self.start.setMinimumWidth(72)
        # One button: it starts a preview, and while one runs or IPR is watching, it stops it.
        self.start.clicked.connect(self._render_or_stop)
        row.addWidget(self.start)
        self.ipr_mode=QtWidgets.QCheckBox('IPR')
        self.ipr_mode.setToolTip('With IPR on, Render keeps following the scene as it is edited, until Stop.')
        self.ipr_mode.setChecked(self.preferences.get('ipr'))
        row.addWidget(self.ipr_mode)
        self.preview_engine=QtWidgets.QComboBox()
        self.preview_engine.addItem('MoonRay', 'moonray')
        self.preview_engine.addItem('MoonLight', 'moonlight')
        self.preview_engine.setCurrentIndex(max(0,self.preview_engine.findData(self.preferences.get('preview_engine'))))
        self.preview_engine.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.preview_engine.setMinimumWidth(130)
        self.preview_engine.setToolTip('MoonLight is a fast GPU preview that approximates materials and lighting; Notices lists what it leaves out. Output renders always use MoonRay.')
        row.addWidget(self.preview_engine)
        self.buffer = QtWidgets.QComboBox()
        self.buffer.addItem('Beauty','beauty')
        self.buffer.addItem('Denoised Beauty','denoised_beauty')
        for key,(label,attributes,channel) in options.AOVS.items():
            self.buffer.addItem(label,key)
        self.buffer.setToolTip('The render buffer shown. Switching does not restart the render.')
        row.addWidget(self.buffer,1)
        self.exposure=QtWidgets.QDoubleSpinBox();self.exposure.setRange(-20,20);self.exposure.setSingleStep(.25)
        self.exposure.setPrefix('EV ');self.exposure.setKeyboardTracking(False)
        self.exposure.setToolTip('Display exposure in stops. The rendered values are not changed.')
        self.exposure.valueChanged.connect(lambda value:self.display_timer.start())
        row.addWidget(self.exposure)
        self.region_enabled=QtWidgets.QCheckBox('Region')
        self.region_enabled.setToolTip('Render only the region set in the Render item\'s MoonRay properties.')
        self.region_enabled.toggled.connect(self._region_toggled)
        row.addWidget(self.region_enabled)
        self.focus_pick=QtWidgets.QToolButton();self.focus_pick.setText('Focus');self.focus_pick.setCheckable(True)
        self.focus_pick.setToolTip('Click, then click a point in the image: the camera focuses on that surface. Right-click the image for Focus Here.')
        self.focus_pick.toggled.connect(self._focus_armed)
        row.addWidget(self.focus_pick)
        gear=self.options_button=QtWidgets.QToolButton();gear.setText('Options');gear.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        gear.setMenu(self._options_menu())
        row.addWidget(gear)
        return row

    def _options_menu(self):
        menu=self.options_menu=QtWidgets.QMenu(self)
        def checkable(target,label):
            # Made here and then added: in Modo's Qt the action a menu makes for a label cannot
            # be used afterwards (it reports as deleted), which stopped IPR from starting.
            action=QtWidgets.QAction(label,self);action.setCheckable(True);target.addAction(action)
            return action
        menu.addAction('Render Settings',self.open_settings)
        menu.addAction('Preferences...',self.edit_preferences)
        menu.addSeparator()
        self.preview_lock=checkable(menu,'Lock Preview')
        self.preview_lock.setToolTip('Hold automatic updates; the current render continues.')
        self.preview_lock.toggled.connect(self._lock_changed)
        from .clay import CHOICES
        clay=self.clay_menu=QtWidgets.QMenu('Preview Material',self);menu.addMenu(clay);self.clay_group=QtWidgets.QActionGroup(self)
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
        menu.addAction('Render EXR...',self.render_final)
        menu.addAction('Render Animation...',self.render_animation)
        menu.addAction('Export Scene...',self.export)
        menu.addSeparator()
        menu.addAction('Render Log...',self.show_log)
        return menu

    def _image_menu(self,point=None):
        menu=QtWidgets.QMenu(self)
        if point is not None:
            menu.addAction('Focus Here',lambda:self.focus_at(point))
            menu.addSeparator()
        menu.addAction('Fit',self.preview.fit)
        menu.addAction('Actual Size',self.preview.actual_size)
        menu.addSeparator()
        menu.addAction('Copy Image',self.copy_image)
        menu.addAction('Save Image...',self.save_preview)
        return menu

    def _status_line(self):
        row=QtWidgets.QHBoxLayout();row.setSpacing(10)
        self.status = QtWidgets.QLabel('Ready')
        # A long message is cut short rather than widening the window.
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Preferred)
        row.addWidget(self.status,1)
        self.image_info=QtWidgets.QLabel('');self.image_info.setEnabled(False)
        row.addWidget(self.image_info)
        self.render_timing=QtWidgets.QLabel('');self.render_timing.setEnabled(False)
        row.addWidget(self.render_timing)
        self.notice_toggle=QtWidgets.QToolButton();self.notice_toggle.setText('Notices (0)');self.notice_toggle.setCheckable(True);self.notice_toggle.setAutoRaise(True)
        self.notice_toggle.setToolTip('What the renderer could not carry over from the scene')
        self.notice_toggle.toggled.connect(lambda visible:self.warnings.setVisible(visible))
        row.addWidget(self.notice_toggle)
        return row

    def _focus_armed(self,armed):
        if armed:
            self.preview.setCursor(QtCore.Qt.CrossCursor)
            self.status.setText('Click the point to focus on.')
        else:self.preview.unsetCursor()

    def eventFilter(self,watched,event):
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
        self.status.setText('Preferences saved.')
        self.refine_timer.stop()
        if self._following:self.preview_timer.start()

    def _region_toggled(self,enabled):
        if enabled==self._settings_values()['region_enabled']:return
        self._store(region_enabled=bool(enabled))
        if self._following:self.preview_timer.start()

    def _commit_exposure(self):
        if self.disposed:return
        display=self._settings_values()['display']
        if abs(display['exposure']-self.exposure.value())<1e-9:return
        self._store(display=dict(display,exposure=self.exposure.value()))
        self._buffer_changed(0)

    # Settings: the scene's, and how the window follows them

    def _settings_values_stored(self):
        try:return properties.scene_settings()
        except Exception:return {}

    def _settings_values(self):
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
        watched=(values['display'],values['denoising'],values['custom_aovs'],values['asset_settings'].get('working_space'),values['region_enabled'])
        if watched==self._shown:return
        previous,self._shown=self._shown,watched
        self._sync_output_menu(values['custom_aovs'])
        if not self.display_timer.isActive():
            blocker=QtCore.QSignalBlocker(self.exposure);self.exposure.setValue(values['display']['exposure']);del blocker
        blocker=QtCore.QSignalBlocker(self.region_enabled);self.region_enabled.setChecked(values['region_enabled']);del blocker
        if previous is None:return
        if previous[1]!=watched[1]:self._denoising_changed()
        if previous[0]!=watched[0] or previous[3]!=watched[3]:self._buffer_changed(0)

    def _sync_output_menu(self,custom_aovs):
        names=[(v['name'],v['name']) for v in custom_aovs if v['kind']!='cryptomatte']
        held={v.get('category','object'):v['name'] for v in custom_aovs if v['kind']=='cryptomatte'}
        names+=[(label,held.get(category,'crypto_'+category)) for category,label in CRYPTOMATTES]
        if 'asset' in held:names.append(('Cryptomatte: Assets',held['asset']))
        base=2+len(options.AOVS)
        if names==[(self.buffer.itemText(i),self.buffer.itemData(i)) for i in range(base,self.buffer.count())]:return
        key=self.buffer.currentData();blocker=QtCore.QSignalBlocker(self.buffer)
        while self.buffer.count()>base:self.buffer.removeItem(self.buffer.count()-1)
        for label,name in names:self.buffer.addItem(label,name)
        self.buffer.setCurrentIndex(max(0,self.buffer.findData(key)));del blocker

    def _engine_changed(self,index):
        self.preferences.set('preview_engine',self.preview_engine.currentData())
        # MoonLight follows edits as they happen, so look for them more often.
        self.timer.setInterval(60 if self.preview_engine.currentData()=='moonlight' else 150)

    def _engine_notices(self,messages):
        """Add what the preview engine left out to the notices of the scene it is showing."""
        snapshot=(self.renderer.active or {}).get('snapshot',{})
        self._set_notices(list(snapshot.get('warnings',[]))+list(messages))

    def _set_notices(self,messages):
        unique=list(dict.fromkeys(str(message) for message in messages if message))
        text='\n\n'.join(unique)
        if text!=self.warnings.toPlainText():self.warnings.setPlainText(text)
        self.notice_toggle.setText('Notices (%d)'%len(unique))

    def _ipr_changed(self,enabled):
        self.preferences.set('ipr',bool(enabled))
        if enabled:
            if self._rendering and not self._output_busy():
                # Turned on during a preview: carry on from it.
                self._follow(True)
                self.status.setText('Following the scene.')
            else:self.status.setText('IPR on: Render will follow the scene until Stop.')
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
            if self.buffer.currentData()=='denoised_beauty':
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

    def _dimensions(self, scene, final=False):
        scene_w, scene_h = scene['width'], scene['height']
        size=self.preferences.get('preview_size')
        width = scene_w if final or size<=0 else size
        return width, max(16, round(width * scene_h / max(1, scene_w)))

    def _capture(self,reuse=False):
        import modo
        if modo.Scene().renderItem.id != self._scene_id:
            self._scene_id=modo.Scene().renderItem.id;self._geometry_cache=None
        scene = host.snapshot(evaluated_geometry=self._settings_values()['surface'] == 2,reuse_geometry=self._geometry_cache if reuse else None,refresh_materials=reuse=='materials' or isinstance(reuse,dict),dirty_meshes=reuse.get('dirty_meshes') if isinstance(reuse,dict) else None)
        if reuse=='transforms':
            from .incremental import refresh_transforms
            refresh_transforms(modo.Scene(),scene)
        import copy,time
        full_capture=scene.pop('_full_capture',not reuse)
        if not reuse or reuse in ('materials','transforms') or isinstance(reuse,dict):
            self._geometry_cache=dict(scene,meshes=[dict(m) for m in scene['meshes']],materials=copy.deepcopy(scene['materials']),native_materials=copy.deepcopy(scene.get('native_materials',{})))
        if full_capture or isinstance(reuse,dict):self._last_full_capture=time.monotonic()
        scene.pop('_evaluated_data',None)
        scene['_geometry_revision']=str(id(self))+':'+str(self._last_full_capture)
        configured=self._configure_snapshot(scene)
        from .assets import signature
        self._asset_scene=configured;self._asset_signature=signature(configured)
        return configured

    def _capture_output(self):
        values=self._settings_values()
        if not values['final_motion']:return self._capture()
        from .animation import capture_current
        return self._configure_snapshot(capture_current(values['surface']==2))

    def _capture_preview(self):
        if self.preview_engine.currentData()!='moonlight' or not self.preferences.get('preview_motion'):return self._capture()
        from .animation import capture_current
        scene=self._configure_snapshot(capture_current(self._settings_values()['surface']==2))
        # Stepping through the shutter is not an edit for IPR to follow.
        self.changes.consume()
        return scene

    def _configure_snapshot(self, scene):
        values = self._settings_values()
        scene['render_settings'] = values['render']
        scene['aovs'] = values['aovs']
        scene['production']=values['production']
        scene['asset_settings']=values['asset_settings']
        from .extra_geometry import attach as attach_geometry
        attach_geometry(scene,values['production'])
        scene['custom_aovs']=values['custom_aovs']
        scene['recovery']=values['recovery']
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
        if self.ipr_mode.isChecked():self._follow(True)
        self.render_once()

    def _set_rendering(self,rendering):
        """Keep the Render button saying what pressing it will do."""
        self._rendering=bool(rendering)
        active=self._rendering or self._following
        self.start.setText('Stop' if active else 'Render')
        self.start.setToolTip(STOP_TIP if active else RENDER_TIP)

    def _submit(self, scene, output=None, refining=False):
        self.refine_timer.stop()
        self._set_rendering(True)
        self._ipr_refine_scene=scene if not output else None
        values=self._settings_values();get=self.preferences.get
        width, height = self._dimensions(scene, bool(output))
        original_digest=self._digest(scene)
        if not output:scene=dict(scene,_clay_preview=self._clay())
        engine='moonray' if output else self.preview_engine.currentData()
        # MoonLight accumulates at full preview size; the IPR quality limits are for MoonRay.
        if self._following and not output and engine=='moonray':
            from .ipr import prepare
            scene,width,height=prepare(scene,width,height,values['samples'],get('ipr/width'),get('ipr/samples'),get('ipr/error'))
        if refining:
            from .ipr import refine
            scene=refine(scene)
        self.renderer.timeout_seconds = values['timeout']*60
        self.renderer.submit(scene, self.runtime_path(), width, height, (4 if refining else 1) if scene.get('_ipr') and not output else values['samples'],
                             values['environment'], values['threads'], output, persistent_preview=get('persistent_preview'), engine=engine)
        self.last_digest = original_digest

    def _digest(self, scene):
        render_scene={key:value for key,value in scene.items() if key not in ('preview_buffer','display','aovs','recovery','_geometry_revision','denoising')}
        stored=self._settings_values();get=self.preferences.get
        values = [render_scene, self._clay(), self.runtime_path(), get('preview_size'), stored['samples'], stored['environment'], stored['threads'], get('persistent_preview'), self._following, get('ipr/width'), get('ipr/samples'), get('ipr/error'), self.preview_engine.currentData()]
        # Geometry is hashed once per list; a streaming JSON pass over every vertex took seconds per update.
        from .scene_digest import digest
        return digest(*values)

    def _preview_denoiser(self):
        denoising=self._settings_values()['denoising']
        return denoising['engine'] if denoising['preview'] and not self._following else 'off'

    def _denoising_changed(self,*args):
        if self.disposed:return
        engine=self._preview_denoiser()
        self.renderer.buffers.denoiser.request(engine)
        self.buffer.setCurrentIndex(self.buffer.findData('beauty' if engine=='off' else 'denoised_beauty'))

    def _buffer_changed(self,index):
        if self.disposed:return
        if self._following and self.buffer.currentData()=='denoised_beauty':
            self.buffer.setCurrentIndex(self.buffer.findData('beauty'));return
        try:
            from .display import values
            stored=self._settings_values();key=self.buffer.currentData()
            if self._add_cryptomatte(key,stored):return
            self.renderer.buffers.select(key,values(stored['display']))
            if not self._rendering and any(v['name']==key and v['kind']=='cryptomatte' for v in stored['custom_aovs']):
                self.status.setText('Cryptomatte: each color is one ID. The EXR holds the mattes.')
        except Exception as exc:
            self.status.setText('Cannot update buffer display: '+str(exc))

    def _add_cryptomatte(self,key,stored):
        """Choosing a Cryptomatte the scene does not output yet adds it and renders; True if it did."""
        category=next((c for c,_ in CRYPTOMATTES if key=='crypto_'+c),None)
        entries=list(stored['custom_aovs'])
        if category is None or any(v['name']==key for v in entries):return False
        if self.preview_engine.currentData()!='moonray':
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
            self.status.setText('Applies to the next render.');return
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
            self._submit(self._capture_preview())
        except Exception as exc:
            self._failed(str(exc))

    def _live_tick(self):
        if self.disposed or not self._following:return
        from .interaction import dragging
        held=dragging()
        # MoonLight is fast enough to follow a drag; a MoonRay preview waits for the button to come up.
        if held and self.preview_engine.currentData()!='moonlight':self.release_timer.start();return
        if self.disposed or self.preview_lock.isChecked() or self._output_busy():
            return
        try:
            import modo
            full,items=self.changes.consume();time=lx.service.Selection().GetTime()
            import time as clock
            from .assets import signature
            # Periodic reconciliation covers host notifications omitted by some
            # procedural mesh providers. Normal idle ticks do not capture geometry.
            now=clock.monotonic()
            asset_changed=False
            # The periodic checks wait for the button too; they would turn a drag that can be
            # followed into a full capture.
            if not held and now-self._asset_check_time>=1:
                self._asset_check_time=now;asset_changed=signature(self._asset_scene)!=self._asset_signature
            full=full or (not held and self.preferences.get('capture_safety') and now-self._last_full_capture>15) or asset_changed
            settings={k:v for k,v in self._settings_values().items() if k not in ('display','preview_buffer','aovs','recovery','denoising')}
            changed=settings!=self._live_settings or time!=self._last_time or modo.Scene().renderItem.id!=self._scene_id
            if not (full or items or changed):return
            reuse=not full and not changed and bool(items) and self._geometry_cache is not None
            if reuse:
                from .incremental import classify
                reuse=classify(modo.Scene(),items,self._geometry_cache)
            if held and reuse not in (True,'transforms','materials'):
                # Modo reports some drags as they happen (the transform tool) and others only on
                # release (viewport navigation). Of those it reports, only light, transform and
                # material edits are followed live; reading meshes or the whole scene in the
                # middle of a tool waits for the release.
                self.changes.full=self.changes.full or full;self.changes.items.update(items)
                self.release_timer.start();return
            scene = self._capture(reuse)
            self._last_time=time;self._live_settings=settings
            if self._digest(scene) != self.last_digest:self._submit(scene)
        except Exception as exc:
            self.changes.invalidate();self._failed(str(exc))

    def stop(self):
        self.refine_timer.stop()
        self._pending_preview=False;self.release_timer.stop()
        self.preview_timer.stop()
        if self.sequence is not None:
            self.sequence.stop()
        self._following=False;self.timer.stop()
        self.preview.set_show_buckets(self.show_buckets.isChecked())
        self.renderer.stop()
        self._set_rendering(False)
        self.status.setText('Stopped.')

    def _failed(self, message):
        self.refine_timer.stop()
        self._following=False;self.timer.stop()
        self.renderer.stop()
        self._set_rendering(False)
        self.status.setText('Render unavailable: ' + message)
        self.status.setToolTip(message)

    def _image(self, path):
        try:
            if isinstance(path,QtGui.QImage):self.preview.set_image(path)
            else:self.preview.load(path)
            active=self.renderer.active or {};frame=self.renderer.buffers.displayed or {}
            snapshot=frame.get('snapshot',active.get('snapshot',{}))
            text='%d x %d'%(self.preview.image.width(),self.preview.image.height())
            if snapshot.get('_ipr'):
                settings=snapshot['render_settings']
                text+=' | IPR '+('1 SPP' if settings['max_adaptive_samples']==1 else '%d-%d SPP'%(settings['min_adaptive_samples'],settings['max_adaptive_samples']))
            self.image_info.setText(text)
            self.image_info.setToolTip(str(frame.get('backend',self.renderer.backend_status)))
        except ValueError as exc:
            self.status.setText('Cannot display cached preview: '+str(exc))

    def _render_progress(self,value,label):
        if self.sequence is not None and self.sequence.running:
            label='Frame %d (%d/%d) | %s'%(self.sequence.frame,len(self.sequence.completed)+1,self.sequence.total,label)
        self.render_progress.setRange(0,0 if value<0 else 100)
        if value>=0: self.render_progress.setValue(value)
        self.render_timing.setText(label.replace(' · ',' | '))

    def _finished(self, output):
        self._set_rendering(False)
        self.status.setToolTip('')
        self.status.setText(('Saved ' + output) if output else ('Following the scene' if self._following else 'Done'))
        if not output:
            self.renderer.buffers.denoiser.request(self._preview_denoiser())
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
