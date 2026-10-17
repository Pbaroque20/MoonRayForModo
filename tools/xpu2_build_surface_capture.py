"""Build an isolated native surface-state capture DLL from retained objects.

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
    a=p.parse_args()
    source,runtime,out=a.source.resolve(),a.runtime.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(runtime):
        p.error('Output must be isolated from source and reference runtime')
    out.mkdir(parents=True,exist_ok=False)
    build=source/'build/native-renderer-avx'
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
    ninja=compiler.with_name('ninja.exe')
    original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/handlers/ShadeBundleHandler.cc'
    target='moonray/lib/rendering/pbr/CMakeFiles/rendering_pbr_objects.dir/handlers/ShadeBundleHandler.cc.obj'
    original_hash=sha(original)
    content=original.read_text(encoding='utf-8')
    anchor='namespace moonray {'
    if content.count(anchor)!=1:raise ValueError('Unknown namespace layout')
    header=ROOT/'xpu2/native_surface_capture.h'
    content=content.replace(anchor,header.read_text(encoding='utf-8')+'\n'+anchor,1)
    anchor='        // Convert AOS RayState objects into SOA bundles.'
    if content.count(anchor)!=1:raise ValueError('Unknown capture entry')
    content=content.replace(anchor,'        auto xpu2Copies = xpu2::captureSurfaces(workLoadSize, rayStates, presences);\n'+anchor)
    anchor='        pbrTls->freeRayStates(workLoadSize, rayStates);'
    if content.count(anchor)!=1:raise ValueError('Unknown ray release boundary')
    content=content.replace(anchor,anchor+'\n        xpu2::publishSurfaceCopies(xpu2Copies);')
    code=out/'ShadeBundleHandler.cc';code.write_text(content,encoding='utf-8')
    compile_line=subprocess.run([str(ninja),'-t','commands',target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
    args=shlex.split(compile_line)
    flags=args[1:args.index('-MD')]+['-iquote',str(original.parent)]
    compile_args=[str(compiler),*flags,'-o',str(out/'trace.obj'),'-c',str(out/'handler.ii')]
    extra=[]
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
    report={'source':str(source),'source_sha256':original_hash,'instrumented_sha256':sha(code),'header_sha256':sha(header),
            'scope':'Retained native objects; not a clean source rebuild','inputs':manifest,
            'compile_command':compile_args,'compiler_sha256':sha(compiler)}
    (out/'build-inputs.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Compiling native surface capture',flush=True)
    run([str(compiler),*flags,'-E',str(code),'-o',str(out/'handler.ii')],'preprocess')
    report['preprocessed_sha256']=sha(out/'handler.ii')
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
    run([str(compiler),*flags,'-E',str(code),'-o',str(out/'handler-recheck.ii')],'preprocess-recheck')
    if sha(out/'handler-recheck.ii')!=report['preprocessed_sha256'] or sha(header)!=report['header_sha256']:raise ValueError('Capture header drift')
    report['status']='built'
    (out/'build-inputs.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Built isolated control and trace runtimes',flush=True)

if __name__=='__main__':main()
