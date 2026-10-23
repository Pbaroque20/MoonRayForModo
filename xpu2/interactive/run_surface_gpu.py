"""Private shared surface CPU/CUDA comparison, not GPU rendering performance."""
import argparse,ctypes as C,json,os,subprocess
from pathlib import Path
from run_sample_core import bind
from reference_runtime import sha
from fallback import environment
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();source=a.source.resolve();out=a.output.resolve()
 if out.is_relative_to(source):p.error('Isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','scope':'shared math only; no GPU traversal/transport or image qualification'}
 context=module=memory=None;handles=[];driver=None
 try:
  files=[HERE/n for n in ('surface_core.h','sample_stream.h','surface_fixture.h','surface_cpu.cc','surface_gpu.cu','run_surface_gpu.py','surface-gates.json','run_sample_core.py')]
  held={str(p):sha(p) for p in files};report['source_hashes']=held
  gates=json.loads((HERE/'surface-gates.json').read_text());(out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8')
  compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';dll=out/'surface.dll'
  flags=['-std=c++17','-O2','-march=ivybridge','-mno-avx2','-mno-fma','-ffp-contract=off','-fno-fast-math','-shared']
  done=subprocess.run([str(compiler),*flags,str(HERE/'surface_cpu.cc'),'-o',str(dll)],capture_output=True,text=True,env=environment(compiler.parent,out),timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'compile.log').write_text(done.stdout+done.stderr,encoding='utf-8')
  if done.returncode:raise RuntimeError('CPU build failed')
  handles.append(os.add_dll_directory(str(compiler.parent)));host=C.CDLL(str(dll));host.fill.argtypes=[C.c_uint,C.POINTER(C.c_float)];host.fill.restype=None
  nvdir=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin';handles.append(os.add_dll_directory(str(nvdir)))
  builtins=C.WinDLL(str(nvdir/'nvrtc-builtins64_128.dll'));nv=C.WinDLL(str(nvdir/'nvrtc64_120_0.dll'))
  ptr=C.c_void_p;strings=C.POINTER(C.c_char_p);program=ptr()
  headers={n:(HERE/n).read_bytes() for n in ('sample_stream.h','surface_core.h','surface_fixture.h')}
  bind(nv,'nvrtcCreateProgram',[C.POINTER(ptr),C.c_char_p,C.c_char_p,C.c_int,strings,strings])(C.byref(program),(HERE/'surface_gpu.cu').read_bytes(),b'surface_gpu.cu',len(headers),(C.c_char_p*len(headers))(*headers.values()),(C.c_char_p*len(headers))(*(n.encode() for n in headers)))
  gpu_flags=['--std=c++17','--gpu-architecture=compute_75','--fmad=false','--prec-div=true','--prec-sqrt=true','--ftz=false']
  try:
   compile_=nv.nvrtcCompileProgram;compile_.argtypes=[ptr,C.c_int,strings];compile_.restype=C.c_int
   status=compile_(program,len(gpu_flags),(C.c_char_p*len(gpu_flags))(*(s.encode() for s in gpu_flags)))
   def get(name):
    size=C.c_size_t();bind(nv,'nvrtcGet'+name+'Size',[ptr,C.POINTER(C.c_size_t)])(program,C.byref(size));b=C.create_string_buffer(size.value);bind(nv,'nvrtcGet'+name,[ptr,ptr])(program,b);return b.value
   (out/'nvrtc.log').write_bytes(get('ProgramLog'))
   if status:raise RuntimeError('CUDA build failed')
   ptx=get('PTX');(out/'surface.ptx').write_bytes(ptx)
  finally:bind(nv,'nvrtcDestroyProgram',[C.POINTER(ptr)])(C.byref(program))
  report['build']={'cpu_flags':flags,'gpu_flags':gpu_flags,'compiler_sha256':sha(compiler),'nvrtc_sha256':sha(nvdir/'nvrtc64_120_0.dll'),'dll_sha256':sha(dll),'ptx_sha256':sha(out/'surface.ptx')}
  driver=C.WinDLL(str(Path(os.environ['SystemRoot'])/'System32/nvcuda.dll'));devptr=C.c_ulonglong
  bind(driver,'cuInit',[C.c_uint])(0);device=C.c_int();bind(driver,'cuDeviceGet',[C.POINTER(C.c_int),C.c_int])(C.byref(device),0)
  context=ptr();module=ptr();memory=devptr();function=ptr()
  bind(driver,'cuCtxCreate_v2',[C.POINTER(ptr),C.c_uint,C.c_int])(C.byref(context),0,device)
  name=C.create_string_buffer(256);bind(driver,'cuDeviceGetName',[ptr,C.c_int,C.c_int])(name,256,device);report['device']=name.value.decode()
  bind(driver,'cuModuleLoadData',[C.POINTER(ptr),ptr])(C.byref(module),C.c_char_p(ptx))
  bind(driver,'cuModuleGetFunction',[C.POINTER(ptr),ptr,C.c_char_p])(C.byref(function),module,b'fill')
  count=1<<20;size=count*16*4;expected=(C.c_float*(count*16))();actual=(C.c_float*(count*16))()
  bind(driver,'cuMemAlloc_v2',[C.POINTER(devptr),C.c_size_t])(C.byref(memory),size)
  n=C.c_uint(count);args=(ptr*2)(C.cast(C.byref(n),ptr),C.cast(C.byref(memory),ptr))
  bind(driver,'cuLaunchKernel',[ptr,*([C.c_uint]*7),ptr,C.POINTER(ptr),ptr])(function,4096,1,1,256,1,1,0,None,args,None)
  host.fill(count,expected);bind(driver,'cuCtxSynchronize',[])();bind(driver,'cuMemcpyDtoH_v2',[ptr,devptr,C.c_size_t])(actual,memory,size)
  memcmp=C.CDLL('msvcrt').memcmp;memcmp.argtypes=[ptr,ptr,C.c_size_t];memcmp.restype=C.c_int
  if memcmp(expected,actual,size):
   # Preserve exact mismatch and component; never relax the frozen gate.
   e=C.cast(expected,C.POINTER(C.c_uint));v=C.cast(actual,C.POINTER(C.c_uint));i=next(i for i in range(count*16) if e[i]!=v[i]);report['first_mismatch']={'row':i//16,'component':i%16,'cpu':expected[i],'gpu':actual[i],'cpu_bits':e[i],'gpu_bits':v[i]};raise RuntimeError('CPU/CUDA surface mismatch')
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  report.update(status='passed',rows=count,float32_words=count*16,mismatches=0,memory_bytes={'device':size,'host':size*2})
 except Exception as e:report.update(status='failed',error=str(e))
 finally:
  if driver:
   if memory and memory.value:bind(driver,'cuMemFree_v2',[C.c_ulonglong])(memory)
   if module and module.value:bind(driver,'cuModuleUnload',[C.c_void_p])(module)
   if context and context.value:bind(driver,'cuCtxDestroy_v2',[C.c_void_p])(context)
  for h in handles:h.close()
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('build','source_hashes')},indent=2),flush=True)
 return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
