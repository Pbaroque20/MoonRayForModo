// XPU2's preview session for MoonRay for Modo, a private test build: the kit's persistent preview protocol v1
// (native-port/persistent_session.inc) rendered by the asynchronous renderer. No Modo API.
//
//   moonray_xpu2 -in <scene> [-in <scene> ...] -out <image> -exec_mode <mode> [-info] [-threads <n>]
//       With MOONRAY_MODO_SESSION set, the preview session; without it, the kit's own MoonRay renders the scene
//       (MOONRAY_XPU2_MOONRAY names its moonray.exe).
//   moonray_xpu2 --compile-shaders
//       Compiles the GPU programs into OptiX's disk cache, printing progress: about an hour the first time, then
//       cached for every session after. A mark of it is left (shaderMark) for this driver and these programs.
//   moonray_xpu2 --shaders-compiled
//       Exits 0 when the mark is there, 3 when it is not.
//
// Where XPU2 does not render a scene (PATH_TRACER.md says what it renders), its GPU programs are not compiled yet,
// or the GPU fails, the session prints "@@MODO_XPU2 FALLBACK <reason>" and ends: the kit then starts MoonRay in its
// place. The picture goes out through shared memory with its rows in MoonRay's film order, and the outlines of
// the work as @@MODO_TILES, the work grid's cells being rendered (its cellular rules move the CPU's workers from cell
// to cell), @@MODO_WORKERS: each CPU worker's 8-pixel tile, and @@MODO_GPU_WORKERS: the cells the GPU's queued
// launches hold (the private kit draws them in a colour of their own).
#include "async_render.h"
#include "../../native-port/modo_protocol_line.h"
#include "../../native-port/modo_scene_memory.h"
#include "../../native-port/modo_shared_image.h"
#include <OpenImageIO/imageio.h>
#include "aov_write.h"
#include "entity_classes.h"
#include "aov_display.h"
#include <scene_rdl2/scene/rdl2/RenderOutput.h>
#include <scene_rdl2/scene/rdl2/rdl2.h>
#include <condition_variable>
#include <new>
#include <psapi.h>
#include <dxgi.h>
#include <fstream>
#include <iostream>
#include <mutex>
#include <set>
#include <sstream>
using namespace xpu2::interactive;
namespace rdl = scene_rdl2::rdl2;
using Clock = std::chrono::steady_clock;
using async::TileSize;
using U32 = unsigned int;

namespace {

fs::path executableFolder() {
    std::wstring path(32768, L'\0');
    const DWORD n = GetModuleFileNameW(nullptr, path.data(), DWORD(path.size()));
    path.resize(n);
    return fs::path(path).parent_path();
}

std::string fileText(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    cpu::need(bool(file), "Cannot read " + path.string());
    return std::string((std::istreambuf_iterator<char>(file)), {});
}

// The session's memory ceiling (memoryCeiling), 0 before it is set.
size_t ceilingBytes = 0;

// A ceiling on the session's memory, its own job object's: past it Windows refuses an allocation, which the session
// reports as a fallback (main), where without it a scene asking for too much took memory the machine could not page
// out and froze it (his Lamborghini with its geometry budget raised to 16 GB). XPU2_SESSION_MEMORY_MB sets it; else the
// RAM free as the session starts, less a reserve for Windows and Modo meanwhile: a tenth of the machine's, 4 GB at least.
void memoryCeiling() {
    MEMORYSTATUSEX status{};
    status.dwLength = sizeof status;
    if (!GlobalMemoryStatusEx(&status)) return;
    const size_t reserve = std::max<size_t>(size_t(status.ullTotalPhys / 10), 4ull << 30);
    size_t limit = status.ullAvailPhys > reserve + (2ull << 30) ? size_t(status.ullAvailPhys) - reserve : 2ull << 30;
    if (const char* mb = std::getenv("XPU2_SESSION_MEMORY_MB"))
        if (const long long n = std::atoll(mb); n > 0) limit = size_t(n) << 20;
    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    if (!job) return;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION info{};
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    info.ProcessMemoryLimit = limit;
    if (SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info, sizeof info) &&
        AssignProcessToJobObject(job, GetCurrentProcess())) {
        ceilingBytes = limit;
        std::printf("XPU2: memory ceiling %zu MB (%.1f GB of the machine's %.1f GB free)\n", limit >> 20, double(status.ullAvailPhys) / (1 << 30),
                    double(status.ullTotalPhys) / (1 << 30));
    } else {
        std::printf("XPU2: no memory ceiling (the job object was refused: %lu)\n", GetLastError());
        CloseHandle(job);
    }
}

// The session's committed memory now and at its peak, in MB.
std::string memoryText() {
    PROCESS_MEMORY_COUNTERS_EX counters{};
    counters.cb = sizeof counters;
    if (!K32GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters), sizeof counters)) return "unknown";
    char text[160];
    std::snprintf(text, sizeof text, "%zu MB committed, %zu MB at most so far%s", counters.PrivateUsage >> 20, counters.PeakPagefileUsage >> 20,
                  ceilingBytes ? (", of a " + std::to_string(ceilingBytes >> 20) + " MB ceiling").c_str() : "");
    return text;
}

// What a byte of prepared positions and triangles costs in all, in bytes of the session's memory: its tessellation's
// buffers, normals, texture coordinates and the CPU's acceleration structure besides (5.7 GB committed for 576 MB on a
// displaced, instanced test scene).
constexpr size_t GeometryFootprint = 11;  // 10.4 measured, and a margin
// The same on the card: its acceleration structures' build and buffers (a peak of 13 GB above the session's own for
// 552 MB there).
constexpr size_t GeometryVramFootprint = 24;

// The largest graphics card's own memory (DXGI's dedicated video memory), 0 where it is not known.
size_t cardMemory() {
    static const size_t bytes = [] {
        HMODULE dxgi = LoadLibraryW(L"dxgi.dll");
        if (!dxgi) return size_t(0);
        using Create = HRESULT(WINAPI*)(REFIID, void**);
        const auto create = reinterpret_cast<Create>(GetProcAddress(dxgi, "CreateDXGIFactory1"));
        IDXGIFactory1* factory = nullptr;
        size_t most = 0;
        if (create && SUCCEEDED(create(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&factory)))) {
            IDXGIAdapter1* adapter = nullptr;
            for (UINT i = 0; factory->EnumAdapters1(i, &adapter) != DXGI_ERROR_NOT_FOUND; ++i) {
                DXGI_ADAPTER_DESC1 desc{};
                if (SUCCEEDED(adapter->GetDesc1(&desc))) most = std::max<size_t>(most, desc.DedicatedVideoMemory);
                adapter->Release();
            }
            factory->Release();
        }
        return most;
    }();
    return bytes;
}

// The prepared geometry a scene may have (cpu::Limits::bytes: its meshes' positions and triangles once tessellated and
// displaced, shared instances' once): XPU2_SESSION_GEOMETRY_MB when set (tests); else what the machine has room for,
// measured as each scene is prepared: the RAM free then, less a reserve for Windows and Modo (a tenth of the machine's,
// 4 GB at least) and for the GPU lane's pinned memory (an eighth, 2 to 8 GB), over GeometryFootprint, within the
// session's memory ceiling (memoryCeiling) and the card's memory (cardMemory), between 256 MB and 64 GB. A scene asking more falls back to XPU as it is
// prepared, where a fixed 1 GiB refused scenes the machine held easily, and more than the machine has froze it.
size_t geometryBudget() {
    if (const char* mb = std::getenv("XPU2_SESSION_GEOMETRY_MB"))
        if (const long long n = std::atoll(mb); n > 0) return std::min<size_t>(size_t(n) << 20, cpu::HardGeometryBytes);
    MEMORYSTATUSEX status{};
    status.dwLength = sizeof status;
    if (!GlobalMemoryStatusEx(&status)) return size_t(1) << 30;
    const size_t total = size_t(status.ullTotalPhys), free = size_t(status.ullAvailPhys);
    const size_t reserve = std::max<size_t>(total / 10, 4ull << 30) + std::clamp<size_t>(total / 8, 2ull << 30, 8ull << 30);
    size_t budget = (free > reserve ? free - reserve : 0) / GeometryFootprint;
    if (ceilingBytes) budget = std::min(budget, ceilingBytes / GeometryFootprint);
    // And what the card holds, less a fifth for the rest of the frame and Modo's viewport: past it the GPU's build fails,
    // only after the whole preparation.
    if (const size_t card = cardMemory()) budget = std::min(budget, (card - card / 5) / GeometryVramFootprint);
    return std::clamp<size_t>(budget, 256ull << 20, cpu::HardGeometryBytes);
}

