"""Native strands, points and file-backed VDB volumes; no proxy polygon shells."""
import json,math,re
from pathlib import Path
from .rdla import IDENTITY,string,number,vector,node_matrix,array

def asset_frame(path,frame):
    # A run of # is a fixed-width frame field (e.g. smoke.####.vdb).
    return re.sub(r'#+',lambda m:('%0*d'%(len(m.group()),int(frame))),str(path))

def curve_shape(item,settings):
    """How a mesh's curves become tubes: its object overrides if it uses them, otherwise the
    scene controls' one radius. None if the object asks for its curves not to be rendered."""
    from . import options,properties
    values=options.object_values(properties.read(item))
    if not values['override']:
        radius=float(settings.get('radius',.001))
        return dict(root=radius,tip=radius,envelope=1.0,samples=int(settings.get('curve_samples',8)),uv=True,round=False)
    if not values['curves']:return None
    shape=dict(root=values['curve_root_width']/2000.0,tip=values['curve_tip_width']/2000.0,envelope=float(values['curve_envelope']),
               samples=values['curve_samples'],uv=values['curve_uv'],round=values['curve_round'])
    if values['hair']:
        shape['hair']={key[5:]:values[key] for key in values if key.startswith('hair_')}
    return shape


# Hair that has been grown, kept by what it was grown from: growing it takes seconds, and nothing about it
# changes until its guides, its scalp or its settings do.
GROWN={}


def scalp_triangles(scene,identity):
    """A mesh's surface as triangles in the world, as it stands deformed."""
    import lx,modo
    from .host import world_matrix
    from .coordinates import transform
    try:item=scene.item(identity)
    except LookupError:return None
    if item.type!='mesh':return None
    mesh=modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item,'deformed')
    points=lx.object.Point(mesh.PointAccessor());polygons=lx.object.Polygon(mesh.PolygonAccessor())
    matrix=world_matrix(item);places={};triangles=[]
    for i in range(mesh.PolygonCount()):
        polygons.SelectByIndex(i)
        count=polygons.VertexCount()
        if count<3:continue
        corners=[]
        for v in range(count):
            point=polygons.VertexByIndex(v);place=places.get(point)
            if place is None:
                points.Select(point);place=places[point]=tuple(transform(list(points.Pos()),matrix))
            corners.append(place)
        triangles+=[(corners[0],corners[k],corners[k+1]) for k in range(1,count-1)]
    return triangles


