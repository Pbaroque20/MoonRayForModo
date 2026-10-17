"""Build an isolated diagnostic DLL from a frozen copy of existing link inputs.

This is NOT a clean source build or a distributable runtime. The retained build
may differ from the pinned runtime; the runner must verify trace-off controls.
Ninja is queried only with -t commands. It is never allowed to build in source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--runtime',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--origins',action='store_true',help='Add copied-ray origin variants; diagnostic single-thread runs only')
    p.add_argument('--contributions',action='store_true',help='Also trace queued radiance and shadow contributions')
    a=p.parse_args()
    source,runtime,out=a.source.resolve(),a.runtime.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(runtime):
        p.error('Output must be isolated from source and reference runtime')
    out.mkdir(parents=True,exist_ok=False)
    build=source/'build/native-renderer-avx'
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
    ninja=compiler.with_name('ninja.exe')
    original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/handlers/XPURayHandlers.cc'
    target='moonray/lib/rendering/pbr/CMakeFiles/rendering_pbr_objects.dir/handlers/XPURayHandlers.cc.obj'
    original_hash=sha(original)
    content=original.read_text(encoding='utf-8')
    anchor='#if 0 // debugging code'
    if content.count(anchor)!=1:raise ValueError('Unknown source layout')
    injected='#include <cstdio>\n#include <cstdlib>\n#include <cstring>\n#include <mutex>\n'+content.replace(anchor,(ROOT/'xpu2/ray_compare.inc').read_text(encoding='utf-8')+'\n'+anchor)
    if a.contributions:
        shadow_anchor='        BundledOcclRay &occlRay = rays[i];'
        if injected.count(shadow_anchor)!=1:raise ValueError('Unknown shadow source layout')
        injected=injected.replace(shadow_anchor,shadow_anchor+'\n'+(ROOT/'xpu2/shadow_compare.inc').read_text(encoding='utf-8'))
    if a.origins:
        anchor='    unsigned char *isOccluded = accel->getOutputOcclusionBuf(tls->mThreadIdx);'
        if injected.count(anchor)!=1:raise ValueError('Unknown GPU shadow result layout')
        injected=injected.replace(anchor,anchor+'\n'+(ROOT/'xpu2/origin_probe.inc').read_text(encoding='utf-8'))
    injected=(ROOT/'xpu2/trace_output.h').read_text(encoding='utf-8')+'\n'+injected.replace('std::fprintf(stderr,','std::fprintf(xpu2TraceOutput(),')
    (out/'XPURayHandlers.cc').write_text(injected,encoding='utf-8')
    compile_line=subprocess.run([str(ninja),'-t','commands',target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
    compile_args=shlex.split(compile_line)
    compile_args=compile_args[:compile_args.index('-MD')]+['-iquote',str(original.parent),'-o',str(out/'trace.obj'),'-c',str(out/'XPURayHandlers.cc')]
    extra=[]
    if a.contributions:
        tls=original.parents[1]/'core/PbrTLState.cc'
        tls_content=tls.read_text(encoding='utf-8')
        for anchor,fragment in [('    mRadianceQueue->addEntries(mTopLevelTls, numEntries, entries, mArena);','queued_radiance.inc'),
                                ('    if (MNRY_VERIFY(mFs)->mExecutionMode == mcrt_common::ExecutionMode::XPU) {','queued_shadow.inc')]:
            if fragment=='queued_shadow.inc':
                start=tls_content.index('TLState::addOcclusionQueueEntries(')
                index=tls_content.index(anchor,start)
                tls_content=tls_content[:index]+(ROOT/'xpu2'/fragment).read_text(encoding='utf-8')+'\n'+tls_content[index:]
            else:
                if tls_content.count(anchor)!=1:raise ValueError('Unknown radiance source layout')
                tls_content=tls_content.replace(anchor,(ROOT/'xpu2'/fragment).read_text(encoding='utf-8')+'\n'+anchor)
        tls_content=(ROOT/'xpu2/trace_output.h').read_text(encoding='utf-8')+'\n#include <cstring>\n'+tls_content.replace('std::fprintf(stderr,','std::fprintf(xpu2TraceOutput(),')
        tls_out=out/'PbrTLState.cc';tls_out.write_text(tls_content,encoding='utf-8')
        tls_target=target.replace('handlers/XPURayHandlers','core/PbrTLState')
        command=shlex.split(subprocess.run([str(ninja),'-t','commands',tls_target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1])
        command=command[:command.index('-MD')]+['-iquote',str(tls.parent),'-o',str(out/'tls-trace.obj'),'-c',str(tls_out)]
        extra.append({'target':tls_target,'source':str(tls),'source_sha256':sha(tls),'instrumented_sha256':sha(tls_out),'object':str(out/'tls-trace.obj'),'command':command})
    lines=(build/'build.ninja').read_text(encoding='utf-8').splitlines()
    i=next(i for i,line in enumerate(lines) if line.startswith('build bin/librendering_rndr.dll '))
    # Explicit object dependencies precede the first implicit-dependency pipe.
    object_text=lines[i].split('CXX_SHARED_LIBRARY_LINKER__rendering_rndr_Release ',1)[1].split(' | ',1)[0]
    objects=object_text.split()
    if any('$' in token for token in objects):raise ValueError('Unexpected escaped object path')
    library_text=next(line.split(' = ',1)[1] for line in lines[i+1:i+16] if line.startswith('  LINK_LIBRARIES ='))
    libraries=shlex.split(library_text)
    inputs=out/'inputs';inputs.mkdir()
    frozen=[]; manifest=[]; replacement=None
    for index,token in enumerate(objects+libraries):
        if token.startswith('-'):
            frozen.append(token);continue
        path=Path(token)
        if not path.is_absolute():path=build/path
        before=sha(path)
        dest=inputs/(str(index)+'-'+path.name)
        shutil.copy2(path,dest)
        if sha(path)!=before or sha(dest)!=before:raise ValueError('Input changed during capture: '+str(path))
        manifest.append({'path':str(path),'copy':str(dest.relative_to(out)),'sha256':before})
        frozen.append(str(dest))
        if token==target:replacement=len(frozen)-1
    if replacement is None:raise ValueError('Missing handler object')
    env=dict(os.environ);env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
    def run(args,name):
        with (out/(name+'.log')).open('w',encoding='utf-8') as stream:
            done=subprocess.run(args,cwd=out,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode:raise RuntimeError(name+' failed: '+str(out/(name+'.log')))
    report={'source':str(source),'source_sha256':original_hash,'instrumented_sha256':sha(out/'XPURayHandlers.cc'),
            'scope':'Retained native objects; not a clean source rebuild','inputs':manifest,
            'compile_command':compile_args,'extra_compiles':extra,'contributions':a.contributions,'origins':a.origins}
    (out/'build-inputs.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Compiling diagnostic handler',flush=True)
    run(compile_args,'compile')
    for index,item in enumerate(extra):run(item['command'],'compile-extra-'+str(index))
    for label in ('control','trace'):
        print('Linking '+label,flush=True)
        folder=out/label;shutil.copytree(runtime,folder)
        args=frozen.copy()
        if label=='trace':
            args[replacement]=str(out/'trace.obj')
            for item in extra:args[objects.index(item['target'])]=item['object']
        rsp=out/(label+'.rsp')
        rsp.write_text('\n'.join('"'+arg.replace('\\','/')+'"' for arg in args),encoding='utf-8')
        run([str(compiler),'-O3','-DNDEBUG','-shared','-o',str(folder/'librendering_rndr.dll'),'@'+str(rsp)],'link-'+label)
        report[label+'_dll_sha256']=sha(folder/'librendering_rndr.dll')
    if sha(original)!=original_hash:raise ValueError('Source changed while building')
    # Detect a concurrent source build replacing any retained inputs.
    for item in manifest:
        if sha(Path(item['path']))!=item['sha256']:raise ValueError('Build input changed: '+item['path'])
    for item in extra:
        if sha(Path(item['source']))!=item['source_sha256']:raise ValueError('Additional source changed')
    report['status']='built'
    (out/'build-inputs.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Built isolated control and trace runtimes',flush=True)

if __name__=='__main__':main()
