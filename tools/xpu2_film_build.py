"""Build a live GPU contribution/film diagnostic from retained native inputs."""
import argparse,ctypes as C,json,os,shlex,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2.film_contribution import sampler
from xpu2_baseline import environment
from xpu2_cuda_sampler_probe import bind

def compile_ptx(source,out):
    toolkit=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
    with os.add_dll_directory(str(toolkit)):
        builtins=C.WinDLL(str(toolkit/'nvrtc-builtins64_128.dll'));nvrtc=C.WinDLL(str(toolkit/'nvrtc64_120_0.dll'))
    code=(ROOT/'xpu2/film_contribution_cuda.cu').read_bytes();program=C.c_void_p()
    bind(nvrtc,'nvrtcCreateProgram',[C.POINTER(C.c_void_p),C.c_char_p,C.c_char_p,C.c_int,C.c_void_p,C.c_void_p])(C.byref(program),code,b'film.cu',0,None,None)
    flags=['--std=c++14','--gpu-architecture=compute_86','--fmad=false','--ftz=false','--prec-div=true','--prec-sqrt=true']
    try:
        fn=nvrtc.nvrtcCompileProgram;fn.argtypes=[C.c_void_p,C.c_int,C.POINTER(C.c_char_p)];fn.restype=C.c_int
        options=(C.c_char_p*len(flags))(*(v.encode() for v in flags));status=fn(program,len(flags),options)
        n=C.c_size_t();bind(nvrtc,'nvrtcGetProgramLogSize',[C.c_void_p,C.POINTER(C.c_size_t)])(program,C.byref(n));log=C.create_string_buffer(n.value)
        bind(nvrtc,'nvrtcGetProgramLog',[C.c_void_p,C.c_void_p])(program,log);(out/'cuda.log').write_bytes(log.value)
        if status:raise ValueError('CUDA compilation failed')
        bind(nvrtc,'nvrtcGetPTXSize',[C.c_void_p,C.POINTER(C.c_size_t)])(program,C.byref(n));ptx=C.create_string_buffer(n.value)
        bind(nvrtc,'nvrtcGetPTX',[C.c_void_p,C.c_void_p])(program,ptx);(out/'film.ptx').write_bytes(ptx.value)
    finally:bind(nvrtc,'nvrtcDestroyProgram',[C.POINTER(C.c_void_p)])(C.byref(program))
    return flags

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','base','output'):p.add_argument('--'+key,required=True,type=Path)
    a=p.parse_args();source,base,out=a.source.resolve(),a.base.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(base):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((base/'build-inputs.json').read_text());assert manifest['status']=='built'
    for label in ('control','trace'):
        for name in ('librendering_rndr.dll','librendering_shading.dll'):
            if digest_file(base/label/name)!=manifest[label+'_'+name]:raise ValueError('Retained DLL drift')
        if digest_file(base/label/'xpu2_batched.dll')!=manifest['bridge_sha256']:raise ValueError('Retained bridge drift')
    report=dict(status='incomplete',base_manifest_sha256=digest_file(base/'build-inputs.json'))
    paths=[ROOT/'xpu2/film_contribution.py',ROOT/'xpu2/film_contribution_bridge.cc',ROOT/'xpu2/film_contribution_cuda.cu',Path(__file__).resolve()]
    report['source_hashes']={str(f.relative_to(ROOT)):digest_file(f) for f in paths}
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ispc=compiler.with_name('ispc.exe');env=environment(compiler.parent,out)
    def run(args,name,stdout=None):
        print(name,flush=True)
        with (out/(name+'.log')).open('w') as log:
            if stdout:
                with stdout.open('w') as output:r=subprocess.run(args,env=env,cwd=out,stdout=output,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            else:r=subprocess.run(args,env=env,cwd=out,stdout=log,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode:raise ValueError(name+' failed')
    try:
        report['cuda_flags']=compile_ptx(source,out)
        lib=out/'libxpu2_film.dll.a';dll=out/'xpu2_film.dll'
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
        run([str(compiler),*flags,'-E',str(ROOT/'xpu2/film_contribution_bridge.cc'),'-o',str(out/'bridge.ii')],'bridge-preprocess')
        run([str(compiler),*flags,str(out/'bridge.ii'),'-shared','-Wl,--out-implib,'+str(lib),'-o',str(dll)],'bridge-compile')
        original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/integrator/PathIntegratorUtil.ispc'
        text=(base/'sampler.ispc').read_text(encoding='utf-8');report['base_sampler_sha256']=digest_file(base/'sampler.ispc')
        code=out/'sampler.ispc';code.write_text(sampler(text),encoding='utf-8')
        ninja=(source/'build/native-renderer-avx/build.ninja').read_text(encoding='utf-8')
        stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and original.stem+'.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
        variables=dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)
        ff=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
        if '--opt=force-aligned-memory' in ff:ff.remove('--opt=force-aligned-memory')
        ff+=['-I'+str(original.parent)]
        run([str(ispc),*ff,'-E',str(code)],'sampler-preprocess',out/'sampler.pp')
        run([str(ispc),*ff,str(code),'--emit-obj','-o',str(out/'sampler.obj')],'sampler-compile')
        run([str(ispc),*ff,'-E',str(code)],'sampler-recheck',out/'sampler-recheck.pp')
        if digest_file(out/'sampler.pp')!=digest_file(out/'sampler-recheck.pp'):raise ValueError('Header drift')
        # Close the contribution context before native renderer/driver teardown.
        context_source=source/'upstream/openmoonray/moonray/moonray/lib/rendering/rndr/RenderContext.cc'
        context_hash=digest_file(context_source);context_text=context_source.read_text(encoding='utf-8');anchor='    mDriver->stopFrame();'
        if context_text.count(anchor)!=1:raise ValueError('Frame stop hook drift')
        context_code=out/'RenderContext.cc';context_code.write_text('extern "C" void xpu2FilmFinish();\n'+context_text.replace(anchor,anchor+'\n    xpu2FilmFinish();'),encoding='utf-8')
        command=subprocess.run([str(compiler.with_name('ninja.exe')),'-t','commands','moonray/lib/rendering/rndr/CMakeFiles/rendering_rndr.dir/RenderContext.cc.obj'],cwd=source/'build/native-renderer-avx',capture_output=True,text=True,check=True).stdout.splitlines()[-1]
        ff_context=shlex.split(command);ff_context=ff_context[:ff_context.index('-MD')]+['-iquote',str(context_source.parent)]
        run([*ff_context,'-E',str(context_code),'-o',str(out/'RenderContext.ii')],'context-preprocess')
        run([*ff_context,'-c',str(out/'RenderContext.ii'),'-o',str(out/'RenderContext.obj')],'context-compile')
        if digest_file(context_source)!=context_hash:raise ValueError('Native source drift')
        report['render_context_source_sha256']=context_hash
        runtime=out/'runtime';shutil.copytree(base/'trace',runtime);shutil.copy2(dll,runtime/dll.name)
        args=shlex.split((base/'librendering_rndr.dll-trace.rsp').read_text());target=str(base/'sampler.obj')
        matches=[i for i,s in enumerate(args) if not s.startswith('-') and Path(s).resolve()==Path(target)]
        if len(matches)!=1:raise ValueError('Sampler link anchor drift')
        held={s:digest_file(Path(s)) for s in args if not s.startswith('-')}
        args[matches[0]]=str(out/'sampler.obj');args.append(str(lib))
        context_matches=[i for i,s in enumerate(args) if s.endswith('-RenderContext.cc.obj')]
        if len(context_matches)!=1:raise ValueError('Context link anchor drift')
        args[context_matches[0]]=str(out/'RenderContext.obj')
        rsp=out/'link.rsp';rsp.write_text('\n'.join('"'+s.replace('\\','/')+'"' for s in args))
        run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(rsp)],'link')
        if any(digest_file(Path(s))!=v for s,v in held.items()):raise ValueError('Retained input drift')
        if any(digest_file(ROOT/s)!=v for s,v in report['source_hashes'].items()):raise ValueError('Source drift')
        report.update(status='built',files={name:digest_file(out/name) for name in ('film.ptx','xpu2_film.dll','bridge.ii','sampler.pp','sampler.obj','RenderContext.obj','RenderContext.ii','runtime/librendering_rndr.dll')},inputs=held)
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
