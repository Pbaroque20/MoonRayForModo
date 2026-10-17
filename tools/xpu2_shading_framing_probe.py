"""Validate native combined shading framing in an isolated output directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from xpu2.reference import verify
from xpu2.shading_exchange import encode_batch,decode_batch
from xpu2.lambert_sample import read as read_materials
import struct
from xpu2.cuda_window_samples import records
from xpu2.cuda_samples import validate


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('native','runtime','source','reference','materials','output'):
        p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args()
    source,out=a.source.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(a.native.resolve()) or out.is_relative_to(a.runtime.resolve()):
        p.error('Use a fresh isolated output directory')
    out.mkdir(parents=True,exist_ok=False)
    meta=json.loads((a.native/'report.json').read_text(encoding='utf-8'))
    exe=(a.native/'sampler.exe').resolve()
    if (meta.get('status')!='passed' or meta.get('shading_exchange_protocol')!='XHB1-XHO1'
            or sha(exe)!=meta['executable_sha256']):
        raise ValueError('Verified native exchange reference required')
    verify(a.runtime,meta['runtime_inventory'])
    env=dict(os.environ)
    env['PATH']=str(a.runtime.resolve())+os.pathsep+str(source/'toolchain/msys64/ucrt64/bin')+os.pathsep+env.get('PATH','')
    sample=next(r for r in records(a.reference) if r.get('mode')=='baseline' and r['dims']==2)
    material=read_materials(a.materials)[1]['input']
    state=struct.pack('<4I',0x31485358,1,1,0)+sample['input']+struct.pack('<24I',*material)+bytes(32)
    row={'input':state,'length':208};good=encode_batch([row])
    inputs={'control':good,'bad_magic':b'BAD!'+good[4:],'empty':good[:4]+(0).to_bytes(4,'little'),
            'oversized':good[:4]+(32769).to_bytes(4,'little'),'short_header':good[:5],
            'short_state':good[:-1],'trailing':good+b'x'}
    results=[]
    for label,data in inputs.items():
        src=out/(label+'.in');dst=out/(label+'.out');src.write_bytes(data)
        done=subprocess.run([str(exe),'1','shade_exchange',str(src),str(dst)],cwd=out,env=env,
                            capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        if label=='control':
            returned,words=decode_batch(dst.read_bytes(),1) if done.returncode==0 else (b'',[])
            passed=done.returncode==0 and words[0]==0 and returned[:16]==state[:16] and returned[16:80]==sample['output'] and words[1:4]==sample['result'][1:4] and returned[112:124]==struct.pack('<3I',*words[4:7])
        else:
            passed=done.returncode==3 and not dst.exists()
        results.append({'case':label,'passed':passed,'exit_code':done.returncode,
                        'message':done.stderr.decode(errors='replace').strip()})
    verify(a.runtime,meta['runtime_inventory'])
    if sha(exe)!=meta['executable_sha256']:
        raise ValueError('Native exchange executable changed')
    report={'passed':all(r['passed'] for r in results),'executable_sha256':sha(exe),
            'reference_sha256':sha(a.reference),'materials_sha256':sha(a.materials),'tool_sha256':sha(Path(__file__)), 'cases':results}
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not report['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
