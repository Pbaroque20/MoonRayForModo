"""Native light linking, emitter overrides and filter assignments."""
import re
from .rdla import string,number,vector,node_matrix,array

LIGHT_KINDS=('','DistantLight','SphereLight','RectLight','SpotLight','DiskLight','CylinderLight','PortalLight')

def owner(geometry):
    return geometry.get('source_item') or str(geometry.get('identity','')).split('|')[0]

def emit(scene,meshes,environment,lines):
    controls=scene.get('production',{});light_controls=controls.get('lights',{});objects=controls.get('objects',{})
    refs={};environment_refs=[]
    if environment>0:
        ref='EnvLight("/modo/environment")';environment_refs.append(ref)
        lines.append('table.insert(lights, %s { ["intensity"] = %s })'%(ref,number(environment)))
    from .environments import emit as emit_environments
    emit_environments(scene.get('environments',[]),lines)
    environment_refs += ['EnvLight(%s)'%string('/modo/environment/scene/%d'%i) for i in range(len(scene.get('environments',[])))]
    portal_refs=([environment_refs[0]] if environment>0 else [])+['EnvLight(%s)'%string('/modo/environment/scene/%d'%i) for i,e in enumerate(scene.get('environments',[])) if e.get('indirect',True)]
    refs['__environment__']=environment_refs
    for index,light in enumerate(scene.get('lights',[])):
        identity=light.get('identity',str(index));settings=light_controls.get(identity,{});kind=settings.get('kind') or light['kind']
        if kind not in LIGHT_KINDS:raise ValueError('Unsupported light: '+kind)
        name='/modo/light/'+identity;ref='%s(%s)'%(kind,string(name));refs[identity]=[ref]
        attrs={'node_xform':node_matrix(light),'color':vector(light['color'],'Rgb'),'intensity':number(light['intensity'])}
        label=settings.get('label','')
        if label:
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',label):raise ValueError('Light group labels must use letters, numbers and underscores')
            attrs['label']=string(label)
        if kind=='DistantLight':attrs['angular_extent']=number(light.get('angle',.5))
        if kind in ('SphereLight','DiskLight','CylinderLight'):attrs['radius']=number(max(.001,light.get('radius',.05)))
        if kind=='CylinderLight':attrs['height']=number(light.get('height',1))
        if kind in ('RectLight','PortalLight'):attrs.update(width=number(light.get('width',1)),height=number(light.get('height',1)))
        if kind=='PortalLight':
            if len(portal_refs)!=1:raise ValueError('A portal needs exactly one active environment; combine environment layers or disable the additional uniform light')
            attrs['light']=portal_refs[0]
        if kind=='SpotLight':
            cone=light.get('cone',45);attrs.update(outer_cone_angle=number(cone),inner_cone_angle=number(max(0,cone-2*light.get('soft_edge',0))),lens_radius=number(light.get('radius',.001)))
        filters=[]
        if settings.get('filter_enabled'):
            f='IntensityLightFilter(%s)'%string(name+'/intensity')
            lines.append('%s { ["intensity"] = %s, ["exposure"] = %s, ["color"] = %s }'%(f,number(settings.get('filter_intensity',1)),number(settings.get('filter_exposure',0)),vector(settings.get('filter_color',[1,1,1]),'Rgb')));filters.append(f)
        if settings.get('decay_enabled'):
            start=float(settings.get('near_start',0));end=float(settings.get('near_end',0));far=float(settings.get('far_start',10));stop=float(settings.get('far_end',20))
            if not 0<=start<=end<=far<stop:raise ValueError('Light decay distances require 0 <= near start <= near end <= far start < far end')
            f='DecayLightFilter(%s)'%string(name+'/decay')
            lines.append('%s { ["falloff_near"] = %s, ["falloff_far"] = true, ["near_start"] = %s, ["near_end"] = %s, ["far_start"] = %s, ["far_end"] = %s }'%(f,'true' if end>start else 'false',number(start),number(end),number(far),number(stop)));filters.append(f)
        if filters:attrs['light_filters']=array(filters)
        lines.append('table.insert(lights, %s {'%ref)
        lines.extend('  [%s] = %s,'%(string(k),v) for k,v in attrs.items())
        lines.append('})')
    for index,mesh in enumerate(meshes):
        identity=owner(mesh);settings=objects.get(identity,{})
        if not settings.get('mesh_light'):continue
        if 'instances' in mesh:raise ValueError('Mesh light '+mesh['name']+' requires instance sharing to be disabled in Object controls')
        ref='MeshLight(%s)'%string('/modo/meshLight/'+str(index));refs.setdefault(identity,[]).append(ref)
        label=settings.get('light_label','')
        if label and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',label):raise ValueError('Invalid mesh light group label')
        lines.append('table.insert(lights, %s { ["geometry"] = RdlMeshGeometry("/modo/mesh/%d"), ["color"] = %s, ["intensity"] = %s, ["label"] = %s })'%(ref,index,vector(settings.get('light_color',[1,1,1]),'Rgb'),number(settings.get('light_intensity',1)),string(label)))
    lines += ['local lightSet = LightSet("/modo/lightSet")(lights)','local objectLightSets = {}','local objectShadowSets = {}']
    for identity,settings in sorted(objects.items()):
        def selected(key):
            keys=settings.get(key,[]);missing=[k for k in keys if k not in refs]
            if missing:raise ValueError('Linked light is missing or disabled: '+', '.join(missing))
            return [ref for k in keys for ref in refs[k]]
        if settings.get('link_enabled'):
            lines.append('objectLightSets[%s] = LightSet(%s)(%s)'%(string(identity),string('/modo/links/'+identity),array(selected('lights'))))
        if settings.get('shadow_exclude'):
            lines.append('objectShadowSets[%s] = ShadowSet(%s)(%s)'%(string(identity),string('/modo/shadows/'+identity),array(selected('shadow_exclude'))))
