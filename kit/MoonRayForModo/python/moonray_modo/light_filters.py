"""Native light shaping filters with host locator transforms."""
from pathlib import Path
from .rdla import string,number,vector,matrix
from .working_space import color as working_color,texture as working_texture

def emit(settings,light,scene,name,lines):
    result=[];identity=settings.get('filter_locator')
    transform=scene.get('scene_references',{}).get(identity,{}).get('matrix') if identity else light['matrix']
    if transform is None:raise ValueError('Light filter locator is missing')
    def add(kind,suffix,attrs):
        ref=kind+'('+string(name+'/'+suffix)+')'
        lines.append(ref+' {');lines.extend('  ['+string(k)+'] = '+v+',' for k,v in attrs.items());lines.append('}');result.append(ref)
    if settings.get('rod_enabled'):
        add('RodLightFilter','rod',{'node_xform':matrix(transform),'width':number(settings.get('rod_width',1)),
            'height':number(settings.get('rod_height',1)),'depth':number(settings.get('rod_depth',1)),
            'radius':number(settings.get('rod_radius',0)),'edge':number(settings.get('rod_edge',.1)),
            'color':vector(working_color(settings.get('rod_color',[0,0,0])),'Rgb'),'density':number(settings.get('rod_density',1)),
            'invert':'true' if settings.get('rod_invert') else 'false'})
    if settings.get('barn_enabled'):
        attrs={'node_xform':matrix(transform),'use_light_xform':'false' if identity else 'true','edge':number(settings.get('barn_edge',.1)),'mode':'0'}
        for side in ('top','bottom','left','right'):attrs['size_'+side]=number(settings.get('barn_'+side,0))
        add('BarnDoorLightFilter','barn',attrs)
    if settings.get('cookie_file'):
        from .textures import prepare
        texture=working_texture(prepare(settings['cookie_file'],True))
        add('CookieLightFilter_v2','cookie',{'node_xform':matrix(transform),'texture':string(texture),'gamma':'Rgb(1,1,1)',
            'projector_focal':number(settings.get('cookie_focal',30)),'projector_film_width_aperture':number(settings.get('cookie_aperture',24)),
            'density':number(settings.get('cookie_density',1)),'invert':'true' if settings.get('cookie_invert') else 'false'})
    if settings.get('ramp_enabled'):
        start=settings.get('ramp_start',0);end=settings.get('ramp_end',10)
        if end<=start:raise ValueError('Color ramp end distance must exceed start distance')
        add('ColorRampLightFilter','ramp',{'node_xform':matrix(transform),'use_xform':'true' if identity else 'false',
            'begin_distance':number(start),'end_distance':number(end),'distances':'{0,1}',
            'colors':'{'+vector(working_color(settings.get('ramp_color0',[1,1,1])),'Rgb')+','+vector(working_color(settings.get('ramp_color1',[0,0,0])),'Rgb')+'}','interpolation_types':'{1,1}'})
    if settings.get('filter_vdb'):
        from .textures import register
        path=Path(settings['filter_vdb']).resolve()
        if not path.is_file():raise ValueError('Missing light-filter VDB: '+str(path))
        add('VdbLightFilter','vdb',{'node_xform':matrix(transform),'vdb_map':string(register(path)),
            'density_grid_name':string(settings.get('filter_vdb_grid','density')),'vdb_interpolation_type':'1',
            'color_tint':vector(working_color(settings.get('filter_vdb_tint',[0,0,0])),'Rgb')})
    return result
