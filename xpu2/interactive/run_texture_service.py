"""Private textured background service and existing spatial/planar regressions."""
import argparse,json
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from reference_runtime import sha,verify
from run_m0 import guard
from run_material_progressive import call
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('source','runtime','baseline','planar','textures','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();planar=a.planar.resolve();textures=a.textures.resolve();out=a.output.resolve()
 if any(out.is_relative_to(x) for x in (src,rt,base,planar)):p.error('Fresh output required')
 out.mkdir(parents=True,exist_ok=False);r={'status':'incomplete','scope':'private GPU texture-migration background service plus existing spatial/planar regression; no speed qualification','cases':{}}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()))
  assert json.loads((base/'report.json').read_text())['status']=='passed'
  gates={'resumed_planar_bytes':'identical frozen native CPU','spatial_service':'identical device-owned reference pixels','stale_or_error_pixels':0,'created_joined_workers':12,'native_qualified':False}
  (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8');r['gates']=gates
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('texture_service_probe.cc','spatial_service_probe.cc','deadline_probe.cc','run_texture_service.py','gpu_trace.cu','gpu_build.py','native_build.py')]+[base/'report.json',planar/'report.json']
  held={str(f):sha(f) for f in files};r['source_hashes']=held
  ptx,r['cuda_build']=compile_ptx(src,out);inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  for name,unit in [('textures','texture_service_probe.cc'),('service','spatial_service_probe.cc'),('planar','deadline_probe.cc')]:
   exe,meta=build(src,HERE/unit,out/(name+'-build'),[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(x) for x in inc]);r[name+'_build']=meta
   cases=[('spatial',base/'f0-d2/input.rdlb',base)] if name=='service' else [(c,planar/c/'frozen/scene.rdlb',planar/c/'frozen' if c=='emission' else planar/c/'frozen/assets') for c in ('emission','transformed','gamma','emission-map')]
   if name=='textures':cases=[('textures',textures/'level-zero/frozen/scene.rdlb',textures/'level-zero/frozen/assets')]
   for case,scene,assets in cases:
    folder=out/case;folder.mkdir();r['cases'][case]=json.loads(call([exe,scene,rt,ptx,folder,assets],rt,folder,'native',timeout=360))
    if name=='textures':assert (folder/'final.rgba').read_bytes()==(textures/'level-zero/mixed-12.rgba').read_bytes(),'Texture service golden image mismatch'
    if name=='planar':
     expected=(planar/case/'cpu1.rgba').read_bytes()
     for f in folder.glob('*.rgba'):assert f.read_bytes()==expected,'Planar regression: '+str(f)
    print('Passed service/regression:',case,flush=True)
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));r['status']='passed'
 except Exception as e:r.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in r.items() if not k.endswith('build') and k!='source_hashes'},indent=2),flush=True)
 return int(r['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
