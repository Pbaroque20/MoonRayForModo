"""The preview window's memory meter: what the renderer holds, what the machine has free and what the graphics card
holds, read from Windows and the NVIDIA driver once a second, whatever the engine. It turns amber, then red, as the
machine or the card runs short, before a render can take more than there is (a heavy scene once froze the machine)."""
import ctypes
import ctypes.wintypes as w
import os
from PySide2 import QtCore, QtWidgets

GB = 1024.0 ** 3


class _MemoryStatus(ctypes.Structure):
    _fields_ = [('dwLength', w.DWORD), ('dwMemoryLoad', w.DWORD), ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong), ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]


class _ProcessCounters(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('PageFaultCount', w.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t), ('PrivateUsage', ctypes.c_size_t)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]


def machine():
    """The machine's RAM: (total, free) in bytes, or None."""
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys, status.ullAvailPhys
    except (AttributeError, OSError):
        pass
    return None


def process(pid):
    """A process's memory in RAM (its working set) and committed, in bytes, or None where it cannot be read."""
    if not pid:
        return None
    try:
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = w.HANDLE
        handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            counters = _ProcessCounters()
            counters.cb = ctypes.sizeof(counters)
            if not k32.K32GetProcessMemoryInfo(w.HANDLE(handle), ctypes.byref(counters), counters.cb):
                return None
            return counters.WorkingSetSize, counters.PrivateUsage
        finally:
            k32.CloseHandle(w.HANDLE(handle))
    except (AttributeError, OSError):
        return None


class _Card:
    """The NVIDIA driver's NVML (nvml.dll, installed with the driver): the first card's memory, or None without one."""

    def __init__(self):
        self.device = None
        self.name = ''
        try:
            path = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'nvml.dll')
            self.nvml = ctypes.CDLL(path) if os.path.isfile(path) else None
            if self.nvml and self.nvml.nvmlInit_v2() == 0:
                device = ctypes.c_void_p()
                if self.nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(device)) == 0:
                    self.device = device
                    name = ctypes.create_string_buffer(96)
                    if self.nvml.nvmlDeviceGetName(device, name, 96) == 0:
                        self.name = name.value.decode('utf-8', 'replace')
        except (OSError, AttributeError):
            self.device = None

    def memory(self):
        """(total, used) in bytes."""
        if self.device is None:
            return None
        info = _NvmlMemory()
        try:
            if self.nvml.nvmlDeviceGetMemoryInfo(self.device, ctypes.byref(info)) == 0:
                return info.total, info.used
        except OSError:
            pass
        return None


_CARD = None


def card():
    global _CARD
    if _CARD is None:
        _CARD = _Card()
    return _CARD


def _level(short):
    # 0 fine, 1 short (amber), 2 very short (red)
    return 2 if short >= 2 else 1 if short >= 1 else 0


COLOURS = {0: '', 1: '#d9a13b', 2: '#e0533d'}


class MemoryMeter(QtWidgets.QLabel):
    """The meter: renderer, RAM free and GPU, its colour the worst of them. processes() gives the renderer's processes'
    ids (none running: the renderer is left out)."""

    def __init__(self, processes, parent=None):
        super().__init__(parent)
        self.processes = processes
        self.setEnabled(False)
        self.setTextFormat(QtCore.Qt.RichText)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        parts, notes, worst = [], [], 0
        pids = [p for p in (self.processes() or []) if p]
        held = [m for m in (process(p) for p in pids) if m]
        if held:
            resident = sum(m[0] for m in held)
            committed = sum(m[1] for m in held)
            parts.append('Renderer %.1f GB' % (resident / GB))
            notes.append('The renderer holds %.1f GB of RAM (%.1f GB committed: what it has asked Windows for, including what the graphics driver '
                         'keeps in reserve for the card).' % (resident / GB, committed / GB))
        ram = machine()
        if ram:
            total, free = ram
            share = free / total if total else 1.0
            level = _level(2 if share < 0.08 else 1 if share < 0.15 else 0)
            worst = max(worst, level)
            text = 'RAM %.0f GB free' % (free / GB)
            parts.append('<span style="color:%s">%s</span>' % (COLOURS[level], text) if level else text)
            notes.append('The machine has %.1f GB of its %.0f GB of RAM free.' % (free / GB, total / GB))
        gpu = card().memory()
        if gpu:
            total, used = gpu
            share = used / total if total else 0.0
            level = _level(2 if share > 0.95 else 1 if share > 0.85 else 0)
            worst = max(worst, level)
            text = 'GPU %.1f/%.0f GB' % (used / GB, total / GB)
            parts.append('<span style="color:%s">%s</span>' % (COLOURS[level], text) if level else text)
            notes.append('The graphics card%s holds %.1f GB of its %.0f GB (every program on it, Modo\'s viewport too).' % (
                ' (' + card().name + ')' if card().name else '', used / GB, total / GB))
        if worst:
            notes.append('Memory is running short: a render that needs more may slow the machine or fall back.')
        self.setText(' \u00b7 '.join(parts))
        self.setToolTip('\n'.join(notes))
        # Shown in full colour when short, dimmed like the picture's details otherwise.
        self.setEnabled(bool(worst))
