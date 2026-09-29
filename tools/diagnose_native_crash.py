"""Debug only our own smoke-render process to identify unsupported instructions."""
import ctypes as C
from ctypes import wintypes as W
import json
import pathlib
import struct
import subprocess
import sys
import time

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native


class Event(C.Structure):
    _fields_ = [('code', W.DWORD), ('pid', W.DWORD), ('tid', W.DWORD),
                ('padding', W.DWORD), ('data', C.c_ubyte * 160)]


kernel = C.WinDLL('kernel32', use_last_error=True)
kernel.WaitForDebugEvent.argtypes = [C.POINTER(Event), W.DWORD]
kernel.ContinueDebugEvent.argtypes = [W.DWORD, W.DWORD, W.DWORD]
kernel.GetFinalPathNameByHandleW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD]
kernel.CloseHandle.argtypes = [W.HANDLE]
kernel.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
source_port = '--native' in sys.argv
runtime = native.find_runtime(root / ('runtime/native-avx' if source_port else 'runtime'))
out = root / ('test-results/native-render' if source_port else 'test-results')
report = {'modules': [], 'exceptions': []}
modules = {}
with (out / 'debug-render.log').open('w') as log:
    proc = subprocess.Popen([str(runtime / 'moonray.exe')] + native.arguments(out / ('triangle.rdla' if source_port else 'native-smoke.rdla'), out / 'debug-render.png', 1),
                            env=native.environment(runtime), cwd=str(out), stdout=log, stderr=log,
                            creationflags=0x2 | subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            event = Event()
            if not kernel.WaitForDebugEvent(C.byref(event), 1000):
                continue
            data = bytes(event.data)
            disposition = 0x00010002
            if event.code in (3, 6):
                file_handle = struct.unpack_from('<Q', data, 0)[0]
                base = struct.unpack_from('<Q', data, 24 if event.code == 3 else 8)[0]
                path = C.create_unicode_buffer(32768)
                if file_handle and kernel.GetFinalPathNameByHandleW(file_handle, path, len(path), 0):
                    modules[base] = path.value
                if file_handle:
                    kernel.CloseHandle(file_handle)
                if event.code == 3:
                    for offset in (8, 16):
                        handle = struct.unpack_from('<Q', data, offset)[0]
                        if handle:
                            kernel.CloseHandle(handle)
            elif event.code == 1:
                code = struct.unpack_from('<I', data, 0)[0]
                address = struct.unpack_from('<Q', data, 16)[0]
                first = struct.unpack_from('<I', data, 152)[0]
                if code != 0x80000003:
                    disposition = 0x80010001
                if code in (0xc000001d, 0xc0000005, 0xc0000409, 0xc0000374):
                    base = max((base for base in modules if base <= address), default=0)
                    buffer = C.create_string_buffer(32)
                    read = C.c_size_t()
                    kernel.ReadProcessMemory(int(proc._handle), address, buffer, len(buffer), C.byref(read))
                    report['exceptions'].append({'code': hex(code), 'address': hex(address), 'first_chance': first,
                                                 'module': modules.get(base), 'module_offset': hex(address - base),
                                                 'bytes': buffer.raw[:read.value].hex(),
                                                 'parameters': list(struct.unpack_from('<15Q', data, 32))})
            elif event.code == 5:
                report['exit_code'] = hex(struct.unpack_from('<I', data, 0)[0])
                kernel.ContinueDebugEvent(event.pid, event.tid, disposition)
                break
            kernel.ContinueDebugEvent(event.pid, event.tid, disposition)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
report['modules'] = [{'base': hex(k), 'path': v} for k, v in modules.items()]
(out / 'native-crash.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report['exceptions'], indent=2))
print('Exit:', report.get('exit_code'))
