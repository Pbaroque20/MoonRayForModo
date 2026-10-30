"""debug_modo.py [--launch | --pid N] [--exe path] [--args ...] [--env K=V ...]: a small Windows debugger for Modo's crash,
in place of gdb (whose JIT breakpoint on nvgpucomp64.dll's __jit_debug_register_code itself ended Modo with 0x80000003).

It sets no breakpoints of its own. On an access violation, a heap corruption report, a fast fail, an illegal
instruction or a breakpoint in the process, it writes the faulting thread's call stack (dbghelp's StackWalk64 with the
modules' unwind tables and exported names) to test-results/xpu2-cl/modo-debug-<time>.log; on one the process will not
survive (second chance), every thread's stack and a minidump (modo-debug-<time>.dmp). It also writes what the process
sends to a debugger (OutputDebugString: Windows' heap reports its corruption so).

--launch starts Modo under it: Windows then gives Modo its debug heap (freed blocks filled, block tails checked), which
reports a bad free or a write past a block where it happens instead of later; slower allocation. Without --launch it
attaches to the running Modo (no debug heap). Ending this script (Ctrl+C) detaches and leaves Modo running."""
import argparse
import ctypes
import ctypes.wintypes as w
import os
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODO = Path(r'C:\Program Files\Modo16.1v9\modo\modo.exe')
p = argparse.ArgumentParser()
p.add_argument('--launch', action='store_true')
p.add_argument('--pid', type=int, default=0)
p.add_argument('--exe', default=str(MODO))
p.add_argument('--args', default='')
p.add_argument('--env', action='append', default=[])
p.add_argument('--log', default='')
p.add_argument('--first-chance', type=int, default=40, help='stacks written for first-chance faults (then only counted)')
a = p.parse_args()

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
dbg = ctypes.WinDLL(r'C:\Windows\System32\dbghelp.dll', use_last_error=True)
HANDLE, PVOID, DWORD, DWORD64 = w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.c_uint64


class EXCEPTION_RECORD(ctypes.Structure):
    _fields_ = [('ExceptionCode', DWORD), ('ExceptionFlags', DWORD), ('ExceptionRecord', PVOID), ('ExceptionAddress', PVOID),
                ('NumberParameters', DWORD), ('ExceptionInformation', ctypes.c_uint64 * 15)]


class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('ExceptionRecord', EXCEPTION_RECORD), ('dwFirstChance', DWORD)]


class CREATE_THREAD_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('hThread', HANDLE), ('lpThreadLocalBase', PVOID), ('lpStartAddress', PVOID)]


class CREATE_PROCESS_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('hFile', HANDLE), ('hProcess', HANDLE), ('hThread', HANDLE), ('lpBaseOfImage', PVOID), ('dwDebugInfoFileOffset', DWORD),
                ('nDebugInfoSize', DWORD), ('lpThreadLocalBase', PVOID), ('lpStartAddress', PVOID), ('lpImageName', PVOID), ('fUnicode', w.WORD)]


class LOAD_DLL_DEBUG_INFO(ctypes.Structure):
    _fields_ = [('hFile', HANDLE), ('lpBaseOfDll', PVOID), ('dwDebugInfoFileOffset', DWORD), ('nDebugInfoSize', DWORD), ('lpImageName', PVOID),
                ('fUnicode', w.WORD)]


class OUTPUT_DEBUG_STRING_INFO(ctypes.Structure):
    _fields_ = [('lpDebugStringData', PVOID), ('fUnicode', w.WORD), ('nDebugStringLength', w.WORD)]


class EXIT_INFO(ctypes.Structure):
    _fields_ = [('dwExitCode', DWORD)]


