"""Build isolated native batched Lambert handoff from frozen link inputs."""
import argparse,json,os,shlex,shutil,subprocess,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from xpu2 import batched_patch
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','runtime','pbr-build','shading-build','trace-build','output'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--profile',action='store_true',help='Build optional aggregate timing and quiet diagnostics mode')
    p.add_argument('--window-dispatch',action='store_true',help='Include optional explicit window publication (requires --profile)')
    a=p.parse_args()
    if a.window_dispatch and not a.profile:p.error('--window-dispatch requires --profile')
    source=a.source.resolve();runtime=a.runtime.resolve();out=a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(runtime):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ispc=compiler.with_name('ispc.exe')
    env=dict(os.environ);env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
    def run(args,label,stdout=None):
        with (out/(label+'.log')).open('w',encoding='utf-8') as log:
            if stdout:
                with stdout.open('w',encoding='utf-8') as f:done=subprocess.run(args,env=env,stdout=f,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            else:done=subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode:raise RuntimeError(label+' failed')
    fragments=[ROOT/'xpu2/batched_collect.ispc.inc',ROOT/'xpu2/batched_bridge.cc',ROOT/'xpu2/native_lambert_hook.ispc.inc',ROOT/'xpu2/native_lambert_queue.cc',ROOT/'xpu2/batched_patch.py',ROOT/'xpu2/deferred_patch.py',Path(__file__).resolve()]
    if a.profile:fragments += [ROOT/'xpu2/profile_patch.py',ROOT/'xpu2/profile_metrics.h']
    if a.window_dispatch:fragments += [ROOT/'xpu2/window_dispatch_patch.py']
    identities={str(f):sha(f) for f in fragments}
    bridge=out/'bridge.cc'
    if a.profile:
        from xpu2 import profile_patch
        code=profile_patch.apply((ROOT/'xpu2/native_lambert_queue.cc').read_text(),fragments[1].read_text(),(ROOT/'xpu2/profile_metrics.h').read_text())
        if a.window_dispatch:
            from xpu2 import window_dispatch_patch
            code=window_dispatch_patch.apply(code)
        bridge.write_text(code,encoding='utf-8')
    else:bridge.write_bytes(fragments[1].read_bytes())
    flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(ROOT/'xpu2'),'-I'+str(source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
    run([str(compiler),*flags,'-E',str(bridge),'-o',str(out/'bridge.ii')],'bridge-preprocess')
    dll=out/'xpu2_batched.dll';lib=out/'libxpu2_batched.dll.a'
    run([str(compiler),*flags,str(out/'bridge.ii'),'-shared','-Wl,--out-implib,'+str(lib),'-o',str(dll)],'bridge-compile')
    ninja=(source/'build/native-renderer-avx/build.ninja').read_text(encoding='utf-8')
    originals={}
    for name,relative in [('sampler','pbr/integrator/PathIntegratorUtil.ispc'),('lambert','shading/ispc/bsdf/BsdfLambert.ispc')]:
        original=source/'upstream/openmoonray/moonray/moonray/lib/rendering'/relative
        text=original.read_text(encoding='utf-8');originals[str(original)]=sha(original)
        if name=='sampler':text=batched_patch.sampler(text,fragments[0].read_text())
        else:text=batched_patch.lambert(text,fragments[2].read_text())
        code=out/(name+'.ispc');code.write_text(text,encoding='utf-8')
        stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and original.stem+'.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
        variables=dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)
        ff=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
        if '--opt=force-aligned-memory' in ff:ff.remove('--opt=force-aligned-memory')
        ff+=['-I'+str(original.parent)]
        print('Compiling '+name+' batched handoff',flush=True)
        run([str(ispc),*ff,'-E',str(code)],name+'-preprocess',out/(name+'.pp'))
        run([str(ispc),*ff,str(code),'--emit-obj','-o',str(out/(name+'.obj'))],name+'-compile')
        run([str(ispc),*ff,'-E',str(code)],name+'-recheck',out/(name+'-recheck.pp'))
        if sha(out/(name+'.pp'))!=sha(out/(name+'-recheck.pp')):raise ValueError('Header drift')
    manifest={'window_dispatch':a.window_dispatch,'profile':a.profile,'status':'incomplete','scope':'Retained-object native bounded batch handoff; native stack stays resident','runtime':str(runtime),'source_hashes':identities,'original_hashes':originals,'inputs':{},'compiler_sha256':sha(compiler),'ispc_sha256':sha(ispc),'bridge_sha256':sha(dll)}
    for label in ('control','trace'):
        shutil.copytree(runtime,out/label);shutil.copy2(dll,out/label/dll.name)
    for module,prior,replacement,replname in [('librendering_rndr.dll',a.pbr_build.resolve(),'PathIntegratorUtil.ispc.obj','sampler'),('librendering_shading.dll',a.shading_build.resolve(),'BsdfLambert.ispc.obj','lambert')]:
        prior_manifest=json.loads((prior/'build-inputs.json').read_text())
        if prior_manifest['status']!='built':raise ValueError('Prior link inputs incomplete')
        inputs=out/module;inputs.mkdir();frozen=[];records=[];index=None;mapping={}
        for item in prior_manifest['inputs']:
            old=prior/item['copy'];dest=inputs/old.name
            if sha(old)!=item['sha256']:raise ValueError('Retained object drift')
            shutil.copy2(old,dest)
            if sha(dest)!=item['sha256']:raise ValueError('Input copy mismatch')
            if Path(item['path']).name==replacement:index=len(frozen)
            mapping[str(old.resolve())]=str(dest)
            frozen.append(str(dest));records.append({'copy':str(dest.relative_to(out)),'sha256':sha(dest),'original':item['path']})
        if index is None:raise ValueError('Missing replacement object')
        manifest['inputs'][module]=records
        replacement_path=frozen[index]
        trace_replacements={}
        if module=='librendering_rndr.dll':
            trace_build=a.trace_build.resolve()
            trace_manifest=json.loads((trace_build/'build-inputs.json').read_text())
            if trace_manifest['status']!='built' or not trace_manifest['contributions']:raise ValueError('Unverified contribution trace build')
            manifest['trace_build_manifest_sha256']=sha(trace_build/'build-inputs.json')
            for object_name,filename in [('XPURayHandlers.cc.obj','trace.obj'),('PbrTLState.cc.obj','tls-trace.obj')]:
                original_object=trace_build/filename
                captured=sha(original_object);dest=out/('contribution-'+filename);shutil.copy2(original_object,dest)
                if sha(dest)!=captured or sha(original_object)!=captured:raise ValueError('Trace object drift')
                target=next(str(out/item['copy']) for item in records if Path(item['original']).name==object_name)
                trace_replacements[target]=str(dest)
                manifest.setdefault('trace_objects',{})[object_name]={'path':str(dest),'sha256':captured}
        old_rsp=shlex.split((prior/'control.rsp').read_text())
        frozen=[]
        for arg in old_rsp:
            if arg.startswith('-l'):frozen.append(arg)
            elif arg.startswith('-'):raise ValueError('Unhandled retained link flag '+arg)
            else:frozen.append(mapping[str(Path(arg).resolve())])
        index=frozen.index(replacement_path)
        frozen=[trace_replacements.get(v,v) for v in frozen]
        manifest.setdefault('link_flags',{})[module]=[v for v in frozen if v.startswith('-')]
        for label in ('control','trace'):
            args=frozen.copy()
            if label=='trace':args[index]=str(out/(replname+'.obj'));args.append(str(lib))
            rsp=out/(module+'-'+label+'.rsp');rsp.write_text('\n'.join('"'+v.replace('\\','/')+'"' for v in args),encoding='utf-8')
            print('Linking '+label+' '+module,flush=True)
            run([str(compiler),'-O3','-DNDEBUG','-shared','-o',str(out/label/module),'@'+str(rsp)],module+'-'+label)
            manifest[label+'_'+module]=sha(out/label/module)
    if identities!={str(f):sha(f) for f in fragments} or any(sha(Path(f))!=v for f,v in originals.items()):raise ValueError('Source drift')
    manifest['preprocessed_sha256']={name:sha(out/name) for name in ('bridge.ii','sampler.pp','lambert.pp')}
    manifest['status']='built';(out/'build-inputs.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
