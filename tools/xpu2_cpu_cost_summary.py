"""Collect completed fixtures, preserving interrupted reports and exact source snapshots."""
import argparse,json
from pathlib import Path
from xpu2_cpu_cost_analyze import analyze
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file

def main():
 p=argparse.ArgumentParser();p.add_argument('--first',type=Path,required=True);p.add_argument('--completed',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 first=json.loads(a.first.read_text());last=json.loads(a.completed.read_text())
 if last['status']!='passed':raise ValueError('Remaining matrix incomplete')
 # Only the two fully bracketed fixtures from the interrupted first matrix.
 earlier=[r for r in first['runs'] if r['fixture'] in ('diffuse','layered')]
 for fixture in ('diffuse','layered'):
  if {r['label'] for r in earlier if r['fixture']==fixture}!={'reference','off_before','sample64','sample16','off_after'}:raise ValueError('Incomplete early fixture')
 for f,h in first['source_hashes'].items():
  target=Path(f)
  if digest_file(target)!=h:
   alternate={'native_build.py':'native_build_at_capture.py','xpu2_cpu_cost_probe.py':'probe_at_capture.py'}.get(target.name)
   if not alternate or digest_file(a.first.parent/alternate)!=h:raise ValueError('Early source drift '+f)
 for f,h in last['source_hashes'].items():
  target=Path(f)
  if digest_file(target)!=h:
   target=a.completed.parent/'probe_at_capture.py' if target.name=='xpu2_cpu_cost_probe.py' else target
   if digest_file(target)!=h:raise ValueError('Final source drift '+f)
 for row in earlier:row['artifact_folder']=str(a.first.resolve().parent/(row['fixture']+'-'+row['label']))
 rows=earlier+last['runs']
 for r in rows:
  if not r['execution']['passed'] or r['comparison']['exactly_different_pixels']:raise ValueError('Unqualified image')
 merged={'status':'passed','runs':rows}
 result=analyze(merged,json.loads((ROOT/'xpu2/exclusive-profile-20261019.json').read_text()))
 result['validation']={'accepted_frames':len(rows),'all_float32_rgba_exact':True,'native_workers':1,'xpu2_gpu_shading_enabled':False,
  'sampled_scope_contract':'O3 native fast-math accounting passed','process_guard':'Positive active-renderer snapshot checked; final continuation uses process snapshots before/during/after each frame.',
  'interruptions':[first.get('error'),last.get('resumed_from',{}).get('reason')],
  'excluded':'The early extra textured reference and completed many-light sample whose WMI boundary query timed out are not used; the latter was rerendered. Original interrupted reports are retained.'}
 result['artifacts']={}
 def artifact(path):
  path=Path(path).resolve();result['artifacts'][str(path.relative_to(ROOT))]=digest_file(path)
 for path in (a.first,a.completed,ROOT/'test-results/xpu2-cpu-cost-full-run/report.json',ROOT/'test-results/xpu2-cpu-cost-run/probe_at_capture.py',ROOT/'test-results/xpu2-cpu-cost-run/native_build_at_capture.py',ROOT/'test-results/xpu2-cpu-cost-full-run/probe_at_capture.py',ROOT/'test-results/xpu2-cpu-cost-full-finish/probe_at_capture.py',ROOT/'test-results/xpu2-cpu-cost-build/report.json',ROOT/'test-results/xpu2-cpu-cost-full-build/report.json'):artifact(path)
 for r in rows:
  folder=Path(r['artifact_folder'])
  for name in ('cpu.csv','stats.csv','beauty.exr','render.log'):
   if (folder/name).exists():artifact(folder/name)
 for item in (first,last):
  for v in item['fixtures'].values():
   if digest_file(Path(v['path']))!=v['sha256']:raise ValueError('Scene drift')
   artifact(v['path'])
  for f,h in item.get('asset_hashes',{}).items():
   if digest_file(Path(f))!=h:raise ValueError('Asset drift')
   artifact(f)
 a.output.write_text(json.dumps(result,indent=2)+'\n');print('wrote',a.output)
if __name__=='__main__':main()
