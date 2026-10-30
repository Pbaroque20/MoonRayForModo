"""Private GPU mip filtering and continuation migration; correctness, not speed."""
import argparse,array,json,math
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from reference_runtime import sha,verify
from run_m0 import guard,standalone,image
from run_cpu_image import rdla,compare_fixture
from run_spatial import fixture
from run_material_progressive import call
import asset_snapshot
HERE=Path(__file__).resolve().parent
GATES={'lookup_abs':5e-5,'native_image_abs':.002,'image_block_width':8,'image_alpha_error':.015,'image_max_pixel_error':.08,'image_max_block_mean_error':.015}
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--reuse-build',type=Path)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete','scope':'opt-in direct-only 3D textured diffuse/emission, shared primary derivatives, OptiX/Embree and safe texture migration; secondary textured transport explicitly rejected','gates':GATES,'cases':{}}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()));(out/'frozen-gates.json').write_text(json.dumps(GATES,indent=2))
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('spatial_texture_probe.cc','gpu_trace.cu','run_spatial_textures.py','gpu_build.py','native_build.py')]
  held={str(f):sha(f) for f in files};report['source_hashes']=held
  if a.reuse_build:
   previous=a.reuse_build.resolve();old=json.loads((previous/'report.json').read_text())
   compiled=[f for f in files if f.suffix=='.h' or f.name in ('spatial_texture_probe.cc','gpu_trace.cu','gpu_build.py','native_build.py')]
   if any(old['source_hashes'].get(str(f))!=sha(f) for f in compiled):raise RuntimeError('Reused build source drift')
   exe=previous/'build/probe.exe';helper=previous/'asset-build/probe.exe';ptx=previous/'gpu_trace.ptx'
   assert sha(exe)==old['native_build']['executable_sha256'] and sha(helper)==old['asset_build']['executable_sha256'] and sha(ptx)==old['cuda_build']['ptx_sha256']
   for key in ('cuda_build','native_build','asset_build'):report[key]=old[key]
   report['verified_reused_build']=str(previous)
  else:
   ptx,report['cuda_build']=compile_ptx(src,out)
   inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
   exe,report['native_build']=build(src,HERE/'spatial_texture_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc])
   helper,report['asset_build']=build(src,HERE/'asset_scene.cc',out/'asset-build')
  for kind in ('float','uint8'):
   call([rt/'oiiotool.exe','--pattern','checker:width=16:height=16:color1=0.1,0.3,0.7:color2=0.9,0.6,0.2','256x256','3','-d',kind,'--otex',out/(kind+'.tx')],rt,out,'make-'+kind)
  for name,seed,near in [('room-resident',0,8),('room-close',17,.125)]:
   folder=out/name;folder.mkdir();text=fixture(seed,0)
   for label,scale in [('far',8),('close',near)]:
    text+=f'ImageMap("/{label}") {{ ["texture"]={json.dumps((out/"float.tx").as_posix())}, ["scale"]=Vec2({scale},{scale*.7}), ["offset"]=Vec2(0.23,-0.16) }}\n'
   for i in range(11):
    if i==2:continue
    map_name='far' if i<5 else 'close'
    text+=f'UsdPreviewSurface("/m{i}") {{ ["diffuseColor"]=bind(ImageMap("/{map_name}"),Rgb(.7,.6,.5)) }}\n'
   text+='UsdPreviewSurface("/m0") { ["emissiveColor"]=bind(ImageMap("/far"),Rgb(.06,.03,.015)) }\n'
   scene=folder/'input.rdla';scene.write_text(text,encoding='utf-8');call([rt/'rdl2_convert.exe','-i',scene,'-o',folder/'input.rdlb'],rt,folder,'convert')
   frozen=folder/'frozen';asset_snapshot.freeze(folder/'input.rdlb',helper,rt,frozen,folder);asset_snapshot.verify(frozen/'manifest.json')
   entry={'native':json.loads(call([exe,frozen/'scene.rdlb',rt,ptx,folder,frozen/'assets'],rt,folder,'native'))};report['cases'][name]=entry
   def raw(label):
    data=array.array('f');data.frombytes((folder/(label+'.rgba')).read_bytes());assert len(data)==64*48*4 and all(math.isfinite(v) for v in data);return data
   base=raw('cpu-control');entry['internal']={}
   for label in ('software','gpu-seeded-1','gpu-seeded-12','mixed-1','mixed-12','pressure','recovered'):
    values=raw(label);delta=max(abs(x-y) for x,y in zip(base,values));entry['internal'][label]=delta
    if delta>GATES['native_image_abs']:raise RuntimeError(f'{name}/{label} image disagreement: {delta}')
   if (folder/'gpu-seeded-1.rgba').read_bytes()!=(folder/'gpu-seeded-12.rgba').read_bytes():raise RuntimeError('Migration varies with worker count')
   if entry['native']['gpu-seeded-12']['gpu_samples']==0:raise RuntimeError('No samples completed on GPU')
   if name=='room-close' and entry['native']['gpu-seeded-12']['texture_misses']==0:raise RuntimeError('No level-zero misses exercised')
   rendered=standalone(rt,frozen/'scene.rdlb',folder/'reference',1);ref=image(rt,folder/'reference');entry['reference']={'execution':rendered['execution'],'errors':compare_fixture(raw('mixed-12'),ref,GATES)}
   asset_snapshot.verify(frozen/'manifest.json');print('Passed spatial GPU textures:',name,flush=True)
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
 except Exception as e:report.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','native_build','cuda_build','asset_build','cases')},indent=2),flush=True);return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
