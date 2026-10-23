"""Private shader-boundary experiment; all candidate sources are isolated snapshots."""
import json,shutil,time,traceback,subprocess,statistics,re
from pathlib import Path
import gpu_build
from reference_runtime import sha,verify
from reference_repeatability import save
from run_m0 import guard
from fallback import environment
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TR=ROOT/'test-results';OUT=TR/'interactive-shader-boundaries-20261022';OUT.mkdir(exist_ok=False)
protocol={'quality':'float32 RGBA bytes identical to existing corrected-ray images; no precision, filtering, sampling, or hit-test changes','cold':'private initially empty OptiX cache per candidate, OS file cache not purged','screen':'baseline plus three function-boundary candidates; gallery 12 workers, one warmup plus two renders','final_gates':'cold module median at least 20% lower; warm render median <=1.05x current baseline at 1 and 12 threads on both large scenes; exact ownership and recovery images','baseline':'interactive-prototype-build-20261022startup; material noinline already enabled'}
save(OUT/'protocol.json',protocol);r={'status':'incomplete','protocol':protocol,'variants':{}}
try:
 guard();rt=TR/'interactive-reference-042';src=Path(__import__('os').environ['XPU2_TOOLCHAIN_ROOT']);verify(rt,json.loads((HERE/'reference-lock.json').read_text()),4)
 snapshot=OUT/'before';snapshot.mkdir();files=[p for p in HERE.iterdir() if p.suffix in ('.h','.cc','.cu','.py','.ps1')]
 for p in files:shutil.copy2(p,snapshot/p.name)
 held={p.name:sha(p) for p in files};save(snapshot/'manifest.json',held)
 host=json.loads((TR/'interactive-startup-candidate-build-20261022/build.json').read_text());assert sha(Path(host['exe']))==host['build']['executable_sha256']
 base=json.loads((TR/'interactive-prototype-build-20261022startup/build.json').read_text());r['host_exe_sha256']=sha(Path(host['exe']))
 r['variants']['baseline']={'ptx':base['ptx'],'ptx_sha256':sha(Path(base['ptx'])),'source_snapshot':str(snapshot)}
 for label in ('sample-call','step-call','sample-step-call'):
  folder=OUT/label;folder.mkdir();source=folder/'source';source.mkdir()
  for p in snapshot.iterdir():
   if p.suffix in ('.h','.cu'):shutil.copy2(p,source/p.name)
  if 'sample' in label:
   p=source/'sample_stream.h';s=p.read_text(encoding='utf-8');needle='X2_HD inline float draw(';assert s.count(needle)==1;s=s.replace(needle,'// Keep one GPU sampler body; CPU inline behavior and arithmetic are unchanged.\n#if defined(__CUDACC__)\n__noinline__\n#endif\n'+needle);p.write_text(s,encoding='utf-8')
  if 'step' in label:
   p=source/'resume_core.h';s=p.read_text(encoding='utf-8');needle='template<class Backend>X2_HD inline void step(';assert s.count(needle)==1;s=s.replace(needle,'template<class Backend>\n#if defined(__CUDACC__)\n__noinline__\n#endif\nX2_HD inline void step(');p.write_text(s,encoding='utf-8')
  gpu_build.HERE=source;t=time.perf_counter();ptx,build=gpu_build.compile_ptx(src,folder);row={'status':'passed','ptx':str(ptx),'build':build,'ptx_sha256':sha(ptx),'ptx_bytes':ptx.stat().st_size,'nvrtc_seconds':time.perf_counter()-t,'source_hashes':{str(p):sha(p) for p in source.iterdir()}};save(folder/'build.json',row);r['variants'][label]=row;print(label,'ptx bytes',row['ptx_bytes'],flush=True)
 f=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text())['cases']['gallery-dense'];scene=Path(f['scenes']['8']);expected=json.loads((TR/'interactive-ray-hit-benchmark-20261022/report.json').read_text())['cases']['gallery-dense']['native']['12']['runs'][0]['raw_sha256']
 for label,row in r['variants'].items():
  guard();d=OUT/(label+'-run');d.mkdir();cache=d/'optix-cache';env=environment(rt,d);env['OPTIX_CACHE_PATH']=str(cache);t=time.perf_counter()
  args=[host['exe'],scene,rt,row['ptx'],scene.parent/'assets',d,12,3,3,3034297317,1,33,2,cache]
  p=subprocess.run(list(map(str,args)),cwd=d,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240,creationflags=subprocess.CREATE_NO_WINDOW);(d/'native.log').write_text(p.stdout+p.stderr,encoding='utf-8');assert p.returncode==0,p.stderr[-1500:];row['measurement']=json.loads(p.stdout);row['process_wall_seconds']=time.perf_counter()-t
  for run in row['measurement']['runs']:assert sha(Path(run['raw_file']))==expected,'Changed float pixels '+label
  row['render_median']=statistics.median(run['sampling_seconds'] for run in row['measurement']['runs'][1:]);save(OUT/'report.json',r);print(label,'module',row['measurement']['startup']['optix_module'],'render',row['render_median'],'exact images',flush=True)
 assert all(sha(HERE/n)==v for n,v in held.items()),'Source changed during snapshot experiment';guard();r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
