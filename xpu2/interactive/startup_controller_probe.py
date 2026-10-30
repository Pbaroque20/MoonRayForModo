"""Fresh private controller launch to first partial and final pixels."""
import argparse,sys,json,time
from pathlib import Path
p=argparse.ArgumentParser()
for n in ('source','build','manifest','output','runtime','lock'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();sys.path.insert(0,str(a.source.resolve()))
from prototype_service import PrototypeService
from protocol_model import Epoch
from reference_runtime import sha
b=json.loads(a.build.read_text());out=a.output.resolve();out.mkdir(exist_ok=False);service=None;r={'status':'incomplete','source':str(a.source),'build_sha256':sha(a.build)}
try:
 t=time.perf_counter();service=PrototypeService(b['exe'],b['ptx'],a.runtime,json.loads(a.lock.read_text()),out/'session',binary_hashes=b['binary_hashes'])
 ticket=service.request(a.manifest,Epoch(4401,1,1,1),12,experimental_native=True,refill_fine=True,publish_ms=33);first=None;phases={}
 while time.perf_counter()-t<180:
  s=service.poll();phases.setdefault(s.phase,time.perf_counter()-t)
  if s.phase=='failed':raise RuntimeError(s.error)
  if s.frame:
   f=s.frame;assert f.ticket==ticket and f.tier=='D' and not f.qualified
   if first is None:first=time.perf_counter()-t
   if f.final:
    r.update(first_image_seconds=first,final_image_seconds=time.perf_counter()-t,phases=phases,cpu_samples=f.cpu_samples,gpu_samples=f.gpu_samples,migrated_paths=f.migrated_paths);(out/'beauty.rgba').write_bytes(f.rgba);r['sha256']=sha(out/'beauty.rgba');break
  time.sleep(.005)
 else:raise TimeoutError('No controller final')
 service.close();assert service.wait_closed(25);r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e))
finally:
 if service:service.close();service.wait_closed(25)
(out/'report.json').write_text(json.dumps(r,indent=2),encoding='utf-8');print(json.dumps(r),flush=True);raise SystemExit(r['status']!='passed')
