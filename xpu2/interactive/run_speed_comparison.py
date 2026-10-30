"""Private, bounded speed experiment; restricted fixture evidence, not VER-11 release qualification."""
import argparse,array,json,math,statistics,time,traceback
from pathlib import Path
import asset_snapshot
from reference_repeatability import run_reference,save,values,distance
from reference_runtime import verify,sha
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent
PLAN={'resolution':[128,96],'target_grid':8,'reference_converged_grid':32,'native_grids':[8,12,16,24,32],
      'reference_repetitions':4,'native_repetitions':4,'warmup_runs_discarded':1,'threads':[1,12],
      'rMSE':'sum RGB squared errors / sum converged reference RGB squared values; linear raw, no display/denoiser',
      'quality_gate':{'high_spp_max_pixel':.08,'high_spp_max_8x8_block_mean':.015,'alpha_max':.015},
      'target':'median rMSE from three measured original XPU normal-spp runs at each worker count',
      'native_time':'full uniform native render at first tested sample grid meeting target in all measured repetitions; discrete upper bound, no interpolation',
      'sampling_mode':'existing native 2ms progressive window pipeline, NOT the spec THR stage',
      'timing':'perf_counter wall, renderer stats; no external profiler. Built-in reference statistics remain unchanged.',
      'reference_cache':'each reference run fresh process; OS/filesystem/OptiX disk cache warm; reference per-process setup separately reported',
      'native_cache':'first render cold native resources; subsequent renders reuse scene/texture/worker resources',
      'claim':'two synthetic supported textured fixtures only; no production corpus, general 50% result, or global qualification'}

def metric(a,b,w,h):
    if len(a)!=w*h*4 or len(b)!=len(a):raise ValueError('Image dimensions mismatch')
    error=energy=0.;pixel=alpha=0.
    for i in range(0,len(a),4):
        alpha=max(alpha,abs(a[i+3]-b[i+3]))
        for c in range(3):
            d=a[i+c]-b[i+c];error+=d*d;energy+=b[i+c]*b[i+c];pixel=max(pixel,abs(d))
    block=0.
    for y in range(0,h,8):
        for x in range(0,w,8):
            ids=[(yy*w+xx)*4 for yy in range(y,min(y+8,h)) for xx in range(x,min(x+8,w))]
            for c in range(3):block=max(block,abs(sum(a[i+c]-b[i+c] for i in ids)/len(ids)))
    return dict(relative_mse=error/max(energy,1e-30),max_pixel=pixel,max_block_mean=block,alpha=alpha)

def quality(m):
    g=PLAN['quality_gate'];return m['max_pixel']<=g['high_spp_max_pixel'] and m['max_block_mean']<=g['high_spp_max_8x8_block_mean'] and m['alpha']<=g['alpha_max']

def timing(rows,key):
    v=[r[key] for r in rows];return {'median':statistics.median(v),'min':min(v),'max':max(v),'values':v}

