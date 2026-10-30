"""Atomic diagnostic sampler/AVX8 shading transactions, not a renderer path integrator."""
import hashlib
import math
import random
import struct
from .exchange import owner
from .cuda_window_samples import continuation_cases
from .lambert_sample import read as read_materials

SIZE=208
WORDS=12
PROFILE_AVX8=1


def encode_batch(batch):
    if not 0<len(batch)<=32768 or any(len(r['input'])!=SIZE for r in batch):
        raise ValueError('Invalid shading batch')
    return struct.pack('<4sI',b'XHB1',len(batch))+b''.join(struct.pack('<I',r['length'])+r['input'] for r in batch)


def decode_batch(data,count):
    if not 0<count<=32768 or len(data)!=8+256*count or struct.unpack('<4sI',data[:8])!=(b'XHO1',count):
        raise ValueError('Invalid shading batch response')
    states=[];words=[]
    for offset in range(8,len(data),256):
        states.append(data[offset:offset+SIZE]);words.extend(struct.unpack('<12I',data[offset+SIZE:offset+256]))
    return b''.join(states),words


def material_status(data):
    words=struct.unpack('<24I',data)
    if words[:2]!=(0x32535058,1) or words[13]!=0 or words[20]>1 or words[21]>1:return 2
    v=struct.unpack('<18f',data[8:80])
    if not all(math.isfinite(x) for x in v) or any(x<0 for x in v[12:]):return 2
    def f32(x):
        try:return struct.unpack('<f',struct.pack('<f',x))[0]
        except OverflowError:return math.copysign(math.inf,x)
    for i in (0,3,6):
        dot=f32(f32(f32(v[i]*v[i])+f32(v[i+1]*v[i+1]))+f32(v[i+2]*v[i+2]))
        if abs(f32(dot-1))>f32(.0001):return 2
    if not all(0<=x<=1 for x in v[9:11]):return 2
    return 1 if words[22] or words[23] or any(x>8 for x in v[12:15]) or any(x>2 for x in v[15:18]) else 0


def gpu_batch(batch,sampler,shader,block=128,tables=True,shader_available=True):
    """Both real GPU stages must succeed before publishing any new state."""
    states=[r['input'] for r in batch];words=[[2]+[0]*11 for r in batch]
    eligible=[]
    for i,r in enumerate(batch):
        if len(r['input'])!=SIZE:raise ValueError('Wrong shading storage size')
        magic,version,profile,reserved=struct.unpack('<4I',r['input'][:16])
        if r['length']!=SIZE or magic!=0x31485358 or version!=1 or reserved:continue
        if profile!=PROFILE_AVX8:words[i][0]=1;continue
        if struct.unpack_from('<I',r['input'],24)[0]!=2:continue
        eligible.append(i)
    if eligible:
        sample_records=[{'input':batch[i]['input'][16:80],'length':64} for i in eligible]
        returned,draws=sampler(sample_records,block,tables)
        if len(returned)!=64*len(eligible) or len(draws)!=5*len(eligible):raise ValueError('Truncated GPU sampler response')
        shading=[];selected=[];pending=[];sample_words=[]
        for k,i in enumerate(eligible):
            draw=list(draws[k*5:(k+1)*5]);status=draw[0]
            if status not in (0,1,2):raise ValueError('Unknown sampler status')
            if status:words[i][0]=status;continue
            material=batch[i]['input'][80:176];status=material_status(material)
            if status:words[i][0]=status;continue
            if not shader_available:words[i][0]=1;continue
            candidate=bytearray(batch[i]['input']);candidate[16:80]=returned[k*64:(k+1)*64]
            struct.pack_into('<2I',candidate,124,*draw[2:4])
            selected.append(i);pending.append(candidate);sample_words.append(draw)
            shading.append({'input':bytes(candidate[80:176]),'length':96})
        if shading:
            unchanged,results=shader(shading,block)
            if len(unchanged)!=96*len(shading) or len(results)!=9*len(shading):raise ValueError('Truncated GPU shader response')
            for k,i in enumerate(selected):
                if unchanged[k*96:(k+1)*96]!=shading[k]['input']:raise ValueError('Shader mutated its parameter packet')
                result=list(results[k*9:(k+1)*9]);status=result[0]
                if status not in (0,1,2):raise ValueError('Unknown shader status')
                if status:words[i][0]=status;continue
                candidate=pending[k];struct.pack_into('<8I',candidate,176,*result[1:])
                struct.pack_into('<3I',candidate,112,*result[1:4])
                states[i]=bytes(candidate);words[i]=[0,*sample_words[k][1:4],*result[1:]]
    return b''.join(states),[v for result in words for v in result]


