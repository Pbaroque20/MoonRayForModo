"""Private prewarming failure and early-close checks."""
import json,time,traceback
from pathlib import Path
from prototype_service import PrototypeService
from prototype_wire import NativeProcess
from protocol_model import Epoch
from reference_runtime import sha,verify
from reference_repeatability import save
from run_prototype import packed
from run_m0 import guard,image
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-startup-failure-20261022';OUT.mkdir(exist_ok=False);rt=TR/'interactive-reference-042';b=json.loads((TR/'interactive-prototype-build-20261022startup/build.json').read_text());lock=json.loads((HERE/'reference-lock.json').read_text());r={'status':'incomplete'};service=None
try:
 guard();bad=OUT/'invalid.ptx';bad.write_text('intentionally invalid private diagnostic PTX',encoding='utf-8');hashes=dict(b['binary_hashes']);hashes['ptx']=sha(bad)
 service=PrototypeService(b['exe'],bad,rt,lock,OUT/'failure',binary_hashes=hashes);f=TR/'interactive-speed-20261022/room-close/grid-8/frozen/manifest.json';ticket=service.request(f,Epoch(4501,1,1,1),12,experimental_native=True,refill_fine=True,publish_ms=33);start=time.monotonic()
 while time.monotonic()-start<180:
  s=service.poll()
  if s.phase=='failed':raise RuntimeError(s.error)
  if s.frame and s.frame.final:
   assert s.frame.ticket==ticket and s.frame.tier=='F' and s.fallback_reason and s.frame.rgba==packed(image(rt,s.frame.reference_image.parent));r['compiler_failure']={'fallback_reason':s.fallback_reason,'exact_reference_pixels':True};break
  time.sleep(.005)
 else:raise TimeoutError('Compiler failure did not fall back')
 service.close();assert service.wait_closed(25);service=None
 p=NativeProcess(b['exe'],rt,b['ptx'],OUT/'early-close');pid=p.process.pid;time.sleep(.03);start=time.monotonic();p.close(timeout=5);r['early_close']={'seconds':time.monotonic()-start,'pid':pid,'exit_code':p.process.poll()};assert p.process.poll() is not None
 verify(rt,lock);guard();r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
finally:
 if service:service.close();service.wait_closed(25)
save(OUT/'report.json',r);print(json.dumps(r,indent=2),flush=True);raise SystemExit(r['status']!='passed')
