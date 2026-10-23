"""Separate long-frame diagnostic; fixed-64 benchmark remains unchanged."""
import argparse,json,time,traceback
from pathlib import Path
from reference_runtime import sha,verify
from reference_repeatability import values,save
from run_speed_comparison import metric,quality
from run_material_progressive import call
from run_m0 import guard
import asset_snapshot
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser()
 for n in ('runtime','build','gpu-build','benchmark','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();out=a.output.resolve();out.mkdir(exist_ok=False);rt=a.runtime.resolve()
 protocol=json.loads((HERE/'large-audit-protocol.json').read_text());save(out/'protocol.json',protocol)
 r={'status':'incomplete','production_qualified':False,'cases':{},'protocol':protocol}
 try:
  lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
  b=json.loads(a.build.read_text());g=json.loads(a.gpu_build.read_text());old=json.loads(a.benchmark.read_text());bench=Path(b['exe']);ptx=Path(g['ptx'])
  assert b['status']==g['status']=='passed' and sha(bench)==b['build']['executable_sha256'] and sha(ptx)==g['binary_hashes']['ptx']
  held={**b['source_hashes'],str(Path(__file__).resolve()):sha(Path(__file__))}
  assert all(sha(Path(k))==v for k,v in held.items())
  r.update(source_hashes=held,reference_identity=lock['identity'],benchmark_sha256=sha(a.benchmark),build_sha256=sha(a.build))
  for name,c in old['cases'].items():
   if 'converged_reference' not in c or '12' not in c['native']:continue
   folder=out/name;folder.mkdir();case=r['cases'][name]={};w,h=c['fixture']['resolution'];ref=values((a.benchmark.resolve().parent/name/'reference-1024/beauty.rgba').read_bytes())
   for grid in (8,32):
    d=folder/f'grid-{grid}';d.mkdir();scene=Path(c['fixture']['scenes'][str(grid)]);asset_snapshot.verify(scene.parent/'manifest.json')
    guard();data=json.loads(call([bench,scene,rt,ptx,scene.parent/'assets',d,12,1,3],rt,d,'audit',timeout=900));guard()
    row=data['runs'][0];raw=Path(row['raw_file']);row['raw_sha256']=sha(raw);row['error']=metric(values(raw.read_bytes()),ref,w,h)
    case[str(grid)]=data
    if grid==8:
     case['driver_output_unchanged']=row['raw_sha256']==c['native']['12']['runs'][0]['raw_sha256'];assert case['driver_output_unchanged'],'Diagnostic driver changed pixels'
    else:case['high_spp_quality_passed']=quality(row['error'])
    print(name,grid*grid,'spp',round(row['sampling_seconds'],3),'s','misses',row['texture_misses'],'migrated',row['migrated_paths'],'error',row['error'],flush=True);save(out/'report.json',r)
  assert all(sha(Path(k))==v for k,v in held.items());verify(rt,lock);guard();r['status']='completed'
 except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
 save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);return int(r['status']!='completed')
if __name__=='__main__':raise SystemExit(main())
