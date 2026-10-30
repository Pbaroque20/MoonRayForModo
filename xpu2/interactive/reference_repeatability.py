"""Private reference-only calibration followed by held-out and fallback checks.
Never modifies MoonRay, rounds pixels, or adapts a gate after held-out results.
"""
import argparse,array,hashlib,json,math,subprocess,time,traceback
from pathlib import Path
from fallback import environment,execution,FallbackJob
from prototype_wire import decode
from protocol_model import Epoch
from reference_runtime import sha,verify
from run_m0 import guard
HERE=Path(__file__).resolve().parent

def values(raw):
    a=array.array('f');a.frombytes(raw)
    if not a or not all(math.isfinite(x) for x in a):raise ValueError('Invalid raw float image')
    return a

def distance(a,b):
    if len(a)!=len(b):raise ValueError('Image size changed')
    return max(abs(x-y) for x,y in zip(a,b))

def envelope(images):
    if len(images)<2:raise ValueError('At least two originals required')
    n=len(images[0]);lo=[min(a[i] for a in images) for i in range(n)];hi=[max(a[i] for a in images) for i in range(n)]
    return max(b-a for a,b in zip(lo,hi))

def against(candidate,controls,bound):
    errors=[distance(candidate,a) for a in controls]
    return {'max_distance_to_controls':max(errors),'min_distance_to_controls':min(errors),'passed':max(errors)<=bound}

def save(path,obj):path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def stats(path):
    result={}
    for line in path.read_text().splitlines():
        for key in ('Render prep (s)','Mcrt time (s)','Total time (s)','Thread(s)'):
            if line.startswith(key+','):result[key]=float(line.split(',')[1])
    return result

def run_reference(rt,scene,folder,threads,exe,*,fallback=False,timeout=240):
    guard();beg=time.perf_counter()
    if fallback:
        job=FallbackJob(rt,scene,folder,threads,Epoch(9001,1,1,1),timeout)
        job.start()
        try:
            while job.poll()=='running':time.sleep(.005)
            result=job.result(job.epoch)
            if result is None:raise RuntimeError('Invalid fallback result: '+str(job.state))
            elapsed=time.perf_counter()-beg;ex=job.execution;cmd=job.command
        finally:
            if job.process.poll() is None:job.cancel();job.process.wait(timeout=10);job.poll()
    else:
        folder.mkdir()
        cmd=[str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(threads),'-info','-stats',str(folder/'stats.csv')]
        with (folder/'render.log').open('wb') as log:
            p=subprocess.Popen(cmd,cwd=folder,env=environment(rt,folder),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            try:code=p.wait(timeout=timeout)
            finally:
                if p.poll() is None:p.kill();p.wait(timeout=10)
        elapsed=time.perf_counter()-beg
        ex=execution((folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text(),threads)
        if code or not ex['passed']:raise RuntimeError('Invalid original XPU run: '+str(ex))
    guard()
    _,raw=decode(exe,rt,folder/'beauty.exr',folder)
    (folder/'beauty.rgba').write_bytes(raw)
    return values(raw),dict(command=cmd,execution=ex,wall_seconds=elapsed,stats=stats(folder/'stats.csv'),raw_sha256=hashlib.sha256(raw).hexdigest(),folder=str(folder))

def main():
    p=argparse.ArgumentParser()
    for n in ('runtime','build','scene','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();rt=a.runtime.resolve();scene=a.scene.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    plan={'calibration_per_thread':12,'heldout_per_thread':4,'fallback_per_thread':2,'threads':[1,12],
          'rule':'maximum channel sup-norm between reference calibration images; no padding; every held-out and fallback must be within that bound of every control',
          'historical':'include all recorded standalone/fallback EXRs of this exact textured RDLB at 1 thread; never candidate native images',
          'scope':'finite fixture qualification, not universal bitwise repeatability','pixels':'float32 RGBA unmodified','native_images_used_for_gate':False}
    save(out/'protocol.json',plan);r={'status':'incomplete','protocol':plan,'cases':{}}
    try:
        lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);build=json.loads(a.build.read_text());exe=Path(build['exe'])
        assert sha(exe)==build['binary_hashes']['exe'];r['runtime_identity']=lock['identity'];r['scene_sha256']=sha(scene);r['harness_sha256']=sha(Path(__file__))
        controls={1:[],12:[]};allchecks=True
        # The anomalous historical image is itself an original-XPU render. Keeping
        # it out of reference calibration previously produced an artificial zero.
        root=HERE.parents[1]/'test-results';old=root/'interactive-prototype-20261022c'
        history=[root/'interactive-spatial-textures-20261022b/room-close/reference']+sorted((old/'reference-envelope-textured').glob('[0-9]'))
        history += [old/'session/reference'/('frame-'+str(i)) for i in (8,12,14)]
        historical_scene=root/'interactive-spatial-textures-20261022b/room-close/frozen/scene.rdlb'
        if sha(scene)!=sha(historical_scene):raise ValueError('Historical reference scene mismatch')
        for t in (1,12):r['cases'][str(t)]={'calibration':[],'heldout':[],'fallback':[]}
        for folder in history:
            log=(folder/'render.log').read_text(errors='replace');csv=(folder/'stats.csv').read_text();assert execution(log,csv,1)['passed']
            assert str(scene) in log,'Historical scene command mismatch'
            _,raw=decode(exe,rt,folder/'beauty.exr',out);controls[1].append(values(raw))
            r['cases']['1']['calibration'].append({'historical':True,'exr':str(folder/'beauty.exr'),'exr_sha256':sha(folder/'beauty.exr'),'raw_sha256':hashlib.sha256(raw).hexdigest()})
        for i in range(plan['calibration_per_thread']):
            for t in (1,12) if i%2==0 else (12,1):
                v,row=run_reference(rt,scene,out/f'cal-t{t}-{i}',t,exe);controls[t].append(v);r['cases'][str(t)]['calibration'].append(row)
                print('calibration',t,i,row['wall_seconds'],flush=True);save(out/'report.json',r)
        for t in (1,12):
            case=r['cases'][str(t)];case['frozen_bound']=envelope(controls[t]);case['unique_calibration_images']=len(set(x['raw_sha256'] for x in case['calibration']))
            save(out/f'frozen-t{t}.json',case)
        # Gates have been written before any holdout/fallback run; never change them.
        for phase,count in [('heldout',plan['heldout_per_thread']),('fallback',plan['fallback_per_thread'])]:
            for i in range(count):
                for t in (1,12):
                    v,row=run_reference(rt,scene,out/f'{phase}-t{t}-{i}',t,exe,fallback=phase=='fallback')
                    row.update(against(v,controls[t],r['cases'][str(t)]['frozen_bound']));r['cases'][str(t)][phase].append(row);allchecks &= row['passed']
                    print(phase,t,i,row['max_distance_to_controls'],row['passed'],flush=True);save(out/'report.json',r)
        assert sha(scene)==r['scene_sha256'];assert sha(Path(__file__))==r['harness_sha256'];verify(rt,lock);guard()
        r['status']='passed' if allchecks else 'failed';r['global_bit_exact_claim']=False
    except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
    save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);return int(r['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
