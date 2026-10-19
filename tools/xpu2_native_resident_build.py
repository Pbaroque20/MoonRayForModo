"""Build per-flight typed and versioned GPU-resident shading records."""
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
  pinned={**m['source_hashes'],**m['native_hashes'],str(base/'report.json'):digest_file(base/'report.json'),str(base/'link.rsp'):digest_file(base/'link.rsp'),str(base/'PathIntegratorUtil.cc'):digest_file(base/'PathIntegratorUtil.cc'),str(ROOT/'xpu2/native_resident_records.py'):digest_file(ROOT/'xpu2/native_resident_records.py'),str(Path(__file__).resolve()):digest_file(Path(__file__))}
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
  from xpu2.native_resident_records import patch
  pinned[str(ROOT/'xpu2/native_resident_records.py')]=digest_file(ROOT/'xpu2/native_resident_records.py')
  rsp=(base/'link.rsp').read_text()
  linked=[Path(line.strip().strip(chr(34))) for line in rsp.splitlines()]
  old_ispc=next(f for f in linked if f.name=='PathIntegratorUtil-ispc.obj')
  ispc_source=old_ispc.with_name('PathIntegratorUtil.ispc')
  pinned[str(ispc_source)]=digest_file(ispc_source)
  shutil.copyfile(ispc_source,out/'PathIntegratorUtil.ispc')
  bundled_obj=next(f for f in linked if f.name=='PathIntegratorBundled-ispc.obj')
  bundled_source=bundled_obj.with_name('PathIntegratorBundled.ispc')
  pinned[str(bundled_source)]=digest_file(bundled_source)
  shutil.copyfile(bundled_source,out/'PathIntegratorBundled.ispc')
  admission_header=ROOT/'xpu2/native_material_admission.isph'
  pinned[str(admission_header)]=digest_file(admission_header)
  shutil.copyfile(admission_header,out/admission_header.name)
  pinned[str(ROOT/'xpu2/resident_records.h')]=digest_file(ROOT/'xpu2/resident_records.h')
  patch(out)
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
  run([*flags,'-E',str(cc),'-o',str(pp)],'sample-preprocess');run([*flags,'-c',str(pp),'-o',str(obj)],'sample-compile')
  ispc_objects={};ispc_preprocessed={}
  for header in (source/'upstream/openmoonray/moonray/moonray/lib/rendering').rglob('*.isph'):pinned[str(header)]=digest_file(header)
  ninja=(build/'build.ninja').read_text()
  for name,old_object in (('PathIntegratorUtil',old_ispc),('PathIntegratorBundled',bundled_obj)):
   original=source/('upstream/openmoonray/moonray/moonray/lib/rendering/pbr/integrator/'+name+'.ispc')
   stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and name+'.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
   variables=dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)
   iflags=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
   if '--opt=force-aligned-memory' in iflags:iflags.remove('--opt=force-aligned-memory')
   iflags+=['-I'+str(original.parent)]
   ipp=out/(name+'.pp');iobj=out/(name+'-ispc.obj')
   with ipp.open('w') as stream,(out/(name+'-preprocess.log')).open('w') as log:
    subprocess.run([str(compiler.with_name('ispc.exe')),*iflags,'-E',str(out/(name+'.ispc'))],cwd=out,env=env,stdout=stream,stderr=log,check=True,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
   run([str(compiler.with_name('ispc.exe')),*iflags,str(out/(name+'.ispc')),'--emit-obj','-o',str(iobj)],name+'-compile')
   rsp=once(rsp,chr(34)+str(old_object).replace('\\','/')+chr(34),chr(34)+str(iobj).replace('\\','/')+chr(34))
   ispc_objects[name+'-ispc']=digest_file(iobj);ispc_preprocessed[name+'-ispc']=digest_file(ipp)
  old='"'+str(base/'PathIntegratorUtil.obj').replace('\\','/')+'"'
  rsp=once(rsp,old,'"'+str(obj).replace('\\','/')+'"');(out/'link.rsp').write_text(rsp)
  run([str(compiler),'-O3','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(out/'link.rsp')],'sample-link')
  for f,h in pinned.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  verify(base/'runtime',held)
  report.update(status='built',source_hashes=pinned,native_hashes={},dll_sha256=digest_file(runtime/'librendering_rndr.dll'),objects={'PathIntegratorUtil':digest_file(obj),**ispc_objects},preprocessed={'PathIntegratorUtil':digest_file(pp),**ispc_preprocessed},experimental_only=True,base_sha256=digest_file(base/'report.json'))
 except Exception as e:
  import traceback
  report['error']=str(e);report['traceback']=traceback.format_exc()
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='built' else 1
if __name__=='__main__':raise SystemExit(main())
