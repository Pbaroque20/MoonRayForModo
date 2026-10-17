"""Strict native direction-sampling corpus and separate numerical diagnostics."""
import gzip
import itertools
import json
import math
import struct


def floats(words):
    return struct.unpack('<%df' % len(words), struct.pack('<%dI' % len(words), *words))


def read(path):
    text = gzip.decompress(path.read_bytes()).decode('utf-8') if path.suffix == '.gz' else path.read_text(encoding='utf-8')
    rows = [json.loads(line) for line in text.splitlines()]
    kind=rows[0].get('kind') if rows else None
    if kind not in ('lambert_sample','lambert_sample_stress'):
        raise ValueError('Unknown sampling corpus')
    normals,pairs=(11,64) if kind=='lambert_sample_stress' else (5,16)
    keys = list(itertools.product(range(2), range(normals), range(2), range(2), range(3), range(2), range(2), range(pairs)))
    if not rows or rows[0] != {'schema': 1, 'kind': kind, 'simd_width': 8, 'cases': len(keys)} or len(rows) != len(keys)+1:
        raise ValueError('Incomplete Lambert sampling corpus')
    for i, (row, key) in enumerate(zip(rows[1:], keys)):
        if type(row.get('id')) is not int or row['id'] != i or row.get('key') != list(key) or any(type(k) is not int for k in row['key']):
            raise ValueError('Invalid sampling case coverage')
        for name, size in (('input',24), ('cpp',8), ('vector',8)):
            data = row.get(name)
            if not isinstance(data,list) or len(data)!=size or any(type(v) is not int or not 0<=v<=0xffffffff for v in data):
                raise ValueError('Invalid sampling packet')
        src = row['input']
        if src[:2] != [0x32535058,1] or src[13]!=0 or src[20:] != [key[0],key[6],0,0]:
            raise ValueError('Invalid sampling controls')
        params = floats(src[2:20])
        if not all(math.isfinite(v) for v in params) or any(v<0 for v in params[12:]):
            raise ValueError('Invalid sampling parameters')
        for offset in (0,3,6):
            if abs(sum(v*v for v in params[offset:offset+3])-1)>0.0001:
                raise ValueError('Nonunit sampling input')
        if not all(0<=v<=1 for v in params[9:11]):
            raise ValueError('Invalid random samples')
        for name in ('cpp','vector'):
            vals = floats(row[name][:7])
            if not all(math.isfinite(v) for v in vals) or any(v<0 for v in vals[3:]) or row[name][7] not in (0,1):
                raise ValueError('Invalid sampled output')
            if abs(sum(v*v for v in vals[:3])-1)>0.0001:
                raise ValueError('Nonunit sampled direction')
    return rows


def ordered(bits):
    return (~bits & 0xffffffff) if bits & 0x80000000 else bits | 0x80000000


def metrics(pairs):
    pairs=list(pairs)
    a=floats([x for x,y in pairs]); b=floats([y for x,y in pairs])
    nonfinite=sum(not (math.isfinite(x) and math.isfinite(y)) for x,y in zip(a,b))
    differences=[abs(x-y) for x,y in zip(a,b)]
    return {'components':len(pairs), 'different_bits':sum(x!=y for x,y in pairs),
            'numerically_different':sum(x!=y for x,y in zip(a,b)),
            'nonfinite_pairs':nonfinite,
            'max_absolute':None if nonfinite else max(differences,default=0),
            'rms':None if nonfinite else math.sqrt(sum(v*v for v in differences)/len(pairs)) if pairs else 0,
            'max_ulp':max((abs(ordered(x)-ordered(y)) for x,y in pairs),default=0)}