// Where the preparation's time went (cpu::prepLaps): its stages and the parts within them, also when it stopped short.
void logPreparation(const char* how, double canonicalSeconds, double cpuSceneSeconds) {
    std::string laps;
    for (const auto& [what, s] : cpu::prepLaps().laps) {
        char text[160];
        std::snprintf(text, sizeof text, "%s%s %.2f s", laps.empty() ? "" : ", ", what.c_str(), s);
        laps += text;
    }
    if (cpuSceneSeconds >= 0)
        std::printf("XPU2: %s: canonical %.2f s; plan: %s; CPU scene %.2f s\n", how, canonicalSeconds, laps.c_str(), cpuSceneSeconds);
    else
        std::printf("XPU2: %s: canonical %.2f s; plan: %s\n", how, canonicalSeconds, laps.c_str());
    if (!cpu::prepLaps().parts.empty()) {
        std::string parts;
        for (const auto& [what, s] : cpu::prepLaps().parts) {
            char text[160];
            std::snprintf(text, sizeof text, "%s%s %.2f s", parts.empty() ? "" : ", ", what.c_str(), s);
            parts += text;
        }
        std::printf("XPU2: within the plan: %s\n", parts.c_str());
    }
    std::printf("XPU2: memory: %s\n", memoryText().c_str());
    std::fflush(stdout);
}

std::string oneLine(std::string text) {
    for (char& c : text)
        if (c == '\n' || c == '\r') c = ' ';
    return text.substr(0, 600);
}

// The renderer's files beside the executable (build_session.py lays them out): the program for every frame, its
// material module and the adaptive pass chain.
struct Programs {
    std::string uniform, material, chain, maps, lights, lobes, volumes, dwa, dwaLobes, extras;
};
Programs programs(const fs::path& folder) {
    return {fileText(folder / "async_gpu.ptx"), fileText(folder / "material" / "async_material.ptx"),
            fileText(folder / "adaptive" / "async_adaptive.ptx"), fileText(folder / "maps" / "async_maps.ptx"),
            fileText(folder / "lights" / "async_lights.ptx"), fileText(folder / "lobes" / "async_lobes.ptx"),
            fileText(folder / "volumes" / "async_volumes.ptx"), fileText(folder / "dwa" / "async_dwa.ptx"),
            fileText(folder / "dwalobes" / "async_dwalobes.ptx"), fileText(folder / "extras" / "async_extras.ptx")};
}

std::unique_ptr<async::GpuLane> gpuLane(const Programs& p, std::function<void(unsigned, unsigned)> progress = {}) {
    async::GpuOptions options;
    options.compileProgress = std::move(progress);
    options.mapsPtx = p.maps;
    options.lightsPtx = p.lights;
    options.lobesPtx = p.lobes;
    options.volumesPtx = p.volumes;
    options.dwaPtx = p.dwa;
    options.dwaLobesPtx = p.dwaLobes;
    options.extrasPtx = p.extras;
    return std::make_unique<async::GpuLane>(p.uniform, p.material, p.chain, options);
}

// OptiX hands out compile tasks whether or not its disk cache holds a program, so whether it does is kept as a mark
// of our own: a file named for the programs' text and the graphics driver (a new driver empties OptiX's cache),
// left once they have compiled.
fs::path shaderMark(const Programs& p) {
    std::uint64_t h = 1469598103934665603ull;
    auto mix = [&](const void* data, size_t n) {
        for (size_t i = 0; i < n; ++i) h = (h ^ static_cast<const unsigned char*>(data)[i]) * 1099511628211ull;
    };
    for (const std::string* s : {&p.uniform, &p.material, &p.chain, &p.maps, &p.lights, &p.lobes, &p.volumes, &p.dwa, &p.dwaLobes, &p.extras}) mix(s->data(), s->size());
    // A test build's lower OptiX optimization (XPU2_OPTIX_LEVEL, async_gpu.h) is another program in OptiX's cache.
    if (const char* level = std::getenv("XPU2_OPTIX_LEVEL")) {
        const std::string l = level;
        mix(l.data(), l.size());
    }
    // So is a diagnostic build's with OptiX's exceptions (XPU2_OPTIX_EXCEPTIONS).
    if (std::getenv("XPU2_OPTIX_EXCEPTIONS")) mix("exceptions", 10);
    wchar_t system[MAX_PATH] = {};
    GetSystemDirectoryW(system, MAX_PATH);
    WIN32_FILE_ATTRIBUTE_DATA driver{};
    if (GetFileAttributesExW((fs::path(system) / "nvcuda.dll").c_str(), GetFileExInfoStandard, &driver))
        mix(&driver.ftLastWriteTime, sizeof(driver.ftLastWriteTime)), mix(&driver.nFileSizeLow, sizeof(driver.nFileSizeLow));
    const char* local = std::getenv("LOCALAPPDATA");
    char name[32];
    std::snprintf(name, sizeof(name), "%016llx.compiled", (unsigned long long)h);
    return fs::u8path(local ? local : ".") / "MoonRayForModo" / "xpu2-shaders" / name;
}
void markCompiled(const Programs& p) {
    std::error_code ignored;
    fs::create_directories(shaderMark(p).parent_path(), ignored);
    std::ofstream(shaderMark(p)) << "compiled\n";
}

// --compile-shaders: the GPU programs into OptiX's disk cache, with progress as it goes.
int compileShaders(const fs::path& folder) {
    const auto began = Clock::now();
    auto seconds = [&] { return std::chrono::duration<double>(Clock::now() - began).count(); };
    try {
        const Programs p = programs(folder);
        std::cout << "XPU2 shaders: compiling (about an hour the first time; at once when OptiX's cache has them)"
                  << std::endl;
        double last = 0;
        gpuLane(p, [&](unsigned done, unsigned waiting) {
            if (seconds() - last < 10) return;
            last = seconds();
            std::printf("XPU2 shaders: %u compile tasks done, %u waiting, %.0f s\n", done, waiting, last);
            std::fflush(stdout);
        });
        markCompiled(p);
        std::printf("XPU2 shaders: compiled in %.0f s\n", seconds());
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "XPU2 shaders: " << e.what() << std::endl;
        return 1;
    }
}

int shadersCompiled(const fs::path& folder) {
    try {
        const bool compiled = fs::exists(shaderMark(programs(folder)));
        std::cout << (compiled ? "XPU2 shaders: compiled" : "XPU2 shaders: not compiled") << std::endl;
        return compiled ? 0 : 3;
    } catch (const std::exception& e) {
        std::cerr << "XPU2 shaders: " << e.what() << std::endl;
        return 1;
    }
}

// Without a session, the kit's MoonRay renders the scene with the same arguments.
int passThrough(int argc, char** argv) {
    const char* moonray = std::getenv("MOONRAY_XPU2_MOONRAY");
    if (!moonray) {
        std::cerr << "XPU2 renders previews only; MOONRAY_XPU2_MOONRAY names the MoonRay for the rest" << std::endl;
        return 2;
    }
    std::wstring command = L"\"" + fs::u8path(moonray).wstring() + L"\"";
    for (int i = 1; i < argc; ++i) command += L" \"" + fs::u8path(argv[i]).wstring() + L"\"";
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, TRUE, 0, nullptr, nullptr, &si, &pi)) return 2;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return int(code);
}

struct Args {
    std::vector<std::string> scenes;
    unsigned threads = 0;
};
Args parse(int argc, char** argv) {
    Args a;
    for (int i = 1; i < argc; ++i) {
        const std::string k = argv[i];
        if (k == "-in" && i + 1 < argc) a.scenes.push_back(argv[++i]);
        else if (k == "-threads" && i + 1 < argc) a.threads = unsigned(std::stoul(argv[++i]));
        else if ((k == "-out" || k == "-exec_mode") && i + 1 < argc) ++i;
    }
    return a;
}

// One file the kit names: a path, or "modo-memory:<length>:<name>", text it holds in shared memory.
void readInto(rdl::SceneContext& context, const std::string& name) {
    if (modoSceneMemory(name)) rdl::AsciiReader(context).fromString(modoReadSceneMemory(name), "@modo-memory");
    else rdl::readSceneFromFile(name, context);
}

// The scene as the kit has handed it over, and what XPU2 makes of it: the canonical copy, the plan, the CPU's
// geometry. A scene is made again only when it has changed.
struct Scene {
    fs::path dso, staging;
    std::unique_ptr<rdl::SceneContext> source;
    std::unique_ptr<CanonicalSession> canonical;
    std::uint64_t epoch = 0, frames = 0;
    fs::path lastFolder;
    cpu::PlanView plan;
    std::unique_ptr<async::CpuScene> cpuScene;
    aov::DisplayFilters displayFilters;  // the scene's display filters, MoonRay's own (aov_display.h)
    bool changed = true;
    // The camera-only fast path (realtime): whether the changes since the last preparation are the camera's alone, and
    // the plan the last camera-only one was made from (the GPU's configuration alone goes again, GpuLane::updateCamera).
    bool cameraOnly = false;
    cpu::PlanView cameraFrom;
    // Whether every object edited since the last full preparation is the camera the scene renders through (the source's
    // objects stay dirty until a full preparation has taken them into the canonical copy and commits them).
    bool onlyCameraDirty() const {
        const rdl::SceneObject* camera = source->getSceneVariables().get(rdl::SceneVariables::sCamera);
        bool cameraDirty = false;
        for (auto it = source->beginSceneObject(); it != source->endSceneObject(); ++it) {
            if (!it->second->isDirty()) continue;
            if (it->second != camera) return false;
            cameraDirty = true;
        }
        return cameraDirty;
    }

