"""Private opt-in mode controller. Native previews are unqualified tier D.

A request is an owned immutable asset package, never a user's mutable scene.
Unsupported admission, native crash/timeout or invalid pixels retire the entire
native epoch and automatically render that same package through pinned XPU.
No native pixels are blended with reference pixels. Default requests are F-only.
Public methods only update bounded mailboxes; hashing, reads, rendering and
reference decoding happen on background workers. This is not a Modo integration.
"""
from collections import deque
from dataclasses import dataclass,asdict
from pathlib import Path
import threading
import time
import asset_snapshot
from fallback_service import ReferenceService
from protocol_model import Epoch
from prototype_wire import NativeProcess,decode
from reference_runtime import sha,verify

@dataclass(frozen=True)
class Request:
    ticket:int
    scene:Path
    manifest:Path
    epoch:Epoch
    threads:int
    experimental_native:bool
    domain:str
    window_ms:int
    fault:int
    refill_fine:bool=False
    publish_ms:int=0

@dataclass(frozen=True)
class Frame:
    ticket:int
    epoch:Epoch
    tier:str
    qualified:bool
    final:bool
    width:int
    height:int
    rgba:bytes
    min_spp:int=0
    windows:int=0
    pending_paths:int=0
    reference_image:Path|None=None
    gpu_samples:int=0
    cpu_samples:int=0
    fine_refills:int=0
    migrated_paths:int=0

@dataclass(frozen=True)
class Status:
    ticket:int
    phase:str
    frame:Frame|None
    fallback_reason:str|None
    error:str|None
    events:tuple
    submitted:int
    coalesced:int
    discarded:int
    native_frames:int
    reference_frames:int
    fallbacks:int

