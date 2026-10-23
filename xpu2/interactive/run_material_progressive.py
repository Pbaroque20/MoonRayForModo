"""Private image textures, emission and complete-sample progressive validation."""
import argparse,array,json,subprocess
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from fallback import environment
from reference_runtime import sha,verify
from run_m0 import guard,standalone,image
from run_cpu_image import rdla,compare_fixture
import asset_snapshot
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def call(args,rt,out,name,timeout=240):
 r=subprocess.run(list(map(str,args)),cwd=out,env=environment(rt,out),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/(name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
 if r.returncode:raise RuntimeError(name+' failed: '+r.stderr[-1400:])
 return r.stdout

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();out=a.output.resolve()
 if out.is_relative_to(src) or out.is_relative_to(rt):p.error('Isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','scope':'experimental planar diffuse/emissive ImageMap subset; no GPU texture or general native qualification','cases':{}}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()))
  gates=json.loads((HERE/'surface-gates.json').read_text());gates.update(progressive_max_difference=1e-6,cpu_threads_identical=True,texture_gpu_submissions=0,minimum_partial_images=1)
  (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8');report['gates']=gates
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('material_progressive_probe.cc','run_material_progressive.py','gpu_trace.cu','gpu_build.py','native_build.py','asset_snapshot.py','asset_scene.cc','run_cpu_image.py')]
  held={str(f):sha(f) for f in files};report['source_hashes']=held
  ptx,report['cuda_build']=compile_ptx(src,out)
  inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  exe,report['native_build']=build(src,HERE/'material_progressive_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc])
  helper,report['asset_build']=build(src,HERE/'asset_scene.cc',out/'asset-build')
  # Spatial pattern; generated once as an asset, then stored mips are copied verbatim.
  for label,kind in [('float','float'),('byte','uint8')]:
   call([rt/'oiiotool.exe','--pattern','checker:width=8:height=8:color1=0.1,0.3,0.7:color2=0.9,0.6,0.2','128x128','3','-d',kind,'--otex',out/(label+'.tx')],rt,out,'make-'+label)
  cases={
   'emission':'',
   'diffuse':'["scale"]=Vec2(1,1), ["offset"]=Vec2(0,0), ["mip_bias"]=0',
   'transformed':'["scale"]=Vec2(8,5), ["offset"]=Vec2(0.23,-0.16), ["mip_bias"]=1',
   'clamped':'["scale"]=Vec2(2,1), ["offset"]=Vec2(-0.4,0.3), ["wrap_around"]=false',
   'gamma':'["gamma"]=2',
   'emission-map':'["scale"]=Vec2(2,2), ["offset"]=Vec2(0.2,0.3)',
  }
  for name,attrs in cases.items():
   folder=out/name;folder.mkdir();text=rdla(0)+'\nSceneVariables { ["russian_roulette_threshold"]=0.0, ["lights_visible_in_camera"]=false }\n'
   if name=='emission':
    for i in range(4):text+=f'UsdPreviewSurface("/m{i}") {{ ["emissiveColor"]=Rgb(0.2,0.1,0.05) }}\n'
   else:
    tx=out/('byte.tx' if name=='gamma' else 'float.tx')
    text+=f'ImageMap("/texture") {{ ["texture"]={json.dumps(tx.as_posix())}, {attrs} }}\n'
    for i in range(4):
     key='emissiveColor' if name=='emission-map' else 'diffuseColor'
     # RDL bind keeps an explicit base multiplier; all colors are linear here.
     text+=f'UsdPreviewSurface("/m{i}") {{ ["{key}"]=bind(ImageMap("/texture"),Rgb(0.7,0.6,0.5)) }}\n'
   scene=folder/'input.rdla';scene.write_text(text,encoding='utf-8')
   call([rt/'rdl2_convert.exe','-i',scene,'-o',folder/'input.rdlb'],rt,folder,'convert')
   assets=folder/'frozen';asset_snapshot.freeze(folder/'input.rdlb',helper,rt,assets,folder);asset_snapshot.verify(assets/'manifest.json')
   native=json.loads(call([exe,assets/'scene.rdlb',rt,ptx,folder,assets/'assets' if name!='emission' else assets],rt,folder,'native'))
   entry={'native':native};report['cases'][name]=entry
   raw=(folder/'cpu1.rgba').read_bytes();assert raw==(folder/'cpu12.rgba').read_bytes(),'Texture worker variation'
   actual=array.array('f');actual.frombytes(raw)
   entry['internal']={}
   for label in ('mixed','progressive','recovered')+ (('post-failure',) if name=='emission' else ()):
    other=array.array('f');other.frombytes((folder/(label+'.rgba')).read_bytes());delta=max(abs(x-y) for x,y in zip(actual,other));entry['internal'][label]=delta
    if len(other)!=len(actual) or delta>gates['progressive_max_difference']:raise RuntimeError('Internal progressive/ownership mismatch')
   rendered=standalone(rt,assets/'scene.rdlb',folder/'reference',1);ref=image(rt,folder/'reference')
   entry['reference']={'execution':rendered['execution'],'errors':compare_fixture(actual,ref,gates)}
   if name!='emission' and native['gpu_samples']!=0:raise RuntimeError('Unqualified GPU texture sampled')
   asset_snapshot.verify(assets/'manifest.json');print('Passed material/progressive:',name,flush=True)
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
 except Exception as e:report.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','cuda_build','native_build','asset_build','cases')},indent=2),flush=True)
 return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
