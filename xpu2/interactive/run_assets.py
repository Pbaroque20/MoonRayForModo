"""Private real-RDL asset rewrite and one-worker reference image validation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from native_build import build
from asset_snapshot import freeze,verify,native
from reference_runtime import sha,verify as verify_runtime
from fallback import environment
from run_m0 import standalone,image,write_json
from xpu2.material_job_metrics import compare
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','runtime','scene','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();source,runtime,scene,out=[getattr(a,n).resolve() for n in ('source','runtime','scene','output')]
    if out.is_relative_to(source) or out.is_relative_to(runtime):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'flagged asset snapshots and reference renders; no native shading',
            'gates':{'image':'exact float32 RGBA at one thread','source_texture':'moved away before packaged render','missing_or_modified_assets':'reject'},
            'limits':['DSO-internal/unflagged dependencies not automatically discovered','No mipmap or image-filter qualification','No production installation']}
    write_json(out/'report.json',report)
    try:
        lock=json.loads((HERE/'reference-lock.json').read_text());verify_runtime(runtime,lock)
        files=[HERE/n for n in ('asset_scene.cc','asset_snapshot.py','native_build.py','run_assets.py','fallback_service.py')]
        held={str(f):sha(f) for f in files};report['source_hashes']=held
        helper,report['build']=build(source,HERE/'asset_scene.cc',out/'build')
        texture=out/'color.tx'
        r=subprocess.run([str(runtime/'oiiotool.exe'),'--pattern','constant:color=0.15,0.65,0.35','64x64','3','--otex',str(texture)],
                         env=environment(runtime,out),cwd=out,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'texture.log').write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError('Synthetic TX fixture failed')
        fixture=out/'textured.rdlb';scan=native(helper,runtime,out,'fixture',scene,texture,fixture)
        report['discovery']=scan
        if not any(x['value']==str(texture) for x in scan['references']):raise ValueError('ImageMap texture undiscovered')
        report['original']=standalone(runtime,fixture,out/'original',1)
        original=image(runtime,out/'original')
        manifest=freeze(fixture,helper,runtime,out/'package',out)
        # Owned test asset only. Keep a renamed copy as evidence; no user file is changed.
        texture.rename(out/'source-retired.tx')
        packed=verify(manifest)
        report['packaged']=standalone(runtime,packed,out/'packaged',1)
        converted=image(runtime,out/'packaged');report['comparison']=compare(original,converted)
        if any(report['comparison'][c]['different_words'] for c in 'RGBA'):raise ValueError('Packaged image differs')
        # Test a native missing input, and ensure no ready manifest is admitted.
        missing=False
        try:freeze(fixture,helper,runtime,out/'missing',out)
        except FileNotFoundError:missing=True
        if not missing or (out/'missing/manifest.json').exists():raise ValueError('Missing asset accepted')
        report.update(missing_asset_rejected=True,source_unavailable_during_packaged_render=True,
                      manifest_sha256=sha(manifest),reference_identity=lock['identity'])
        verify_runtime(runtime,lock)
        if any(sha(Path(f))!=h for f,h in held.items()):raise ValueError('Source drift')
        report['status']='passed'
    except Exception as e:report.update(status='failed',error=str(e))
    write_json(out/'report.json',report);print(report['status'],report.get('error',''),flush=True)
    return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
