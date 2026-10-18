"""Build the isolated native owned GPU diffuse-path candidate."""
import argparse,json,os,shlex,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment
from xpu2_native_path_build import patch
from xpu2 import native_gpu_paths, native_gpu_early

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','base','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();source,base,out=(getattr(a,n).resolve() for n in ('source','base','output'))
    if out.is_relative_to(source) or out.is_relative_to(base):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete'}
    try:
        manifest=json.loads((base/'build-inputs.json').read_text());assert manifest['status']=='built'
        for item in manifest['inputs']:
            if digest_file(base/item['copy'])!=item['sha256']:raise ValueError('Retained link input drift')
        runtime=out/'runtime';shutil.copytree(base/'control',runtime)
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';build=source/'build/native-renderer-avx'
        env=environment(runtime,out);env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
        files=[ROOT/'xpu2'/s for s in ('native_path_restore.h','native_path_restore.inc','native_gpu_shading.h','native_gpu_pack.ispc.inc','native_gpu_paths.py','native_lambert_queue.cc','native_gpu_early.h','native_gpu_early.py','native_gpu_early_pack.ispc.inc')]+[Path(__file__).resolve(),ROOT/'tools/xpu2_native_path_build.py']
        hashes={str(f):digest_file(f) for f in files};native={};objects={};preprocessed={}
        (out/'native_gpu_paths.inc').write_text(native_gpu_early.adapter((ROOT/'xpu2/native_path_restore.inc').read_text()),encoding='utf-8')
        (out/'early_queue.inc').write_text(native_gpu_early.queue((ROOT/'xpu2/native_lambert_queue.cc').read_text()),encoding='utf-8')
        (out/'native_gpu_shading.h').write_text((ROOT/'xpu2/native_gpu_shading.h').read_text().replace('native_lambert_queue.cc','early_queue.inc'),encoding='utf-8')
        def run(args,label):
            print(label,flush=True)
            with (out/(label+'.log')).open('w') as log:
                done=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            if done.returncode:raise ValueError(label+' failed')
        for name in ('PathIntegratorUtil','PbrTLState','RenderFrame','RenderFramePasses','RenderContext'):
            part={'PathIntegratorUtil':'pbr/integrator/','PbrTLState':'pbr/core/'}.get(name,'rndr/')
            original=source/('upstream/openmoonray/moonray/moonray/lib/rendering/'+part+name+'.cc');native[str(original)]=digest_file(original)
            cc=out/(name+'.cc');cc.write_text(native_gpu_early.cpp(original.read_text(encoding='utf-8')) if name=='PathIntegratorUtil' else patch(name,original.read_text(encoding='utf-8')),encoding='utf-8')
            target=('moonray/lib/rendering/pbr/CMakeFiles/rendering_pbr_objects.dir/'+part.split('/')[1]+'/' if part.startswith('pbr/') else 'moonray/lib/rendering/rndr/CMakeFiles/rendering_rndr.dir/')+name+'.cc.obj'
            command=subprocess.run([str(compiler.with_name('ninja.exe')),'-t','commands',target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
            flags=shlex.split(command);flags=flags[:flags.index('-MD')]+['-iquote',str(original.parent),'-I'+str(ROOT/'xpu2'),'-I'+str(source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
            pp=out/(name+'.ii');obj=out/(name+'.obj')
            run([*flags,'-E',str(cc),'-o',str(pp)],name+'-preprocess')
            run([*flags,'-c',str(pp),'-o',str(obj)],name+'-compile')
            objects[name]=digest_file(obj);preprocessed[name]=digest_file(pp)
        name='PathIntegratorUtil'
        original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/integrator/PathIntegratorUtil.ispc'
        native[str(original)]=digest_file(original)
        code=out/(name+'.ispc');header=original.with_name('BsdfSampler.isph');native[str(header)]=digest_file(header)
        code.write_text(native_gpu_early.ispc(original.read_text(encoding='utf-8'),header.read_text(encoding='utf-8')),encoding='utf-8')
        ninja=(build/'build.ninja').read_text(encoding='utf-8')
        stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and name+'.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
        variables=dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)
        flags=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
        if '--opt=force-aligned-memory' in flags:flags.remove('--opt=force-aligned-memory')
        flags+=['-I'+str(original.parent)]
        obj=out/(name+'-ispc.obj');pp=out/(name+'.pp')
        # ISPC preprocessing writes stdout, unlike the C++ -o form.
        with pp.open('w') as output, (out/(name+'-preprocess.log')).open('w') as log:
            subprocess.run([str(compiler.with_name('ispc.exe')),*flags,'-E',str(code)],cwd=out,env=env,stdout=output,stderr=log,check=True,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        run([str(compiler.with_name('ispc.exe')),*flags,str(code),'--emit-obj','-o',str(obj)],name+'-compile')
        objects[name+'-ispc']=digest_file(obj);preprocessed[name+'-ispc']=digest_file(pp)
        lines=(base/'control.rsp').read_text().splitlines()
        for name in objects:
            anchor=[s for s in lines if s.strip().strip('"').endswith('-'+name.replace('-ispc','')+('.ispc.obj' if name.endswith('-ispc') else '.cc.obj'))]
            if len(anchor)!=1:raise ValueError('Link anchor drift '+name)
            lines=['"'+str(out/(name+'.obj')).replace('\\','/')+'"' if s in anchor else s for s in lines]
        rsp=out/'link.rsp';rsp.write_text('\n'.join(lines));run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(rsp)],'link')
        if any(digest_file(Path(f))!=h for f,h in {**hashes,**native}.items()):raise ValueError('Source drift')
        report.update(status='built',source_hashes=hashes,native_hashes=native,objects=objects,preprocessed=preprocessed,dll_sha256=digest_file(runtime/'librendering_rndr.dll'),base_sha256=digest_file(base/'build-inputs.json'))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
