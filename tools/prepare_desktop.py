"""Guard the optional Unix telnet console in the desktop renderer."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'upstream/openmoonray/moonray/moonray/lib/rendering/rndr/RenderContext.cc'
text = path.read_text(encoding='utf-8')
if '#ifndef MOONRAY_WINDOWS_DESKTOP' not in text:
    text = text.replace('#include "RenderContextConsoleDriver.h"',
                        '#ifndef MOONRAY_WINDOWS_DESKTOP\n#include "RenderContextConsoleDriver.h"\n#endif')
    start = text.index('    if (RenderContextConsoleDriver::get())')
    end = text.index('\n    }', start) + len('\n    }')
    text = text[:start] + '#ifndef MOONRAY_WINDOWS_DESKTOP\n' + text[start:end] + '\n#endif' + text[end:]
    start = text.index('    { // renderContext console setup for debug purpose')
    end = text.index('\n    // Determine if to render', start)
    text = text[:start] + '''#ifdef MOONRAY_WINDOWS_DESKTOP
    if (vars.get(scene_rdl2::rdl2::SceneVariables::sDebugConsole) >= 0)
        throw std::runtime_error("Telnet debugging is unavailable in the Windows desktop renderer.");
#else
''' + text[start:end] + '\n#endif\n' + text[end:]
    path.write_text(text, encoding='utf-8')
