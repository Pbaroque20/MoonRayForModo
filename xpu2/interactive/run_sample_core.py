"""Private bounded CPU/CUDA parity qualification, not a render benchmark."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import time
from reference_runtime import sha
from fallback import environment
HERE=Path(__file__).resolve().parent

def bind(lib,name,args):
    fn=getattr(lib,name);fn.argtypes=args;fn.restype=C.c_int
    def checked(*values):
        status=fn(*values)
        if status:raise RuntimeError(name+" failed: "+str(status))
    return checked

def compile_ptx(source,out,suite="sample"):
    root=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
    handle=os.add_dll_directory(str(root))
    builtins=C.WinDLL(str(root/'nvrtc-builtins64_128.dll'))
    lib=C.WinDLL(str(root/'nvrtc64_120_0.dll'))
    ptr=C.c_void_p;strings=C.POINTER(C.c_char_p)
    create=bind(lib,'nvrtcCreateProgram',[C.POINTER(ptr),C.c_char_p,C.c_char_p,C.c_int,strings,strings])
    destroy=bind(lib,'nvrtcDestroyProgram',[C.POINTER(ptr)])
    compile_=getattr(lib,'nvrtcCompileProgram');compile_.argtypes=[ptr,C.c_int,strings];compile_.restype=C.c_int
    headers={name:(HERE/name).read_bytes() for name in ('sample_stream.h','path_stage.h','sample_fixture.h')+ (('qmc_fixture.h',) if suite=='qmc' else ())}
    names=(C.c_char_p*len(headers))(*(s.encode() for s in headers))
    values=(C.c_char_p*len(headers))(*headers.values())
    program=ptr();create(C.byref(program),(HERE/(suite+'_gpu.cu')).read_bytes(),(suite+'_gpu.cu').encode(),len(headers),values,names)
    flags=['--std=c++17','--gpu-architecture=compute_75','--fmad=false','--prec-div=true','--prec-sqrt=true','--ftz=false']
    try:
        result=compile_(program,len(flags),(C.c_char_p*len(flags))(*(x.encode() for x in flags)))
        def get(name):
            size=C.c_size_t();bind(lib,'nvrtcGet'+name+'Size',[ptr,C.POINTER(C.c_size_t)])(program,C.byref(size))
            data=C.create_string_buffer(size.value);bind(lib,'nvrtcGet'+name,[ptr,ptr])(program,data)
            return data.value
        (out/'nvrtc.log').write_bytes(get('ProgramLog'))
        if result:raise RuntimeError('NVRTC compilation failed: '+str(result))
        ptx=get('PTX');(out/'sample.ptx').write_bytes(ptx)
        return ptx,flags,{str(root/n):sha(root/n) for n in ('nvrtc64_120_0.dll','nvrtc-builtins64_128.dll')}
    finally:
        destroy(C.byref(program));handle.close()


def run(args,report):
    source,out=args.source.resolve(),args.output.resolve();suite=args.suite
    files=[HERE/n for n in ('sample_stream.h','path_stage.h','sample_fixture.h',suite+'_gpu.cu',suite+'_cpu.cc','run_sample_core.py')+ (('qmc_fixture.h',) if suite=='qmc' else ())]
    held={str(p):sha(p) for p in files};report['source_hashes']=held
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
    dll=out/'sample_cpu.dll'
    flags=['-std=c++17','-O2','-march=ivybridge','-mno-avx2','-mno-fma','-ffp-contract=off','-fno-fast-math','-pthread','-shared']
    result=subprocess.run([str(compiler),*flags,str(HERE/(suite+'_cpu.cc')),'-o',str(dll)],capture_output=True,text=True,
                          timeout=180,env=environment(compiler.parent,out),creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('CPU build failed')
    handle=os.add_dll_directory(str(compiler.parent))
    host=C.CDLL(str(dll));host.checks.restype=C.c_uint
    host.fill.argtypes=[C.c_ulonglong,C.c_uint,C.POINTER(C.c_uint),C.c_uint];host.fill.restype=C.c_int
    report['cpu_check_mask']=host.checks()
    if report['cpu_check_mask']:raise RuntimeError('CPU known-answer/stage checks failed')
    ptx,deviceflags,nvrtc_hashes=compile_ptx(source,out,suite)
    report.update(compiler_sha256=sha(compiler),cpu_flags=flags,gpu_flags=deviceflags,nvrtc_hashes=nvrtc_hashes,
                  cpu_dll_sha256=sha(dll),ptx_sha256=sha(out/'sample.ptx'))
    driver=C.WinDLL(str(Path(os.environ['SystemRoot'])/'System32/nvcuda.dll'))
    ptr=C.c_void_p;devptr=C.c_ulonglong
    bind(driver,'cuInit',[C.c_uint])(0)
    device=C.c_int();bind(driver,'cuDeviceGet',[C.POINTER(C.c_int),C.c_int])(C.byref(device),0)
    name=C.create_string_buffer(256);bind(driver,'cuDeviceGetName',[ptr,C.c_int,C.c_int])(name,256,device)
    version=C.c_int();bind(driver,'cuDriverGetVersion',[C.POINTER(C.c_int)])(C.byref(version))
    report.update(device=name.value.decode(),driver_api_version=version.value)
    context=ptr();module=ptr();memory=devptr();stream=ptr()
    try:
        bind(driver,'cuCtxCreate_v2',[C.POINTER(ptr),C.c_uint,C.c_int])(C.byref(context),0,device)
        bind(driver,'cuModuleLoadData',[C.POINTER(ptr),ptr])(C.byref(module),C.c_char_p(ptx))
        bind(driver,'cuStreamCreate',[C.POINTER(ptr),C.c_uint])(C.byref(stream),1)
        capacity=args.chunk_blocks*32
        bind(driver,'cuMemAlloc_v2',[C.POINTER(devptr),C.c_size_t])(C.byref(memory),capacity)
        expected=(C.c_uint*(args.chunk_blocks*8))();actual=(C.c_uint*(args.chunk_blocks*8))()
        fn=ptr();check=ptr()
        get=bind(driver,'cuModuleGetFunction',[C.POINTER(ptr),ptr,C.c_char_p])
        get(C.byref(fn),module,b'fill');get(C.byref(check),module,b'check')
        launch=bind(driver,'cuLaunchKernel',[ptr,*([C.c_uint]*7),ptr,C.POINTER(ptr),ptr])
        sync=bind(driver,'cuStreamSynchronize',[ptr])
        copy=bind(driver,'cuMemcpyDtoH_v2',[ptr,devptr,C.c_size_t])
        checkargs=(ptr*1)(C.cast(C.byref(memory),ptr))
        launch(check,1,1,1,1,1,1,0,stream,checkargs,None);sync(stream);copy(actual,memory,4)
        report['gpu_check_mask']=actual[0]
        if actual[0]:raise RuntimeError('GPU known-answer/stage checks failed')
        # Every uint32 RNG word AND its float32 conversion is compared directly.
        # No checksum or sampling is used in place of comparison.
        memcmp=C.CDLL('msvcrt').memcmp;memcmp.argtypes=[ptr,ptr,C.c_size_t];memcmp.restype=C.c_int
        total=args.tuples//4;first=0;started=time.monotonic();chunks=0
        while first<total:
            count=min(args.chunk_blocks,total-first)
            f=C.c_ulonglong(first);n=C.c_uint(count)
            kernelargs=(ptr*3)(C.cast(C.byref(f),ptr),C.cast(C.byref(n),ptr),C.cast(C.byref(memory),ptr))
            launch(fn,min(4096,(count+255)//256),1,1,256,1,1,0,stream,kernelargs,None)
            if host.fill(first,count,expected,args.threads):raise RuntimeError('CPU fill failed')
            sync(stream);copy(actual,memory,count*32)
            if memcmp(actual,expected,count*32):
                bad=next(i for i in range(count*8) if actual[i]!=expected[i])
                report['first_mismatch']={'block':first+bad//8,'word':bad%8,'cpu':expected[bad],'gpu':actual[bad]}
                raise RuntimeError('CPU/CUDA word mismatch')
            first+=count;chunks+=1
            if chunks%32==0:print('Compared',first*4,'tuples',flush=True)
        report.update(tuples_compared=first*4,float32_conversions_compared=first*4,checks='known answers; rollback; reservation; epochs; replay; limits',
                      tuples_gate=first*4>=1_000_000_000,mismatches=0,chunks=chunks,validation_seconds=time.monotonic()-started,
                      memory_bytes={'device':capacity,'host_outputs':capacity*2},threads=args.threads)
        if any(sha(Path(p))!=v for p,v in held.items()):raise RuntimeError('Input drift')
    finally:
        if stream.value:
            bind(driver,'cuStreamSynchronize',[ptr])(stream)
        if memory.value:bind(driver,'cuMemFree_v2',[devptr])(memory)
        if stream.value:bind(driver,'cuStreamDestroy_v2',[ptr])(stream)
        if module.value:bind(driver,'cuModuleUnload',[ptr])(module)
        if context.value:bind(driver,'cuCtxDestroy_v2',[ptr])(context)
        handle.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--suite',choices=('sample','qmc'),default='sample')
    p.add_argument('--tuples',type=int,default=1_000_000_000)
    p.add_argument('--chunk-blocks',type=int,default=1<<20)
    p.add_argument('--threads',type=int,default=12)
    args=p.parse_args()
    if args.tuples<=0 or args.tuples%4 or args.tuples>4*(1<<60) or not 1<=args.chunk_blocks<=1<<22 or not 1<=args.threads<=64:p.error('Invalid bounded workload')
    if args.output.resolve().is_relative_to(args.source.resolve()):p.error('Isolated output required')
    args.output.mkdir(parents=True,exist_ok=False)
    report={'suite':args.suite,'status':'incomplete','scope':'shared sampler and bounded stage primitives only; no renderer or transfer qualification'}
    try:run(args,report);report['status']='passed'
    except Exception as error:report.update(status='failed',error=str(error))
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
