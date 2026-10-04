"""Native strands, points and file-backed VDB volumes; no proxy polygon shells."""
import json,math,re
from pathlib import Path
from .rdla import IDENTITY,string,number,vector,node_matrix,array

def asset_frame(path,frame):
    # A run of # is a fixed-width frame field (e.g. smoke.####.vdb).
    return re.sub(r'#+',lambda m:('%0*d'%(len(m.group()),int(frame))),str(path))

def collect(scene,warnings,controls):
    import lx,modo,lxu.utils
    from .host import render_visible,world_matrix,first_map
    objects=controls.get('objects',{});result=[]
    for item in scene.items('mesh',superType=False):
        if not render_visible(item):continue
        settings=objects.get(item.id,{})
        mesh=modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item,'deformed')
        polygons=lx.object.Polygon(mesh.PolygonAccessor());points=lx.object.Point(mesh.PointAccessor())
        has_curves=False;point_ids=set()
        for i in range(mesh.PolygonCount()):
            polygons.SelectByIndex(i);kind=lxu.utils.decodeID4(polygons.Type())
            has_curves=has_curves or kind in ('CURV','BEZR','BSPL','LINE')
            if kind=='OPNT':point_ids.update(int(polygons.VertexByIndex(v)) for v in range(polygons.VertexCount()))
        if has_curves:
            try:
                group=lx.object.CurveGroup(lx.service.Mesh().CurveGroupFromMesh(mesh,((1.,0.,0.,0.),(0.,1.,0.,0.),(0.,0.,1.,0.),(0.,0.,0.,1.))))
                for i in range(group.Count()):
                    curve=lx.object.Curve(group.ByIndex(i));count=max(2,min(4096,int(settings.get('curve_samples',32))*max(1,curve.BendCount())))
                    vertices=[]
                    for j in range(count+1):curve.SetParam(j/count);vertices.append(list(curve.Position()))
                    try:tag=lx.object.StringTag(curve).Get(lx.symbol.i_POLYTAG_MATERIAL) or ''
                    except (LookupError,RuntimeError):tag=''
                    stable=None
                    id_tag=settings.get('strand_id_tag','')
                    if id_tag:
                        if len(id_tag)!=4 or not id_tag.isascii():raise ValueError('Strand ID tag must contain four characters')
                        try:stable=lx.object.StringTag(curve).Get(lxu.utils.lxID4(id_tag))
                        except (LookupError,RuntimeError):raise ValueError('Strand is missing its persistent ID tag: '+item.name)
                        if not stable:raise ValueError('Strand ID tag is empty: '+item.name)
                    result.append(dict(kind='curves',identity=item.id+'|curve|'+(str(stable) if stable is not None else str(i)),source_item=item.id,name=item.name,vertices=vertices,counts=[len(vertices)],radius=float(settings.get('radius',.001)),curve_type=0,material=settings.get('material') or tag,matrix=world_matrix(item)))
                    if stable is not None:result[-1]['ids']=[str(stable)]
            except (LookupError,RuntimeError,TypeError,AttributeError) as exc:
                raise ValueError('Cannot read evaluated curves for '+item.name+': '+str(exc))
        if not mesh.PolygonCount() or point_ids or settings.get('points'):
            vertices=[];stable=[];id_name=settings.get('point_id_map','')
            id_map=first_map(mesh,lx.symbol.i_VMAP_WEIGHT,id_name) if id_name else None
            if id_name and id_map is None:raise ValueError('Missing point ID weight map: '+id_name)
            storage=lx.object.storage();storage.setType('f');storage.setSize(1)
            for i in range(mesh.PointCount()):
                points.SelectByIndex(i)
                if settings.get('points') or not mesh.PolygonCount() or int(points.ID()) in point_ids:
                    vertices.append(list(points.Pos()))
                    if id_map is not None:
                        if not points.MapValue(id_map,storage):raise ValueError('Point has no persistent ID value: '+item.name)
                        raw=storage.get();value=raw[0] if isinstance(raw,(list,tuple)) else raw
                        if not math.isfinite(value) or int(value)!=value or abs(value)>16777216:raise ValueError('Point IDs must be exact float integers within +/-16777216')
                        stable.append(int(value))
            if vertices:result.append(dict(kind='points',identity=item.id+'|points',source_item=item.id,name=item.name,vertices=vertices,radius=float(settings.get('radius',.001)),material=settings.get('material',''),matrix=world_matrix(item)))
            if vertices and id_map is not None:
                if len(set(stable))!=len(stable):raise ValueError('Duplicate point IDs: '+item.name)
                result[-1]['ids']=stable
    return result

def attach(scene,settings):
    # Controls refer to stable item IDs. File geometry can be attached to a locator.
    from .host import world_matrix
    import modo,lx
    frame=scene.get('frame',round(lx.service.Selection().GetTime()*float(modo.Scene().fps)))
    if '_external_motion_settings' in scene:
        if scene['_external_motion_settings']!=settings:raise ValueError('Geometry asset settings changed after shutter capture; capture the frame again')
        return
    values=[value for value in scene.get('extra_geometry',[]) if not value.get('_external_asset')]
    for identity,entry in settings.get('objects',{}).items():
        path=entry.get('geometry_file','')
        if not path:continue
        path=Path(asset_frame(path,frame)).expanduser().resolve()
        if not path.is_file():raise ValueError('Missing geometry asset: '+str(path))
        try:item=modo.Scene().item(identity)
        except LookupError:raise ValueError('Geometry asset owner no longer exists: '+identity)
        transform=scene.get('asset_owners',{}).get(identity,{'matrix':world_matrix(item)})
        if path.suffix.lower()=='.vdb':
            value=dict(entry,kind='vdb',file=str(path),identity=identity+'|vdb',source_item=identity,name=item.name,**transform)
        else:
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('kind') not in ('curves','points'):raise ValueError('Geometry JSON needs kind curves or points')
            value=dict(data,identity=identity+'|external',source_item=identity,name=item.name,**transform,file=str(path),material=entry.get('material') or data.get('material',''))
        value['_external_asset']=True
        if value['kind'] in ('curves','points') and 'ids' in value:
            from .geometry_ids import align
            align(value,value)
        values.append(value)
    scene['extra_geometry']=values

