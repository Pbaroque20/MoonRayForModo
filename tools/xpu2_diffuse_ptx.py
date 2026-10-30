"""Compile versioned diffuse sampling for the isolated native GPU candidate."""
import argparse,ctypes as C,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_cuda_sampler_probe import bind

def compile_ptx(source,out):
    toolkit=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
    with os.add_dll_directory(str(toolkit)):
        builtins=C.WinDLL(str(toolkit/'nvrtc-builtins64_128.dll'));nvrtc=C.WinDLL(str(toolkit/'nvrtc64_120_0.dll'))
    code=b'\n'.join((ROOT/'xpu2'/name).read_bytes() for name in ('sampler_cuda.cu','lambert_cuda.cu','ispc_math_cuda.cuh','diffuse_sample_cuda.cu'))
    (out/'film.cu').write_bytes(code);program=C.c_void_p()
    bind(nvrtc,'nvrtcCreateProgram',[C.POINTER(C.c_void_p),C.c_char_p,C.c_char_p,C.c_int,C.c_void_p,C.c_void_p])(C.byref(program),code,b'film.cu',0,None,None)
    flags=['--std=c++14','--gpu-architecture=compute_86','--fmad=false','--ftz=false','--prec-div=true','--prec-sqrt=true']
    try:
        fn=nvrtc.nvrtcCompileProgram;fn.argtypes=[C.c_void_p,C.c_int,C.POINTER(C.c_char_p)];fn.restype=C.c_int
        options=(C.c_char_p*len(flags))(*(v.encode() for v in flags));status=fn(program,len(flags),options)
        n=C.c_size_t();bind(nvrtc,'nvrtcGetProgramLogSize',[C.c_void_p,C.POINTER(C.c_size_t)])(program,C.byref(n));log=C.create_string_buffer(n.value)
        bind(nvrtc,'nvrtcGetProgramLog',[C.c_void_p,C.c_void_p])(program,log);(out/'cuda.log').write_bytes(log.value)
        if status:raise ValueError('CUDA compilation failed')
        bind(nvrtc,'nvrtcGetPTXSize',[C.c_void_p,C.POINTER(C.c_size_t)])(program,C.byref(n));ptx=C.create_string_buffer(n.value)
        bind(nvrtc,'nvrtcGetPTX',[C.c_void_p,C.c_void_p])(program,ptx);(out/'film.ptx').write_bytes(ptx.value)
    finally:bind(nvrtc,'nvrtcDestroyProgram',[C.POINTER(C.c_void_p)])(C.byref(program))
    return flags

def main():
    p=argparse.ArgumentParser(description='Compile the versioned broader diffuse GPU kernel')
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    names=('sampler_cuda.cu','lambert_cuda.cu','ispc_math_cuda.cuh','diffuse_sample_cuda.cu')
    hashes={name:digest_file(ROOT/'xpu2'/name) for name in names}
    flags=compile_ptx(a.source.resolve(),out)
    if any(digest_file(ROOT/'xpu2'/n)!=h for n,h in hashes.items()):raise ValueError('Kernel source drift')
    (out/'report.json').write_text(json.dumps(dict(status='built',sources=hashes,flags=flags,ptx_sha256=digest_file(out/'film.ptx')),indent=2)+'\n')
    print('built',flush=True)
if __name__=='__main__':main()
