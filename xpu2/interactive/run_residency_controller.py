"""Targeted final controller checks after qualification/log-lifecycle fixes."""
import argparse,array,json,time
from pathlib import Path
from prototype_service import PrototypeService
from protocol_model import Epoch
from reference_runtime import sha,verify
from run_m0 import guard,image
from run_prototype import packed,classify
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','runtime','manifest','previous','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);rt=a.runtime.resolve();manifest=a.manifest.resolve();service=None
    r={'status':'incomplete','scope':'current controller startup, preview, failure fallback, raw decode and unqualified tags; not reference-repeatability or speed qualification'}
    try:
        guard();lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);b=json.loads(a.build.read_text());assert b['status']=='passed'
        assert all(sha(Path(k))==v for k,v in b['source_hashes'].items()),'Compiled source drift'
        previous=json.loads(a.previous.read_text());r['earlier_full_sequence_review']=classify(previous)['status']
        (out/'qualification-review.json').write_text(json.dumps({k:v for k,v in previous.items() if k in ('status','operational_status','reference_gate','reference_repeatability','default_reference','failure_fallback','process_crash_fallback')},indent=2)+'\n')
        held={str(HERE/n):sha(HERE/n) for n in ('prototype_service.py','prototype_wire.py','run_residency_controller.py','run_prototype.py','prototype_preview.py')};r['source_hashes']=held
        service=PrototypeService(b['exe'],b['ptx'],rt,lock,out/'session',binary_hashes=b['binary_hashes'],test_faults=True)
        def run(number,fault=0,refill=True):
            ticket=service.request(manifest,Epoch(2101,number,1,1),1 if fault else 12,experimental_native=True,fault=fault,refill_fine=refill,publish_ms=33 if refill else 0);end=time.monotonic()+180;seen=0
            while time.monotonic()<end:
                s=service.poll()
                if s.phase=='failed':raise RuntimeError(s.error)
                if s.frame:
                    assert s.frame.ticket==ticket and not s.frame.qualified
                    if s.frame.final:return s,seen
                    seen+=1
                time.sleep(.005)
            raise TimeoutError('Final controller check timed out')
        s,partials=run(1);assert s.frame.tier=='D' and partials>0 and s.frame.gpu_samples==s.frame.cpu_samples and s.frame.gpu_samples>0 and s.frame.fine_refills==1 and s.frame.migrated_paths==0
        (out/'native.rgba').write_bytes(s.frame.rgba);r['progressive_native']={'partials_seen':partials,'windows':s.frame.windows,'raw_sha256':sha(out/'native.rgba'),'qualified':s.frame.qualified,'gpu_samples':s.frame.gpu_samples,'cpu_samples':s.frame.cpu_samples,'fine_refills':s.frame.fine_refills,'migrated_paths':s.frame.migrated_paths}
        s,_=run(2);assert s.frame.tier=='D' and s.frame.fine_refills==0 and s.frame.migrated_paths==0 and s.frame.gpu_samples==s.frame.cpu_samples;r['second_request_fine_cache_preserved']=True
        s,_=run(3,refill=False);assert s.frame.tier=='D' and s.frame.migrated_paths>0;r['option_off_legacy_migration']=True
        s,_=run(4,1);assert s.frame.tier=='F' and s.fallback_reason and s.frame.rgba==packed(image(rt,s.frame.reference_image.parent))
        r['fallback']={'reason':s.fallback_reason,'tier':'F','qualified':s.frame.qualified,'exact_owned_reference_pixels':True}
        service.close();assert service.wait_closed(25) and service.poll().frame is None and service.poll().phase=='closed' and service.poll().error is None
        assert all(sha(Path(k))==v for k,v in held.items()),'Controller source drift'
        verify(rt,lock);guard();r['status']='passed'
    except Exception as error:r.update(status='failed',error=str(error))
    finally:
        if service is not None:service.close();service.wait_closed(25)
    (out/'report.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k!='source_hashes'},indent=2),flush=True);return r['status']!='passed'
if __name__=='__main__':raise SystemExit(main())
