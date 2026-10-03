"""Input color rules and renderer texture budget."""
from PySide2 import QtWidgets
from .assets import values

class AssetsDialog(QtWidgets.QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent);self.setWindowTitle('MoonRay input color and assets');self.resize(850,520);v=values(settings)
        layout=QtWidgets.QVBoxLayout(self);form=QtWidgets.QFormLayout();layout.addLayout(form)
        note=QtWidgets.QLabel('Modo colors and texture graphs are interpreted in linear Rec.709, then color outputs convert to the selected render primaries. EXRs retain the render working space. Normal, bump, UV and mask values remain data.');note.setWordWrap(True);layout.addWidget(note)
        self.working=QtWidgets.QComboBox();self.working.addItem('Linear Rec.709','rec709');self.working.addItem('ACEScg (AP1, D60)','acescg');self.working.setCurrentIndex(max(0,self.working.findData(v['working_space'])));form.addRow('Render working space',self.working)
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
        maintain=QtWidgets.QPushButton('Manage on-disk texture cache…');maintain.clicked.connect(self.maintain);layout.addWidget(maintain)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def maintain(self):
        from .texture_cache import summary,trim
        count,size=summary()
        limit,ok=QtWidgets.QInputDialog.getInt(self,'Texture cache','Keep completed cache under MB (currently %d files, %.1f MB). Only files older than seven days are eligible.'%(count,size/1048576),10240,0,1048576)
        if ok:
            removed,remaining=trim(limit)
            QtWidgets.QMessageBox.information(self,'Texture cache','Removed %d old cache files; %.1f MB remain. Source textures are preserved.'%(removed,remaining/1048576))
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
        try:self.entries=values({'working_space':self.working.currentData(),'config':self.config.text().strip(),'linear_space':self.linear.text().strip(),'texture_cache_mb':self.cache.value(),'rules':[{'path':self.table.item(r,0).text().strip(),'space':self.table.item(r,1).text().strip()} for r in range(self.table.rowCount())]})
        except ValueError as exc:QtWidgets.QMessageBox.warning(self,'Input color',str(exc));return
        super().accept()
