"""Actual background service admission of a frozen asset package, private only."""
import argparse
import json
import time
from pathlib import Path
from fallback_service import ReferenceService
from protocol_model import Epoch
from asset_snapshot import verify
from reference_runtime import sha
from run_m0 import image,write_json
from xpu2.material_job_metrics import compare
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime','manifest','reference','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();runtime,manifest,reference,out=[getattr(a,n).resolve() for n in ('runtime','manifest','reference','output')]
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'background frozen-asset admission and original-XPU pixels; no native XPU2 shading'}
    write_json(out/'report.json',report);service=None
    files=[HERE/n for n in ('asset_snapshot.py','fallback_service.py','fallback.py','run_asset_service.py')]
    held={str(f):sha(f) for f in files}
    try:
        scene=verify(manifest);lock=json.loads((HERE/'reference-lock.json').read_text())
        service=ReferenceService(runtime,lock,out/'service')
        ticket=service.request(scene,Epoch(601,1,1,1),1,manifest)
        end=time.monotonic()+180
        while time.monotonic()<end:
            status=service.poll()
            if status.phase in ('failed','finished'):break
            time.sleep(.02)
        else:raise TimeoutError('Asset service deadline')
        if status.phase!='finished':raise ValueError(status.error)
        if status.ticket!=ticket or status.result.epoch!=Epoch(601,1,1,1):raise ValueError('Stale result')
        comparison=compare(image(runtime,reference),image(runtime,status.result.image.parent))
        if any(comparison[c]['different_words'] for c in 'RGBA'):raise ValueError('Service pixels differ')
        report.update(status='passed',comparison=comparison,manifest_sha256=sha(manifest),source_hashes=held,
                      completed=status.completed,actual_mode=status.result.actual_mode,result=str(status.result.image))
        if any(sha(Path(f))!=v for f,v in held.items()):raise ValueError('Source drift')
    except Exception as e:report.update(status='failed',error=str(e))
    finally:
        if service is not None:
            service.close();report['closed']=service.wait_closed(10)
            if not report['closed']:report.update(status='failed',error='Service shutdown deadline')
    write_json(out/'report.json',report);print(report['status'],report.get('error',''),flush=True)
    return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