def emit(scene,materials,lines,crypto=False):
    from .lighting import owner
    from .working_space import color as working_color
    for index,entry in enumerate(scene.get('extra_geometry',[])):
        path='/modo/extra/'+entry['identity'];kind=entry['kind'];tag=entry.get('material','');tag=tag if tag in materials else ''
        attrs={'node_xform':node_matrix(entry)}
        if kind=='vdb':
            shader='VdbVolume(%s)'%string(path+'/volume');gain=max(0,float(entry.get('density',1)));emission=max(0,float(entry.get('emission',1)));anisotropy=float(entry.get('anisotropy',0))
            if not -1<=anisotropy<=1:raise ValueError('Volume anisotropy must be between -1 and 1')
            lines.append('%s { ["opacity_gain_mult"] = Rgb(%s,%s,%s), ["color_mult"] = %s, ["incandescence_gain_mult"] = Rgb(%s,%s,%s), ["anisotropy"] = %s }'%(shader,number(gain),number(gain),number(gain),vector(working_color(entry.get('volume_color',[1,1,1])),'Rgb'),number(emission),number(emission),number(emission),number(anisotropy)))
            attrs.update(model=string(entry['file']),density_grid=string(entry.get('density_grid','density')),emission_grid=string(entry.get('emission_grid','')),velocity_grid=string(entry.get('velocity_grid','')),velocity_scale=number(entry.get('velocity_scale',1)))
            constructor='VdbGeometry'
        else:
            vertices=entry['vertices'];radii=entry.get('radii',[entry.get('radius',.001)])
            if not vertices:continue
            if not isinstance(radii,list):raise ValueError('Geometry radii must be an array')
            if any(not math.isfinite(float(r)) or r<0 for r in radii) or not any(r>0 for r in radii):raise ValueError('Curve/point radii must be nonnegative with at least one positive radius')
            if kind=='points' and len(radii)==1:radii=radii*len(vertices)
            counts=entry.get('counts',[])
            allowed={1,len(vertices),len(counts)} if kind=='curves' else {len(vertices)}
            if len(radii) not in allowed:raise ValueError('Radius count does not match geometry')
            attrs.update(vertex_list_0=array(vector(v) for v in vertices),radius_list=array(number(v) for v in radii))
            for key,target in (('vertices_close','vertex_list_1'),('velocities','velocity_list_0')):
                if key in entry:
                    if len(entry[key])!=len(vertices):raise ValueError('Motion data does not match geometry vertices')
                    attrs[target]=array(vector(v) for v in entry[key])
            constructor='RdlPointGeometry'
            if kind=='curves':
                curve_type=int(entry.get('curve_type',0))
                if curve_type not in (0,1,2) or sum(counts)!=len(vertices) or any(type(c)!=int or c<(2 if curve_type==0 else 4) or (curve_type==1 and (c-1)%3) for c in counts):raise ValueError('Invalid curve counts or interpolation')
                constructor='RdlCurveGeometry';attrs.update(curves_vertex_count=array(str(c) for c in counts),curve_type=str(curve_type))
                if entry.get('uvs'):
                    if len(entry['uvs'])!=len(counts):raise ValueError('Curve UVs must have one entry per strand')
                    attrs['uv_list']=array(vector(v,'Vec2') for v in entry['uvs'])
        if 'visibility' in entry:
            camera,indirect,reflection,refraction,subsurface,shadow=entry['visibility']
            for key,value in [('visible_in_camera',camera),('visible_shadow',shadow),('visible_diffuse_reflection',indirect),('visible_diffuse_transmission',indirect),('visible_glossy_reflection',reflection),('visible_mirror_reflection',reflection),('visible_glossy_transmission',refraction),('visible_mirror_transmission',refraction)]:attrs[key]='true' if value else 'false'
        if crypto and kind!='vdb':
            from .cryptomatte import userdata,category
            attrs['primitive_attributes']=array([userdata(entry,lines,category(scene),scene)])
        lines += ['do','  local g = %s(%s) { %s }'%(constructor,string(path),', '.join('[%s] = %s'%(string(k),v) for k,v in attrs.items())),'  table.insert(geometries, g)']
        if kind=='vdb':
            lines += ['  local a = {g, "", %s, objectLightSets[%s] or (nativeLightSets[%s] and nativeLightSets[%s][%s]) or lightSet}'%(shader,string(owner(entry)),string(owner(entry)),string(owner(entry)),string(tag)),'  if objectShadowSets[%s] then table.insert(a, objectShadowSets[%s]) end'%(string(owner(entry)),string(owner(entry))),'  table.insert(assignments,a)']
        else:lines.append('  assign(g, "", %s, %s)'%(string(tag),string(owner(entry))))
        lines.append('end')
