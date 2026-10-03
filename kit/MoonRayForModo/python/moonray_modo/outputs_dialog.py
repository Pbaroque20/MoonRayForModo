"""Named output editor with explicit precision and filtering controls."""
from PySide2 import QtWidgets
from . import outputs

class OutputsDialog(QtWidgets.QDialog):
    def __init__(self,entries,parent=None):
        super().__init__(parent);self.setWindowTitle('MoonRay render outputs');self.resize(940,460)
        layout=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('Add named channels to the final EXR. LPE uses MoonRay expressions; Material AOV uses its native expression. Object Cryptomatte uses fixed Cryptomatte00… channel names, stable item IDs, an embedded manifest, and 32-bit channels. Motion vectors require motion samples.');note.setWordWrap(True);layout.addWidget(note)
        group=QtWidgets.QPushButton('Add light-group output…');group.clicked.connect(self.light_group);layout.addWidget(group)
        self.table=QtWidgets.QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Name','Type','Expression','Precision','Filter','EXR part','Crypto depth','Crypto category']);layout.addWidget(self.table)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        add=QtWidgets.QPushButton('Add output');add.clicked.connect(lambda:self.add({'name':'pass_'+str(self.table.rowCount()+1),'kind':'lpe','expression':'diffuse'}));row.addWidget(add)
        remove=QtWidgets.QPushButton('Remove selected');remove.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()));row.addWidget(remove)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        for entry in entries:self.add(entry)
    def light_group(self):
        label,ok=QtWidgets.QInputDialog.getText(self,'Light-group output','Light group label (set in Lighting scene controls)')
        if not ok:return
        import re
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',label):QtWidgets.QMessageBox.warning(self,'Light group','Use letters, numbers and underscores.');return
        self.add({'name':label+'_light','kind':'lpe','expression':"C.*<L.'"+label+"'>"})
    def add(self,v):
        row=self.table.rowCount();self.table.insertRow(row)
        for col,key in ((0,'name'),(2,'expression'),(5,'part')):self.table.setItem(row,col,QtWidgets.QTableWidgetItem(str(v.get(key,''))))
        for col,key,choices,default in ((1,'kind',[(label,key) for key,label in outputs.KINDS.items()],'lpe'),(3,'precision',[('32-bit float',0),('16-bit half',1)],0),(4,'filter',[(n,i) for i,n in enumerate(('Average','Sum','Minimum','Maximum','Consistent sampling','Closest'))],0)):
            widget=QtWidgets.QComboBox()
            for label,value in choices:widget.addItem(label,value)
            widget.setCurrentIndex(max(0,widget.findData(v.get(key,default))));self.table.setCellWidget(row,col,widget)
        category=QtWidgets.QComboBox()
        for key in ('object','material','asset'):category.addItem(key.title(),key)
        category.setCurrentIndex(max(0,category.findData(v.get('category','object'))));self.table.setCellWidget(row,7,category)
        depth=QtWidgets.QSpinBox();depth.setRange(1,16);depth.setValue(v.get('depth',6));self.table.setCellWidget(row,6,depth)
    def accept(self):
        try:
            entries=[]
            for row in range(self.table.rowCount()):
                v={key:self.table.item(row,col).text().strip() for col,key in ((0,'name'),(2,'expression'),(5,'part'))}
                v.update({key:self.table.cellWidget(row,col).currentData() for col,key in ((1,'kind'),(3,'precision'),(4,'filter'))});v['depth']=self.table.cellWidget(row,6).value();v['category']=self.table.cellWidget(row,7).currentData();entries.append(v)
            self.entries=outputs.values(entries)
        except ValueError as exc:QtWidgets.QMessageBox.warning(self,'Render outputs',str(exc));return
        super().accept()
