"""Resolve artist-selected projector/camera/locator references at capture time."""
from contextvars import ContextVar
from contextlib import contextmanager
_references=ContextVar('moonray_scene_references',default={})

@contextmanager
def configuration(scene):
    token=_references.set(scene.get('scene_references',{}))
    try:yield
    finally:_references.reset(token)

def capture(scene,snapshot):
    from .host import world_matrix,channel
    wanted=set()
    def visit(value):
        if isinstance(value,dict):
            if set(value)=={'item'}:wanted.add(value['item'])
            for key,child in value.items():
                if key not in ('vertices','faces','normals','uvs','uv_sets'):visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(snapshot.get('materials',{}));visit(snapshot.get('native_materials',{}))
    from .properties import scene_settings
    for control in scene_settings().get('production',{}).get('lights',{}).values():
        if control.get('filter_locator'):wanted.add(control['filter_locator'])
    result={}
    for identity in sorted(wanted):
        item=scene.item(identity);record={'matrix':world_matrix(item),'camera':item.type=='camera'}
        if record['camera']:
            projection=channel(item,'projType','persp')
            if projection not in ('persp','ortho'):raise ValueError('Projector camera requires perspective or orthographic projection')
            record.update(projection=projection,focal=float(channel(item,'focalLen',.05))*1000,
                          aperture=float(channel(item,'apertureX',.036))*1000)
        result[identity]=record
    return result

def emit(value,definition,path):
    from .rdla import matrix,number
    identity=value['item'];record=_references.get().get(identity)
    if record is None:raise ValueError('Missing camera/projector item: '+identity)
    if record.get('camera'):
        kind='OrthographicCamera' if record['projection']=='ortho' else 'PerspectiveCamera'
        attrs={'node_xform':matrix(record['matrix']),'film_width_aperture':number(record['aperture'])}
        if kind=='PerspectiveCamera':attrs['focal']=number(record['focal'])
        return definition(kind,path,attrs)
    # Coordinate-only node: no geometry or lighting is attached to this handle.
    return definition('RdlMeshGeometry',path,{'node_xform':matrix(record['matrix'])})
