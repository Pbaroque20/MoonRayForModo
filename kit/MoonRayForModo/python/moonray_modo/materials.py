"""Undoable material assignment, called only by Modo commands."""
import uuid
import modo
from . import properties

def selected():
    return [i for i in modo.Scene().selected if properties.is_material(i)]

def above_base(scene,mask):
    """Where a new mask goes under the render item: over the Base Material and every other
    layer, just beneath the shaders. A layer lower down is covered by the Base Material."""
    # Modo has already put the new mask among the layers; it is not counted.
    layers=[layer for layer in scene.renderItem.children() if layer.id!=mask.id]
    for index,layer in enumerate(layers):
        if layer.type=='defaultShader':return index
    return len(layers)

def assign(shader=None, kind='advancedMaterial'):
    scene=modo.Scene()
    # Without a named shader it is a DwaBaseMaterial, edited through that material's own form.
    shader=shader or 'DwaBaseMaterial'
    meshes=properties.selected_meshes()
    if not meshes:
        raise ValueError('Select one or more meshes first.')
    # Validate all meshes before changing anything.
    for mesh in meshes:
        if not len(mesh.geometry.polygons):
            raise ValueError('Mesh has no polygons: '+mesh.name)
    tag='MoonShine_'+uuid.uuid4().hex[:12]
    mask=scene.addItem('mask',name='MoonShine - '+meshes[0].name)
    mask.setParent(scene.renderItem,above_base(scene,mask))
    mask.channel('ptyp').set('Material'); mask.channel('ptag').set(tag)
    material=scene.addItem(kind,name='MoonShine Material')
    material.setParent(mask,0)
    properties.write(material,{'shader':'DwaBaseMaterial','thin_geometry':False,'moonshine_override':True,'native_shader':shader,'native_parameters':{}})
    material.channel('diffAmt').set(1)
    material.channel('rough').set(.35)
    for mesh in meshes:
        with mesh.geometry as geometry:
            # By index: stepping through the polygons while tagging them passed one over.
            for index in range(len(geometry.polygons)):
                geometry.polygons[index].materialTag=tag
        missed=[index for index in range(len(mesh.geometry.polygons)) if mesh.geometry.polygons[index].materialTag!=tag]
        if missed:
            with mesh.geometry as geometry:
                for index in missed:geometry.polygons[index].materialTag=tag
    # Named for what it is; the mask above it already says MoonShine.
    material.name=shader
    scene.select(material)
    return material


def import_materialx(path):
    """Put the material of a MaterialX file on the selected meshes, as a MoonRay material with the file's graph."""
    from pathlib import Path
    from . import materialx
    from .material_override import synchronize
    # Read first: a file that cannot be followed leaves the scene as it was.
    graph=materialx.read(path)
    material=assign(graph['nodes'][graph['root']]['type'],properties.MATERIALX_TYPE)
    load_materialx(material,path,graph)
    # The group it sits in says what it is, as the material's own type does.
    try:material.parent.name='MaterialX - '+material.name
    except (AttributeError,LookupError,RuntimeError):pass
    return material


def load_materialx(material,path,graph=None):
    """Give a MaterialX material the material of a file: its graph, its controls and its name."""
    from pathlib import Path
    from . import materialx
    from .material_override import synchronize
    graph=graph or materialx.read(path)
    settings=properties.read(material)
    settings.update(shader='DwaBaseMaterial',moonshine_override=True,native_shader=graph['nodes'][graph['root']]['type'],node_graph=graph)
    properties.write(material,synchronize(settings,graph))
    material.name=Path(path).stem
    return material


def active(item):
    if item.type=='material.moonrayMoonShine':
        from .material_override import enabled
        return enabled(properties.read(item))
    return item.type!='material.moonrayMaterialX' or bool(properties.read(item).get('materialx_override'))
