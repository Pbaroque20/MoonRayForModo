"""Explicit per-format asset actions, invoked through an undoable host command."""
from pathlib import Path

SCENES={'.obj','.fbx','.lxo','.abc','.usd','.usda','.usdc'}
IMAGES={'.exr','.hdr','.tx','.png','.jpg','.jpeg','.tif','.tiff'}
LUTS={'.cube','.3dl'}

def action(path):
    name=str(path).lower();suffix=Path(path).suffix.lower()
    if name.endswith('.moonmat.json'):return 'Assign material'
    if suffix in SCENES:return 'Import scene / model'
    if suffix in IMAGES:return 'Import image clip'
    if suffix in LUTS:return 'Use display LUT'
    return {'.mtlx':'Import MaterialX override','.vdb':'Add VDB volume','.rdla':'Import RDL scene','.rdlb':'Import RDL scene'}.get(suffix,'')

def command_path(path):
    if any(c in str(path) for c in '{}\r\n'):raise ValueError('Rename this asset to remove command delimiters before importing')
    return '{'+str(path)+'}'

def execute(path,material_name=None):
    import copy,lx,modo
    from . import properties
    path=Path(path).expanduser().resolve()
    if not path.is_file():raise ValueError('Missing asset: '+str(path))
    suffix=path.suffix.lower();scene=modo.Scene()
    if suffix in SCENES:
        try:lx.eval('scene.open '+command_path(path)+' import')
        except (RuntimeError,LookupError) as exc:raise ValueError('Modo could not import '+suffix+'; an installed Modo reader for this format is required. '+str(exc))
    elif suffix in IMAGES:
        lx.eval('clip.addStill '+command_path(path))
    elif suffix=='.mtlx':
        from . import materialx
        graph=materialx.read(path,material_name)
        selected=list(scene.selected)
        from . import properties
        if len(selected)!=1 or not (properties.is_material(selected[0]) or selected[0].type=='mask'):
            raise ValueError('Select one material or material mask before importing a MaterialX override')
        source=selected[0];parent=source if source.type=='mask' else source.parent
        index=len(parent.children()) if source.type=='mask' else source.parentIndex+1
        item=scene.addItem('material.moonrayMaterialX',name='MaterialX Override - '+path.stem)
        item.setParent(parent,index)
        properties.write(item,{'materialx_override':True,'materialx_graph':graph})
        scene.select(item)
    elif suffix=='.vdb':
        settings=properties.scene_settings()
        item=scene.addItem('locator',name='MoonRay Volume - '+path.stem)
        settings.setdefault('production',{}).setdefault('objects',{})[item.id]={'geometry_file':str(path),'density_grid':'density','density':1,'emission':1}
        properties.write(scene.renderItem,settings);scene.select(item);sync_panels(settings)
    elif suffix in LUTS:
        from . import display
        settings=properties.scene_settings();values=display.values(settings.get('display',{}));values['lut']=str(path)
        settings['display']=values;properties.write(scene.renderItem,settings);sync_panels(settings)
    else:raise ValueError('No direct importer for '+suffix)

def sync_panels(settings):
    """Keep open panels from writing stale copies over newly imported settings."""
    import copy
    from PySide2 import QtWidgets
    from .panel import Panel
    app=QtWidgets.QApplication.instance()
    if not app:return
    for widget in app.allWidgets():
        if not isinstance(widget,Panel):continue
        widget.production=copy.deepcopy(settings.get('production',{}))
        control=widget.display_controls.get('lut')
        if control is not None:
            control.setText(settings.get('display',{}).get('lut',''))
            widget._buffer_changed(0)
        widget.changes.invalidate()
