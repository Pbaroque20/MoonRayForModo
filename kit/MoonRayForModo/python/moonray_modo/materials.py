"""Undoable material assignment, called only by Modo commands."""
import uuid
import lx
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

def chosen_polygons(meshes):
    """The polygons the user has picked out on each mesh, by mesh: {mesh id: [polygon IDs]}. They are held by Modo's
    own ID for each, not by where it comes in the mesh: tagging a polygon can move it among the others.

    Empty unless Modo is in polygon selection mode and something is selected there. A selection left behind from
    earlier, while the user works with items or with vertices, is not one they are looking at and does not count."""
    try:
        if not lx.eval('select.typeFrom polygon;edge;vertex;item;pivot;center;ptag ?'):
            return {}
    except RuntimeError:
        return {}
    picked = {}
    for mesh in meshes:
        try:
            indices = [polygon.id for polygon in mesh.geometry.polygons.selected]
        except (AttributeError, LookupError, RuntimeError):
            indices = []
        if indices:
            picked[mesh.id] = indices
    return picked


def target():
    """In words, what an assignment made now would go on."""
    meshes=properties.selected_meshes()
    picked=chosen_polygons(meshes)
    if picked:
        count=sum(len(v) for v in picked.values());names=[mesh.name for mesh in meshes if mesh.id in picked]
        return 'the %d selected polygon%s of %s'%(count,'' if count==1 else 's',', '.join(names[:3])+(' and others' if len(names)>3 else ''))
    names=[mesh.name for mesh in meshes]
    return 'every polygon of '+', '.join(names[:3])+(' and others' if len(names)>3 else '') if names else ''


def names_in_use():
    """The names and material tags the Shader Tree already holds, which a new material should not repeat."""
    held=set()
    for item in modo.Scene().items('mask'):
        held.add(item.name)
        try:held.add(item.channel('ptag').get() or '')
        except (LookupError,RuntimeError,AttributeError):pass
    return held


def assign(shader=None, kind='advancedMaterial', name=None, color=None, smoothing=None, angle=40.0):
    """Give the selected meshes a MoonRay material of their own. With polygons selected, in polygon mode, only those
    polygons take it and the rest of each mesh keeps what it had; otherwise every polygon of each selected mesh does.

    name is what the material and its polygon tag are called, as with Modo's own Polygon Set Material. color goes to
    the material's main colour. smoothing, where it is given, has this material say how its polygons are smoothed:
    False for flat, True for smooth within angle degrees."""
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
    picked=chosen_polygons(meshes)
    if picked:
        # Only the meshes that have polygons picked out are touched.
        meshes=[mesh for mesh in meshes if mesh.id in picked]
    tag='MoonShine_'+uuid.uuid4().hex[:12]
    if name:
        # Called by its name, as Modo's own materials are, where no other material has taken it.
        held=names_in_use();tag,count=name,1
        while tag in held:
            count+=1;tag='%s %d'%(name,count)
    mask=scene.addItem('mask',name=tag if name else 'MoonShine - '+meshes[0].name+(' (%d polygons)'%sum(len(v) for v in picked.values()) if picked else ''))
    mask.setParent(scene.renderItem,above_base(scene,mask))
    mask.channel('ptyp').set('Material'); mask.channel('ptag').set(tag)
    material=scene.addItem(kind,name='MoonShine Material')
    material.setParent(mask,0)
    held={'shader':'DwaBaseMaterial','thin_geometry':False,'moonshine_override':True,'native_shader':shader,'native_parameters':{}}
    if color is not None:
        from .material_editor import colour_attribute
        from . import shader_library
        key=colour_attribute(shader)
        if key:held['native_parameters']=shader_library.validate(shader,{key:[float(v) for v in color]})
    if smoothing is not None:
        held.update(smoothing=bool(smoothing),smoothing_angle=max(0.0,min(180.0,float(angle))))
    properties.write(material,held)
    if color is not None:
        # Modo's own viewport shows the material by this.
        try:material.channel('diffCol').set(tuple(float(v) for v in color))
        except (LookupError,RuntimeError,AttributeError,TypeError):pass
    material.channel('diffAmt').set(1)
    material.channel('rough').set(.35)
    for mesh in meshes:
        if mesh.id in picked:
            # Each picked polygon is found again by its ID and tagged through the mesh's own accessor.
            with mesh.geometry as geometry:
                accessor=lx.object.Polygon(geometry.internalMesh.PolygonAccessor())
                tagger=lx.object.StringTag(accessor)
                for identity in picked[mesh.id]:
                    accessor.Select(identity)
                    tagger.Set(lx.symbol.i_POLYTAG_MATERIAL,tag)
            continue
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
    if name:mask.name=tag
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
