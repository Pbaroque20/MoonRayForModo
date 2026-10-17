"""Inspect selected-pixel contributions without pretending they have branch IDs."""
from collections import Counter
import json
import math
import struct

PIXELS=((96,77),(132,96))
PREFIXES={'radiance':'XPU2_RADIANCE ', 'queued':'XPU2_SHADOW_QUEUED ', 'shadow':'XPU2_SHADOW_RESULT '}

def f32(value):
    return struct.unpack('<f',struct.pack('<f',value))[0]

def restore(value):
    if isinstance(value,dict):return {k:restore(v) for k,v in value.items()}
    if isinstance(value,list):return [restore(v) for v in value]
    if not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Invalid contribution value')
    return f32(value) if isinstance(value,float) else value

def parse(log):
    result={k:[] for k in PREFIXES}
    for line in log.splitlines():
        for kind,prefix in PREFIXES.items():
            if line.startswith(prefix):
                row=restore(json.loads(line[len(prefix):]));pixel=(row['pixel']&0xffff,row['pixel']>>16)
                if pixel not in PIXELS:raise ValueError('Unexpected contribution pixel')
                if row['sample']!=0:raise ValueError('Expected one camera sample')
                if kind=='radiance' and len(row['rgba'])!=4:raise ValueError('Expected RGBA contribution')
                if kind!='radiance' and len(row['rgb'])!=3:raise ValueError('Expected RGB contribution')
                result[kind].append(row)
    return result

def pixel_rows(rows,pixel):
    return [r for r in rows if r['pixel']==(pixel[1]<<16)|pixel[0]]

def accumulate(rows,canonical):
    if canonical:rows=sorted(rows,key=lambda r:(r['sample'],r['weight'],*r['rgba']))
    total=[0.]*4;weight=0.
    for r in rows:
        total=[f32(a+b) for a,b in zip(total,r['rgba'])];weight=f32(weight+r['weight'])
    if weight<=0:raise ValueError('Missing accumulated pixel weight')
    return [f32(v/weight) for v in total]

def summarize(records,image):
    width,height=image['dimensions'];output=[]
    for pixel in PIXELS:
        x,y=pixel
        if x>=width or y>=height:raise ValueError('Selected pixel outside image')
        rad=pixel_rows(records['radiance'],pixel);queued=pixel_rows(records['queued'],pixel);shadows=pixel_rows(records['shadow'],pixel)
        if not rad:raise ValueError('Missing radiance contributions')
        weight=math.fsum(r['weight'] for r in rad)
        if weight<=0:raise ValueError('Invalid total weight')
        exact=[math.fsum(r['rgba'][c] for r in rad)/weight for c in range(4)]
        observed=[image['channels'][k][y*width+x] for k in 'RGBA']
        tested=[r for r in shadows if r['cpu']!=-1]
        output.append({'x':x,'y_from_bottom':y,'radiance_count':len(rad),'weight':weight,
                       'normalized_fsum_rgba':exact,'image_rgba':observed,
                       'fsum_image_max_error':max(abs(a-b) for a,b in zip(exact,observed)),
                       'queue_order_float32_rgba':accumulate(rad,False),
                       'canonical_float32_rgba':accumulate(rad,True),
                       'queued_shadow_count':len(queued),
                       'pre_shadow_fsum_rgb':[math.fsum(r['rgb'][c] for r in queued) for c in range(3)],
                       'gpu_shadow_count':len(shadows),'cpu_shadow_checks':len(tested),
                       'shadow_disagreements':sum(r['cpu']!=r['gpu'] for r in tested),
                       'gpu_occluded':sum(bool(r['gpu']) for r in shadows),
                       'disabled_shadowing':any(r['disabled'] for r in shadows)})
    return output

def multiset_comparison(left,right):
    result=[]
    for pixel in PIXELS:
        def counts(records):
            return Counter((r['sample'],r['weight'],*r['rgba']) for r in pixel_rows(records['radiance'],pixel))
        a,b=counts(left),counts(right)
        removed=list((a-b).elements());added=list((b-a).elements())
        result.append({'x':pixel[0],'y_from_bottom':pixel[1],
                       'identical_radiance_multiset':a==b,'removed_count':len(removed),'added_count':len(added),
                       'removed':sorted(removed),'added':sorted(added)})
    return result


def shadow_changes(left,right):
    """Match only unique identical directions; never pair ambiguous path labels."""
    def key(row):return (row['pixel'],row['sample'],row['sequence'],row['depth'],row['type'],*row['direction'])
    def group(records,kind):
        result={}
        for row in records[kind]:result.setdefault(key(row),[]).append(row)
        return result
    a,b=group(left,'shadow'),group(right,'shadow')
    aq,bq=group(left,'queued'),group(right,'queued')
    changes=[];matched=0
    for k in sorted(a.keys() & b.keys()):
        if len(a[k])!=1 or len(b[k])!=1:continue
        matched+=1
        old,new=a[k][0],b[k][0]
        if old['gpu']!=new['gpu'] or old['cpu']!=new['cpu']:
            if len(aq.get(k,[]))!=1 or len(bq.get(k,[]))!=1:raise ValueError('Ambiguous changed shadow origin')
            changes.append({'before':old,'after':new,'queued_before':aq[k][0],'queued_after':bq[k][0]})
    return {'unique_identical_direction_matches':matched,'visibility_changes':changes,
            'scope':'Exact direction and path labels only; unmatched/ambiguous rays are not silently paired'}
