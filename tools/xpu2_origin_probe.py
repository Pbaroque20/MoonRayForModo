"""Probe copied shadow-ray origins on both native backends; images remain unchanged."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import inventory,verify,digest_file
from xpu2.images import read_rgba,compare_rgba
from xpu2 import origins
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def transform(scale=1,translation=(0,0,0)):
    x,y,z=translation
    return 'Mat4(%s,0,0,0,0,%s,0,0,0,0,%s,0,%s,%s,%s,1)'%(scale,scale,scale,x,y,z)

def fixture(original,scale=1,translation=(0,0,0),vertices=None):
    camera=origins.add(translation,[0,0,4*scale])
    text=original+'\nRdlMeshGeometry("/modo/mesh/0") { ["node_xform"] = '+transform(scale,translation)+' }\n'
    text+='PerspectiveCamera("/modo/camera") { ["node_xform"] = '+transform(1,camera)+', ["near"] = '+repr(.001*scale)+' }\n'
    if vertices:
        points=', '.join('Vec3(%s)'%', '.join(format(x,'.9g') for x in p) for p in vertices)
        text+='''local blocker = RdlMeshGeometry("/xpu2/near_blocker") {
 ["node_xform"] = Mat4(1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1),
 ["visible_in_camera"] = false, ["visible_shadow"] = true,
 ["is_subd"] = false, ["smooth_normal"] = false,
 ["vertex_list_0"] = {'''+points+'''},
 ["face_vertex_count"] = {3,3}, ["vertices_by_index"] = {0,1,2,0,2,3}
}
assign(blocker,"","red","origin_probe_blocker")
table.insert(geometries,blocker)
GeometrySet("/modo/geometrySet")(geometries)
Layer("/modo/layer")(assignments)
'''
    return text

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--surface-reference',required=True,type=Path)
    p.add_argument('--cases',help='Comma-separated fixture names; defaults to all')
    p.add_argument('--baseline-origins',type=Path,help='Validated unit/probe/origins.json for a blocker-only rerun')
    a=p.parse_args();build,out,previous=a.build.resolve(),a.output.resolve(),a.surface_reference.resolve()
    out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','cases':[]}
    try:
        manifest=json.loads((build/'build-inputs.json').read_text(encoding='utf-8'))
        if manifest.get('status')!='built' or not manifest.get('origins'):raise ValueError('Origin build required')
        runtime=build/'trace'
        if digest_file(runtime/'librendering_rndr.dll')!=manifest['trace_dll_sha256']:raise ValueError('Diagnostic DLL changed')
        before=inventory(runtime);gpu=gpu_identity()
        if not gpu:raise ValueError('Missing GPU identity')
        report.update(build_manifest_sha256=digest_file(build/'build-inputs.json'),gpu_driver_identity=gpu)
        prior=json.loads((previous/'report.json').read_text(encoding='utf-8'))
        if digest_file(previous/'scene.rdla')!=prior['diagnostic_scene_sha256']:raise ValueError('Changed reference scene')
        original=(previous/'scene.rdla').read_text(encoding='utf-8')
        rays=json.loads((ROOT/'xpu2/selected-rays-20261016.json').read_text(encoding='utf-8'))['rays']
        hit=next(r for r in rays if r['x']==96 and r['y_from_bottom']==77 and r['depth']==0)
        point=prior['state']['P']['at_largest_beauty_difference']
        if (point['x'],point['y_from_bottom'])!=(96,77):raise ValueError('Reference target pixel changed')
        position=point['vectorized']
        cases=[('unit',1,(0,0,0),None),('small',.01,(0,0,0),None),('large',1000,(0,0,0),None),('translated',1,(1e6,1e6,1e6),None)]
        cases.extend(('gap_'+str(gap),1,(0,0,0),origins.blocker(gap,position,hit['cpu']['Ng'])) for gap in (1e-6,1e-5,1e-4))
        baseline_rows=None
        if a.baseline_origins:
            baseline_rows=json.loads(a.baseline_origins.read_text(encoding='utf-8'))
            report['baseline_origins_sha256']=digest_file(a.baseline_origins)
        if a.cases:
            requested=set(a.cases.split(','))
            if not requested <= {c[0] for c in cases}:raise ValueError('Unknown requested case')
            cases=[c for c in cases if c[0] in requested]
        for name,scale,translation,vertices in cases:
            case=out/name;case.mkdir();scene=case/'scene.rdla'
            scene.write_text(fixture(original,scale,translation,vertices),encoding='utf-8')
            record={'name':name,'scale':scale,'translation':translation,'blocker_vertices_camera_space':vertices,'scene_sha256':digest_file(scene),'runs':[]};report['cases'].append(record)
            images={}
            for enabled in (False,True):
                label='probe' if enabled else 'control';folder=case/label;folder.mkdir();env=environment(runtime,folder)
                if enabled:env.update(XPU2_TRACE_RAYS='1',XPU2_PROBE_ORIGINS='1',XPU2_TRACE_FILE=str(folder/'trace.jsonl'))
                command=[str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
                print(name+' '+label,flush=True)
                with (folder/'render.log').open('w',encoding='utf-8') as stream:
                    done=subprocess.run(command,env=env,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
                log=(folder/'render.log').read_text(encoding='utf-8',errors='replace');stats=(folder/'stats.csv').read_text(encoding='utf-8',errors='replace')
                check=successful('xpu',1,done.returncode,log,stats,(folder/'beauty.exr').exists());record['runs'].append(dict(check,label=label))
                if not check['passed']:raise ValueError('Invalid render '+name+' '+label)
                origins.validate_fixture(log,stats,vertices is not None)
                images[label]=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
                if enabled:
                    trace=(folder/'trace.jsonl').read_text(encoding='utf-8')
                    origins.validate_source_hits(trace)
                    record['source_surfaces_validated']=True
                    rows=origins.parse(trace)
                    (folder/'origins.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
                    record['origin_queries']=origins.summarize(rows,vertices)
                    if name=='unit':baseline_rows=rows
                    if vertices:
                        if baseline_rows is None:raise ValueError('Need unit baseline queries to verify blocker activity')
                        record['blocker_activity']=origins.blocker_activity(baseline_rows,rows)
                        if not record['blocker_activity']['newly_blocked_on_both_backends']:raise ValueError('Blocker has not demonstrated real occlusion')
                    record['trace_sha256']=digest_file(folder/'trace.jsonl')
            record['image_control']=compare_rgba(images['control'],images['probe'])
            if record['image_control']['status']!='passed':raise ValueError('Probe altered image '+name)
        verify(runtime,before)
        if gpu_identity()!=gpu:raise ValueError('GPU changed')
        report['runtime_inventory']=before
        report['status']='measured_candidates' # No origin policy is approved by this status.
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='measured_candidates' else 1

if __name__=='__main__':raise SystemExit(main())
