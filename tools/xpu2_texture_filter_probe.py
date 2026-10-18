"""Compare isolated CUDA point/bilinear sampling to frozen native OIIO lookups."""
import argparse, ctypes as C, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file, inventory, verify
from xpu2.images import read_rgba, compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity
from xpu2_cuda_sampler_probe import bind


def compile_cuda(source, out):
    toolkit=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
    with os.add_dll_directory(str(toolkit)):
        builtins=C.WinDLL(str(toolkit/'nvrtc-builtins64_128.dll'))
        nvrtc=C.WinDLL(str(toolkit/'nvrtc64_120_0.dll'))
    driver=C.WinDLL('nvcuda.dll')
    ptr, integer, size=C.c_void_p,C.c_int,C.c_size_t
    bind(driver,'cuInit',[C.c_uint])(0)
    dev,major,minor=integer(),integer(),integer()
    bind(driver,'cuDeviceGet',[C.POINTER(integer),integer])(C.byref(dev),0)
    bind(driver,'cuDeviceComputeCapability',[C.POINTER(integer),C.POINTER(integer),integer])(C.byref(major),C.byref(minor),dev)
    flags=['--std=c++14','--gpu-architecture=compute_'+str(major.value)+str(minor.value),'--fmad=false','--ftz=false','--prec-div=true','--prec-sqrt=true']
    program=ptr();code=(ROOT/'xpu2/texture_filter_cuda.cu').read_text(encoding='utf-8-sig').encode()
    bind(nvrtc,'nvrtcCreateProgram',[C.POINTER(ptr),C.c_char_p,C.c_char_p,integer,ptr,ptr])(C.byref(program),code,b'texture_filter_cuda.cu',0,None,None)
    try:
        fn=nvrtc.nvrtcCompileProgram;fn.argtypes=[ptr,integer,C.POINTER(C.c_char_p)];fn.restype=integer
        status=fn(program,len(flags),(C.c_char_p*len(flags))(*(v.encode() for v in flags)))
        n=size();bind(nvrtc,'nvrtcGetProgramLogSize',[ptr,C.POINTER(size)])(program,C.byref(n))
        log=C.create_string_buffer(n.value);bind(nvrtc,'nvrtcGetProgramLog',[ptr,ptr])(program,log)
        (out/'cuda-compile.log').write_bytes(log.value)
        if status:raise ValueError('NVRTC failed: '+log.value.decode(errors='replace'))
        bind(nvrtc,'nvrtcGetPTXSize',[ptr,C.POINTER(size)])(program,C.byref(n));ptx=C.create_string_buffer(n.value)
        bind(nvrtc,'nvrtcGetPTX',[ptr,ptr])(program,ptx);(out/'texture_filter.ptx').write_bytes(ptx.value)
    finally:bind(nvrtc,'nvrtcDestroyProgram',[C.POINTER(ptr)])(C.byref(program))
    return flags


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','runtime','fixtures','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();source,runtime,fixtures,out=(getattr(a,n).resolve() for n in ('source','runtime','fixtures','output'))
    if any(out.is_relative_to(v) for v in (source,runtime,fixtures)):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',scope='Raw native-channel, base-level CUDA point/bilinear filtering. Texture-space test images, not full MoonRay renders.')
    try:
        prior=json.loads((fixtures/'report.json').read_text())
        if prior.get('status')!='passed':raise ValueError('Passed native OIIO fixture report required')
        fixture_hashes={n:digest_file(fixtures/n) for n in ('rgba.tx','rgb.tx','gray.tx','rg.tx')}
        if any(h!=prior['fixture_hashes'][n] for n,h in fixture_hashes.items()):raise ValueError('Fixture drift')
        verify(runtime,prior['runtime_inventory']);locked=inventory(runtime)
        prefix=source/'toolchain/msys64/ucrt64';compiler=prefix/'bin/g++.exe'
        cuda=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        nvrtc=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
        libraries=[prefix/'lib'/n for n in ('libOpenImageIO.dll.a','libOpenImageIO_Util.dll.a')]
        files=[ROOT/'xpu2'/n for n in ('texture_filter_cuda.cu','texture_filter_probe.cc','texture_cache.h','texture_cuda_backend.h','texture_oiio_loader.h','texture_residency.h')]
        files += [ROOT/'xpu2/images.py',ROOT/'tools/validate_reference_images.py',Path(__file__).resolve(),ROOT/'tools/xpu2_cuda_sampler_probe.py',compiler,*libraries,fixtures/'report.json',nvrtc/'nvrtc64_120_0.dll',nvrtc/'nvrtc-builtins64_128.dll']
        hashes={str(f):digest_file(f) for f in files};report['gpu']=gpu_identity()
        for n in ('libOpenImageIO-3.1.dll','libOpenImageIO_Util-3.1.dll'):
            if digest_file(prefix/'bin'/n)!=digest_file(runtime/n):raise ValueError('Build/runtime OIIO mismatch')
        def run(label,args,env):
            print(label,flush=True)
            r=subprocess.run([str(v) for v in args],cwd=out,env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
            if r.returncode and not(label=='probe' and r.returncode==2):raise ValueError(label+' failed: '+r.stderr[-2000:])
            return r.stdout
        report['cuda_flags']=compile_cuda(source,out)
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(cuda),'-I'+str(prefix/'include')]
        exe,pp=out/'filter-probe.exe',out/'filter-probe.ii';env=environment(prefix/'bin',out)
        run('preprocess',[compiler,*flags,'-E',ROOT/'xpu2/texture_filter_probe.cc','-o',pp],env)
        run('compile',[compiler,*flags,pp,'-o',exe,*libraries],env)
        native=json.loads(run('probe',[exe,fixtures,out/'texture_filter.ptx',out],environment(runtime,out)))
        report.update(native=native,source_hashes=hashes,fixture_hashes=fixture_hashes,runtime_inventory=locked,preprocessed_sha256=digest_file(pp),executable_sha256=digest_file(exe),ptx_sha256=digest_file(out/'texture_filter.ptx'))
        if native.get('cases')!=32 or native.get('queries')!=234976 or native.get('fallback_checks')!=32:
            raise ValueError('Incomplete native filter coverage')
        image_env=environment(runtime,out)
        reference=read_rgba(runtime,out/'texture-reference.exr',out,'reference',image_env)
        actual=read_rgba(runtime,out/'texture-gpu.exr',out,'gpu',image_env)
        report['texture_image']=compare_rgba(reference,actual,absolute=2e-6)
        report['image_channel_ranges']={k:[min(v),max(v)] for k,v in reference['channels'].items()}
        if any(high-low<.1 for low,high in report['image_channel_ranges'].values()):
            raise ValueError('Texture-space image is unexpectedly blank/constant')
        if report['texture_image']['status']!='passed':
            raise ValueError('Texture-space EXR comparison failed')
        verify(runtime,locked)
        if hashes!={str(f):digest_file(f) for f in files} or fixture_hashes!={n:digest_file(fixtures/n) for n in fixture_hashes}:raise ValueError('Source/fixture drift')
        if report['gpu']!=gpu_identity():raise ValueError('GPU identity changed')
        if native.get('passed') is not True:raise ValueError('Filtering parity gate failed; see cases.jsonl')
        report['status']='passed'
    except Exception as e:report['error']=str(e)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
