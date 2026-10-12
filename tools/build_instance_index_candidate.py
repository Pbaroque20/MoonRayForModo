"""Build only an isolated geometry-library candidate; never alter the shared build."""
import argparse,ctypes,hashlib,json,os,re,subprocess
from pathlib import Path
from port_instance_indices import patch_text
p=argparse.ArgumentParser();p.add_argument('checkout',type=Path);a=p.parse_args()
root=a.checkout.resolve();build=root/'build/native-renderer-avx';out=Path('test-results/native-index-candidate').resolve();out.mkdir(parents=True,exist_ok=True)
bin=root/'toolchain/msys64/ucrt64/bin';env=dict(os.environ,PATH=str(bin)+os.pathsep+os.environ.get('PATH',''))
original=root/'upstream/openmoonray/moonray/moonray/lib/rendering/geom/InstanceProceduralLeaf.cc'
source=out/original.name;source.write_text(patch_text(original.read_text(encoding='utf-8')),encoding='utf-8')
r=subprocess.run([str(bin/'ninja.exe'),'-t','commands','bin/librendering_geom.dll'],cwd=build,env=env,capture_output=True,text=True,check=True)
command=next(c for c in r.stdout.splitlines() if 'InstanceProceduralLeaf.cc.obj' in c and ' -c ' in c)
parse=ctypes.windll.shell32.CommandLineToArgvW;parse.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)];parse.restype=ctypes.POINTER(ctypes.c_wchar_p)
count=ctypes.c_int();ptr=parse(command,ctypes.byref(count));args=[ptr[i] for i in range(count.value)];ctypes.windll.kernel32.LocalFree(ptr)
old_object=args[args.index('-o')+1];obj=out/'InstanceProceduralLeaf.cc.obj'
args[args.index('-o')+1]=str(obj);args[args.index('-MF')+1]=str(out/'instance.d');args[args.index('-c')+1]=str(source);args+=['-I'+str(original.parent)]
with (out/'compile.log').open('w',encoding='utf-8') as log:subprocess.run(args,cwd=build,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=240)
s=(build/'build.ninja').read_text(encoding='utf-8');start=s.index('build bin/librendering_geom.dll');block=s[start:s.index('\n\n',start)]
inputs=block.splitlines()[0].split(': ',1)[1].split(' ',1)[1].split(' |',1)[0]
assert inputs.count(old_object)==1,'Unexpected linker input list'
objects=inputs.split();hashes={str(build/v):hashlib.sha256((build/v).read_bytes()).hexdigest() for v in objects}
inputs=inputs.replace(old_object,'"'+obj.as_posix()+'"')
libs=next(line.split(' = ',1)[1] for line in block.splitlines() if line.startswith('  LINK_LIBRARIES ='))
assert '$' not in inputs+libs,'Unexpanded Ninja expression'
rsp=out/'geom.rsp';rsp.write_text(inputs+' '+libs,encoding='utf-8')
with (out/'link.log').open('w',encoding='utf-8') as log:subprocess.run([str(bin/'g++.exe'),'-O3','-DNDEBUG','-shared','-o',str(out/'librendering_geom.dll'),'-Wl,--out-implib,'+str(out/'librendering_geom.dll.a'),'@'+str(rsp)],cwd=build,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==value for path,value in hashes.items()),'Shared objects changed during linking'
(out/'build-report.json').write_text(json.dumps({'candidate':str(out/'librendering_geom.dll'),'shared_objects_unchanged':True},indent=2),encoding='utf-8')
print('Isolated geometry library built; shared objects unchanged')
