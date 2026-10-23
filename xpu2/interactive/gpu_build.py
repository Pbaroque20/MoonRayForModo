"""Private NVRTC build using the local pinned toolchain, with input inventory."""
import ctypes as C,os
from pathlib import Path
from run_sample_core import bind
from reference_runtime import sha
HERE=Path(__file__).resolve().parent
def compile_ptx(source,out):
 nvdir=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
 cuda=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
 optix=source/'toolchain/xpu/optix-dev/include'
 handle=os.add_dll_directory(str(nvdir));builtins=C.WinDLL(str(nvdir/'nvrtc-builtins64_128.dll'));nv=C.WinDLL(str(nvdir/'nvrtc64_120_0.dll'))
 ptr=C.c_void_p;strings=C.POINTER(C.c_char_p);program=ptr()
 headers={n:(HERE/n).read_bytes() for n in ('gpu_jobs.h','triangle_hit.h','texture_core.h','resume_core.h','surface_core.h','sample_stream.h','path_stage.h')}
 held={str(p):sha(p) for base in (cuda,optix) for p in base.rglob('*.h')}
 flags=['--std=c++17','--gpu-architecture=compute_75','--fmad=false','--prec-div=true','--prec-sqrt=true','--ftz=false','-I'+str(cuda),'-I'+str(optix)]
 bind(nv,'nvrtcCreateProgram',[C.POINTER(ptr),C.c_char_p,C.c_char_p,C.c_int,strings,strings])(C.byref(program),(HERE/'gpu_trace.cu').read_bytes(),b'gpu_trace.cu',len(headers),(C.c_char_p*len(headers))(*headers.values()),(C.c_char_p*len(headers))(*(n.encode() for n in headers)))
 try:
  fn=nv.nvrtcCompileProgram;fn.argtypes=[ptr,C.c_int,strings];fn.restype=C.c_int;result=fn(program,len(flags),(C.c_char_p*len(flags))(*(f.encode() for f in flags)))
  def get(kind):
   n=C.c_size_t();bind(nv,'nvrtcGet'+kind+'Size',[ptr,C.POINTER(C.c_size_t)])(program,C.byref(n));data=C.create_string_buffer(n.value);bind(nv,'nvrtcGet'+kind,[ptr,ptr])(program,data);return data.value
  (out/'nvrtc.log').write_bytes(get('ProgramLog'))
  if result:raise RuntimeError('NVRTC compilation failed; see nvrtc.log')
  file=out/'gpu_trace.ptx';file.write_bytes(get('PTX'))
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Toolchain header drift')
  return file,{'flags':flags,'headers':held,'ptx_sha256':sha(file),'nvrtc_sha256':sha(nvdir/'nvrtc64_120_0.dll')}
 finally:bind(nv,'nvrtcDestroyProgram',[C.POINTER(ptr)])(C.byref(program));handle.close()
