"""Build an opt-in terminal-radiance continuation in a copied native XPU runtime."""
import argparse,json,os,shlex,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment

def patch(name,text):
    def edit(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Native hook drift: '+name+' '+old[:60])
        text=text.replace(old,new)
    if name=='Film':
        anchor='    Film* const film = static_cast<Film*>(userData);\n    if (film->mRenderBufOdd) {'
        edit(anchor,'    Film* const film = static_cast<Film*>(userData);\n    if (xpu2::nativefilm::defer(tls,numEntries,entries,film,film->mRenderBufOdd!=nullptr)) return;\n    if (film->mRenderBufOdd) {')
        anchor='namespace moonray {'
        edit(anchor,'#include "native_deferred_film.inc"\n\n'+anchor)
    elif name=='RenderFrame':
        anchor='    Film *film = driver->mFilm;'
        edit(anchor,anchor+'\n    xpu2::nativefilm::begin();')
    elif name=='RenderFramePasses':
        anchor='                processedSampleTotal += static_cast<unsigned long long>(renderTiles(driver, topLevelTls, group));'
        edit(anchor,anchor+'\n                xpu2::nativefilm::drain(topLevelTls,driver->mFilm);')
        anchor='            double timeQueueDraining = scene_rdl2::util::getSeconds(); // get current time'
        edit(anchor,'            xpu2::nativefilm::drain(topLevelTls,driver->mFilm);\n'+anchor)
    elif name=='RenderContext':
        anchor='    mDriver->stopFrame();'
        edit(anchor,anchor+'\n    xpu2::nativefilm::finish();')
    if name!='Film':text='#include "native_deferred_film.h"\n'+text
    return text

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
        files=[ROOT/'xpu2'/s for s in ('deferred_film.h','native_deferred_film.h','native_deferred_film.inc')]+[Path(__file__).resolve()]
        hashes={str(f):digest_file(f) for f in files};native={};objects={};preprocessed={}
        def run(args,label):
            print(label,flush=True)
            with (out/(label+'.log')).open('w') as log:
                done=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            if done.returncode:raise ValueError(label+' failed')
        for name in ('Film','RenderFrame','RenderFramePasses','RenderContext'):
            original=source/('upstream/openmoonray/moonray/moonray/lib/rendering/rndr/'+name+'.cc');native[str(original)]=digest_file(original)
            cc=out/(name+'.cc');cc.write_text(patch(name,original.read_text(encoding='utf-8')),encoding='utf-8')
            target='moonray/lib/rendering/rndr/CMakeFiles/rendering_rndr.dir/'+name+'.cc.obj'
            command=subprocess.run([str(compiler.with_name('ninja.exe')),'-t','commands',target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
            flags=shlex.split(command);flags=flags[:flags.index('-MD')]+['-iquote',str(original.parent),'-I'+str(ROOT/'xpu2')]
            pp=out/(name+'.ii');obj=out/(name+'.obj')
            run([*flags,'-E',str(cc),'-o',str(pp)],name+'-preprocess')
            run([*flags,'-c',str(pp),'-o',str(obj)],name+'-compile')
            objects[name]=digest_file(obj);preprocessed[name]=digest_file(pp)
        lines=(base/'control.rsp').read_text().splitlines()
        for name in objects:
            anchor=[s for s in lines if s.strip().strip('"').endswith('-'+name+'.cc.obj')]
            if len(anchor)!=1:raise ValueError('Link anchor drift '+name)
            lines=['"'+str(out/(name+'.obj')).replace('\\','/')+'"' if s in anchor else s for s in lines]
        rsp=out/'link.rsp';rsp.write_text('\n'.join(lines));run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(rsp)],'link')
        if any(digest_file(Path(f))!=h for f,h in {**hashes,**native}.items()):raise ValueError('Source drift')
        report.update(status='built',source_hashes=hashes,native_hashes=native,objects=objects,preprocessed=preprocessed,dll_sha256=digest_file(runtime/'librendering_rndr.dll'),base_sha256=digest_file(base/'build-inputs.json'))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