    void load(const std::vector<std::string>& files) {
        cpuScene.reset();
        plan.reset();
        canonical.reset();
        source = std::make_unique<rdl::SceneContext>();
        source->setProxyModeEnabled(true);
        source->setDsoPath(dso.string());
        for (const auto& f : files) readInto(*source, f);
        canonical.reset(new CanonicalSession(dso.string(), {3301, 0, 0, 0}));
        // The scene indexer's classification of every object (entity_classes.h).
        canonical->classifier([](const rdl::SceneObject& o) {
            const classes::Class c = classes::classify(o);
            Decision d;
            d.support = c.support;
            d.evidence = c.reason;
            d.families = c.families;
            return d;
        });
        epoch = 0;
        changed = true;
    }
    void apply(const std::string& delta) {
        readInto(*source, delta);
        changed = true;
        cameraOnly = plan && onlyCameraDirty();
    }
    // The plan for the scene as it stands; refusals throw cpu::Unsupported.
    void prepare() {
        if (!changed) return;
        cameraFrom.reset();
        // A camera-only edit: the plan as it was with its camera, render space and render origin made again
        // (cpu::updateCamera), the CPU's Embree scenes taken over; no canonical copy, no plan, until a full preparation.
        if (cameraOnly && plan && cpuScene) {
            const auto began = std::chrono::steady_clock::now();
            auto next = std::make_shared<cpu::Plan>(*plan);
            if (cpu::updateCamera(*next, *source)) {
                cameraFrom = plan;
                plan = next;
                cpuScene = std::make_unique<async::CpuScene>(plan, std::move(*cpuScene));
                changed = cameraOnly = false;
                std::printf("XPU2: the camera alone changed: prepared in %.1f ms\n",
                            std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count() * 1000.0);
                return;
            }
        }
        cameraOnly = false;
        ++epoch;
        const fs::path folder = staging / ("frame-" + std::to_string(++frames));
        const auto began = std::chrono::steady_clock::now();
        auto seconds = [](std::chrono::steady_clock::time_point from) {
            return std::chrono::duration<double>(std::chrono::steady_clock::now() - from).count();
        };
        auto frame = canonical->prepare(*source, folder, {3301, epoch, epoch, epoch});
        const double canonicalSeconds = seconds(began);
        logClasses(*frame->routing);
        // The outputs in the order the scene declared them (the canonical copy holds them by name).
        aov::outputOrder().clear();
        for (const rdl::RenderOutput* ro : source->getAllRenderOutputs()) aov::outputOrder().push_back(ro->getName());
        try {
            cpu::Limits limits;
            limits.bytes = geometryBudget();
            plan = cpu::prepare(*canonical, frame, plan, limits, assetRoot(), cpu::Domain::SurfaceTextures, true, true);
        } catch (...) {
            canonical->reject(frame);
            logPreparation("preparation stopped", canonicalSeconds, -1);
            throw;
        }
        cpu::need(canonical->acknowledge(frame) && canonical->publish(frame), "Canonical publish");
        // The source's edits are in the canonical copy now: clean, so that the next preparation reads only what is
        // edited after it (and a camera-only edit is told from the rest).
        source->commitAllChanges();
        const auto planned = std::chrono::steady_clock::now();
        // The CPU's Embree scenes kept where no mesh changed (a camera, a light, a material edited).
        if (cpuScene && cpuScene->plan && async::CpuScene::sameGeometry(*cpuScene->plan, *plan))
            cpuScene = std::make_unique<async::CpuScene>(plan, std::move(*cpuScene));
        else
            cpuScene = std::make_unique<async::CpuScene>(plan);
        // Where the preparation's time went: the canonical copy, the plan by its stages (cpu::prepLaps), the CPU's scene.
        logPreparation("prepared", canonicalSeconds, seconds(planned));
        std::printf("XPU2: geometry: %zu MB of positions and triangles, of a %zu MB budget\n", plan->bytes >> 20, geometryBudget() >> 20);
        const auto& subd = cpu::subdTimes();
        if (subd.meshes)
            std::printf("XPU2: tessellation: %lld meshes (MoonRay's subdivision and PolyMesh) in %.2f s; displacement %lld vertices, "
                        "%.2f s over %lld threads, spanning %.2f s\n",
                        (long long)subd.meshes, double(subd.tessellateNs) * 1e-9, (long long)subd.displaceCalls, double(subd.displaceNs) * 1e-9,
                        (long long)subd.threads, double(subd.last - subd.first) * 1e-9);
        displayFilters = aov::DisplayFilters();
        if (plan->aovs && !plan->aovs->displayFilters.empty())
            displayFilters.prepare(canonical->replica(), *plan->aovs, dso.string(), plan->width, plan->height);
        std::error_code ignored;
        if (!lastFolder.empty()) fs::remove_all(lastFolder, ignored);
        lastFolder = folder;
        changed = false;
    }
    // The classification's summary for the log: objects by class, the GPU families the scene's objects need on
    // each side, the objects that send the scene to MoonRay.
    static void logClasses(const Snapshot& s) {
        size_t counts[3] = {0, 0, 0};
        uint64_t gpu = 0, cpuOnly = 0;
        std::vector<std::string> fallbacks;
        for (auto it = s.decisions.begin(); it != s.decisions.end(); ++it) {
            const Decision& d = it->second;
            ++counts[static_cast<unsigned>(d.support)];
            if (d.support == Support::Both) gpu |= d.families;
            if (d.support == Support::Cpu) cpuOnly |= d.families & ~classes::GpuFamilies;
            if (d.support == Support::Fallback && fallbacks.size() < 4) fallbacks.push_back(d.evidence);
        }
        std::fprintf(stderr, "XPU2 classes: %zu both, %zu CPU only, %zu fall back; mode %s; GPU families %llx, CPU-only families %llx%s%s\n",
                     counts[2], counts[1], counts[0], s.mode == Mode::Fallback ? "fallback" : s.mode == Mode::NativeCpu ? "cpu" : "mixed",
                     (unsigned long long)gpu, (unsigned long long)cpuOnly, fallbacks.empty() ? "" : "; first: ",
                     fallbacks.empty() ? "" : fallbacks[0].c_str());
        std::fflush(stderr);
    }
    // Textures anywhere on the system drive (the asset root bounds what a texture path may be).
    static fs::path assetRoot() {
        const char* drive = std::getenv("SystemDrive");
        return fs::u8path(std::string(drive ? drive : "C:") + "\\");
    }
};

// What the frame writes when it ends: the scene's render outputs (aov_plan.h, aov_write.h), as MoonRay writes them.
// What XPU2 does not make yet leaves the scene to MoonRay.
void checkOutputs(const aov::Plan& plan, bool gpu) {
    cpu::need(!plan.deep, "Deep outputs are not rendered by XPU2 yet");
    // Checkpoints are saved (Safe Denoising). A render to be continued from a saved one starts again: MoonRay could not
    // take up XPU2's saves (they carry no progressCheckpointTileSamples), and XPU2 does not yet know which samples a
    // save holds (a pixel's may not be its first ones yet).
    if (plan.resume) std::printf("XPU2: Continue starts this render again (XPU2 does not take up a saved render yet)\n");
}

// A checkpoint render's saves (Safe Denoising), on a thread of their own so that the render goes on meanwhile: each the
// frame so far, written to its files' checkpoint names, each file reported as MoonRay reports it ("Wrote: <path>"),
// which the kit follows. A save asked for while one is being written is let go: the next one is soon.
class Checkpoints {
public:
    Checkpoints() : thread_([this] { loop(); }) {}
    ~Checkpoints() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stop_ = true;
        }
        wake_.notify_all();
        thread_.join();
    }
    // Before a frame: the plan and display filters its saves use.
    void frame(const aov::Plan* plan, aov::DisplayFilters* filters, unsigned width, unsigned height) {
        wait();
        std::lock_guard<std::mutex> lock(mutex_);
        plan_ = plan;
        filters_ = filters;
        width_ = width;
        height_ = height;
    }
    void save(async::RenderResult&& sofar) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (busy_ || !plan_) return;
        pending_ = std::move(sofar);
        busy_ = true;
        wake_.notify_all();
    }
    // Returns once no save is being written (before a frame's own files, or another scene).
    void wait() {
        std::unique_lock<std::mutex> lock(mutex_);
        done_.wait(lock, [&] { return !busy_; });
    }

