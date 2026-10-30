"""Private background fallback controller with a bounded latest-scene mailbox.

Host calls only request(), poll(), cancel() and close(): no hashing, process
waits, log reads or scene reads happen there. wait_closed() is for service/test
shutdown, never the interactive host tick. A finished result is a tier-F EXR
reference; decoding/display remain separate background stages.
"""
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from fallback import FallbackJob
from protocol_model import Epoch
from reference_runtime import verify
from asset_snapshot import verify as verify_asset_snapshot


@dataclass(frozen=True)
class Request:
    ticket: int
    scene: Path
    epoch: Epoch
    threads: int
    asset_manifest: Path | None = None


@dataclass(frozen=True)
class Status:
    phase: str
    ticket: int
    active_ticket: int | None
    result: object
    error: str | None
    submitted: int
    coalesced: int
    cancelled: int
    completed: int
    discarded: int


class ReferenceService:
    def __init__(self,runtime,lock,output,job_factory=FallbackJob,verify_runtime=verify,verify_assets=verify_asset_snapshot):
        self.runtime=Path(runtime)
        self.output=Path(output)
        self._runtime_lock=lock
        self._factory=job_factory
        self._verify=verify_runtime
        self._verify_assets=verify_assets
        self._mutex=threading.Lock()
        self._wake=threading.Event()
        self._closed=threading.Event()
        self._closing=False
        self._ticket=0
        self._pending=None
        self._active=None
        self._result=None
        self._error=None
        self._phase="starting"
        self._submitted=self._coalesced=self._cancelled=self._completed=self._discarded=0
        self._thread=threading.Thread(target=self._run,name="XPU2-reference-service",daemon=True)
        self._thread.start()

    def request(self,scene,epoch,threads,asset_manifest=None):
        if not isinstance(epoch,Epoch) or type(threads) is not int or threads<=0:
            raise ValueError("Explicit epoch and positive threads required")
        # Caller supplies an owned, immutable canonical RDLB snapshot. All file
        # admission happens on the worker; this does not read the user's scene.
        path=Path(scene)
        if not path.is_absolute() or path.suffix.lower()!=".rdlb":
            raise ValueError("Absolute canonical RDLB path required")
        manifest=Path(asset_manifest) if asset_manifest is not None else None
        if manifest is not None and (not manifest.is_absolute() or manifest.parent!=path.parent):
            raise ValueError("Asset manifest must belong to the canonical scene package")
        with self._mutex:
            if self._closing or self._closed.is_set():
                raise RuntimeError("Reference service is closed")
            self._ticket+=1
            self._submitted+=1
            if self._pending is not None:self._coalesced+=1
            self._pending=Request(self._ticket,path,epoch,threads,manifest)
            self._result=None
            self._error=None
            self._phase="pending"
            ticket=self._ticket
        self._wake.set()
        return ticket

    def cancel(self):
        with self._mutex:
            self._ticket+=1 # Also invalidates a completed frame of the old ticket.
            self._pending=None
            self._result=None
            if not self._closing and not self._closed.is_set():self._phase="cancelling"
        self._wake.set()

    def poll(self):
        with self._mutex:
            return Status(self._phase,self._ticket,self._active,self._result,self._error,
                self._submitted,self._coalesced,self._cancelled,self._completed,self._discarded)

    def close(self):
        with self._mutex:
            self._closing=True
            self._pending=None
            self._result=None
        self._wake.set()

    def wait_closed(self,timeout):
        return self._closed.wait(timeout)

    def _run(self):
        job=None
        active=None
        cancel_started=None
        try:
            self.output.mkdir(parents=True,exist_ok=False)
            self._verify(self.runtime,self._runtime_lock)
            with self._mutex:
                if self._pending is None:self._phase="idle"
            while True:
                with self._mutex:
                    closing=self._closing
                    obsolete=active is not None and active.ticket!=self._ticket
                if job is not None:
                    if (closing or obsolete) and cancel_started is None:
                        job.cancel("service superseded or closed")
                        cancel_started=time.monotonic()
                        with self._mutex:self._cancelled+=1
                    state=job.poll()
                    if state in ("running","cancelling"):
                        if cancel_started is not None and time.monotonic()-cancel_started>5:
                            # Only this service's owned child may be killed.
                            if job.process.poll() is None:job.process.kill()
                    else:
                        # Do not read stale logs or expose results after an edit.
                        finished=job.result(active.epoch) if not closing and not obsolete else None
                        asset_error=None
                        if finished is not None and active.asset_manifest is not None:
                            try:
                                if self._verify_assets(active.asset_manifest)!=active.scene:
                                    raise ValueError("Asset package scene mismatch")
                            except Exception as error:
                                finished=None;asset_error=str(error)
                        with self._mutex:
                            self._active=None
                            if active.ticket==self._ticket and not self._closing:
                                self._result=finished
                                if finished is not None:
                                    self._phase="finished"
                                    self._completed+=1
                                else:
                                    self._phase="failed"
                                    self._error=asset_error or ("Fallback did not produce a verified XPU result ("+state+")")
                            else:self._discarded+=1
                        job=active=None
                        cancel_started=None
                if job is None:
                    with self._mutex:
                        if self._closing:break
                        request=self._pending
                        self._pending=None
                        if request is None and self._phase=="cancelling":self._phase="idle"
                    if request is not None:
                        active=request
                        try:
                            if request.asset_manifest is not None:
                                if self._verify_assets(request.asset_manifest)!=request.scene:
                                    raise ValueError("Asset package scene mismatch")
                            with self._mutex:
                                stale=self._closing or request.ticket!=self._ticket
                            if stale:
                                active=None
                                continue
                            job=self._factory(self.runtime,request.scene,
                                self.output/("frame-"+str(request.ticket)),request.threads,request.epoch)
                            job.start()
                            with self._mutex:
                                self._active=request.ticket
                                if request.ticket==self._ticket:self._phase="rendering"
                        except Exception as error:
                            with self._mutex:
                                if request.ticket==self._ticket:
                                    self._phase="failed"
                                    self._error=str(error)
                            job=active=None
                self._wake.wait(.01)
                self._wake.clear()
        except Exception as error:
            with self._mutex:
                self._phase="failed"
                self._error=str(error)
        finally:
            if job is not None and job.process is not None and job.process.poll() is None:
                job.cancel("service failure")
                try:job.process.wait(timeout=5)
                except Exception:
                    job.process.kill()
                    job.process.wait(timeout=5)
                job.poll()
            with self._mutex:
                self._active=None
                self._result=None
                if self._closing:self._phase="closed"
            self._closed.set()
