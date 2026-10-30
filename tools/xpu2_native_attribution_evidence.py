"""Collect paired render-stage attribution without treating differences as additive costs."""
import argparse,csv,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file
CASES=('reference','disabled','native_chunk','capacity0','control')
def stages(path):
    active=False;values={}
    with path.open(newline='') as f:
        for row in csv.reader(f):
            if row and 'MCRT Time Breakdown' in row[0]:active=True
            elif active and row and row[0]=='Totals':break
            elif active and len(row)==3 and row[0]!='Name':values[row[0]]=float(row[1])
    if 'Integration' not in values:raise ValueError('Missing Integration stage')
    return values

def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    file=a.report.resolve();r=json.loads(file.read_text());folder=file.parent
    if r['status']!='passed' or not r['exact_rgba_required'] or r['image_mismatches']:raise ValueError('Exact-image qualification required')
    if r['threads']!=1:raise ValueError('Single-worker attribution required')
    result={'status':'passed','report':str(file.relative_to(ROOT)),'report_sha256':digest_file(file),'threads':r['threads'],'gpu':r['gpu'],'timings':r['summary'],'runs':[],'stage_medians':{},'paired_comparisons':{}}
    samples={};seen=set()
    for row in r['runs']:
        label,n=row['label'],row['round'];key=(n,label)
        if key in seen or label not in CASES:raise ValueError('Duplicate or unexpected run')
        seen.add(key)
        if row['comparison']['exactly_different_pixels'] or row['comparison']['status']!='passed':raise ValueError('Image mismatch')
        if row['activity_before'] or row['activity_after']:raise ValueError('Competing render activity')
        expect=32 if label in ('reference','disabled') else 64
        if row['native_chunk_rays']!=expect:raise ValueError('Incorrect chunk configuration')
        if label=='capacity0' and (row['flight']['submitted'] or row['early']['gpu_lanes'] or not row['early']['fallback_lanes']):raise ValueError('Fallback was not isolated')
        if label=='control' and not row['early']['gpu_lanes']:raise ValueError('GPU control not exercised')
        stats=folder/(str(n)+'-'+label)/'stats.csv';s=stages(stats)
        samples[key]={'mcrt':row['execution']['renderer_timings_seconds']['Mcrt time'],'integration':s['Integration']}
        result['runs'].append({'round':n,'label':label,'stats_sha256':digest_file(stats),'stats':s,'comparison':row['comparison'],**samples[key]})
    rounds=sorted({n for n,label in seen if n>0})
    if len(rounds)<3 or seen!={(n,c) for n in [0,*rounds] for c in CASES}:raise ValueError('Incomplete rotated comparison')
    result['exact_images']=len(seen)
    for label in CASES:
        rows=[x for x in result['runs'] if x['label']==label and x['round']>0]
        result['stage_medians'][label]={k:statistics.median(x['stats'][k] for x in rows) for k in rows[0]['stats']}
    for low,high in [('reference','disabled'),('disabled','native_chunk'),('reference','native_chunk'),('native_chunk','capacity0'),('capacity0','control'),('native_chunk','control')]:
        key=high+'_minus_'+low
        result['paired_comparisons'][key]={field:{'per_round_seconds':[samples[n,high][field]-samples[n,low][field] for n in rounds],'median_seconds':statistics.median(samples[n,high][field]-samples[n,low][field] for n in rounds)} for field in ('mcrt','integration')}
    result['limitations']=['One native worker and one reflection/transmission fixture; not production scaling.','No runtime change: same qualified timeline-v3 binary, tracing disabled.','Disabled32 versus original includes compiled adapter scaffolding and prior native patch differences.','Capacity-zero retains preparation/replay and adds CPU fallback; it is not pure dispatch or transfer cost.','Differences are configuration comparisons, not additive nonoverlapping phase costs.','Process checks before/after renders cannot exclude brief intervening activity.']
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'timings':result['timings'],'paired_comparisons':result['paired_comparisons'],'exact_images':result['exact_images']},indent=2))
if __name__=='__main__':main()
