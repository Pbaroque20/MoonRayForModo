"""Reviewable relinking of missing Modo image clips."""
from pathlib import Path
from PySide2 import QtWidgets
import modo
from .host import channel
from .textures import source_tiles,resolve_scene_source

def show():
    scene=modo.Scene();clips=[]
    for clip in scene.items('videoStill',superType=False):
        source=channel(clip,'filename','')
        if not source:continue
        try:resolved,_=resolve_scene_source(source,getattr(scene,'filename',None))
        except ValueError:resolved=source
        if not source_tiles(resolved):clips.append((clip,source))
    if not clips:QtWidgets.QMessageBox.information(None,'Relink images','No missing image clips were found.');return
    dialog=QtWidgets.QDialog();dialog.setWindowTitle('Relink missing image clips');dialog.resize(850,440);layout=QtWidgets.QVBoxLayout(dialog)
    table=QtWidgets.QTableWidget(len(clips),3);table.setHorizontalHeaderLabels(['Clip','Missing path','Replacement']);table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);layout.addWidget(table)
    for row,(clip,path) in enumerate(clips):
        for col,text in enumerate((clip.name,path,'')):table.setItem(row,col,QtWidgets.QTableWidgetItem(text))
    def choose():
        row=table.currentRow()
        if row<0:return
        path,_=QtWidgets.QFileDialog.getOpenFileName(dialog,'Replacement texture','','Images (*.*)')
        if path:table.item(row,2).setText(path)
    button=QtWidgets.QPushButton('Choose replacement for selected clip…');button.clicked.connect(choose);layout.addWidget(button)
    note=QtWidgets.QLabel('Only rows with a replacement are changed. Use <UDIM> in a replacement path to relink a tile set. This operation can be undone in Modo.');note.setWordWrap(True);layout.addWidget(note)
    buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Cancel);layout.addWidget(buttons);buttons.rejected.connect(dialog.reject)
    def apply():
        replacements=[(clip,table.item(row,2).text().strip()) for row,(clip,old) in enumerate(clips) if table.item(row,2).text().strip()]
        missing=[path for clip,path in replacements if not source_tiles(path)]
        if missing:QtWidgets.QMessageBox.warning(dialog,'Missing replacement','\n'.join(missing));return
        old=[(clip,channel(clip,'filename','')) for clip,path in replacements]
        try:
            for clip,path in replacements:clip.channel('filename').set(path)
        except Exception:
            for clip,path in old:clip.channel('filename').set(path)
            raise
        dialog.accept()
    buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(apply);dialog.exec_()
