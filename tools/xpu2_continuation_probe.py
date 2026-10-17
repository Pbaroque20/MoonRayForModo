"""Validate owned CPU-resume leases with the real diagnostic GPU queue."""
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
from xpu2 import native_integration
from xpu2.surface_state import decode as decode_surface
from xpu2.correlated_state import decode as decode_correlated
import struct
from xpu2_repeatability import gpu_identity
from xpu2_baseline import environment

CASES={'pressure':(65,0,512),'missing_ptx':(65,0,0),'restart':(1,0,16),
       'leased_restart':(1,1,16),'ready_restart':(1,0,16),'admission_fallback':(1,1,0)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--ptx',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--surface-capture',type=Path,help='Optional XNS1 numeric native state; independent of the shader-packet fixture')
    p.add_argument('--correlated-capture',type=Path,help='XCL1 same-call native sampler/shader fixture')
    a=p.parse_args();source=a.source.resolve();ptx=a.ptx.resolve();out=a.output.resolve()
    if a.surface_capture and a.correlated_capture:p.error('Choose one state fixture')
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    files=[ROOT/'xpu2/continuation_probe.cc',ROOT/'xpu2/continuation_mailbox.h',ROOT/'xpu2/native_lambert_queue.cc',
           ROOT/'xpu2/native_integration.py',ROOT/'xpu2/surface_state.py',ROOT/'xpu2/correlated_state.py',Path(__file__).resolve(),ptx]
    if a.surface_capture:files.append(a.surface_capture.resolve())
    if a.correlated_capture:files.append(a.correlated_capture.resolve())
    identities={str(f):digest_file(f) for f in files}
    report={'status':'incomplete','scope':'Real GPU shader queue with owned synthetic continuation metadata; not a native MoonRay path continuation or render','source_hashes':identities,'gpu':gpu_identity(),'runs':[]}
    try:
        raw=gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes())
        if hashlib.sha256(raw).hexdigest()!='39715df807458a8da5746fd8133f5a552ae5dd6116738f2d57010c66401b5ee3':raise ValueError('Native capture drift')
        correlated_rows=None
        if a.correlated_capture:
            correlated_rows=decode_correlated(a.correlated_capture.resolve().read_bytes())
            # Repeat actual events to fill bounded stress packets, preserving every
            # lane's matching context. These repetitions are not new image samples.
            raw=bytearray(b'XNI1')
            for index in range(66*8):
                row=correlated_rows[index%len(correlated_rows)]
                output=row['output'][:7]+[int(struct.unpack('<f',struct.pack('<I',row['output'][7]))[0])]
                raw.extend(struct.pack('<24I',*row['input'])+struct.pack('<8I',*output)+bytes(36))
        capture=out/'reference.bin';capture.write_bytes(raw)
        report['shader_fixture_sha256']=digest_file(capture)
        surface_args=[]
        if a.surface_capture:
            surface=a.surface_capture.resolve();rows=decode_surface(surface.read_bytes())
            report['native_surface_fixture']={'path':str(surface),'sha256':digest_file(surface),'records':len(rows),
                'pairing':'Native numeric state and shader captures are independent fixtures, not the same path event'}
            report['scope']='Real GPU queue ownership test with native numeric surface payloads; no native path resumption'
            surface_args=[str(surface)]
        if a.correlated_capture:
            correlated=a.correlated_capture.resolve()
            report['correlated_fixture']={'path':str(correlated),'sha256':digest_file(correlated),'events':len(correlated_rows),
                'repetition':'Actual same-call events repeated to fill stress packets; not extra rendered samples'}
            report['scope']='Real GPU queue using correlated native sampler metadata and matching Lambert packets; no native path resumption'
            surface_args=[str(correlated)]
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
        headers=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        env=environment(compiler.parent,out)
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(headers)]
        pp=out/'continuation.ii';exe=out/'continuation-probe.exe'
        for label,args in [('preprocess',['-E',str(files[0]),'-o',str(pp)]),('compile',[str(pp),'-o',str(exe)])]:
            done=subprocess.run([str(compiler),*flags,*args],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError(label+' failed')
        report.update(compiler_sha256=digest_file(compiler),preprocessed_sha256=digest_file(pp),executable_sha256=digest_file(exe))
        for name,(accepted,revoked,samples) in CASES.items():
            folder=out/name;folder.mkdir()
            runenv=environment(compiler.parent,folder)
            runenv.update(XPU2_NATIVE_LAMBERT='sentinel',XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if name=='missing_ptx' else ptx),
                          XPU2_NATIVE_LAMBERT_LOG=str(folder/'shading.log'),XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shading.bin'),
                          XPU2_QUEUE_CAPACITY='0' if name=='admission_fallback' else '64',XPU2_QUEUE_POLICY='all',XPU2_QUEUE_LOG=str(folder/'queue.log'))
            print('Continuation '+name,flush=True)
            done=subprocess.run([str(exe),name,str(capture),*surface_args],env=runenv,capture_output=True,text=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/'process.log').write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError('Continuation process failed: '+name)
            checks=json.loads(done.stdout)
            if checks!={'case':name,'accepted_cpu_resumes':accepted,'revoked_cpu_resumes':revoked,'outstanding':0,'passed':True}:raise ValueError('Incomplete continuation checks')
            if name=='admission_fallback':
                if (folder/'shading.log').exists() or (folder/'shading.bin').exists():raise ValueError('Admission fallback initialized GPU')
                counts={'gpu_not_initialized':True};observed=native_integration.records(b'XNI1')
            else:
                counts=native_integration.summary((folder/'shading.log').read_text())
                observed=native_integration.records((folder/'shading.bin').read_bytes())
                if name=='missing_ptx':
                    if not counts['errors'] or counts['samples']!=512 or counts['accepted'] or counts['replaced']:raise ValueError('Incorrect native fallback')
                else:native_integration.verify_counts(counts,observed,'replace')
            if observed['records']!=samples:raise ValueError('Shader work differs from expected')
            rows=[json.loads(line) for line in (folder/'queue.log').read_text().splitlines() if line.startswith('{')]
            q=[r for r in rows if 'calls' in r][-1];ids=[r['delivered_id'] for r in rows if 'delivered_id' in r]
            if len(ids)!=len(set(ids)) or len(ids)!=q['delivered'] or q['retained_async'] or q['worker_failures']:raise ValueError('Invalid terminal queue state')
            if q['calls']!=q['submitted']+q['queue_full']+q['closed_fallback']+q['cpu_batches']:raise ValueError('Missing admission')
            if q['submitted']!=q['delivered']+q['cancelled_requests']+q['timeouts']:raise ValueError('Missing terminal result')
            if q['cancelled_requests']+q['timeouts']!=q['late_discarded']+q['cancelled_before_dispatch']:raise ValueError('Missing cancellation')
            report['runs'].append({'case':name,'checks':checks,'queue':q,'delivery_ids':ids,'shading':counts,'observations':observed,
                                   'log_hashes':{f.name:digest_file(f) for f in folder.iterdir() if f.is_file()}})
        if identities!={str(f):digest_file(f) for f in files} or report['gpu']!=gpu_identity():raise ValueError('Source/device drift')
        if report['executable_sha256']!=digest_file(exe):raise ValueError('Probe executable drift')
        report['status']='passed'
    except Exception as e:report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
