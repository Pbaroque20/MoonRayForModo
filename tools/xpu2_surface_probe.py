"""Full-frame, one-sample primary-hit comparison: vector vs XPU, one thread.

Avoids -debug_pixel: a one-pixel render changes batch sizes and can route all
intersection work to the CPU. Surface AOVs locate first-hit differences but do
not constitute a per-bounce ray/BSDF trace.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"tools")]
from xpu2.reference import digest_file, identity, verify, compare_values
from xpu2.images import read_rgba, compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful
from validate_reference_images import pixels



def summarize_state(size, a, b, beauty):
    if len(a) != size[0]*size[1]*3 or len(b) != len(a):
        raise ValueError("Invalid state buffer size")
    metrics=compare_values(a,b,0,0)
    diffs=[(max(abs(a[i*3+c]-b[i*3+c]) for c in range(3)),i) for i in range(size[0]*size[1])]
    peak,i=max(diffs)
    def point(x,y):
        j=y*size[0]+x
        return {"x":x,"y_from_bottom":y,"vectorized":list(a[j*3:j*3+3]),"xpu":list(b[j*3:j*3+3])}
    metrics["largest_difference"]=point(i%size[0],i//size[0]) if peak else None
    for key, row in (("at_first_beauty_difference",beauty["first_difference"]),
                     ("at_largest_beauty_difference",next(iter(beauty["largest_differences"]),None))):
        if row:metrics[key]=point(row["x"],row["y_from_bottom"])
    return metrics

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    runtime,out=args.runtime.resolve(),args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    report={"status":"incomplete","scope":"One camera sample per pixel; primary-hit state only",
            "runs":[],"state":{}}
    try:
        lock=json.loads((ROOT/"xpu2/reference/reference.json").read_text(encoding="utf-8"))
        if lock["identity"]!=identity(lock["contract"]):raise ValueError("Invalid lock")
        verify(runtime,lock["contract"]["runtime"])
        original=ROOT/"xpu2/reference/scene.rdla"
        if digest_file(original)!=lock["contract"]["scene_sha256"]:raise ValueError("Fixture changed")
        scene=original.read_bytes()+b'\nSceneVariables { ["frame"]=0, ["min_frame"]=0, ["max_frame"]=0, ["lock_frame_noise"]=true, ["pixel_samples"]=1 }\n'
        lines=['RenderOutput("/xpu2/beauty") { ["result"]=0, ["file_name"]="beauty.exr", ["channel_format"]=0 }',
               'RenderOutput("/xpu2/alpha") { ["result"]=1, ["file_name"]="beauty.exr", ["channel_format"]=0 }']
        for name,value in (("P",0),("Ng",1),("N",2)):
            lines.append('RenderOutput("/xpu2/%s") { ["result"]=3, ["state_variable"]=%d, ["file_name"]="%s.exr", ["channel_format"]=0 }'%(name,value,name))
        (out/"scene.rdla").write_bytes(scene+("\n".join(lines)+"\n").encode())
        report["diagnostic_scene_sha256"]=digest_file(out/"scene.rdla")
        report["reference_identity"]=lock["identity"]
        held={}
        for mode in ("vectorized","xpu"):
            folder=out/mode;folder.mkdir()
            env=environment(runtime,folder)
            command=[str(runtime/"moonray.exe"),"-in",str(out/"scene.rdla"),"-out",str(folder/"beauty.exr"),
                     "-exec_mode",mode,"-threads","1","-info","-stats",str(folder/"stats.csv")]
            print("Rendering surface probe "+mode,flush=True)
            with (folder/"render.log").open("w",encoding="utf-8") as stream:
                done=subprocess.run(command,env=env,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,
                                    timeout=180,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            log=(folder/"render.log").read_text(encoding="utf-8",errors="replace")
            stats=(folder/"stats.csv").read_text(encoding="utf-8",errors="replace")
            check=successful(mode,1,done.returncode,log,stats,(folder/"beauty.exr").is_file())
            report["runs"].append(dict(check,mode=mode))
            if not check["passed"]:raise ValueError("Invalid surface render: "+mode)
            values={}
            values["beauty"]=read_rgba(runtime,folder/"beauty.exr",folder,"beauty",env)
            for name in ("P","Ng","N"):
                info=subprocess.run([str(runtime/"oiiotool.exe"),"--info","-v",str(folder/(name+".exr"))],
                                    env=env,capture_output=True,text=True,timeout=60,
                                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                (folder/(name+"-info.txt")).write_text(info.stdout+info.stderr,encoding="utf-8")
                names=re.findall(r"channel list:\s*([^\r\n]+)",info.stdout)
                if info.returncode or len(names)!=1 or len(names[0].split(","))!=3:
                    raise ValueError("Expected a float vector output: "+name)
                done=subprocess.run([str(runtime/"oiiotool.exe"),str(folder/(name+".exr")),
                                     "-d","float","-o",str(folder/(name+".pfm"))],env=env,
                                    capture_output=True,text=True,timeout=60,
                                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                if done.returncode:raise ValueError(done.stderr)
                values[name]=pixels(folder/(name+".pfm"))
            held[mode]=values
        report["beauty"]=compare_rgba(held["vectorized"]["beauty"],held["xpu"]["beauty"])
        for name in ("P","Ng","N"):
            (size,a),(other,b)=held["vectorized"][name],held["xpu"][name]
            if size!=other:raise ValueError("State dimensions differ")
            report["state"][name]=summarize_state(size,a,b,report["beauty"])
        verify(runtime,lock["contract"]["runtime"])
        report["status"]="measured_differences" if any(not row["passed"] for row in report["state"].values()) or report["beauty"]["status"]=="failed" else "exact_match_observed"
    except Exception as exc:report["error"]=str(exc)
    (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(report["status"],out/"report.json",flush=True)
    return {"exact_match_observed":0,"measured_differences":2}.get(report["status"],1)


if __name__=="__main__":raise SystemExit(main())