def compare(paths):
    if len(paths)<2:raise ValueError('Repeated executions required')
    parsed=[read(p) for p in paths]
    same=all(p==parsed[0] for p in parsed[1:])
    rows=parsed[0][1:]
    comparison={name:metrics((r['cpp'][i],r['vector'][i]) for r in rows for i in indices)
                for name,indices in (('direction',range(3)),('rgb',range(3,6)),('pdf',[6]))}
    flags=sum(r['cpp'][7]!=r['vector'][7] for r in rows)
    exact=not flags and not any(m['different_bits'] for m in comparison.values())
    return {'status':'passed' if same else 'failed','cases':len(rows),
            'components_per_mode':len(rows)*7,'executions':len(paths),
            'all_execution_records_identical':same,
            'different_components':{'execution_records':sum(a!=b for p in parsed[1:] for a,b in zip(parsed[0][1:],p[1:]))},
            'cpp_vs_vector':comparison,'geometric_validity_differences':flags,
            'cpp_vector_bitwise_parity':exact,
            'scope':'Repeatability of original C++ and AVX8 ISPC Lambert sampling; cross-backend parity is reported separately, not assumed'}


def records(reference,tables=False):
    output=[]
    for r in read(reference)[1:]:
        data=struct.pack('<24I',*r['input'])
        output.append({'input':data,'output':data,'length':96,'result':[0,*r['cpp']],
                       'vector':[0,*r['vector']],'dims':7,'case':r['id']})
    base=list(struct.unpack('<24I',output[0]['input']))
    guards=[('unsupported',[(22,1),(23,1),(14,0x7f7fffff),(17,0x7f7fffff)],1),
            ('invalid',[(0,0),(1,2),(2,0x7fc00000),(5,0x7f800000),(10,0),(11,0x40000000),
                        (12,0xbf800000),(13,1),(14,0xbf800000),(17,0x7f800000),(20,2),(21,2)],2)]
    for label,edits,status in guards:
        for field,value in edits:
            words=base[:];words[field]=value;data=struct.pack('<24I',*words)
            output.append({'input':data,'output':data,'length':96,'result':[status]+[0]*8,'dims':0,'case':label})
    data=output[0]['input'];output.append({'input':data,'output':data,'length':95,'result':[2]+[0]*8,'dims':0,'case':'invalid'})
    return output


def validate(records,returned,result_words,stride=96):
    import hashlib
    if stride!=96 or len(returned)!=len(records)*96 or len(result_words)!=len(records)*9:
        raise ValueError('Truncated sampling output')
    words=[list(result_words[i*9:(i+1)*9]) for i in range(len(records))]
    states=sum(returned[i*96:(i+1)*96]!=r['output'] for i,r in enumerate(records))
    statuses=sum(w[0]!=r['result'][0] for r,w in zip(records,words))
    guards=sum(w!=r['result'] for r,w in zip(records,words) if r['result'][0]!=0)
    supported=[(r,w) for r,w in zip(records,words) if r['result'][0]==0]
    finite=all(math.isfinite(v) for r,w in supported for v in floats(w[1:8]))
    comparisons={}
    for mode in ('result','vector'):
        comparisons['cpp' if mode=='result' else mode]={
            name:metrics((r[mode][i],w[i]) for r,w in supported for i in indices)
            for name,indices in (('direction',range(1,4)),('rgb',range(4,7)),('pdf',[7]))}
        comparisons['cpp' if mode=='result' else mode]['geometric_validity_differences']=sum(r[mode][8]!=w[8] for r,w in supported)
    digest=hashlib.sha256()
    for r,w in sorted(supported,key=lambda pair:pair[0]['case']):
        digest.update(struct.pack('<9I',*w))
    exact=all(w==r['result'] for r,w in supported)
    return {'passed':not(states or statuses or guards) and finite and exact,
            'transport_guards_passed':not(states or statuses or guards),'finite_outputs':finite,
            'records':len(records),'supported_records':len(supported),
            'unsupported_records':sum(r['result'][0]==1 for r in records),
            'invalid_records':sum(r['result'][0]==2 for r in records),
            'state_mismatch_records':states,'status_mismatch_records':statuses,'guard_mismatch_records':guards,
            'cpp_bitwise_parity':exact,
            'vector_bitwise_parity':all(w==r['vector'] for r,w in supported),
            'comparisons':comparisons,
            'canonical_result_sha256':digest.hexdigest()}


def validate_vector(records,returned,result_words,stride=96):
    result=validate(records,returned,result_words,stride=stride)
    result['passed']=(result['transport_guards_passed'] and result['finite_outputs'] and result['vector_bitwise_parity'])
    return result
