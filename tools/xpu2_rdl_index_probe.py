"""Build and exercise owned indexed native RDL data; optional exact XPU renders."""
import argparse, json, os, shlex, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file, inventory, verify
from xpu2.images import read_rgba, compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful, gpu_identity


def block(text, prefix):
    stanza=next(s for s in text.split('\n\n') if s.startswith(prefix))
    return dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('source','runtime','scene','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--render',action='store_true')
    a=parser.parse_args();source,runtime,scene,out=(getattr(a,k).resolve() for k in ('source','runtime','scene','output'))
    if out.is_relative_to(source) or out.is_relative_to(runtime):parser.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',scope='Real native RDL index and separate native replica',renders=[])
    try:
        inputs=[ROOT/'xpu2'/n for n in ('indexed_scene.h','persistent_map.h','rdl_scene_index.h','rdl_replica.h','rdl_scene_index_probe.cc')]+[Path(__file__).resolve(),scene]
        hashes={str(f):digest_file(f) for f in inputs}
        build=source/'build/native-avx';compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
        ninja=(build/'build.ninja').read_text(encoding='utf-8')
        compile_block=block(ninja,'build scene-rdl2/cmd/rdl2_cmd/rdl2_print/CMakeFiles/rdl2_print.dir/rdl2_print.cc.obj:')
        link_block=block(ninja,'build bin/rdl2_print.exe:')
        flags=shlex.split(' '.join(compile_block[k] for k in ('DEFINES','FLAGS','INCLUDES')))
        flags+=['-I'+str(compiler.parent.parent/'include'),'-fno-fast-math']
        libraries=shlex.split(link_block['LINK_LIBRARIES'])
        libraries=[str((build/v).resolve()) if not v.startswith('-') else v for v in libraries]
        held={v:digest_file(Path(v)) for v in libraries if not v.startswith('-')}
        exe,pp=out/'rdl-index.exe',out/'rdl-index.ii'
        env=environment(compiler.parent,out)
        for label,args in [('preprocess',['-E',str(ROOT/'xpu2/rdl_scene_index_probe.cc'),'-o',str(pp)]),
                           ('compile',[str(pp),'-o',str(exe),*libraries])]:
            print(label,flush=True)
            done=subprocess.run([str(compiler),*flags,*args],env=env,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError(label+' failed')
        report.update(source_hashes=hashes,library_hashes=held,compiler_sha256=digest_file(compiler),preprocessed_sha256=digest_file(pp),executable_sha256=digest_file(exe))
        print("verify runtime",flush=True)
        locked=inventory(runtime)
        env=environment(runtime,out)
        print('native scene index',flush=True)
        done=subprocess.run([str(exe),str(scene),env['RDL2_DSO_PATH'],str(out)],env=env,cwd=out,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'probe.log').write_text(done.stdout+done.stderr,encoding='utf-8')
        if done.returncode:raise ValueError('Native scene probe failed: '+done.stderr[-1600:])
        report['native']=json.loads(done.stdout)
        if report['native'].get('status')!='passed':raise ValueError('Native index validation failed')
        if a.render:
            report['gpu']=gpu_identity()
            for stage in ('initial','transform','material','deformation','binding','unbinding'):
                images={}
                for kind in ('source','indexed'):
                    label=stage+'-'+kind;folder=out/label;folder.mkdir();runenv=environment(runtime,folder)
                    print('render '+label,flush=True);started=time.perf_counter()
                    with (folder/'render.log').open('w') as log:
                        run=subprocess.run([str(runtime/'moonray.exe'),'-in',str(out/(label+'.rdlb')),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],cwd=folder,env=runenv,stdout=log,stderr=log,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
                    check=successful('xpu',1,run.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
                    row=dict(label=label,wall_seconds=time.perf_counter()-started,execution=check,scene_sha256=digest_file(out/(label+'.rdlb')));report['renders'].append(row)
                    if not check['passed']:raise ValueError('Render failed: '+label)
                    images[kind]=read_rgba(runtime,folder/'beauty.exr',folder,'raw',runenv)
                result=compare_rgba(images['source'],images['indexed']);report['renders'][-1]['image_comparison']=result
                if result['status']!='passed':raise ValueError('Exact image mismatch: '+stage)
            if gpu_identity()!=report['gpu']:raise ValueError('GPU identity changed')
        verify(runtime,locked)
        if hashes!={str(f):digest_file(f) for f in inputs} or any(digest_file(Path(f))!=v for f,v in held.items()):raise ValueError('Source/library drift')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
