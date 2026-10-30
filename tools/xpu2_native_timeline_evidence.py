"""Collect exact-image, recovery, clock-corrected trace and paired timing evidence."""
import csv,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_native_timeline_analyze import analyze

def integration(path):
    active=False
    with path.open(newline='') as f:
        for row in csv.reader(f):
            if row and 'MCRT Time Breakdown' in row[0]:active=True
            elif active and row and row[0]=='Integration':return float(row[1])
    raise ValueError('Missing native integration stats')
def main():
    result={'status':'incomplete','scope':'Single native worker on reflection/transmission fixture. Diagnostics only; no performance optimization or general material claim.','reports':{},'traces':{}}
    reports={}
    for label in ('controls','timing','cancel'):
        folder=ROOT/'test-results'/('xpu2-timeline-v3-'+label);file=folder/'report.json';r=json.loads(file.read_text())
        if r['status']!='passed':raise ValueError('Failed report '+label)
        reports[label]=r;result['reports'][label]={'path':str(file.relative_to(ROOT)),'sha256':digest_file(file),'runs':len(r['runs'])}
        for trace in folder.glob('*/timeline.csv'):
            value=analyze(trace,allow_empty=trace.parent.name in ('0-missing','0-upload_failure'))
            value['sha256']=digest_file(trace)
            (trace.parent/'analysis.json').write_text(json.dumps(value,indent=2)+'\n')
            result['traces'][str(trace.relative_to(ROOT))]=value
    r=reports['timing'];result['timings']=r['summary']
    stages={}
    for label in ('reference','previous','control','profile_control'):
        rows=[x for x in r['runs'] if x['label']==label and x['round']>0]
        values=[integration(ROOT/'test-results/xpu2-timeline-v3-timing'/f"{x['round']}-{label}"/'stats.csv') for x in rows]
        stages[label]={'integration_median_seconds':statistics.median(values),'integration_seconds':values}
    result['native_stage_timings']=stages
    result['tracing_render_overhead_percent']=100*(r['summary']['profile_control']['render_median']/r['summary']['control']['render_median']-1)
    result['untraced_integration_delta_seconds']=stages['control']['integration_median_seconds']-stages['reference']['integration_median_seconds']
    result['untraced_render_delta_seconds']=r['summary']['control']['render_median']-r['summary']['reference']['render_median']
    result['limitations']=['CUDA event intervals include scheduling delays; not pure copy-engine or ALU occupancy.','Host/GPU correspondence uses start/end calibration brackets; interior correlation is approximate.','The shading bridge timeline omits native OptiX traversal and uninstrumented CPU paths.','Empty shading queue is not proof the entire GPU is idle.','Nested/overlapping stage totals must not be added.','Original uses native 32-ray chunks; XPU2 uses 64. Stage delta does not isolate chunk-size effects.','Persistent trace file contains final replacement frame; cancellation correctness comes from separate lifetime counters.']
    result['status']='passed'
    out=ROOT/'xpu2/native-timeline-20261018.json';out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('traces','reports')},indent=2))
if __name__=='__main__':main()
