"""XPU2: compiling its GPU programs into OptiX's cache, and what state they are in."""
import os
import sys
package_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python")
if package_root not in sys.path: sys.path.insert(0, package_root)
import lx
import lxu.command
from moonray_modo.property_notifications import Followed


def _running(pid):
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle: return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259




UP_TO_DATE = 'Up to date'
# How long a press says Compiling at the least, in seconds: with OptiX's cache holding the programs a compile is over in a
# second, before the form next looks, and the press seemed to do nothing.
SHOWN_AT_LEAST = 3.0
# When the button was last pressed.
_pressed = [None]


def button_name(held):
    """The button, named for what it does now, by the shaders' state: compiling, it says so; up to date, the shaders can
    only be compiled again."""
    if held.startswith('Compiling'): return 'Compiling XPU2 Shaders...'
    return 'Re-compile XPU2 Shaders' if held == UP_TO_DATE else 'Compile XPU2 Shaders'


def compiled():
    """Whether XPU2's runtime finds its mark of compiled shaders (native.xpu2_shaders_compiled)."""
    from moonray_modo import native
    return native.xpu2_shaders_compiled()


def _counts(lines):
    """The log's last count of tasks ("N compile tasks done, M waiting, T s", every ten seconds): (done, waiting,
    seconds), or None before the first."""
    for line in reversed(lines):
        words = line.replace(',', ' ').split()
        if 'tasks' in words and 'done' in words and 'waiting' in words:
            try:
                return (int(words[words.index('tasks') - 2]), int(words[words.index('waiting') - 1]),
                        float(words[words.index('waiting') + 1]) if len(words) > words.index('waiting') + 1 else 0.0)
            except (ValueError, IndexError):
                return None
    return None


def _progress(lines):
    """How far a compile has come, in percent; None before the first count."""
    counts = _counts(lines)
    if counts is None or not counts[0] + counts[1]:
        return None
    return int(100 * counts[0] / (counts[0] + counts[1]))


def _minutes(seconds):
    return '%d min' % max(1, round(seconds / 60.0)) if seconds >= 60 else '%d s' % max(1, round(seconds))


def last_compile():
    """How long the last whole compile took on this machine, in seconds (kept beside the log as it ends), or None."""
    from moonray_modo import native
    try:
        return float(native.xpu2_shaders_log().with_suffix('.took').read_text().strip())
    except (OSError, ValueError):
        return None


def how_long():
    """What a message says of how long a compile takes: the last one here, or that the state shows it as it goes."""
    took = last_compile()
    return 'it took %s here last time' % _minutes(took) if took else 'how long it has left shows as it goes'


def _keep_took(lines):
    """A finished compile's time ("compiled in T s") kept beside the log, for the next messages."""
    from moonray_modo import native
    for line in reversed(lines):
        if 'compiled in' in line:
            try:
                seconds = float(line.split('compiled in', 1)[1].split()[0])
                native.xpu2_shaders_log().with_suffix('.took').write_text('%.0f' % seconds)
            except (OSError, ValueError, IndexError):
                pass
            return


def state():
    """The shaders' state in a few words: compiling (how far, from the compile's log), compiled, or not."""
    from moonray_modo import native
    log = native.xpu2_shaders_log()
    pid = log.with_suffix('.pid')
    try: lines = [l for l in log.read_text(encoding='utf-8', errors='replace').splitlines() if l.strip()]
    except OSError: lines = []
    try: compiling = _running(pid.read_text().strip())
    except (OSError, ValueError): compiling = False
    last = lines[-1] if lines else ''
    import time
    if compiling or (_pressed[0] is not None and time.monotonic() - _pressed[0] < SHOWN_AT_LEAST):
        # How far, in percent of its compile tasks: 0% from the moment it starts (asked 2026-10-30: the state changes at
        # once, no message box).
        counts = _counts(lines)
        if counts is None or not counts[0] + counts[1]:
            return 'Compiling 0%'
        done, waiting, seconds = counts
        return 'Compiling %d%%' % int(100 * done / (done + waiting))
    _keep_took(lines)
    # For these programs and this graphics driver, or for others (asked 2026-10-31: "compiled" did not say which).
    from moonray_modo import native
    held, why = native.xpu2_shaders_state()
    if held == 'current': return UP_TO_DATE
    if held == 'stale': return 'Out of date' + (' (%s)' % why if why else '')
    # Memory (the compile's guard, asked 2026-11-07): not begun for want of free memory, or stopped as it ran low.
    tail = ' '.join(lines[-3:])
    if 'not enough free memory' in tail: return 'Not compiled (needs more free memory: close other programs)'
    if 'memory ran low' in tail: return 'Stopped (memory ran low: close other programs, compile again)'
    # Just that (asked 2026-10-30); why a compile failed is in its log and the Render Log.
    return 'Not compiled'