def initial_cases(items,material_reference):
    sample_cases=continuation_cases(items)
    materials=read_materials(material_reference)[1:]
    cases={}
    for key,samples in sample_cases.items():
        if samples[0]['dims']!=2:continue
        m=materials[(len(cases)*617)%len(materials)]
        packet=struct.pack('<4I',0x31485358,1,PROFILE_AVX8,0)+samples[0]['input']+struct.pack('<24I',*m['input'])+bytes(32)
        cases[key]={'input':packet,'length':SIZE,'samples':samples}
    if len(cases)!=108:raise ValueError('Expected complete 2D sample cases')
    return cases


def check(batch,states,words):
    if len(states)!=SIZE*len(batch) or len(words)!=WORDS*len(batch):raise ValueError('Truncated shading result')
    bad_state=sum(states[i*SIZE:(i+1)*SIZE]!=r['output'] for i,r in enumerate(batch))
    bad_words=sum(list(words[i*WORDS:(i+1)*WORDS])!=r['result'] for i,r in enumerate(batch))
    return {'passed':not(bad_state or bad_words),'records':len(batch),'state_mismatches':bad_state,'result_mismatches':bad_words}


def declines(batch,status=1):
    return [dict(r,output=r['input'],result=[status]+[0]*11) for r in batch]


def guard_cases(base):
    result=[]
    for field,value,status in ((0,0,2),(1,2,2),(2,0,1),(2,2,1),(3,1,2),
                               (20,0,2),(33,1,2),(34,0xbf800000,2),(42,1,1),
                               (34,0x7f7fffff,1)):
        data=bytearray(base);struct.pack_into('<I',data,field*4,value)
        result.append({'input':bytes(data),'length':SIZE,'output':bytes(data),'result':[status]+[0]*11})
    data=bytearray(base);data[76]^=1
    result.append({'input':bytes(data),'length':SIZE,'output':bytes(data),'result':[2]+[0]*11})
    result.append({'input':base,'length':SIZE-1,'output':base,'result':[2]+[0]*11})
    return result


