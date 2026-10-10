"""Named output editor with explicit precision and filtering controls."""
from PySide2 import QtGui, QtWidgets
from . import outputs

class OutputsDialog(QtWidgets.QDialog):
    def __init__(self,entries,parent=None):
        super().__init__(parent);self.setWindowTitle('Light path expressions and named outputs');self.resize(940,460)
        layout=QtWidgets.QVBoxLayout(self)
        note=QtWidgets.QLabel('Add named channels to the final EXR. LPE uses MoonRay expressions; Material AOV uses its native expression. Cryptomatte supports object, material and asset categories with a matching runtime. Each category uses a separate EXR part, a manifest and 32-bit channels. Volume coverage is not available. Motion vectors require motion samples.');note.setWordWrap(True);layout.addWidget(note)
        top=QtWidgets.QHBoxLayout();layout.addLayout(top)
        # The light paths most often wanted, each added as an output ready to render.
        preset=QtWidgets.QPushButton('Add light path preset');presets=QtWidgets.QMenu(preset)
        for label,name,expression in outputs.PRESETS:
            action=QtWidgets.QAction(label,presets);action.setToolTip(expression)
            action.triggered.connect(lambda checked=False,n=name,e=expression:self.add({'name':self.free(n),'kind':'lpe','expression':e}))
            presets.addAction(action)
        presets.setToolTipsVisible(True);preset.setMenu(presets);top.addWidget(preset)
        group=QtWidgets.QPushButton('Add light-group output...');group.clicked.connect(self.light_group);top.addWidget(group);top.addStretch(1)
        self.table=QtWidgets.QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Name','Type','Expression','Precision','Filter','EXR part','Crypto depth','Crypto category']);layout.addWidget(self.table)
        row=QtWidgets.QHBoxLayout();layout.addLayout(row)
        add=QtWidgets.QPushButton('Add output');add.clicked.connect(lambda:self.add({'name':'pass_'+str(self.table.rowCount()+1),'kind':'lpe','expression':'diffuse'}));row.addWidget(add)
        remove=QtWidgets.QPushButton('Remove selected');remove.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()));row.addWidget(remove)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.problem=QtWidgets.QLabel('');self.problem.setWordWrap(True);self.problem.setStyleSheet('color: #e0a030;');layout.insertWidget(layout.count()-1,self.problem)
        for entry in entries:self.add(entry)
        self.table.itemChanged.connect(lambda item:self.check())
        self.check()
    def free(self,name):
        """The name, or the name with a number after it where an output already has it."""
        taken={self.table.item(row,0).text() for row in range(self.table.rowCount()) if self.table.item(row,0)}
        number,made=1,name
        while made in taken:number+=1;made='%s_%d'%(name,number)
        return made
    def check(self):
        """Mark each light path expression that is not written as one, and say what is wrong with the first."""
        if not hasattr(self,'problem'):return
        first=''
        for row in range(self.table.rowCount()):
            cell,kind=self.table.item(row,2),self.table.cellWidget(row,1)
            if cell is None or kind is None:continue
            wrong=outputs.lpe_problem(cell.text()) if kind.currentData()=='lpe' else None
            blocked=self.table.blockSignals(True)
            cell.setForeground(QtGui.QBrush(QtGui.QColor('#b02010' if wrong else '#000000')));cell.setToolTip(wrong or '')
            self.table.blockSignals(blocked)
            if wrong and not first:first='%s: %s'%(self.table.item(row,0).text() if self.table.item(row,0) else 'Row %d'%(row+1),wrong)
        self.problem.setText(first)
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
        self.table.cellWidget(row,1).currentIndexChanged.connect(lambda index:self.check())
        self.check()
    def accept(self):
        try:
            entries=[]
            for row in range(self.table.rowCount()):
                v={key:self.table.item(row,col).text().strip() for col,key in ((0,'name'),(2,'expression'),(5,'part'))}
                v.update({key:self.table.cellWidget(row,col).currentData() for col,key in ((1,'kind'),(3,'precision'),(4,'filter'))});v['depth']=self.table.cellWidget(row,6).value();v['category']=self.table.cellWidget(row,7).currentData();entries.append(v)
            self.entries=outputs.values(entries)
        except ValueError as exc:QtWidgets.QMessageBox.warning(self,'Render outputs',str(exc));return
        super().accept()
