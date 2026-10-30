"""Generate owned, reproducible larger fixtures inside the current native subset."""
import argparse,array,json,math
from pathlib import Path
from run_cpu_image import rdla
from run_material_progressive import call
from reference_repeatability import save
from reference_runtime import sha
import asset_snapshot
HERE=Path(__file__).resolve().parent
CASES={'gallery-dense':{'width':384,'height':288,'columns':8,'rows':8,'segments':64,'rings':32,'fine_panels':False},
       'workshop-detail':{'width':512,'height':384,'columns':16,'rows':8,'segments':32,'rings':16,'fine_panels':True}}
def texture(path,size,kind):
 # Floating linear RGB, deterministic patterns with low/high spatial frequencies.
 out=array.array('f')
 for y in range(size):
  for x in range(size):
   u=x/size;v=y/size
   if kind%4==0:
    a=.5+.25*math.sin(83*u+7*math.sin(17*v))+.12*math.sin(513*u+v*23)
   elif kind%4==1:
    row=y//32;brick=((x+(row%2)*32)//64)*73+row*29
    a=.09 if y%32<2 or (x+(row%2)*32)%64<2 else .35+(brick%43)/100
   elif kind%4==2:
    a=.25+.45*((x//8+y//8)%2)+.1*math.sin(7*u+31*v)
   else:
    h=((x*73856093)^(y*19349663)^(kind*83492791))&65535
    a=.35+.22*math.sin(18*u+15*v)+.15*h/65535
   tint=((.85,.58,.31),(.63,.71,.82),(.37,.79,.52),(.83,.41,.28))[kind%4]
   out.extend(max(.015,min(.95,a*t+.07)) for t in tint)
 with path.open('wb') as f:f.write(('PF\n%d %d\n-1.0\n'%(size,size)).encode());out.tofile(f)
def sphere(segments,rings):
 verts=[(0,0,1)];faces=[]
 for j in range(1,rings):
  a=math.pi*j/rings
  for k in range(segments):
   b=2*math.pi*k/segments;r=1+.035*math.sin(5*b)*math.sin(3*a)
   verts.append((r*math.sin(a)*math.cos(b),r*math.sin(a)*math.sin(b),r*math.cos(a)))
 bottom=len(verts);verts.append((0,0,-1))
 for k in range(segments):faces.append((0,1+k,1+(k+1)%segments))
 for j in range(rings-2):
  for k in range(segments):
   a=1+j*segments+k;b=1+j*segments+(k+1)%segments;c=a+segments;d=b+segments
   faces.extend(((a,c,b),(b,c,d)))
 start=1+(rings-2)*segments
 for k in range(segments):faces.append((bottom,start+(k+1)%segments,start+k))
 return verts,faces
def cube():
 v=[(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]
 quads=[(4,5,6,7),(1,0,3,2),(0,4,7,3),(5,1,2,6),(3,7,6,2),(0,1,5,4)]
 return v,[t for a,b,c,d in quads for t in ((a,b,c),(a,c,d))]
def scene(config,paths):
 text=rdla(0).split('UsdPreviewSurface')[0]
 text+='SceneVariables { ["image_width"]=%d, ["image_height"]=%d, ["pixel_samples"]=8, ["max_depth"]=0, ["max_diffuse_depth"]=0, ["russian_roulette_threshold"]=0.0, ["lights_visible_in_camera"]=false }\n'%(config['width'],config['height'])
 text+='PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0,0,1,0,0,0,0,1,0,0,0,14,1) }\n'
 for i,path in enumerate(paths):
  scale=.06 if config['fine_panels'] and i>=6 else 1.7+i*.23
  text+='ImageMap("/map%d") { ["texture"]=%s, ["scale"]=Vec2(%g,%g), ["offset"]=Vec2(%g,%g), ["gamma"]=0 }\n'%(i,json.dumps(path.as_posix()),scale,scale*.73,.13*i,.07*i)
 geometry=[];assign=[];stats={'meshes':0,'vertices':0,'triangles':0,'materials':0,'maps':8,'resolution':[config['width'],config['height']],'domain':'direct-only diffuse/emission, flat triangles, constant environment'}
 def mesh(v,t,material,transform=None):
  nonlocal text
  i=stats['meshes'];stats['meshes']+=1;stats['vertices']+=len(v);stats['triangles']+=len(t)
  vector=lambda v:'Vec3('+','.join(format(x,'.8g') for x in v)+')'
  text+='RdlMeshGeometry("/g%d") { ["vertex_list"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["is_subd"]=false, ["smooth_normal"]=false%s }\n'%(i,','.join(map(vector,v)),','.join('3' for _ in t),','.join(str(k) for tri in t for k in tri),(', ["node_xform"]=Mat4('+','.join(format(x,'.8g') for x in transform)+')') if transform else '')
  geometry.append('RdlMeshGeometry("/g%d")'%i);assign.append('{ RdlMeshGeometry("/g%d"), "", UsdPreviewSurface("/m%d"), LightSet("/lights") }'%(i,material))
 def material(i,mapid,tint=1,emit=False):
  nonlocal text
  stats['materials']+=1
  text+='UsdPreviewSurface("/m%d") { ["diffuseColor"]=bind(ImageMap("/map%d"),Rgb(%g,%g,%g)), ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0)%s }\n'%(i,mapid,.75*tint,.7*tint,.65*tint,(', ["emissiveColor"]=bind(ImageMap("/map%d"),Rgb(.02,.01,.005))'%mapid) if emit else '')
 # Filled back wall keeps alpha coverage controlled while geometry creates dense occlusion.
 room=[((-7,-5.5,-1.5),(7,-5.5,-1.5),(7,5.5,-1.5),(-7,5.5,-1.5)),
       ((-5.7,-4,2.5),(5.7,-4,2.5),(5.7,-4,-1.5),(-5.7,-4,-1.5)),
       ((-5.7,-4,2.5),(-5.7,-4,-1.5),(-5.7,4,-1.5),(-5.7,4,2.5)),
       ((5.7,-4,-1.5),(5.7,-4,2.5),(5.7,4,2.5),(5.7,4,-1.5))]
 for i,v in enumerate(room):material(i,i,1);mesh(v,[(0,1,2),(0,2,3)],i)
 sp=sphere(config['segments'],config['rings']);box=cube()
 for y in range(config['rows']):
  for x in range(config['columns']):
   k=y*config['columns']+x;i=k+4;is_box=config['fine_panels'] and k%5==0
   material(i,k%(6 if config['fine_panels'] else 8),.75+.24*((k*13)%17)/16,k%13==0)
   radius=.39 if not config['fine_panels'] else .23
   radius*=.87+.22*((k*7)%19)/18;angle=.19*(k%7);c=math.cos(angle);s=math.sin(angle)
   transform=[radius*c,0,-radius*s,0,0,radius*(1+.15*(k%3)),0,0,radius*s,0,radius*c,0,(x-(config['columns']-1)/2)*9.1/config['columns'],(y-3.5)*.92,.15+.25*math.sin(k*1.3),1]
   v,t=box if is_box else sp;mesh(v,t,i,transform)
 if config['fine_panels']:
  for panel in range(2):
   i=4+config['rows']*config['columns']+panel;material(i,6+panel,1)
   x=-4.6+panel*1.15;mesh([(x,-2.8,1.4),(x+.95,-2.8,1.4),(x+.95,2.8,1.4),(x,2.8,1.4)],[(0,1,2),(0,2,3)],i)
 text+='GeometrySet("/geometry") { '+','.join(geometry)+' }\nLayer("/layer") { '+','.join(assign)+' }\nSceneVariables { ["layer"]=Layer("/layer") }\n'
 text+='RenderOutput("/beauty") { ["file_name"]="beauty.exr", ["result"]=0, ["channel_format"]=0, ["compression"]=1 }\nRenderOutput("/alpha") { ["file_name"]="beauty.exr", ["result"]=1, ["channel_format"]=0, ["compression"]=1 }\n'
 return text,stats
def main():
 p=argparse.ArgumentParser()
 for n in ('runtime','build','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();rt=a.runtime.resolve();out=a.output.resolve();out.mkdir(exist_ok=False);b=json.loads(a.build.read_text());helper=Path(b['helper']);assert sha(helper)==b['asset_build']['executable_sha256']
 report={'status':'incomplete','cases':{},'generator_sha256':sha(Path(__file__))};save(out/'protocol.json',CASES)
 for name,config in CASES.items():
  d=out/name;d.mkdir();assets=d/'textures';assets.mkdir();paths=[]
  for i in range(8):
   size=1024 if config['fine_panels'] and i>=6 else 512;pfm=assets/f'map{i}.pfm';tx=assets/f'map{i}.tx';texture(pfm,size,i);call([rt/'oiiotool.exe',pfm,'-d','float','--otex',tx],rt,assets,f'make{i}');paths.append(tx)
  text,stats=scene(config,paths);(d/'input.rdla').write_text(text,encoding='utf-8');stats['scenes']={}
  for grid in (8,32):
   g=d/f'grid-{grid}';g.mkdir();source=g/'input.rdla';source.write_text(text+f'\nSceneVariables {{ ["pixel_samples"]={grid} }}\n',encoding='utf-8')
   call([rt/'rdl2_convert.exe','-i',source,'-o',g/'input.rdlb'],rt,g,'convert',timeout=300);asset_snapshot.freeze(g/'input.rdlb',helper,rt,g/'frozen',g);stats['scenes'][str(grid)]=str(asset_snapshot.verify(g/'frozen/manifest.json'))
  stats['texture_files']=[{'path':str(v),'bytes':v.stat().st_size,'sha256':sha(v)} for v in paths];report['cases'][name]=stats;save(out/'report.json',report);print(name,{k:v for k,v in stats.items() if k not in ('texture_files','scenes')},flush=True)
 report['status']='prepared';save(out/'report.json',report)
if __name__=='__main__':main()
