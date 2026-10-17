"""The MoonRay Terminal: every program the plugin runs, shown as on a command line: the command, what the program
prints, and how it ended.

Recording is always on and costs little: the last LIMIT lines are kept, so the window shows what happened before it
was opened. Programs started with Qt (MoonRay, MoonLightIPR, the denoiser and the rest) are followed by watch(); those
started with Python's subprocess are seen by an audit hook (install), for calls made from the plugin's own code."""
import collections
import itertools
import os
import subprocess
import sys
import threading
import time
import weakref

LIMIT = 20000
# The lines MoonRay prints for the plugin to read (bucket and progress packets), hidden in the window unless asked for.
PACKET_PREFIX = '@@'

_lock = threading.RLock()
_entries = collections.deque(maxlen=LIMIT)  # (serial, time, kind, source, text)
_serial = itertools.count(1)
_ids = itertools.count(1)
_running = {}  # id -> (source, started)
_partial = {}  # id -> text of a line not yet ended
sources = set()


def _add(kind, source, text):
    with _lock:
        _entries.append((next(_serial), time.time(), kind, source, text))


def entries(after=0):
    """The lines recorded since serial after, oldest first."""
    with _lock:
        return [entry for entry in _entries if entry[0] > after]


def clear():
    with _lock:
        _entries.clear()


def command_line(program, arguments):
    """A command as it would be typed: the program and its arguments, quoted where they need it."""
    return subprocess.list2cmdline([str(program)] + [str(a) for a in arguments])


def command(program, arguments, source, directory=None, line=None):
    """A program started: returns the id its output and end are recorded under. line is the command as already
    written out, where it comes so (on Windows, subprocess quotes the command itself)."""
    with _lock:
        ident = next(_ids)
        sources.add(source)
        _running[ident] = (source, time.time())
        _add('command', source, line if line is not None else command_line(program, arguments))
        if directory:
            _add('note', source, 'in ' + str(directory))
        return ident


def busy():
    """Whether a program the plugin started is still running."""
    with _lock:
        return bool(_running)


def output(ident, text):
    """What a program printed; whole lines are recorded, a line still being written waits for its end."""
    if not text:
        return
    with _lock:
        source = _running.get(ident, ('?', 0))[0]
        held = _partial.get(ident, '') + text.replace('\r\n', '\n')
        *done, rest = held.split('\n')
        for line in done:
            for part in line.split('\r'):
                if part:
                    _add('out', source, part)
        _partial[ident] = rest[-65536:]


# The exit code Qt gives a program it ends by force on Windows (QProcess.kill): stopped by the plugin, not crashed.
KILLED = 0xF291


def ended(ident, code, crashed=False, known=True, stopped=False):
    with _lock:
        rest = _partial.pop(ident, '')
        if ident not in _running:
            return
        source, began = _running.pop(ident)
        if rest:
            _add('out', source, rest)
        seconds = time.time() - began
        if not known:
            _add('end', source, 'ended (exit code not known) after %.1f s' % seconds)
        elif stopped:
            _add('stop', source, 'stopped after %.1f s' % seconds)
        elif crashed:
            _add('fail', source, 'crashed (0x%08X) after %.1f s' % (code & 0xffffffff, seconds))
        else:
            _add('end' if code == 0 else 'fail', source, 'exited %d after %.1f s' % (code, seconds))


def note(source, text):
    _add('note', source, text)