def run_handoffs(items,material_reference,cpu,gpu,save_baseline):
    cases=initial_cases(items,material_reference);baseline={};states={k:r['input'] for k,r in cases.items()}
    # Native-only trajectory is generated first; GPU receives no expected outputs.
    for step in range(48):
        keys=[k for k,r in cases.items() if step<len(r['samples'])]
        batch=[{'input':states[k],'length':SIZE} for k in keys]
        returned,words=cpu(batch,1)
        if len(returned)!=SIZE*len(batch) or len(words)!=WORDS*len(batch):raise ValueError('Truncated native baseline')
        for i,k in enumerate(keys):
            result=list(words[i*WORDS:(i+1)*WORDS]);state=returned[i*SIZE:(i+1)*SIZE]
            sample=cases[k]['samples'][step]
            if result[0]!=0 or result[1:4]!=sample['result'][1:4] or state[16:80]!=sample['output']:
                raise ValueError('Native baseline disagrees with pinned sampler or declined shading')
            if state[:16]!=cases[k]['input'][:16] or state[112:124]!=struct.pack('<3I',*result[4:7]):
                raise ValueError('Native baseline failed profile/direction feedback')
            baseline[k,step]={'input':states[k],'output':state,'result':result,'length':SIZE}
            states[k]=state
    save_baseline(baseline)
    guards=guard_cases(next(iter(cases.values()))['input'])
    guard_reports={}
    for name,dispatch in (('cpu',lambda b:cpu(b,4)),('gpu',lambda b:gpu(b,128,True,True))):
        state,words=dispatch(guards);guard_reports[name]=check(guards,state,words)
        if not guard_reports[name]['passed']:return {'passed':False,'failure':'Envelope guard failure','guards':guard_reports}
    reports=[]
    for plan,workers in (('alternating',1),('chunks7',4),('shuffled',4)):
        states={k:r['input'] for k,r in cases.items()};last={};engines={k:set() for k in cases};published={}
        counters=dict(cpu_steps=0,gpu_steps=0,table_fallbacks=0,shader_fallbacks=0,cross_device_retries=0,cpu_to_gpu=0,gpu_to_cpu=0)
        for step in range(48):
            for device in (0,1):
                keys=[k for k,r in cases.items() if (k,step) in baseline and owner(plan,k,step)==device]
                random.Random(791+step*2+device).shuffle(keys)
                if not keys:continue
                batch=[dict(baseline[k,step],input=states[k]) for k in keys];actual=device
                if device==1 and step%16 in (7,11):
                    stage='table' if step%16==7 else 'shader'
                    state,words=gpu(batch,128,stage!='table',stage!='shader')
                    checked=check(declines(batch),state,words)
                    if not checked['passed']:return {'passed':False,'failure':'Nonatomic '+stage+' fallback','check':checked}
                    batch=[dict(r,input=state[i*SIZE:(i+1)*SIZE]) for i,r in enumerate(batch)]
                    counters[stage+'_fallbacks']+=len(batch);actual=0
                state,words=cpu(batch,workers) if actual==0 else gpu(batch,(64,128,256)[step%3],True,True)
                checked=check(batch,state,words)
                if not checked['passed']:return {'passed':False,'failure':'Handoff mismatch','plan':plan,'step':step,'device':actual,'check':checked}
                if step%13==5:
                    retry=batch[:7];again,values=gpu(retry,64,True,True) if actual==0 else cpu(retry,workers)
                    checked=check(retry,again,values)
                    if not checked['passed']:return {'passed':False,'failure':'Cross-device retry mismatch','check':checked}
                    counters['cross_device_retries']+=len(retry)
                counters['cpu_steps' if actual==0 else 'gpu_steps']+=len(batch)
                for i,k in enumerate(keys):
                    address=(k,step)
                    if address in published:raise ValueError('Duplicate shading publication')
                    states[k]=state[i*SIZE:(i+1)*SIZE];published[address]=(states[k],list(words[i*WORDS:(i+1)*WORDS]));engines[k].add(actual)
                    if k in last and last[k]!=actual:counters['cpu_to_gpu' if actual else 'gpu_to_cpu']+=1
                    last[k]=actual
        digest=hashlib.sha256()
        for (key,step),(state,words) in sorted(published.items()):digest.update(struct.pack('<2I',key,step)+state+struct.pack('<12I',*words))
        complete=set(published)==set(baseline) and all(e=={0,1} for e in engines.values()) and all(counters.values())
        reports.append({'plan':plan,'passed':bool(complete),'unique_steps':len(published),'cases_on_both_devices':sum(e=={0,1} for e in engines.values()),
                        'cpu_workers_requested':workers,**counters,'canonical_output_sha256':digest.hexdigest()})
    return {'passed':all(r['passed'] for r in reports) and len({r['canonical_output_sha256'] for r in reports})==1,
            'scope':'Atomic native AVX8/CUDA sampling and shading continuations; synchronous diagnostics with no ray intersections or rendered image',
            'math_profile':'native-avx8','baseline_steps':len(baseline),'guards':guard_reports,'plans':reports}
