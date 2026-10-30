"""Validate real CUDA sampling plus native contribution arithmetic; no renderer changes."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import struct
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.fused_contribution import join
from xpu2.reference import digest_file
from xpu2_cuda_sampler_probe import bind
from xpu2_repeatability import gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','lambert','contribution','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();source=a.source.resolve()
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    rows,unmatched=join(a.lambert.read_bytes(),a.contribution.read_bytes())
    report=dict(status='incomplete',scope='Captured nonmirror Lambert + pre-shadow contribution CUDA replay, not live lighting or path tracing.',matched=len(rows),unmatched_identities=unmatched,gpu=gpu_identity(),checks=[],timings=[])
    toolkit=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
    names=['sampler_cuda.cu','lambert_cuda.cu','ispc_math_cuda.cuh','lambert_sample_cuda.cu','fused_contribution_cuda.cu']
    files=[ROOT/'xpu2'/n for n in names]+[ROOT/'xpu2/fused_contribution.py',Path(__file__).resolve(),a.lambert.resolve(),a.contribution.resolve(),toolkit/'nvrtc64_120_0.dll',toolkit/'nvrtc-builtins64_128.dll']
    hashes={str(f):digest_file(f) for f in files};report['source_hashes']=hashes
    ptr,u64,size,integer=C.c_void_p,C.c_uint64,C.c_size_t,C.c_int
    context=ptr();module=ptr();buffers=[];driver=None
    try:
        with os.add_dll_directory(str(toolkit)):
            builtins=C.WinDLL(str(toolkit/'nvrtc-builtins64_128.dll'));nvrtc=C.WinDLL(str(toolkit/'nvrtc64_120_0.dll'))
        driver=C.WinDLL('nvcuda.dll');bind(driver,'cuInit',[C.c_uint])(0)
        device=integer();major=integer();minor=integer()
        bind(driver,'cuDeviceGet',[C.POINTER(integer),integer])(C.byref(device),0)
        bind(driver,'cuDeviceComputeCapability',[C.POINTER(integer),C.POINTER(integer),integer])(C.byref(major),C.byref(minor),device)
        flags=['--std=c++14','--gpu-architecture=compute_%d%d'%(major.value,minor.value),'--fmad=false','--ftz=false','--prec-div=true','--prec-sqrt=true']
        report['compile_flags']=flags
        code='\n'.join((ROOT/'xpu2'/n).read_text(encoding='utf-8-sig') for n in names).encode()
        (out/'combined.cu').write_bytes(code)
        program=ptr();bind(nvrtc,'nvrtcCreateProgram',[C.POINTER(ptr),C.c_char_p,C.c_char_p,integer,ptr,ptr])(C.byref(program),code,b'combined.cu',0,None,None)
        try:
            fn=nvrtc.nvrtcCompileProgram;fn.argtypes=[ptr,integer,C.POINTER(C.c_char_p)];fn.restype=integer
            options=(C.c_char_p*len(flags))(*(s.encode() for s in flags));status=fn(program,len(flags),options)
            n=size();bind(nvrtc,'nvrtcGetProgramLogSize',[ptr,C.POINTER(size)])(program,C.byref(n));log=C.create_string_buffer(n.value)
            bind(nvrtc,'nvrtcGetProgramLog',[ptr,ptr])(program,log);(out/'compile.log').write_bytes(log.value)
            if status:raise ValueError('CUDA compilation failed')
            bind(nvrtc,'nvrtcGetPTXSize',[ptr,C.POINTER(size)])(program,C.byref(n));ptx=C.create_string_buffer(n.value)
            bind(nvrtc,'nvrtcGetPTX',[ptr,ptr])(program,ptx);(out/'combined.ptx').write_bytes(ptx.value)
        finally:bind(nvrtc,'nvrtcDestroyProgram',[C.POINTER(ptr)])(C.byref(program))
        report['ptx_sha256']=digest_file(out/'combined.ptx')
        bind(driver,'cuCtxCreate_v2',[C.POINTER(ptr),C.c_uint,integer])(C.byref(context),0,device)
        bind(driver,'cuModuleLoadData',[C.POINTER(ptr),ptr])(C.byref(module),ptx)
        functions={}
        for name in ('lambert_sample_vector','contribution_only','fused_lambert_contribution'):
            f=ptr();bind(driver,'cuModuleGetFunction',[C.POINTER(ptr),ptr,C.c_char_p])(C.byref(f),module,name.encode());functions[name]=f
        maximum=8192
        for width in (96,4,96,36,96,32):
            b=u64();bind(driver,'cuMemAlloc_v2',[C.POINTER(u64),size])(C.byref(b),maximum*width);buffers.append(b)
        h2d=bind(driver,'cuMemcpyHtoD_v2',[u64,ptr,size]);d2h=bind(driver,'cuMemcpyDtoH_v2',[ptr,u64,size])
        launch=bind(driver,'cuLaunchKernel',[ptr,*([C.c_uint]*7),ptr,C.POINTER(ptr),ptr])
        sync=bind(driver,'cuCtxSynchronize',[])
        def run(mode,selected,perturb=False):
            count=len(selected);words=[];contrib=[];expect_sample=[];expect_contrib=[]
            for row in selected:
                src=list(row['lambert'])
                if perturb:
                    for c in (14,15,16):src[c]=struct.unpack('<I',struct.pack('<f',struct.unpack('<f',struct.pack('<I',src[c]))[0]*.5))[0]
                words.extend(src);contrib.extend(row['contribution'])
                native=list(row['sample']);native[7]=int(struct.unpack('<f',struct.pack('<I',native[7]))[0]);expect_sample.extend([0]+native);expect_contrib.extend(row['expected'])
            source_bytes=struct.pack('<%dI'%len(words),*words);a0=C.create_string_buffer(source_bytes)
            lengths=(C.c_uint*count)(*([96]*count));a4=C.create_string_buffer(struct.pack('<%dI'%len(contrib),*contrib))
            echo=C.create_string_buffer(count*96);samples=C.create_string_buffer(count*36);result=C.create_string_buffer(count*32)
            n=C.c_uint(count);zero=u64(0)
            def kernel(name,args):
                params=(ptr*len(args))(*(C.cast(C.byref(x),ptr) for x in args));launch(functions[name],(count+63)//64,1,1,64,1,1,0,None,params,None)
            start=time.perf_counter_ns()
            h2d(buffers[0],a0,count*96);h2d(buffers[1],lengths,count*4);h2d(buffers[4],a4,count*96)
            if mode=='fused':kernel('fused_lambert_contribution',[*buffers[:4],buffers[4],buffers[5],n])
            else:
                kernel('lambert_sample_vector',[*buffers[:4],zero,zero,n])
                kernel('contribution_only',[buffers[4],buffers[3],buffers[5],n])
            sync();d2h(echo,buffers[2],count*96);d2h(samples,buffers[3],count*36);d2h(result,buffers[5],count*32)
            elapsed=time.perf_counter_ns()-start
            if echo.raw!=source_bytes:raise ValueError('Input echo mismatch')
            observed_sample=struct.unpack('<%dI'%(count*9),samples.raw);observed=struct.unpack('<%dI'%(count*8),result.raw)
            differences=[(i,x,y) for i,(x,y) in enumerate(zip(observed,expect_contrib)) if x!=y]
            delta=max((abs(struct.unpack('<f',struct.pack('<I',x))[0]-struct.unpack('<f',struct.pack('<I',y))[0]) for _,x,y in differences),default=0)
            return dict(mode=mode,count=count,wall_ns=elapsed,sample_mismatches=sum(x!=y for x,y in zip(observed_sample,expect_sample)),contribution_mismatches=len(differences),max_absolute=delta,first_differences=differences[:8]),samples.raw+result.raw
        baseline=None
        for reverse in (False,True):
            selected=list(reversed(rows)) if reverse else rows
            for mode in ('split','fused'):
                check,data=run(mode,selected);check['reverse']=reverse;report['checks'].append(check)
                if mode=='split':baseline=data
                elif data!=baseline:raise ValueError('Fusion changed GPU output')
        exact=all(not r['sample_mismatches'] and not r['contribution_mismatches'] for r in report['checks'])
        if not exact:
            report['status']='parity_failed';raise ValueError('Native parity failed; timing gate closed')
        for count in (128,2048,8192):
            selected=[rows[i%len(rows)] for i in range(count)]
            for repeat in range(5):
                for mode in (('split','fused') if repeat%2==0 else ('fused','split')):
                    check,_=run(mode,selected);check['repeat']=repeat
                    if check['sample_mismatches'] or check['contribution_mismatches']:raise ValueError('Larger-batch parity failed')
                    report['timings'].append(check)
        changed=[]
        for mode in ('split','fused'):
            check,data=run(mode,rows,True);changed.append(data);report['checks'].append(dict(**check,perturbed=True))
            if not check['sample_mismatches'] or not check['contribution_mismatches']:raise ValueError('Color perturbation did not reach outputs')
        if changed[0]!=changed[1]:raise ValueError('Perturbed split/fused differ')
        if hashes!={str(f):digest_file(f) for f in files} or report['gpu']!=gpu_identity():raise ValueError('Input/device drift')
        report['status']='passed'
    except Exception as exc:
        report['error']=str(exc);raise
    finally:
        cleanup=[]
        if driver:
            for b in reversed(buffers):
                try:bind(driver,'cuMemFree_v2',[u64])(b)
                except Exception as exc:cleanup.append(str(exc))
            if module.value:
                try:bind(driver,'cuModuleUnload',[ptr])(module)
                except Exception as exc:cleanup.append(str(exc))
            if context.value:
                try:bind(driver,'cuCtxDestroy_v2',[ptr])(context)
                except Exception as exc:cleanup.append(str(exc))
        report['cleanup_errors']=cleanup
        if cleanup:report['status']='cleanup_failed'
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ('status','matched','checks','cleanup_errors')},indent=2))
        if cleanup:raise RuntimeError('CUDA cleanup failed')

if __name__=='__main__':main()
