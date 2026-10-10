"""Native strands, points and file-backed VDB volumes; no proxy polygon shells."""
import json,math,re
from pathlib import Path
from .rdla import IDENTITY,string,number,vector,node_matrix,array,many_vectors


def vectors(values,kind='Vec3'):
    """A long list of vectors as text: all at once where there are many, which is what hair is."""
    whole=many_vectors(values,kind) if len(values)>1000 else None
    return whole if whole is not None else array(vector(v,kind) for v in values)

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
        return dict(root=radius,tip=radius,envelope=1.0,samples=int(settings.get('curve_samples',8)),uv=True,round=False,basis=0)
    if not values['curves']:return None
    shape=dict(root=values['curve_root_width']/2000.0,tip=values['curve_tip_width']/2000.0,envelope=float(values['curve_envelope']),
               samples=values['curve_samples'],uv=values['curve_uv'],round=values['curve_round'],basis=values['curve_basis'])
    if values['hair']:
        shape['hair']={key[5:]:values[key] for key in values if key.startswith('hair_')}
    return shape


# Hair that has been grown, kept by what it was grown from: growing it takes seconds, and nothing about it
# changes until its guides, its scalp or its settings do.
GROWN={}
# The grown strands back in their mesh's own space, and the curve geometry made of them, kept so that a scene read
# again with its hair as it was hands on the very same lists. What comes after knows a list it has seen by which
# list it is, and does not go through a hundred thousand points to find that nothing moved.
PLACED={}
BATCHED={}
SCALPS={}


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
    # Each strand keeps its guide's material, and goes back into the mesh's own space, where its curves are.
    placed=(key,tuple(float(v) for v in matrix),tuple(tag for _,tag,_ in strands),bool(settings['guides']))
    if placed not in PLACED:
        if len(PLACED)>=8:PLACED.pop(next(iter(PLACED)))
        # The runtime's own program grows the same hair many times faster, and puts it back in the mesh's space itself.
        from . import hair_native
        fast=hair_native.grow(guides,triangles,settings['mode'],settings['count'],settings['width']/2000.0,settings['clump'],settings['length'],settings['seed'],
                              [float(v) for v in back])
        if fast is not None:
            local,adrift=fast
        else:
            if key not in GROWN:
                if len(GROWN)>=8:GROWN.pop(next(iter(GROWN)))
                # The scalp's grid is kept by its triangles: a guide moved, or a setting changed, leaves the scalp as it was.
                surface=None
                if triangles:
                    shape=hashlib.sha1(packed('d',itertools.chain.from_iterable(itertools.chain.from_iterable(triangles))).tobytes()).digest()
                    if shape not in SCALPS:
                        if len(SCALPS)>=4:SCALPS.pop(next(iter(SCALPS)))
                        SCALPS[shape]=hair.Scalp(triangles)
                    surface=SCALPS[shape]
                GROWN[key]=hair.grow(guides,surface,settings['mode'],settings['count'],
                                     settings['width']/2000.0,settings['clump'],settings['length'],settings['seed'])
            children,adrift=GROWN[key]
            # The matrix written out: this runs once for every point of every strand.
            a,b,c,_,d,e,f,_,g,h,i,_,x,y,z,_=(float(v) for v in back)
            local=[[[p[0]*a+p[1]*d+p[2]*g+x,p[0]*b+p[1]*e+p[2]*h+y,p[0]*c+p[1]*f+p[2]*i+z] for p in child] for child in children]
        per=max(1,settings['count'])
        grown_strands=[(child,strands[min(len(strands)-1,index//per)][1],None) for index,child in enumerate(local)]
        PLACED[placed]=((list(strands) if settings['guides'] else [])+grown_strands,adrift)
    made,adrift=PLACED[placed]
    if adrift:
        warnings.append('Hair on %s: %d of %d guides %s too far from the scalp, and the hair of %s grows from the guide itself. Start each guide on the surface.'%(item.name,adrift,len(guides),'starts' if adrift==1 else 'start','it' if adrift==1 else 'them'))
    return made


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
            for a,b in zip(strand,strand[1:]):lengths.append(lengths[-1]+math.dist(a,b))
            total=lengths[-1] or 1.0;across=(index+.5)/len(members)
            for length in lengths:
                along=length/total
                if tapered:radii.append(shape['root']+(shape['tip']-shape['root'])*along**shape['envelope'])
                if shape['uv']:uvs.append([across,along])
        entry=dict(kind='curves',identity=identity+'|curves|'+tag,source_item=identity,name=name,vertices=vertices,counts=counts,
                   radius=shape['root'],curve_type=0,material=tag,matrix=matrix)
        # Lines whose points are the control points of a smooth curve go to MoonRay as that curve, where there are
        # points enough for one: four for a B-spline, four and then three more at a time for a Bezier.
        basis=shape.get('basis',0)
        if basis==2 and all(c>=4 for c in counts) or basis==1 and all(c>=4 and (c-1)%3==0 for c in counts):entry['curve_type']=basis
        if shape.get('round'):entry['round']=True
        if tapered:entry['radii']=radii
        if shape['uv']:entry['uvs']=uvs
        if ids:entry['ids']=ids
        result.append(entry)
    return result


# The text of the long lists of a curve geometry, kept by what is in them: thousands of strands
# are slow to write out and are the same from one render to the next.
WRITTEN={}
SEEN={}


def written(kind,values,write):
    import hashlib,itertools
    from array import array as packed
    # A list seen before, the very same one, is not read through again.
    seen=SEEN.get((kind,id(values)))
    if seen is not None and seen[0] is values and seen[1]==len(values):return seen[2]
    flat=values if not values or not isinstance(values[0],(list,tuple)) else itertools.chain.from_iterable(values)
    key=(kind,len(values),hashlib.sha1(packed('d',flat).tobytes()).digest())
    if key not in WRITTEN:
        if len(WRITTEN)>=32:WRITTEN.pop(next(iter(WRITTEN)))
        WRITTEN[key]=write()
    if len(values)>4096:
        if len(SEEN)>=32:SEEN.pop(next(iter(SEEN)))
        SEEN[(kind,id(values))]=(values,len(values),WRITTEN[key])
    return WRITTEN[key]


def fur_entries(scene,item,mesh,polygons,points,warnings):
    """The fur of a mesh that wears one of Modo's Fur materials, as curve geometry: one for each Fur material that is
    on any of its polygons."""
    import lx,lxu.utils
    from . import fur
    from .host import channel,world_matrix
    try:layers=list(scene.items('furMaterial'))
    except (LookupError,RuntimeError,TypeError):return []
    made=[]
    for layer in layers:
        mask=layer.parent if layer.parent is not None and layer.parent.type=='mask' else None
        if not channel(layer,'enable',1) or (mask is not None and not channel(mask,'enable',1)):continue
        wanted=''
        if mask is not None:
            # Which polygons the group is for: those of a material tag, of chosen items, or all.
            if channel(mask,'ptyp','') not in ('Material',''):continue
            wanted=channel(mask,'ptag','') or ''
            if wanted=='(all)':wanted=''
            try:targets=list(mask.itemGraph('shadeLoc').forward())
            except (LookupError,RuntimeError,AttributeError):targets=[]
            if targets and all(target.id!=item.id for target in targets):continue
        tags=lx.object.StringTag(polygons);places={};faces=[]
        for i in range(mesh.PolygonCount()):
            polygons.SelectByIndex(i)
            if lxu.utils.decodeID4(polygons.Type()) not in ('FACE','SUBD','PSUB') or polygons.VertexCount()<3:continue
            if wanted and strand_tag(tags,lx.symbol.i_POLYTAG_MATERIAL)!=wanted:continue
            corners=[]
            for v in range(polygons.VertexCount()):
                point=polygons.VertexByIndex(v)
                if point not in places:
                    points.Select(point);places[point]=tuple(points.Pos())
                corners.append(point)
            faces.append((corners,strand_tag(tags,lx.symbol.i_POLYTAG_MATERIAL)))
        if not faces:continue
        # The surface's normal at each point: its faces' normals together, so fur on a round thing stands out all round.
        normals={}
        for corners,_ in faces:
            x=y=z=0.0
            for k,point in enumerate(corners):
                a,b=places[point],places[corners[(k+1)%len(corners)]]
                x+=(a[1]-b[1])*(a[2]+b[2]);y+=(a[2]-b[2])*(a[0]+b[0]);z+=(a[0]-b[0])*(a[1]+b[1])
            for point in corners:
                held=normals.get(point,(0.0,0.0,0.0));normals[point]=(held[0]+x,held[1]+y,held[2]+z)
        for point,(x,y,z) in normals.items():
            size=math.sqrt(x*x+y*y+z*z) or 1.0;normals[point]=(x/size,y/size,z/size)
        triangles=[(places[c[0]],places[c[k]],places[c[k+1]],normals[c[0]],normals[c[k]],normals[c[k+1]]) for c,_ in faces for k in range(1,len(c)-1)]
        # Each fibre takes the material of the polygon it stands on.
        worn=[tag for c,tag in faces for k in range(1,len(c)-1)]
        read=lambda key,layer=layer:layer.channel(key).get()
        strands,root,tip,asked,stands=fur.kept(triangles,fur.settings(read))
        left=fur.unread(read)
        if left:warnings.append('Fur on %s is grown without %s, which the plugin does not read from a Fur material.'%(item.name,', '.join(left)))
        if asked>len(strands):
            warnings.append('Fur on %s: Modo would grow %s fibres; %s are grown, each wider, to cover the surface as well.'%(item.name,format(asked,','),format(len(strands),',')))
        if not strands:continue
        shape=dict(root=root,tip=tip,envelope=1.0,samples=8,uv=True,round=False,basis=0)
        kept=(item.id+'|fur|'+layer.id,item.name,root,tip,wanted,tuple(world_matrix(item)))
        held=BATCHED.get(kept)
        if held is None or held[0] is not strands:
            if len(BATCHED)>=8:BATCHED.pop(next(iter(BATCHED)))
            held=BATCHED[kept]=(strands,batches(item.id+'|fur|'+layer.id,item.name,[(strand,worn[at],None) for strand,at in zip(strands,stands)],shape,'',world_matrix(item)))
        # The fur is its mesh's, for what lights it and what it is called.
        made+=[dict(entry,source_item=item.id) for entry in held[1]]
    return made


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
        # A heavy mesh the scene reader has just found to hold only surface polygons has no curves or loose points to look for.
        from . import mesh_reader
        known=mesh_reader.SURFACES_ONLY.get(item.id)==(mesh.PolygonCount(),mesh.PointCount())
        for i in range(0 if known else mesh.PolygonCount()):
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
            if shape.get('hair'):
                # A cluster left at no width is sized from its guides, a sixth of their length across; and no strand is so
                # thick that the strands of a cluster run into one another, which is what made a lock look like one rod.
                growing=dict(shape['hair'])
                if growing['width']<=0:
                    lengths=[sum(math.dist(a,b) for a,b in zip(points,points[1:])) for points,_,_ in strands if len(points)>1]
                    growing['width']=1000.0*(sum(lengths)/len(lengths) if lengths else 0.06)/6.0
                strands=grown(scene,item,strands,growing,warnings)
                apart=growing['width']/1000.0/(12.0*math.sqrt(max(1,growing['count'])))
                shape=dict(shape,root=min(shape['root'],apart),tip=min(shape['tip'],apart))
            if shape.get('hair'):
                # Hair that grew as it did before is the geometry it was before: the same lists, not new ones alike.
                kept=(item.id,item.name,tuple(sorted((k,v) for k,v in shape.items() if k!='hair')),settings.get('material',''),tuple(world_matrix(item)))
                held=BATCHED.get(kept)
                if held is None or held[0] is not strands:
                    if len(BATCHED)>=8:BATCHED.pop(next(iter(BATCHED)))
                    held=BATCHED[kept]=(strands,batches(item.id,item.name,strands,shape,settings.get('material',''),world_matrix(item)))
                made=[dict(entry) for entry in held[1]]
            else:
                made=batches(item.id,item.name,strands,shape,settings.get('material',''),world_matrix(item))
            from . import primitive_attributes
            carried=primitive_attributes.read(item)
            for entry in made:
                if carried:entry['attributes']=carried
            result+=made
        try:result+=fur_entries(scene,item,mesh,polygons,points,warnings)
        except (LookupError,RuntimeError,TypeError,AttributeError,ValueError) as exc:warnings.append('Fur on %s could not be read: %s'%(item.name,exc))
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
            attrs.update(vertex_list_0=written('points',vertices,lambda:vectors(vertices)),
                         radius_list=written('radii',radii,lambda:'{'+', '.join(map('%.12g'.__mod__,radii))+'}'))
            for key,target in (('vertices_close','vertex_list_1'),('velocities','velocity_list_0')):
                if key in entry:
                    if len(entry[key])!=len(vertices):raise ValueError('Motion data does not match geometry vertices')
                    attrs[target]=vectors(entry[key])
            constructor='RdlPointGeometry'
            if kind=='curves':
                curve_type=int(entry.get('curve_type',0))
                if curve_type not in (0,1,2) or sum(counts)!=len(vertices) or any(type(c)!=int or c<(2 if curve_type==0 else 4) or (curve_type==1 and (c-1)%3) for c in counts):raise ValueError('Invalid curve counts or interpolation')
                constructor='RdlCurveGeometry';attrs.update(curves_vertex_count=written('counts',counts,lambda:array(str(c) for c in counts)),curve_type=str(curve_type))
                # MoonRay's own default is a ribbon that faces the view.
                if entry.get('round'):attrs['curves_subtype']='1'
                if entry.get('uvs'):
                    if len(entry['uvs']) not in (len(counts),len(vertices)):raise ValueError('Curve UVs must have one entry per strand or per point')
                    attrs['uv_list']=written('uvs',entry['uvs'],lambda:vectors(entry['uvs'],'Vec2'))
        if 'visibility' in entry:
            camera,indirect,reflection,refraction,subsurface,shadow=entry['visibility']
            for key,value in [('visible_in_camera',camera),('visible_shadow',shadow),('visible_diffuse_reflection',indirect),('visible_diffuse_transmission',indirect),('visible_glossy_reflection',reflection),('visible_mirror_reflection',reflection),('visible_glossy_transmission',refraction),('visible_mirror_transmission',refraction)]:attrs[key]='true' if value else 'false'
        carried=[]
        if crypto and kind!='vdb':
            from .cryptomatte import userdata_set
            carried=list(userdata_set(entry,lines,scene))
        if entry.get('attributes') and kind=='curves':
            from . import primitive_attributes
            carried+=primitive_attributes.emit(path+'/attribute',[entry['attributes']],lines)
        if kind=='curves':
            # MoonRay's hair glints turn with a number that is each strand's own, which it reads from the strands as
            # scatter_tag; without it a hair material with glints renders as an error.
            held=materials.get(tag) or {};held=(held.get('material_stack') or [held])[-1]
            if held.get('native_shader')=='HairMaterial_v3' and (held.get('native_parameters') or {}).get('show_hair_glint'):
                from .moonlightipr_curves import chance
                lines+=['UserData(%s) {'%string(path+'/scatter'),'  ["float_key"] = "scatter_tag",','  ["float_values_0"] = {%s},'%', '.join('%.6f'%chance(i) for i in range(len(counts))),'}']
                carried.append('UserData(%s)'%string(path+'/scatter'))
        if carried:attrs['primitive_attributes']=array(carried)
        lines += ['do','  local g = %s(%s) { %s }'%(constructor,string(path),', '.join('[%s] = %s'%(string(k),v) for k,v in attrs.items())),'  table.insert(geometries, g)']
        if kind=='vdb':
            lines += ['  local a = {g, "", %s, objectLightSets[%s] or (nativeLightSets[%s] and nativeLightSets[%s][%s]) or lightSet}'%(shader,string(owner(entry)),string(owner(entry)),string(owner(entry)),string(tag)),'  if objectShadowSets[%s] then table.insert(a, objectShadowSets[%s]) end'%(string(owner(entry)),string(owner(entry))),'  table.insert(assignments,a)']
        else:lines.append('  assign(g, "", %s, %s)'%(string(tag),string(owner(entry))))
        lines.append('end')
