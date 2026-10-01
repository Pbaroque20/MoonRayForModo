"""Debug only a disposable Modo 16.1v9 test process; never attach to user sessions."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import struct
import subprocess
import time

root=Path(__file__).resolve().parents[1]
profile=root/'test-results/gui-pview-release-early'
class Event(C.Structure):
    _fields_=[('code',W.DWORD),('pid',W.DWORD),('tid',W.DWORD),('padding',W.DWORD),('data',C.c_ubyte*160)]
kernel=C.WinDLL('kernel32',use_last_error=True)
kernel.WaitForDebugEvent.argtypes=[C.POINTER(Event),W.DWORD]
kernel.ContinueDebugEvent.argtypes=[W.DWORD,W.DWORD,W.DWORD]
kernel.GetFinalPathNameByHandleW.argtypes=[W.HANDLE,W.LPWSTR,W.DWORD,W.DWORD]
kernel.CloseHandle.argtypes=[W.HANDLE]
report={'exceptions':[]};modules={}
with (root/'test-results/modo-debug.log').open('w') as log:
    process=subprocess.Popen([r'C:\Program Files\Modo16.1v9\modo\modo.exe',
        '-path:user='+str(profile),'-config:'+str(profile/'MODO16.1.CFG'),
        '-cmdlate:@{'+str(root/'tools/probe_pview_kit.py')+'}'],
        stdout=log,stderr=subprocess.STDOUT,creationflags=2)
    try:
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            event=Event()
            if not kernel.WaitForDebugEvent(C.byref(event),1000):continue
            data=bytes(event.data);disposition=0x10002
            if event.code in (3,6):
                handle=struct.unpack_from('<Q',data,0)[0]
                base=struct.unpack_from('<Q',data,24 if event.code==3 else 8)[0]
                path=C.create_unicode_buffer(32768)
                if handle and kernel.GetFinalPathNameByHandleW(handle,path,len(path),0):modules[base]=path.value
                if handle:kernel.CloseHandle(handle)
                if event.code==3:
                    for offset in (8,16):
                        handle=struct.unpack_from('<Q',data,offset)[0]
                        if handle:kernel.CloseHandle(handle)
            elif event.code==1:
                code=struct.unpack_from('<I',data,0)[0]
                address=struct.unpack_from('<Q',data,16)[0]
                first=struct.unpack_from('<I',data,152)[0]
                if code!=0x80000003:disposition=0x80010001
                if code in (0xc0000005,0xc0000374,0xc0000409):
                    base=max((b for b in modules if b<=address),default=0)
                    report['exceptions'].append(dict(code=hex(code),address=hex(address),first_chance=first,
                        module=modules.get(base),offset=hex(address-base),parameters=list(struct.unpack_from('<15Q',data,32))))
            elif event.code==5:
                report['exit']=hex(struct.unpack_from('<I',data,0)[0])
                kernel.ContinueDebugEvent(event.pid,event.tid,disposition)
                break
            kernel.ContinueDebugEvent(event.pid,event.tid,disposition)
    finally:
        if process.poll() is None:process.kill()
        process.wait(timeout=10)
(root/'test-results/modo-debug.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
