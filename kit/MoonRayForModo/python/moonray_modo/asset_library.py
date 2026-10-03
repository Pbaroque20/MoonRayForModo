"""Local asset catalog. Browsing never evaluates RDLA, MaterialX or scene files."""
import json,os
from pathlib import Path
from . import shader_library
CATEGORIES={'.rdla':'Example scenes','.rdlb':'Example scenes','.lxo':'Modo scenes','.usd':'USD / models','.usda':'USD / models','.usdc':'USD / models','.obj':'Models','.fbx':'Models','.abc':'Models','.vdb':'Volumes','.mtlx':'MaterialX','.exr':'Textures / environments','.hdr':'Textures / environments','.tx':'Textures / environments','.png':'Textures / environments','.jpg':'Textures / environments','.jpeg':'Textures / environments','.tif':'Textures / environments','.tiff':'Textures / environments','.cube':'Color / LUT','.3dl':'Color / LUT'}
SOURCE='https://docs.openmoonray.org/getting-started/test-scenes/'
def bundled():return Path(__file__).resolve().parents[2]/'assets/library'
def builtins():
 rows=[]
 for shader,schema in sorted(shader_library.catalog().items()):
  rows.append({'name':shader,'category':'Material types','shader':shader,'parameters':{},'source':'MoonRay / MoonShine','license':'Apache-2.0','description':'Native material defaults. Layer/mix shaders require input materials; hair shaders require strands.\n'+str(schema.get('comment',''))})
 from . import map_library
 for kind,schema in sorted(map_library.catalog().items()):
  rows.append({'name':kind,'category':'Texture / normal node types','source':'MoonRay / MoonShine','license':'Apache-2.0','description':'Available in the node editor. Parameters: '+', '.join(schema['attributes'])})
 for name,description,license in [('MoonRay Widget','DreamWorks shader ball in USD formats.','ASWF Digital Assets License 1.1'),('MoonRay example scenes','Scenes curated by Benedikt Bitterli. Preserve each scene\'s own license and dependencies.','See individual scene credits'),('ALab 2.2.0','Netflix Animation Studios production scene, including 4K textures. Large optional download.','ASWF Digital Assets License 1.1'),('MoonRay USD sphere','Simple DreamWorks Hydra test scene.','ASWF Digital Assets License 1.1')]:
  rows.append({'name':name,'category':'Official downloads','url':SOURCE,'source':SOURCE,'license':license,'description':description+' Not bundled. Download from the source page, extract, then add its folder to this library.'})
 return rows

def scan(roots):
 """Yield bounded batches; caller schedules this iterator between UI events."""
 seen=set();batch=[];count=0
 for root in roots:
  root=Path(root)
  if not root.is_dir():continue
  for directory,dirs,files in os.walk(str(root),followlinks=False):
   dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not Path(directory,d).is_symlink())
   for name in sorted(files):
    path=Path(directory,name);ext=path.suffix.lower();count+=1
    if not path.is_symlink() and (ext in CATEGORIES or name.endswith('.moonmat.json')):
     identity=os.path.normcase(str(path.absolute()))
     if identity not in seen:
      seen.add(identity)
      batch.append({'name':path.stem,'category':'Saved materials' if name.endswith('.moonmat.json') else CATEGORIES[ext],'path':str(path),'source':str(root),'license':'See accompanying LICENSE / credits','description':str(path.relative_to(root))})
    if count%256==0:yield batch;batch=[]
    if count>=100000:
     yield batch
     raise ValueError('Library scan limit reached (100,000 files). Add narrower asset folders.')
 if batch:yield batch

def read_preset(path):
 path=Path(path)
 if path.stat().st_size>1024*1024:raise ValueError('Material preset exceeds 1 MB')
 data=json.loads(path.read_text(encoding='utf-8'))
 if data.get('format')!=1:raise ValueError('Unsupported MoonRay material preset')
 shader=data.get('shader');parameters=shader_library.validate(shader,data.get('parameters',{}))
 # Cross-item references cannot be transferred without their dependency graph.
 for key,value in parameters.items():
  if shader_library.catalog()[shader]['attributes'][key]['type'].startswith('SceneObject') and value is not None:
   raise ValueError('Save self-contained materials; this preset contains scene-item references')
 return shader,parameters
