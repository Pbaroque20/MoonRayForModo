"""Private real-process test of supersession, background admission and shutdown."""
import argparse
import json
from pathlib import Path
import sys
import time
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE),str(ROOT),str(ROOT/"tools")]
from fallback_service import ReferenceService
from protocol_model import Epoch
from reference_runtime import sha,verify
from run_m0 import guard,image,write_json
from xpu2.material_job_metrics import compare


def wait_status(service,predicate):
    end=time.monotonic()+120
    while time.monotonic()<end:
        status=service.poll()
        if status.phase=="failed":raise RuntimeError(status.error)
        if predicate(status):return status
        time.sleep(.01)
    raise TimeoutError("Fallback service did not reach requested state")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("runtime","indexed","output"):parser.add_argument("--"+key,type=Path,required=True)
    a=parser.parse_args()
    runtime,source,out=a.runtime.resolve(),a.indexed.resolve(),a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    report={"status":"incomplete","scope":"actual one-worker pinned MoonRay background service",
            "gates":{"supersession":"old result never published","new_frame":"float32 RGBA exact",
                     "close":"owned child retired; no result"},
            "limits":["No Modo host integration or UI latency qualification", "No XPU2 shading",
                      "Batch RDLB/EXR transport only", "No GPU-resource retirement test"]}
    write_json(out/"report.json",report)
    service=None
    try:
        guard()
        lock=json.loads((HERE/"reference-lock.json").read_text())
        files=[HERE/n for n in ("run_service.py","fallback_service.py","fallback.py","protocol_model.py",
                               "run_m0.py","reference_runtime.py","reference-lock.json")]
        files += [ROOT/"xpu2"/n for n in ("images.py","material_job_metrics.py","reference.py")]
        files += [ROOT/"tools"/n for n in ("validate_reference_images.py","xpu2_baseline.py","xpu2_cpu_cost_probe.py")]
        files += [ROOT/"kit/MoonRayForModo/python/moonray_modo/native.py",
                  source/"initial-indexed.rdlb",source/"map-indexed.rdlb",source/"map-source-render/beauty.exr"]
        held={str(p):sha(p) for p in files}
        report.update(source_hashes=held,reference_identity=lock["identity"])
        service=ReferenceService(runtime,lock,out/"service")
        first=service.request(source/"initial-indexed.rdlb",Epoch(1,1,0,0),1)
        wait_status(service,lambda s:s.active_ticket==first and s.phase=="rendering")
        second=service.request(source/"map-indexed.rdlb",Epoch(1,2,0,0),1)
        if service.poll().result is not None:raise ValueError("Old image exposed after scene edit")
        ready=wait_status(service,lambda s:s.ticket==second and s.phase=="finished")
        if ready.cancelled!=1 or ready.discarded!=1 or ready.completed!=1:
            raise ValueError("Unexpected ownership counts after supersession")
        if ready.result.epoch!=Epoch(1,2,0,0) or ready.result.tier!="F":
            raise ValueError("Incorrect published frame identity")
        actual=image(runtime,ready.result.image.parent)
        reference=image(runtime,source/"map-source-render")
        comparison=compare(reference,actual)
        if any(comparison[c]["different_words"] for c in "RGBA"):
            raise ValueError("Background fallback image differs")
        report.update(comparison=comparison,new_frame_sha256=sha(ready.result.image),
                      superseded_child_retired=True,published_epoch=[1,2,0,0])
        # Only a fresh active job is closed; never terminate another renderer.
        third=service.request(source/"initial-indexed.rdlb",Epoch(1,3,0,0),1)
        wait_status(service,lambda s:s.active_ticket==third and s.phase=="rendering")
        service.close()
        if not service.wait_closed(15):raise ValueError("Owned child did not retire on close")
        final=service.poll()
        if final.phase!="closed" or final.result is not None or final.cancelled!=2:
            raise ValueError("Invalid closed service")
        report["counts"]={k:getattr(final,k) for k in ("submitted","coalesced","cancelled","completed","discarded")}
        guard()
        verify(runtime,lock)
        if any(sha(Path(p))!=h for p,h in held.items()):raise ValueError("Source drift")
        report["status"]="passed"
    except Exception as error:report.update(status="failed",error=str(error))
    finally:
        if service:
            service.close()
            if not service.wait_closed(15):report.update(status="failed",error="Service shutdown timed out")
    write_json(out/"report.json",report)
    print(report["status"],report.get("error",""),flush=True)
    return 0 if report["status"]=="passed" else 1

if __name__=="__main__":raise SystemExit(main())
