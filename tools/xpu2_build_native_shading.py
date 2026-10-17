"""Build isolated retained-object control/probe shading DLLs; never rebuild shared source."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--runtime',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();source,runtime,out=a.source.resolve(),a.runtime.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(runtime):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    build=source/'build/native-renderer-avx'
    ninja=(build/'build.ninja').read_text(encoding='utf-8')
    stanza=next(s for s in ninja.split('\n\n') if s.startswith('build bin/librendering_shading.dll '))
    objects=stanza.splitlines()[0].split('CXX_SHARED_LIBRARY_LINKER__rendering_shading_Release ',1)[1].split(' | ',1)[0].split()
    libraries=shlex.split(next(l.split(' = ',1)[1] for l in stanza.splitlines() if l.startswith('  LINK_LIBRARIES =')))
    inputs=out/'inputs';inputs.mkdir()
    manifest=[];frozen=[];replacement=None
    for index,token in enumerate(objects+libraries):
        if token.startswith('-'):frozen.append(token);continue
        path=Path(token)
        if not path.is_absolute():path=build/path
        digest=sha(path);dest=inputs/(str(index)+'-'+path.name)
        shutil.copy2(path,dest)
        if sha(path)!=digest or sha(dest)!=digest:raise ValueError('Changing link input')
        manifest.append({'path':str(path),'copy':str(dest.relative_to(out)),'sha256':digest})
        if path.name=='BsdfLambert.ispc.obj':replacement=len(frozen)
        frozen.append(str(dest))
    if replacement is None:raise ValueError('Missing Lambert object')
    ispc_stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and 'BsdfLambert.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
    variables=dict(line.strip().split(' = ',1) for line in ispc_stanza.splitlines()[1:] if ' = ' in line)
    flags=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
    # Flat bridge arrays do not inherit the native SoA alignment guarantee.
    flags.remove('--opt=force-aligned-memory')
    original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/shading/ispc/bsdf/BsdfLambert.ispc'
    original_sha=sha(original)
    text=original.read_text(encoding='utf-8')
    anchor='    return LambertBsdfLobe_eval(lobe, slice, wi, &pdf);'
    if text.count(anchor)!=1:raise ValueError('Unexpected native sample layout')
    text='extern "C" void xpu2NativeLambert(uniform float input[], uniform float output[], uniform int count);\n'+text.replace(anchor,(ROOT/'xpu2/native_lambert_hook.ispc.inc').read_text(encoding='utf-8'))
    code=out/'BsdfLambert.ispc';code.write_text(text,encoding='utf-8')
    bridge=out/'bridge.cc';bridge.write_bytes((ROOT/'xpu2/native_lambert_bridge.cc').read_bytes())
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ispc=compiler.with_name('ispc.exe')
    flags+=['-I'+str(original.parent)]
    env=dict(os.environ);env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
    def run(args,label,stdout=None):
        with (out/(label+'.log')).open('w',encoding='utf-8') as log:
            if stdout:
                with stdout.open('w',encoding='utf-8') as dest:
                    done=subprocess.run(args,cwd=out,env=env,stdout=dest,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            else:done=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode:raise RuntimeError(label+' failed: '+str(out/(label+'.log')))
    print('Compiling isolated native Lambert hook',flush=True)
    run([str(ispc),*flags,'-E',str(code)],'ispc-preprocess',out/'lambert.pp')
    run([str(ispc),*flags,str(code),'--emit-obj','-o',str(out/'lambert.obj')],'ispc-compile')
    includes=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
    ccflags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(includes)]
    run([str(compiler),*ccflags,'-E',str(bridge),'-o',str(out/'bridge.ii')],'cpp-preprocess')
    run([str(compiler),*ccflags,'-c',str(out/'bridge.ii'),'-o',str(out/'bridge.obj')],'cpp-compile')
    report={'status':'incomplete','scope':'Retained shading objects plus isolated Lambert hook; no clean source/runtime rebuild',
            'source':str(source),'runtime':str(runtime),'source_sha256':original_sha,'inputs':manifest,
            'ispc_flags':flags,'compiler_sha256':sha(compiler),'ispc_compiler_sha256':sha(ispc),
            'hook_sha256':sha(code),'bridge_sha256':sha(bridge),'ispc_preprocessed_sha256':sha(out/'lambert.pp'),
            'cpp_preprocessed_sha256':sha(out/'bridge.ii')}
    for label in ('control','probe'):
        print('Linking '+label+' shading DLL',flush=True)
        folder=out/label;shutil.copytree(runtime,folder)
        args=frozen.copy()
        if label=='probe':args[replacement]=str(out/'lambert.obj');args.append(str(out/'bridge.obj'))
        rsp=out/(label+'.rsp');rsp.write_text('\n'.join('"'+arg.replace('\\','/')+'"' for arg in args),encoding='utf-8')
        run([str(compiler),'-O3','-DNDEBUG','-shared','-o',str(folder/'librendering_shading.dll'),'@'+str(rsp)],'link-'+label)
        report[label+'_dll_sha256']=sha(folder/'librendering_shading.dll')
    run([str(ispc),*flags,'-E',str(code)],'ispc-recheck',out/'lambert.recheck.pp')
    run([str(compiler),*ccflags,'-E',str(bridge),'-o',str(out/'bridge.recheck.ii')],'cpp-recheck')
    if sha(out/'lambert.pp')!=sha(out/'lambert.recheck.pp') or sha(out/'bridge.ii')!=sha(out/'bridge.recheck.ii') or sha(original)!=original_sha:raise ValueError('Source/header drift')
    for item in manifest:
        if sha(Path(item['path']))!=item['sha256']:raise ValueError('Link input drift')
    report['status']='built'
    (out/'build-inputs.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Built isolated shading integration probe',flush=True)

if __name__=='__main__':main()
