"""Native Lambert evaluation corpus and strict CUDA diagnostic expectations."""
import gzip
import itertools
import json
import math
import struct


def read(path):
    text=gzip.decompress(path.read_bytes()).decode('utf-8') if path.suffix=='.gz' else path.read_text(encoding='utf-8')
    rows=[json.loads(line) for line in text.splitlines()]
    keys=list(itertools.product(range(5),range(2),range(8),range(3),range(4),range(3),range(2),range(2)))
    if not rows or rows[0]!={'schema':1,'kind':'lambert_eval','cases':len(keys)} or len(rows)!=1+len(keys):
        raise ValueError('Incomplete Lambert corpus')
    for i,(r,key) in enumerate(zip(rows[1:],keys)):
        if type(r.get('id')) is not int or r['id']!=i or r.get('key')!=list(key) or any(type(k) is not int for k in r.get('key',[])):
            raise ValueError('Invalid Lambert case coverage')
        src,dst=r.get('input'),r.get('output')
        if (not isinstance(src,list) or len(src)!=24 or not isinstance(dst,list) or len(dst)!=8
            or any(type(v) is not int or not 0<=v<=0xffffffff for v in src+dst)):
            raise ValueError('Invalid Lambert packet')
        if src[:2]!=[0x324c5058,1] or src[20:]!=[key[6],key[7],0,0] or dst[7] not in (0,1):
            raise ValueError('Wrong Lambert controls')
        floats=struct.unpack('<18f',struct.pack('<18I',*src[2:20]))
        if not all(math.isfinite(v) for v in floats) or any(v<0 for v in floats[12:]):
            raise ValueError('Invalid Lambert parameters')
        for offset in (0,3,6,9):
            if abs(sum(v*v for v in floats[offset:offset+3])-1)>0.0001:
                raise ValueError('Nonunit direction')
        values=struct.unpack('<7f',struct.pack('<7I',*dst[:7]))
        if not all(math.isfinite(v) and v>=0 for v in values):
            raise ValueError('Invalid Lambert output')
    return rows


def compare(paths):
    if len(paths)<2:raise ValueError('Repeated native executions required')
    parsed=[read(p) for p in paths];same=all(r==parsed[0] for r in parsed[1:])
    return {'status':'passed' if same else 'failed','cases':len(parsed[0])-1,
            'components_per_mode':(len(parsed[0])-1)*7,'executions':len(paths),
            'all_execution_records_identical':same,'different_components':{'execution_records':sum(a!=b for rows in parsed[1:] for a,b in zip(parsed[0][1:],rows[1:]))},
            'scope':'Original C++ Lambert eval/albedo/PDF/geometric validity; not native ISPC or rendered parity'}


def records(reference,tables=False):
    output=[]
    for r in read(reference)[1:]:
        data=struct.pack('<24I',*r['input'])
        output.append({'input':data,'output':data,'length':96,'result':[0,*r['output']],'dims':7,'case':r['id']})
    base=list(struct.unpack('<24I',output[0]['input']))
    for field,value in ((22,1),(23,1),(14,0x7f7fffff),(17,0x7f7fffff)):
        words=base[:];words[field]=value;data=struct.pack('<24I',*words)
        output.append({'input':data,'output':data,'length':96,'result':[1]+[0]*8,'dims':0,'case':'unsupported'})
    for field,value in ((0,0),(1,2),(2,0x7fc00000),(5,0x7f800000),(10,0),(11,0x40000000),(14,0xbf800000),(17,0x7f800000),(20,2),(21,2)):
        words=base[:];words[field]=value;data=struct.pack('<24I',*words)
        output.append({'input':data,'output':data,'length':96,'result':[2]+[0]*8,'dims':0,'case':'invalid'})
    data=output[0]['input'];output.append({'input':data,'output':data,'length':95,'result':[2]+[0]*8,'dims':0,'case':'invalid'})
    return output


def validate(records,returned,result_words,stride=96):
    if stride!=96 or len(returned)!=len(records)*96 or len(result_words)!=len(records)*9:
        raise ValueError('Truncated Lambert output')
    bad_states=sum(returned[i*96:(i+1)*96]!=r['output'] for i,r in enumerate(records))
    bad_results=sum(list(result_words[i*9:(i+1)*9])!=r['result'] for i,r in enumerate(records))
    counts={s:sum(r['result'][0]==s for r in records) for s in (0,1,2)}
    return {'passed':not(bad_states or bad_results),'records':len(records),'supported_records':counts[0],
            'unsupported_records':counts[1],'invalid_records':counts[2],
            'compared_sample_components':counts[0]*7,'geometric_validity_checks':counts[0],
            'state_mismatch_records':bad_states,'sample_or_status_mismatch_records':bad_results}
