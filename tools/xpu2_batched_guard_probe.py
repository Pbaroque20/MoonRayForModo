"""Check native handoff guards using the actual bridge and GPU queue."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2.correlated_state import decode
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','capture','ptx','output'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--profile',action='store_true',help='Check the aggregate profiling candidate with quiet diagnostics')
    p.add_argument('--window-dispatch',action='store_true')
    a=p.parse_args()
    if a.window_dispatch and not a.profile:p.error('--window-dispatch requires --profile')
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);source=a.source.resolve()
    report={'status':'incomplete','scope':'Standalone guard checks; native rendering is validated separately','runs':[]}
    try:
        decode(a.capture.read_bytes())
        inputs=[ROOT/'xpu2/batched_guard_probe.cc',ROOT/'xpu2/batched_bridge.cc',ROOT/'xpu2/native_lambert_queue.cc',Path(__file__).resolve(),a.capture.resolve(),a.ptx.resolve()]
        if a.profile:inputs += [ROOT/'xpu2/profile_patch.py',ROOT/'xpu2/profile_metrics.h']
        if a.window_dispatch:inputs += [ROOT/'xpu2/window_dispatch_patch.py']
        hashes={str(f):digest_file(f) for f in inputs}
        report.update(source_hashes=hashes,gpu=gpu_identity())
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';env=environment(compiler.parent,out)
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
        pp=out/'guards.ii';exe=out/'guards.exe';code=inputs[0]
        if a.profile:
            from xpu2 import profile_patch
            bridge=profile_patch.apply(inputs[2].read_text(),inputs[1].read_text(),(ROOT/'xpu2/profile_metrics.h').read_text())
            if a.window_dispatch:
                from xpu2 import window_dispatch_patch
                bridge=window_dispatch_patch.apply(bridge)
            code=out/'guards.cc';code.write_text(inputs[0].read_text().replace('#include "batched_bridge.cc"',bridge),encoding='utf-8')
        for label,args in [('preprocess',['-E',str(code),'-o',str(pp)]),('compile',[str(pp),'-o',str(exe)])]:
            done=subprocess.run([str(compiler),*flags,*args],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr)
            if done.returncode:raise ValueError(label+' failed')
        report.update(preprocessed_sha256=digest_file(pp),executable_sha256=digest_file(exe),compiler_sha256=digest_file(compiler))
        cases=['positive','transformed','mask','multiple','nested','window']
        if a.window_dispatch:cases += ['publication']
        for case in cases:
            folder=out/case;folder.mkdir();runenv=environment(compiler.parent,folder)
            runenv.update(XPU2_NATIVE_LAMBERT='sentinel',XPU2_NATIVE_LAMBERT_PTX=str(a.ptx.resolve()),
                XPU2_NATIVE_LAMBERT_LOG=str(folder/'shading.log'),XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shading.bin'),
                XPU2_DEFERRED_LOG=str(folder/'deferred.log'),XPU2_QUEUE_LOG=str(folder/'queue.log'))
            if a.profile:runenv.update(XPU2_PROFILE_FILE=str(folder/'profile.json'),XPU2_PROFILE_QUIET='1')
            if a.window_dispatch:runenv['XPU2_WINDOW_DISPATCH']='1'
            done=subprocess.run([str(exe),case,str(a.capture.resolve())],env=runenv,cwd=folder,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/'process.log').write_text(done.stdout+done.stderr)
            if done.returncode:raise ValueError(case+' failed')
            row=json.loads(done.stdout)
            if row!={'case':case,'passed':True,'cleanup':True}:raise ValueError('Incomplete guard test')
            row['log_hashes']={f.name:digest_file(f) for f in folder.iterdir() if f.is_file()};report['runs'].append(row)
        if hashes!={str(f):digest_file(f) for f in inputs} or report['gpu']!=gpu_identity():raise ValueError('Source/device drift')
        report['status']='passed'
    except Exception as e:report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
