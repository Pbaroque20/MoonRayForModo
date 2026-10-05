#pragma once
// Defaults for relocatable Windows distributions. Explicit settings take precedence.
#ifdef _WIN32
#include <windows.h>
#include <cstdlib>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>
inline void modoRuntimePaths()
{
    std::vector<char> buffer(32768);
    DWORD n = GetModuleFileNameA(nullptr, buffer.data(), DWORD(buffer.size()));
    if (!n || n >= buffer.size()) throw std::runtime_error("Cannot locate MoonRay executable directory");
    const auto directory = std::filesystem::path(std::string(buffer.data(), n)).parent_path();
    auto setDefault = [](const char* key, const std::string& value) {
        const char* current = std::getenv(key);
        if ((!current || !*current) && _putenv_s(key, value.c_str()) != 0)
            throw std::runtime_error(std::string("Cannot configure ") + key);
    };
    setDefault("REZ_MOONRAY_ROOT", directory.string());
    std::string dsos = directory.string();
    if (std::filesystem::is_directory(directory / "rdl2dso"))
        dsos = (directory / "rdl2dso").string() + ";" + dsos;
    setDefault("RDL2_DSO_PATH", dsos);
    n = GetTempPathA(DWORD(buffer.size()), buffer.data());
    if (n && n < buffer.size()) setDefault("TMPDIR", std::string(buffer.data(), n));
}
#else
inline void modoRuntimePaths() {}
#endif
