"""Private GPU mip filtering and continuation migration; correctness, not speed."""
import argparse,array,json,math
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from reference_runtime import sha,verify
from run_m0 import guard,standalone,image
from run_cpu_image import rdla,compare_fixture
from run_material_progressive import call
import asset_snapshot
HERE=Path(__file__).resolve().parent
GATES={'lookup_abs':5e-5,'native_image_abs':2e-5,'image_block_width':8,'image_alpha_error':.015,'image_max_pixel_error':.08,'image_max_block_mean_error':.015}
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--case',choices=['resident','level-zero','clamped-gamma','constant-level-zero'])
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete','scope':'opt-in planar textured diffuse/emission mixtures, software aniso4 mip filtering and bounded GPU-to-CPU whole-batch continuation migration; not general material or spec qualification','gates':GATES,'cases':{}}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()));(out/'frozen-gates.json').write_text(json.dumps(GATES,indent=2))
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('texture_migration_probe.cc','gpu_trace.cu','run_texture_migration.py','gpu_build.py','native_build.py')]
  held={str(f):sha(f) for f in files};report['source_hashes']=held
  ptx,report['cuda_build']=compile_ptx(src,out)
  inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  exe,report['native_build']=build(src,HERE/'texture_migration_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc])
  helper,report['asset_build']=build(src,HERE/'asset_scene.cc',out/'asset-build')
  for kind in ('float','uint8'):
   call([rt/'oiiotool.exe','--pattern','checker:width=16:height=16:color1=0.1,0.3,0.7:color2=0.9,0.6,0.2','256x256','3','-d',kind,'--otex',out/(kind+'.tx')],rt,out,'make-'+kind)
  call([rt/'oiiotool.exe','--pattern','constant:color=0.25,0.5,0.75','1x1','3','-d','float','--otex',out/'one.tx'],rt,out,'make-one')
  for name,kind,near,wrap,gamma in [('resident','float',16,True,0),('level-zero','float',.25,True,0),('clamped-gamma','uint8',.25,False,2),('constant-level-zero','float',.25,True,0)]:
   if a.case and name!=a.case:continue
   folder=out/name;folder.mkdir();text=rdla(0)+'\nSceneVariables { ["russian_roulette_threshold"]=0.0, ["lights_visible_in_camera"]=false }\n'
   for label,scale in [('far',16),('close',near)]:
    text+=f'ImageMap("/{label}") {{ ["texture"]={json.dumps((out/(kind+".tx")).as_posix())}, ["scale"]=Vec2({scale},{scale*.7}), ["offset"]=Vec2(0.23,-0.16), ["wrap_around"]={str(wrap).lower()}, ["gamma"]={gamma} }}\n'
   # Mixed untextured diffuse, textured diffuse and textured emission. Pixel 0
   # uses a texture, so the explicit migration validator can target it.
   if name=='constant-level-zero':text+=f'ImageMap("/close") {{ ["texture"]={json.dumps((out/"one.tx").as_posix())} }}\n'
   text+='UsdPreviewSurface("/m0") { ["diffuseColor"]=bind(ImageMap("/far"),Rgb(.7,.6,.5)) }\n'
   text+='UsdPreviewSurface("/m1") { ["emissiveColor"]=bind(ImageMap("/far"),Rgb(.12,.06,.03)) }\n'
   text+='UsdPreviewSurface("/m3") { ["diffuseColor"]=bind(ImageMap("/close"),Rgb(.7,.6,.5)) }\n'
   scene=folder/'input.rdla';scene.write_text(text,encoding='utf-8');call([rt/'rdl2_convert.exe','-i',scene,'-o',folder/'input.rdlb'],rt,folder,'convert')
   frozen=folder/'frozen';asset_snapshot.freeze(folder/'input.rdlb',helper,rt,frozen,folder);asset_snapshot.verify(frozen/'manifest.json')
   entry={'native':json.loads(call([exe,frozen/'scene.rdlb',rt,ptx,folder,frozen/'assets'],rt,folder,'native'))};report['cases'][name]=entry
   def raw(label):
    data=array.array('f');data.frombytes((folder/(label+'.rgba')).read_bytes());assert len(data)==64*48*4 and all(math.isfinite(v) for v in data);return data
   base=raw('oiio');entry['internal']={}
   for label in ('software','gpu-seeded-1','gpu-seeded-12','mixed-1','mixed-12','pressure','recovered'):
    values=raw(label);delta=max(abs(x-y) for x,y in zip(base,values));entry['internal'][label]=delta
    if delta>GATES['native_image_abs']:raise RuntimeError(f'{name}/{label} image disagreement: {delta}')
   if (folder/'gpu-seeded-1.rgba').read_bytes()!=(folder/'gpu-seeded-12.rgba').read_bytes():raise RuntimeError('Migration varies with worker count')
   if entry['native']['gpu-seeded-12']['gpu_samples']==0:raise RuntimeError('No samples completed on GPU')
   if name!='resident' and entry['native']['gpu-seeded-12']['texture_misses']==0:raise RuntimeError('No level-zero misses exercised')
   rendered=standalone(rt,frozen/'scene.rdlb',folder/'reference',1);ref=image(rt,folder/'reference');entry['reference']={'execution':rendered['execution'],'errors':compare_fixture(raw('mixed-12'),ref,GATES)}
   asset_snapshot.verify(frozen/'manifest.json');print('Passed GPU textures:',name,flush=True)
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
 except Exception as e:report.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','native_build','cuda_build','asset_build','cases')},indent=2),flush=True);return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