private:
    void loop() {
        for (;;) {
            async::RenderResult r;
            const aov::Plan* plan;
            aov::DisplayFilters* filters;
            unsigned width, height;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                wake_.wait(lock, [&] { return stop_ || busy_; });
                if (stop_) return;
                r = std::move(pending_);
                plan = plan_;
                filters = filters_;
                width = width_;
                height = height_;
            }
            try {
                if (filters && !filters->empty()) {
                    std::vector<std::vector<float>> filtered;
                    filters->run(*plan, r, filtered);
                    size_t k = 0;
                    for (const aov::Output* out : plan->all)
                        if (out->result == aov::ResultDisplayFilter && k < filtered.size()) r.displayFilters[out->name] = std::move(filtered[k++]);
                }
                std::vector<std::string> warnings;
                const std::string error = aov::writeOutputs(*plan, r, width, height, warnings, true, [](const std::string& name) {
                    std::printf("Wrote: %s\n", name.c_str());
                    std::fflush(stdout);
                });
                if (!error.empty()) std::printf("XPU2: checkpoint not saved: %s\n", error.c_str());
            } catch (const std::exception& e) {
                std::printf("XPU2: checkpoint not saved: %s\n", e.what());
            }
            std::fflush(stdout);
            {
                std::lock_guard<std::mutex> lock(mutex_);
                busy_ = false;
            }
            done_.notify_all();
        }
    }
    std::mutex mutex_;
    std::condition_variable wake_, done_;
    bool stop_ = false, busy_ = false;
    async::RenderResult pending_;
    const aov::Plan* plan_ = nullptr;
    aov::DisplayFilters* filters_ = nullptr;
    unsigned width_ = 0, height_ = 0;
    std::thread thread_;
};

// The outlines of the work, thirty times a second, from a thread of their own.
class Outlines {
public:
    explicit Outlines(bool on) : on_(on) {
        if (on_) thread_ = std::thread([this] { loop(); });
    }
    ~Outlines() {
        stop_.store(true);
        if (thread_.joinable()) thread_.join();
    }
    void watch(const async::Renderer* renderer, const std::string& id, U32 width, U32 height) {
        std::lock_guard<std::mutex> lock(mutex_);
        renderer_ = renderer;
        id_ = id;
        width_ = width;
        height_ = height;
    }

private:
    void loop() {
        std::vector<U32> tiles, cells, live;
        while (!stop_.load()) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (renderer_) {
                    renderer_->activity(tiles, cells);
                    renderer_->liveTiles(live);
                    tell(tiles, cells, renderer_->cellSize(), live);
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(33));
        }
    }
    struct Rect {
        U32 x0, y0, x1, y1;
        bool operator<(const Rect& o) const { return std::tie(x0, y0, x1, y1) < std::tie(o.x0, o.y0, o.x1, o.y1); }
    };
    // In the film's coordinates, which are MoonRay's.
    Rect rect(U32 x0, U32 y0, U32 side) const { return {x0, y0, std::min(x0 + side, width_), std::min(y0 + side, height_)}; }
    void tell(const std::vector<U32>& tiles, const std::vector<U32>& cells, U32 cellSize, const std::vector<U32>& live) {
        const U32 tilesX = (width_ + TileSize - 1) / TileSize, cellsX = (width_ + cellSize - 1) / cellSize;
        std::vector<Rect> workers, gpuWorkers;
        for (U32 t : tiles) workers.push_back(rect(t % tilesX * TileSize, t / tilesX * TileSize, TileSize));
        for (U32 c : cells) {
            if (gpuWorkers.size() >= 512) break;
            gpuWorkers.push_back(rect(c % cellsX * cellSize, c / cellsX * cellSize, cellSize));
        }
        // The buckets are the work grid's cells (the cellular rules move workers between them): those the CPU's
        // workers are in, and those the GPU's queued launches hold.
        std::set<Rect> buckets;
        // An adaptive frame's buckets are its live tiles, the generation being sampled (runs of them along each row
        // of tiles, so a large image's cells fit the line).
        for (size_t i = 0; i < live.size() && buckets.size() < 512;) {
            size_t j = i + 1;
            while (j < live.size() && live[j] == live[j - 1] + 1 && live[j] / tilesX == live[i] / tilesX) ++j;
            const U32 x0 = live[i] % tilesX * TileSize, y0 = live[i] / tilesX * TileSize;
            buckets.insert({x0, y0, std::min((live[j - 1] % tilesX + 1) * TileSize, width_), std::min(y0 + TileSize, height_)});
            i = j;
        }
        if (!live.empty()) {
            auto line = [&](const char* kind, auto begin, auto end) {
                std::ostringstream s;
                s << kind << " " << id_ << " " << width_ << " " << height_;
                for (auto k = begin; k != end; ++k) s << " " << k->x0 << "," << k->y0 << "," << k->x1 << "," << k->y1;
                modoProtocolLine(s.str());
            };
            line("@@MODO_TILES", buckets.begin(), buckets.end());
            line("@@MODO_WORKERS", workers.begin(), workers.end());
            line("@@MODO_GPU_WORKERS", gpuWorkers.begin(), gpuWorkers.end());
            return;
        }
        for (U32 t : tiles) {
            const U32 x = t % tilesX * TileSize / cellSize * cellSize, y = t / tilesX * TileSize / cellSize * cellSize;
            buckets.insert(rect(x, y, cellSize));
        }
        for (U32 c : cells) {
            if (buckets.size() >= 512) break;
            buckets.insert(rect(c % cellsX * cellSize, c / cellsX * cellSize, cellSize));
        }
        auto line = [&](const char* kind, auto begin, auto end) {
            std::ostringstream s;
            s << kind << " " << id_ << " " << width_ << " " << height_;
            for (auto i = begin; i != end; ++i) s << " " << i->x0 << "," << i->y0 << "," << i->x1 << "," << i->y1;
            modoProtocolLine(s.str());
        };
        line("@@MODO_TILES", buckets.begin(), buckets.end());
        line("@@MODO_WORKERS", workers.begin(), workers.end());
        line("@@MODO_GPU_WORKERS", gpuWorkers.begin(), gpuWorkers.end());
    }
    bool on_;
    std::atomic<bool> stop_{false};
    std::mutex mutex_;
    const async::Renderer* renderer_ = nullptr;
    std::string id_;
    U32 width_ = 0, height_ = 0;
    std::thread thread_;
};

void fallback(const std::string& reason) {
    std::cerr << "XPU2: " << reason << std::endl;
    modoProtocolLine("@@MODO_XPU2 FALLBACK " + oneLine(reason));
}

bool envOn(const char* name, bool otherwise) {
    const char* v = std::getenv(name);
    return v ? std::string(v) == "1" : otherwise;
}

// Realtime's pictures denoised in the session, where the kit's Denoised Beauty is chosen with RT on: OptiX's denoiser
// on the GPU (async::GpuLane::Denoiser), with the first hits' albedo and normal (the kit's denoiser guides), on a
// thread of its own so that the GPU is fed meanwhile. The newest picture wins: one asked for while another is being
// denoised takes the place of any waiting. (Open Image Denoise on the CPU took 0.24 s for a 640 by 360 picture at its
// fast quality on a six-core machine, and as long again for each guide it cleans: too slow for realtime.)
class RealtimeDenoiser {
public:
    struct Picture {
        std::string id;  // the frame it is of
        U32 width = 0, height = 0;
        std::vector<float> color, albedo, normal;  // three floats a pixel each, in the film's order
        // A picture some of whose pixels no sample has reached yet is denoised at half its size (each two by two
        // pixels one) and shown at its own: filled from their neighbours, those pixels read to the denoiser as
        // detail, and it left such a picture all but as it was (a mean change of 0.0001 against 0.03 once every
        // pixel had a sample).
        U32 shownWidth = 0, shownHeight = 0;  // its size shown, where it is denoised at half
    };
    using Publish = std::function<void(const Picture&, const std::vector<float>&)>;
    RealtimeDenoiser(async::GpuLane& lane, Publish publish) : engine_(lane), half_(lane), publish_(std::move(publish)) {
        thread_ = std::thread([this] { loop(); });
    }
    ~RealtimeDenoiser() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            quit_ = true;
        }
        wake_.notify_all();
        thread_.join();
    }
    void submit(Picture&& picture) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            waiting_ = std::move(picture);
            hasWaiting_ = true;
        }
        wake_.notify_all();
    }
    // The picture waiting let go (its frame is over); the one in hand finishes, and goes out only if its frame is
    // still the one rendering.
    void drop() {
        std::lock_guard<std::mutex> lock(mutex_);
        hasWaiting_ = false;
    }
    // The picture waiting let go, and the one in hand finished.
    void flush() {
        std::unique_lock<std::mutex> lock(mutex_);
        hasWaiting_ = false;
        idle_.wait(lock, [&] { return !busy_; });
    }
    // A picture denoised on the caller's thread (a frame's last, after flush).
    bool denoise(const Picture& picture, std::vector<float>& out) {
        std::lock_guard<std::mutex> lock(deviceMutex_);
        return run(picture, out);
    }
    std::string error() {
        std::lock_guard<std::mutex> lock(deviceMutex_);
        return error_;
    }
    // The last picture's time, and the pictures denoised since asked.
    double milliseconds() const { return ms_.load(); }
    unsigned taken() { return count_.exchange(0); }

