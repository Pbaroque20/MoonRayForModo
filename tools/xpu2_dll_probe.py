"""Test actual queue cleanup across a separately loaded Windows diagnostic DLL."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2 import native_integration,queue_integration
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--ptx',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();source=a.source.resolve();ptx=a.ptx.resolve();out=a.output.resolve()
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    dependencies=[ROOT/'xpu2/queue_dll_probe.cc',ROOT/'xpu2/queue_dll_host.cc',ROOT/'xpu2/native_queue_stress.cc',ROOT/'xpu2/native_lambert_queue.cc',ROOT/'xpu2/native_integration.py',ROOT/'xpu2/queue_integration.py',Path(__file__).resolve(),ptx]
    identities={str(f):digest_file(f) for f in dependencies}
    report={'status':'incomplete','scope':'Windows diagnostic DLL load/run/explicit cleanup/unload; not a Modo plugin or native shading DLL unload test','source_hashes':identities,'gpu':gpu_identity(),'runs':[]}
    try:
        raw=gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes())
        if hashlib.sha256(raw).hexdigest()!='39715df807458a8da5746fd8133f5a552ae5dd6116738f2d57010c66401b5ee3':raise ValueError('Reference drift')
        capture=out/'reference.bin';capture.write_bytes(raw)
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
        includes=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        env=environment(compiler.parent,out)
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(includes)]
        build={}
        for label,src,output,linkflags in [('dll',dependencies[0],out/'queue-probe.dll',['-shared']),('host',dependencies[1],out/'queue-host.exe',[])]:
            preprocessed=out/(label+'.ii')
            for phase,args in [('preprocess',['-E',str(src),'-o',str(preprocessed)]),('compile',[str(preprocessed),*linkflags,'-o',str(output)])]:
                done=subprocess.run([str(compiler),*flags,*args],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
                (out/(label+'-'+phase+'.log')).write_text(done.stdout+done.stderr,encoding='utf-8')
                if done.returncode:raise ValueError(label+' '+phase+' failed')
            build[label]={'preprocessed_sha256':digest_file(preprocessed),'binary_sha256':digest_file(output)}
        report.update(build=build,compiler_sha256=digest_file(compiler))
        for scenario,loads in [('lifecycle',4),('lifecycle_missing_ptx',4),('shutdown',2)]:
            folder=out/scenario;folder.mkdir()
            runenv=environment(compiler.parent,folder)
            runenv.update(XPU2_NATIVE_LAMBERT='sentinel',XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if scenario=='lifecycle_missing_ptx' else ptx),XPU2_QUEUE_CAPACITY='64',XPU2_QUEUE_POLICY='all')
            print('DLL boundary '+scenario,flush=True)
            done=subprocess.run([str(out/'queue-host.exe'),str(out/'queue-probe.dll'),scenario,str(capture),str(folder),str(loads)],env=runenv,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/'process.log').write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError('DLL host failed: '+scenario)
            checks=[json.loads(line) for line in done.stdout.splitlines() if line.startswith('{')]
            if len(checks)!=loads+1 or not all(r.get('passed') is True for r in checks):raise ValueError('Missing scenario checks')
            if checks[-1]!={'loader':True,'loads':loads,'unloads':loads,'passed':True}:raise ValueError('Incomplete DLL unload checks')
            cycles=[]
            for index in range(loads):
                load=folder/('load-'+str(index))
                for suffix in (['.0','.1','.2','.3'] if scenario.startswith('lifecycle') else ['']):
                    counts=native_integration.summary((load/('shading.log'+suffix)).read_text())
                    observed=native_integration.records((load/('shading.bin'+suffix)).read_bytes())
                    missing=scenario=='lifecycle_missing_ptx'
                    if missing:
                        if counts['errors']!=1 or counts['samples']!=8 or counts['accepted'] or counts['replaced'] or observed['records']:raise ValueError('Incorrect partial-init fallback')
                    else:native_integration.verify_counts(counts,observed,'replace')
                    text=(load/('queue.log'+suffix)).read_text()
                    if scenario=='shutdown':
                        rows=[json.loads(line) for line in text.splitlines() if line.startswith('{')]
                        counters=[r for r in rows if 'calls' in r][-1]
                        ids=[r['delivered_id'] for r in rows if 'delivered_id' in r]
                        if len(ids)!=33 or set(ids)!=set(range(33)) or counters['closed_fallback']!=2 or counters['timeouts'] or observed['records']!=264:raise ValueError('Incomplete drain before unload')
                    else:
                        counters=queue_integration.verify(text,None if missing else 8)
                        if counters['submitted']!=1 or counters['delivered']!=1:raise ValueError('Incorrect lifecycle request count')
                    cycles.append({'load':index,'suffix':suffix,'queue':counters,'shading':counts,'observations':observed})
            report['runs'].append({'scenario':scenario,'checks':checks,'cycles':cycles,'log_hashes':{str(f.relative_to(folder)):digest_file(f) for f in folder.rglob('*') if f.is_file()}})
        if identities!={str(f):digest_file(f) for f in dependencies} or report['gpu']!=gpu_identity():raise ValueError('Source or GPU drift')
        if build['dll']['binary_sha256']!=digest_file(out/'queue-probe.dll') or build['host']['binary_sha256']!=digest_file(out/'queue-host.exe'):raise ValueError('Probe binary drift')
        report['status']='passed'
    except Exception as e:
        report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
