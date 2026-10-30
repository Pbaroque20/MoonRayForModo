"""Fixture construction and copied-ray origin analysis; no production bias policy."""
from collections import defaultdict
import json
import math
from .contributions import restore, f32

POLICIES={0:'unchanged',1:'normal_sign_1_ulp',2:'normal_sign_2_ulp',3:'normal_sign_4_ulp',4:'normal_sign_8_ulp',5:'normal_4eps_max_coordinate_plus_ulp'}
def add(a,b):return [x+y for x,y in zip(a,b)]
def sub(a,b):return [x-y for x,y in zip(a,b)]
def mul(a,s):return [x*s for x in a]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def unit(a):return mul(a,1/math.sqrt(dot(a,a)))
def blocker(gap,position,normal):
    n=unit(normal);u=unit(cross(n,[0,1,0]));v=cross(n,u)
    center=add(position,mul(n,gap))
    return [[f32(c) for c in add(add(center,mul(u,x*.02)),mul(v,y*.02))] for x,y in [(-1,-1),(1,-1),(1,1),(-1,1)]]

def plane_hit(origin,direction,vertices):
    # Actual float32 fixture vertices, double-precision triangle arithmetic.
    # Geometric evidence, not a replacement for either native backend.
    hits=[]
    for i,j,k in ((0,1,2),(0,2,3)):
        a,b,c=(vertices[q] for q in (i,j,k));e1=sub(b,a);e2=sub(c,a)
        h=cross(direction,e2);det=dot(e1,h)
        if det==0:continue
        inv=1/det;s=sub(origin,a);u=dot(s,h)*inv;q=cross(s,e1);v=dot(direction,q)*inv
        if u>=0 and v>=0 and u+v<=1:hits.append(dot(e2,q)*inv)
    return min(hits) if hits else None

def parse(log):
    rows=[]
    for line in log.splitlines():
        if line.startswith('XPU2_ORIGIN '):
            row=restore(json.loads(line[len('XPU2_ORIGIN '):]))
            if row['policy'] not in POLICIES or row['sample']!=0:raise ValueError('Invalid origin probe identity')
            if any(row[k] not in (0,1) for k in ('cpu','gpu','original_gpu')):raise ValueError('Invalid visibility result')
            rows.append(row)
    return rows

def summarize(rows,vertices=None):
    if not rows:raise ValueError('Missing native origin queries')
    groups=defaultdict(dict)
    for row in rows:
        # source_index is local to a GPU batch, not a global ray identifier.
        key=(row['pixel'],row['sample'],*row['direction'],row['source_index'])
        if row['policy'] in groups[key]:raise ValueError('Ambiguous duplicate origin variant')
        groups[key][row['policy']]=row
    result={'source_rays':len(groups),'policies':{name:{'queries':0,'cpu_gpu_disagreements':0,'blocked_to_clear':0,'clear_to_blocked':0,'skipped_blocker':0} for name in POLICIES.values()},'blocker_failures':[]}
    for group in groups.values():
        if set(group)!=set(POLICIES):raise ValueError('Incomplete origin policy set')
        baseline=group[0]
        if baseline['gpu']!=baseline['original_gpu']:raise ValueError('Diagnostic query changed baseline GPU visibility')
        original_t=plane_hit(baseline['origin'],baseline['direction'],vertices) if vertices else None
        for policy,row in group.items():
            counts=result['policies'][POLICIES[policy]];counts['queries']+=1
            counts['cpu_gpu_disagreements']+=row['cpu']!=row['gpu']
            counts['blocked_to_clear']+=bool(baseline['gpu'] and not row['gpu'])
            counts['clear_to_blocked']+=bool(not baseline['gpu'] and row['gpu'])
            if vertices and original_t is not None and original_t>baseline['near'] and baseline['gpu'] and not row['gpu']:
                candidate_t=plane_hit(row['origin'],row['direction'],vertices)
                if candidate_t is None or candidate_t<=row['near']:
                    counts['skipped_blocker']+=1
                    result['blocker_failures'].append({'policy':POLICIES[policy],'baseline':baseline,'candidate':row,'original_triangle_t':original_t,'candidate_triangle_t':candidate_t})
    return result

def validate_fixture(log,stats,has_blocker):
    import csv
    import io
    if 'No Attribute named' in log:raise ValueError('Unknown scene attribute; invalid fixture')
    if has_blocker:
        rows=[row for row in csv.reader(io.StringIO(stats)) if row and row[0]=='/xpu2/near_blocker' and len(row)==6]
        if len(rows)!=1 or rows[0][1:3]!=['2','4']:raise ValueError('Blocker must have two faces and four vertices')

def blocker_activity(baseline,actual):
    def grouped(rows):
        result=defaultdict(list)
        for row in rows:
            key=(row['pixel'],row['sample'],row['policy'],*row['origin'],*row['direction'],row['near'])
            result[key].append(row)
        return result
    before,after=grouped(baseline),grouped(actual);hits=[];matched=0
    for key in before.keys() & after.keys():
        if len(before[key])!=1 or len(after[key])!=1:continue
        matched+=1;a,b=before[key][0],after[key][0]
        if a['cpu']==a['gpu']==0 and b['cpu']==b['gpu']==1:hits.append({'without_blocker':a,'with_blocker':b})
    return {'identical_input_matches':matched,'newly_blocked_on_both_backends':len(hits),'examples':hits[:3]}

def validate_source_hits(log):
    rows=[restore(json.loads(line[len('XPU2_RAY '):])) for line in log.splitlines() if line.startswith('XPU2_RAY ')]
    primary=[r for r in rows if r['depth']==0 and r['sample']==0]
    if len(primary)!=2 or {r['pixel'] for r in primary}!={(77<<16)|96,(96<<16)|132}:
        raise ValueError('Missing selected primary surfaces')
    if any(r['gpu']['geom']==0xffffffff or dot(r['gpu']['Ng'],r['gpu']['Ng'])<=0 for r in primary):
        raise ValueError('Invalid geometric normal for origin probe')
