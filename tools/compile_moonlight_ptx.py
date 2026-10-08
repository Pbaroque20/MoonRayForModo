"""Compile MoonLight OptiX device code with NVIDIA NVRTC, without a host CUDA compiler."""
import ctypes as C
import os
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
xpu=root/'toolchain/xpu'
runtime=xpu/'cuda_nvrtc-windows-x86_64-12.8.93-archive'
source=Path(sys.argv[1]);output=Path(sys.argv[2])
handles=[os.add_dll_directory(str(runtime/'bin'))]
builtins=C.WinDLL(str(runtime/'bin/nvrtc-builtins64_128.dll'))
lib=C.WinDLL(str(runtime/'bin/nvrtc64_120_0.dll'))
program=C.c_void_p()
lib.nvrtcCreateProgram.argtypes=[C.POINTER(C.c_void_p),C.c_char_p,C.c_char_p,C.c_int,C.POINTER(C.c_char_p),C.POINTER(C.c_char_p)]
lib.nvrtcCompileProgram.argtypes=[C.c_void_p,C.c_int,C.POINTER(C.c_char_p)]
for name in ('nvrtcGetProgramLogSize','nvrtcGetPTXSize'):
    getattr(lib,name).argtypes=[C.c_void_p,C.POINTER(C.c_size_t)]
for name in ('nvrtcGetProgramLog','nvrtcGetPTX'):
    getattr(lib,name).argtypes=[C.c_void_p,C.c_void_p]
lib.nvrtcDestroyProgram.argtypes=[C.POINTER(C.c_void_p)]
result=lib.nvrtcCreateProgram(C.byref(program),source.read_bytes(),str(source).encode(),0,None,None)
if result: raise RuntimeError('nvrtcCreateProgram failed: '+str(result))
try:
    includes=[source.parent,xpu/'optix-dev/include',xpu/'cuda_cudart-windows-x86_64-12.8.90-archive/include',xpu/'cuda_nvcc-windows-x86_64-12.8.93-archive/include']
    # compute_75 matches the XPU program; the NVIDIA driver compiles the PTX for the installed GPU.
    flags=['--std=c++14','--gpu-architecture=compute_75','--use_fast_math']+['--include-path='+str(p) for p in includes]
    options=(C.c_char_p*len(flags))(*(v.encode() for v in flags))
    result=lib.nvrtcCompileProgram(program,len(flags),options)
    size=C.c_size_t();lib.nvrtcGetProgramLogSize(program,C.byref(size))
    log=C.create_string_buffer(size.value);lib.nvrtcGetProgramLog(program,log)
    print(log.value.decode(errors='replace'),flush=True)
    if result: raise RuntimeError('NVRTC compilation failed: '+str(result))
    lib.nvrtcGetPTXSize(program,C.byref(size));ptx=C.create_string_buffer(size.value);lib.nvrtcGetPTX(program,ptx)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(ptx.value)
    print('Compiled MoonLight PTX:',output,flush=True)
finally: lib.nvrtcDestroyProgram(C.byref(program))
