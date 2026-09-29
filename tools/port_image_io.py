"""Use native binary file handles for checkpoint copies on Windows."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rndr = root / 'upstream/openmoonray/moonray/moonray/lib/rendering/rndr'
for name in ('RenderContext.cc', 'ImageWriteDriver.cc'):
    path = rndr / name
    text = path.read_text(encoding='utf-8')
    text = text.replace('#ifndef __APPLE__', '#if !defined(__APPLE__) && !defined(_WIN32)')
    path.write_text(text, encoding='utf-8')
path = rndr / 'ImageWriteCache.cc'
text = path.read_text(encoding='utf-8')
if '_O_TEMPORARY' not in text:
    text = text.replace('#ifndef __APPLE__\n#include <malloc.h>',
        '#if defined(_WIN32)\n#include <windows.h>\n#include <io.h>\n#include <filesystem>\n#elif !defined(__APPLE__)\n#include <malloc.h>')
    text = text.replace('#ifndef __APPLE__\n    malloc_trim', '#if !defined(__APPLE__) && !defined(_WIN32)\n    malloc_trim')
    text = text.replace('    mTmpFileFd = open(mTmpFilename.c_str(), O_RDONLY, 0);', '''#ifdef _WIN32
    mTmpFileFd = _wopen(std::filesystem::u8path(mTmpFilename).c_str(),
                       _O_RDONLY | _O_BINARY | _O_TEMPORARY);
#else
    mTmpFileFd = open(mTmpFilename.c_str(), O_RDONLY, 0);
#endif''')
    text = text.replace('    if (unlink(mTmpFilename.c_str()) == -1) {\n        return false;\n    }',
        '#ifndef _WIN32\n    if (unlink(mTmpFilename.c_str()) == -1) {\n        return false;\n    }\n#endif')
    text = text.replace('    int dstFd = open(copyDestName.c_str(), O_WRONLY | O_CREAT, 0666);', '''#ifdef _WIN32
    int dstFd = _wopen(std::filesystem::u8path(copyDestName).c_str(),
                      _O_WRONLY | _O_CREAT | _O_TRUNC | _O_BINARY, _S_IREAD | _S_IWRITE);
#else
    int dstFd = open(copyDestName.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0666);
#endif''')
    text = text.replace('#ifdef __APPLE__\n    int result = fcopyfile', '''#ifdef _WIN32
    HANDLE source = reinterpret_cast<HANDLE>(_get_osfhandle(mTmpFileFd));
    HANDLE destination = reinterpret_cast<HANDLE>(_get_osfhandle(dstFd));
    LARGE_INTEGER length{};
    bool copied = GetFileSizeEx(source, &length) != FALSE;
    std::vector<char> buffer(1024 * 1024);
    for (uint64_t offset = 0; copied && offset < static_cast<uint64_t>(length.QuadPart);) {
        OVERLAPPED position{};
        position.Offset = static_cast<DWORD>(offset);
        position.OffsetHigh = static_cast<DWORD>(offset >> 32);
        DWORD count = static_cast<DWORD>(std::min<uint64_t>(buffer.size(), length.QuadPart - offset));
        DWORD readBytes = 0, writtenBytes = 0;
        copied = ReadFile(source, buffer.data(), count, &readBytes, &position) && readBytes == count;
        if (copied) copied = WriteFile(destination, buffer.data(), count, &writtenBytes, nullptr) && writtenBytes == count;
        offset += count;
    }
    if (!copied) {
        const DWORD error = GetLastError();
        close(dstFd);
        errMsg = "Windows checkpoint copy failed: " + copyDestName + " (error " + std::to_string(error) + ")";
        return false;
    }
#elif defined(__APPLE__)
    int result = fcopyfile''')
    text = text.replace('    if (rename(srcName.c_str(), dstName.c_str()) == -1) {', '''#ifdef _WIN32
    const bool renameFailed = !MoveFileExW(std::filesystem::u8path(srcName).c_str(),
        std::filesystem::u8path(dstName).c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
#else
    const bool renameFailed = rename(srcName.c_str(), dstName.c_str()) == -1;
#endif
    if (renameFailed) {''')
    path.write_text(text, encoding='utf-8')
path = rndr / 'Error.cc'
text = path.read_text(encoding='utf-8')
if 'strerror_s' not in text:
    text = text.replace('#if __APPLE__ ||', '''#if defined(_WIN32)
    return strerror_s(errbuf.data(), errbuf.size(), errno) == 0 ? std::string(errbuf.data()) : "Unknown error";
#elif __APPLE__ ||''')
    path.write_text(text, encoding='utf-8')