def main():
 p=argparse.ArgumentParser()
 for n in ('runtime','build','speed-build','repeatability','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--diagnostic',action='store_true',help='Allow unqualified measurements after a failed reference gate')
 a=p.parse_args();rt=a.runtime.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);save(out/'protocol.json',PLAN)
 r={'status':'incomplete','protocol':PLAN,'cases':{}}
 try:
  gate=json.loads(a.repeatability.read_text());assert gate['status'] in ('passed','failed'),'Reference controls incomplete'
  r['reference_repeatability_passed']=gate['status']=='passed'
  if not r['reference_repeatability_passed'] and not a.diagnostic:raise ValueError('Reference repeatability failed; --diagnostic is required for unqualified timings')
  r['speed_qualification']='exploratory only; reference repeatability gate remains open' if gate['status']!='passed' else 'restricted fixture measurement only'
  r['reference_gate_sha256']=sha(a.repeatability);lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
  build=json.loads(a.build.read_text());speed=json.loads(a.speed_build.read_text());assert build['status']==speed['status']=='passed'
  exe,ptx,helper,bench=map(Path,(build['exe'],build['ptx'],build['helper'],speed['exe']))
  assert sha(exe)==build['binary_hashes']['exe'] and sha(ptx)==build['binary_hashes']['ptx'] and sha(helper)==build['asset_build']['executable_sha256'] and sha(bench)==speed['build']['executable_sha256']
  for k,v in speed['source_hashes'].items():assert sha(Path(k))==v,'Benchmark source drift'
  held={str(HERE/n):sha(HERE/n) for n in ('run_speed_comparison.py','reference_repeatability.py','asset_snapshot.py')};r['source_hashes']=held;r['native_build_sha256']=sha(a.speed_build);r['runtime_identity']=lock['identity']
  base=HERE.parents[1]/'test-results/interactive-spatial-textures-20261022b'
  for name in ('room-resident','room-close'):
   folder=out/name;folder.mkdir();entry=r['cases'][name]={'threads':{}};text=(base/name/'input.rdla').read_text()
   scenes={}
   for grid in PLAN['native_grids']:
    f=folder/f'grid-{grid}';f.mkdir();source=f/'input.rdla';source.write_text(text+f'\nSceneVariables {{ ["image_width"]=128, ["image_height"]=96, ["pixel_samples"]={grid} }}\n',encoding='utf-8')
    call([rt/'rdl2_convert.exe','-i',source,'-o',f/'input.rdlb'],rt,f,'convert');asset_snapshot.freeze(f/'input.rdlb',helper,rt,f/'frozen',f);asset_snapshot.verify(f/'frozen/manifest.json');scenes[grid]=f/'frozen/scene.rdlb'
   # Converged reference uses exactly 16x the normal 64 spp. Its cost is not part of benchmark timing.
   ref,meta=run_reference(rt,scenes[32],folder/'converged-reference',12,exe,timeout=600);entry['converged']=meta
   # Separate original reference variation at the benchmark resolution is recorded.
   for t in (1,12):
    case=entry['threads'][str(t)]={'reference':[],'native':{},'winner':None};normal=[]
    for i in range(PLAN['reference_repetitions']):
     v,row=run_reference(rt,scenes[8],folder/f'xpu-t{t}-{i}',t,exe,timeout=600);row['error']=metric(v,ref,128,96);case['reference'].append(row);normal.append(v)
     print(name,'XPU',t,i,row['stats']['Mcrt time (s)'],flush=True);save(out/'report.json',r)
    target=statistics.median(x['error']['relative_mse'] for x in case['reference'][1:]);case['frozen_target_error']=target
    case['reference_repeat_max_delta']=max(distance(v,normal[0]) for v in normal)
    case['reference_sampling_seconds']=timing([x['stats'] for x in case['reference'][1:]],'Mcrt time (s)')
    save(folder/f't{t}-frozen-target.json',case)
    # First establish restricted high-spp conformance, then choose the smallest
    # predeclared uniform sample budget meeting the original-XPU target.
    def native(grid,repeats):
     dest=folder/f'native-t{t}-g{grid}';dest.mkdir();guard();start=time.perf_counter()
     data=json.loads(call([bench,scenes[grid],rt,ptx,scenes[grid].parent/'assets',dest,t,repeats],rt,dest,'probe',timeout=600));data['process_wall_seconds']=time.perf_counter()-start;guard()
     assert data['status']=='passed' and data['threads']==t and data['workers_created']==t and data['steady_gpu_allocations']==0 and data['steady_gpu_synchronizations']==0
     for row in data['runs']:
      raw=Path(row['raw_file']);row['raw_sha256']=sha(raw);row['error']=metric(values(raw.read_bytes()),ref,128,96)
     case['native'][str(grid)]=data;save(out/'report.json',r);print(name,'XPU2',t,grid,[round(x['sampling_seconds'],4) for x in data['runs']],flush=True);return data
    high=native(32,PLAN['native_repetitions']);case['high_spp_quality_passed']=all(quality(x['error']) for x in high['runs']);save(out/'report.json',r)
    for grid in PLAN['native_grids']:
     data=high if grid==32 else native(grid,PLAN['native_repetitions']);measure=data['runs'][1:]
     reaches=all(x['error']['relative_mse']<=target and x['error']['alpha']<=PLAN['quality_gate']['alpha_max'] for x in measure)
     data['meets_target_in_all_measured_runs']=reaches
     data['sampling_seconds']=timing(measure,'sampling_seconds');data['first_partial_seconds']=timing(measure,'first_partial_seconds');data['first_full_coverage_seconds']=timing(measure,'first_full_coverage_seconds')
     if reaches:
      case['winner']={'grid':grid,'spp':grid*grid,'native_sampling_seconds':data['sampling_seconds'],'reference_sampling_seconds':case['reference_sampling_seconds'],'quality_passed':case['high_spp_quality_passed'],
       'savings':1-data['sampling_seconds']['median']/case['reference_sampling_seconds']['median'],'scope':'exploratory current progressive pipeline; not production VER-11'};break
    save(out/'report.json',r)
   for scene in scenes.values():asset_snapshot.verify(scene.parent/'manifest.json')
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Harness drift')
  verify(rt,lock);guard();r['measurement_status']='completed';r['production_qualified']=False
  r['status']='measured' if r['reference_repeatability_passed'] else 'partial'
 except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
 save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);return int(r.get('measurement_status')!='completed')
if __name__=='__main__':raise SystemExit(main())
