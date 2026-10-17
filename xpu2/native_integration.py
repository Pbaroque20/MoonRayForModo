"""Read bounded native/CUDA shading observations without relaxing parity checks."""
import hashlib
import json
import math
import struct


def summary(log):
    rows=[json.loads(line) for line in log.splitlines() if line.startswith('{')]
    if not rows:raise ValueError('Missing native shading summary')
    row=rows[-1]
    fields={'batches','samples','accepted','replaced','unsupported','invalid','mismatch','errors'}
    if set(row)!=fields or any(type(v) is not int or v<0 for v in row.values()):raise ValueError('Malformed native shading summary')
    if row['replaced']>row['accepted']:raise ValueError('Impossible replacement count')
    return row


def records(data):
    if data[:4]!=b'XNI1' or (len(data)-4)%164:raise ValueError('Malformed native shading records')
    result={'records':0,'accepted':0,'unsupported':0,'invalid':0,'mismatch':0,'nonfinite':0,
            'direction_mismatches':0,'rgb_mismatches':0,'pdf_mismatches':0,'validity_mismatches':0}
    cases=[]
    for offset in range(4,len(data),164):
        src=data[offset:offset+96]
        native=struct.unpack_from('<8I',data,offset+96)
        gpu=struct.unpack_from('<9I',data,offset+128)
        if struct.unpack_from('<2I',src)!=(0x32535058,1):raise ValueError('Invalid shader packet')
        if gpu[0] not in (0,1,2):raise ValueError('Unknown GPU shader status')
        result['records']+=1
        if gpu[0]:
            if any(gpu[1:]):raise ValueError('Nonzero declined output')
            result['unsupported' if gpu[0]==1 else 'invalid']+=1
            continue
        finite=all(math.isfinite(v) for v in struct.unpack('<7f',struct.pack('<7I',*gpu[1:8])))
        result['nonfinite']+=not finite
        matched=native==gpu[1:]
        result['accepted' if matched else 'mismatch']+=1
        for name,indices in [('direction',range(3)),('rgb',range(3,6)),('pdf',[6]),('validity',[7])]:
            result[name+'_mismatches']+=sum(native[i]!=gpu[i+1] for i in indices)
        if not matched and len(cases)<8:cases.append({'input':list(struct.unpack('<24I',src)),'native':native,'gpu':gpu})
    result['first_mismatches']=cases
    result['sha256']=hashlib.sha256(data).hexdigest()
    return result


def verify_counts(counts, observations, mode):
    for name in ('accepted','unsupported','invalid','mismatch'):
        if counts[name]!=observations[name]:raise ValueError('Counter/record mismatch: '+name)
    if counts['samples']!=observations['records']:raise ValueError('Unaccounted shading samples')
    if counts['errors'] or counts['invalid'] or counts['mismatch'] or observations['nonfinite']:
        raise ValueError('Native CUDA shading errors or differences')
    if mode=='unsupported':
        if counts['accepted'] or counts['replaced'] or not counts['unsupported']:raise ValueError('Unsupported material escaped fallback')
    elif not counts['accepted']:raise ValueError('No native shading executed on GPU')
    elif counts['replaced']!=(counts['accepted'] if mode=='replace' else 0):raise ValueError('Incorrect replacement mode')
