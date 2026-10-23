"""Private real-RDL index/publication integration; exact one-worker fallback images.
This exercises no XPU2 shading and makes no performance claim.
"""
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE),str(ROOT),str(ROOT/"tools")]
from reference_runtime import sha,verify
from fallback import environment
from run_m0 import standalone,image,guard,write_json
from xpu2.material_job_metrics import compare
from xpu2_rdl_index_probe import block


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("source","runtime","scene","output"):
        parser.add_argument("--"+key,type=Path,required=True)
    parser.add_argument("--probe",choices=("routing","session"),default="routing")
    args=parser.parse_args()
    source,runtime,scene,out=(getattr(args,k).resolve() for k in ("source","runtime","scene","output"))
    if out.is_relative_to(source) or out.is_relative_to(runtime):
        parser.error("An isolated output folder is required")
    out.mkdir(parents=True,exist_ok=False)
    report={"status":"incomplete","scope":"real-RDL indexed fallback; no XPU2 shading", "renders":[],
            "gates":{"threads":1,"float32_rgba":"identical words", "unknown_features":"fallback",
                     "publication":"backend-ready; reject stale completion", "geometry_reuse":True},
            "limits":["No production renderer connected to Router", "Dirty capture still scans scene objects",
                      "No in-flight GPU resource-retirement qualification", "No throughput claim"]}
    write_json(out/"report.json",report)
    try:
        lock=json.loads((HERE/"reference-lock.json").read_text())
        verify(runtime,lock)
        report["reference_identity"]=lock["identity"]
        probe="scene_index_probe.cc" if args.probe=="routing" else "canonical_session_test.cc"
        files=[HERE/n for n in (probe,"canonical_session.h","routing_index.h","run_scene_index.py",
               "reference-lock.json","reference_runtime.py","run_m0.py","fallback.py","protocol_model.py")]
        files += [ROOT/"xpu2"/n for n in ("indexed_scene.h","persistent_map.h","rdl_scene_index.h","rdl_replica.h",
                   "images.py","material_job_metrics.py","reference.py")]
        files += [ROOT/"tools"/n for n in ("xpu2_rdl_index_probe.py","xpu2_baseline.py","xpu2_repeatability.py",
                   "validate_reference_images.py","xpu2_cpu_cost_probe.py")]
        files += [ROOT/"kit/MoonRayForModo/python/moonray_modo/native.py",scene]
        hashes={str(f):sha(f) for f in files}
        build=source/"build/native-avx"
        compiler=source/"toolchain/msys64/ucrt64/bin/g++.exe"
        ninja=(build/"build.ninja").read_text(encoding="utf-8")
        compile_block=block(ninja,"build scene-rdl2/cmd/rdl2_cmd/rdl2_print/CMakeFiles/rdl2_print.dir/rdl2_print.cc.obj:")
        link_block=block(ninja,"build bin/rdl2_print.exe:")
        flags=shlex.split(" ".join(compile_block[k] for k in ("DEFINES","FLAGS","INCLUDES")))
        flags += ["-I"+str(compiler.parent.parent/"include"),"-fno-fast-math","-ffp-contract=off"]
        libs=[str((build/v).resolve()) if not v.startswith("-") else v for v in shlex.split(link_block["LINK_LIBRARIES"])]
        held={v:sha(Path(v)) for v in libs if not v.startswith("-")}
        exe,preprocessed=out/"scene-index.exe",out/"scene-index.ii"
        for label,cmd in (("preprocess",["-E",str(HERE/probe),"-o",str(preprocessed)]),
                          ("compile",[str(preprocessed),"-o",str(exe),*libs])):
            print(label,flush=True)
            done=subprocess.run([str(compiler),*flags,*cmd],env=environment(compiler.parent,out),
                  capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+".log")).write_text(done.stdout+done.stderr,encoding="utf-8")
            if done.returncode: raise ValueError(label+" failed")
        report.update(source_hashes=hashes,library_hashes=held,compiler_sha256=sha(compiler),
                      preprocessed_sha256=sha(preprocessed),executable_sha256=sha(exe))
        write_json(out/"report.json",report)
        env=environment(runtime,out)
        print("index and gated publication",flush=True)
        done=subprocess.run([str(exe),str(scene),env["RDL2_DSO_PATH"],str(out)],env=env,cwd=out,
                 capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/"probe.log").write_text(done.stdout+done.stderr,encoding="utf-8")
        if done.returncode:raise ValueError("Native probe failed: "+done.stderr[-1200:])
        report["native"]=json.loads(done.stdout)
        if report["native"]["status"]!="passed":raise ValueError("Index validation failed")
        write_json(out/"report.json",report)
        for entry in report["native"]["stages"]:
            stage=entry["name"]
            images={}
            for kind in ("source","indexed"):
                label=stage+"-"+kind
                print(label,flush=True)
                scene_path=out/(label+".rdlb")
                folder=out/(label+"-render")
                row=standalone(runtime,scene_path,folder,1)
                images[kind]=image(runtime,folder)
                row.update(label=label,scene_sha256=sha(scene_path),image_sha256=sha(folder/"beauty.exr"))
                report["renders"].append(row)
                write_json(out/"report.json",report)
            comparison=compare(images["source"],images["indexed"])
            report["renders"][-1]["comparison"]=comparison
            if any(comparison[c]["different_words"] for c in "RGBA"):raise ValueError("Image words differ: "+stage)
            write_json(out/"report.json",report)
        verify(runtime,lock)
        if any(sha(Path(f))!=digest for f,digest in {**hashes,**held}.items()):
            raise ValueError("Source/library drift")
        report["status"]="passed"
    except Exception as error:
        report.update(status="failed",error=str(error))
    write_json(out/"report.json",report)
    print(report["status"],report.get("error",""),flush=True)
    return 0 if report["status"]=="passed" else 1

if __name__=="__main__":raise SystemExit(main())
