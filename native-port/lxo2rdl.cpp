// SPDX-License-Identifier: MIT
// lxo2rdl: Modo scenes (.lxo) written as MoonRay scenes (.rdla, .rdlb) by Modo's command-line engine (modo_cl.exe) and the
// kit's scripts/export_moonray.py, as MoonRay > Convert LXO to RDL does inside Modo (moonray_modo/lxo_convert.py). It sits in
// the kit's bin folder: run it from a command line, or drop scenes or folders on it in Explorer. Modo may be open or not.
//
//   lxo2rdl [--rdla | --rdlb | --split] [--frames] [--no-outputs] [--collect] [--out FOLDER] [--jobs N] [--modo modo_cl.exe]
//           scene.lxo | folder ...
//
// Each scene is written by its own MoonRay render settings, as Export as MoonRay Scene writes it, beside the scene or in
// --out. The exit code is the number of scenes that failed.
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cwctype>
#include <filesystem>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

namespace {

const wchar_t* USAGE =
    L"lxo2rdl: Modo scenes written as MoonRay scenes, by Modo's command-line engine (modo_cl.exe).\n"
    L"\n"
    L"  lxo2rdl [options] scene.lxo | folder ...\n"
    L"\n"
    L"  A folder's .lxo files are converted, its subfolders' too. Scenes or folders can be dropped on lxo2rdl.exe.\n"
    L"\n"
    L"  --rdla         one text file for each scene (the default)\n"
    L"  --rdlb         one binary file: smaller, quicker to load\n"
    L"  --split        settings as RDLA, geometry as RDLB (MoonRay's split scene)\n"
    L"  --frames       one MoonRay scene for each frame of the scene's frame range\n"
    L"  --no-outputs   leave the AOVs, Cryptomatte and deep out\n"
    L"  --collect      copy the pictures each scene reads into a folder beside it\n"
    L"  --out FOLDER   write into FOLDER, not beside each scene\n"
    L"  --jobs N       convert N scenes at the same time (1 unless said)\n"
    L"  --modo PATH    modo_cl.exe, where it is not in Program Files\\Modo...\\modo\n";

std::string utf8(const std::wstring& text) {
    if (text.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), int(text.size()), nullptr, 0, nullptr, nullptr);
    std::string out(size_t(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), int(text.size()), out.data(), size, nullptr, nullptr);
    return out;
}

std::wstring wide(const std::string& text) {
    if (text.empty()) return {};
    const int size = MultiByteToWideChar(CP_UTF8, 0, text.data(), int(text.size()), nullptr, 0);
    std::wstring out(size_t(size), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), int(text.size()), out.data(), size);
    return out;
}

std::wstring lower(std::wstring text) {
    std::transform(text.begin(), text.end(), text.begin(), [](wchar_t c) { return wchar_t(std::towlower(c)); });
    return text;
}

std::mutex said;

void say(const std::wstring& text) {
    std::lock_guard<std::mutex> hold(said);
    const std::string bytes = utf8(text);
    std::fwrite(bytes.data(), 1, bytes.size(), stdout);
    std::fflush(stdout);
}

fs::path self() {
    std::wstring held(32768, L'\0');
    held.resize(GetModuleFileNameW(nullptr, held.data(), DWORD(held.size())));
    return fs::path(held);
}

// Modo's command-line engine: as given, then MODO_CL, then Program Files\Modo...\modo\modo_cl.exe (16.1 first, the Modo
// the kit is made for).
fs::path findModo(const fs::path& given) {
    if (!given.empty()) return given;
    wchar_t held[32768];
    if (GetEnvironmentVariableW(L"MODO_CL", held, 32768)) return fs::path(held);
    std::vector<fs::path> found;
    for (const wchar_t* name : {L"ProgramW6432", L"ProgramFiles"}) {
        if (!GetEnvironmentVariableW(name, held, 32768)) continue;
        std::error_code error;
        for (const auto& entry : fs::directory_iterator(fs::path(held), error)) {
            const std::wstring folder = entry.path().filename().wstring();
            const fs::path engine = entry.path() / L"modo" / L"modo_cl.exe";
            if (lower(folder).rfind(L"modo", 0) == 0 && fs::is_regular_file(engine, error)) found.push_back(engine);
        }
    }
    std::sort(found.begin(), found.end(), [](const fs::path& a, const fs::path& b) {
        const bool a16 = a.wstring().find(L"16.1") != std::wstring::npos, b16 = b.wstring().find(L"16.1") != std::wstring::npos;
        return a16 != b16 ? a16 : a.wstring() > b.wstring();
    });
    return found.empty() ? fs::path() : found.front();
}

