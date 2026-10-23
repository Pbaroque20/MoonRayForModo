"""Private CPU surface/sample-tree conformance against pinned MoonRay libraries."""
import argparse,json,shlex,subprocess,sys
from pathlib import Path
from fallback import environment
from reference_runtime import sha,verify
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from xpu2_rdl_index_probe import block

def compile_probe(source,runtime,out,unit):
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
    ninja=(source/'build/native-renderer-avx/build.ninja').read_text(encoding='utf-8')
    c=block(ninja,'build moonray/lib/rendering/pbr/CMakeFiles/rendering_pbr_objects.dir/camera/PerspectiveCamera.cc.obj:')
    flags=shlex.split(' '.join(c[k] for k in ('DEFINES','FLAGS','INCLUDES')))
    flags+=['-I'+str(compiler.parent.parent/'include'),'-fno-fast-math','-ffp-contract=off']
    # Import directly from the pinned binaries, not mutable candidate libraries.
    names=('librendering_rndr.dll','librendering_shading.dll','libscene_rdl2.dll','libcommon_math.dll','libcommon_platform.dll','librender_logging.dll')
    # RDL library is named scene_rdl2 in some builds and rdl2 in others.
    libs=[]
    for n in names:
        path=runtime/n
        if not path.exists() and n=='libscene_rdl2.dll':path=runtime/'librdl2.dll'
        if not path.exists():raise RuntimeError('Missing pinned library '+str(path))
        libs.append(str(path))
    pre=out/'surface.ii';exe=out/'surface.exe'
    for phase,cmd in [('preprocess',['-E',str(unit),'-o',str(pre)]),('compile',[str(pre),'-o',str(exe),*libs])]:
        run=subprocess.run([str(compiler),*flags,*cmd],env=environment(compiler.parent,out),capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/(phase+'.log')).write_text(run.stdout+run.stderr,encoding='utf-8')
        if run.returncode:raise RuntimeError(phase+' failed: '+run.stderr[-1500:])
    return exe,dict(compiler_sha256=sha(compiler),preprocessed_sha256=sha(pre),exe_sha256=sha(exe),flags=flags,libraries={v:sha(Path(v)) for v in libs})

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','runtime','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output=a.output.resolve();a.source=a.source.resolve();a.runtime=a.runtime.resolve()
    if a.output.is_relative_to(a.source) or a.output.is_relative_to(a.runtime):p.error('Isolated output required')
    a.output.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'components only; not a qualified renderer'}
    try:
        verify(a.runtime,json.loads((HERE/'reference-lock.json').read_text()))
        files=[HERE/n for n in ('surface_core.h','surface_probe.cc','sample_tree.h','path_stage.h','sample_stream.h','surface-gates.json','run_surface.py')]
        held={str(p):sha(p) for p in files};report['source_hashes']=held
        gates=json.loads((HERE/'surface-gates.json').read_text());report['gates']=gates
        (a.output/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8')
        exe,build=compile_probe(a.source,a.runtime,a.output,HERE/'surface_probe.cc');report['build']=build
        done=subprocess.run([str(exe)],cwd=a.output,env=environment(a.runtime,a.output),capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        (a.output/'probe.log').write_text(done.stdout+done.stderr,encoding='utf-8')
        if done.returncode:raise RuntimeError('Probe failed '+str(done.returncode)+': '+done.stderr[-1000:])
        result=json.loads(done.stdout);report['results']=result
        for k in ('filter','lambert','camera'):
            if result[k+'_error']>gates[k+'_max_absolute_error']:raise RuntimeError(k+' conformance failed')
        if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
        report['status']='passed'
    except Exception as e:report.update(status='failed',error=str(e))
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','build','gates')},indent=2),flush=True)
    return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