import lxifc

# The form's own notifier: told while the shaders compile, it asks the form to look again at the button and the
# shaders' state (how far along, then Up to date and Re-compile).
NOTIFIER = 'moonray.xpu2.shaders'


class ShadersNotifier(lxifc.Notifier):
    clients = {}
    def noti_Name(self): return NOTIFIER
    def noti_SetArgs(self, args): pass
    def noti_Args(self): return ''
    def noti_AddClient(self, event): self.clients[event.__peekobj__()] = event
    def noti_RemoveClient(self, event): self.clients.pop(event.__peekobj__(), None)


def _notify():
    for event in list(ShadersNotifier.clients.values()):
        try: lx.object.CommandEvent(event).Event(lx.symbol.fCMDNOTIFY_CHANGE_ALL)
        except (RuntimeError, LookupError): pass


_ticking = []


def _tick():
    """While the shaders compile, the form told every two seconds; once more as they are done, and the watch ended."""
    if not state().startswith('Compiling'):
        for timer in _ticking: timer.stop()
        del _ticking[:]
        from moonray_modo import native
        native._shaders_asked[1] = None    # whether they are compiled, asked again at once
    _notify()


def _watch():
    """Follow a compile under way (started here, or still running from before Modo was opened)."""
    if _ticking: return
    try:
        from PySide2 import QtCore
    except ImportError:
        return
    timer = QtCore.QTimer()
    timer.setInterval(2000)
    timer.timeout.connect(_tick)
    timer.start()
    _ticking.append(timer)


class CompileShaders(Followed, lxu.command.BasicCommand):
    """Compile XPU2's GPU programs into OptiX's disk cache in the background, once (the state says how long it has left),
    after which every XPU2 preview starts in seconds. Modo stays usable meanwhile."""
    WATCHED = ((NOTIFIER, ''),)
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    # Greyed while a compile is under way: pressed again, it would only start another.
    def basic_Enable(self, msg): return not state().startswith('Compiling')
    def basic_ButtonName(self): return button_name(state())
    def basic_Execute(self, msg, flags):
        import subprocess
        from moonray_modo import native
        exe = native.xpu2_runtime() / 'moonray_xpu2.exe'
        if not exe.is_file():
            lx.out('MoonRay XPU2: no runtime-xpu2 in this kit'); return
        if state().startswith('Compiling'):
            lx.out('MoonRay XPU2: the shaders are compiling already'); return
        log = native.xpu2_shaders_log(); log.parent.mkdir(parents=True, exist_ok=True)
        import time
        _pressed[0] = time.monotonic()
        env = dict(os.environ)
        env.update(native.xpu2_environment(native.default_runtime()))
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'): env.pop(key, None)
        with open(log, 'w', encoding='utf-8') as out:
            process = subprocess.Popen([str(exe), '--compile-shaders'], cwd=str(exe.parent), env=env, stdout=out,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       creationflags=0x00000008 | 0x08000000 | 0x00004000)  # detached, no window, below normal
        log.with_suffix('.pid').write_text(str(process.pid))
        native._shaders_asked[1] = None
        _watch()
        _notify()
        lx.out('MoonRay XPU2: compiling the shaders in the background (%s); see %s' % (how_long(), log))


