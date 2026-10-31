"""Native Windows MoonRay integration for Modo 16.1v9."""
from pathlib import Path

__version__ = "0.5.1"
# The MoonRay the runtime is compiled from: the OpenMoonRay release, and the version of MoonRay itself in it
# (patches/native-windows/sources.json names the commits).
MOONRAY_RELEASE = "2026.29.1"
MOONRAY_VERSION = "18.4"
_BUILD_FILE = Path(__file__).with_name('BUILD.txt')


def build_number():
    """What tools/build_number.py stamped this kit with: "unknown" for a kit that was not."""
    try:
        return _BUILD_FILE.read_text(encoding='ascii').strip() or 'unknown'
    except OSError:
        return 'unknown'
