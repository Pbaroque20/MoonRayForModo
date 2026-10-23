"""Private second shader screen: share immutable Sobol direction data."""
import json,shutil,time,subprocess,statistics,traceback
from pathlib import Path
import gpu_build
from reference_runtime import sha
from reference_repeatability import save
from run_m0 import guard
from fallback import environment
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-shader-constants-20261022';OUT.mkdir(exist_ok=False);before=TR/'interactive-shader-boundaries-20261022/before';r={'status':'incomplete','variants':{}}
save(OUT/'protocol.json',json.loads((before.parent/'protocol.json').read_text()))
try:
 src=Path(__import__('os').environ['XPU2_TOOLCHAIN_ROOT']);rt=TR/'interactive-reference-042';host=json.loads((TR/'interactive-startup-candidate-build-20261022/build.json').read_text());fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());scene=Path(fixtures['cases']['gallery-dense']['scenes']['8']);expected=json.loads((TR/'interactive-ray-hit-benchmark-20261022/report.json').read_text())['cases']['gallery-dense']['native']['12']['runs'][0]['raw_sha256']
 for label in ('constant-table','constant-table-step'):
  folder=OUT/label;folder.mkdir();source=folder/'source';source.mkdir()
  for p in before.iterdir():
   if p.suffix in ('.h','.cu'):shutil.copy2(p,source/p.name)
  p=source/'sample_stream.h';s=p.read_text(encoding='utf-8');start=s.index('    constexpr U32 directions[4][32]={');end=s.index('    };',start)+len('    };');table=s[start:end].replace('    constexpr U32 directions','X2_SOBOL_STORAGE U32 directions',1)
  s=s[:start]+s[end:];pos=s.index('X2_HD inline U32 sobol(')
  table='// One immutable direction table on the GPU, rather than a local copy per call.\n#if defined(__CUDACC__)\n#define X2_SOBOL_STORAGE static __device__ __constant__ const\n#else\n#define X2_SOBOL_STORAGE inline constexpr\n#endif\n'+table+'\n#undef X2_SOBOL_STORAGE\n'
  s=s[:pos]+table+s[pos:];p.write_text(s,encoding='utf-8')
  if label.endswith('-step'):
   p=source/'resume_core.h';s=p.read_text(encoding='utf-8');s=s.replace('template<class Backend>X2_HD inline void step(','template<class Backend>\n#if defined(__CUDACC__)\n__noinline__\n#endif\nX2_HD inline void step(');p.write_text(s,encoding='utf-8')
  gpu_build.HERE=source;t=time.perf_counter();ptx,b=gpu_build.compile_ptx(src,folder);row={'status':'passed','ptx':str(ptx),'build':b,'ptx_sha256':sha(ptx),'ptx_bytes':ptx.stat().st_size,'nvrtc_seconds':time.perf_counter()-t,'source_hashes':{str(p):sha(p) for p in source.iterdir()}};save(folder/'build.json',row);r['variants'][label]=row;print(label,'ptx bytes',row['ptx_bytes'],flush=True)
 for label,row in r['variants'].items():
  guard();d=OUT/(label+'-run');d.mkdir();cache=d/'optix-cache';env=environment(rt,d);env['OPTIX_CACHE_PATH']=str(cache)
  args=[host['exe'],scene,rt,row['ptx'],scene.parent/'assets',d,12,3,3,3034297317,1,33,2,cache]
  p=subprocess.run(list(map(str,args)),cwd=d,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240,creationflags=subprocess.CREATE_NO_WINDOW);(d/'native.log').write_text(p.stdout+p.stderr,encoding='utf-8');assert p.returncode==0,p.stderr[-1500:];row['measurement']=json.loads(p.stdout)
  for run in row['measurement']['runs']:assert sha(Path(run['raw_file']))==expected,'Changed pixels '+label
  row['render_median']=statistics.median(v['sampling_seconds'] for v in row['measurement']['runs'][1:]);save(OUT/'report.json',r);print(label,'module',row['measurement']['startup']['optix_module'],'render',row['render_median'],'exact images',flush=True)
 r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
