"""Strict intersection of captured Lambert and native contribution stages."""
import math
import struct
from xpu2.correlated_state import decode

def join(lambert, contribution):
    rows=decode(lambert)
    if contribution[:4]!=b'XCR1' or (len(contribution)-4)%160:
        raise ValueError('Malformed contribution capture')
    if not 1<=(len(contribution)-4)//160<=4096:
        raise ValueError('Contribution count out of bounds')
    index={}
    for row in rows:
        m=row['metadata'];key=tuple(m[k] for k in (0,1,2,3,10,11,13,12))
        if key in index:raise ValueError('Ambiguous Lambert identity')
        index[key]=row
    matched=[];unmatched=[];seen=set()
    for off in range(4,len(contribution),160):
        words=struct.unpack_from('<40I',contribution,off);key=words[:8]
        if key in seen:raise ValueError('Duplicate contribution identity')
        seen.add(key)
        if key not in index:unmatched.append(key);continue
        row=index[key]
        if row['output'][7]!=0:raise ValueError('Geometrically invalid Lambert sample')
        values=struct.unpack('<24f',struct.pack('<24I',*words[8:32]));out=words[32:]
        if not all(math.isfinite(v) for v in values+struct.unpack('<8f',struct.pack('<8I',*out))):
            raise ValueError('Nonfinite contribution')
        if values[0]<=0 or values[1]<0 or values[7]<=0 or any(values[k] not in (0,1) for k in (2,3,4)) or any(values[17:]):
            raise ValueError('Invalid contribution domain')
        if values[3]!=0 or values[4]!=0 or values[5]<=0:
            raise ValueError('Only nonmirror valid-light samples supported')
        if words[15]!=row['output'][6] or words[19:22]!=tuple(row['output'][3:6]):
            raise ValueError('Lambert contribution boundary mismatch')
        if words[16:19]!=tuple(row['metadata'][19:22]):raise ValueError('Throughput mismatch')
        matched.append(dict(identity=key,lambert=row['input'],sample=row['output'],contribution=list(words[8:32]),expected=list(out)))
    if not matched:raise ValueError('No joined samples')
    return matched,unmatched
