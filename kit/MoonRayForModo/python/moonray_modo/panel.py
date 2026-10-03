"""Dockable Modo Custom View with a native Windows render process."""
import hashlib
import json
from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets
from . import host, native, rdla, options, properties
import lx
from .render import Renderer


from .viewer import Preview


class Panel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QtCore.QSettings('MoonRayForModo', 'NativePreview')
        installation_id=native.installation_id()
        if installation_id and self.settings.value('runtime_installation')!=installation_id:
            self.settings.setValue('previous_runtime',self.settings.value('runtime',''))
            self.settings.setValue('runtime',native.default_runtime())
            self.settings.setValue('runtime_installation',installation_id)
        self.renderer = Renderer(self)
        from .changes import Changes
        self.changes=Changes();self._geometry_cache=None;self._last_time=None;self._live_settings=None;self._asset_signature=[];self._asset_scene={};self._last_full_capture=0
        self.last_digest = None
        self.disposed = False
        self.sequence = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self._live_tick)
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel('MoonRay Preview')
        layout.addWidget(title)
        self.tabs = QtWidgets.QTabWidget()
        self.pages = {}
        for key, label in [('render', 'Render'), ('lighting', 'Lighting'), ('object', 'Objects'),
                           ('aovs', 'AOVs'), ('display', 'Color / LUT'), ('system', 'System')]:
            page = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(page)
            self.pages[key] = form
            scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QtWidgets.QFrame.NoFrame);scroll.setWidget(page)
            self.tabs.addTab(scroll, label)
        row = QtWidgets.QHBoxLayout()
        self.runtime = QtWidgets.QLineEdit(str(self.settings.value('runtime', native.default_runtime())))
        self.runtime.setPlaceholderText('Folder containing moonray.exe or blender.shared')
        browse = QtWidgets.QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        row.addWidget(QtWidgets.QLabel('MoonRay'))
        row.addWidget(self.runtime, 1)
        row.addWidget(browse)
        self.pages['system'].addRow(row)
        self.persistent_preview=QtWidgets.QCheckBox('Keep MoonRay loaded between preview updates')
        self.persistent_preview.setChecked(str(self.settings.value('persistent_preview','true')).lower()!='false')
        self.persistent_preview.setToolTip('Update compatible scene attributes in a persistent renderer. Structural edits reload the scene. Requires the bundled session-capable runtime; older runtimes use separate renders.')
        self.persistent_preview.toggled.connect(lambda value:self.settings.setValue('persistent_preview',value))
        self.pages['system'].addRow(self.persistent_preview)
        asset_controls=QtWidgets.QPushButton('Input color spaces and texture cache…');asset_controls.clicked.connect(self._edit_assets);self.pages['display'].addRow(asset_controls)
        asset_report=QtWidgets.QPushButton('Report scene assets…');asset_report.clicked.connect(self._report_assets);self.pages['system'].addRow(asset_report)
        package=QtWidgets.QPushButton('Package portable render scene…');package.clicked.connect(self._package_assets);self.pages['system'].addRow(package)
        controls = self.pages['render']
        self.size = QtWidgets.QComboBox()
        self.size.addItems(['320 px wide', '640 px wide', '960 px wide', 'Scene resolution'])
        self.size.setCurrentIndex(1)
        self.samples = QtWidgets.QSpinBox()
        self.samples.setRange(1, 64)
        self.samples.setValue(4)
        self.samples.setToolTip('MoonRay pixel sample grid side; 4 = 16 samples/pixel.')
        self.environment = QtWidgets.QDoubleSpinBox()
        self.environment.setRange(0, 100)
        self.environment.setSingleStep(.1)
        self.environment.setValue(0)
        self.environment.setToolTip('Additional uniform environment light; zero preserves scene lighting.')
        self.threads = QtWidgets.QSpinBox()
        self.threads.setRange(1, 256)
        self.threads.setValue(4)
        controls.addRow('Preview size', self.size)
        controls.addRow('Pixel sample grid', self.samples)
        self.ipr_width=QtWidgets.QComboBox()
        for value in (80,160,240):self.ipr_width.addItem('%d px maximum'%value,value)
        self.ipr_width.setCurrentIndex(max(0,self.ipr_width.findData(int(self.settings.value('ipr/width',160)))))
        self.ipr_samples=QtWidgets.QComboBox()
        for value in (1,4,16):self.ipr_samples.addItem('%d SPP maximum'%value,value)
        self.ipr_samples.setCurrentIndex(max(0,self.ipr_samples.findData(int(self.settings.value('ipr/samples',1)))))
        self.ipr_error=QtWidgets.QDoubleSpinBox();self.ipr_error.setRange(.1,1000);self.ipr_error.setDecimals(1)
        self.ipr_error.setValue(float(self.settings.value('ipr/error',100)));self.ipr_error.setSingleStep(10)
        self.ipr_error.setToolTip('Higher adaptive error stops sooner. The 1-SPP preset uses uniform sampling; higher caps use adaptive sampling from 2 SPP.')
        controls.addRow('IPR width cap',self.ipr_width)
        controls.addRow('IPR sample cap',self.ipr_samples)
        controls.addRow('IPR adaptive error',self.ipr_error)
        ipr_note=QtWidgets.QLabel('IPR uses uniform sampling at 1 SPP, adaptive sampling for higher caps, and one light/material/subsurface sample per grid side. Final renders and stored scene settings keep their regular quality.');ipr_note.setWordWrap(True);controls.addRow(ipr_note)

        self.region_enabled = QtWidgets.QCheckBox('Render region')
        controls.addRow(self.region_enabled)
        self.region_controls = []
        for label, value in [('Left (%)',0),('Top (%)',0),('Right (%)',100),('Bottom (%)',100)]:
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0,100)
            spin.setValue(value)
            spin.setEnabled(False)
            self.region_enabled.toggled.connect(spin.setEnabled)
            self.region_controls.append(spin)
            controls.addRow(label,spin)
        self.execution_mode=QtWidgets.QComboBox()
        self.execution_mode.addItem('Auto (XPU → Vector → Scalar)', 'auto')
        self.execution_mode.addItem('XPU (NVIDIA GPU + CPU)', 'xpu')
        self.execution_mode.addItem('Vector (CPU / AVX)', 'vectorized')
        self.execution_mode.addItem('Scalar (CPU)', 'scalar')
        self.pages['system'].addRow('Rendering mode', self.execution_mode)
        self.pages['system'].addRow('CPU threads', self.threads)
        self.timeout = QtWidgets.QSpinBox()
        self.timeout.setRange(0,10080)
        self.timeout.setSpecialValueText('No limit')
        self.timeout.setSuffix(' min')
        self.pages['system'].addRow('Render time limit',self.timeout)
        scene_controls=QtWidgets.QPushButton('Object light links, emitters and volumes…');scene_controls.clicked.connect(self._edit_production)
        self.pages['lighting'].addRow(scene_controls)
        geometry_assets=QtWidgets.QPushButton('Strands, points and VDB assets…');geometry_assets.clicked.connect(self._edit_production)
        self.pages['object'].addRow(geometry_assets)
        self.pages['lighting'].addRow('Uniform environment', self.environment)
        self.modo_environment = QtWidgets.QCheckBox('Use Modo environments')
        self.modo_environment.setChecked(True)
        self.pages['lighting'].addRow(self.modo_environment)
        self.environment_multiplier = QtWidgets.QDoubleSpinBox()
        self.environment_multiplier.setRange(0,10000)
        self.environment_multiplier.setValue(1)
        self.pages['lighting'].addRow('Modo environment multiplier',self.environment_multiplier)
        self.background_controls={}
        self.background_controls['mode']=QtWidgets.QComboBox()
        for title,key in [('Scene environment (lighting and background)','environment'),('Black background','black'),('Solid color','color'),('Environment image','image')]:
            self.background_controls['mode'].addItem(title,key)
        self.background_controls['color']=QtWidgets.QLineEdit('#000000')
        self.background_controls['image']=QtWidgets.QLineEdit()
        self.background_controls['intensity']=QtWidgets.QDoubleSpinBox()
        self.background_controls['intensity'].setRange(0,10000);self.background_controls['intensity'].setValue(1)
        self.background_controls['rotation']=QtWidgets.QDoubleSpinBox()
        self.background_controls['rotation'].setRange(-360,360)
        for key,label in [('mode','Camera background'),('color','Background color (#RRGGBB)'),('image','Background image (lat-long)'),('intensity','Background brightness'),('rotation','Background rotation (degrees)')]:
            self.pages['lighting'].addRow(label,self.background_controls[key])
        choose_background=QtWidgets.QPushButton('Choose background image...')
        choose_background.clicked.connect(self._browse_background)
        self.pages['lighting'].addRow(choose_background)
        self.light_multiplier = QtWidgets.QDoubleSpinBox()
        self.light_multiplier.setRange(0, 10000)
        self.light_multiplier.setValue(1)
        self.pages['lighting'].addRow('Modo light multiplier', self.light_multiplier)
        self.render_controls = {}
        for key, (default, minimum, maximum, label) in options.RENDER.items():
            if key in options.ENUMS:
                control = QtWidgets.QComboBox()
                for title,value in options.ENUMS[key]: control.addItem(title,value)
                control.setCurrentIndex(control.findData(default))
            elif isinstance(default,float):
                control=QtWidgets.QDoubleSpinBox();control.setDecimals(6);control.setRange(minimum,maximum);control.setValue(default);control.setSingleStep(.1)
            else:
                control = QtWidgets.QSpinBox()
                control.setRange(minimum, maximum)
                control.setValue(default)
            self.render_controls[key] = control
            controls.addRow(label, control)
        self.denoiser=QtWidgets.QComboBox()
        for title,value in [('Off','off'),('NVIDIA OptiX (GPU)','optix'),('Intel Open Image Denoise (CPU)','oidn_cpu')]: self.denoiser.addItem(title,value)
        controls.addRow('Beauty denoiser',self.denoiser)
        self.denoise_preview=QtWidgets.QCheckBox('Denoise beauty preview');self.denoise_preview.setChecked(True)
        self.denoise_final=QtWidgets.QCheckBox('Save separate denoised beauty EXR');self.denoise_final.setChecked(True)
        controls.addRow(self.denoise_preview);controls.addRow(self.denoise_final)
        note=QtWidgets.QLabel('Adaptive limits are samples per pixel, not grid sizes. Lower target error means cleaner, slower renders. Denoising preserves the original linear EXR and AOVs.');note.setWordWrap(True);controls.addRow(note)
        self.render_controls['sampling_mode'].currentIndexChanged.connect(self._sampling_controls)
        self.render_controls['light_sampling_mode'].currentIndexChanged.connect(self._sampling_controls)
        self._sampling_controls()
        surface = self.pages['object']
        self.surface = QtWidgets.QComboBox()
        self.surface.addItems(['As modeled', 'Smooth subdivision', 'Modo evaluated geometry (experimental)'])
        self.surface.setToolTip('Modo evaluated geometry uses Modo render tessellation and displacement. MoonRay subdivision overrides are bypassed in this mode.')
        self.subdivision_level = QtWidgets.QSpinBox()
        self.subdivision_level.setRange(1, 5)
        self.subdivision_level.setValue(3)
        self.subdivision_level.setToolTip('Detail for subdivision surfaces. Higher levels use more memory and take longer to render.')
        surface.addRow('Scene default surface', self.surface)
        surface.addRow('Default subdivision level', self.subdivision_level)
        self.selected_object = QtWidgets.QLabel('Select a mesh, instance or replicator in Modo')
        self.selected_object.setWordWrap(True)
        surface.addRow(self.selected_object)
        self.object_controls = {}
        for key, (default, label) in options.OBJECT.items():
            if type(default) is bool:
                widget = QtWidgets.QCheckBox()
                widget.setChecked(default)
            elif type(default) is float:
                widget = QtWidgets.QDoubleSpinBox()
                widget.setDecimals(2)
                widget.setRange(0.1 if key=='tessellation_angle' else 0,64 if key=='adaptive_error' else 180)
                widget.setValue(default)
            else:
                widget = QtWidgets.QSpinBox()
                widget.setRange(1, 5)
                widget.setValue(default)
            self.object_controls[key] = widget
            surface.addRow(label, widget)
        geometry_note=QtWidgets.QLabel('Angle-based density estimates use the subdivision level as a cap. Evaluated geometry keeps Modo tessellation; normals can be overridden. Smoothing angles do not replace subdivision creases. Camera-adaptive subdivision expands instances and uses 2 pixels when screen error is zero.')
        geometry_note.setWordWrap(True)
        surface.addRow(geometry_note)
        self.object_apply = QtWidgets.QPushButton('Apply to selected geometry')
        self.object_apply.clicked.connect(self._save_object)
        surface.addRow(self.object_apply)
        self.aov_controls = {}
        aov_text = QtWidgets.QLabel('Beauty RGB is always written. Checked AOVs are additional channels in the same 32-bit linear EXR. Choose the displayed buffer above the preview. EXR selections below control saved output.')
        aov_text.setWordWrap(True)
        self.pages['aovs'].addRow(aov_text)
        for key, (label, attributes, channel) in options.AOVS.items():
            checkbox = QtWidgets.QCheckBox(label + '  [' + channel + ']')
            checkbox.setChecked(key == 'alpha')
            self.aov_controls[key] = checkbox
            self.pages['aovs'].addRow(checkbox)
        edit_outputs=QtWidgets.QPushButton('Configure named outputs…');edit_outputs.clicked.connect(self._edit_outputs);self.pages['aovs'].addRow(edit_outputs)
        from .display import DEFAULTS
        self.display_controls = {}
        for key,label in [('view','Display transform'),('exposure','Exposure (stops)'),('lut','LUT file'),
                          ('lut_space','LUT input'),('config','OCIO config (optional)'),
                          ('source','OCIO linear source'),('display','OCIO display'),('ocio_view','OCIO view')]:
            if key in ('view','lut_space'):
                widget=QtWidgets.QComboBox()
                choices=[('Highlight compression + sRGB','reinhard'),('sRGB','srgb'),('Raw linear','raw'),('OCIO display / view','ocio')] if key=='view' else [('After display transform','display'),('Scene-linear, before view','linear')]
                for title,value in choices: widget.addItem(title,value)
            elif key=='exposure':
                widget=QtWidgets.QDoubleSpinBox();widget.setRange(-20,20);widget.setSingleStep(.25)
            else:
                widget=QtWidgets.QLineEdit(DEFAULTS[key])
            self.display_controls[key]=widget
            if key in ('lut','config'):
                row=QtWidgets.QHBoxLayout();row.addWidget(widget)
                button=QtWidgets.QPushButton('Browse...')
                button.clicked.connect(lambda checked=False,k=key:self._browse_display(k))
                row.addWidget(button);self.pages['display'].addRow(label,row)
            else: self.pages['display'].addRow(label,widget)
        note=QtWidgets.QLabel('Display controls affect Beauty and lighting buffers only. EXRs remain linear. Select a LUT matching its chosen input space. Depth, normals and other data buffers bypass the view transform.')
        note.setWordWrap(True);self.pages['display'].addRow(note)
        lighting_note = QtWidgets.QLabel('Glass uses Modo Transparency Amount/Color, Refraction Index, Roughness and Transparency Roughness. Use closed meshes for solid glass. Start with IOR 1.5 and Transparency 100%; increase Glossy and Mirror/refraction bounces for multiple glass surfaces. UV images can drive transmission amount, color and roughness. Absorption distance uses a closed-volume model. Dispersion is not translated. New material features are unverified; see compatibility notices below.')
        lighting_note.setWordWrap(True)
        self.pages['lighting'].addRow(lighting_note)
        self.final_motion=QtWidgets.QCheckBox('Include motion blur / motion vectors in final outputs');controls.addRow(self.final_motion)
        self.checkpoint=QtWidgets.QCheckBox('Save checkpoints for final renders');controls.addRow(self.checkpoint)
        self.resume_checkpoint=QtWidgets.QCheckBox('Resume matching checkpoint');self.resume_checkpoint.setChecked(True);controls.addRow(self.resume_checkpoint)
        self.checkpoint_minutes=QtWidgets.QDoubleSpinBox();self.checkpoint_minutes.setRange(.1,1440);self.checkpoint_minutes.setValue(1);controls.addRow('Checkpoint interval (minutes)',self.checkpoint_minutes)
        save_settings = QtWidgets.QPushButton('Store render settings in scene')
        save_settings.clicked.connect(self._save_settings)
        controls.addRow(save_settings)
        animation = QtWidgets.QPushButton('Render animation…')
        animation.clicked.connect(self.render_animation)
        controls.addRow(animation)
        actions = QtWidgets.QHBoxLayout()
        self.start = QtWidgets.QPushButton('Refresh preview')
        self.start.setToolTip('Capture the current scene and start a fresh preview. The previous image stays visible until its replacement is ready.')
        self.start.clicked.connect(self.render_once)
        stop = QtWidgets.QPushButton('Stop')
        stop.clicked.connect(self.stop)
        self.live = QtWidgets.QCheckBox('Live updates')
        self.live.toggled.connect(self._toggle_live)
        self.preview_lock=QtWidgets.QCheckBox('Lock preview')
        self.preview_lock.setToolTip('Keep the current render running. Hold automatic scene changes until unlocked; cached buffers and display transforms remain available. Refresh preview still starts a new preview explicitly.')
        self.preview_lock.toggled.connect(self._lock_changed)
        self.final = QtWidgets.QPushButton('Render EXR…')
        self.final.clicked.connect(self.render_final)
        export = QtWidgets.QPushButton('Export scene…')
        export.clicked.connect(self.export)
        self.settings_toggle = QtWidgets.QPushButton('Settings')
        self.settings_toggle.setCheckable(True)
        self.settings_toggle.setChecked(True)
        self.settings_toggle.toggled.connect(self.tabs.setVisible)
        for widget in (self.start, stop, self.live, self.preview_lock, self.settings_toggle, self.final, export):
            actions.addWidget(widget)
        layout.addLayout(actions)
        buffer_row = QtWidgets.QHBoxLayout()
        self.ipr_mode=QtWidgets.QCheckBox('IPR')
        self.ipr_mode.setToolTip('Start live previews with lower resolution and sampling. Disable to return to regular preview quality. Stops remain manual; no automatic full-quality refinement.')
        buffer_row.addWidget(self.ipr_mode)
        buffer_row.addWidget(QtWidgets.QLabel('Render buffer'))
        self.buffer = QtWidgets.QComboBox()
        self.buffer.addItem('Beauty','beauty')
        for key,(label,attributes,channel) in options.AOVS.items():
            self.buffer.addItem(label,key)
        self.buffer.setToolTip('Switch buffers from the last completed preview without restarting rendering. Available after the first pass. Saved EXR values are unchanged.')
        buffer_row.addWidget(self.buffer,1)
        layout.addLayout(buffer_row)
        self.preview = Preview()
        self.preview.start_requested.connect(self.render_once)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter=split
        split.addWidget(self.tabs)
        split.addWidget(self.preview)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 580])
        layout.addWidget(split, 1)
        self.render_progress=QtWidgets.QProgressBar()
        self.render_progress.setRange(0,100);self.render_progress.setValue(0)
        self.render_progress.setToolTip('MoonRay progress for the current pass. Adaptive sampling estimates can change; preparation and denoising have no reliable percentage.')
        self.render_timing=QtWidgets.QLabel('Elapsed 0m 00s · Remaining: —')
        layout.addWidget(self.render_progress);layout.addWidget(self.render_timing)
        self.renderer.progress.connect(self._render_progress)
        self.status = QtWidgets.QLabel('Ready. Click the preview or choose Refresh preview.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.image_info=QtWidgets.QLabel('No rendered image yet')
        layout.addWidget(self.image_info)
        self.notice_toggle=QtWidgets.QToolButton();self.notice_toggle.setText('Scene notices (0)');self.notice_toggle.setCheckable(True);self.notice_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon);self.notice_toggle.setArrowType(QtCore.Qt.RightArrow)
        layout.addWidget(self.notice_toggle)
        self.warnings=QtWidgets.QPlainTextEdit();self.warnings.setReadOnly(True);self.warnings.setMaximumHeight(150);self.warnings.hide()
        self.warnings.setPlaceholderText('Scene compatibility notices appear after capture. No notices does not guarantee full scene parity.')
        self.notice_toggle.toggled.connect(self._toggle_notices);layout.addWidget(self.warnings)
        footer = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton('Save preview…')
        save.clicked.connect(self.save_preview)
        log = QtWidgets.QPushButton('Render log…')
        log.clicked.connect(self.show_log)
        fit = QtWidgets.QPushButton('Fit image')
        fit.clicked.connect(self.preview.fit)
        footer.addWidget(fit)
        actual=QtWidgets.QPushButton('100%');actual.setToolTip('Show one rendered pixel per screen pixel');actual.clicked.connect(self.preview.actual_size);footer.addWidget(actual)
        footer.addWidget(save)
        copy_image=QtWidgets.QPushButton('Copy image');copy_image.clicked.connect(self.copy_image);footer.addWidget(copy_image)
        footer.addWidget(log)
        footer.addStretch()
        layout.addLayout(footer)
        self.renderer.status.connect(self.status.setText)
        self.renderer.failed.connect(self._failed)
        self.renderer.image_ready.connect(self._image)
        self.renderer.finished.connect(self._finished)
        self._scene_id = None
        self._object_signature = None
        self._load_settings()
        self.buffer.currentIndexChanged.connect(self._buffer_changed)
        self.execution_mode.currentIndexChanged.connect(self._preview_changed)
        self.display_timer=QtCore.QTimer(self)
        self.display_timer.setSingleShot(True);self.display_timer.setInterval(200)
        self.display_timer.timeout.connect(lambda:self._buffer_changed(0))
        self.preview_timer=QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(400)
        self.preview_timer.timeout.connect(lambda:self._preview_changed(0))
        for controls,timer in ((self.display_controls,self.display_timer),(self.background_controls,self.preview_timer)):
            for control in controls.values():
                signal=control.currentIndexChanged if isinstance(control,QtWidgets.QComboBox) else control.valueChanged if isinstance(control,QtWidgets.QDoubleSpinBox) else control.editingFinished
                signal.connect(lambda *args,t=timer:t.start())
        self.selection_timer = QtCore.QTimer(self)
        self.selection_timer.setInterval(750)
        self.selection_timer.timeout.connect(self._refresh_object)
        self.selection_timer.start()
        self._refresh_object()
        stored_split=self.settings.value('workspace/splitter')
        if isinstance(stored_split,QtCore.QByteArray):self.splitter.restoreState(stored_split)
        try:self.tabs.setCurrentIndex(max(0,min(self.tabs.count()-1,int(self.settings.value('workspace/tab',0)))))
        except (ValueError,TypeError):pass
        self.settings_toggle.setChecked(str(self.settings.value('workspace/settings_visible','true')).lower()!='false')
        self.splitter.splitterMoved.connect(self._store_workspace)
        self.tabs.currentChanged.connect(self._store_workspace)
        self.settings_toggle.toggled.connect(self._store_workspace)
        self.ipr_mode.toggled.connect(self._ipr_changed)
        self.ipr_width.currentIndexChanged.connect(self._ipr_quality_changed)
        self.ipr_samples.currentIndexChanged.connect(self._ipr_quality_changed)
        self.ipr_error.valueChanged.connect(self._ipr_quality_changed)


    def _ipr_changed(self,enabled):
        self.preview_timer.stop()
        if self._output_busy():
            self.status.setText('IPR selection saved for the next preview. Output render continues.');return
        if enabled and not self.live.isChecked():
            self.live.setChecked(True)
        else:
            self._preview_changed(0)

    def _ipr_quality_changed(self,*args):
        self.settings.setValue('ipr/width',self.ipr_width.currentData())
        self.settings.setValue('ipr/samples',self.ipr_samples.currentData())
        self.settings.setValue('ipr/error',self.ipr_error.value())
        if self.ipr_mode.isChecked():self.preview_timer.start()

    def _store_workspace(self,*args):
        self.settings.setValue('workspace/splitter',self.splitter.saveState())
        self.settings.setValue('workspace/tab',self.tabs.currentIndex())
        self.settings.setValue('workspace/settings_visible',self.settings_toggle.isChecked())

    def _toggle_notices(self,visible):
        self.warnings.setVisible(visible)
        self.notice_toggle.setArrowType(QtCore.Qt.DownArrow if visible else QtCore.Qt.RightArrow)

    def _set_notices(self,messages):
        unique=list(dict.fromkeys(str(message) for message in messages if message))
        text='\n\n'.join(unique)
        if text!=self.warnings.toPlainText():self.warnings.setPlainText(text)
        self.notice_toggle.setText('Scene notices (%d)'%len(unique))
        self.notice_toggle.setToolTip('Expand to read or copy scene translation notices')

    def _output_busy(self):
        return (self.sequence is not None and self.sequence.running) or bool(self.renderer.pending and self.renderer.pending.get('output')) or bool(self.renderer.active and self.renderer.active.get('output') and self.renderer.process.state()!=QtCore.QProcess.NotRunning)

    def _lock_changed(self,locked):
        if locked:
            self.timer.stop()
            if hasattr(self,'preview_timer'):self.preview_timer.stop()
            self.status.setText('Preview locked. Automatic updates are held; the current render continues.')
        else:
            self.status.setText('Preview unlocked. Refresh to apply changes, or enable Live updates.')
            if self.live.isChecked():self.timer.start();self._live_tick()

    def copy_image(self):
        if self.preview.image.isNull():self.status.setText('Render a preview first.');return
        QtWidgets.QApplication.clipboard().setImage(self.preview.image)
        self.status.setText('Displayed image copied. Use Render EXR for linear output.')

    def show_page(self, page):
        if page in self.pages:
            self.settings_toggle.setChecked(True)
            self.tabs.setCurrentIndex(list(self.pages).index(page))

    def _load_settings(self):
        import modo
        self._scene_id = modo.Scene().renderItem.id
        values = properties.scene_settings()
        recovery=values.get('recovery',{})
        self.checkpoint.setChecked(recovery.get('enabled',False));self.resume_checkpoint.setChecked(recovery.get('resume',True));self.checkpoint_minutes.setValue(recovery.get('minutes',1))
        self.custom_aovs=values.get('custom_aovs',[])
        self.production=values.get('production',{})
        self.final_motion.setChecked(values.get('final_motion',False))
        self.asset_settings=values.get('asset_settings',{})
        self._sync_output_menu()
        mode=values.get('execution_mode',native.default_execution_mode(self.runtime.text()))
        self.execution_mode.blockSignals(True)
        self.execution_mode.setCurrentIndex(max(0,self.execution_mode.findData(mode)))
        self.execution_mode.blockSignals(False)
        self.buffer.blockSignals(True)
        self.buffer.setCurrentIndex(max(0,self.buffer.findData(values.get('preview_buffer','beauty'))))
        self.buffer.blockSignals(False)
        from .display import values as display_values
        for key,value in display_values(values.get('display',{})).items():
            control=self.display_controls[key];control.blockSignals(True)
            if isinstance(control,QtWidgets.QComboBox): control.setCurrentIndex(max(0,control.findData(value)))
            elif isinstance(control,QtWidgets.QDoubleSpinBox): control.setValue(value)
            else: control.setText(value)
            control.blockSignals(False)
        from .background import DEFAULTS as background_defaults
        for key,value in dict(background_defaults,**values.get('background',{})).items():
            if key not in self.background_controls: continue
            control=self.background_controls[key];control.blockSignals(True)
            if isinstance(control,QtWidgets.QComboBox): control.setCurrentIndex(max(0,control.findData(value)))
            elif isinstance(control,QtWidgets.QDoubleSpinBox): control.setValue(value)
            else: control.setText(value)
            control.blockSignals(False)
        denoise=values.get('denoising',{})
        self.denoiser.setCurrentIndex(max(0,self.denoiser.findData(denoise.get('engine','off'))))
        self.denoise_preview.setChecked(denoise.get('preview',True));self.denoise_final.setChecked(denoise.get('final',True))
        stored=dict(values.get('render',{}))
        if stored and 'sampling_mode' not in stored: stored['sampling_mode']=0
        for key, value in options.render_values(stored).items():
            control = self.render_controls[key]
            control.setCurrentIndex(control.findData(value)) if isinstance(control, QtWidgets.QComboBox) else control.setValue(value)
        for key, control in self.aov_controls.items():
            control.setChecked(key in values.get('aovs', ['alpha']))
        for key, control, default in [('samples', self.samples, 4), ('environment', self.environment, 0),
                             ('threads', self.threads, 4), ('subdivision_level', self.subdivision_level, 3),
                             ('light_multiplier', self.light_multiplier, 1)]:
            control.setValue(values.get(key, default))
        self.surface.setCurrentIndex(int(values.get('surface', 0)))
        self.modo_environment.setChecked(values.get('modo_environment',True))
        self.environment_multiplier.setValue(values.get('environment_multiplier',1))
        self.region_enabled.setChecked(values.get('region_enabled',False))
        for control,value in zip(self.region_controls,values.get('region',[0,0,1,1])):
            control.setValue(value*100)

    def _settings_values(self):
        return {'final_motion':self.final_motion.isChecked(),'production':self.production,'asset_settings':self.asset_settings,'recovery':{'enabled':self.checkpoint.isChecked(),'resume':self.resume_checkpoint.isChecked(),'minutes':self.checkpoint_minutes.value()},'custom_aovs':self.custom_aovs,'render': {key: control.currentData() if isinstance(control, QtWidgets.QComboBox) else control.value()
                           for key, control in self.render_controls.items()},
                'background': {key:control.currentData() if isinstance(control,QtWidgets.QComboBox) else control.value() if isinstance(control,QtWidgets.QDoubleSpinBox) else control.text().strip() for key,control in self.background_controls.items()},
                'display': {key:control.currentData() if isinstance(control,QtWidgets.QComboBox) else control.value() if isinstance(control,QtWidgets.QDoubleSpinBox) else control.text().strip() for key,control in self.display_controls.items()},
                'preview_buffer': self.buffer.currentData(),
                'execution_mode': self.execution_mode.currentData(),
                'denoising': {'engine':self.denoiser.currentData(),'preview':self.denoise_preview.isChecked(),'final':self.denoise_final.isChecked()},
                'aovs': [key for key, control in self.aov_controls.items() if control.isChecked()],
                'samples': self.samples.value(), 'environment': self.environment.value(),
                'threads': self.threads.value(), 'surface': self.surface.currentIndex(),
                'subdivision_level': self.subdivision_level.value(), 'light_multiplier': self.light_multiplier.value(),
                'modo_environment':self.modo_environment.isChecked(),
                'environment_multiplier':self.environment_multiplier.value(),
                'region_enabled':self.region_enabled.isChecked(),
                'region':[control.value()/100 for control in self.region_controls]}

    def _sync_output_menu(self):
        key=self.buffer.currentData();self.buffer.blockSignals(True)
        while self.buffer.count()>1+len(options.AOVS):self.buffer.removeItem(self.buffer.count()-1)
        for v in self.custom_aovs:
            if v['kind']!='cryptomatte':self.buffer.addItem(v['name'],v['name'])
        self.buffer.setCurrentIndex(max(0,self.buffer.findData(key)));self.buffer.blockSignals(False)

    def _edit_outputs(self):
        from .outputs_dialog import OutputsDialog
        dialog=OutputsDialog(self.custom_aovs,self)
        if dialog.exec_():
            self.custom_aovs=dialog.entries;self._sync_output_menu()
            self.status.setText('Named outputs updated. Refresh preview to populate new buffers; store render settings to save them with the scene.')

    def _edit_assets(self):
        from .assets_dialog import AssetsDialog
        dialog=AssetsDialog(self.asset_settings,self)
        if dialog.exec_()==QtWidgets.QDialog.Accepted:
            self.asset_settings=dialog.entries;self._save_settings();self.changes.invalidate()

    def _report_assets(self):
        try:
            from .assets import inventory
            scene=self._capture();entries=inventory(scene)
            text='\n'.join(('%s | %d file(s) | %.1f MB | %s'%('MISSING' if v['missing'] else 'Found',v['tiles'],v['bytes']/1048576,v['path'])) for v in entries)
            text+='\n\nScene notices:\n'+'\n'.join(scene.get('warnings',[]))
            dialog=QtWidgets.QDialog(self);dialog.setWindowTitle('Scene asset report');dialog.resize(900,480);layout=QtWidgets.QVBoxLayout(dialog);view=QtWidgets.QPlainTextEdit(text);view.setReadOnly(True);layout.addWidget(view);dialog.exec_()
        except Exception as exc:self._failed(str(exc))

    def _package_assets(self):
        path=self._save_path('New portable scene folder','package','','All names (*)')
        if not path:return
        try:
            from .assets import package
            scene=self._capture_output();width,height=self._dimensions(scene,True)
            output=package(scene,path,width,height,self.samples.value(),self.environment.value())
            self.status.setText('Packaged render scene: '+output)
        except Exception as exc:self._failed(str(exc))

    def _edit_production(self):
        from .production_dialog import Controls
        dialog=Controls(self.production,self)
        if dialog.exec_()==QtWidgets.QDialog.Accepted:
            self.production=dialog.values;self._save_settings();self.changes.invalidate()
            self.status.setText('Scene controls saved. Refresh preview to apply.')

    def _sampling_controls(self,*args):
        adaptive=self.render_controls['sampling_mode'].currentData()==2
        self.samples.setEnabled(not adaptive)
        for key in ('min_adaptive_samples','max_adaptive_samples','target_adaptive_error'): self.render_controls[key].setEnabled(adaptive)
        self.render_controls['light_sampling_quality'].setEnabled(self.render_controls['light_sampling_mode'].currentData()==1)

    def _save_settings(self):
        try:
            lx.eval('moonray.sceneSettings ' + properties.encode(self._settings_values()))
            self.status.setText('Render settings stored in scene. Save the Modo scene to keep them on disk.')
        except Exception as exc:
            self.status.setText('Cannot store settings: ' + str(exc))

    def _refresh_object(self):
        try:
            selected = properties.selected_geometry()
            signature = [(item.id, properties.read(item)) for item in selected]
            if signature == self._object_signature:
                return
            self._object_signature = signature
            self.object_apply.setEnabled(bool(selected))
            self.selected_object.setText(', '.join(item.name for item in selected) or 'Select a mesh, instance or replicator in Modo')
            values = options.object_values(properties.read(selected[0])) if selected else options.object_values({})
            for key, widget in self.object_controls.items():
                widget.setEnabled(bool(selected))
                widget.setChecked(values[key]) if isinstance(widget, QtWidgets.QCheckBox) else widget.setValue(values[key])
        except Exception:
            self.object_apply.setEnabled(False)

    def _save_object(self):
        try:
            values = {key: control.isChecked() if isinstance(control, QtWidgets.QCheckBox) else control.value()
                      for key, control in self.object_controls.items()}
            lx.eval('moonray.objectSettings ' + properties.encode(values))
            self._object_signature = None
            self._refresh_object()
            self.status.setText('Object properties updated. Per-object overrides take precedence over scene defaults.')
        except Exception as exc:
            self.status.setText('Cannot update object properties: ' + str(exc))

    def _browse_background(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Background environment image','','Images (*.exr *.hdr *.tx *.png *.jpg *.jpeg *.tif *.tiff);;All files (*)')
        if path:
            self.background_controls['image'].setText(path)
            self.background_controls['mode'].setCurrentIndex(self.background_controls['mode'].findData('image'))
            self.preview_timer.start()

    def _browse_display(self, key):
        filters='LUT files (*.cube *.spi1d *.spi3d *.3dl *.clf *.ctf);;All files (*)' if key=='lut' else 'OCIO config (*.ocio);;All files (*)'
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Select '+key,'',filters)
        if path:
            self.display_controls[key].setText(path)
            self.display_timer.start()

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose native Windows MoonRay runtime', self.runtime.text())
        if path:
            self.runtime.setText(path)

    def _dimensions(self, scene, final=False):
        scene_w, scene_h = scene['width'], scene['height']
        width = scene_w if final or self.size.currentIndex() == 3 else (320, 640, 960)[self.size.currentIndex()]
        return width, max(16, round(width * scene_h / max(1, scene_w)))

    def _capture(self,reuse=False):
        import modo
        if modo.Scene().renderItem.id != self._scene_id:
            self._load_settings();self._geometry_cache=None
        scene = host.snapshot(evaluated_geometry=self.surface.currentIndex() == 2,reuse_geometry=self._geometry_cache if reuse else None)
        import copy,time
        if not reuse:
            self._geometry_cache=dict(scene,meshes=[dict(m) for m in scene['meshes']],materials=copy.deepcopy(scene['materials']),native_materials=copy.deepcopy(scene.get('native_materials',{})))
            self._last_full_capture=time.monotonic()
        scene['_geometry_revision']=str(id(self))+':'+str(self._last_full_capture)
        configured=self._configure_snapshot(scene)
        from .assets import signature
        self._asset_scene=configured;self._asset_signature=signature(configured)
        return configured

    def _capture_output(self):
        if not self.final_motion.isChecked():return self._capture()
        from .animation import capture_current
        return self._configure_snapshot(capture_current(self.surface.currentIndex()==2))

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
        scene['display'] = display_values(values['display'])
        if values['region_enabled']:
            scene['region'] = values['region']
        if not self.modo_environment.isChecked():
            scene['environments']=[]
        for environment in scene.get('environments',[]):
            environment['intensity'] *= self.environment_multiplier.value()
        from .background import apply as apply_background
        apply_background(scene,values['background'])
        for light in scene['lights']:
            light['intensity'] *= self.light_multiplier.value()
        for mesh in scene['meshes']:
            if mesh.get('object_override'):
                continue
            if self.surface.currentIndex() == 1:
                mesh['subdivision'] = True
            mesh['subdivision_level'] = self.subdivision_level.value()
        if self.surface.currentIndex() == 1:
            scene['warnings'].append('Smooth subdivision rounds all exported meshes, including sharp edges.')
        self._set_notices(scene['warnings'])
        return scene

    def _submit(self, scene, output=None):
        width, height = self._dimensions(scene, bool(output))
        original_digest=self._digest(scene)
        if self.ipr_mode.isChecked() and not output:
            from .ipr import prepare
            scene,width,height=prepare(scene,width,height,self.samples.value(),
                                       self.ipr_width.currentData(),self.ipr_samples.currentData(),self.ipr_error.value())
        self.renderer.timeout_seconds = self.timeout.value()*60
        self.renderer.submit(scene, self.runtime.text(), width, height, 1 if scene.get('_ipr') and not output else self.samples.value(),
                             self.environment.value(), self.threads.value(), output, persistent_preview=self.persistent_preview.isChecked())
        self.settings.setValue('runtime', self.runtime.text())
        self.last_digest = original_digest

    def _digest(self, scene):
        render_scene={key:value for key,value in scene.items() if key not in ('preview_buffer','display','aovs','recovery','_geometry_revision')}
        values = [render_scene, self.runtime.text(), self.size.currentIndex(), self.samples.value(), self.environment.value(), self.threads.value(), self.persistent_preview.isChecked(), self.ipr_mode.isChecked(), self.ipr_width.currentData(), self.ipr_samples.currentData(), self.ipr_error.value()]
        digest = hashlib.sha256()
        for chunk in json.JSONEncoder(sort_keys=True,separators=(',',':')).iterencode(values):
            digest.update(chunk.encode('utf-8'))
        return digest.hexdigest()

    def _buffer_changed(self,index):
        if self.disposed:return
        try:
            from .display import values
            display=values(self._settings_values()['display'])
            self.renderer.buffers.select(self.buffer.currentData(),display)
        except Exception as exc:
            self.status.setText('Cannot update buffer display: '+str(exc))

    def _preview_changed(self, index):
        if self.disposed: return
        if self.preview_lock.isChecked():
            self.status.setText('Preview locked. Selection saved for the next refresh.');return
        if (self.sequence is not None and self.sequence.running) or (
                self.renderer.active and self.renderer.active.get('output') and
                self.renderer.process.state()!=QtCore.QProcess.NotRunning):
            self.status.setText('Preview settings changed. They will apply after the output render finishes.')
            return
        self.render_once()

    def render_once(self):
        if self._output_busy():
            self.status.setText('Output render is running. Press Stop before starting a preview.');return
        try:
            self._submit(self._capture())
        except Exception as exc:
            self._failed(str(exc))

    def _toggle_live(self, on):
        if on and self.preview_lock.isChecked():
            self.status.setText('Live updates will resume when the preview is unlocked.');return
        if on:
            self.render_once()
            if self.live.isChecked():
                self.timer.start()
        else:
            self.timer.stop()

    def _live_tick(self):
        if self.disposed or self.preview_lock.isChecked() or self._output_busy():
            return
        try:
            import modo
            full,items=self.changes.consume();time=lx.service.Selection().GetTime()
            import time as clock
            from .assets import signature
            # Periodic reconciliation covers host notifications omitted by some
            # procedural mesh providers. Normal idle ticks do not capture geometry.
            full=full or clock.monotonic()-self._last_full_capture>15 or signature(self._asset_scene)!=self._asset_signature
            settings={k:v for k,v in self._settings_values().items() if k not in ('display','preview_buffer','aovs','recovery')}
            changed=settings!=self._live_settings or time!=self._last_time or modo.Scene().renderItem.id!=self._scene_id
            if not (full or items or changed):return
            reuse=not full and not changed and bool(items) and self._geometry_cache is not None
            if reuse:
                for identity in items:
                    if modo.Scene().item(identity).type not in ('camera','sunLight','pointLight','areaLight','spotLight','lightMaterial'):
                        reuse=False;break
            scene = self._capture(reuse)
            self._last_time=time;self._live_settings=settings
            if self._digest(scene) != self.last_digest:self._submit(scene)
        except Exception as exc:
            self.changes.invalidate();self._failed(str(exc))

    def stop(self):
        self.preview_timer.stop()
        if self.sequence is not None:
            self.sequence.stop()
        self.live.setChecked(False)
        self.renderer.stop()

    def _failed(self, message):
        self.live.setChecked(False)
        self.renderer.stop()
        self.status.setText('Render unavailable: ' + message)

    def _image(self, path):
        try:
            self.preview.load(path)
            active=self.renderer.active or {};frame=self.renderer.buffers.displayed or {}
            snapshot=frame.get('snapshot',active.get('snapshot',{}))
            key=frame.get('key',snapshot.get('preview_buffer','beauty'));label='Beauty' if key=='beauty' else options.AOVS.get(key,(key,))[0]
            self.image_info.setText('Showing %s · %d × %d · %s'%(label,self.preview.image.width(),self.preview.image.height(),frame.get('backend',self.renderer.backend_status)))
            if frame:self.image_info.setText(self.image_info.text()+(' · Rendering' if frame.get('partial') else ' · Last completed preview'))
            if snapshot.get('_ipr'):
                settings=snapshot['render_settings']
                quality='1 SPP' if settings['max_adaptive_samples']==1 else '%d–%d SPP, error %g'%(settings['min_adaptive_samples'],settings['max_adaptive_samples'],settings['target_adaptive_error'])
                self.image_info.setText(self.image_info.text()+' · IPR '+quality)
        except ValueError as exc:
            self.status.setText('Cannot display cached preview: '+str(exc))

    def _render_progress(self,value,label):
        if self.sequence is not None and self.sequence.running:
            label='Frame %d (%d/%d) · %s'%(self.sequence.frame,len(self.sequence.completed)+1,self.sequence.total,label)
        self.render_progress.setRange(0,0 if value<0 else 100)
        if value>=0: self.render_progress.setValue(value)
        self.render_timing.setText(label)

    def _finished(self, output):
        message=('Saved ' + output) if output else ('Preview complete' + (' · Watching scene changes' if self.live.isChecked() else ''))
        if not output and self.renderer.session.running():message+=' · MoonRay session retained'
        self.status.setText(message+' · '+self.renderer.backend_status)

    def _save_path(self,title,key,suffix,name_filter):
        dialog=QtWidgets.QFileDialog(self,title,str(self.settings.value('output/'+key,'')))
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dialog.setNameFilter(name_filter);dialog.setDefaultSuffix(suffix)
        if not dialog.exec_():return ''
        path=dialog.selectedFiles()[0]
        self.settings.setValue('output/'+key,str(Path(path).parent))
        return path

    def render_final(self):
        if self._output_busy():self.status.setText('An output render is running. Press Stop before starting another.');return
        path=self._save_path('Render OpenEXR','exr','exr','OpenEXR (*.exr)')
        if not path:
            return
        self.stop()
        try:
            self._submit(self._capture_output(), path)
        except Exception as exc:
            self._failed(str(exc))

    def export(self):
        path=self._save_path('Export MoonRay scene','rdla','rdla','MoonRay scene (*.rdla)')
        if not path:
            return
        try:
            scene = self._capture_output()
            width, height = self._dimensions(scene, True)
            text = rdla.scene_text(scene, width, height, self.samples.value(), self.environment.value(),
                                   str(Path(path).with_suffix('.exr')))
            Path(path).write_text(text, encoding='utf-8')
            self.status.setText('Exported ' + path)
        except Exception as exc:
            self._failed(str(exc))

    def save_preview(self):
        if self.preview.image.isNull():
            self.status.setText('Render a preview first.')
            return
        path=self._save_path('Save preview','png','png','PNG image (*.png)')
        if path:
            self.status.setText('Saved '+path if self.preview.image.save(path,'PNG') else 'Could not save the preview image.')

    def show_log(self):
        dialog = QtWidgets.QDialog(self);dialog.setWindowTitle('MoonRay render log');dialog.resize(820,500)
        layout=QtWidgets.QVBoxLayout(dialog);row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        search=QtWidgets.QLineEdit();search.setPlaceholderText('Find in render log…');row.addWidget(search,1)
        find=QtWidgets.QPushButton('Find next');row.addWidget(find)
        text=QtWidgets.QPlainTextEdit(self.renderer.log or 'No renderer output yet.');text.setReadOnly(True);layout.addWidget(text)
        def find_next():
            if not search.text():return
            follow.setChecked(False)
            if not text.find(search.text()):
                cursor=text.textCursor();cursor.movePosition(QtGui.QTextCursor.Start);text.setTextCursor(cursor);text.find(search.text())
        find.clicked.connect(find_next);search.returnPressed.connect(find_next)
        footer=QtWidgets.QHBoxLayout();layout.addLayout(footer)
        copy=QtWidgets.QPushButton('Copy log');copy.clicked.connect(lambda:QtWidgets.QApplication.clipboard().setText(text.toPlainText()));footer.addWidget(copy)
        save=QtWidgets.QPushButton('Save log…');footer.addWidget(save)
        def save_log():
            path=self._save_path('Save render log','log','txt','Text (*.txt)')
            if path:
                try:Path(path).write_text(text.toPlainText(),encoding='utf-8')
                except OSError as exc:QtWidgets.QMessageBox.warning(dialog,'Cannot save log',str(exc))
        save.clicked.connect(save_log)
        follow=QtWidgets.QCheckBox('Follow live output');follow.setChecked(True);footer.addWidget(follow)
        timer=QtCore.QTimer(dialog);timer.setInterval(750)
        def refresh():
            current=self.renderer.log or 'No renderer output yet.'
            if follow.isChecked() and current!=text.toPlainText():
                text.setPlainText(current);bar=text.verticalScrollBar();bar.setValue(bar.maximum())
        timer.timeout.connect(refresh);timer.start();dialog.exec_();timer.stop()

    def dispose(self):
        if not self.disposed:
            self._store_workspace()
            self.disposed = True
            self.changes.close()
            self.display_timer.stop()
            self.preview_timer.stop()
            self.timer.stop()
            self.selection_timer.stop()
            if self.sequence is not None:
                self.sequence.stop()
            self.renderer.close()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)

    def render_animation(self):
        if self._output_busy():self.status.setText('An output render is running. Press Stop before starting an animation.');return
        from .output_dialog import AnimationDialog
        from .animation import Sequence
        dialog=AnimationDialog(self.settings,self)
        if not dialog.exec_():return
        directory=dialog.folder.text().strip()
        try:
            candidate=Sequence(self,directory,dialog.first.value(),dialog.last.value(),
                               dialog.fps.value(),dialog.motion.isChecked(),
                               step=dialog.step.value(),prefix=dialog.prefix.text(),missing=dialog.missing.isChecked())
            self.settings.setValue('output/animation',directory)
            self.stop()
            self.sequence=candidate
            self.sequence.start()
        except Exception as exc:
            self._failed(str(exc))
