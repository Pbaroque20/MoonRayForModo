"""Input color rules and renderer texture budget."""
from PySide2 import QtWidgets
from .assets import values

class AssetsDialog(QtWidgets.QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent);self.setWindowTitle('MoonRay input color and assets');self.resize(850,520);v=values(settings)
        layout=QtWidgets.QVBoxLayout(self);form=QtWidgets.QFormLayout();layout.addLayout(form)
        note=QtWidgets.QLabel('Render working space: linear Rec.709. Modo RGB values and linear EXRs use this space. Name its matching space in your OCIO config below. Normal, bump and other data maps stay raw unless explicitly overridden.');note.setWordWrap(True);layout.addWidget(note)
        self.config=QtWidgets.QLineEdit(v['config']);form.addRow('Input OCIO config',self.config)
        button=QtWidgets.QPushButton('Choose OCIO config…');button.clicked.connect(self.browse_config);form.addRow(button)
        self.linear=QtWidgets.QLineEdit(v['linear_space']);form.addRow('Config name for linear Rec.709',self.linear)
        self.cache=QtWidgets.QSpinBox();self.cache.setRange(64,131072);self.cache.setSuffix(' MB');self.cache.setValue(v['texture_cache_mb']);form.addRow('Renderer texture cache',self.cache)
        label=QtWidgets.QLabel('Per-file color-space overrides (supports <UDIM>). Use raw for data, sRGB for display-referred color, or an OCIO color-space name.');label.setWordWrap(True);layout.addWidget(label)
        self.table=QtWidgets.QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Texture path','Input color space']);self.table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch);layout.addWidget(self.table)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        add=QtWidgets.QPushButton('Add texture rule…');add.clicked.connect(self.browse_texture);row.addWidget(add)
        remove=QtWidgets.QPushButton('Remove selected rule');remove.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()));row.addWidget(remove)
        for rule in v['rules']:self.add(rule['path'],rule['space'])
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def add(self,path,space):
        row=self.table.rowCount();self.table.insertRow(row)
        for col,value in enumerate((path,space)):self.table.setItem(row,col,QtWidgets.QTableWidgetItem(value))
    def browse_texture(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Texture','','Images (*.*)')
        if path:self.add(path,'sRGB')
    def browse_config(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Input color configuration','','OCIO (*.ocio)')
        if path:self.config.setText(path)
    def accept(self):
        try:self.entries=values({'config':self.config.text().strip(),'linear_space':self.linear.text().strip(),'texture_cache_mb':self.cache.value(),'rules':[{'path':self.table.item(r,0).text().strip(),'space':self.table.item(r,1).text().strip()} for r in range(self.table.rowCount())]})
        except ValueError as exc:QtWidgets.QMessageBox.warning(self,'Input color',str(exc));return
        super().accept()