private:
    void loop() {
        for (;;) {
            Picture picture;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                wake_.wait(lock, [&] { return quit_ || hasWaiting_; });
                if (quit_) return;
                picture = std::move(waiting_);
                hasWaiting_ = false;
                busy_ = true;
            }
            std::vector<float> out;
            bool ok;
            {
                std::lock_guard<std::mutex> lock(deviceMutex_);
                ok = run(picture, out);
            }
            if (ok) publish_(picture, out);
            {
                std::lock_guard<std::mutex> lock(mutex_);
                busy_ = false;
            }
            idle_.notify_all();
        }
    }
    bool run(const Picture& p, std::vector<float>& out) {
        if (!error_.empty()) return false;
        const size_t n = size_t(p.width) * p.height * 3;
        if (!n || p.color.size() != n || p.albedo.size() != n || p.normal.size() != n) return false;
        const auto began = Clock::now();
        out.resize(n);
        // A diagnostic (XPU2_SESSION_RT_SHOW=color, albedo or normal): the denoiser's input shown in its place.
        if (const char* show = std::getenv("XPU2_SESSION_RT_SHOW")) {
            const std::string which(show);
            out = which == "albedo" ? p.albedo : which == "normal" ? p.normal : p.color;
            if (which == "normal")
                for (float& v : out) v = 0.5f * v + 0.5f;
            if (p.shownWidth) out = upscale(out, p.width, p.height, p.shownWidth, p.shownHeight);
            ++count_;
            return true;
        }
        auto& engine = p.shownWidth ? half_ : engine_;
        if (!engine.run(p.color.data(), p.albedo.data(), p.normal.data(), out.data(), p.width, p.height, error_)) return false;
        if (p.shownWidth) out = upscale(out, p.width, p.height, p.shownWidth, p.shownHeight);
        ms_.store(std::chrono::duration<double, std::milli>(Clock::now() - began).count());
        ++count_;
        return true;
    }
    // A half-size picture back at its own size, bilinearly.
    static std::vector<float> upscale(const std::vector<float>& half, U32 w, U32 h, U32 width, U32 height) {
        std::vector<float> out(size_t(width) * height * 3);
        for (U32 y = 0; y < height; ++y) {
            const float fy = std::clamp((y + 0.5f) * 0.5f - 0.5f, 0.0f, float(h - 1));
            const U32 y0 = U32(fy), y1 = std::min(y0 + 1, h - 1);
            const float ty = fy - float(y0);
            for (U32 x = 0; x < width; ++x) {
                const float fx = std::clamp((x + 0.5f) * 0.5f - 0.5f, 0.0f, float(w - 1));
                const U32 x0 = U32(fx), x1 = std::min(x0 + 1, w - 1);
                const float tx = fx - float(x0);
                for (int c = 0; c < 3; ++c) {
                    auto at = [&](U32 xx, U32 yy) { return half[(size_t(yy) * w + xx) * 3 + c]; };
                    const float top = at(x0, y0) + (at(x1, y0) - at(x0, y0)) * tx;
                    const float bottom = at(x0, y1) + (at(x1, y1) - at(x0, y1)) * tx;
                    out[(size_t(y) * width + x) * 3 + c] = top + (bottom - top) * ty;
                }
            }
        }
        return out;
    }

    async::GpuLane::Denoiser engine_, half_;
    Publish publish_;
    std::thread thread_;
    std::mutex mutex_, deviceMutex_;
    std::condition_variable wake_, idle_;
    Picture waiting_;
    bool hasWaiting_ = false, busy_ = false, quit_ = false;
    std::string error_;
    std::atomic<double> ms_{0.0};
    std::atomic<unsigned> count_{0};
};