class U(ctypes.Union):
    _fields_ = [('Exception', EXCEPTION_DEBUG_INFO), ('CreateThread', CREATE_THREAD_DEBUG_INFO), ('CreateProcessInfo', CREATE_PROCESS_DEBUG_INFO),
                ('Exit', EXIT_INFO), ('LoadDll', LOAD_DLL_DEBUG_INFO), ('DebugString', OUTPUT_DEBUG_STRING_INFO)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [('dwDebugEventCode', DWORD), ('dwProcessId', DWORD), ('dwThreadId', DWORD), ('u', U)]


class ADDRESS64(ctypes.Structure):
    _fields_ = [('Offset', DWORD64), ('Segment', w.WORD), ('Mode', DWORD)]


class STACKFRAME64(ctypes.Structure):
    _fields_ = [('AddrPC', ADDRESS64), ('AddrReturn', ADDRESS64), ('AddrFrame', ADDRESS64), ('AddrStack', ADDRESS64), ('AddrBStore', ADDRESS64),
                ('FuncTableEntry', PVOID), ('Params', DWORD64 * 4), ('Far', w.BOOL), ('Virtual', w.BOOL), ('Reserved', DWORD64 * 3),
                ('KdHelp', ctypes.c_ubyte * 512)]


class EXCEPTION_POINTERS(ctypes.Structure):
    _fields_ = [('ExceptionRecord', PVOID), ('ContextRecord', PVOID)]


class MINIDUMP_EXCEPTION_INFORMATION(ctypes.Structure):
    _pack_ = 4
    _fields_ = [('ThreadId', DWORD), ('ExceptionPointers', PVOID), ('ClientPointers', w.BOOL)]


class STARTUPINFO(ctypes.Structure):
    _fields_ = [('cb', DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR), ('lpTitle', w.LPWSTR), ('dwX', DWORD), ('dwY', DWORD),
                ('dwXSize', DWORD), ('dwYSize', DWORD), ('dwXCountChars', DWORD), ('dwYCountChars', DWORD), ('dwFillAttribute', DWORD),
                ('dwFlags', DWORD), ('wShowWindow', w.WORD), ('cbReserved2', w.WORD), ('lpReserved2', PVOID), ('hStdInput', HANDLE),
                ('hStdOutput', HANDLE), ('hStdError', HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', HANDLE), ('hThread', HANDLE), ('dwProcessId', DWORD), ('dwThreadId', DWORD)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('nLength', DWORD), ('lpSecurityDescriptor', PVOID), ('bInheritHandle', w.BOOL)]


k32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), DWORD]
k32.ContinueDebugEvent.argtypes = [DWORD, DWORD, DWORD]
k32.DebugActiveProcess.argtypes = [DWORD]
k32.DebugActiveProcessStop.argtypes = [DWORD]
k32.DebugSetProcessKillOnExit.argtypes = [w.BOOL]
k32.GetThreadContext.argtypes = [HANDLE, PVOID]
k32.ReadProcessMemory.argtypes = [HANDLE, PVOID, PVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.K32GetModuleFileNameExW.argtypes = [HANDLE, PVOID, w.LPWSTR, DWORD]
k32.OpenThread.argtypes = [DWORD, w.BOOL, DWORD]
k32.OpenThread.restype = HANDLE
k32.CloseHandle.argtypes = [HANDLE]
k32.CreateFileW.argtypes = [w.LPCWSTR, DWORD, DWORD, PVOID, DWORD, DWORD, HANDLE]
k32.CreateFileW.restype = HANDLE
k32.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, PVOID, PVOID, w.BOOL, DWORD, PVOID, w.LPCWSTR, ctypes.POINTER(STARTUPINFO),
                               ctypes.POINTER(PROCESS_INFORMATION)]
dbg.SymSetOptions.argtypes = [DWORD]
dbg.SymInitializeW.argtypes = [HANDLE, w.LPCWSTR, w.BOOL]
dbg.SymRefreshModuleList.argtypes = [HANDLE]
dbg.SymGetModuleBase64.argtypes = [HANDLE, DWORD64]
dbg.SymGetModuleBase64.restype = DWORD64
dbg.SymFromAddr.argtypes = [HANDLE, DWORD64, ctypes.POINTER(DWORD64), PVOID]
dbg.StackWalk64.argtypes = [DWORD, HANDLE, HANDLE, ctypes.POINTER(STACKFRAME64), PVOID, PVOID, PVOID, PVOID, PVOID]
dbg.MiniDumpWriteDump.argtypes = [HANDLE, DWORD, HANDLE, DWORD, PVOID, PVOID, PVOID]

DBG_CONTINUE, DBG_EXCEPTION_NOT_HANDLED = 0x00010002, 0x80010001
CONTEXT_ALL = 0x10001F
NAMES = {0xC0000005: 'access violation', 0xC0000374: 'heap corruption', 0xC0000409: 'fast fail / stack buffer overrun', 0xC000001D: 'illegal instruction',
         0x80000003: 'breakpoint', 0xC00000FD: 'stack overflow', 0xC0000096: 'privileged instruction', 0xC0000420: 'assertion failure',
         0xC0000602: 'fail fast', 0x80000004: 'single step'}
WATCHED = set(NAMES) - {0x80000004}

stamp = time.strftime('%Y%m%d-%H%M%S')
log_path = Path(a.log) if a.log else HERE / ('modo-debug-%s.log' % stamp)
out = log_path.open('a', encoding='utf-8', buffering=1)


def say(*parts):
    line = ' '.join(str(x) for x in parts)
    out.write(line + '\n')
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        pass  # no console left: the log has it


process = None
pid = 0
threads = {}
modules = {}
sym_ready = False
first_chance_written = 0
counts = {}
initial_break = True


def ensure_symbols():
    global sym_ready
    if not sym_ready:
        dbg.SymSetOptions(0x2 | 0x4 | 0x10 | 0x200 | 0x80000)  # undname, deferred loads, lines, no critical errors, no prompts
        sym_ready = bool(dbg.SymInitializeW(process, None, True))
    else:
        dbg.SymRefreshModuleList(process)


def module_name(base):
    if base not in modules:
        buf = ctypes.create_unicode_buffer(520)
        modules[base] = os.path.basename(buf.value) if k32.K32GetModuleFileNameExW(process, PVOID(base), buf, 520) else '?'
    return modules[base]


def where(addr):
    base = dbg.SymGetModuleBase64(process, addr)
    mod = module_name(base) if base else '?'
    info = ctypes.create_string_buffer(88 + 1024)
    struct.pack_into('<I', info, 0, 88)
    struct.pack_into('<I', info, 80, 1000)
    disp = DWORD64(0)
    if dbg.SymFromAddr(process, addr, ctypes.byref(disp), info):
        name = info.raw[84:84 + struct.unpack_from('<I', info, 76)[0]].decode('latin-1')
        return '%s!%s+0x%x' % (mod, name, disp.value) if base else '%s+0x%x' % (name, disp.value)
    return '%s+0x%x' % (mod, addr - base) if base else '0x%x' % addr


def context_of(handle):
    raw = ctypes.create_string_buffer(1232 + 16)
    addr = (ctypes.addressof(raw) + 15) & ~15
    ctypes.memmove(addr + 0x30, struct.pack('<I', CONTEXT_ALL), 4)
    if not k32.GetThreadContext(handle, PVOID(addr)):
        return None, None
    return raw, addr


def stack(tid, limit=48):
    handle = threads.get(tid)
    if not handle:
        return ['  (no handle for thread %d)' % tid]
    raw, ctx = context_of(handle)
    if ctx is None:
        return ['  (no context for thread %d: error %d)' % (tid, ctypes.get_last_error())]
    rip, rsp, rbp = (struct.unpack_from('<Q', ctypes.string_at(ctx + off, 8))[0] for off in (0xF8, 0x98, 0xA0))
    frame = STACKFRAME64()
    frame.AddrPC.Offset, frame.AddrPC.Mode = rip, 3
    frame.AddrStack.Offset, frame.AddrStack.Mode = rsp, 3
    frame.AddrFrame.Offset, frame.AddrFrame.Mode = rbp, 3
    lines = []
    access = ctypes.cast(dbg.SymFunctionTableAccess64, PVOID)
    base = ctypes.cast(dbg.SymGetModuleBase64, PVOID)
    for i in range(limit):
        if not dbg.StackWalk64(0x8664, process, handle, ctypes.byref(frame), PVOID(ctx), None, access, base, None):
            break
        pc = frame.AddrPC.Offset
        if not pc:
            break
        lines.append('  #%-2d 0x%016x %s' % (i, pc, where(pc)))
    return lines or ['  (empty stack, rip 0x%x)' % rip]


def minidump(tid, record_addr, ctx_raw_addr):
    path = log_path.with_suffix('.dmp')
    h = k32.CreateFileW(str(path), 0x40000000, 0, None, 2, 0x80, None)
    if h in (None, HANDLE(-1).value):
        say('  minidump: cannot create', path)
        return
    pointers = EXCEPTION_POINTERS(record_addr, ctx_raw_addr)
    info = MINIDUMP_EXCEPTION_INFORMATION(tid, ctypes.addressof(pointers), False)
    kinds = 0x4 | 0x20 | 0x40 | 0x100 | 0x800 | 0x1000
    ok = dbg.MiniDumpWriteDump(process, pid, h, kinds, ctypes.byref(info), None, None)
    k32.CloseHandle(h)
    say('  minidump:', path if ok else 'failed (error %d)' % ctypes.get_last_error())


def read_string(info):
    n = info.nDebugStringLength
    if not n or not info.lpDebugStringData:
        return ''
    size = n * (2 if info.fUnicode else 1)
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(process, PVOID(info.lpDebugStringData), buf, size, ctypes.byref(got)):
        return '(unreadable)'
    data = buf.raw[:got.value]
    return (data.decode('utf-16-le', 'replace') if info.fUnicode else data.decode('mbcs', 'replace')).rstrip('\0\r\n')


def on_exception(ev):
    global first_chance_written, initial_break
    info = ev.u.Exception
    rec = info.ExceptionRecord
    code = rec.ExceptionCode & 0xFFFFFFFF
    addr = rec.ExceptionAddress or 0
    first = bool(info.dwFirstChance)
    if code == 0x80000003 and initial_break:
        initial_break = False
        say('[%s] attached (initial breakpoint, thread %d)' % (time.strftime('%H:%M:%S'), ev.dwThreadId))
        return DBG_CONTINUE
    if code not in WATCHED:
        return DBG_EXCEPTION_NOT_HANDLED
    counts[(code, first)] = counts.get((code, first), 0) + 1
    ensure_symbols()
    detail = ''
    if code == 0xC0000005 and rec.NumberParameters >= 2:
        detail = ' (%s 0x%x)' % ({0: 'reading', 1: 'writing', 8: 'executing'}.get(rec.ExceptionInformation[0], '?'), rec.ExceptionInformation[1])
    if code == 0xC0000409 and rec.NumberParameters >= 1:
        detail = ' (fast fail code %d)' % rec.ExceptionInformation[0]
    fatal = not first
    if first and first_chance_written >= a.first_chance and code != 0x80000003:
        return DBG_EXCEPTION_NOT_HANDLED
    say('\n[%s] ==== %s%s, %s chance, thread %d, at %s ====' % (time.strftime('%H:%M:%S'), NAMES[code], detail, 'first' if first else 'SECOND',
                                                               ev.dwThreadId, where(addr)))
    for line in stack(ev.dwThreadId):
        say(line)
    if first:
        first_chance_written += 1
    if fatal or code in (0xC0000374, 0xC0000409, 0xC0000602):
        say('---- every thread ----')
        for tid in list(threads):
            if tid == ev.dwThreadId:
                continue
            say(' thread %d' % tid)
            for line in stack(tid, 24):
                say(line)
        handle = threads.get(ev.dwThreadId)
        raw, ctx = context_of(handle) if handle else (None, None)
        record = EXCEPTION_RECORD.from_buffer_copy(bytes(rec))
        if ctx is not None:
            minidump(ev.dwThreadId, ctypes.addressof(record), ctx)
    if code == 0x80000003:
        # A break into the debugger (ntdll's heap reports, DebugBreak): carried on from as a debugger would; one
        # elsewhere goes to the process's own handler as without a debugger.
        base = dbg.SymGetModuleBase64(process, addr)
        return DBG_CONTINUE if base and module_name(base).lower() == 'ntdll.dll' else DBG_EXCEPTION_NOT_HANDLED
    return DBG_EXCEPTION_NOT_HANDLED


def launch():
    global process, pid
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONHOME', 'PYTHONPATH')}
    # Python's own fault handler: on a crash, every Python thread's traceback, written to the process's stderr (the
    # .out file beside the log), so a native stack in python39 or shiboken2 comes with the kit code that ran it.
    env['PYTHONFAULTHANDLER'] = '1'
    env.update(dict(v.split('=', 1) for v in a.env))
    block = ''.join('%s=%s\0' % kv for kv in sorted(env.items())) + '\0'
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    stdout = k32.CreateFileW(str(log_path.with_suffix('.out')), 0x40000000, 0x1 | 0x2, ctypes.byref(sa), 2, 0x80, None)
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = 0x100  # STARTF_USESTDHANDLES
    si.hStdOutput = si.hStdError = stdout
    pi = PROCESS_INFORMATION()
    exe = a.exe
    cmd = ctypes.create_unicode_buffer('"%s" %s' % (exe, a.args))
    if not k32.CreateProcessW(exe, cmd, None, None, True, 0x2 | 0x400, ctypes.create_unicode_buffer(block), str(Path(exe).parent),
                              ctypes.byref(si), ctypes.byref(pi)):
        sys.exit('CreateProcess failed: %d' % ctypes.get_last_error())
    k32.CloseHandle(stdout)
    pid = pi.dwProcessId
    k32.CloseHandle(pi.hThread)
    k32.CloseHandle(pi.hProcess)
    say('started %s, process %d, under the debugger (debug heap %s); its output in %s' % (
        exe, pid, 'off' if env.get('_NO_DEBUG_HEAP') == '1' else 'on', log_path.with_suffix('.out')))


def modo_pid():
    import subprocess
    listed = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq modo.exe', '/FO', 'CSV', '/NH'], capture_output=True, text=True).stdout
    for line in listed.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if parts and parts[0].lower() == 'modo.exe':
            return int(parts[1])
    return 0


if a.launch:
    launch()
else:
    pid = a.pid or modo_pid()
    if not pid:
        sys.exit('Modo is not running')
    if not k32.DebugActiveProcess(pid):
        sys.exit('DebugActiveProcess failed: %d' % ctypes.get_last_error())
    say('attaching to process', pid)
k32.DebugSetProcessKillOnExit(False)
ev = DEBUG_EVENT()
try:
    while True:
        if not k32.WaitForDebugEvent(ctypes.byref(ev), 500):
            continue
        status = DBG_CONTINUE
        code = ev.dwDebugEventCode
        if code == 3:
            ci = ev.u.CreateProcessInfo
            process = ci.hProcess
            threads[ev.dwThreadId] = ci.hThread
            if ci.hFile:
                k32.CloseHandle(ci.hFile)
        elif code == 2:
            threads[ev.dwThreadId] = ev.u.CreateThread.hThread
        elif code == 4:
            threads.pop(ev.dwThreadId, None)
        elif code == 6:
            if ev.u.LoadDll.hFile:
                k32.CloseHandle(ev.u.LoadDll.hFile)
        elif code == 8:
            text = read_string(ev.u.DebugString)
            if text:
                say('[%s] debug output: %s' % (time.strftime('%H:%M:%S'), text[:2000]))
        elif code == 1:
            status = on_exception(ev)
        elif code == 5:
            say('[%s] process exited, code 0x%08x' % (time.strftime('%H:%M:%S'), ev.u.Exit.dwExitCode & 0xFFFFFFFF))
            k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)
            break
        k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, status)
except KeyboardInterrupt:
    k32.DebugActiveProcessStop(pid)
    say('detached; the process goes on')
finally:
    if counts:
        say('faults seen:', ', '.join('%s %s x%d' % (NAMES[c], 'first' if f else 'second', n) for (c, f), n in sorted(counts.items())))
    out.close()
