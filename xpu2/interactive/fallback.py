"""Polling Windows MoonRay fallback; no Modo API or display transforms.
Hash verification and decoding run on service workers, not inside poll().
This is batch/reference fallback, not Arras progressive integration.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import time
from protocol_model import Epoch


def environment(runtime, output):
    allowed={"SYSTEMROOT","WINDIR","COMSPEC","USERPROFILE","LOCALAPPDATA",
             "APPDATA","PROGRAMDATA","SYSTEMDRIVE","NUMBER_OF_PROCESSORS"}
    env={k:v for k,v in os.environ.items() if k.upper() in allowed}
    windows=Path(env.get("SystemRoot",env.get("SYSTEMROOT",r"C:\Windows")))
    env.update(PATH=os.pathsep.join(map(str,(runtime,windows/"System32",windows))),
        TEMP=str(output),TMP=str(output),TMPDIR=str(output),
        REZ_MOONRAY_ROOT=str(runtime),
        RDL2_DSO_PATH=os.pathsep.join(str(p) for p in (runtime/"rdl2dso",runtime)
                                    if p.is_dir()))
    return env


def execution(log, stats, threads):
    selected="executing an xpu render" in log.lower()
    setup="GPU: Setup complete" in log
    fallback="falling back" in log.lower()
    problem=bool(re.search(r"optixLaunch\(\) failure|cudaStreamSynchronize\(\) error",log))
    actual=re.search(r"^Thread\(s\),(\d+)\s*$",stats,re.MULTILINE)
    utilization=re.search(r"GPU bundled intersection ray utilization\s*=\s*([0-9.]+)%",log)
    actual_threads=int(actual.group(1)) if actual else None
    gpu_intersections=float(utilization.group(1)) if utilization else None
    return {"requested_mode":"xpu","actual_mode":"xpu" if selected and not fallback else "unverified",
        "threads":actual_threads,"gpu_intersection_percent":gpu_intersections,
        "passed":bool(selected and setup and not fallback and not problem and
                      actual_threads==threads and (gpu_intersections or 0)>0)}


@dataclass(frozen=True)
class Finished:
    epoch: Epoch
    image: Path
    tier: str
    actual_mode: str


class FallbackJob:
    def __init__(self,runtime,scene,output,threads,epoch,timeout=180.0):
        self.runtime=Path(runtime).resolve()
        self.scene=Path(scene).resolve()
        self.output=Path(output).resolve()
        if not isinstance(epoch,Epoch) or type(threads) is not int or threads<=0:
            raise ValueError("Explicit epoch and positive thread count required")
        if not 0 < timeout < 86400:
            raise ValueError("Invalid timeout")
        if self.scene.suffix.lower()!=".rdlb" or not self.scene.is_file():
            raise ValueError("A frozen RDLB input is required")
        if self.output.exists():
            raise ValueError("A fresh output directory is required")
        self.threads,self.epoch,self.timeout=threads,epoch,timeout
        self.state="new"
        self.process=None
        self.log=None
        self.reason=None
        self.code=None
        self.image=self.output/"beauty.exr"

    def start(self):
        if self.state!="new":
            raise ValueError("Job already started")
        self.output.mkdir(parents=True)
        self.log=(self.output/"render.log").open("w",encoding="utf-8")
        self.command=[str(self.runtime/"moonray.exe"),"-in",str(self.scene),
            "-out",str(self.image),"-exec_mode","xpu","-threads",str(self.threads),
            "-info","-stats",str(self.output/"stats.csv")]
        self.began=time.monotonic()
        try:
            self.process=subprocess.Popen(self.command,cwd=self.output,
                env=environment(self.runtime,self.output),stdout=self.log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except Exception:
            self.log.close()
            self.state="failed"
            raise
        self.state="running"

    def cancel(self,reason="cancelled"):
        if self.state=="running":
            self.reason=reason
            self.state="cancelling"
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass

    def poll(self):
        if self.state not in ("running","cancelling"):
            return self.state
        code=self.process.poll()
        if code is None:
            if self.state=="running" and time.monotonic()-self.began>self.timeout:
                self.cancel("timeout")
            return self.state
        self.code=code
        self.log.close()
        self.wall_seconds=time.monotonic()-self.began
        self.state=("cancelled" if self.reason else ("finished" if code==0 else "failed"))
        return self.state

    def result(self,current_epoch):
        if self.poll()!="finished" or current_epoch!=self.epoch or not self.image.is_file():
            return None
        log=(self.output/"render.log").read_text(encoding="utf-8",errors="replace")
        stats_path=self.output/"stats.csv"
        stats=stats_path.read_text(encoding="utf-8",errors="replace") if stats_path.exists() else ""
        self.execution=execution(log,stats,self.threads)
        if not self.execution["passed"]:
            return None
        return Finished(self.epoch,self.image,"F","xpu")
