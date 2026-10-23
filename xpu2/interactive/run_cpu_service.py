"""Private real native CPU background execution and latest-epoch checks."""
import argparse,json,subprocess
from pathlib import Path
from native_build import build
from fallback import environment
from reference_runtime import sha,verify
from run_m0 import guard
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','runtime','baseline','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();source=a.source.resolve();rt=a.runtime.resolve();baseline=a.baseline.resolve();out=a.output.resolve()
 if out.is_relative_to(source) or out.is_relative_to(rt):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','scope':'experimental CPU service; no GPU or host UI latency qualification'}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()))
  original=json.loads((baseline/'report.json').read_text());assert original['status']=='passed'
  gates={'pending_requests':4,'queued_results':2,'retirement_slots':4,'rgba':'exact against canonical CPU material image','scene_supersession':'only latest ticket may be returned','failure':'no pixels','tier':'D; unqualified','handoffs':1000000}
  (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8');report['gates']=gates
  files=[HERE/n for n in ('spsc_ring.h','cpu_service.h','cpu_service_probe.cc','run_cpu_service.py','cpu_lane.h','cpu_scene.h','native_build.py','canonical_session.h','surface_core.h','sample_tree.h','sample_stream.h','path_stage.h','routing_index.h','snapshot_budget.h')]+[baseline/n for n in ('report.json','initial/scene.rdlb','material.rgba')]+[ROOT/'xpu2'/n for n in ('rdl_scene_index.h','rdl_replica.h','indexed_scene.h','persistent_map.h')]
  held={str(f):sha(f) for f in files};report['source_hashes']=held
  exe,meta=build(source,HERE/'cpu_service_probe.cc',out/'build',[rt/'libembree4.dll']);report['build']=meta
  run=subprocess.run([str(exe),str(baseline/'initial/scene.rdlb'),str(rt),str(out)],cwd=out,env=environment(rt,out),capture_output=True,text=True,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'probe.log').write_text(run.stdout+run.stderr,encoding='utf-8')
  if run.returncode:raise RuntimeError('Service probe failed: '+run.stderr[-1200:])
  report['native']=json.loads(run.stdout)
  if report['native']['status']!='passed':raise RuntimeError('Native service checks failed')
  expected=(baseline/'material.rgba').read_bytes()
  for name in ('material','recovered'):
   if (out/(name+'.rgba')).read_bytes()!=expected:raise RuntimeError(name+' image differs')
  report['image_sha256']=sha(out/'material.rgba')
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
 except Exception as error:report.update(status='failed',error=str(error))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','build')},indent=2),flush=True)
 return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
