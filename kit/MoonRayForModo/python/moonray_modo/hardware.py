"""What the renderer is running on, in a few words: the graphics card and the processor, for the preview window.

Asked of the machine once and kept. The graphics card is the first NVIDIA one, which is the one MoonRay's XPU mode
uses; where it cannot be asked, or there is none, nothing is said of it.
"""
import re
import subprocess

_held = {}


def short(name):
    """A product name without its maker's flourishes: 'NVIDIA GeForce RTX 3090' as 'RTX 3090'."""
    name = re.sub(r'\((R|TM|tm|r)\)', '', str(name or ''))
    name = re.sub(r'@.*$', '', name)
    name = re.sub(r'\b(NVIDIA|GeForce|Intel|AMD|Core|CPU|Processor|\d+-Core)\b', ' ', name)
    return ' '.join(name.split())


def gpu():
    """The first NVIDIA graphics card's name, shortened, or '' where there is none to ask."""
    if 'gpu' not in _held:
        found = ''
        try:
            done = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader', '-i', '0'], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=4, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if done.returncode == 0:
                found = short(done.stdout.decode('utf-8', 'replace').splitlines()[0]) if done.stdout.strip() else ''
        except (OSError, subprocess.SubprocessError, IndexError):
            found = ''
        _held['gpu'] = found
    return _held['gpu']


def cpu():
    """The processor's name, shortened, or ''."""
    if 'cpu' not in _held:
        found = ''
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                found = short(winreg.QueryValueEx(key, 'ProcessorNameString')[0])
        except (ImportError, OSError):
            try:
                import platform
                found = short(platform.processor())
            except Exception:
                found = ''
        _held['cpu'] = found
    return _held['cpu']
