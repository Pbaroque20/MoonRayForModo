"""Keep local render statistics; omit the optional Unix studio telemetry."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
rndr = root / 'upstream/openmoonray/moonray/moonray/lib/rendering/rndr'
path = rndr / 'RenderStatistics.h'
text = path.read_text(encoding='utf-8')
if 'Windows desktop renderer does not use Athena' not in text:
    text = text.replace('#include <moonray/rendering/rndr/statistics/AthenaCSVStream.h>',
        '#ifndef MOONRAY_WINDOWS_DESKTOP\n#include <moonray/rendering/rndr/statistics/AthenaCSVStream.h>\n#endif\n#include <fstream>')
    text = text.replace('    moonray::stats::AthenaCSVStream mAthenaStream;',
        '#ifdef MOONRAY_WINDOWS_DESKTOP\n    std::ofstream mAthenaStream;\n#else\n    moonray::stats::AthenaCSVStream mAthenaStream;\n#endif')
    start = text.index('        if (guid !=', text.index('void openAthenaStream'))
    end = text.index('\n    }', start)
    text = text[:start] + '''#ifdef MOONRAY_WINDOWS_DESKTOP
        scene_rdl2::Logger::warn("Windows desktop renderer does not use Athena studio telemetry.");
#else
''' + text[start:end] + '\n#endif' + text[end:]
    path.write_text(text, encoding='utf-8')
path = rndr / 'RenderStatistics.cc'
text = path.read_text(encoding='utf-8')
if 'GetModuleFileNameW' not in text:
    text = text.replace('#include <sys/param.h>', '#ifdef _WIN32\n#include <windows.h>\n#include <filesystem>\n#ifndef MAXPATHLEN\n#define MAXPATHLEN 32768\n#endif\n#else\n#include <sys/param.h>\n#endif')
    start = text.index("    // readlink does not append")
    end = text.index('\n}', start)
    text = text[:start] + '''#ifdef _WIN32
    std::wstring path(32768, L'\\0');
    DWORD count = GetModuleFileNameW(nullptr, &path[0], static_cast<DWORD>(path.size()));
    if (!count || count >= path.size()) throw std::runtime_error("Cannot query executable path");
    path.resize(count);
    return std::filesystem::path(path).u8string();
#else
''' + text[start:end] + '\n#endif' + text[end:]
    path.write_text(text, encoding='utf-8')

for name in ('RenderStatistics.cc', 'ImageWriteDriver.cc', 'ResumeHistoryMetaData.cc'):
    path = rndr / name
    text = path.read_text(encoding='utf-8')
    if 'GetComputerNameA' not in text:
        text = '''#ifdef _WIN32
#include <windows.h>
#ifndef HOST_NAME_MAX
#define HOST_NAME_MAX 255
#endif
namespace {
int desktopHostname(char* buffer, size_t length) {
    DWORD capacity = static_cast<DWORD>(length);
    return GetComputerNameA(buffer, &capacity) ? 0 : -1;
}
}
#else
#define desktopHostname gethostname
#endif
''' + text.replace('gethostname(', 'desktopHostname(')
        path.write_text(text, encoding='utf-8')
