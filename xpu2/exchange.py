"""Diagnostic CPU/CUDA handoffs; transport is synchronous, not a renderer scheduler."""
import hashlib
import random
import struct
from .cuda_samples import validate
from .cuda_window_samples import continuation_cases


def encode_batch(batch):
    if not 0 < len(batch) <= 32768 or any(len(r['input']) != 64 for r in batch):
        raise ValueError('Invalid native exchange batch')
    return struct.pack('<4sI',b'XWB2',len(batch))+b''.join(struct.pack('<I',r['length'])+r['input'] for r in batch)


def decode_batch(data,count):
    if (not 0 < count <= 32768 or len(data) != 8+84*count
            or struct.unpack('<4sI',data[:8]) != (b'XWO2',count)):
        raise ValueError('Incomplete or invalid native exchange output')
    states=[];words=[]
    for offset in range(8,len(data),84):
        states.append(data[offset:offset+64])
        words.extend(struct.unpack('<5I',data[offset+64:offset+84]))
    return b''.join(states),words


def owner(plan,case,step):
    if plan=='alternating':
        return (step+case)%2
    if plan=='chunks7':
        return (step//7+case)%2
    if plan=='shuffled':
        return random.Random(913+case*65536+step).randrange(2)
    raise ValueError('Unknown handoff schedule')


def run_handoffs(items,cpu,gpu):
    cases=continuation_cases(items)
    expected={(r['case'],r['sample']) for samples in cases.values() for r in samples}
    reports=[]
    for plan,workers in [('alternating',1),('chunks7',4),('shuffled',4)]:
        states={key:samples[0]['input'] for key,samples in cases.items()}
        last={};engines={key:set() for key in cases};published={}
        transitions={'cpu_to_gpu':0,'gpu_to_cpu':0}
        counters={'cpu_samples':0,'gpu_samples':0,'fallback_samples':0,'retry_samples':0}
        checks=[]
        for step in range(48):
            for device in (0,1):
                batch=[dict(samples[step],input=states[key]) for key,samples in cases.items()
                       if step<len(samples) and owner(plan,key,step)==device]
                random.Random(719+step*2+device).shuffle(batch)
                if not batch:
                    continue
                actual=device
                if device==1 and step%16==7:
                    returned,words=gpu(batch,128,False)
                    declined=[dict(r,output=r['input'],result=[1,r['result'][1],0,0,0]) for r in batch]
                    check=validate(declined,returned,words,stride=64);checks.append(check)
                    if not check['passed']:
                        return {'passed':False,'failure':'GPU fallback changed state','plans':reports}
                    batch=[dict(r,input=returned[i*64:(i+1)*64]) for i,r in enumerate(batch)]
                    counters['fallback_samples']+=len(batch)
                    actual=0
                returned,words=(cpu(batch,workers) if actual==0 else gpu(batch,(64,128,256)[step%3],True))
                check=validate(batch,returned,words,stride=64);checks.append(check)
                if not check['passed']:
                    return {'passed':False,'failure':'Handoff sample/state mismatch','plan':plan,'step':step,'engine':actual,'check':check,'plans':reports}
                if step%13==5:
                    retry=batch[:11]
                    again,values=(gpu(retry,64,True) if actual==0 else cpu(retry,workers))
                    check=validate(retry,again,values,stride=64);checks.append(check)
                    if not check['passed']:
                        return {'passed':False,'failure':'Cross-device retry mismatch','plans':reports}
                    counters['retry_samples']+=len(retry)
                counters['cpu_samples' if actual==0 else 'gpu_samples']+=len(batch)
                for i,r in enumerate(batch):
                    key=r['case'];address=(key,r['sample'])
                    if address in published:
                        raise ValueError('Duplicate sample publication')
                    result=returned[i*64:(i+1)*64]
                    published[address]=(result,tuple(words[i*5:(i+1)*5]))
                    states[key]=result;engines[key].add(actual)
                    if key in last and last[key]!=actual:
                        transitions['cpu_to_gpu' if actual==1 else 'gpu_to_cpu']+=1
                    last[key]=actual
        digest=hashlib.sha256()
        for address,(state,words) in sorted(published.items()):
            digest.update(struct.pack('<2I',*address)+state+struct.pack('<5I',*words))
        complete=(set(published)==expected and all(engines[k]=={0,1} for k in cases)
                  and all(transitions.values()) and counters['fallback_samples']>0 and counters['retry_samples']>0)
        reports.append({'plan':plan,'passed':bool(complete),'cpu_workers_requested':workers,
                        'cases_on_both_devices':sum(e=={0,1} for e in engines.values()),
                        'unique_samples':len(published),'components':sum(r['dims'] for samples in cases.values() for r in samples),
                        **counters,**transitions,'canonical_output_sha256':digest.hexdigest(),
                        'checks':len(checks)})
    return {'passed':all(r['passed'] for r in reports) and len({r['canonical_output_sha256'] for r in reports})==1,
            'scope':'Real native CPU/CUDA state handoffs with synchronous diagnostic transport; no shading or speedup',
            'plans':reports}
