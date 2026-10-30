"""Compare scheduling policies with synthetic work; NOT a rendering benchmark."""
import argparse
import hashlib
import heapq
import json
from pathlib import Path
import random
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.local_tile_schedule import Batch, TileQueues
from xpu2.morton_schedule import morton
from xpu2.reference import digest_file


def workload(name):
    # Fixed checkpoint. Cost units are invented inputs, never hardware timings.
    rng=random.Random(9481)
    tiles=sorted(((x,y) for y in range(16) for x in range(16)),key=lambda p:morton(*p))
    jobs=[];costs={}
    for x,y in tiles:
        for sample in range(8):
            key=(1,y*16+x,sample)
            gpu=name!='cpu_only' and (name!='mixed' or (x+y)%4!=0)
            jobs.append(Batch(key,(x,y),frozenset({'cpu','gpu'} if gpu else {'cpu'})))
            base=rng.randrange(1,40) if name in ('irregular','irregular_locality') else 1
            if name=='hotspot' and x<4 and y<4:base=80
            costs[key]={'cpu':base*4.,'gpu':base*1.}
    return jobs,costs


def simulate(name,policy):
    jobs,costs=workload(name);q=TileQueues(jobs,policy.removesuffix('_reserved'),prefer_cpu_only=policy.endswith('_reserved'))
    workers=[('cpu0','cpu'),('cpu1','cpu'),('gpu0','gpu')]
    events=[];counts={w:0 for w,_ in workers};busy={w:0. for w,_ in workers}
    previous={};dispatch_ns=0;switches=0;serial=0;end=0.
    def launch(worker,device,now):
        nonlocal dispatch_ns,switches,serial
        begin=time.perf_counter_ns();lease=q.claim(worker,device);dispatch_ns+=time.perf_counter_ns()-begin
        if lease is None:return
        changed=worker in previous and previous[worker]!=lease.batch.tile
        switches+=changed;previous[worker]=lease.batch.tile
        cost=costs[lease.batch.key][device]+(8. if name in ('locality','irregular_locality') and changed else 0.)
        busy[worker]+=cost;counts[worker]+=1;serial+=1
        heapq.heappush(events,(now+cost,serial,worker,device,lease))
    for w,d in workers:launch(w,d,0.)
    while events:
        end,_,w,d,lease=heapq.heappop(events)
        key=lease.batch.key
        assert q.complete(lease,(float(key[1]),float(key[2]),1.))
        launch(w,d,end)
    result=q.checkpoint()
    assert result is not None,'Missing or blocked work'
    return {'policy':policy,'workload':name,'batches':len(jobs),
            'synthetic_completion_cost_units':end,'worker_batches':counts,
            'synthetic_worker_busy_fraction':{w:v/end for w,v in busy.items()},
            'tile_switches':switches,'candidate_checks':q.candidate_checks,
            'tile_probes':q.tile_probes,'local_claims':q.local_claims,
            'python_claim_nanoseconds':dispatch_ns,
            'keyed_payload_sha256':hashlib.sha256(repr(result).encode()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),ROOT/'xpu2/local_tile_schedule.py',ROOT/'tests/test_xpu2_local_tile_schedule.py']
    hashes={str(f.relative_to(ROOT)):digest_file(f) for f in files}
    rows=[]
    for name in ('uniform','mixed','irregular','hotspot','locality','irregular_locality','cpu_only'):
        pair=[simulate(name,policy) for policy in ('shared','neighbor','shared_reserved','neighbor_reserved')]
        assert all(row['keyed_payload_sha256']==pair[0]['keyed_payload_sha256'] for row in pair)
        rows.extend(pair)
    assert all(digest_file(ROOT/n)==h for n,h in hashes.items())
    report={'status':'passed','native_render_test':False,'gpu_execution_test':False,
            'scope':'Coordinator model, invented work costs, Python claim overhead; no rendering speed claim',
            'source_hashes':hashes,'runs':rows}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('passed: seven four-policy scheduler-model comparisons; no native/GPU render benchmark')

if __name__=='__main__':main()
