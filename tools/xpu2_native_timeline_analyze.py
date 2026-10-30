import argparse,csv,json,statistics
from pathlib import Path
NAMES={0:'native_window_prepare',3:'native_cpu_lobes',4:'native_resume',10:'native_condition_wait',11:'host_dispatch_inclusive',12:'worker_pack',13:'host_enqueue_calls',14:'worker_retire',15:'worker_empty_wait',16:'completion_observed',20:'clock_calibration',21:'gpu_upload_interval',22:'gpu_kernel_interval',23:'gpu_download_interval',25:'clock_calibration_end'}
def merge(xs):
    out=[]
    for a,b in sorted(xs):
        if b<a:raise ValueError('Reversed interval')
        if not out or a>out[-1][1]:out.append([a,b])
        else:out[-1][1]=max(out[-1][1],b)
    return out
def duration(xs):return sum(b-a for a,b in merge(xs))
def overlap(a,b):
    a,b=merge(a),merge(b);i=j=0;total=0
    while i<len(a) and j<len(b):
        total+=max(0,min(a[i][1],b[j][1])-max(a[i][0],b[j][0]))
        if a[i][1]<b[j][1]:i+=1
        else:j+=1
    return total
def analyze(path,allow_empty=False):
    with path.open(newline='') as stream:
        rows=[{k:int(v) for k,v in r.items()} for r in csv.DictReader(stream)]
    footer=[r for r in rows if r['phase']==99]
    if len(footer)!=1 or footer[0]['id']:raise ValueError('Missing footer or dropped trace events')
    rows=[r for r in rows if r['phase']!=99];groups={}
    for r in rows:
        if r['phase'] not in NAMES or r['end_ns']<r['begin_ns']:raise ValueError('Invalid trace record')
        groups.setdefault(r['phase'],[]).append(r)
    # Map CUDA offsets using start/end brackets. Single-anchor host correlation
    # drifts by milliseconds on this device; do not interpret it as wake latency.
    calibration={}
    if groups.get(21):
        starts,ends=groups.get(20,[]),groups.get(25,[])
        if len(starts)!=1 or len(ends)!=1:raise ValueError('Two clock calibration brackets required')
        first,last=starts[0],ends[0]
        a=(first['begin_ns']+first['end_ns'])/2
        b=(last['begin_ns']+last['end_ns'])/2
        if last['id']<=a:raise ValueError('Invalid GPU calibration span')
        scale=(b-a)/(last['id']-a)
        calibration={'gpu_to_host_scale':scale,'end_uncorrected_drift_us':(b-last['id'])/1000,
                     'end_half_bracket_us':(last['end_ns']-last['begin_ns'])/2000,
                     'alignment':'Linear start/end bracket mapping; not a hardware profiler correlation guarantee.'}
        for key in (21,22,23):
            for row in groups.get(key,[]):
                row['begin_ns']=round(a+(row['begin_ns']-a)*scale)
                row['end_ns']=round(a+(row['end_ns']-a)*scale)
    spans=lambda key:[(r['begin_ns'],r['end_ns']) for r in groups.get(key,[])]
    report={'status':'passed','frame_scope_seconds':footer[0]['end_ns']/1e9,'events':len(rows),'phases':{},'scope':'Single native worker, shading bridge only. Event intervals include scheduling delays. Host/GPU alignment approximate; native OptiX activity not captured.'}
    report['clock_calibration']=calibration
    for key,rs in groups.items():
        ds=[r['end_ns']-r['begin_ns'] for r in rs]
        report['phases'][NAMES[key]]={'count':len(rs),'sum_seconds':sum(ds)/1e9,'union_seconds':duration(spans(key))/1e9,'median_us':statistics.median(ds)/1000,'max_ms':max(ds)/1e6}
    gpu=spans(21)+spans(22)+spans(23);cpu=spans(0)+spans(3)+spans(4);wait=spans(10)
    report['native_instrumented_union_seconds']=duration(cpu)/1e9
    report['gpu_shading_interval_union_seconds']=duration(gpu)/1e9
    report['native_wait_union_seconds']=duration(wait)/1e9
    report['approx_native_wait_during_shading_seconds']=overlap(wait,gpu)/1e9
    report['approx_native_instrumented_during_shading_seconds']=overlap(cpu,gpu)/1e9
    report['kernel_interval_overlap_between_slots_seconds']=(sum(duration([(r['begin_ns'],r['end_ns']) for r in groups.get(22,[]) if r['track']==t]) for t in (1,2,3,4))-duration(spans(22)))/1e9
    if not gpu:
        if not allow_empty:raise ValueError('No GPU work recorded')
        return report
    # Exactly one triple per completed batch; incomplete/failed submissions may lack it.
    batches={}
    for key in (21,22,23):
        for r in groups[key]:
            item=batches.setdefault(r['id'],{})
            if key in item:raise ValueError('Duplicate GPU batch phase')
            item[key]=r
    for item in batches.values():
        if set(item)!={21,22,23}:raise ValueError('Incomplete successful batch trace')
        if item[21]['end_ns']!=item[22]['begin_ns'] or item[22]['end_ns']!=item[23]['begin_ns']:raise ValueError('Discontinuous GPU batch')
    cal=groups.get(20,[])
    if len(cal)!=1:raise ValueError('Expected single GPU clock calibration')
    uncertainty=max((cal[0]['end_ns']-cal[0]['begin_ns'])/2,calibration['end_half_bracket_us']*1000)
    report['clock_alignment_half_bracket_us']=uncertainty/1000
    observed={r['id']:r for r in groups.get(16,[])}
    delays=[observed[k]['begin_ns']-v[23]['end_ns'] for k,v in batches.items() if k in observed]
    if len(delays)!=len(batches):raise ValueError('Missing completion observations')
    report['approx_completion_detection']={'count':len(delays),'median_us':statistics.median(delays)/1000,'max_us':max(delays)/1000,'minimum_us':min(delays)/1000,'negative_beyond_calibration':sum(x < -uncertainty-10000 for x in delays)}
    lo,hi=min(a for a,b in gpu),max(b for a,b in gpu)
    report['gpu_shading_envelope_seconds']=(hi-lo)/1e9
    report['gpu_shading_envelope_uncovered_seconds']=(hi-lo-duration(gpu))/1e9
    report['uncovered_does_not_mean_device_idle']=True
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('trace',type=Path);p.add_argument('--allow-empty',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze(a.trace,a.allow_empty);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
