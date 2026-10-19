"""Build a diagnostic hold point into a frozen owned-chunk candidate only."""
import argparse,json,os,shlex,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2_baseline import environment
from xpu2.native_gpu_paths import once

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('source','base','output'):p.add_argument('--'+k,type=Path,required=True)
 a=p.parse_args();source,base,out=(getattr(a,k).resolve() for k in ('source','base','output'))
 if out.is_relative_to(source) or out.is_relative_to(base):p.error('Isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete'}
 try:
  m=json.loads((base/'report.json').read_text());assert m['status']=='built'
  pinned={**m['source_hashes'],**m['native_hashes'],str(base/'report.json'):digest_file(base/'report.json'),str(base/'link.rsp'):digest_file(base/'link.rsp'),str(base/'ShadeBundleHandler.cc'):digest_file(base/'ShadeBundleHandler.cc'),str(Path(__file__).resolve()):digest_file(Path(__file__))}
  for line in (base/'link.rsp').read_text().splitlines():
   f=Path(line.strip().strip(chr(34)))
   if f.is_absolute() and f.is_file():pinned[str(f)]=digest_file(f)
  for name,h in m['objects'].items():
   f=base/(name+'.obj')
   if digest_file(f)!=h:raise ValueError('Base object drift '+name)
   pinned[str(f)]=h
  for f,h in pinned.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  held=inventory(base/'runtime');runtime=out/'runtime';shutil.copytree(base/'runtime',runtime)
  code=(base/'ShadeBundleHandler.cc').read_text(encoding='utf-8')
  code='#include <atomic>\n#include <chrono>\n#include <thread>\n#include <cstdio>\n#include <cstdlib>\n#include <stdexcept>\n'+code
  anchor='            for(unsigned i=0;i<prepared;++i){'
  gate=r'''
            // Diagnostic only: retain a whole group until the normal session cancel arrives.
            if(prepared>=2){
                static std::atomic<bool> gateUsed{false};
                const char* path=std::getenv("XPU2_OWNED_CANCEL_GATE");
                if(path && !gateUsed.exchange(true)){
                    FILE* file=std::fopen(path,"w");if(!file)throw std::runtime_error("Cannot write owned cancel gate");
                    std::fprintf(file,"{\"prepared\":%u,\"depth\":%u}\n",prepared,xpu2Depth);std::fclose(file);
                    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
                    while(!pbrTls->isCanceled() && std::chrono::steady_clock::now()<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(1));
                    if(!pbrTls->isCanceled())throw std::runtime_error("Owned cancel gate timed out");
                }
            }
'''
  code=once(code,anchor,gate+anchor);cc=out/'ShadeBundleHandler.cc';cc.write_text(code,encoding='utf-8')
  compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';build=source/'build/native-renderer-avx'
  env=environment(runtime,out);env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
  target='moonray/lib/rendering/pbr/CMakeFiles/rendering_pbr_objects.dir/handlers/ShadeBundleHandler.cc.obj'
  command=subprocess.run([str(compiler.with_name('ninja.exe')),'-t','commands',target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
  flags=shlex.split(command);flags=flags[:flags.index('-MD')]+['-iquote',str(source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/handlers'),'-I'+str(ROOT/'xpu2')]
  flags=flags[:1]+['-I'+str(base/'overrides')]+flags[1:]
  def run(args,label):
   print(label,flush=True)
   with (out/(label+'.log')).open('w') as log:r=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
   if r.returncode:raise ValueError(label+' failed')
  pp=out/'ShadeBundleHandler.ii';obj=out/'ShadeBundleHandler.obj'
  run([*flags,'-E',str(cc),'-o',str(pp)],'gate-preprocess');run([*flags,'-c',str(pp),'-o',str(obj)],'gate-compile')
  rsp=(base/'link.rsp').read_text();old='"'+str(base/'ShadeBundleHandler.obj').replace('\\','/')+'"'
  rsp=once(rsp,old,'"'+str(obj).replace('\\','/')+'"');(out/'link.rsp').write_text(rsp)
  run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(out/'link.rsp')],'gate-link')
  for f,h in pinned.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  verify(base/'runtime',held)
  report.update(status='built',source_hashes=pinned,native_hashes={},dll_sha256=digest_file(runtime/'librendering_rndr.dll'),objects={'ShadeBundleHandler':digest_file(obj)},preprocessed={'ShadeBundleHandler':digest_file(pp)},diagnostic_only=True,base_sha256=digest_file(base/'report.json'))
 except Exception as e:report['error']=str(e)
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
