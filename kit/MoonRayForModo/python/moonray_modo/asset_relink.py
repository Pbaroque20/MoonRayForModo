"""Reviewable relinking of missing images: Modo's image clips, and the images MoonRay node graphs name (an image node's
file, an ImageMap's texture). A graph's image is offered the file rendering already finds for it (textures.relink_graph:
beside the scene by its last folders, or by its name in a folder the scene's own images are in); a clip's replacement
is chosen by hand, as before."""
import copy
from pathlib import Path
from PySide2 import QtWidgets
import modo
from .host import channel
from .textures import source_tiles,resolve_scene_source

GRAPH_KEYS=('node_graph','materialx_graph')


def missing_clips(scene):
    """[(clip, its missing path)]: clips whose image is nowhere rendering looks."""
    clips=[]
    for clip in scene.items('videoStill',superType=False):
        source=channel(clip,'filename','')
        if not source:continue
        try:resolved,_=resolve_scene_source(source,getattr(scene,'filename',None))
        except ValueError:resolved=source
        if not source_tiles(resolved):clips.append((clip,source))
    return clips


def missing_graph_images(scene):
    """[(material, graph key, node, parameter, missing path, path offered or '', how or why)] for each image a material's
    graph names that is not where it says."""
    from . import properties, textures
    from .host import _image_folders
    found=[];folders=None
    for material in scene.items('advancedMaterial',superType=True):
        try:values=properties.read(material)
        except Exception:continue
        for key in GRAPH_KEYS:
            graph=values.get(key)
            if not isinstance(graph,dict):continue
            if folders is None:folders=_image_folders(scene)
            for node,parameter,old,new,how in textures.missing_graph_images(graph,getattr(scene,'filename',None),folders):
                found.append((material,key,node,parameter,old,new or '',how))
    return found


def apply_graph_images(replacements):
    """Each (material, graph key, node, parameter, new path) written into its material's graph, one write a material."""
    from . import properties
    by_material={}
    for material,key,node,parameter,path in replacements:by_material.setdefault(material.id,(material,[]))[1].append((key,node,parameter,path))
    for material,changes in by_material.values():
        values=copy.deepcopy(properties.read(material))
        for key,node,parameter,path in changes:
            values[key]['nodes'][node].setdefault('parameters',{})[parameter]=str(path).replace('\\','/')
        properties.write(material,values)


def show():
    scene=modo.Scene()
    clips=missing_clips(scene)
    graphs=missing_graph_images(scene)
    if not clips and not graphs:QtWidgets.QMessageBox.information(None,'Relink images','No missing images were found.');return
    dialog=QtWidgets.QDialog();dialog.setWindowTitle('Relink missing images');dialog.resize(950,460);layout=QtWidgets.QVBoxLayout(dialog)
    rows=[('clip',clip,path,'') for clip,path in clips]
    rows+=[('graph',(material,key,node,parameter),old,new) for material,key,node,parameter,old,new,how in graphs]
    table=QtWidgets.QTableWidget(len(rows),3);table.setHorizontalHeaderLabels(['Image','Missing path','Replacement'])
    table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);layout.addWidget(table)
    for row,(kind,owner,path,offered) in enumerate(rows):
        if kind=='clip':where=owner.name
        else:
            material,key,node,parameter=owner
            node_type=str(((properties_read(material).get(key) or {}).get('nodes') or {}).get(node,{}).get('type',''))
            where='%s: %s %s'%(material.name,node_type or 'node',parameter)
        for col,text in enumerate((where,path,offered)):table.setItem(row,col,QtWidgets.QTableWidgetItem(text))
        if kind=='graph':
            how=graphs[row-len(clips)][6]
            tip='Found by its name in a folder the scene\'s own images are in.' if how=='same name' else 'Found beside the scene.' if how=='relocated' else 'Not found: '+str(how)
            for col in range(3):table.item(row,col).setToolTip(tip)
    def choose():
        row=table.currentRow()
        if row<0:return
        path,_=QtWidgets.QFileDialog.getOpenFileName(dialog,'Replacement texture','','Images (*.*)')
        if path:table.item(row,2).setText(path)
    button=QtWidgets.QPushButton('Choose replacement for selected image…');button.clicked.connect(choose);layout.addWidget(button)
    note=QtWidgets.QLabel('Only rows with a replacement are changed. A MoonRay graph\'s image is offered the file rendering already finds for it; '
                          'check it before applying. Use <UDIM> in a replacement path to relink a tile set. This operation can be undone in Modo.');note.setWordWrap(True);layout.addWidget(note)
    buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Cancel);layout.addWidget(buttons);buttons.rejected.connect(dialog.reject)
    def apply():
        chosen=[(rows[row],table.item(row,2).text().strip()) for row in range(len(rows)) if table.item(row,2).text().strip()]
        missing=[path for _,path in chosen if not source_tiles(path)]
        if missing:QtWidgets.QMessageBox.warning(dialog,'Missing replacement','\n'.join(missing));return
        clip_changes=[(owner,path) for (kind,owner,_,_),path in chosen if kind=='clip']
        graph_changes=[owner+(path,) for (kind,owner,_,_),path in chosen if kind=='graph']
        old=[(clip,channel(clip,'filename','')) for clip,path in clip_changes]
        try:
            for clip,path in clip_changes:clip.channel('filename').set(path)
        except Exception:
            for clip,path in old:clip.channel('filename').set(path)
            raise
        apply_graph_images(graph_changes)
        dialog.accept()
    buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(apply);dialog.exec_()


def properties_read(material):
    from . import properties
    try:return properties.read(material)
    except Exception:return {}
