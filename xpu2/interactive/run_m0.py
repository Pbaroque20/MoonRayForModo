"""Private M0 identity experiment, with frozen reference-only envelopes.

No candidate GPU rendering or speedup claim. Exact RGBA at one worker; at twelve,
held-out originals must pass their own five-run envelope before fallback counts.
This is a finite operational gate, not a population confidence guarantee.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE),str(ROOT),str(ROOT/"tools")]
from fallback import FallbackJob, environment, execution
from protocol_model import Epoch
from reference_runtime import sha,verify
from xpu2.images import read_rgba
from xpu2.material_job_metrics import compare,envelope,qualified
from xpu2_cpu_cost_probe import renderer_pids


def write_json(path,value):
    temp=path.with_suffix(".pending.json")
    temp.write_text(json.dumps(value,indent=2,allow_nan=False)+chr(10),encoding="utf-8")
    os.replace(temp,path)


def guard(owned=None):
    others=[pid for pid in renderer_pids() if pid!=owned]
    if others:
        raise RuntimeError("Competing MoonRay renderer: "+str(others))


def wait_job(job):
    # CLI/service worker only. FallbackJob.poll itself never sleeps or waits.
    try:
        while job.poll() in ("running","cancelling"):
            guard(job.process.pid)
            time.sleep(.02)
    except BaseException:
        job.cancel("harness aborted")
        deadline=time.monotonic()+10
        while job.poll()=="cancelling" and time.monotonic()<deadline:
            time.sleep(.02)
        if job.process.poll() is None:
            job.process.kill()
            job.process.wait(timeout=10)
            job.poll()
        raise


def standalone(runtime,scene,out,threads):
    guard()
    out.mkdir()
    args=[str(runtime/"moonray.exe"),"-in",str(scene),"-out",str(out/"beauty.exr"),
          "-exec_mode","xpu","-threads",str(threads),"-info","-stats",str(out/"stats.csv")]
    began=time.monotonic()
    with (out/"render.log").open("w",encoding="utf-8") as log:
        p=subprocess.Popen(args,cwd=out,env=environment(runtime,out),
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while p.poll() is None:
                guard(p.pid)
                if time.monotonic()-began>180:
                    raise TimeoutError("Reference exceeded timeout")
                time.sleep(.05)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
    data=(out/"render.log").read_text(errors="replace")
    stats=(out/"stats.csv").read_text(errors="replace") if (out/"stats.csv").exists() else ""
    ex=execution(data,stats,threads)
    if p.returncode or not ex["passed"] or not (out/"beauty.exr").is_file():
        raise ValueError("Invalid standalone execution: "+str(ex))
    return {"command":args,"wall_seconds":time.monotonic()-began,"execution":ex}


def image(runtime,out):
    value=read_rgba(runtime,out/"beauty.exr",out,"raw",environment(runtime,out))
    info=(out/"raw-info.txt").read_text()
    if "half" in info.lower() or "float" not in info.lower():
        raise ValueError("The source EXR must have full float channels")
    if max(value["channels"]["R"])<=0 or max(value["channels"]["A"])<=0:
        raise ValueError("Empty reference image")
    return value


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--runtime",type=Path,required=True)
    p.add_argument("--lock",type=Path,default=HERE/"reference-lock.json")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--threads",type=int,nargs="+",default=[1,12])
    a=p.parse_args()
    if any(t not in (1,12) for t in a.threads):
        p.error("Protocol frozen for 1 and 12 workers")
    rt,out=a.runtime.resolve(),a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    report={"status":"incomplete","kind":"M0-batch-fallback-identity",
        "limits":["No XPU2 image or speedup","No interactive Arras or Modo integration",
                  "Beauty RGBA fixture only; no all-AOV or scene-corpus qualification",
                  "Binary baseline pinned; clean source rebuild provenance remains open"],
        "cases":{}}
    write_json(out/"report.json",report)
    try:
        lock=json.loads(a.lock.read_text())
        verify(rt,lock)
        report["reference_identity"]=lock["identity"]
        fixture=ROOT/"test-results/xpu2-cpu-cost-full-run/diffuse.rdla"
        text=fixture.read_text()+chr(10)+"""
SceneVariables { ["image_width"]=192, ["image_height"]=128, ["pixel_samples"]=2,
 ["sampling_mode"]=0, ["frame"]=0, ["lock_frame_noise"]=true }
RenderOutput("/m0/beauty") { ["file_name"]="beauty.exr", ["result"]=0,
 ["channel_format"]=0, ["compression"]=1 }
RenderOutput("/m0/alpha") { ["file_name"]="beauty.exr", ["result"]=1,
 ["channel_format"]=0, ["compression"]=1 }
