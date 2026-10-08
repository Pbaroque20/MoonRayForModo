"""Undoable material assignment, called only by Modo commands."""
import uuid
import modo
from . import properties

def selected():
    return [i for i in modo.Scene().selected if i.type in ('advancedMaterial','material.moonrayMoonShine','material.moonrayMaterialX')]

def above_base(scene):
    """Where a new mask goes under the render item: over the Base Material and every other
    layer, just beneath the shaders. A layer lower down is covered by the Base Material."""
    layers=scene.renderItem.children()
    for index,layer in enumerate(layers):
        if layer.type=='defaultShader':return index
    return len(layers)

def assign(shader=None):
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
    mask.setParent(scene.renderItem,above_base(scene))
    mask.channel('ptyp').set('Material'); mask.channel('ptag').set(tag)
    material=scene.addItem('advancedMaterial',name='MoonShine Material')
    material.setParent(mask,0)
    properties.write(material,{'shader':'DwaBaseMaterial','thin_geometry':False,'moonshine_override':True,'native_shader':shader,'native_parameters':{}})
    material.channel('diffAmt').set(1)
    material.channel('rough').set(.35)
    for mesh in meshes:
        with mesh.geometry as geometry:
            for polygon in geometry.polygons:
                polygon.materialTag=tag
    # Named for what it is; the mask above it already says MoonShine.
    material.name=shader
    scene.select(material)
    return material


def active(item):
    if item.type=='material.moonrayMoonShine':
        from .material_override import enabled
        return enabled(properties.read(item))
    return item.type!='material.moonrayMaterialX' or bool(properties.read(item).get('materialx_override'))
