"""Compile and stress the actual native GPU queue in standalone child processes."""
import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2 import native_integration
from xpu2_repeatability import gpu_identity
from xpu2_baseline import environment


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--ptx',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--cases',default='capacity,timeout,pending_timeout,shutdown,shutdown,coalesce_timeout',help='Comma-separated cases; repetitions allowed')
    a=p.parse_args();source=a.source.resolve();out=a.output.resolve();ptx=a.ptx.resolve()
    cases=a.cases.split(',')
    if not cases or any(c not in ('capacity','timeout','pending_timeout','shutdown','coalesce_timeout','lifecycle','lifecycle_missing_ptx') for c in cases):p.error('Unknown stress case')
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    files=[ROOT/'xpu2/native_queue_stress.cc',ROOT/'xpu2/native_lambert_queue.cc',Path(__file__).resolve(),ptx]
    identities={str(x):digest_file(x) for x in files}
    report={'status':'incomplete','scope':'Standalone real queue and CUDA shader stress; not a native render or reusable renderer lifecycle test','source_hashes':identities,'gpu':gpu_identity(),'runs':[]}
    try:
        raw=gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes())
        import hashlib
        assert hashlib.sha256(raw).hexdigest()=='39715df807458a8da5746fd8133f5a552ae5dd6116738f2d57010c66401b5ee3'
        capture=out/'reference.bin';capture.write_bytes(raw)
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
        headers=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        env=environment(compiler.parent,out)
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(headers)]
        preprocessed=out/'queue.ii';exe=out/'queue-stress.exe'
        for label,args in [('preprocess',['-E',str(files[0]),'-o',str(preprocessed)]),('compile',[str(preprocessed),'-o',str(exe)])]:
            done=subprocess.run([str(compiler),*flags,*args],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError(label+' failed')
        report.update(compiler_sha256=digest_file(compiler),preprocessed_sha256=digest_file(preprocessed),executable_sha256=digest_file(exe))
        for name in cases:
            folder=out/(name+'-'+str(len(report['runs'])));folder.mkdir()
            runenv=environment(compiler.parent,folder)
            runenv.update(XPU2_NATIVE_LAMBERT='sentinel',XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if name=='lifecycle_missing_ptx' else ptx),XPU2_NATIVE_LAMBERT_LOG=str(folder/'shading.log'),XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shading.bin'),XPU2_QUEUE_CAPACITY='64',XPU2_QUEUE_POLICY='all',XPU2_QUEUE_LOG=str(folder/'queue.log'))
            print('Queue stress '+folder.name,flush=True)
            done=subprocess.run([str(exe),name,str(capture)],env=runenv,capture_output=True,text=True,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/'process.log').write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError('Stress process failed: '+folder.name)
            result=json.loads(done.stdout)
            if result.get('passed') is not True:raise ValueError('Missing stress success')
            if name in ('lifecycle','lifecycle_missing_ptx'):
                cycles=[]
                for index in range(4):
                    counts=native_integration.summary((folder/('shading.log.'+str(index))).read_text())
                    observations=native_integration.records((folder/('shading.bin.'+str(index))).read_bytes())
                    if name=='lifecycle_missing_ptx':
                        if counts['errors']!=1 or counts['samples']!=8 or counts['accepted'] or counts['replaced'] or observations['records']:raise ValueError('Missing PTX did not preserve native fallback')
                    else:native_integration.verify_counts(counts,observations,'replace')
                    rows=[json.loads(x) for x in (folder/('queue.log.'+str(index))).read_text().splitlines() if x.startswith('{')]
                    counters=[r for r in rows if 'calls' in r][-1]
                    ids=[r['delivered_id'] for r in rows if 'delivered_id' in r]
                    if observations['records']!=(0 if name=='lifecycle_missing_ptx' else 8) or ids!=[0] or counters['submitted']!=1 or counters['delivered']!=1:raise ValueError('Lifecycle cycle accounting mismatch')
                    cycles.append({'queue':counters,'shading':counts,'observations':observations})
                report['runs'].append({'case':folder.name,'checks':result,'cycles':cycles,'log_hashes':{f.name:digest_file(f) for f in folder.iterdir() if f.is_file()}})
                continue
            if name=='coalesce_timeout':
                if (folder/'shading.log').exists() or (folder/'shading.bin').exists():raise ValueError('Empty batch initialized GPU bridge')
                counts={'gpu_not_initialized':True}
                observations=native_integration.records(b'XNI1')
            else:
                counts=native_integration.summary((folder/'shading.log').read_text())
                observations=native_integration.records((folder/'shading.bin').read_bytes())
                native_integration.verify_counts(counts,observations,'replace')
            expected=0 if name=='coalesce_timeout' else 520 if name=='capacity' else 264 if name=='shutdown' else 16
            if observations['records']!=expected:raise ValueError('Unexpected shader sample count')
            rows=[json.loads(x) for x in (folder/'queue.log').read_text().splitlines() if x.startswith('{')]
            counters=[r for r in rows if 'calls' in r][-1]
            deliveries=[r for r in rows if 'delivered_id' in r]
            ids=[r['delivered_id'] for r in deliveries]
            if len(set(ids))!=len(ids) or len(ids)!=counters['delivered']:raise ValueError('Duplicate/missing publication')
            if name=='capacity' and set(ids)!=set(range(65)):raise ValueError('Capacity delivery identities differ')
            if name=='coalesce_timeout' and (ids or counters.get('cancelled_before_dispatch')!=1 or counters['worker_batches']):raise ValueError('Empty batch submitted work')
            if name=='shutdown' and (set(ids)!=set(range(33)) or counters.get('closed_fallback')!=2):raise ValueError('Shutdown request accounting failed')
            if name=='timeout' and ids!=[1]:raise ValueError('Cancelled request published')
            if name=='pending_timeout':
                if ids!=[64]:raise ValueError('Pending cancelled request published')
                if counters.get('cancelled_before_dispatch')!=63 or counters['late_discarded']!=1:raise ValueError('Cancelled work was not pruned')
            if counters['calls']!=counters['submitted']+counters['cpu_batches']+counters['queue_full']+counters.get('closed_fallback',0):raise ValueError('Unaccounted caller')
            if counters['submitted']!=counters['delivered']+counters['timeouts'] or counters['timeouts']!=counters['late_discarded']+counters.get('cancelled_before_dispatch',0):raise ValueError('Incomplete request accounting')
            record={'case':folder.name,'checks':result,'queue':counters,'delivery_ids':ids,'shading':counts,'observations':observations,'log_hashes':{f.name:digest_file(f) for f in folder.iterdir() if f.is_file()}}
            report['runs'].append(record)
        if identities!={str(x):digest_file(x) for x in files} or report['gpu']!=gpu_identity():raise ValueError('Source or device drift')
        report['status']='passed'
    except Exception as e:
        report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
