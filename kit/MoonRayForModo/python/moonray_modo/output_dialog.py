"""Output controls for frame sequence rendering."""
from pathlib import Path
from PySide2 import QtWidgets


class AnimationDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Render animation');self.resize(520,300)
        form=QtWidgets.QFormLayout(self)
        row=QtWidgets.QHBoxLayout()
        self.folder=QtWidgets.QLineEdit(str(settings.value('output/animation','')))
        browse=QtWidgets.QPushButton('Browse…');browse.clicked.connect(self.browse)
        row.addWidget(self.folder,1);row.addWidget(browse);form.addRow('Output folder',row)
        self.prefix=QtWidgets.QLineEdit('frame');form.addRow('File prefix',self.prefix)
        self.first=QtWidgets.QSpinBox();self.first.setRange(-100000,100000);self.first.setValue(1)
        self.last=QtWidgets.QSpinBox();self.last.setRange(-100000,100000);self.last.setValue(1)
        self.step=QtWidgets.QSpinBox();self.step.setRange(1,100000);self.step.setValue(1)
        self.fps=QtWidgets.QDoubleSpinBox();self.fps.setRange(.001,1000);self.fps.setDecimals(3);self.fps.setValue(24)
        form.addRow('First frame',self.first);form.addRow('Last frame',self.last)
        form.addRow('Frame step',self.step);form.addRow('Frames per second',self.fps)
        self.motion=QtWidgets.QCheckBox('Include motion blur');form.addRow(self.motion)
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);form.addRow(self.summary)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Render sequence')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);form.addRow(buttons)
        for control in (self.first,self.last,self.step):control.valueChanged.connect(self.update_summary)
        self.prefix.textChanged.connect(self.update_summary);self.update_summary()

    def browse(self):
        folder=QtWidgets.QFileDialog.getExistingDirectory(self,'Animation output folder',self.folder.text())
        if folder:self.folder.setText(folder)

    def update_summary(self,*args):
        count=max(0,(self.last.value()-self.first.value())//self.step.value()+1)
        self.summary.setText('%d frames · %s.%06d.exr\nExisting frames are never overwritten. Use a folder without a sequence manifest.'%(count,self.prefix.text(),self.first.value()))

    def accept(self):
        import re
        if not self.folder.text().strip() or not Path(self.folder.text().strip()).is_absolute():
            QtWidgets.QMessageBox.warning(self,'Output folder','Choose an absolute output folder.');return
        if self.last.value()<self.first.value() or self.last.value()-self.first.value()>100000:
            QtWidgets.QMessageBox.warning(self,'Frame range','Last frame must follow first frame, with at most 100001 frame positions.');return
        if not re.fullmatch(r'[A-Za-z0-9_-]+',self.prefix.text()):
            QtWidgets.QMessageBox.warning(self,'File prefix','Use letters, digits, underscores or hyphens.');return
        super().accept()
