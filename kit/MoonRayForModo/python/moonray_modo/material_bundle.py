"""Portable native material graphs, dependencies and original texture assets."""
import copy,hashlib,json,shutil,uuid
from pathlib import Path
from . import nodes,shader_library

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def refs(value):
 if isinstance(value,dict):
  if set(value)=={'material'}:yield value['material']
  else:
   for item in value.values():yield from refs(item)
 elif isinstance(value,list):
  for item in value:yield from refs(item)

def remap(value,identities):
 if isinstance(value,dict):
  if set(value)=={'material'}:return {'material':identities[value['material']]}
  if set(value)=={'item'}:raise ValueError('Projector/camera item references must be removed or baked before saving a portable material')
  return {k:remap(v,identities) for k,v in value.items()}
 if isinstance(value,list):return [remap(v,identities) for v in value]
 return value

def parameter_sets(settings):
 shader=settings.get('native_shader')
 if shader:yield settings.setdefault('native_parameters',{}),shader_library.catalog()[shader]['attributes']
 for key in ('node_graph','materialx_graph'):
  if settings.get(key):
   graph=settings[key];nodes.validate(graph)
   for node in graph['nodes'].values():yield node.setdefault('parameters',{}),nodes.specs(node['type'])
   for override in graph.get('overrides',[]):
    node=graph['nodes'][override['node']]
    yield override.setdefault('parameters',{}),nodes.specs(node['type'])

def files(settings,callback):
 for parameters,schema in parameter_sets(settings):
  for key,value in list(parameters.items()):
   spec=schema.get(key,{})
   if isinstance(value,str) and value and (key=='file' or 'FLAGS_FILENAME' in spec.get('flags','')):parameters[key]=callback(value)

def validate(data):
 if data.get('format')!=2 or not isinstance(data.get('materials'),dict) or not 1<=len(data['materials'])<=256:raise ValueError('Invalid material bundle')
 materials=data['materials'];root=data.get('root')
 if root not in materials:raise ValueError('Missing root material')
 done=set()
 def visit(identity,trail):
  if identity in trail or len(trail)>64:raise ValueError('Material dependency cycle or depth limit')
  if identity in done:return
  if identity not in materials:raise ValueError('Missing material dependency: '+identity)
  settings=materials[identity]['settings']
  remap(settings,{key:key for key in materials})
  if not settings.get('native_shader') and not settings.get('node_graph') and not settings.get('materialx_graph'):raise ValueError('Bundle requires native material types or graphs')
  for parameters,schema in parameter_sets(settings):
   for key,value in parameters.items():
    if key not in schema:raise ValueError('Unknown parameter: '+key)
    shader_library.typed(value,schema[key])
  for dependency in refs(settings):visit(dependency,trail+(identity,))
  done.add(identity)
 for identity in materials:visit(identity,())
 return data

def save(root_id,lookup,destination):
 """lookup returns name/settings; the destination must be a new folder."""
 destination=Path(destination).resolve()
 if destination.exists():raise ValueError('Choose a new material bundle folder')
 materials={};identities={}
 allowed={'shader','native_shader','native_parameters','node_graph','node_override','materialx_graph','materialx_override','thin_geometry','subsurface_model','anisotropy_angle','sss_input_normal','sss_resolve_self_intersections'}
 def collect(identity,trail=()):
  if identity in trail:raise ValueError('Material reference cycle')
  if len(trail)>64:raise ValueError('Material dependency depth exceeds 64')
  if identity in identities:return
  if len(identities)>=256:raise ValueError('Material bundle exceeds 256 dependencies')
  entry=lookup(identity);key='material'+str(len(identities));identities[identity]=key
  settings={k:copy.deepcopy(v) for k,v in entry['settings'].items() if k in allowed}
  materials[key]={'name':entry['name'],'settings':settings}
  for child in refs(settings):collect(child,trail+(identity,))
 collect(root_id)
 for entry in materials.values():entry['settings']=remap(entry['settings'],identities)
 data=validate({'format':2,'root':identities[root_id],'materials':materials,'assets':[]})
 destination.parent.mkdir(parents=True,exist_ok=True)
 staging=destination.with_name(destination.name+'.partial-'+uuid.uuid4().hex);staging.mkdir();(staging/'assets').mkdir()
 copied={}
 def collect_file(original):
  if original in copied:return copied[original]
  from .textures import source_tiles
  tiles=source_tiles(original)
  if not tiles:raise ValueError('Missing material asset: '+original)
  token=hashlib.sha256(str(Path(original).resolve()).encode()).hexdigest()[:20]
  folder=staging/'assets'/token;folder.mkdir()
  for source in tiles.values():
   source=Path(source);target=folder/source.name;shutil.copy2(str(source),str(target))
   checksum=digest(target)
   if checksum!=digest(source):raise ValueError('Asset changed during collection: '+str(source))
   data['assets'].append({'file':target.relative_to(staging).as_posix(),'sha256':checksum})
  copied[original]=(folder/Path(original).name).relative_to(staging).as_posix();return copied[original]
 for entry in materials.values():files(entry['settings'],collect_file)
 (staging/'material.moonmat.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
 (staging/'README.txt').write_text('Assign material.moonmat.json through MoonRay Asset Library. All graph and referenced-material assets are relative to this folder. Native Modo Shader Tree texture layers outside these graphs are not part of this bundle. Source asset licenses still apply.\n',encoding='utf-8')
 staging.rename(destination);return destination/'material.moonmat.json'

def load(path):
 path=Path(path).resolve();root=path.parent
 if path.stat().st_size>16*1024*1024:raise ValueError('Material bundle manifest exceeds 16 MB')
 data=validate(json.loads(path.read_text(encoding='utf-8')))
 for entry in data.get('assets',[]):
  asset=(root/entry['file']).resolve();asset.relative_to(root)
  if digest(asset)!=entry['sha256']:raise ValueError('Material asset changed: '+entry['file'])
 declared={entry['file'] for entry in data.get('assets',[])}
 def resolve(value):
  asset=(root/value).resolve();asset.relative_to(root)
  from .textures import source_tiles
  tiles=source_tiles(str(asset))
  if not tiles or any(Path(v).resolve().relative_to(root).as_posix() not in declared for v in tiles.values()):raise ValueError('Unlisted or missing material asset: '+value)
  return str(asset)
 for entry in data['materials'].values():files(entry['settings'],resolve)
 return data

def assign(path):
 # Called inside an undoable Modo command. Validate all data/assets before mutation.
 from . import materials,properties
 import modo
 data=load(path);scene=modo.Scene();root=data['root']
 root_item=materials.assign(data['materials'][root]['settings'].get('native_shader'))
 created={root:root_item};mask=None
 for key,entry in data['materials'].items():
  if key==root:continue
  if mask is None:
   mask=scene.addItem('mask',name='MoonRay library dependencies');mask.setParent(scene.renderItem,0)
   mask.channel('ptyp').set('Material');mask.channel('ptag').set('MoonRay_Unassigned_'+uuid.uuid4().hex)
  item=scene.addItem('advancedMaterial',name=entry['name']);item.setParent(mask,0);created[key]=item
 identities={key:item.id for key,item in created.items()}
 for key,item in created.items():
  properties.write(item,remap(data['materials'][key]['settings'],identities));item.name=data['materials'][key]['name']
 scene.select(root_item)
