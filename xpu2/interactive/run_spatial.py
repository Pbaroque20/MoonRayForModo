"""Private opt-in flat triangle, multi-bounce CPU/OptiX image and lifetime checks."""
import argparse,array,json,math
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from reference_runtime import sha,verify
from run_m0 import guard,standalone,image
from run_cpu_image import rdla,compare_fixture
from run_material_progressive import call
HERE=Path(__file__).resolve().parent

# Fixed before candidate execution. Exploratory admission, NOT full spec VER-2.
GATES=dict(image_block_width=8,image_max_pixel_error=.08,image_max_block_mean_error=.015,image_alpha_error=.015,mean_error=.003,
 cpu_gpu_max_error=.01,cpu_gpu_rmse=.0005,resumed_device_error=0,partial_sample_commits=0,per_slice_allocations=0,per_slice_sync=0)

def fixture(seed,depth,variant="room"):
 text=rdla(seed);text=text[:text.index('UsdPreviewSurface')]
 text+='SceneVariables { ["pixel_samples"]=32, ["max_depth"]=%d, ["max_diffuse_depth"]=%d, ["russian_roulette_threshold"]=0.0, ["lights_visible_in_camera"]=false }\n'%(depth,depth)
 # Open-front room. Each face is a separate flat triangle mesh; no smooth normals.
 faces=[((-2,-1.5,-1),(2,-1.5,-1),(2,1.5,-1),(-2,1.5,-1)),
        ((-2,-1.5,2),(2,-1.5,2),(2,-1.5,-1),(-2,-1.5,-1)),
        ((-2,1.5,-1),(2,1.5,-1),(2,1.5,2),(-2,1.5,2)),
        ((-2,-1.5,2),(-2,-1.5,-1),(-2,1.5,-1),(-2,1.5,2)),
        ((2,-1.5,-1),(2,-1.5,2),(2,1.5,2),(2,1.5,-1))]
 colors=[(.65,.65,.65),(.65,.65,.65),(.65,.65,.65),(.65,.08,.04),(.05,.15,.65)]
 # A rotated, nonuniformly scaled box inside the room exercises face normals,
 # secondary occlusion, arbitrary triangle planes and node transforms.
 box=[(-.5,-.5,-.5),(.5,-.5,-.5),(.5,.5,-.5),(-.5,.5,-.5),(-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)]
 indices=[(4,5,6,7),(1,0,3,2),(0,4,7,3),(5,1,2,6),(3,7,6,2),(0,1,5,4)]
 for inds in indices:faces.append(tuple(box[i] for i in inds));colors.append((.45,.55,.22))
 for i,(verts,color) in enumerate(zip(faces,colors)):
  text+='UsdPreviewSurface("/m%d") { ["diffuseColor"]=Rgb(%s), ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\n'%(i,','.join(map(str,color)))
  xform=', ["node_xform"]=Mat4(.8660254,0,-.5,0, 0,1.5,0,0, .4,0,.6928203,0, .25,-.7,.3,1)' if i>=5 else ''
  text+='RdlMeshGeometry("/g%d") { ["vertex_list"]={%s}, ["face_vertex_count"]={3,3}, ["vertices_by_index"]={0,1,2,0,2,3}, ["is_subd"]=false, ["smooth_normal"]=false%s }\n'%(i,','.join('Vec3(%s)'%','.join(map(str,v)) for v in verts),xform)
 text+='GeometrySet("/geometry") { '+','.join('RdlMeshGeometry("/g%d")'%i for i in range(len(faces)))+' }\n'
 text+='Layer("/layer") { '+','.join('{ RdlMeshGeometry("/g%d"), "", UsdPreviewSurface("/m%d"), LightSet("/lights") }'%(i,i) for i in range(len(faces)))+' }\n'
 text+='SceneVariables { ["layer"]=Layer("/layer") }\n'
 text+='RenderOutput("/beauty") { ["file_name"]="beauty.exr", ["result"]=0, ["channel_format"]=0, ["compression"]=1 }\nRenderOutput("/alpha") { ["file_name"]="beauty.exr", ["result"]=1, ["channel_format"]=0, ["compression"]=1 }\n'
 if variant=='zero-plane':
  text+='PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,5,1) }\n'
  for i in range(len(faces)):
   transform='1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,1,1' if i<5 else '.8660254,0,-.5,0, 0,1.5,0,0, .4,0,.6928203,0, .25,-.7,1.3,1'
   text+='RdlMeshGeometry("/g%d") { ["node_xform"]=Mat4(%s) }\n'%(i,transform)
 if variant=='emission':text+='UsdPreviewSurface("/m0") { ["emissiveColor"]=Rgb(0.1,0.03,0.06) }\n'
 return text

