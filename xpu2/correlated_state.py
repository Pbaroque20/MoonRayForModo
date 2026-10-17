"""Strict same-call ISPC sampler/Lambert capture, without native continuation claims."""
import math
import struct
RECORD=struct.Struct('<60I')
def floats(words):return struct.unpack('<%df'%len(words),struct.pack('<%dI'%len(words),*words))
def decode(data):
    if data[:4]!=b'XCL1' or (len(data)-4)%RECORD.size:raise ValueError('Malformed correlated capture')
    count=(len(data)-4)//RECORD.size
    if not 1<=count<=1024:raise ValueError('Invalid correlated count')
    rows=[]
    for offset in range(4,len(data),RECORD.size):
        words=RECORD.unpack_from(data,offset);m=words[:28];src=words[28:52];out=words[52:]
        if m[0] not in ((77<<16)|96,(96<<16)|132) or m[1]!=0 or m[13]>7 or m[14]>1 or m[27]:raise ValueError('Invalid context identity/flags')
        if m[8]!=m[7]+1 or m[26]==0 or m[11]>=m[26]:raise ValueError('Invalid sampler counter advance')
        if src[:2]!=(0x32535058,1) or src[13] or src[20] not in (0,1) or src[21] not in (0,1):raise ValueError('Invalid Lambert packet')
        if m[24:26]!=src[11:13]:raise ValueError('Sampler/Lambert random mismatch')
        if not all(math.isfinite(v) for v in floats(m[16:26])+floats(src[2:20])+floats(out)):raise ValueError('Nonfinite correlated state')
        if not all(0<=v<=1 for v in floats(m[24:26])) or floats(out[7:])[0] not in (0,1):raise ValueError('Invalid sample/validity')
        rows.append({'metadata':list(m),'input':list(src),'output':list(out)})
    return rows

def match_surface(rows,surfaces):
    matched=[]
    for row in rows:
        m=row['metadata'];p=floats(m[16:19]);throughput=floats(m[19:22])
        candidates=[s for s in surfaces if s['ids']['pixel']==m[0] and s['ids']['subpixel']==m[1]
                    and s['ids']['sequence']==m[2] and s['ids']['nonmirror_depth']==m[3]
                    and tuple(s['fields']['position'])==p and tuple(s['fields']['throughput'])==throughput]
        if len(candidates)!=1:raise ValueError('Missing/ambiguous native surface identity')
        s=candidates[0];src=floats(row['input'][2:11])
        # The material may transform/renormalize N between the pre-shading surface
        # capture and its Lambert lobe. Preserve both stage values; never substitute
        # the earlier N in the GPU packet. Ng and Wo are invariant in this fixture.
        if tuple(s['fields']['geometric_normal'])!=src[3:6] or tuple(-v for v in s['fields']['direction'])!=src[6:9]:raise ValueError('Native surface/shader orientation differs')
        matched.append({'pixel':m[0],'subpixel':m[1],'sequence':m[2],'nonmirror_depth':m[3],
                        'lobe_seed':m[4],'sample_before':m[7],'sample_after':m[8],'lane':m[13],
                        'surface_normal':list(s['fields']['normal']),'lambert_normal':list(src[:3]),
                        'normal_stages_equal':tuple(s['fields']['normal'])==src[:3]})
    return matched
