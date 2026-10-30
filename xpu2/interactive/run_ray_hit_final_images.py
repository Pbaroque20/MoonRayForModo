"""Replay the timed images through the final private standalone controller."""
import json,time,traceback
from pathlib import Path
from prototype_service import PrototypeService
from protocol_model import Epoch
from reference_runtime import sha,verify
from reference_repeatability import save,values,distance
from run_m0 import guard
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-ray-hit-final-images-20261022';OUT.mkdir(exist_ok=False)
r={'status':'incomplete','scope':'final controller image replay after planar-only regression fix; timings remain those of the archived spatial candidate','cases':{}};service=None
try:
 rt=TR/'interactive-reference-042';lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard();b=json.loads((TR/'interactive-prototype-build-20261022hits/build.json').read_text());assert b['status']=='passed' and all(sha(Path(k))==v for k,v in b['source_hashes'].items());r['build']=b['binary_hashes'];r['source_hashes']=b['source_hashes'];fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());bench=json.loads((TR/'interactive-ray-hit-benchmark-20261022/report.json').read_text());assert bench['status']=='passed'
 service=PrototypeService(b['exe'],b['ptx'],rt,lock,OUT/'session',binary_hashes=b['binary_hashes']);number=0
 for name,f in fixtures['cases'].items():
  for threads in (1,12):
   number+=1;manifest=Path(f['scenes']['8']).parent/'manifest.json';ticket=service.request(manifest,Epoch(2401,number,1,1),threads,experimental_native=True,refill_fine=True,publish_ms=33);end=time.monotonic()+180
   while time.monotonic()<end:
    s=service.poll()
    if s.phase=='failed':raise RuntimeError(s.error)
    if s.frame and s.frame.final:
     frame=s.frame;assert frame.ticket==ticket and frame.tier=='D' and not frame.qualified and frame.cpu_samples==frame.gpu_samples and frame.migrated_paths==0;raw=OUT/(name+'-t'+str(threads)+'.rgba');raw.write_bytes(frame.rgba);expected=Path(bench['cases'][name]['native'][str(threads)]['runs'][0]['raw_file']);delta=distance(values(frame.rgba),values(expected.read_bytes()));assert delta<=.002
     r['cases'][name+'-'+str(threads)]={'sha256':sha(raw),'timed_sha256':sha(expected),'max_delta':delta,'byte_identical':frame.rgba==expected.read_bytes(),'gpu_samples':frame.gpu_samples,'cpu_samples':frame.cpu_samples};save(OUT/'report.json',r);print(name,threads,'image replay',delta,flush=True);break
    time.sleep(.005)
   else:raise TimeoutError('Final image timeout')
 service.close();assert service.wait_closed(25);assert all(sha(Path(k))==v for k,v in b['source_hashes'].items());verify(rt,lock);guard();r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
finally:
 if service is not None:service.close();service.wait_closed(25)
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
