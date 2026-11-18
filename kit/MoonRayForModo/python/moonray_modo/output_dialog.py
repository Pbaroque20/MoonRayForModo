"""Output controls for frame sequence rendering."""
from pathlib import Path
from PySide2 import QtWidgets
from .sequence_plan import DIGITS, frame_name


# Before a type in the Frames As list: saved in that type alone.
ONLY='only:'


class AnimationDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None, values=None):
        super().__init__(parent)
        # What it opens with: sequence_plan.window_values, the scene's settings and what it last rendered with.
        values=values or {}
        self.setWindowTitle('Render animation');self.resize(520,300)
        form=QtWidgets.QFormLayout(self)
        # Which engine renders the frames: MoonRay (XPU), MoonRay itself in Render Settings' execution mode; MoonRay (XPU2),
        # XPU2 whatever renders the preview (render.xpu2_output); or MoonLightIPR, to Render Samples a pixel (Render
        # Settings, MoonLightIPR). 'moonray', kept before there were two, is the one the preferences render the preview with.
        from . import native
        self.engine=QtWidgets.QComboBox()
        self.engine.addItem('MoonRay (XPU)','xpu');self.engine.addItem('MoonRay (XPU2)','xpu2');self.engine.addItem('MoonLightIPR','moonlightipr')
        held=values.get('engine') or 'moonray'
        if held=='moonray':held='xpu2' if native.xpu2() else 'xpu'
        if not native.xpu2_available():
            # No XPU2 in the kit: its entry is there, greyed.
            self.engine.model().item(1).setEnabled(False)
            if held=='xpu2':held='xpu'
        self.engine.setCurrentIndex(max(0,self.engine.findData(held)))
        self.engine.setToolTip("MoonRay (XPU) renders each frame with MoonRay itself, in Render Settings' Execution Mode (Auto: the graphics card "
                               'first, then the processor), with every output, checkpoints among them. '
                               "MoonRay (XPU2) renders each frame with XPU2, the graphics card and the processor together as Preferences > MoonRay > XPU2 "
                               "says, whatever renders the preview; what XPU2 does not write (checkpoints, a scene's deep image with volumes) goes to MoonRay. "
                               "MoonLightIPR renders each frame on the graphics card to its Render Samples a pixel (Render Settings, MoonLightIPR), "
                               'written as an EXR of its own picture, the beauty, with its denoised beauty beside it (frame.denoised.0001.exr) where the Denoiser is on, as MoonRay writes it; no other outputs.')
        self.engine.currentIndexChanged.connect(self.update_summary)
        form.addRow('Engine',self.engine)
        row=QtWidgets.QHBoxLayout()
        self.folder=QtWidgets.QLineEdit(str(values.get('folder') or settings.value('output/animation','')))
        browse=QtWidgets.QPushButton('Browse…');browse.clicked.connect(self.browse)
        row.addWidget(self.folder,1);row.addWidget(browse);form.addRow('Output folder',row)
        self.prefix=QtWidgets.QLineEdit(str(values.get('prefix','frame')));form.addRow('File prefix',self.prefix)
        self.digits=QtWidgets.QSpinBox();self.digits.setRange(1,12);self.digits.setValue(int(values.get('digits',DIGITS)))
        self.digits.setToolTip('How many digits the frame numbers have, filled out with zeros: 4 names frame 1 frame.0001.exr.')
        form.addRow('Frame digits',self.digits)
        self.first=QtWidgets.QSpinBox();self.first.setRange(-100000,100000);self.first.setValue(int(values.get('first',1)))
        self.last=QtWidgets.QSpinBox();self.last.setRange(-100000,100000);self.last.setValue(int(values.get('last',1)))
        self.step=QtWidgets.QSpinBox();self.step.setRange(1,100000);self.step.setValue(int(values.get('step',1)))
        self.fps=QtWidgets.QDoubleSpinBox();self.fps.setRange(.001,1000);self.fps.setDecimals(3);self.fps.setValue(float(values.get('fps',24)))
        form.addRow('First frame',self.first);form.addRow('Last frame',self.last)
        form.addRow('Frame step',self.step);form.addRow('Frames per second',self.fps)
        # Each frame is an EXR, MoonRay's own file; it may be saved in another picture type beside it as well.
        from .image_formats import FORMATS
        self.type=QtWidgets.QComboBox();self.type.addItem('OpenEXR only',None)
        for key,label,extension,numbers,shown in FORMATS:
            if extension!='exr':self.type.addItem(label+' only',ONLY+key)
        for key,label,extension,numbers,shown in FORMATS:
            if extension!='exr':self.type.addItem('OpenEXR, and '+label,key)
        self.type.setCurrentIndex(max(0,self.type.findData(settings.value('output/animation_type',None))))
        self.type.setToolTip('OpenEXR keeps every output. Another type holds the picture as the preview shows it, denoised where the render is, with its alpha where Alpha is on in Render Settings (JPEG has none). A type on its own leaves no EXR: the other outputs are not kept.')
        self.type.currentIndexChanged.connect(self.update_summary)
        form.addRow('Frames as',self.type)
        self.settings=settings
        self.motion=QtWidgets.QCheckBox('Include motion blur');self.motion.setChecked(bool(values.get('motion',False)));form.addRow(self.motion)
        self.missing=QtWidgets.QCheckBox('Render missing frames / resume sequence');form.addRow(self.missing)
        self.missing.setToolTip('Keep recognizable EXR frames and render gaps. Use the same scene and render settings as the original sequence.')
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);form.addRow(self.summary)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Render sequence')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);form.addRow(buttons)
        for control in (self.first,self.last,self.step,self.digits):control.valueChanged.connect(self.update_summary)
        self.prefix.textChanged.connect(self.update_summary);self.update_summary()

    def browse(self):
        folder=QtWidgets.QFileDialog.getExistingDirectory(self,'Animation output folder',self.folder.text())
        if folder:self.folder.setText(folder)

    def update_summary(self,*args):
        count=max(0,(self.last.value()-self.first.value())//self.step.value()+1)
        also='';extension='exr'
        if getattr(self,'type',None) is not None and self.type.currentData():
            from .image_formats import find
            held=self.type.currentData()
            if held.startswith(ONLY):extension=find(held[len(ONLY):])[2]
            else:also=' and .%s'%find(held)[2]
        by=' · '+(self.engine.currentText() if getattr(self,'engine',None) is not None else 'MoonRay')
        self.summary.setText('%d frames · %s%s%s\nExisting frames are never overwritten. Enable Render missing frames to keep the frames already there and render the others.'%(count,frame_name(self.prefix.text(),self.first.value(),self.digits.value(),extension),also,by))

    def kept(self):
        """What the window has now, as it is kept with the scene for the next time it opens."""
        return {'engine':self.engine.currentData(),'folder':self.folder.text().strip(),'prefix':self.prefix.text(),'digits':self.digits.value(),'first':self.first.value(),
                'last':self.last.value(),'step':self.step.value(),'fps':self.fps.value(),'motion':self.motion.isChecked()}

    def export_as(self):
        """The other type each frame is saved in, {'type', 'quality', 'only'}, or None for OpenEXR only. only: in that type
        alone, with no EXR left beside it."""
        key=self.type.currentData()
        self.settings.setValue('output/animation_type',key or '')
        if not key:return None
        only=key.startswith(ONLY)
        return {'type':key[len(ONLY):] if only else key,'quality':int(self.settings.value('output/jpeg_quality',92)),'only':only}

    def accept(self):
        import re
        if not self.folder.text().strip() or not Path(self.folder.text().strip()).is_absolute():
            QtWidgets.QMessageBox.warning(self,'Output folder','Choose an absolute output folder.');return
        if self.last.value()<self.first.value() or self.last.value()-self.first.value()>100000:
            QtWidgets.QMessageBox.warning(self,'Frame range','Last frame must follow first frame, with at most 100001 frame positions.');return
        if not re.fullmatch(r'[A-Za-z0-9_-]+',self.prefix.text()):
            QtWidgets.QMessageBox.warning(self,'File prefix','Use letters, digits, underscores or hyphens.');return
        super().accept()