struct Job {
    fs::path scene, target;
    std::vector<std::wstring> written, notices;
    std::string log;
    bool done = false;
};

struct Options {
    std::wstring format = L"rdla";
    bool frames = false, outputs = true, collect = false;
    fs::path out, modo;
    int jobs = 1;
};

// The Modo scenes among the arguments: .lxo files, and those in folders and their subfolders, each once.
std::vector<fs::path> scenes(const std::vector<fs::path>& given) {
    std::vector<fs::path> found;
    std::set<std::wstring> seen;
    auto add = [&](const fs::path& path) {
        std::error_code error;
        const fs::path whole = fs::absolute(path, error);
        if (lower(whole.extension().wstring()) != L".lxo" || !fs::is_regular_file(whole, error)) return;
        if (seen.insert(lower(whole.wstring())).second) found.push_back(whole);
    };
    for (const fs::path& path : given) {
        std::error_code error;
        if (fs::is_directory(path, error)) {
            std::vector<fs::path> inside;
            for (const auto& entry : fs::recursive_directory_iterator(path, fs::directory_options::skip_permission_denied, error))
                if (entry.is_regular_file(error)) inside.push_back(entry.path());
            std::sort(inside.begin(), inside.end(), [](const fs::path& a, const fs::path& b) { return lower(a.wstring()) < lower(b.wstring()); });
            for (const fs::path& scene : inside) add(scene);
        } else {
            add(path);
        }
    }
    return found;
}

// Where each scene is written: beside it, or in --out, by its name; two of the same name in one folder told apart by a
// number (shot.rdla, shot_2.rdla), as the window does (lxo_convert.targets).
void place(std::vector<Job>& jobs, const Options& options) {
    const std::wstring suffix = options.format == L"rdlb" ? L".rdlb" : L".rdla";
    std::set<std::wstring> taken;
    for (Job& job : jobs) {
        const fs::path folder = options.out.empty() ? job.scene.parent_path() : fs::absolute(options.out);
        const std::wstring name = job.scene.stem().wstring();
        fs::path target = folder / (name + suffix);
        for (int count = 2; !taken.insert(lower(target.wstring())).second; ++count)
            target = folder / (name + L"_" + std::to_wstring(count) + suffix);
        job.target = target;
    }
}

std::wstring trim(std::wstring text) {
    while (!text.empty() && std::iswspace(text.back())) text.pop_back();
    size_t start = 0;
    while (start < text.size() && std::iswspace(text[start])) ++start;
    return text.substr(start);
}

