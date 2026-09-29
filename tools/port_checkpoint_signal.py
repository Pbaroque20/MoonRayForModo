"""Map Windows console interrupts to MoonRay's checkpoint request."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
rndr = root / 'upstream/openmoonray/moonray/moonray/lib/rendering/rndr'
path = rndr / 'ImageWriteDriver.h'
text = path.read_text(encoding='utf-8')
if 'struct CheckpointSignalInfo' not in text:
    text = text.replace('class RenderContext;', '''#ifdef _WIN32
// Windows console events have no POSIX sender PID or UID.
struct CheckpointSignalInfo { int si_signo, si_code, si_pid, si_uid; };
#else
using CheckpointSignalInfo = siginfo_t;
#endif

class RenderContext;''')
    text = text.replace('const siginfo_t&', 'const CheckpointSignalInfo&').replace('    siginfo_t mSigInfo;', '    CheckpointSignalInfo mSigInfo;')
    path.write_text(text, encoding='utf-8')
path = rndr / 'ImageWriteDriver.cc'
text = path.read_text(encoding='utf-8').replace('siginfo_t', 'CheckpointSignalInfo')
path.write_text(text, encoding='utf-8')
path = rndr / 'CheckpointSigIntHandler.cc'
text = path.read_text(encoding='utf-8')
if 'SetConsoleCtrlHandler' not in text:
    text = text.replace('#include <signal.h>', '#include <signal.h>\n#ifdef _WIN32\n#include <windows.h>\n#endif')
    start = text.index('static\nvoid\ncheckpointSigActionFunction')
    end = text.index('\n#ifdef TEST_SCENE_CONTEXT_DUMP', start)
    text = text[:start] + '''#ifdef _WIN32
static BOOL WINAPI checkpointConsoleHandler(DWORD event) {
    if (event != CTRL_C_EVENT && event != CTRL_BREAK_EVENT) return FALSE;
    const CheckpointSignalInfo info{SIGINT, static_cast<int>(event), -1, -1};
    ImageWriteDriver::get()->interruptBySignal(info);
    return TRUE;
}
#else
''' + text[start:end] + '\n#endif\n' + text[end:]
    start = text.index('    struct sigaction', text.index('CheckpointSigIntHandler::enable'))
    end = text.index('\n    // We need tmp directory', start)
    text = text[:start] + '''#ifdef _WIN32
    if (!SetConsoleCtrlHandler(checkpointConsoleHandler, TRUE))
        throw std::runtime_error("Cannot register Windows checkpoint console handler");
#else
''' + text[start:end] + '\n#endif\n' + text[end:]
    start = text.index('    struct sigaction', text.index('CheckpointSigIntHandler::disable'))
    end = text.index('\n}\n', start)
    text = text[:start] + '''#ifdef _WIN32
    if (!SetConsoleCtrlHandler(checkpointConsoleHandler, FALSE))
        throw std::runtime_error("Cannot remove Windows checkpoint console handler");
#else
''' + text[start:end] + '\n#endif\n' + text[end:]
    path.write_text(text, encoding='utf-8')
