"""Compare real persistent XPU sessions with native index hooks off and on."""
import argparse,json,os,shlex,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity
from xpu2_rdl_index_probe import block

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','build','reference','fixtures','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();source,build,reference,fixtures,out=(getattr(a,k).resolve() for k in ('source','build','reference','fixtures','output'))
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',sessions=[],comparisons={})
    try:
        manifest=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if manifest['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=manifest['dll_sha256']:raise ValueError('Build drift')
        for path,sha in manifest['source_hashes'].items():
            if digest_file(Path(path))!=sha:raise ValueError('Bridge source drift')
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';nativebuild=source/'build/native-avx'
        ninja=(nativebuild/'build.ninja').read_text();c=block(ninja,'build scene-rdl2/cmd/rdl2_cmd/rdl2_print/CMakeFiles/rdl2_print.dir/rdl2_print.cc.obj:');l=block(ninja,'build bin/rdl2_print.exe:')
        flags=shlex.split(' '.join(c[k] for k in ('DEFINES','FLAGS','INCLUDES')))+['-fno-fast-math']
        libraries=[str((nativebuild/v).resolve()) if not v.startswith('-') else v for v in shlex.split(l['LINK_LIBRARIES'])]
        helper=ROOT/'xpu2/rdl_delta_fixture.cc';pp=out/'fixture.ii';exe=out/'fixture.exe';env=environment(compiler.parent,out)
        for label,command in [('preprocess',['-E',str(helper),'-o',str(pp)]),('compile',[str(pp),'-o',str(exe),*libraries])]:
            print('fixture '+label,flush=True);run=subprocess.run([str(compiler),*flags,*command],env=env,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(run.stdout+run.stderr)
            if run.returncode:raise ValueError('Fixture '+label+' failed')
        stages=['initial','transform','material','deformation','binding','unbinding']
        env=environment(runtime,out);deltas={};report['deltas']={}
        for old,new in zip(stages,stages[1:]):
            path=out/(new+'.rdlb');run=subprocess.run([str(exe),str(fixtures/(old+'-source.rdlb')),str(fixtures/(new+'-source.rdlb')),env['RDL2_DSO_PATH'],str(path)],env=env,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
            if run.returncode:raise ValueError('Fixture delta failed: '+run.stderr)
            deltas[new]=path;report['deltas'][new]=dict(json.loads(run.stdout),sha256=digest_file(path),bytes=path.stat().st_size)
        report.update(build_manifest_sha256=digest_file(build/'report.json'),helper_sha256=digest_file(helper),helper_executable_sha256=digest_file(exe),gpu=gpu_identity())
        locked={str(rt):inventory(rt) for rt in (runtime,reference)}
        initial=fixtures/'initial-source.rdlb';images={}
        steps=[('initial',None,None)]+[(s,'delta',deltas[s]) for s in stages[1:]]+[('noop','delta',deltas['unbinding']),('reload','full',None),('transform-again','delta',deltas['transform'])]
        for label,rt,enabled in [('reference',reference,False),('control',runtime,False),('indexed',runtime,True)]:
            folder=out/label;folder.mkdir();session=folder/'session';session.mkdir();env=environment(rt,folder)
            env.update(MOONRAY_MODO_SESSION=str(session),MOONRAY_MODO_GENERATION='0',XPU2_RDL_INDEX='1' if enabled else '0',XPU2_RDL_INDEX_TRACE=str(folder/'trace.jsonl'))
            command=[str(rt/'moonray.exe'),'-in',str(initial),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
            logpath=folder/'render.log';frames=[];times=[];print('session '+label,flush=True)
            with logpath.open('w') as log:
                process=subprocess.Popen(command,cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                def wait(marker,timeout=180):
                    deadline=time.monotonic()+timeout
                    while time.monotonic()<deadline:
                        if marker in logpath.read_text(errors='replace'):return
                        if process.poll() is not None:raise ValueError(label+' exited before '+marker)
                        time.sleep(.02)
                    raise TimeoutError(label+' timed out: '+marker)
                def send(number,mode,path):
                    pending=session/'pending.txt';pending.write_text('\n'.join([str(number),mode,str(path or ''),str(initial)])+'\n');pending.replace(session/'command.txt')
                try:
                    for number,(stage,mode,path) in enumerate(steps):
                        started=time.perf_counter()
                        if mode:send(number,mode,path)
                        wait('@@MODO_SESSION DONE '+str(number)+'\n');times.append(time.perf_counter()-started)
                        saved=folder/(stage+'.exr');shutil.copy2(folder/'beauty.exr',saved);frames.append(saved)
                        print(label+' '+stage,flush=True)
                    send(len(steps),'quit',None);code=process.wait(timeout=30)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=10)
            check=successful('xpu',1,code,logpath.read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace'),(folder/'beauty.exr').exists())
            if not check['passed']:raise ValueError('Invalid native session '+label)
            row=dict(label=label,execution=check,frame_seconds=times,log_sha256=digest_file(logpath));report['sessions'].append(row)
            trace=folder/'trace.jsonl'
            if enabled:
                rows=[json.loads(s) for s in trace.read_text().splitlines()];row['updates']=rows
                if len(rows)!=7 or sum(r['initialized'] for r in rows)!=2 or not rows[-2]['noop']:raise ValueError('Index reuse/noop/reload contract failed')
                if rows[0]['attributes_encoded']!=1 or rows[1]['attributes_encoded']!=1 or rows[2]['attributes_encoded']!=1:raise ValueError('Clean attributes were recaptured')
            elif trace.exists():raise ValueError('Index unexpectedly enabled')
            images[label]=[read_rgba(rt,f,folder,f.stem,env) for f in frames]
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for label in ('control','indexed'):
            report['comparisons'][label]=[dict(stage=stage,**compare_rgba(ref,img)) for (stage,_,_),ref,img in zip(steps,images['reference'],images[label])]
            if any(r['status']!='passed' for r in report['comparisons'][label]):raise ValueError('Persistent image parity failed: '+label)
        for label,frames in images.items():
            if compare_rgba(frames[0],frames[7])['status']!='passed' or compare_rgba(frames[1],frames[8])['status']!='passed' or compare_rgba(frames[5],frames[6])['status']!='passed':raise ValueError('Reload/noop repeatability failed: '+label)
        for rt in (runtime,reference):verify(rt,locked[str(rt)])
        if gpu_identity()!=report['gpu']:raise ValueError('GPU drift')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
