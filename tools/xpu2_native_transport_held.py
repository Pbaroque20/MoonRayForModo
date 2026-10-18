"""Hold the built transport queue's CUDA streams and cancel all live contracts."""
import argparse,gzip,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2_native_flight_held import CPP
from xpu2.reference import digest_file
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','build','ptx','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    build=a.build.resolve();manifest=json.loads((build/'report.json').read_text())
    files=[Path(__file__),ROOT/'tools/xpu2_native_flight_held.py',ROOT/'xpu2/native_queue_stress.cc',ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz',a.ptx.resolve(),build/'report.json']
    copies=('early_queue.inc','batch_transport.h','native_tile_policy.h')
    files.extend(build/name for name in copies)
    hashes={**manifest['source_hashes'],**manifest['native_hashes'],**{str(f):digest_file(f) for f in files}}
    report={'status':'incomplete','source_hashes':hashes,'gpu':gpu_identity(),'scope':'Actual built queue with CUDA stream callback gates; cancellation while transfers are incomplete, not preemption of an executing shader kernel'}
    try:
        if manifest['status']!='built':raise ValueError('Incomplete build')
        for f,h in hashes.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
        for name in copies:(out/name).write_bytes((build/name).read_bytes())
        helpers=(ROOT/'xpu2/native_queue_stress.cc').read_text().split('int main(')[0].replace('"native_lambert_queue.cc"','"early_queue.inc"')
        marker='    std::cout<<'
        if CPP.count(marker)!=1:raise ValueError('Held harness changed')
        checks=r'''
    require(q->transport && q->transportPacks>=4,"Transport not exercised");
    require(q->transportPacks==q->transportRetired && q->transportRetired==q->flightRetired,"Unretired contract");
    require(q->transportDiscarded==q->transportRetired,"Cancelled contract was published");
    require(!q->transportActive && !q->transportFailed && !q->transportBypass,"Transport ownership failure");
    std::cout<<"{\"passed\":true,\"peak_inflight\":"<<q->peakFlights<<",\"packed\":"<<q->transportPacks<<",\"retired\":"<<q->transportRetired<<",\"discarded\":"<<q->transportDiscarded<<",\"active\":"<<q->transportActive<<",\"retained_credits\":"<<q->retainedAsync<<",\"published\":"<<q->delivered<<"}\n";
}
'''
        (out/'held.cc').write_text(helpers+CPP.split(marker)[0]+checks)
        raw=gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes());(out/'packets.bin').write_bytes(raw)
        compiler=a.source/'toolchain/msys64/ucrt64/bin/g++.exe';headers=a.source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        env=environment(compiler.parent,out)
        for key in list(env):
            if key.startswith('XPU2_'):del env[key]
        env.update(XPU2_NATIVE_LAMBERT='execute',XPU2_NATIVE_LAMBERT_PTX=str(a.ptx.resolve()),XPU2_INFLIGHT_BATCHES='4',XPU2_TILE_BATCH_LIMIT='4',XPU2_QUEUE_CAPACITY='64',XPU2_BATCH_TRANSPORT='1',XPU2_CUDA_CONTEXT='private')
        built=subprocess.run([str(compiler),'-std=c++17','-O2','-mavx','-ffast-math','-I'+str(headers),str(out/'held.cc'),'-o',str(out/'held.exe')],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'build.log').write_text(built.stdout+built.stderr)
        if built.returncode:raise ValueError('Compile failed')
        done=subprocess.run([str(out/'held.exe'),str(out/'packets.bin')],env=env,capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'process.log').write_text(done.stdout+done.stderr)
        if done.returncode:raise ValueError('Held flight failed')
        report['result']=json.loads(done.stdout)
        if not report['result']['passed']:raise ValueError('Missing success')
        for f,h in hashes.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
