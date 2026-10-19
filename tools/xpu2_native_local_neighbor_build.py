"""Build bounded local-neighbor selection into a frozen coordination runtime."""
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
  pinned={**m['source_hashes'],**m['native_hashes'],str(base/'report.json'):digest_file(base/'report.json'),str(base/'link.rsp'):digest_file(base/'link.rsp'),str(base/'PathIntegratorUtil.cc'):digest_file(base/'PathIntegratorUtil.cc'),str(ROOT/'xpu2/native_local_tile_policy.h'):digest_file(ROOT/'xpu2/native_local_tile_policy.h'),str(Path(__file__).resolve()):digest_file(Path(__file__))}
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
  # Retain all local generated includes; only queue selection and its header change.
  for src in list(base.glob('*.h'))+list(base.glob('*.inc')):
   pinned[str(src)]=digest_file(src);shutil.copyfile(src,out/src.name)
  shutil.copyfile(ROOT/'xpu2/native_local_tile_policy.h',out/'native_tile_policy.h')
  q=(out/'early_queue.inc').read_text(encoding='utf-8')
  q=once(q,'        tilePolicy.neighbor=tp && !std::strcmp(tp,"neighbor");','''        tilePolicy.neighbor=tp && !std::strcmp(tp,"neighbor");
        const char* bound=std::getenv("XPU2_NEIGHBOR_SCAN");
        tilePolicy.scanLimit=bound && !std::strcmp(bound,"16")?16:bound && !std::strcmp(bound,"8")?8:0;''')
  (out/'early_queue.inc').write_text(q,encoding='utf-8')
  profile=out/'native_gpu_shading.h';pf=profile.read_text(encoding='utf-8')
  pf=once(pf,r'\"batch_limit\":%u',r'\"scan_limit\":%zu,\"batch_limit\":%u')
  pf=once(pf,'p.neighbor?"true":"false",q.batchLimit','p.neighbor?"true":"false",p.scanLimit,q.batchLimit')
  profile.write_text(pf,encoding='utf-8')
  cc=out/'PathIntegratorUtil.cc';shutil.copyfile(base/'PathIntegratorUtil.cc',cc)
  compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';build=source/'build/native-renderer-avx'
  env=environment(runtime,out);env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
  target='moonray/lib/rendering/pbr/CMakeFiles/rendering_pbr_objects.dir/integrator/PathIntegratorUtil.cc.obj'
  command=subprocess.run([str(compiler.with_name('ninja.exe')),'-t','commands',target],cwd=build,capture_output=True,text=True,check=True).stdout.splitlines()[-1]
  flags=shlex.split(command);flags=flags[:flags.index('-MD')]+['-iquote',str(source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/integrator'),'-I'+str(ROOT/'xpu2'),'-I'+str(source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
  flags=flags[:1]+['-I'+str(base/'overrides')]+flags[1:]
  def run(args,label):
   print(label,flush=True)
   with (out/(label+'.log')).open('w') as log:r=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
   if r.returncode:raise ValueError(label+' failed')
  pp=out/'PathIntegratorUtil.ii';obj=out/'PathIntegratorUtil.obj'
  run([*flags,'-E',str(cc),'-o',str(pp)],'neighbor-preprocess');run([*flags,'-c',str(pp),'-o',str(obj)],'neighbor-compile')
  rsp=(base/'link.rsp').read_text();old='"'+str(base/'PathIntegratorUtil.obj').replace('\\','/')+'"'
  rsp=once(rsp,old,'"'+str(obj).replace('\\','/')+'"');(out/'link.rsp').write_text(rsp)
  run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(out/'link.rsp')],'neighbor-link')
  for f,h in pinned.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  verify(base/'runtime',held)
  report.update(status='built',source_hashes=pinned,native_hashes={},dll_sha256=digest_file(runtime/'librendering_rndr.dll'),objects={'PathIntegratorUtil':digest_file(obj)},preprocessed={'PathIntegratorUtil':digest_file(pp)},experimental_only=True,base_sha256=digest_file(base/'report.json'))
 except Exception as e:report['error']=str(e)
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