def watch(process, source):
    """Follow a QProcess: its command as it starts, everything the plugin reads from it, and its end. Call before
    connecting its readers: the process's read functions are wrapped to copy what they return. source is the name
    shown, or a function giving it as the process starts (one process can run different programs)."""
    from PySide2 import QtCore
    state = {'id': None, 'stopped': False}

    def started():
        state['stopped'] = False
        named = source() if callable(source) else source
        state['id'] = command(process.program(), process.arguments(), named, process.workingDirectory())

    def tapped(read):
        def reader():
            data = read()
            if state['id'] is not None:
                output(state['id'], bytes(data.data()).decode('utf-8', errors='replace'))
            return data
        return reader

    def finished(code, status):
        if state['id'] is not None:
            # What is left unread is the program's too.
            crashed = status == QtCore.QProcess.CrashExit
            # Ended by the plugin (a render stopped by hand, a session closed): a stop, though Qt calls it a crash.
            stopped = state['stopped'] or (crashed and (code & 0xffffffff) == KILLED)
            ended(state['id'], code, crashed, stopped=stopped)
            state['id'] = None

    def failed(error):
        if error == QtCore.QProcess.FailedToStart:
            note(source() if callable(source) else source, 'could not start %s: %s' % (command_line(process.program(), process.arguments()), process.errorString()))

    process.started.connect(started)
    process.finished.connect(finished)
    process.errorOccurred.connect(failed)
    process.readAllStandardOutput = tapped(process.readAllStandardOutput)
    process.readAllStandardError = tapped(process.readAllStandardError)
    process.readAll = tapped(process.readAll)

    def stopping(end):
        def stop(*arguments):
            state['stopped'] = True
            return end(*arguments)
        return stop
    process.kill = stopping(process.kill)
    process.terminate = stopping(process.terminate)
    return process


# Programs started with Python's subprocess, seen by an audit hook.
_HERE = os.path.dirname(os.path.abspath(__file__))
_KIT = os.path.normcase(os.path.dirname(os.path.dirname(_HERE)))


def _caller():
    """The plugin module that started a subprocess, or None when it was not the plugin."""
    frame = sys._getframe(2)
    popen = None
    while frame is not None:
        name = os.path.normcase(frame.f_code.co_filename)
        if frame.f_code.co_name == '__init__' and name.endswith('subprocess.py') and popen is None:
            popen = frame.f_locals.get('self')
        if name.startswith(_KIT) and not name.endswith('terminal.py'):
            return os.path.splitext(os.path.basename(name))[0], popen
        frame = frame.f_back
    return None, None


def _follow(ident, popen):
    """See a subprocess end: Python sets its exit code as it waits for it or polls it, which the plugin's code does
    (subprocess.run, communicate, wait); the code is read there. One left unwaited is noted as it is let go."""
    def wrapped(method):
        def call(*arguments, **keywords):
            try:
                return method(*arguments, **keywords)
            finally:
                if popen.returncode is not None and ident in _running:
                    ended(ident, popen.returncode)
        return call
    for name in ('_wait', '_internal_poll'):
        if hasattr(popen, name):
            setattr(popen, name, wrapped(getattr(popen, name)))
    weakref.finalize(popen, lambda: ident in _running and ended(ident, 0, known=False))


def _audit(event, arguments):
    if event != 'subprocess.Popen':
        return
    try:
        module, popen = _caller()
        if module is None:
            return
        executable, given, directory = arguments[0], arguments[1], arguments[2]
        if isinstance(given, (str, bytes)):
            text = given.decode(errors='replace') if isinstance(given, bytes) else given
            program, rest, line = text, [], text
        else:
            listed = [a.decode(errors='replace') if isinstance(a, bytes) else str(a) for a in given]
            program, rest, line = (listed[0] if listed else str(executable)), listed[1:], None
        with _lock:
            ident = command(program, rest, module, directory, line)
            if popen is not None:
                _follow(ident, popen)
            else:
                ended(ident, 0, known=False)
    except Exception:
        pass


def install():
    """Start seeing subprocesses. An audit hook cannot be taken away, so one is added for the session, which looks this
    module up anew each time: a reloaded plugin is followed by its new code."""
    if getattr(sys, '_moonray_terminal_hook', False):
        return
    sys._moonray_terminal_hook = True

    def hook(event, arguments):
        if event == 'subprocess.Popen':
            held = sys.modules.get(__name__)
            if held is not None:
                held._audit(event, arguments)
    sys.addaudithook(hook)


_window = None


def show(parent=None):
    """Open the Terminal window, or bring it forward."""
    global _window
    from .terminal_window import TerminalWindow
    if _window is None:
        _window = TerminalWindow(parent)
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window