int session(const Args& args, const fs::path& directory) {
    // The host may end without telling the renderer to: the renderer then ends itself.
    if (const char* host = std::getenv("MOONRAY_MODO_HOST")) {
        if (HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, DWORD(std::strtoul(host, nullptr, 10)))) {
            std::thread([process] {
                WaitForSingleObject(process, INFINITE);
                TerminateProcess(GetCurrentProcess(), 0);
            }).detach();
        }
    }
    const fs::path folder = executableFolder();
    const fs::path mailbox = directory / "command.txt";
    ModoSceneCommand command(std::getenv("MOONRAY_MODO_COMMAND"));
    auto waiting = [&] { return command.enabled() ? command.ready() : fs::exists(mailbox); };
    auto event = [](const char* kind, const std::string& id) { modoProtocolLine(std::string("@@MODO_SESSION ") + kind + " " + id); };
    std::string id = std::getenv("MOONRAY_MODO_GENERATION") ? std::getenv("MOONRAY_MODO_GENERATION") : "0";
    const bool useShared = std::getenv("MOONRAY_MODO_SHARED") != nullptr;
    // The investigation switches: CPU only or GPU only (0 or 1, else both), the adaptive pass chain on the GPU
    // (the fastest, its tiles unknown to the host) and the progressive pictures' interval.
    const int mode = std::getenv("XPU2_SESSION_MODE") ? std::atoi(std::getenv("XPU2_SESSION_MODE")) : 2;
    const bool deviceChain = envOn("XPU2_SESSION_CHAIN", false);
    // Partial shading (texture misses finished a level up, rendered again in full later; off: they wait for the tile).
    const bool partial = envOn("XPU2_SESSION_PARTIAL", true);
    // Adaptive frames: cellular generations (the default), or MoonRay's error trees (XPU2_SESSION_ADAPTIVE=trees).
    const bool cellular = !(std::getenv("XPU2_SESSION_ADAPTIVE") && std::string(std::getenv("XPU2_SESSION_ADAPTIVE")) == "trees");
    // Frames by sampling generations with a GPU: the CPU lane's workers take chunks too (off: the GPU takes them all).
    const bool generationsCpu = envOn("XPU2_SESSION_ADAPTIVE_CPU", true);
    const double previewSeconds = std::getenv("XPU2_SESSION_PREVIEW_MS") ? std::atof(std::getenv("XPU2_SESSION_PREVIEW_MS")) / 1000.0 : 0.1;
    std::cout << "XPU2 preview session (private test build): " << (mode == 0 ? "CPU only" : mode == 1 ? "GPU only" : "CPU and GPU")
              << ", adaptive passes " << (deviceChain ? "on the GPU" : "on the host") << std::endl;

    Scene scene;
    scene.dso = folder;
    scene.staging = directory / "xpu2";
    std::error_code ignored;
    fs::remove_all(scene.staging, ignored);
    fs::create_directories(scene.staging);
    cpu::sequenceDirectory() = folder;
    std::unique_ptr<async::GpuLane> gpu;
    std::unique_ptr<async::Renderer> renderer;
    double deviceRatio = 0;  // the lanes' measured rate ratio, from one scene's renderer to the next
    cpu::PlanView gpuPlan;
    bool gpuUsable = true;  // the GPU lane renders the scene (cpuOnly empty)
    ModoSharedImage shared;
    Outlines outlines(envOn("MOONRAY_MODO_BUCKETS", false));
    Checkpoints checkpoints;  // Safe Denoising's saves
    // Realtime's denoised pictures (RealtimeDenoiser), made once one is asked for. The shared picture is the session's
    // and the denoiser's both, one at a time; the denoiser's goes out only while its frame is the one rendering.
    std::mutex sharedMutex;
    std::string liveId;
    const bool realtimeDenoise = envOn("XPU2_SESSION_RT_DENOISE", true);
    std::unique_ptr<RealtimeDenoiser> denoiser;
    std::string denoiserError;
    try {
        scene.load(args.scenes);
    } catch (const std::exception& e) {
        fallback(std::string("the scene did not load: ") + e.what());
        return 0;
    }
    for (;;) {
        event("APPLIED", id);
        bool complete = false;
        if (!waiting()) {
            async::RenderResult result;
            try {
                const auto began = Clock::now();
                const bool fresh = scene.changed;
                // The renderer's workers hold the CPU scene that is about to be made again.
                if (fresh) {
                    outlines.watch(nullptr, id, 0, 0);
                    renderer.reset();
                }
                scene.prepare();
                if (scene.plan->aovs) checkOutputs(*scene.plan->aovs, mode != 0);
                if (mode != 0 && !gpu) {
                    const Programs p = programs(folder);
                    if (!fs::exists(shaderMark(p))) {
                        outlines.watch(nullptr, id, 0, 0);
                        fallback("XPU2's GPU programs are not compiled yet: System > Preferences > MoonRay > XPU2 (experimental) > "
                                 "Compile XPU2 Shaders (about an hour, once)");
                        return 0;
                    }
                    // Taken from OptiX's cache in a second or two. Its cache emptied (a driver update, its size limit),
                    // they would compile for an hour here: past a minute the session leaves the scene to MoonRay.
                    const auto made = Clock::now();
                    std::atomic<bool> loaded{false};
                    std::thread guard([&] {
                        for (int i = 0; i < 600 && !loaded.load(); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(100));
                        if (loaded.load()) return;
                        std::error_code gone;
                        fs::remove(shaderMark(p), gone);
                        fallback("OptiX's shader cache no longer holds XPU2's GPU programs (a new graphics driver?): "
                                 "Compile XPU2 Shaders again");
                        std::fflush(stdout);
                        TerminateProcess(GetCurrentProcess(), 0);
                    });
                    try {
                        gpu = gpuLane(p);
                    } catch (...) {
                        loaded.store(true);
                        guard.join();
                        throw;
                    }
                    loaded.store(true);
                    guard.join();
                    std::printf("XPU2: GPU programs loaded from the cache in %.2f s\n",
                                std::chrono::duration<double>(Clock::now() - made).count());
                    std::printf("XPU2: memory with the GPU lane made: %s\n", memoryText().c_str());
                }
                if (fresh) {
                    // A scene the GPU programs do not render yet (async::GpuLane::cpuOnly) renders on the CPU alone.
                    if (gpu && gpuPlan != scene.plan && scene.cameraFrom && gpuPlan == scene.cameraFrom) {
                        // A camera-only edit: the GPU's scene stays, its configuration (the camera) goes again.
                        if (gpuUsable) gpu->updateCamera(scene.plan);
                        gpuPlan = scene.plan;
                    } else if (gpu && gpuPlan != scene.plan) {
                        const std::string why = async::GpuLane::cpuOnly(scene.plan);
                        gpuUsable = why.empty();
                        const auto gpuBegan = Clock::now();
                        if (gpuUsable) gpu->prepare(scene.plan);
                        if (gpuUsable) std::printf("XPU2: GPU scene prepared in %.2f s (memory: %s)\n", std::chrono::duration<double>(Clock::now() - gpuBegan).count(), memoryText().c_str());
                        else std::printf("XPU2: the GPU leaves %s to the CPU; rendering on the CPU alone\n", why.c_str());
                        gpuPlan = scene.plan;
                    }
                    renderer = std::make_unique<async::Renderer>(scene.plan, *scene.cpuScene, gpuUsable ? gpu.get() : nullptr);
                    renderer->deviceRatio(deviceRatio);
                    std::printf("XPU2: memory with the renderer made: %s\n", memoryText().c_str());
                    // Sampling generations: uniform's samples spent where they show, or adaptive's to its target error.
                    std::printf("XPU2: scene ready in %.2f s (%ux%u, %s %u)\n", std::chrono::duration<double>(Clock::now() - began).count(),
                                scene.plan->width, scene.plan->height,
                                scene.plan->sampleBudget ? "uniform by sampling generations, on average"
                                : scene.plan->adaptive   ? "adaptive by sampling generations, at most"
                                                         : "uniform,",
                                scene.plan->sampleBudget || !scene.plan->adaptive ? scene.plan->spp : scene.plan->maxSamples);
                    // The kit's low-latency rendering (async::lowLatency): threads at the process's priority, one left free.
                    std::printf("XPU2: low-latency rendering %s\n", async::lowLatency() ? "on (threads at the renderer's priority, one free for Modo)" : "off");
                    // The sampling generations' settings (the kit's render settings, cpu_scene.h).
                    if (scene.plan->adaptive)
                        std::printf("XPU2: generations: first %u, most %u a pixel; %s; noise target %g; CPU workers %s\n",
                                    scene.plan->minSamples, scene.plan->maxSamples,
                                    !scene.plan->sampleBudget       ? "no budget (the target error ends it)"
                                    : scene.plan->budgetBySamples   ? "exactly the samples"
                                                                    : "as long as uniform would take",
                                    double(scene.plan->sampleBudget ? scene.plan->noiseTarget : scene.plan->targetError) * 10000.0,
                                    scene.plan->generationsCpu ? "on" : "off");
                }
                const U32 width = scene.plan->width, height = scene.plan->height;
                outlines.watch(renderer.get(), id, width, height);
                // The kit's control files: drain.txt and hold.txt name the render they are for.
                auto asked = [&](const char* name, std::vector<std::string>* keys) {
                    std::ifstream f(directory / name);
                    std::string which, key;
                    if (!(f >> which) || which != id) return false;
                    if (keys)
                        while (f >> key && keys->size() < 16) keys->push_back(key);
                    return true;
                };
                std::vector<std::string> holdKeys;
                bool held = false;
                async::Watch watch;
                watch.stop = waiting;
                watch.drain = [&] {
                    if (asked("drain.txt", nullptr)) {
                        fs::remove(directory / "drain.txt", ignored);
                        modoProtocolLine("Modo session: finishing with what is in hand");
                        return true;
                    }
                    if (asked("hold.txt", &holdKeys)) return held = true;
                    return false;
                };
                // Realtime: pictures as they come (the first, a quarter of the pixels, after its pass).
                watch.previewSeconds = scene.plan->realtime ? std::min(previewSeconds, 0.033) : previewSeconds;
                double lastStatus = 0;
                const auto frameStart = Clock::now();
                // The film's rows are in MoonRay's order.
                {
                    std::lock_guard<std::mutex> lock(sharedMutex);
                    liveId = id;
                }
                auto sharedReady = [&] {
                    std::lock_guard<std::mutex> lock(sharedMutex);
                    return shared.ready();
                };
                auto publish = [&](const std::vector<float>& rgb, U32 w, U32 h) {
                    std::lock_guard<std::mutex> lock(sharedMutex);
                    return useShared && shared.publish(id, "beauty", w, h, [&](size_t i, float* out) {
                        out[0] = rgb[i * 3];
                        out[1] = rgb[i * 3 + 1];
                        out[2] = rgb[i * 3 + 2];
                    });
                };
                // An output the kit asks to see (its view.txt, a key of hold.txt): /modo/preview/<key>, of at most three
                // channels, neither Cryptomatte nor deep (as the kit's MoonRay session takes it).
                auto previewOutput = [&](const std::string& key) -> const aov::Output* {
                    if (key == "beauty" || !scene.plan->aovs) return nullptr;
                    for (const aov::Output* out : scene.plan->aovs->all)
                        if (out->name == "/modo/preview/" + key && out->channels.size() <= 3 && out->result != aov::ResultCryptomatte)
                            return out;
                    return nullptr;
                };
                auto viewKey = [&]() {
                    std::string key = "beauty", selected;
                    std::ifstream view(directory / "view.txt");
                    if (std::getline(view, selected) && !selected.empty() && selected.size() <= 64 &&
                        std::all_of(selected.begin(), selected.end(), [](unsigned char c) { return std::isalnum(c) || c == '_'; }))
                        key = selected;
                    return key;
                };
                // An output's values as a picture (one channel shown grey, two with blue black).
                auto publishOutput = [&](const std::string& key, const aov::Output& out, async::RenderResult& r) {
                    if (out.result == aov::ResultDisplayFilter && !scene.displayFilters.empty() && !r.displayFilters.count(out.name)) {
                        std::vector<std::vector<float>> filtered;
                        scene.displayFilters.run(*scene.plan->aovs, r, filtered);
                        size_t k = 0;
                        for (const aov::Output* o : scene.plan->aovs->all)
                            if (o->result == aov::ResultDisplayFilter && k < filtered.size()) r.displayFilters[o->name] = std::move(filtered[k++]);
                    }
                    const size_t n = out.channels.size();
                    std::vector<float> v(std::max<size_t>(n, 3) + 8);
                    std::lock_guard<std::mutex> lock(sharedMutex);
                    return useShared && shared.publish(id, key, width, height, [&](size_t i, float* px) {
                        aov::outputValues(*scene.plan->aovs, out, r, i, v.data());
                        px[0] = v[0];
                        px[1] = n > 1 ? v[1] : v[0];
                        px[2] = n > 2 ? v[2] : n == 1 ? v[0] : 0.0f;
                    });
                };
                // Realtime with the kit's Denoised Beauty chosen: its pictures are denoised here (RealtimeDenoiser), with
                // the kit's denoiser guides, a preview's outputs, for the first hits' albedo and normal.
                auto guide = [&](const char* key) -> const aov::Output* {
                    if (!scene.plan->aovs) return nullptr;
                    for (const aov::Output* out : scene.plan->aovs->all)
                        if (out->name == std::string("/modo/preview/denoise_") + key && out->channels.size() == 3) return out;
                    return nullptr;
                };
                const aov::Output* rtAlbedo = scene.plan->realtime && realtimeDenoise ? guide("albedo") : nullptr;
                const aov::Output* rtNormal = scene.plan->realtime && realtimeDenoise ? guide("normal") : nullptr;
                auto denoising = [&](const std::string& view) {
                    return rtAlbedo && rtNormal && denoiserError.empty() && view == "denoised_beauty";
                };
                // A picture for the denoiser: the beauty and its guides, the pixels no sample has reached yet filled from
                // the nearest that have (as the progressive pictures are).
                auto realtimePicture = [&](const async::RenderResult& r) {
                    RealtimeDenoiser::Picture p;
                    p.id = id;
                    p.width = width;
                    p.height = height;
                    const size_t pixels = size_t(width) * height;
                    p.color.assign(pixels * 3, 0.0f);
                    p.albedo.assign(pixels * 3, 0.0f);
                    p.normal.assign(pixels * 3, 0.0f);
                    std::vector<unsigned char> covered(pixels, 0);
                    bool gaps = false;
                    // The normals in camera space, as OptiX's denoiser takes them: render space's (the state variable N)
                    // onto the camera's axes, the rows of its camera-to-render matrix.
                    const auto& toRender = scene.plan->camera.cameraToRender.m;
                    float axes[3][3];
                    for (int a = 0; a < 3; ++a) {
                        const float length = std::sqrt(toRender[a][0] * toRender[a][0] + toRender[a][1] * toRender[a][1] + toRender[a][2] * toRender[a][2]);
                        for (int c = 0; c < 3; ++c) axes[a][c] = length > 0 ? toRender[a][c] / length : float(a == c);
                    }
                    cpu::parallelRange(pixels, [&](size_t begin, size_t end) {
                        std::vector<float> v(16);
                        for (size_t i = begin; i < end; ++i) {
                            if (i >= r.counts.size() || !r.counts[i]) continue;
                            covered[i] = 1;
                            for (int c = 0; c < 3; ++c) {
                                const float x = r.rgba[i * 4 + c];
                                p.color[i * 3 + c] = std::isfinite(x) ? std::max(0.0f, x) : 0.0f;
                            }
                            aov::outputValues(*scene.plan->aovs, *rtAlbedo, r, i, v.data());
                            for (int c = 0; c < 3; ++c) p.albedo[i * 3 + c] = std::isfinite(v[c]) ? std::clamp(v[c], 0.0f, 1.0f) : 0.0f;
                            aov::outputValues(*scene.plan->aovs, *rtNormal, r, i, v.data());
                            for (int c = 0; c < 3; ++c) v[c] = std::isfinite(v[c]) ? v[c] : 0.0f;
                            for (int a = 0; a < 3; ++a)
                                p.normal[i * 3 + a] = std::clamp(v[0] * axes[a][0] + v[1] * axes[a][1] + v[2] * axes[a][2], -1.0f, 1.0f);
                        }
                    });
                    for (unsigned char c : covered)
                        if (!c) {
                            gaps = true;
                            break;
                        }
                    if (gaps) {
                        async::Renderer::fillGaps(p.color, covered, width, height);
                        async::Renderer::fillGaps(p.albedo, covered, width, height);
                        async::Renderer::fillGaps(p.normal, covered, width, height);
                        // Denoised at half its size (RealtimeDenoiser::Picture), each two by two pixels averaged.
                        const U32 hw = (width + 1) / 2, hh = (height + 1) / 2;
                        auto halve = [&](std::vector<float>& v) {
                            std::vector<float> half(size_t(hw) * hh * 3, 0.0f);
                            for (U32 y = 0; y < hh; ++y)
                                for (U32 x = 0; x < hw; ++x) {
                                    float sum[3] = {};
                                    int n = 0;
                                    for (U32 yy = 2 * y; yy < std::min(2 * y + 2, height); ++yy)
                                        for (U32 xx = 2 * x; xx < std::min(2 * x + 2, width); ++xx, ++n)
                                            for (int c = 0; c < 3; ++c) sum[c] += v[(size_t(yy) * width + xx) * 3 + c];
                                    for (int c = 0; c < 3; ++c) half[(size_t(y) * hw + x) * 3 + c] = sum[c] / float(std::max(n, 1));
                                }
                            v.swap(half);
                        };
                        halve(p.color);
                        halve(p.albedo);
                        halve(p.normal);
                        p.shownWidth = width;
                        p.shownHeight = height;
                        p.width = hw;
                        p.height = hh;
                    }
                    return p;
                };
                if (rtAlbedo && rtNormal && gpu && gpuUsable && !denoiser)
                    denoiser = std::make_unique<RealtimeDenoiser>(*gpu, [&](const RealtimeDenoiser::Picture& p, const std::vector<float>& out) {
                        std::lock_guard<std::mutex> lock(sharedMutex);
                        if (p.id != liveId || !useShared) return;
                        shared.publish(p.id, "denoised_beauty", p.shownWidth ? p.shownWidth : p.width, p.shownWidth ? p.shownHeight : p.height,
                                       [&](size_t i, float* px) {
                            px[0] = out[i * 3];
                            px[1] = out[i * 3 + 1];
                            px[2] = out[i * 3 + 2];
                        });
                    });
                std::string currentView = "beauty";
                watch.previewAov = [&] {
                    currentView = viewKey();
                    if (denoiser && denoiserError.empty()) denoiserError = denoiser->error();
                    return previewOutput(currentView) != nullptr || denoising(currentView);
                };
                watch.previewResult = [&](const async::RenderResult& sofar, double fraction) {
                    if (denoising(currentView) && denoiser) denoiser->submit(realtimePicture(sofar));
                    else if (const aov::Output* out = previewOutput(currentView)) {
                        async::RenderResult r = sofar;
                        publishOutput(currentView, *out, r);
                    }
                    std::ostringstream progress;
                    progress << "@@MODO_PROGRESS " << id << " " << fraction;
                    modoProtocolLine(progress.str());
                };
                watch.preview = [&](const std::vector<float>& rgb, U32 w, U32 h, double fraction) {
                    publish(rgb, w, h);
                    std::ostringstream progress;
                    progress << "@@MODO_PROGRESS " << id << " " << fraction;
                    modoProtocolLine(progress.str());
                    const double t = std::chrono::duration<double>(Clock::now() - frameStart).count();
                    if (t - lastStatus >= 1.0) {
                        lastStatus = t;
                        std::printf("XPU2: %.0f%% in %.1f s\n", fraction * 100.0, t);
                        std::fflush(stdout);
                    }
                };
                async::RenderOptions options;
                options.threads = args.threads ? args.threads : std::max(1u, std::thread::hardware_concurrency());
                options.mode = gpu && gpuUsable ? mode : 0;  // a scene the GPU leaves to the CPU (cpuOnly): the CPU alone
                options.deviceChain = deviceChain;
                options.cellular = cellular;
                options.generationsCpu = generationsCpu;
                options.partial = partial;
                options.watch = &watch;
                // Safe Denoising's checkpoints: the frame so far saved every checkpoint_interval minutes.
                if (scene.plan->aovs && scene.plan->aovs->checkpoint) {
                    checkpoints.frame(scene.plan->aovs.get(), &scene.displayFilters, width, height);
                    watch.checkpointSeconds = std::max(1.0, scene.plan->aovs->checkpointMinutes * 60.0);
                    watch.checkpoint = [&](async::RenderResult&& sofar) { checkpoints.save(std::move(sofar)); };
                }
                result = renderer->render(options);
                checkpoints.wait();  // a save under way is whole before the frame's own files, or another scene
                if (renderer->deviceRatio() > 0) deviceRatio = renderer->deviceRatio();
                if (result.seededCells)
                    std::printf("XPU2: cells by suitability: %u of %u the CPU's (%u the GPU would defer), GPU/CPU rate %.2f, probed in %.1f ms\n",
                                result.seededCpuCells, result.seededCells, result.seededDeferCells, result.seededRatio, result.seedSeconds * 1e3);
                if (result.deferred) std::printf("XPU2: %llu samples deferred to the CPU\n", (unsigned long long)result.deferred);
                // Where a frame's time went: when the grid ran out of chunks, the GPU's launches and their rate, the parked
                // samples it ran again, and the fine-detail cache's loads and evictions.
                if (result.launches)
                    std::printf("XPU2: grid empty at %.2f s of %.2f s; %llu GPU launches at %.0f samples a second; %llu parked samples run again; "
                                "fine-detail tiles loaded %llu, evicted %llu\n",
                                result.timeline.gridEmpty, result.seconds, (unsigned long long)result.launches, result.gpuItemsPerSecond,
                                (unsigned long long)result.parkedRun, (unsigned long long)result.fineLoaded, (unsigned long long)result.fineEvicted);
                if (result.gpuProfile[async::ProfileSample]) {
                    // The GPU profile (XPU2_PROFILE): each stage's share of the samples' time on the GPU.
                    const double all = double(result.gpuProfile[async::ProfileSample]);
                    const unsigned long long inStages = result.gpuProfile[async::ProfileTrace] + result.gpuProfile[async::ProfileShadow] +
                                         result.gpuProfile[async::ProfileShade] + result.gpuProfile[async::ProfilePresence] +
                                         result.gpuProfile[async::ProfileVolumes];
                    std::printf("XPU2 profile: rays %.1f%%, shadow rays %.1f%%, materials %.1f%%, presence %.1f%%, volume crossings %.1f%%, "
                                "the rest (lights, lobes, AOVs, the path tracer) %.1f%%\n",
                                100 * result.gpuProfile[async::ProfileTrace] / all, 100 * result.gpuProfile[async::ProfileShadow] / all,
                                100 * result.gpuProfile[async::ProfileShade] / all, 100 * result.gpuProfile[async::ProfilePresence] / all,
                                100 * result.gpuProfile[async::ProfileVolumes] / all, 100 * (all - double(inStages)) / all);
                }
                if (result.gpuProfile[async::ProfileCountTrace] && result.gpuSamples) {
                    // The GPU profile's rays a sample: shadow rays (light samples', BSDF samples', the rest: subsurface,
                    // volumes), those a bounce stood for, and rays traced for hits.
                    const double n = double(result.gpuSamples);
                    const auto& g = result.gpuProfile;
                    std::printf("XPU2 profile: a sample's rays: %.2f shadow (%.2f light samples', %.2f BSDF samples', %.2f others), %.2f stood for "
                                "by bounces, %.2f for hits\n",
                                g[async::ProfileCountShadow] / n, g[async::ProfileCountNee] / n, g[async::ProfileCountBsdf] / n,
                                (double(g[async::ProfileCountShadow]) - g[async::ProfileCountNee] - g[async::ProfileCountBsdf]) / n,
                                g[async::ProfileCountHeld] / n, g[async::ProfileCountTrace] / n);
                }
                if (result.provisional)
                    std::printf("XPU2: %llu provisional samples (textures read a level up while their tiles landed), rendered again in full: "
                                "%llu on the GPU, %llu on the CPU\n",
                                (unsigned long long)result.provisional, (unsigned long long)result.refinedGpu, (unsigned long long)result.refinedCpu);
                if (result.failed) {
                    outlines.watch(nullptr, id, 0, 0);
                    fallback(result.error);
                    return 0;
                }
                // Realtime's denoised pictures: the one waiting is of this frame, which is over; the frame's last is
                // denoised below, once the one in hand is out.
                if (denoiser) {
                    if (result.cancelled) denoiser->drop();
                    else denoiser->flush();
                    if (const unsigned n = denoiser->taken())
                        std::printf("XPU2: realtime: %u pictures denoised, the last in %.1f ms (OptiX)\n", n,
                                    denoiser->milliseconds());
                    const std::string error = denoiser->error();
                    if (!error.empty() && denoiserError.empty()) {
                        denoiserError = error;
                        std::printf("XPU2: realtime pictures are not denoised: %s\n", error.c_str());
                    }
                }
                if (!result.cancelled) {
                    std::vector<float> rgb(size_t(width) * height * 3);
                    for (size_t i = 0; i < size_t(width) * height; ++i)
                        for (int c = 0; c < 3; ++c) rgb[i * 3 + c] = result.rgba[i * 4 + c];
                    // The last picture waits a moment for the host to have taken the one before it.
                    const auto until = Clock::now() + std::chrono::milliseconds(held ? 3000 : 300);
                    while (useShared && !sharedReady() && Clock::now() < until) std::this_thread::sleep_for(std::chrono::milliseconds(5));
                    if (held) {
                        // The keys asked for at a stop, each when the host has taken the one before.
                        for (const auto& key : holdKeys) {
                            const auto wait = Clock::now() + std::chrono::milliseconds(3000);
                            while (useShared && !sharedReady() && Clock::now() < wait) std::this_thread::sleep_for(std::chrono::milliseconds(5));
                            if (key == "beauty") publish(rgb, width, height);
                            else if (const aov::Output* out = previewOutput(key)) publishOutput(key, *out, result);
                        }
                        fs::remove(directory / "hold.txt", ignored);
                    } else {
                        const std::string view = viewKey();
                        std::vector<float> clean;
                        if (const aov::Output* out = previewOutput(view)) publishOutput(view, *out, result);
                        else if (denoising(view) && denoiser && denoiser->denoise(realtimePicture(result), clean)) {
                            std::lock_guard<std::mutex> lock(sharedMutex);
                            if (useShared)
                                shared.publish(id, "denoised_beauty", width, height, [&](size_t i, float* px) {
                                    px[0] = clean[i * 3];
                                    px[1] = clean[i * 3 + 1];
                                    px[2] = clean[i * 3 + 2];
                                });
                        } else publish(rgb, width, height);
                        if (scene.plan->aovs) {
                            std::vector<std::string> warnings;
                            if (!scene.displayFilters.empty()) {
                                std::vector<std::vector<float>> filtered;
                                scene.displayFilters.run(*scene.plan->aovs, result, filtered);
                                size_t k = 0;
                                for (const aov::Output* out : scene.plan->aovs->all)
                                    if (out->result == aov::ResultDisplayFilter && k < filtered.size())
                                        result.displayFilters[out->name] = std::move(filtered[k++]);
                            }
                            const std::string error = aov::writeOutputs(*scene.plan->aovs, result, width, height, warnings);
                            for (const auto& w : warnings) std::puts(("XPU2: " + w).c_str());
                            cpu::need(error.empty(), error);
                        }
                        complete = true;
                        std::printf("XPU2: %s in %.2f s (CPU %llu samples, GPU %llu)\n", result.drained ? "drained" : "finished",
                                    result.seconds, (unsigned long long)result.cpuSamples, (unsigned long long)result.gpuSamples);
                        std::printf("XPU2: memory: %s; GPU lane %s\n", memoryText().c_str(), gpu ? gpu->memoryText().c_str() : "none");
                    }
                }
                outlines.watch(nullptr, id, 0, 0);
            } catch (const std::exception& e) {
                outlines.watch(nullptr, id, 0, 0);
                fallback(e.what());
                return 0;
            }
        }
        event(complete ? "DONE" : "CANCELED", id);
        while (!waiting()) std::this_thread::sleep_for(std::chrono::milliseconds(20));
        std::string mode_, delta, full;
        {
            std::ifstream file;
            std::istringstream memory;
            if (command.enabled()) memory.str(command.receive());
            else file.open(mailbox);
            std::istream& input = command.enabled() ? static_cast<std::istream&>(memory) : static_cast<std::istream&>(file);
            if (!std::getline(input, id) || !std::getline(input, mode_) || !std::getline(input, delta) || !std::getline(input, full)) {
                fallback("an incomplete Modo session command");
                return 1;
            }
        }
        if (!command.enabled()) fs::remove(mailbox, ignored);
        if (mode_ == "quit") return 0;
        try {
            if (mode_ == "full") {
                std::vector<std::string> list;
                for (size_t at = 0;;) {
                    const size_t bar = full.find('|', at);
                    list.push_back(full.substr(at, bar == std::string::npos ? std::string::npos : bar - at));
                    if (bar == std::string::npos) break;
                    at = bar + 1;
                }
                scene.load(list);
                event("RELOADED", id);
            } else if (mode_ == "delta") {
                scene.apply(delta);
            } else {
                fallback("an unknown Modo session command");
                return 1;
            }
        } catch (const std::exception& e) {
            fallback(std::string("the scene did not load: ") + e.what());
            return 0;
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    const fs::path folder = executableFolder();
    if (argc == 2 && std::string(argv[1]) == "--compile-shaders") return compileShaders(folder);
    if (argc == 2 && std::string(argv[1]) == "--shaders-compiled") return shadersCompiled(folder);
    const char* directory = std::getenv("MOONRAY_MODO_SESSION");
    if (!directory) return passThrough(argc, argv);
    memoryCeiling();
    try {
        return session(parse(argc, argv), fs::u8path(directory));
    } catch (const std::bad_alloc&) {
        // Its memory ceiling (memoryCeiling) refused it more: the scene goes to XPU, the machine is left alone.
        fallback("XPU2 ran out of the memory it may use (" + memoryText() + ")");
        return 0;
    } catch (const std::exception& e) {
        fallback(e.what());
        return 0;
    }
}
