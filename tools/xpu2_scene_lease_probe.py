"""Exercise owned scene leases while the real diagnostic CUDA queue is delayed.
Scene resources in this probe are synthetic owned data, not native MoonRay scenes.
"""
import argparse,gzip,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2 import native_integration
from xpu2.scene_lifecycle import EXPECTED,validate
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--ptx',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();source,ptx,out=a.source.resolve(),a.ptx.resolve(),a.output.resolve()
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',scope='Real diagnostic CUDA shading queue with synthetic owned scenes; not native accelerator/SceneContext lifetime integration',runs=[])
    try:
        files=[ROOT/'xpu2'/n for n in ('scene_lease_probe.cc','scene_lease.h','shadow_request.h','native_lambert_queue.cc','scene_lifecycle.py','native_integration.py')]+[Path(__file__).resolve(),ptx]
        hashes={str(f):digest_file(f) for f in files};gpu=gpu_identity()
        if not gpu:raise ValueError('No GPU identity')
        raw=gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes())
        if hashlib.sha256(raw).hexdigest()!='39715df807458a8da5746fd8133f5a552ae5dd6116738f2d57010c66401b5ee3':raise ValueError('Native fixture drift')
        capture=out/'reference.bin';capture.write_bytes(raw)
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';headers=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(headers)]
        pp=out/'scene-lease.ii';exe=out/'scene-lease.exe';env=environment(compiler.parent,out)
        for label,args in [('preprocess',['-E',str(files[0]),'-o',str(pp)]),('compile',[str(pp),'-o',str(exe)])]:
            print(label,flush=True);done=subprocess.run([str(compiler),*flags,*args],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr)
            if done.returncode:raise ValueError(label+' failed')
        report.update(source_hashes=hashes,gpu=gpu,compiler_sha256=digest_file(compiler),preprocessed_sha256=digest_file(pp),executable_sha256=digest_file(exe))
        for repeat in range(3):
            for case in EXPECTED:
                folder=out/(case+'-'+str(repeat));folder.mkdir();runenv=environment(compiler.parent,folder)
                runenv.update(XPU2_NATIVE_LAMBERT='sentinel',XPU2_NATIVE_LAMBERT_PTX=str(ptx),XPU2_NATIVE_LAMBERT_LOG=str(folder/'shading.log'),XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shading.bin'),XPU2_QUEUE_CAPACITY='64',XPU2_QUEUE_POLICY='all',XPU2_QUEUE_LOG=str(folder/'queue.log'))
                print(folder.name,flush=True);done=subprocess.run([str(exe),case,str(capture)],env=runenv,capture_output=True,text=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
                (folder/'process.log').write_text(done.stdout+done.stderr)
                if done.returncode:raise ValueError(folder.name+' failed')
                checks=json.loads(done.stdout);rows=[json.loads(line) for line in (folder/'queue.log').read_text().splitlines() if line.startswith('{')];queue=[v for v in rows if 'calls' in v][-1]
                result=validate(case,checks,queue)
                counts=native_integration.summary((folder/'shading.log').read_text());observed=native_integration.records((folder/'shading.bin').read_bytes());native_integration.verify_counts(counts,observed,'replace')
                if counts['samples']!=8 or observed['records']!=8:raise ValueError('GPU sample count differs')
                report['runs'].append(dict(case=case,repeat=repeat,result=result,shading=counts,log_hashes={f.name:digest_file(f) for f in folder.iterdir() if f.is_file()}))
        if hashes!={str(f):digest_file(f) for f in files} or gpu!=gpu_identity():raise ValueError('Source/device drift')
        if report['executable_sha256']!=digest_file(exe):raise ValueError('Probe binary drift')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
