"""Rest positions for meshes (MoonRay's ref_P), for what reads a surface in reference space.

Glitter set to reference space places its flakes by each point's rest position, so that they stay on a surface as
it deforms rather than swim through it; without one MoonRay fails the material and draws it pink or black. A mesh's
rest position is where its point is before Modo's deformers move it: its base mesh, point for point. They are sent
only where a material asks for them, as a value at each point named ref_P, in the mesh's own space as its points are.
MoonRay works the reference normal out from them."""
# The materials with glitter, and its reference space (MoonRay's default; the plugin starts glitter in object space).
GLITTERING = ('DwaBaseMaterial', 'DwaFabricMaterial', 'DwaMetalMaterial', 'DwaSkinMaterial', 'DwaSolidDielectricMaterial',
              'DwaToonMaterial', 'DwaVelvetMaterial_v2')
REFERENCE_SPACE = 5
NAME = 'ref_P'


def in_reference_space(shader, parameters):
    """Whether a material of this shader, with these settings, shows glitter in reference space."""
    parameters = parameters or {}
    if shader not in GLITTERING or not parameters.get('show_glitter'):
        return False
    try:
        return int(parameters.get('glitter_space', REFERENCE_SPACE)) == REFERENCE_SPACE
    except (TypeError, ValueError):
        return False


def wanted(materials):
    """Whether any of the scene's materials (as host.snapshot reads them) asks for rest positions."""
    def asks(material):
        if not isinstance(material, dict):
            return False
        if in_reference_space(material.get('native_shader'), material.get('native_parameters')):
            return True
        graph = material.get('node_graph') or {}
        if any(in_reference_space(node.get('type'), node.get('parameters')) for node in (graph.get('nodes') or {}).values()):
            return True
        return any(asks(layer) for layer in material.get('material_stack') or [] if layer is not material)
    return any(asks(material) for material in (materials or {}).values())


def read(item, count):
    """A mesh item's rest positions: its base mesh's points, before deformers, in its own space; None where the base
    mesh has not the same number of points as the mesh rendered (a deformer that adds or takes away points)."""
    import lx
    import modo
    from . import mesh_reader
    base = modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'read')
    if base.PointCount() != count:
        return None
    whole = mesh_reader.read(base)
    if whole is not None and len(whole.vertices) == count:
        return [list(point) for point in whole.vertices]
    points = lx.object.Point(base.PointAccessor())
    found = []
    for index in range(count):
        points.SelectByIndex(index)
        found.append(list(points.Pos()))
    return found