class PrototypeService:
    def __init__(self,exe,ptx,runtime,lock,output,*,binary_hashes,test_faults=False,native_timeout=180):
        self.exe,self.ptx,self.runtime,self.output=map(Path,(exe,ptx,runtime,output))
        self._runtime_lock=lock;self._hashes=dict(binary_hashes);self._test_faults=test_faults
        if not 1<=native_timeout<=600:raise ValueError('Invalid native timeout')
        self._native_timeout=native_timeout
        self._mutex=threading.Lock();self._wake=threading.Event();self._closed=threading.Event()
        self._closing=False;self._ticket=0;self._pending=None;self._frame=None;self._retired=None
        self._phase='starting';self._reason=self._error=None;self._last_epoch=None;self._events=deque(maxlen=32)
        self._submitted=self._coalesced=self._discarded=self._native_frames=self._reference_frames=self._fallbacks=0
        self._thread=threading.Thread(target=self._run,name='XPU2-prototype-coordinator',daemon=True);self._thread.start()
    def request(self,manifest,epoch,threads=12,*,experimental_native=False,domain='surface-textures',window_ms=2,fault=0,refill_fine=False,publish_ms=0):
        manifest=Path(manifest)
        if not manifest.is_absolute() or manifest.name!='manifest.json':raise ValueError('Absolute owned asset manifest required')
        if not isinstance(epoch,Epoch) or type(threads) is not int or not 1<=threads<=12:raise ValueError('Epoch and 1..12 workers required')
        if domain not in ('surface-textures','planar-textures','diffuse-mesh'):raise ValueError('Unknown native admission domain')
        if type(window_ms) is not int or not 1<=window_ms<=100:raise ValueError('Window must be 1..100 ms')
        if type(fault) is not int or fault not in (0,1,2) or (fault and not self._test_faults):raise ValueError('Debug fault not enabled')
        if type(experimental_native) is not bool:raise ValueError('Explicit experimental opt-in required')
        if type(refill_fine) is not bool or (refill_fine and not experimental_native):raise ValueError('Fine residency requires explicit native opt-in')
        if type(publish_ms) is not int or not 0<=publish_ms<=1000:raise ValueError('Publish interval must be 0..1000 ms')

        with self._mutex:
            if self._closing or self._closed.is_set():raise RuntimeError('Prototype is closed')
            old=self._last_epoch
            if old is not None and (epoch.session!=old.session or epoch==old or any(getattr(epoch,k)<getattr(old,k) for k in ('scene','camera','settings'))):raise ValueError('Use a new monotonically advancing scene/camera/settings epoch')
            if self._ticket>=(1<<31)-2:raise RuntimeError('Request identity exhausted')
            self._ticket+=1;self._last_epoch=epoch;self._submitted+=1
            if self._pending is not None:self._coalesced+=1
            self._pending=Request(self._ticket,manifest.parent/'scene.rdlb',manifest,epoch,threads,experimental_native,domain,window_ms,fault,refill_fine,publish_ms)
            self._clear();self._error=self._reason=None;self._phase='pending'
            self._events.append((self._ticket,'pending','clear'));ticket=self._ticket
        self._wake.set();return ticket
    def _clear(self):
        if self._frame is not None:self._retired=self._frame
        self._frame=None
    def cancel(self):
        with self._mutex:
            if self._closing or self._closed.is_set():return
            self._ticket+=1;self._pending=None;self._clear();self._phase='cancelling';self._error=self._reason=None
            self._events.append((self._ticket,'cancel','clear'))
        self._wake.set()
    def poll(self):
        with self._mutex:return Status(self._ticket,self._phase,self._frame,self._reason,self._error,tuple(self._events),self._submitted,self._coalesced,self._discarded,self._native_frames,self._reference_frames,self._fallbacks)
    def close(self):
        with self._mutex:self._closing=True;self._pending=None;self._clear()
        self._wake.set()
    def wait_closed(self,timeout):return self._closed.wait(timeout)
    def _current(self,request):
        with self._mutex:return not self._closing and self._ticket==request.ticket
    def _state(self,request,phase,*,error=None,reason=None):
        with self._mutex:
            if self._closing or self._ticket!=request.ticket:return False
            self._phase=phase;self._error=error
            if reason is not None:self._reason=reason
            if phase in ('fallback','failed'):self._clear()
            self._events.append((request.ticket,phase,'clear' if phase in ('fallback','failed') else ''))
            return True
    def _publish(self,request,frame):
        with self._mutex:
            if self._closing or self._ticket!=request.ticket:self._discarded+=1;return
            self._frame=frame;self._phase='finished' if frame.final else 'rendering-native'
            if frame.tier=='F':self._reference_frames+=1
            else:self._native_frames+=1
            if frame.final:self._events.append((request.ticket,'finished',frame.tier))
    def _run(self):
        native=reference=None;active=None;ref_ticket=None;started=0;seen=0;generation=0
        try:
            self.output.mkdir(exist_ok=False,parents=True)
            if set(self._hashes)!=set(('exe','ptx')) or sha(self.exe)!=self._hashes['exe'] or sha(self.ptx)!=self._hashes['ptx']:raise RuntimeError('Prototype binary changed')
            verify(self.runtime,self._runtime_lock,workers=4)
            reference=ReferenceService(self.runtime,self._runtime_lock,self.output/'reference',verify_runtime=lambda root,lock:verify(root,lock,workers=4))
            with self._mutex:
                if self._pending is None:self._phase='idle'
            while True:
                with self._mutex:
                    closing=self._closing;ticket=self._ticket
                    request=self._pending;self._pending=None
                    retired=self._retired;self._retired=None
                del retired # Large buffers retire here, not on the host tick.
                if closing:break
                if ticket!=seen:
                    reference.cancel();ref_ticket=None
                    if native is not None:
                        try:native.cancel(ticket*2-1 if request else ticket*2)
                        except (OSError,ValueError):native.close();native=None
                    seen=ticket;active=request
                    if request is None:
                        with self._mutex:
                            if ticket==self._ticket:self._phase='idle'
                    else:
                        self._state(active,'admitting')
                        try:
                            if asset_snapshot.verify(active.manifest)!=active.scene:raise ValueError('Canonical manifest mismatch')
                            if not self._current(active):continue
                            if active.experimental_native:
                                try:
                                    if native is None:
                                        generation+=1;native=NativeProcess(self.exe,self.runtime,self.ptx,self.output/('native-'+str(generation)),test_faults=self._test_faults)
                                    native.request(active,self.output/('canonical-'+str(active.ticket)))
                                    started=time.monotonic();self._state(active,'rendering-native')
                                except Exception as error:
                                    self._state(active,'fallback',reason='Native startup: '+str(error))
                                    with self._mutex:self._fallbacks+=1
                                    if native is not None:native.close();native=None
                                    if self._current(active):ref_ticket=reference.request(active.scene,active.epoch,active.threads,active.manifest)
                            else:
                                # Retire native GPU resources before starting reference XPU.
                                if native is not None:native.close();native=None
                                ref_ticket=reference.request(active.scene,active.epoch,active.threads,active.manifest)
                                self._state(active,'rendering-reference')
                        except Exception as error:
                            self._state(active,'failed',error=str(error));active=None
                if active is not None and self._current(active):
                    reason=None
                    if ref_ticket is None and native is not None:
                        packet,error=native.poll()
                        if error:reason='Native process failed: '+error
                        elif time.monotonic()-started>self._native_timeout:reason='Native progress exceeded bounded request timeout'
                        if packet is not None:
                            header,data=packet
                            if header.get('id')!=active.ticket*2:
                                with self._mutex:self._discarded+=1
                            elif header.get('epoch')!=asdict(active.epoch):reason='Native epoch mismatch'
                            elif header['kind']=='error':reason=header.get('error','Native request failed')
                            elif header.get('tier')!='D' or header.get('qualified') is not False:reason='Native fidelity tag invalid'
                            else:
                                final=header.get('final')
                                if type(final) is not bool:raise RuntimeError('Native final flag invalid')
                                if final:asset_snapshot.verify(active.manifest)
                                frame=Frame(active.ticket,active.epoch,'D',False,final,header['width'],header['height'],data,
                                    header['min_spp'],header['windows'],header['pending_paths'],gpu_samples=header.get('gpu_samples',0),cpu_samples=header.get('cpu_samples',0),fine_refills=header.get('fine_refills',0),migrated_paths=header.get('migrated_paths',0))
                                self._publish(active,frame)
                                if final:active=None
                    if reason is not None and active is not None:
                        # Clear pixels before retiring native resources. Only the
                        # original frozen package can seed the reference render.
                        if self._state(active,'fallback',reason=reason):
                            with self._mutex:self._fallbacks+=1
                        native.close();native=None
                        if self._current(active):
                            ref_ticket=reference.request(active.scene,active.epoch,active.threads,active.manifest)
                    if active is not None and ref_ticket is not None:
                        state=reference.poll()
                        if state.ticket==ref_ticket:
                            if state.phase=='failed':self._state(active,'failed',error=state.error);active=None
                            elif state.result is not None:
                                if state.result.epoch!=active.epoch or state.result.tier!='F' or state.result.actual_mode!='xpu':raise RuntimeError('Reference identity mismatch')
                                header,data=decode(self.exe,self.runtime,state.result.image,self.output)
                                self._publish(active,Frame(active.ticket,active.epoch,'F',False,True,header['width'],header['height'],data,reference_image=state.result.image))
                                active=None
                self._wake.wait(.002);self._wake.clear()
        except Exception as error:
            with self._mutex:self._phase='failed';self._error=str(error);self._clear()
        finally:
            try:
                if native is not None:native.close()
                if reference is not None:
                    reference.close()
                    if not reference.wait_closed(15):raise RuntimeError('Reference service shutdown timed out')
            except Exception as error:
                with self._mutex:self._error=str(error)
            with self._mutex:
                self._clear()
                if self._closing:self._phase='closed'
            self._closed.set()
