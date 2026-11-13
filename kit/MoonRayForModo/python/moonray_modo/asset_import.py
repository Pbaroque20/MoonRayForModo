"""Explicit per-format asset actions, invoked through an undoable host command."""
from pathlib import Path

SCENES={'.obj','.fbx','.abc','.usd','.usda','.usdc'}
IMAGES={'.exr','.hdr','.tx','.png','.jpg','.jpeg','.tif','.tiff'}
LUTS={'.cube','.3dl'}

def action(path):
    name=str(path).lower();suffix=Path(path).suffix.lower()
    if name.endswith('.moonmat.json'):return 'Assign material'
    # A Modo scene opens as a scene of its own: brought into the open one, its sun and sky lit it beside the open
    # scene's own (the ocean demo twice as bright) and its camera and render settings were left behind.
    if suffix=='.lxo':return 'Open Modo scene'
    if suffix in SCENES:return 'Import scene / model'
    if suffix in IMAGES:return 'Import image clip'
    if suffix in LUTS:return 'Use display LUT'
    return {'.mtlx':'Import MaterialX override','.vdb':'Add VDB volume','.rdla':'Import RDL scene','.rdlb':'Import RDL scene'}.get(suffix,'')

def command_path(path):
    if any(c in str(path) for c in '{}\r\n'):raise ValueError('Rename this asset to remove command delimiters before importing')
    return '{'+str(path)+'}'

def working_copy(path):
    """Where a library scene is opened from: a scene that came with the kit is copied to Documents/MoonRay for Modo/Scenes
    first (a new name each time), so saving it never writes over the kit's file, which the next install would put back;
    a scene from a folder of the user's own is opened where it is."""
    import shutil
    from .asset_library import bundled
    path=Path(path).resolve()
    try:path.relative_to(bundled().resolve())
    except ValueError:return path
    folder=Path.home()/'Documents'/'MoonRay for Modo'/'Scenes';folder.mkdir(parents=True,exist_ok=True)
    target=folder/path.name;count=1
    while target.exists():
        count+=1;target=folder/('%s %d%s'%(path.stem,count,path.suffix))
    shutil.copy2(path,target)
    return target

def execute(path,material_name=None):
    import copy,lx,modo
    from . import properties
    path=Path(path).expanduser().resolve()
    if not path.is_file():raise ValueError('Missing asset: '+str(path))
    suffix=path.suffix.lower();scene=modo.Scene()
    if suffix=='.lxo':
        opened=working_copy(path)
        try:lx.eval('scene.open '+command_path(opened)+' normal')
        except (RuntimeError,LookupError) as exc:raise ValueError('Modo could not open '+path.name+': '+str(exc))
        return
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
    from .panel import live_panels
    for widget in live_panels():
        widget.production=copy.deepcopy(settings.get('production',{}))
        control=widget.display_controls.get('lut')
        if control is not None:
            control.setText(settings.get('display',{}).get('lut',''))
            widget._buffer_changed(0)
        widget.changes.invalidate()
