// XPU2's preview session for MoonRay for Modo, a private test build: the kit's persistent preview protocol v1
// (native-port/persistent_session.inc) rendered by the asynchronous renderer. No Modo API.
//
//   moonray_xpu2 -in <scene> [-in <scene> ...] -out <image> -exec_mode <mode> [-info] [-threads <n>]
//       With MOONRAY_MODO_SESSION set, the preview session; without it, the kit's own MoonRay renders the scene
//       (MOONRAY_XPU2_MOONRAY names its moonray.exe).
//   moonray_xpu2 --compile-shaders
//       Compiles the GPU programs into OptiX's disk cache, printing progress: about an hour the first time, then
//       cached for every session after.
//   moonray_xpu2 --shaders-compiled
//       Exits 0 when the GPU programs are in OptiX's cache, 3 when they are not.
//
// Where XPU2 does not render a scene (PATH_TRACER.md says what it renders), its GPU programs are not compiled yet,
// or the GPU fails, the session prints "@@MODO_XPU2 FALLBACK <reason>" and ends: the kit then starts MoonRay in its
// place. The picture goes out through shared memory with its rows in MoonRay's film order, and the outlines of the work as @@MODO_TILES (snapped to the bucket size) and @@MODO_WORKERS: each CPU worker's
// 8-pixel tile, and the work grid's cells that the GPU's queued launches hold.
#include "async_render.h"
#include "../../native-port/modo_bucket_size.h"
#include "../../native-port/modo_protocol_line.h"
#include "../../native-port/modo_scene_memory.h"
#include "../../native-port/modo_shared_image.h"
#include <OpenImageIO/imageio.h>
#include <scene_rdl2/scene/rdl2/RenderOutput.h>
#include <scene_rdl2/scene/rdl2/rdl2.h>
#include <fstream>
#include <iostream>
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

std::string oneLine(std::string text) {
    for (char& c : text)
        if (c == '\n' || c == '\r') c = ' ';
    return text.substr(0, 600);
}

// The renderer's files beside the executable (build_session.py lays them out).
struct Programs {
    std::string uniform, adaptive, chain;
};
Programs programs(const fs::path& folder) {
    return {fileText(folder / "async_gpu.ptx"), fileText(folder / "adaptive" / "async_gpu.ptx"),
            fileText(folder / "adaptive" / "async_adaptive.ptx")};
}

std::unique_ptr<async::GpuLane> gpuLane(const Programs& p, bool cachedOnly,
                                        std::function<void(unsigned, unsigned)> progress = {}) {
    async::GpuOptions options;
    options.cachedOnly = cachedOnly;
    options.compileProgress = std::move(progress);
    return std::make_unique<async::GpuLane>(p.uniform, p.adaptive, p.chain, options);
}

// --compile-shaders: the GPU programs into OptiX's disk cache, with progress as it goes.
int compileShaders(const fs::path& folder) {
    const auto began = Clock::now();
    auto seconds = [&] { return std::chrono::duration<double>(Clock::now() - began).count(); };
    try {
        const Programs p = programs(folder);
        try {
            gpuLane(p, true);
            std::cout << "XPU2 shaders: already compiled" << std::endl;
            return 0;
        } catch (const async::NotCompiled&) {
        }
        std::cout << "XPU2 shaders: compiling (about an hour the first time; later sessions take them from the cache)"
                  << std::endl;
        double last = -1;
        gpuLane(p, false, [&](unsigned done, unsigned waiting) {
            if (seconds() - last < 10) return;
            last = seconds();
            std::printf("XPU2 shaders: %u compile tasks done, %u waiting, %.0f s\n", done, waiting, last);
            std::fflush(stdout);
        });
        std::printf("XPU2 shaders: compiled in %.0f s\n", seconds());
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "XPU2 shaders: " << e.what() << std::endl;
        return 1;
    }
}

