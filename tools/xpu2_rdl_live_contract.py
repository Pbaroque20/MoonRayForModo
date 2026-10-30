"""Check coordinator, failure and lifecycle contracts on the native scene bridge."""
import argparse,json,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment
from xpu2_rdl_index_probe import block

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','runtime','scene','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();source,runtime,scene,out=(getattr(a,k).resolve() for k in ('source','runtime','scene','output'));out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete')
    try:
        native=source/'build/native-avx';compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ninja=(native/'build.ninja').read_text()
        c=block(ninja,'build scene-rdl2/cmd/rdl2_cmd/rdl2_print/CMakeFiles/rdl2_print.dir/rdl2_print.cc.obj:');l=block(ninja,'build bin/rdl2_print.exe:')
        flags=shlex.split(' '.join(c[k] for k in ('DEFINES','FLAGS','INCLUDES')))+['-fno-fast-math']
        libraries=[str((native/v).resolve()) if not v.startswith('-') else v for v in shlex.split(l['LINK_LIBRARIES'])]
        files=[ROOT/'xpu2'/s for s in ('rdl_live_contract.cc','rdl_live_bridge.h','rdl_scene_index.h','indexed_scene.h','persistent_map.h')]+[Path(__file__).resolve(),scene]
        held={str(f):digest_file(f) for f in files};exe=out/'contract.exe';pp=out/'contract.ii';env=environment(compiler.parent,out)
        for label,args in [('preprocess',['-E',str(files[0]),'-o',str(pp)]),('compile',[str(pp),'-o',str(exe),*libraries])]:
            run=subprocess.run([str(compiler),*flags,*args],env=env,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(run.stdout+run.stderr)
            if run.returncode:raise ValueError(label+' failed')
        env=environment(runtime,out);env.pop('XPU2_RDL_INDEX_TRACE',None)
        run=subprocess.run([str(exe),str(scene),env['RDL2_DSO_PATH']],env=env,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'run.log').write_text(run.stdout+run.stderr)
        if run.returncode:raise ValueError('Contract failed: '+run.stderr)
        result=json.loads(run.stdout)
        if result.get('passed') is not True:raise ValueError('Incomplete contract')
        if held!={str(f):digest_file(f) for f in files}:raise ValueError('Source drift')
        report.update(status='passed',checks=result,source_hashes=held,preprocessed_sha256=digest_file(pp),executable_sha256=digest_file(exe))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
