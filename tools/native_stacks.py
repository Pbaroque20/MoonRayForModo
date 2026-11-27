"""Each thread's native stack of a running process, as module+offset, without attaching a debugger (gdb kills Modo:
memory modo-crash-debugging). Each thread is suspended a moment, its registers read, and its stack memory scanned for
addresses inside loaded modules (likely return addresses; a scan, not an unwind, so some are stale). Run with a 64-bit
Python: native_stacks.py PID [--words N] [--out FILE]."""
import argparse
import ctypes
import ctypes.wintypes as w
import sys

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL = 0x0010 | 0x0400 | 0x0008  # VM_READ | QUERY_INFORMATION | VM_OPERATION
THREAD_ALL = 0x0002 | 0x0008 | 0x0040  # SUSPEND_RESUME | GET_CONTEXT | QUERY_INFORMATION
TH32CS_SNAPTHREAD = 0x4
CONTEXT_FULL = 0x10000B


class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ThreadID', w.DWORD), ('th32OwnerProcessID', w.DWORD),
                ('tpBasePri', w.LONG), ('tpDeltaPri', w.LONG), ('dwFlags', w.DWORD)]


class M128(ctypes.Structure):
    _fields_ = [('lo', ctypes.c_uint64), ('hi', ctypes.c_int64)]


class CONTEXT(ctypes.Structure):
    _pack_ = 16
    _fields_ = [('P1Home', ctypes.c_uint64), ('P2Home', ctypes.c_uint64), ('P3Home', ctypes.c_uint64), ('P4Home', ctypes.c_uint64),
                ('P5Home', ctypes.c_uint64), ('P6Home', ctypes.c_uint64), ('ContextFlags', w.DWORD), ('MxCsr', w.DWORD),
                ('SegCs', w.WORD), ('SegDs', w.WORD), ('SegEs', w.WORD), ('SegFs', w.WORD), ('SegGs', w.WORD), ('SegSs', w.WORD),
                ('EFlags', w.DWORD), ('Dr0', ctypes.c_uint64), ('Dr1', ctypes.c_uint64), ('Dr2', ctypes.c_uint64),
                ('Dr3', ctypes.c_uint64), ('Dr6', ctypes.c_uint64), ('Dr7', ctypes.c_uint64)] + \
               [(r, ctypes.c_uint64) for r in ('Rax', 'Rcx', 'Rdx', 'Rbx', 'Rsp', 'Rbp', 'Rsi', 'Rdi', 'R8', 'R9', 'R10', 'R11',
                                                'R12', 'R13', 'R14', 'R15', 'Rip')] + \
               [('FltSave', ctypes.c_byte * 512), ('VectorRegister', M128 * 26), ('VectorControl', ctypes.c_uint64),
                ('DebugControl', ctypes.c_uint64), ('LastBranchToRip', ctypes.c_uint64), ('LastBranchFromRip', ctypes.c_uint64),
                ('LastExceptionToRip', ctypes.c_uint64), ('LastExceptionFromRip', ctypes.c_uint64)]


class MODULEINFO(ctypes.Structure):
    _fields_ = [('lpBaseOfDll', ctypes.c_void_p), ('SizeOfImage', w.DWORD), ('EntryPoint', ctypes.c_void_p)]


def modules(process):
    handles = (ctypes.c_void_p * 2048)()
    needed = w.DWORD()
    psapi.EnumProcessModulesEx(process, handles, ctypes.sizeof(handles), ctypes.byref(needed), 3)
    found = []
    for h in handles[:needed.value // ctypes.sizeof(ctypes.c_void_p)]:
        info = MODULEINFO()
        name = ctypes.create_unicode_buffer(260)
        psapi.GetModuleInformation(process, ctypes.c_void_p(h), ctypes.byref(info), ctypes.sizeof(info))
        psapi.GetModuleBaseNameW(process, ctypes.c_void_p(h), name, 260)
        found.append((info.lpBaseOfDll or 0, info.SizeOfImage, name.value))
    return sorted(found)


def where(address, listed):
    for base, size, name in listed:
        if base <= address < base + size:
            return '%s+0x%x' % (name, address - base)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid', type=int)
    parser.add_argument('--words', type=int, default=4096)
    parser.add_argument('--out')
    args = parser.parse_args()
    process = k32.OpenProcess(PROCESS_ALL, False, args.pid)
    if not process:
        raise SystemExit('cannot open process %d (%d)' % (args.pid, ctypes.get_last_error()))
    listed = modules(process)
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    threads = []
    ok = k32.Thread32First(snap, ctypes.byref(entry))
    while ok:
        if entry.th32OwnerProcessID == args.pid:
            threads.append(entry.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    lines = []
    for tid in threads:
        thread = k32.OpenThread(THREAD_ALL, False, tid)
        if not thread:
            continue
        k32.SuspendThread(thread)
        try:
            buffer = ctypes.create_string_buffer(ctypes.sizeof(CONTEXT) + 16)
            offset = (-ctypes.addressof(buffer)) % 16
            context = CONTEXT.from_buffer(buffer, offset)
            context.ContextFlags = CONTEXT_FULL
            if not k32.GetThreadContext(thread, ctypes.byref(context)):
                lines.append('thread %d: no context (%d)' % (tid, ctypes.get_last_error()))
                continue
            rip, rsp = context.Rip, context.Rsp
            # Read page by page up to the stack's top: one read past it fails whole.
            values = []
            at = rsp
            while len(values) < args.words:
                end = min((at // 4096 + 1) * 4096, at + 8 * (args.words - len(values)))
                chunk = (ctypes.c_uint64 * ((end - at) // 8))()
                got = ctypes.c_size_t()
                if not k32.ReadProcessMemory(process, ctypes.c_void_p(at), chunk, ctypes.sizeof(chunk), ctypes.byref(got)) or not got.value:
                    break
                values.extend(chunk[:got.value // 8])
                at = end
        finally:
            k32.ResumeThread(thread)
            k32.CloseHandle(thread)
        frames = [where(rip, listed) or hex(rip)]
        for value in values:
            at = where(value, listed)
            if at and at != frames[-1]:
                frames.append(at)
        lines.append('thread %d:\n  ' % tid + '\n  '.join(frames[:60]))
    text = '\n'.join(lines)
    if args.out:
        open(args.out, 'w').write(text)
    print(text)


if __name__ == '__main__':
    sys.exit(main())