// One scene: modo_cl given the export and app.quit as its input, what it says read until it ends.
void convert(Job& job, const Options& options, const fs::path& engine, const fs::path& script, const fs::path& scratch, size_t index) {
    std::error_code error;
    fs::create_directories(job.target.parent_path(), error);
    const fs::path commands = scratch / (L"scene-" + std::to_wstring(index) + L".txt");
    // What the script did, in a file of its own: modo_cl does not pass on what a script says (export_moonray.py, report=).
    const fs::path report = scratch / (L"scene-" + std::to_wstring(index) + L".report.txt");
    std::wstring text = L"@{" + script.wstring() + L"} \"" + job.scene.wstring() + L"\" \"" + job.target.wstring() + L"\" format=" +
                        options.format + L" outputs=" + (options.outputs ? L"1" : L"0") + L" collect=" + (options.collect ? L"1" : L"0") +
                        (options.frames ? L" frames" : L"") + L" \"report=" + report.wstring() + L"\"\napp.quit\n";
    {
        FILE* file = _wfopen(commands.c_str(), L"wb");
        if (!file) { job.log = "The command file could not be written in " + utf8(scratch.wstring()); return; }
        const std::string bytes = utf8(text);
        std::fwrite(bytes.data(), 1, bytes.size(), file);
        std::fclose(file);
    }
    SECURITY_ATTRIBUTES inherit{sizeof(inherit), nullptr, TRUE};
    HANDLE input = CreateFileW(commands.c_str(), GENERIC_READ, FILE_SHARE_READ, &inherit, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    HANDLE readEnd = nullptr, writeEnd = nullptr;
    if (input == INVALID_HANDLE_VALUE || !CreatePipe(&readEnd, &writeEnd, &inherit, 0)) {
        job.log = "The command file could not be handed to modo_cl";
        if (input != INVALID_HANDLE_VALUE) CloseHandle(input);
        return;
    }
    SetHandleInformation(readEnd, HANDLE_FLAG_INHERIT, 0);
    STARTUPINFOW start{};
    start.cb = sizeof(start);
    start.dwFlags = STARTF_USESTDHANDLES;
    start.hStdInput = input;
    start.hStdOutput = writeEnd;
    start.hStdError = writeEnd;
    PROCESS_INFORMATION process{};
    std::wstring line = L"\"" + engine.wstring() + L"\"";
    const BOOL started = CreateProcessW(engine.c_str(), line.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr,
                                        scratch.c_str(), &start, &process);
    CloseHandle(writeEnd);
    CloseHandle(input);
    if (!started) {
        job.log = "modo_cl could not be started: " + utf8(engine.wstring());
        CloseHandle(readEnd);
        return;
    }
    char buffer[65536];
    DWORD got = 0;
    while (ReadFile(readEnd, buffer, sizeof(buffer), &got, nullptr) && got) job.log.append(buffer, got);
    CloseHandle(readEnd);
    WaitForSingleObject(process.hProcess, INFINITE);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    fs::remove(commands, error);
    // The report: a line each, its kind ("wrote", "notice", "error") and a tab before what it says.
    std::string said;
    if (FILE* file = _wfopen(report.c_str(), L"rb")) {
        char chunk[65536];
        for (size_t n; (n = std::fread(chunk, 1, sizeof(chunk), file)) > 0;) said.append(chunk, n);
        std::fclose(file);
    }
    fs::remove(report, error);
    std::string errors;
    size_t at = 0;
    while (at < said.size()) {
        size_t end = said.find('\n', at);
        if (end == std::string::npos) end = said.size();
        const std::string row = said.substr(at, end - at);
        at = end + 1;
        const size_t tab = row.find('\t');
        if (tab == std::string::npos) continue;
        const std::string kind = row.substr(0, tab);
        const std::wstring what = trim(wide(row.substr(tab + 1)));
        if (kind == "wrote") job.written.push_back(what);
        else if (kind == "notice") job.notices.push_back(what);
        else if (kind == "error") errors += row.substr(tab + 1) + "\n";
    }
    if (!errors.empty()) job.log = errors + "\n" + job.log;
    job.done = !job.written.empty() &&
               std::all_of(job.written.begin(), job.written.end(), [](const std::wstring& file) { std::error_code e; return fs::is_regular_file(file, e); });
}

// The last lines modo_cl said, for a scene that failed.
std::wstring tail(const std::string& log, size_t lines) {
    std::wstring text = wide(log);
    size_t at = text.size(), count = 0;
    while (at > 0 && count <= lines) {
        at = text.rfind(L'\n', at - 1);
        if (at == std::wstring::npos) { at = 0; break; }
        ++count;
    }
    return trim(text.substr(at));
}

// Started from Explorer (a double-click, or scenes dropped on it), the window would close before it could be read.
void pauseIfOwnWindow() {
    DWORD processes[2];
    if (GetConsoleProcessList(processes, 2) == 1) {
        say(L"\nPress Enter to close.\n");
        std::getchar();
    }
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    SetConsoleOutputCP(CP_UTF8);
    Options options;
    std::vector<fs::path> given;
    for (int i = 1; i < argc; ++i) {
        const std::wstring word = argv[i];
        auto next = [&]() -> std::wstring { return i + 1 < argc ? std::wstring(argv[++i]) : std::wstring(); };
        if (word == L"--rdla" || word == L"--rdlb" || word == L"--split") options.format = word.substr(2);
        else if (word == L"--frames") options.frames = true;
        else if (word == L"--no-outputs") options.outputs = false;
        else if (word == L"--collect") options.collect = true;
        else if (word == L"--out") options.out = next();
        else if (word == L"--modo") options.modo = next();
        else if (word == L"--jobs") options.jobs = std::max(1, std::min(16, _wtoi(next().c_str())));
        else if (word == L"--help" || word == L"-h" || word == L"/?") { say(USAGE); pauseIfOwnWindow(); return 0; }
        else if (word.rfind(L"--", 0) == 0) { say(L"Unknown option " + word + L"\n\n" + USAGE); pauseIfOwnWindow(); return 2; }
        else given.push_back(fs::path(word));
    }
    if (given.empty()) { say(USAGE); pauseIfOwnWindow(); return 0; }
    const fs::path script = self().parent_path().parent_path() / L"scripts" / L"export_moonray.py";
    std::error_code error;
    if (!fs::is_regular_file(script, error)) {
        say(L"The kit's export script is not where it should be: " + script.wstring() + L"\nKeep lxo2rdl.exe in the kit's bin folder.\n");
        pauseIfOwnWindow();
        return 2;
    }
    const fs::path engine = findModo(options.modo);
    if (engine.empty() || !fs::is_regular_file(engine, error)) {
        say(L"Modo's command-line engine, modo_cl.exe, was not found. Give it with --modo, or set MODO_CL.\n");
        pauseIfOwnWindow();
        return 2;
    }
    std::vector<Job> jobs;
    for (const fs::path& scene : scenes(given)) jobs.push_back(Job{scene});
    if (jobs.empty()) { say(L"No Modo scenes (.lxo) among what was given.\n"); pauseIfOwnWindow(); return 2; }
    place(jobs, options);
    const fs::path scratch = fs::temp_directory_path() / (L"lxo2rdl-" + std::to_wstring(GetCurrentProcessId()));
    fs::create_directories(scratch, error);
    say(L"Converting " + std::to_wstring(jobs.size()) + L" scene" + (jobs.size() == 1 ? L"" : L"s") + L" with " + engine.wstring() + L"\n");
    std::atomic<size_t> following{0}, finished{0};
    auto work = [&]() {
        for (size_t index = following++; index < jobs.size(); index = following++) {
            Job& job = jobs[index];
            say(L"  " + job.scene.filename().wstring() + L": converting\n");
            convert(job, options, engine, script, scratch, index);
            const size_t count = ++finished;
            std::wstring report = L"[" + std::to_wstring(count) + L"/" + std::to_wstring(jobs.size()) + L"] " + job.scene.wstring();
            if (job.done) {
                for (const std::wstring& file : job.written) report += L"\n    wrote " + file;
                for (const std::wstring& notice : job.notices) report += L"\n    notice: " + notice;
            } else {
                report += L"\n    failed. What modo_cl said last:\n" + tail(job.log, 20);
            }
            say(report + L"\n");
        }
    };
    std::vector<std::thread> workers;
    for (int i = 0; i < std::min<int>(options.jobs, int(jobs.size())); ++i) workers.emplace_back(work);
    for (std::thread& worker : workers) worker.join();
    fs::remove_all(scratch, error);
    const int failed = int(std::count_if(jobs.begin(), jobs.end(), [](const Job& job) { return !job.done; }));
    say(L"\n" + std::to_wstring(jobs.size() - size_t(failed)) + L" converted, " + std::to_wstring(failed) + L" failed.\n");
    pauseIfOwnWindow();
    return failed;
}