int shadersCompiled(const fs::path& folder) {
    try {
        gpuLane(programs(folder), true);
        std::cout << "XPU2 shaders: compiled" << std::endl;
        return 0;
    } catch (const async::NotCompiled&) {
        std::cout << "XPU2 shaders: not compiled" << std::endl;
        return 3;
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
    bool changed = true;

    void load(const std::vector<std::string>& files) {
        cpuScene.reset();
        plan.reset();
        canonical.reset();
        source = std::make_unique<rdl::SceneContext>();
        source->setProxyModeEnabled(true);
        source->setDsoPath(dso.string());
        for (const auto& f : files) readInto(*source, f);
        canonical.reset(new CanonicalSession(dso.string(), {3301, 0, 0, 0}));
        epoch = 0;
        changed = true;
    }
    void apply(const std::string& delta) {
        readInto(*source, delta);
        changed = true;
    }
    // The plan for the scene as it stands; refusals throw cpu::Unsupported.
    void prepare() {
        if (!changed) return;
        ++epoch;
        const fs::path folder = staging / ("frame-" + std::to_string(++frames));
        auto frame = canonical->prepare(*source, folder, {3301, epoch, epoch, epoch});
        try {
            plan = cpu::prepare(*canonical, frame, plan, cpu::Limits{}, assetRoot(), cpu::Domain::SurfaceTextures, true, true);
        } catch (...) {
            canonical->reject(frame);
            throw;
        }
        cpu::need(canonical->acknowledge(frame) && canonical->publish(frame), "Canonical publish");
        cpuScene = std::make_unique<async::CpuScene>(plan);
        std::error_code ignored;
        if (!lastFolder.empty()) fs::remove_all(lastFolder, ignored);
        lastFolder = folder;
        changed = false;
    }
    // Textures anywhere on the system drive (the asset root bounds what a texture path may be).
    static fs::path assetRoot() {
        const char* drive = std::getenv("SystemDrive");
        return fs::u8path(std::string(drive ? drive : "C:") + "\\");
    }
};

// What the frame writes when it ends: the scene's render outputs, its beauty (RGB) and alpha (A).
struct Output {
    std::string file;
    int result = 0;
    bool half = false;
    int compression = 1;
};
std::vector<Output> outputs(const rdl::SceneContext& context) {
    std::vector<Output> list;
    for (auto i = context.beginSceneObject(); i != context.endSceneObject(); ++i) {
        const rdl::SceneObject* o = i->second;
        if (!o->isA<rdl::RenderOutput>()) continue;
        const auto* r = o->asA<rdl::RenderOutput>();
        if (!r->getActive()) continue;
        const int result = int(r->getResult());
        cpu::need(result == 0 || result == 1,
                  o->getName() + ": XPU2 renders the beauty and alpha only; this render output needs MoonRay");
        list.push_back({r->getFileName(), result, r->getChannelFormat() == rdl::RenderOutput::CHANNEL_FORMAT_HALF, int(r->getCompression())});
    }
    return list;
}
void writeOutput(const Output& out, const std::vector<float>& rgba, U32 width, U32 height) {
    // The film's rows run from the bottom, an EXR's from the top (as MoonRay writes it).
    const int channels = out.result == 0 ? 3 : 1;
    std::vector<float> data(size_t(width) * height * channels);
    for (size_t y = 0; y < height; ++y)
        for (size_t x = 0; x < width; ++x)
            for (int c = 0; c < channels; ++c)
                data[((height - 1 - y) * width + x) * channels + c] = rgba[(y * width + x) * 4 + (out.result == 0 ? c : 3)];
    OIIO::ImageSpec spec(int(width), int(height), channels, out.half ? OIIO::TypeDesc::HALF : OIIO::TypeDesc::FLOAT);
    spec.channelnames = out.result == 0 ? std::vector<std::string>{"R", "G", "B"} : std::vector<std::string>{"A"};
    static const char* const compressions[] = {"none", "zip", "rle", "zips", "piz", "pxr24", "b44", "b44a", "dwaa", "dwab"};
    spec.attribute("compression", compressions[out.compression >= 0 && out.compression < 10 ? out.compression : 1]);
    auto file = OIIO::ImageOutput::create(out.file);
    cpu::need(file && file->open(out.file, spec), "Cannot write " + out.file);
    cpu::need(file->write_image(OIIO::TypeDesc::FLOAT, data.data()) && file->close(), "Cannot write " + out.file);
}

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
        std::vector<U32> tiles, cells;
        while (!stop_.load()) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (renderer_) {
                    renderer_->activity(tiles, cells);
                    tell(tiles, cells, renderer_->cellSize());
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
    void tell(const std::vector<U32>& tiles, const std::vector<U32>& cells, U32 cellSize) {
        const U32 tilesX = (width_ + TileSize - 1) / TileSize, cellsX = (width_ + cellSize - 1) / cellSize;
        std::vector<Rect> workers;
        for (U32 t : tiles) workers.push_back(rect(t % tilesX * TileSize, t / tilesX * TileSize, TileSize));
        for (U32 c : cells) {
            if (workers.size() >= 512) break;
            workers.push_back(rect(c % cellsX * cellSize, c / cellsX * cellSize, cellSize));
        }
        const U32 size = modoBucketSize(width_, height_);
        std::set<Rect> buckets;
        for (const Rect& r : workers)
            for (U32 y = r.y0 / size * size; y < r.y1 && buckets.size() < 512; y += size)
                for (U32 x = r.x0 / size * size; x < r.x1 && buckets.size() < 512; x += size)
                    buckets.insert({x, y, std::min(x + size, width_), std::min(y + size, height_)});
        auto line = [&](const char* kind, auto begin, auto end) {
            std::ostringstream s;
            s << kind << " " << id_ << " " << width_ << " " << height_;
            for (auto i = begin; i != end; ++i) s << " " << i->x0 << "," << i->y0 << "," << i->x1 << "," << i->y1;
            modoProtocolLine(s.str());
        };
        line("@@MODO_TILES", buckets.begin(), buckets.end());
        line("@@MODO_WORKERS", workers.begin(), workers.end());
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
    cpu::PlanView gpuPlan;
    ModoSharedImage shared;
    Outlines outlines(envOn("MOONRAY_MODO_BUCKETS", false));
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
            std::vector<Output> files;
            try {
                const auto began = Clock::now();
                const bool fresh = scene.changed;
                // The renderer's workers hold the CPU scene that is about to be made again.
                if (fresh) {
                    outlines.watch(nullptr, id, 0, 0);
                    renderer.reset();
                }
                scene.prepare();
                files = outputs(*scene.source);
                if (mode != 0 && !gpu) {
                    const auto made = Clock::now();
                    gpu = gpuLane(programs(folder), true);
                    std::printf("XPU2: GPU programs loaded from the cache in %.2f s\n",
                                std::chrono::duration<double>(Clock::now() - made).count());
                }
                if (fresh) {
                    if (gpu && gpuPlan != scene.plan) {
                        gpu->prepare(scene.plan);
                        gpuPlan = scene.plan;
                    }
                    renderer = std::make_unique<async::Renderer>(scene.plan, *scene.cpuScene, gpu.get());
                    std::printf("XPU2: scene ready in %.2f s (%ux%u, %s %u)\n", std::chrono::duration<double>(Clock::now() - began).count(),
                                scene.plan->width, scene.plan->height, scene.plan->adaptive ? "adaptive, at most" : "uniform,",
                                scene.plan->spp);
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
                watch.previewSeconds = previewSeconds;
                double lastStatus = 0;
                const auto frameStart = Clock::now();
                // The film's rows are in MoonRay's order.
                auto publish = [&](const std::vector<float>& rgb, U32 w, U32 h) {
                    return useShared && shared.publish(id, "beauty", w, h, [&](size_t i, float* out) {
                        out[0] = rgb[i * 3];
                        out[1] = rgb[i * 3 + 1];
                        out[2] = rgb[i * 3 + 2];
                    });
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
                options.mode = gpu ? mode : 0;
                options.deviceChain = deviceChain;
                options.watch = &watch;
                result = renderer->render(options);
                if (result.failed) {
                    outlines.watch(nullptr, id, 0, 0);
                    fallback(result.error);
                    return 0;
                }
                if (!result.cancelled) {
                    std::vector<float> rgb(size_t(width) * height * 3);
                    for (size_t i = 0; i < size_t(width) * height; ++i)
                        for (int c = 0; c < 3; ++c) rgb[i * 3 + c] = result.rgba[i * 4 + c];
                    // The last picture waits a moment for the host to have taken the one before it.
                    const auto until = Clock::now() + std::chrono::milliseconds(held ? 3000 : 300);
                    while (useShared && !shared.ready() && Clock::now() < until) std::this_thread::sleep_for(std::chrono::milliseconds(5));
                    if (held) {
                        for (const auto& key : holdKeys)
                            if (key == "beauty") publish(rgb, width, height);
                        fs::remove(directory / "hold.txt", ignored);
                    } else {
                        publish(rgb, width, height);
                        for (const auto& f : files) writeOutput(f, result.rgba, width, height);
                        complete = true;
                        std::printf("XPU2: %s in %.2f s (CPU %llu samples, GPU %llu)\n", result.drained ? "drained" : "finished",
                                    result.seconds, (unsigned long long)result.cpuSamples, (unsigned long long)result.gpuSamples);
                    }
                }
                outlines.watch(nullptr, id, 0, 0);
            } catch (const async::NotCompiled&) {
                outlines.watch(nullptr, id, 0, 0);
                fallback("XPU2's GPU programs are not compiled yet: System > Preferences > MoonRay > Compile XPU2 Shaders (about an hour, once)");
                return 0;
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
    try {
        return session(parse(argc, argv), fs::u8path(directory));
    } catch (const std::exception& e) {
        fallback(e.what());
        return 0;
    }
}