class ShaderState(Followed, lxu.command.BasicCommand):
    """The state of XPU2's shaders (read only)."""
    WATCHED = ((NOTIFIER, ''),)
    def __init__(self):
        super().__init__()
        self.dyna_Add('value', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def cmd_Query(self, index, query):
        held = state()
        # A compile found under way (one still running from before Modo was opened) is followed from here.
        if held.startswith('Compiling'): _watch()
        lx.object.ValueArray(query).AddString(held)
    def basic_Execute(self, msg, flags): pass


# The compile's memory, shown beside the button (asked 2026-11-08: whether the machine has enough free to compile).
# The thresholds are the compile's own guard's (xpu2/interactive/xpu2_session.cc, CompileGuard): it will not begin
# under NEED_GB free, and stops itself when free memory falls under a twentieth of the machine's (2 GB at least).
# PEAK_GB is the most a whole compile has taken (d53fc99f); a compile finished here says its own peak in the log.
NEED_GB = 8.0
PEAK_GB = 11.0
GB = 1024.0 ** 3


def _need():
    try: return max(1.0, float(os.environ.get('XPU2_COMPILE_NEED_GB', NEED_GB)))
    except ValueError: return NEED_GB


def _measured_peak(lines):
    """The last finished compile's peak ("memory at most X GB") from its log, or None."""
    for line in reversed(lines):
        if 'memory at most' in line:
            try: return float(line.split('memory at most', 1)[1].split()[0])
            except (ValueError, IndexError): return None
    return None


def memory_reading(total, free, need=NEED_GB, peak=PEAK_GB):
    """The meter in words, from the machine's RAM in bytes: free of total, and whether that is enough to compile.
    (level, text), level 0 enough, 1 tight (it begins, but may stop as other programs take memory), 2 not enough."""
    free_gb, total_gb = free / GB, total / GB
    floor = max(2.0, total_gb / 20.0)
    head = '%.1f GB free of %.0f GB' % (free_gb, total_gb)
    if total_gb < need + floor:
        return 2, '%s: this machine has too little RAM to compile (needs about %.0f GB free)' % (head, need)
    if free_gb < need:
        return 2, '%s: not enough (needs about %.0f GB free; close other programs)' % (head, need)
    if free_gb < peak + floor:
        return 1, '%s: tight (it can take up to %.0f GB; close other programs to be safe)' % (head, peak)
    return 0, '%s: enough (it takes up to %.0f GB)' % (head, peak)


def memory_state():
    """The meter's words now, or '' where Windows does not say."""
    try:
        import ctypes
        import ctypes.wintypes as w

        class Status(ctypes.Structure):
            _fields_ = [('dwLength', w.DWORD), ('dwMemoryLoad', w.DWORD)] + [(n, ctypes.c_ulonglong) for n in (
                'ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile', 'ullAvailPageFile', 'ullTotalVirtual',
                'ullAvailVirtual', 'ullAvailExtendedVirtual')]
        status = Status()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)): return ''
    except (AttributeError, OSError):
        return ''
    peak = PEAK_GB
    try:
        from moonray_modo import native
        lines = native.xpu2_shaders_log().read_text(encoding='utf-8', errors='replace').splitlines()
        measured = _measured_peak(lines)
        # What it took here, with room for a driver that compiles larger; never under the need to begin.
        if measured: peak = max(_need(), measured * 1.5)
    except Exception:
        pass
    return memory_reading(status.ullTotalPhys, status.ullAvailPhys, _need(), peak)[1]


MEMORY_NOTIFIER = 'moonray.xpu2.compileMemory'


class MemoryNotifier(lxifc.Notifier):
    clients = {}
    def noti_Name(self): return MEMORY_NOTIFIER
    def noti_SetArgs(self, args): pass
    def noti_Args(self): return ''
    def noti_AddClient(self, event): self.clients[event.__peekobj__()] = event
    def noti_RemoveClient(self, event): self.clients.pop(event.__peekobj__(), None)


# The meter is read again every few seconds while a form shows it: each reading asks the form to look again, and a form
# that is closed asks nothing, so the timer stops once no one has read the meter for a while.
_memory_timer = []
_memory_read = [0.0]
MEMORY_EVERY = 3000
MEMORY_IDLE = 10.0


def _memory_tick():
    import time
    if time.monotonic() - _memory_read[0] > MEMORY_IDLE:
        for timer in _memory_timer: timer.stop()
        del _memory_timer[:]
        return
    for event in list(MemoryNotifier.clients.values()):
        try: lx.object.CommandEvent(event).Event(lx.symbol.fCMDNOTIFY_VALUE)
        except (RuntimeError, LookupError): pass


def _memory_watch():
    import time
    _memory_read[0] = time.monotonic()
    if _memory_timer: return
    try:
        from PySide2 import QtCore
    except ImportError:
        return
    timer = QtCore.QTimer()
    timer.setInterval(MEMORY_EVERY)
    timer.timeout.connect(_memory_tick)
    timer.start()
    _memory_timer.append(timer)


class CompileMemory(Followed, lxu.command.BasicCommand):
    """The machine's free RAM against what the shader compile needs (read only)."""
    WATCHED = ((MEMORY_NOTIFIER, ''),)
    def __init__(self):
        super().__init__()
        self.dyna_Add('value', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def cmd_Query(self, index, query):
        _memory_watch()
        lx.object.ValueArray(query).AddString(memory_state())
    def basic_Execute(self, msg, flags): pass


lx.bless(MemoryNotifier, MEMORY_NOTIFIER)
lx.bless(CompileMemory, 'moonray.xpu2.compileMemory')
lx.bless(ShadersNotifier, NOTIFIER)
lx.bless(CompileShaders, 'moonray.xpu2.compileShaders')
lx.bless(ShaderState, 'moonray.xpu2.shaderState')
