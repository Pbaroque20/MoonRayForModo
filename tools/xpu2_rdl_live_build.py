"""Build opt-in native index update hooks in an isolated retained XPU runtime."""
import argparse,json,os,shlex,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment

def patch(text):
    def edit(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Native hook anchor drift: '+old[:90])
        text=text.replace(old,new)
    old='''        if (modoSceneMemory(filename)) { scene_rdl2::rdl2::AsciiReader reader(*mSceneContext); reader.fromString(modoReadSceneMemory(filename)); }
        else readSceneFromFile(filename, *mSceneContext);'''
    new='''        if (xpu2::rdllive::enabled()) {
            xpu2::rdllive::update(*mSceneContext,mRendering,[&](scene_rdl2::rdl2::SceneContext& source){
                if(modoSceneMemory(filename)){scene_rdl2::rdl2::AsciiReader reader(source);reader.fromString(modoReadSceneMemory(filename));}
                else readSceneFromFile(filename,source);
            });
        } else {
'''+old+'''
        }'''
    edit(old,new)
    old='''        scene_rdl2::rdl2::BinaryReader reader(*mSceneContext);
        reader.fromBytes(manifest, payload);'''
    edit(old,'''        if (xpu2::rdllive::enabled()) {
            xpu2::rdllive::update(*mSceneContext,mRendering,[&](scene_rdl2::rdl2::SceneContext& source){
                scene_rdl2::rdl2::BinaryReader reader(source);reader.fromBytes(manifest,payload);
            });
        } else {
'''+old+'''
        }''')
    edit('RenderContext::startFrame(const bool simulationMode)\n{','RenderContext::startFrame(const bool simulationMode)\n{\n    xpu2::rdllive::healthy(*mSceneContext);')
    edit('RenderContext::~RenderContext()\n{','RenderContext::~RenderContext()\n{\n    xpu2::rdllive::forget(mSceneContext.get());')
    edit('RenderContext::updateGeometry(const std::vector<moonray::ObjectData>& updateData)\n{','RenderContext::updateGeometry(const std::vector<moonray::ObjectData>& updateData)\n{\n    xpu2::rdllive::healthy(*mSceneContext);\n    xpu2::rdllive::forget(mSceneContext.get());')
    return '#include "rdl_live_bridge.h"\n'+text

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','frozen-build','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();source,base,out=a.source.resolve(),a.frozen_build.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(base):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete')
    try:
        manifest=json.loads((base/'build-inputs.json').read_text());assert manifest['status']=='built'
        for item in manifest['inputs']:
            if digest_file(base/item['copy'])!=item['sha256']:raise ValueError('Frozen link input drift')
        runtime=out/'runtime';shutil.copytree(base/'control',runtime)
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ninja=compiler.with_name('ninja.exe');build=source/'build/native-renderer-avx'
        env=environment(runtime,out);env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
        files=[ROOT/'xpu2'/s for s in ('rdl_live_bridge.h','rdl_scene_index.h','indexed_scene.h','persistent_map.h')]+[Path(__file__).resolve()]
        hashes={str(f):digest_file(f) for f in files}
        original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/rndr/RenderContext.cc';originalHash=digest_file(original)
        cc=out/'RenderContext.cc';cc.write_text(patch(original.read_text()))
        target='moonray/lib/rendering/rndr/CMakeFiles/rendering_rndr.dir/RenderContext.cc.obj'
        line=subprocess.run([str(ninja),'-t','commands',target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
        flags=shlex.split(line);flags=flags[:flags.index('-MD')]+['-fno-fast-math','-iquote',str(original.parent),'-I'+str(ROOT/'xpu2')]
        def run(args,label):
            print(label,flush=True)
            with (out/(label+'.log')).open('w') as log:done=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            if done.returncode:raise ValueError(label+' failed')
        pp=out/'RenderContext.ii';obj=out/'RenderContext.obj'
        run([*flags,'-E',str(cc),'-o',str(pp)],'preprocess');run([*flags,'-c',str(pp),'-o',str(obj)],'compile')
        lines=(base/'control.rsp').read_text().splitlines();anchor=[x for x in lines if x.strip().strip('"').endswith('-RenderContext.cc.obj')]
        if len(anchor)!=1:raise ValueError('Link anchor drift')
        lines=['"'+str(obj).replace('\\','/')+'"' if x in anchor else x for x in lines]
        rsp=out/'link.rsp';rsp.write_text('\n'.join(lines));run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(rsp)],'link')
        if hashes!={str(f):digest_file(f) for f in files} or originalHash!=digest_file(original):raise ValueError('Source drift')
        report.update(status='built',source_hashes=hashes,native_source_sha256=originalHash,preprocessed_sha256=digest_file(pp),object_sha256=digest_file(obj),dll_sha256=digest_file(runtime/'librendering_rndr.dll'),frozen_manifest_sha256=digest_file(base/'build-inputs.json'))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
