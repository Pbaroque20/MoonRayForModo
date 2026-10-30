"""Summarize diagnostic frame ceilings without upgrading failed image gates."""
import argparse,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2.material_job_metrics import cpu_totals,compare,qualified
from xpu2.images import read_rgba
from xpu2_baseline import environment

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('one','twelve','earlier','reference','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    one=json.loads(a.one.read_text());twelve=json.loads(a.twelve.read_text());earlier=json.loads(a.earlier.read_text())
    if one['status']!='passed' or twelve['status'] not in ('passed','failed') or earlier['status']!='passed':
        raise ValueError('Incomplete measurement matrix')
    if one['threads']!=1 or twelve['threads']!=12 or earlier['threads']!=1:
        raise ValueError('Unexpected thread counts')
    gates=ROOT/'xpu2/MATERIAL_JOB_GATES.json'
    if any(r['protocol']['sha256']!=digest_file(gates) for r in (one,twelve)):
        raise ValueError('Acceptance protocol drift')
    old=json.loads((ROOT/'xpu2/cpu-cost-20261019.json').read_text())
    # Reuse only pre-existing accepted 1-worker textured/many-light frames, with
    # artifact hashes already committed before this experiment. Do not rerender
    # to replace an unfavorable result.
    for f,h in old['artifacts'].items():
        if digest_file(ROOT/f)!=h:
            raise ValueError('Earlier evidence drift '+f)
    report=dict(status='measurements_complete',gpu_material_job_qualified=False,fixtures={},artifacts={},
        protocol_sha256=digest_file(gates),all_one_worker_words_exact=True,
        twelve_worker_image_gate=twelve['status'],
        scope='GPU shading disabled throughout; disjoint sampled CPU material/maps and selected-light costs. Not a GPU speed test.',
        limitations=['Material/maps timing includes native graph and closure construction, not pure texture lookup.',
            'Selected-light work sums light tree, sample/evaluation and all-lobe BSDF/MIS, excluding visibility traces.',
            'Worker elapsed seconds include preemption/internal waits and overlap across threads; they are not removable frame seconds.',
            'Two independent sampling rates are sensitivity checks, not confidence intervals.',
            'Disabled controls contain old experimental hooks; the five-variant new-job speed matrix is still pending.'])
    def artifact(path):
        path=Path(path).resolve();report['artifacts'][str(path.relative_to(ROOT))]=digest_file(path)
    for f in (a.one,a.twelve,a.earlier,gates,ROOT/'xpu2/cpu-cost-20261019.json'):
        artifact(f)
    for threads,rows in ((1,one['runs']+earlier['runs']),(12,twelve['runs'])):
        for name in ('diffuse','layered','textured','many_adaptive'):
            group=[r for r in rows if r['fixture']==name]
            refs=[r for r in group if r['label'].startswith('reference')]
            sampled=[r for r in group if r['rate']]
            offs=[r for r in group if r['label'].startswith('off_')]
            if len(refs)!=(1 if threads==1 else 5) or len(sampled)!=2 or len(offs)!=2:
                raise ValueError('Incomplete or duplicate fixture '+name)
            costs=[cpu_totals(Path(r['artifact_folder'])/'cpu.csv') for r in sampled]
            baseline=None
            for r in group:
                if not r['execution']['passed']:
                    raise ValueError('Invalid native execution')
                folder=Path(r['artifact_folder'])
                for f in ('beauty.exr','render.log','stats.csv','cpu.csv'):
                    if (folder/f).exists():artifact(folder/f)
            if threads==1:
                folder=Path(refs[0]['artifact_folder']);label='verify-'+name+'-reference'
                baseline=read_rgba(a.reference,folder/'beauty.exr',out,label,environment(a.reference,out))
                for r in group:
                    folder=Path(r['artifact_folder'])
                    rgba=read_rgba(a.reference,folder/'beauty.exr',out,'verify-'+name+'-'+r['label'],environment(a.reference,out))
                    if not qualified([compare(baseline,rgba)]):
                        raise ValueError('Prior/new 1-worker image is not bit exact '+name+' '+r['label'])
            def times(rs,k):
                return [r['execution']['renderer_timings_seconds'][k] for r in rs]
            failures=[]
            if threads==12:
                bound=twelve['envelopes'][name]
                for r in group:
                    for channel in 'RGBA':
                        for metric,limit in bound[channel].items():
                            observed=max((c[channel][metric] for c in r.get('comparisons',[])),default=0)
                            if observed>limit:
                                failures.append(dict(label=r['label'],channel=channel,metric=metric,observed=observed,reference_maximum=limit))
            value=dict(original_total_seconds=times(refs,'Total time'),original_mcrt_seconds=times(refs,'Mcrt time'),
                candidate_off_total_seconds=times(offs,'Total time'),candidate_off_mcrt_seconds=times(offs,'Mcrt time'),
                sampled_mcrt_seconds=times(sampled,'Mcrt time'),
                material_maps_worker_seconds=[c['material_maps_worker_seconds'] for c in costs],
                selected_lighting_worker_seconds=[c['selected_lighting_worker_seconds'] for c in costs],
                material_points=[c['stages']['material_construct_maps']['lanes'] for c in costs],
                stage_estimates=costs,image_gate_failures=failures)
            value['candidate_off_mcrt_overhead_fraction']=statistics.mean(value['candidate_off_mcrt_seconds'])/statistics.median(value['original_mcrt_seconds'])-1
            report['fixtures'][name+'-'+str(threads)]=value
    report['twelve_worker_envelopes']=twelve['envelopes']
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    for k,v in report['fixtures'].items():
        print(k,'original total',round(statistics.median(v['original_total_seconds']),3),'material worker sec',[round(x,3) for x in v['material_maps_worker_seconds']], 'light worker sec',[round(x,3) for x in v['selected_lighting_worker_seconds']], 'image gate failures',len(v['image_gate_failures']))
if __name__=='__main__':main()