def grown(scene,item,strands,settings,warnings):
    """The strands of a mesh whose curves are guides: the hair grown from them on its scalp."""
    import hashlib,itertools
    from array import array as packed
    from . import hair
    from .host import world_matrix
    from .coordinates import transform,inverse
    triangles=scalp_triangles(scene,settings['scalp']) if settings['scalp'] else None
    if triangles is None:
        warnings.append('Hair on %s: choose the mesh it grows on (Hair Scalp) and its roots will be held to that surface; until then they follow the guides alone.'%item.name)
    matrix=world_matrix(item);back=inverse(matrix)
    guides=[[transform(list(p),matrix) for p in strand] for strand,_,_ in strands]
    held=hashlib.sha1()
    for part in (packed('d',itertools.chain.from_iterable(itertools.chain.from_iterable(guides))),packed('q',[len(g) for g in guides]),
                 packed('d',itertools.chain.from_iterable(itertools.chain.from_iterable(triangles or []))),
                 packed('d',[settings['mode'],settings['count'],settings['width'],settings['clump'],settings['length'],settings['seed']])):
        held.update(part.tobytes());held.update(b'|')
    key=held.digest()
    if key not in GROWN:
        if len(GROWN)>=8:GROWN.pop(next(iter(GROWN)))
        GROWN[key]=hair.grow(guides,hair.Scalp(triangles) if triangles else None,settings['mode'],settings['count'],
                             settings['width']/2000.0,settings['clump'],settings['length'],settings['seed'])
    children,adrift=GROWN[key]
    if adrift:
        warnings.append('Hair on %s: %d of %d strands found no scalp within reach and were left on their guides. Draw the guides from the surface, or widen the clusters less.'%(item.name,adrift,len(children)))
    # Each strand keeps its guide's material, and goes back into the mesh's own space, where its curves are.
    per=max(1,settings['count']);grown_strands=[]
    for index,child in enumerate(children):
        tag=strands[min(len(strands)-1,index//per)][1]
        grown_strands.append(([transform(p,back) for p in child],tag,None))
    return (list(strands) if settings['guides'] else [])+grown_strands


def polylines(mesh,polygons,points,id_tag,item):
    """Strands that are already lines: their points as they stand, with nothing to evaluate.
    This is how hair guides and imported strands arrive, thousands at a time."""
    import lx,lxu.utils
    tags=lx.object.StringTag(polygons);positions={};found=[]
    code=lxu.utils.lxID4(id_tag) if id_tag else None
    for i in range(mesh.PolygonCount()):
        polygons.SelectByIndex(i)
        if lxu.utils.decodeID4(polygons.Type())!='LINE':continue
        strand=[]
        for v in range(polygons.VertexCount()):
            point=polygons.VertexByIndex(v);place=positions.get(point)
            if place is None:
                points.Select(point);place=positions[point]=list(points.Pos())
            strand.append(place)
        if len(strand)<2:continue
        found.append((strand,strand_tag(tags,lx.symbol.i_POLYTAG_MATERIAL),strand_id(tags,code,item)))
    return found


def sampled(mesh,polygons,samples,id_tag,item,lines):
    """Strands drawn as splines, read off Modo's own evaluation of each curve. Modo lists the
    line polygons among its curves too; those keep the points they have."""
    import lx,lxu.utils
    kinds=[]
    for i in range(mesh.PolygonCount()):
        polygons.SelectByIndex(i);kind=lxu.utils.decodeID4(polygons.Type())
        if kind in ('CURV','BEZR','BSPL','LINE') and (kind!='LINE' or polygons.VertexCount()>1):kinds.append(kind)
    group=lx.object.CurveGroup(lx.service.Mesh().CurveGroupFromMesh(mesh,((1.,0.,0.,0.),(0.,1.,0.,0.),(0.,0.,1.,0.),(0.,0.,0.,1.))))
    code=lxu.utils.lxID4(id_tag) if id_tag else None;found=[]
    # The curves come in the order of their polygons; if they do not match up, evaluate them all.
    ordered=group.Count()==len(kinds);ready=iter(lines)
    for i in range(group.Count()):
        if ordered and kinds[i]=='LINE':
            found.append(next(ready));continue
        curve=lx.object.Curve(group.ByIndex(i));count=max(2,min(4096,int(samples)*max(1,curve.BendCount())))
        strand=[]
        for j in range(count+1):curve.SetParam(j/count);strand.append(list(curve.Position()))
        tags=lx.object.StringTag(curve)
        found.append((strand,strand_tag(tags,lx.symbol.i_POLYTAG_MATERIAL),strand_id(tags,code,item)))
    return found


def strand_tag(tags,code):
    try:return tags.Get(code) or ''
    except (LookupError,RuntimeError):return ''


def strand_id(tags,code,item):
    if code is None:return None
    try:stable=tags.Get(code)
    except (LookupError,RuntimeError):raise ValueError('Strand is missing its persistent ID tag: '+item.name)
    if not stable:raise ValueError('Strand ID tag is empty: '+item.name)
    return str(stable)


def batches(identity,name,strands,shape,material,matrix):
    """All of a mesh's strands of one material as a single curve geometry: one list of points,
    one count per strand. MoonRay builds one acceleration structure for the lot, which is what
    makes thousands of hairs cost little more than one mesh."""
    groups={}
    for strand,tag,stable in strands:groups.setdefault(material or tag,[]).append((strand,stable))
    result=[];tapered=abs(shape['root']-shape['tip'])>1e-12
    for tag,members in groups.items():
        vertices=[];counts=[];radii=[];uvs=[];ids=[]
        for index,(strand,stable) in enumerate(members):
            vertices+=strand;counts.append(len(strand))
            if stable is not None:ids.append(stable)
            if not (tapered or shape['uv']):continue
            # How far along the strand each point is, by length rather than by count.
            lengths=[0.0]
            for a,b in zip(strand,strand[1:]):lengths.append(lengths[-1]+math.sqrt((b[0]-a[0])**2+(b[1]-a[1])**2+(b[2]-a[2])**2))
            total=lengths[-1] or 1.0;across=(index+.5)/len(members)
            for length in lengths:
                along=length/total
                if tapered:radii.append(shape['root']+(shape['tip']-shape['root'])*along**shape['envelope'])
                if shape['uv']:uvs.append([across,along])
        entry=dict(kind='curves',identity=identity+'|curves|'+tag,source_item=identity,name=name,vertices=vertices,counts=counts,
                   radius=shape['root'],curve_type=0,material=tag,matrix=matrix)
        if shape.get('round'):entry['round']=True
        if tapered:entry['radii']=radii
        if shape['uv']:entry['uvs']=uvs
        if ids:entry['ids']=ids
        result.append(entry)
    return result


# The text of the long lists of a curve geometry, kept by what is in them: thousands of strands
# are slow to write out and are the same from one render to the next.
WRITTEN={}


def written(kind,values,write):
    import hashlib,itertools
    from array import array as packed
    flat=values if not values or not isinstance(values[0],(list,tuple)) else itertools.chain.from_iterable(values)
    key=(kind,len(values),hashlib.sha1(packed('d',flat).tobytes()).digest())
    if key not in WRITTEN:
        if len(WRITTEN)>=32:WRITTEN.pop(next(iter(WRITTEN)))
        WRITTEN[key]=write()
    return WRITTEN[key]


def collect(scene,warnings,controls):
    import lx,modo,lxu.utils
    from .host import render_visible,world_matrix,first_map
    objects=controls.get('objects',{});result=[]
    for item in scene.items('mesh',superType=False):
        if not render_visible(item):continue
        settings=objects.get(item.id,{})
        mesh=modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item,'deformed')
        polygons=lx.object.Polygon(mesh.PolygonAccessor());points=lx.object.Point(mesh.PointAccessor())
        splines=lines=0;point_ids=set()
        for i in range(mesh.PolygonCount()):
            polygons.SelectByIndex(i);kind=lxu.utils.decodeID4(polygons.Type())
            splines+=kind in ('CURV','BEZR','BSPL');lines+=kind=='LINE'
            if kind=='OPNT':point_ids.update(int(polygons.VertexByIndex(v)) for v in range(polygons.VertexCount()))
        shape=curve_shape(item,settings)
        if (splines or lines) and shape is not None:
            id_tag=settings.get('strand_id_tag','')
            if id_tag and (len(id_tag)!=4 or not id_tag.isascii()):raise ValueError('Strand ID tag must contain four characters')
            try:
                strands=polylines(mesh,polygons,points,id_tag,item)
                if splines:strands=sampled(mesh,polygons,shape['samples'],id_tag,item,strands)
            except (LookupError,RuntimeError,TypeError,AttributeError) as exc:
                raise ValueError('Cannot read evaluated curves for '+item.name+': '+str(exc))
            if shape.get('hair'):strands=grown(scene,item,strands,shape['hair'],warnings)
            result+=batches(item.id,item.name,strands,shape,settings.get('material',''),world_matrix(item))
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
            attrs.update(vertex_list_0=written('points',vertices,lambda:array(vector(v) for v in vertices)),
                         radius_list=written('radii',radii,lambda:array(number(v) for v in radii)))
            for key,target in (('vertices_close','vertex_list_1'),('velocities','velocity_list_0')):
                if key in entry:
                    if len(entry[key])!=len(vertices):raise ValueError('Motion data does not match geometry vertices')
                    attrs[target]=array(vector(v) for v in entry[key])
            constructor='RdlPointGeometry'
            if kind=='curves':
                curve_type=int(entry.get('curve_type',0))
                if curve_type not in (0,1,2) or sum(counts)!=len(vertices) or any(type(c)!=int or c<(2 if curve_type==0 else 4) or (curve_type==1 and (c-1)%3) for c in counts):raise ValueError('Invalid curve counts or interpolation')
                constructor='RdlCurveGeometry';attrs.update(curves_vertex_count=written('counts',counts,lambda:array(str(c) for c in counts)),curve_type=str(curve_type))
                # MoonRay's own default is a ribbon that faces the view.
                if entry.get('round'):attrs['curves_subtype']='1'
                if entry.get('uvs'):
                    if len(entry['uvs']) not in (len(counts),len(vertices)):raise ValueError('Curve UVs must have one entry per strand or per point')
                    attrs['uv_list']=written('uvs',entry['uvs'],lambda:array(vector(v,'Vec2') for v in entry['uvs']))
        if 'visibility' in entry:
            camera,indirect,reflection,refraction,subsurface,shadow=entry['visibility']
            for key,value in [('visible_in_camera',camera),('visible_shadow',shadow),('visible_diffuse_reflection',indirect),('visible_diffuse_transmission',indirect),('visible_glossy_reflection',reflection),('visible_mirror_reflection',reflection),('visible_glossy_transmission',refraction),('visible_mirror_transmission',refraction)]:attrs[key]='true' if value else 'false'
        if crypto and kind!='vdb':
            from .cryptomatte import userdata_set
            attrs['primitive_attributes']=array(userdata_set(entry,lines,scene))
        lines += ['do','  local g = %s(%s) { %s }'%(constructor,string(path),', '.join('[%s] = %s'%(string(k),v) for k,v in attrs.items())),'  table.insert(geometries, g)']
        if kind=='vdb':
            lines += ['  local a = {g, "", %s, objectLightSets[%s] or (nativeLightSets[%s] and nativeLightSets[%s][%s]) or lightSet}'%(shader,string(owner(entry)),string(owner(entry)),string(owner(entry)),string(tag)),'  if objectShadowSets[%s] then table.insert(a, objectShadowSets[%s]) end'%(string(owner(entry)),string(owner(entry))),'  table.insert(assignments,a)']
        else:lines.append('  assign(g, "", %s, %s)'%(string(tag),string(owner(entry))))
        lines.append('end')
