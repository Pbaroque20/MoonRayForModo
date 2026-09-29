"""Use Windows temporary paths and native process memory accounting."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
rndr = root / 'upstream/openmoonray/moonray/moonray/lib/rendering/rndr'
path = rndr / 'ImageWriteDriver.cc'
text = path.read_text(encoding='utf-8')
if 'return static_cast<size_t>(moonray::util::ProcessStats' not in text:
    text = '#include <moonray/common/mcrt_util/ProcessStats.h>\n' + text
    start = text.index('    std::ifstream stat_stream', text.index('ImageWriteDriver::getProcMemUsage()'))
    end = text.index('\n}', start)
    text = text[:start] + '    return static_cast<size_t>(moonray::util::ProcessStats().getProcessMemory());' + text[end:]
    path.write_text(text, encoding='utf-8')
path = rndr / 'ProcKeeper.cc'
text = path.read_text(encoding='utf-8')
if '_commit(mImageWriteProgressFd)' not in text:
    text = '#ifdef _WIN32\n#include <filesystem>\n#include <io.h>\n#endif\n' + text
    text = text.replace('    ostr << WRITE_PROGRESS_UPDATE_FILE_NAME << static_cast<unsigned>(getpid()) << ".log";', '''#ifdef _WIN32
    ostr << (std::filesystem::temp_directory_path() / "moonray_write.").u8string()
         << static_cast<unsigned>(getpid()) << ".log";
#else
    ostr << WRITE_PROGRESS_UPDATE_FILE_NAME << static_cast<unsigned>(getpid()) << ".log";
#endif''')
    text = text.replace('    if (::fsync(mImageWriteProgressFd) == -1) return false;', '''#ifdef _WIN32
    if (::_commit(mImageWriteProgressFd) == -1) return false;
#else
    if (::fsync(mImageWriteProgressFd) == -1) return false;
#endif''')
    text = text.replace('    mImageWriteProgressFd = ::open(mImageWriteProgressFilename.c_str(), O_WRONLY | O_CREAT, S_IREAD);', '''#ifdef _WIN32
    mImageWriteProgressFd = ::_wopen(std::filesystem::u8path(mImageWriteProgressFilename).c_str(),
                                   _O_WRONLY | _O_CREAT | _O_TRUNC | _O_BINARY, _S_IREAD | _S_IWRITE);
#else
    mImageWriteProgressFd = ::open(mImageWriteProgressFilename.c_str(), O_WRONLY | O_CREAT, S_IREAD);
#endif''')
    text = text.replace('    if (::unlink(mImageWriteProgressFilename.c_str()) == -1) {', '''#ifdef _WIN32
    const bool unlinkFailed = ::_wunlink(std::filesystem::u8path(mImageWriteProgressFilename).c_str()) == -1;
#else
    const bool unlinkFailed = ::unlink(mImageWriteProgressFilename.c_str()) == -1;
#endif
    if (unlinkFailed) {''')
    path.write_text(text, encoding='utf-8')
