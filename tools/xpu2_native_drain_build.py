"""Build isolated native frame-drain hooks against retained native objects."""
import argparse,json,os,shlex,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment

def patch(name,text):
    def edit(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Native hook anchor drift: '+old[:90])
        text=text.replace(old,new)
    if name=='XPURayHandlers':
        anchor='    unsigned char *isOccluded = accel->getOutputOcclusionBuf(tls->mThreadIdx);'
        edit(anchor,anchor+'\n    xpu2drain::capture(accel,tls->mThreadIdx,numRays,gpuRays,isOccluded);')
    elif name=='RenderContext':
        for signature,label in [('RenderContext::startFrame(const bool simulationMode)','start_frame'),('RenderContext::updateScene(const std::string& filename)','update_scene'),('RenderContext::updateScene(const std::string& manifest, const std::string& payload)','update_scene_binary'),('RenderContext::updateGeometry(const std::vector<moonray::ObjectData>& updateData)','update_geometry')]:
            edit(signature+'\n{',signature+'\n{\n    xpu2drain::drain("'+label+'");')
        edit('    mDriver->startFrame(frameState);','    xpu2drain::openFrame();\n    mDriver->startFrame(frameState);')
        edit('    mDriver->stopFrame();','    mDriver->stopFrame();\n    xpu2drain::drain("post_frame");')
        edit('    // There is an issue NOVAVP-12','    xpu2drain::drain("context_teardown");\n    // There is an issue NOVAVP-12')
    elif name=='GeometryManager':
        edit('{\n    mGPUAccelerator.reset();','{\n    xpu2drain::drain("accelerator_rebuild");\n    mGPUAccelerator.reset();')
    else:raise ValueError('Unknown native source')
    return '#include <cstring>\n#include "native_scene_drain.h"\n'+text

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','frozen-build','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();source,base,out=a.source.resolve(),a.frozen_build.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(base):p.error('Isolated build required')
    out.mkdir(parents=True,exist_ok=False);manifest=json.loads((base/'build-inputs.json').read_text())
    if manifest['status']!='built':raise ValueError('Missing frozen inputs')
    for item in manifest['inputs']:
        if digest_file(base/item['copy'])!=item['sha256']:raise ValueError('Frozen input changed')
    runtime=out/'runtime';shutil.copytree(base/'control',runtime)
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ninja=compiler.with_name('ninja.exe');build=source/'build/native-renderer-avx'
    env=environment(runtime,out);env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
    header=ROOT/'xpu2/native_scene_drain.h';before=digest_file(header)
    report=dict(status='incomplete',frozen_manifest_sha256=digest_file(base/'build-inputs.json'),header_sha256=before,sources=[])
    targets=[('XPURayHandlers','pbr/handlers/XPURayHandlers.cc','pbr/CMakeFiles/rendering_pbr_objects.dir/handlers/XPURayHandlers.cc.obj'),('RenderContext','rndr/RenderContext.cc','rndr/CMakeFiles/rendering_rndr.dir/RenderContext.cc.obj'),('GeometryManager','rt/GeometryManager.cc','rt/CMakeFiles/rendering_rt_objects.dir/GeometryManager.cc.obj')]
    def run(args,label):
        print(label,flush=True)
        with (out/(label+'.log')).open('w') as log:d=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        if d.returncode:raise ValueError(label+' failed')
    try:
        lines=(base/'control.rsp').read_text().splitlines()
        for name,path,target in targets:
            original=source/'upstream/openmoonray/moonray/moonray/lib/rendering'/path;held=digest_file(original);cc=out/(name+'.cc');cc.write_text(patch(name,original.read_text()))
            line=subprocess.run([str(ninja),'-t','commands','moonray/lib/rendering/'+target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
            flags=shlex.split(line);flags=flags[:flags.index('-MD')]+['-iquote',str(original.parent),'-I'+str(ROOT/'xpu2'),'-I'+str(source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
            pp=out/(name+'.ii');obj=out/(name+'.obj')
            run([*flags,'-E',str(cc),'-o',str(pp)],'preprocess-'+name)
            run([*flags,'-c',str(pp),'-o',str(obj)],'compile-'+name)
            if held!=digest_file(original):raise ValueError('Source drift')
            report['sources'].append(dict(name=name,source=str(original),sha256=held,preprocessed_sha256=digest_file(pp),object_sha256=digest_file(obj)))
            anchor=[x for x in lines if x.strip().strip('"').endswith('-'+name+'.cc.obj')]
            if len(anchor)!=1:raise ValueError('Link anchor drift')
            lines=['"'+str(obj).replace('\\','/')+'"' if x in anchor else x for x in lines]
        rsp=out/'link.rsp';rsp.write_text('\n'.join(lines));run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(rsp)],'link')
        if digest_file(header)!=before:raise ValueError('Header drift')
        report.update(status='built',dll_sha256=digest_file(runtime/'librendering_rndr.dll'))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
