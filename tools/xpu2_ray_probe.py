"""Compare copied control/diagnostic runtimes without installing either.

Full-frame XPU, one thread. Only selected GPU surface rays are cross-checked;
shadow rays, CPU-routed tails, BSDF evaluation and film contributions are not traced.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import inventory, verify, digest_file
from xpu2.images import read_rgba, compare_rgba
from xpu2 import contributions
from xpu2_baseline import environment
from xpu2_repeatability import successful, gpu_identity


def parse_rays(log):
    rows=[]
    for line in log.splitlines():
        if not line.startswith('XPU2_RAY '):continue
        row=json.loads(line[len('XPU2_RAY '):])
        def finite(value):
            if isinstance(value,dict):return all(finite(v) for v in value.values())
            if isinstance(value,list):return all(finite(v) for v in value)
            return isinstance(value,(int,float)) and math.isfinite(value)
        if not finite(row):raise ValueError('Invalid ray record')
        # %.9g round-trips float32, but parsing into float64 alone preserves
        # decimal formatting noise. Recover the original float32 values first.
        def restore(value):
            if isinstance(value,dict):return {k:restore(v) for k,v in value.items()}
            if isinstance(value,list):return [restore(v) for v in value]
            if isinstance(value,float):return struct.unpack('<f',struct.pack('<f',value))[0]
            return value
        row=restore(row)
        row['x']=row['pixel'] & 0xffff;row['y_from_bottom']=row['pixel'] >> 16
        if (row['x'],row['y_from_bottom']) not in ((96,77),(132,96)):
            raise ValueError('Unexpected selected pixel')
        if row['batch']<=1024:raise ValueError('Unexpected GPU routing')
        rows.append(row)
    return rows


def summarize(rows):
    result={'rays':len(rows),'hit_miss_mismatches':0,'primitive_mismatches':0,
            'different_hit_attributes':0,'max_t_error':0.,'max_uv_error':0.,'max_Ng_error':0.,
            'depths':sorted(set(r['depth'] for r in rows))}
    for row in rows:
        a,b=row['cpu'],row['gpu']
        hit_a,hit_b=a['geom']!=0xffffffff,b['geom']!=0xffffffff
        if hit_a!=hit_b:result['hit_miss_mismatches']+=1;continue
        if not hit_a:continue
        if any(a[k]!=b[k] for k in ('geom','prim','inst')):result['primitive_mismatches']+=1;continue
        errors={'t':abs(a['t']-b['t']),
                'uv':max(abs(x-y) for x,y in zip(a['uv'],b['uv'])),
                'Ng':max(abs(x-y) for x,y in zip(a['Ng'],b['Ng']))}
        if any(errors.values()):result['different_hit_attributes']+=1
        for name,value in errors.items():result['max_'+name+'_error']=max(result['max_'+name+'_error'],value)
    return result


def replay_result(gpu, replay, cpu, rows):
    if gpu['dimensions']!=replay['dimensions'] or gpu['dimensions']!=cpu['dimensions']:
        raise ValueError('Replay dimensions differ')
    if gpu['metadata']!=replay['metadata'] or gpu['metadata']!=cpu['metadata']:
        raise ValueError('Replay metadata differs')
    width,height=gpu['dimensions']
    selected={(96,77),(132,96)}
    targets=[];outside=0
    for y in range(height):
        for x in range(width):
            i=y*width+x
            a,b,c=([image['channels'][key][i] for key in 'RGBA'] for image in (gpu,replay,cpu))
            if not all(math.isfinite(v) for rgba in (a,b,c) for v in rgba):raise ValueError('Nonfinite replay pixel')
            if (x,y) in selected:
                targets.append({'x':x,'y_from_bottom':y,'original_xpu':a,'replayed_primary':b,'vectorized':c,
                                'max_error_before':max(abs(v-w) for v,w in zip(a,c)),
                                'max_error_after':max(abs(v-w) for v,w in zip(b,c))})
            elif a!=b:outside+=1
    applied=[row for row in rows if row.get('replayed_primary')]
    if len(applied)!=2 or {(r['x'],r['y_from_bottom']) for r in applied}!=selected or any(row['depth']!=0 for row in applied):raise ValueError('Unexpected replay coverage')
    return {'selected_pixels':targets,'changed_pixels_outside_selection':outside,
            'replayed_primary_hits':len(applied),'scope':'Two selected primary rays only; not a production correction'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--contributions',action='store_true',help='Trace shadow/radiance queues and add vector controls')
    p.add_argument('--replay-primary',action='store_true',help='Also run the explicit selected-primary-hit substitution experiment')
    p.add_argument('--surface-reference',type=Path,required=True,help='Previously measured primary-state folder')
    a=p.parse_args();build,out,previous=a.build.resolve(),a.output.resolve(),a.surface_reference.resolve()
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':__doc__,'runs':[]}
    try:
        provenance=json.loads((build/'build-inputs.json').read_text(encoding='utf-8'))
        if provenance.get('status')!='built':raise ValueError('Incomplete build')
        if a.contributions and not provenance.get('contributions'):raise ValueError('Build lacks contribution probes')
        report['build_manifest_sha256']=digest_file(build/'build-inputs.json')
        for kind in ('control','trace'):
            if digest_file(build/kind/'librendering_rndr.dll')!=provenance[kind+'_dll_sha256']:
                raise ValueError('Diagnostic DLL changed since build: '+kind)
        hardware=gpu_identity()
        if not hardware:raise ValueError('Cannot identify GPU/driver')
        report['gpu_driver_identity']=hardware
        before={name:inventory(build/name) for name in ('control','trace')}
        scene=out/'scene.rdla';scene.write_bytes((previous/'scene.rdla').read_bytes())
        old=json.loads((previous/'report.json').read_text(encoding='utf-8'))
        if digest_file(scene)!=old['diagnostic_scene_sha256']:raise ValueError('Reference scene changed')
        report['scene_sha256']=digest_file(scene)
        images={};traces={};contribution_records={}
        cases=[('control','control',False),('trace-off','trace',False),('trace-on','trace',True),('trace-repeat','trace',True)]
        if a.replay_primary:cases.append(('replay-primary','trace',True))
        if a.contributions:cases.extend([('vector-off','trace',False),('vector-on','trace',True)])
        for name,kind,enabled in cases:
            mode='vectorized' if name.startswith('vector-') else 'xpu'
            folder=out/name;folder.mkdir();runtime=build/kind
            env=environment(runtime,folder)
            if enabled:
                env['XPU2_TRACE_RAYS']='1'
                env['XPU2_TRACE_FILE']=str(folder/'trace.jsonl')
            if enabled and a.contributions:env['XPU2_TRACE_CONTRIBUTIONS']='1'
            if name=='replay-primary':env['XPU2_REPLAY_CPU_PRIMARY']='1'
            command=[str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode',mode,'-threads','1','-info','-stats',str(folder/'stats.csv')]
            print('Rendering '+name,flush=True)
            with (folder/'render.log').open('w',encoding='utf-8') as stream:
                done=subprocess.run(command,cwd=folder,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            log=(folder/'render.log').read_text(encoding='utf-8',errors='replace')
            stats=(folder/'stats.csv').read_text(encoding='utf-8',errors='replace')
            check=successful(mode,1,done.returncode,log,stats,(folder/'beauty.exr').exists())
            report['runs'].append(dict(check,name=name))
            if not check['passed']:raise ValueError('Invalid run '+name)
            images[name]=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
            diagnostic_log=(folder/'trace.jsonl').read_text(encoding='utf-8') if (folder/'trace.jsonl').exists() else ''
            rows=parse_rays(diagnostic_log)
            if bool(rows)!=(enabled and mode=='xpu'):raise ValueError('Trace enable/disable failed')
            if enabled and mode=='xpu':
                primary=[row for row in rows if row['depth']==0]
                if len(primary)!=2 or {(r['x'],r['y_from_bottom'],r['sample']) for r in primary}!={(96,77,0),(132,96,0)}:
                    raise ValueError('Incomplete selected-primary trace')
                traces[name]=rows
                (folder/'rays.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
            if a.contributions:
                records=contributions.parse(diagnostic_log)
                if bool(records['radiance'])!=enabled:raise ValueError('Contribution tracing enable/disable failed')
                if enabled:
                    contribution_records[name]=records
                    (folder/'contributions.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        env=environment(build/'control',out)
        original=read_rgba(build/'control',previous/'xpu/beauty.exr',out,'pinned',env)
        report['comparisons']={
            'pinned_to_control':compare_rgba(original,images['control']),
            'control_to_trace_off':compare_rgba(images['control'],images['trace-off']),
            'trace_off_to_on':compare_rgba(images['trace-off'],images['trace-on']),
            'trace_repeat':compare_rgba(images['trace-on'],images['trace-repeat'])}
        report['ray_records_identical']=traces['trace-on']==traces['trace-repeat']
        report['intersection_summary']=summarize(traces['trace-on'])
        if a.replay_primary:
            cpu=read_rgba(build/'control',previous/'vectorized/beauty.exr',out,'cpu-reference',env)
            report['replay']=replay_result(images['trace-on'],images['replay-primary'],cpu,traces['replay-primary'])
        if a.contributions:
            cpu=read_rgba(build/'control',previous/'vectorized/beauty.exr',out,'cpu-control',env)
            report['comparisons']['vector_trace_off_to_on']=compare_rgba(images['vector-off'],images['vector-on'])
            report['comparisons']['pinned_vector_to_control']=compare_rgba(cpu,images['vector-off'])
            report['contributions']={name:contributions.summarize(records,images[name]) for name,records in contribution_records.items()}
            report['contribution_records_identical']=contribution_records['trace-on']==contribution_records['trace-repeat']
            pairs=[('vector-on','trace-on'),('trace-on','trace-repeat')]
            if a.replay_primary:pairs.extend([('vector-on','replay-primary'),('trace-on','replay-primary')])
            report['contribution_comparisons']={left+'__'+right:contributions.multiset_comparison(contribution_records[left],contribution_records[right]) for left,right in pairs}
            if a.replay_primary:report['matched_shadow_changes']=contributions.shadow_changes(contribution_records['trace-on'],contribution_records['replay-primary'])
            report['scope']='Selected surface rays, pre-shadow lighting, GPU shadow decisions and queued radiance; no complete BSDF/texture or branch-identity trace'
        for kind,held in before.items():verify(build/kind,held)
        report['runtime_inventory']=before
        if gpu_identity()!=hardware:raise ValueError('GPU/driver changed during experiment')
        controls=all(v['status']=='passed' for k,v in report['comparisons'].items() if k!='pinned_to_control')
        report['status']='valid_diagnostic' if controls and report['ray_records_identical'] and report.get('contribution_records_identical',True) else 'diagnostic_changed_results'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='valid_diagnostic' else 1

if __name__=='__main__':raise SystemExit(main())