def raw(file):
 a=array.array('f');a.frombytes(file.read_bytes());return a

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('source','runtime','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();out=a.output.resolve()
 if out.is_relative_to(src) or out.is_relative_to(rt):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);r={'status':'incomplete','scope':'bounded opaque flat triangle diffuse chains, 64x48; not full material, geometry or statistical production qualification','gates':GATES,'cases':{}}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()))
  (out/'frozen-gates.json').write_text(json.dumps(GATES,indent=2),encoding='utf-8')
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('spatial_probe.cc','run_spatial.py','gpu_trace.cu','gpu_build.py','native_build.py','run_cpu_image.py','run_material_progressive.py')]
  held={str(f):sha(f) for f in files};r['source_hashes']=held
  ptx,r['cuda_build']=compile_ptx(src,out)
  inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  exe,r['native_build']=build(src,HERE/'spatial_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc])
  for seed,depth,variant in ((0,0,'room'),(0,2,'room'),(17,2,'room'),(59,2,'room'),(0,2,'zero-plane'),(59,7,'emission')):
   key=f'f{seed}-d{depth}'+('' if variant=='room' else '-'+variant);folder=out/key;folder.mkdir();scene=folder/'input.rdla';scene.write_text(fixture(seed,depth,variant),encoding='utf-8')
   call([rt/'rdl2_convert.exe','-i',scene,'-o',folder/'input.rdlb'],rt,folder,'convert')
   e={};r['cases'][key]=e
   e['native']=json.loads(call([exe,folder/'input.rdlb',rt,ptx,folder],rt,folder,'native',timeout=360))
   cp,gp=raw(folder/'cpu.rgba'),raw(folder/'gpu.rgba');diff=[abs(x-y) for x,y in zip(cp,gp)]
   e['cpu_gpu']={'max':max(diff),'rmse':math.sqrt(sum(x*x for x in diff)/len(diff))}
   assert e['cpu_gpu']['max']<=GATES['cpu_gpu_max_error'] and e['cpu_gpu']['rmse']<=GATES['cpu_gpu_rmse'],'CPU/GPU discrepancy'
   rendered=standalone(rt,folder/'canonical/scene.rdlb',folder/'reference',1);ref=image(rt,folder/'reference')
   e['reference']={'execution':rendered['execution'],'cpu':compare_fixture(cp,ref,GATES),'gpu':compare_fixture(gp,ref,GATES)}
   for backend in ('cpu','gpu'):
    assert max(abs(v['mean']) for v in e['reference'][backend].values())<=GATES['mean_error'],'Mean bias gate'
   print('Passed spatial image and continuation:',key,flush=True)
  direct=raw(out/'f0-d0/cpu.rgba');indirect=raw(out/'f0-d2/cpu.rgba');r['indirect_mean_increase']=sum(indirect[i]-direct[i] for i in range(len(direct)) if i%4<3)/(64*48*3)
  assert r['indirect_mean_increase']>.01,'No visible indirect contribution'
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));r['status']='passed'
 except Exception as e:r.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in r.items() if k not in ('source_hashes','cuda_build','native_build','cases')},indent=2),flush=True)
 return int(r['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