"""
        source=out/"scene.rdla"
        source.write_text(text,encoding="utf-8")
        scene=out/"scene.rdlb"
        cmd=[str(rt/"rdl2_convert.exe"),"-i",str(source),"-o",str(scene)]
        done=subprocess.run(cmd,cwd=out,env=environment(rt,out),capture_output=True,
            text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/"conversion.log").write_text(done.stdout+done.stderr)
        if done.returncode or not scene.is_file():
            raise ValueError("RDLB conversion failed")
        report["scene"]={"source_fixture_sha256":sha(fixture),"rdla_sha256":sha(source),
            "rdlb_sha256":sha(scene),"conversion_command":cmd}
        pinned=[Path(__file__),HERE/"fallback.py",HERE/"protocol_model.py",
            HERE/"reference_runtime.py",ROOT/"xpu2/images.py",ROOT/"xpu2/reference.py",
            ROOT/"xpu2/material_job_metrics.py",ROOT/"tools/validate_reference_images.py",
            ROOT/"tools/xpu2_cpu_cost_probe.py",ROOT/"tools/xpu2_baseline.py",
            ROOT/"tools/xpu2_repeatability.py",ROOT/"kit/MoonRayForModo/python/moonray_modo/native.py",
            scene,source,a.lock.resolve(),HERE/"m0-gates.json"]
        hashes={str(f):sha(f) for f in pinned}
        report["source_hashes"]=hashes
        write_json(out/"report.json",report)
        all_ok=True
        for threads in a.threads:
            case=report["cases"][str(threads)]={"runs":[]}
            originals=[]
            for i in range(5):
                label=f"t{threads}-reference-{i}"
                print(label,flush=True)
                folder=out/label
                row=standalone(rt,scene,folder,threads)
                value=image(rt,folder)
                originals.append(value)
                case["runs"].append(dict(row,label=label,image_sha256=sha(folder/"beauty.exr")))
                write_json(out/"report.json",report)
            bound=envelope(originals)
            case["frozen_reference_envelope"]=bound
            write_json(out/"report.json",report)
            # Save bounds before any held-out reference or fallback is rendered.
            write_json(out/f"t{threads}-frozen-envelope.json",bound)
            holdout_ok=True
            for i in range(2):
                label=f"t{threads}-holdout-{i}"
                print(label,flush=True)
                folder=out/label
                row=standalone(rt,scene,folder,threads)
                value=image(rt,folder)
                comparisons=[compare(ref,value) for ref in originals]
                ok=qualified(comparisons,None if threads==1 else bound)
                holdout_ok &= ok
                case["runs"].append(dict(row,label=label,passed=ok,comparisons=comparisons,
                    image_sha256=sha(folder/"beauty.exr")))
                write_json(out/"report.json",report)
            # Cancellation removes only our child and never qualifies a partial output.
            guard()
            epoch=Epoch(1,1,1,1)
            job=FallbackJob(rt,scene,out/f"t{threads}-cancel",threads,epoch)
            job.start()
            job.cancel()
            wait_job(job)
            case["cancellation"]={"state":job.state,"no_result":job.result(epoch) is None}
            if job.state!="cancelled" or job.result(epoch) is not None:
                raise ValueError("Cancelled output was exposed")
            fallback_ok=True
            for i in range(2):
                guard()
                label=f"t{threads}-fallback-{i}"
                print(label,flush=True)
                job=FallbackJob(rt,scene,out/label,threads,epoch)
                job.start()
                wait_job(job)
                result=job.result(epoch)
                stale=job.result(Epoch(1,1,1,2))
                if result is None or stale is not None:
                    raise ValueError("Fallback invalid or stale output exposed")
                value=image(rt,job.output)
                comparisons=[compare(ref,value) for ref in originals]
                ok=qualified(comparisons,None if threads==1 else bound)
                fallback_ok &= ok
                case["runs"].append({"label":label,"passed":ok,"comparisons":comparisons,
                    "image_sha256":sha(result.image),"tier":result.tier,"execution":job.execution,
                    "command":job.command,"wall_seconds":job.wall_seconds,"stale_rejected":True})
                write_json(out/"report.json",report)
            case.update(held_out_reference_passed=holdout_ok,fallback_passed=fallback_ok,
                        passed=holdout_ok and fallback_ok)
            all_ok &= case["passed"]
        for f,h in hashes.items():
            if sha(f)!=h:
                raise ValueError("Measurement input changed: "+f)
        verify(rt,lock)
        report["status"]="passed" if all_ok else "failed"
    except Exception as e:
        report.update(status="failed",error=str(e),traceback=traceback.format_exc())
    write_json(out/"report.json",report)
    print(report["status"],report.get("error",""),flush=True)
    return 0 if report["status"]=="passed" else 1


if __name__=="__main__":
    raise SystemExit(main())
