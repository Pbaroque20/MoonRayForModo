"""Undoable material assignment, called only by Modo commands."""
import uuid
import modo
from . import properties

def selected():
    return [i for i in modo.Scene().selected if i.type=='advancedMaterial']

def assign():
    scene=modo.Scene()
    meshes=properties.selected_meshes()
    if not meshes:
        raise ValueError('Select one or more meshes first.')
    # Validate all meshes before changing anything.
    for mesh in meshes:
        if not len(mesh.geometry.polygons):
            raise ValueError('Mesh has no polygons: '+mesh.name)
    tag='MoonShine_'+uuid.uuid4().hex[:12]
    mask=scene.addItem('mask',name='MoonShine - '+meshes[0].name)
    mask.setParent(scene.renderItem,0)
    mask.channel('ptyp').set('Material'); mask.channel('ptag').set(tag)
    material=scene.addItem('advancedMaterial',name='MoonShine Material')
    material.setParent(mask,0)
    properties.write(material,{'shader':'DwaBaseMaterial','thin_geometry':False})
    material.channel('diffAmt').set(1)
    material.channel('rough').set(.35)
    for mesh in meshes:
        with mesh.geometry as geometry:
            for polygon in geometry.polygons:
                polygon.materialTag=tag
    scene.select(material)
    return material
