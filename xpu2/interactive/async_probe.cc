// Timing and image worker for the asynchronous renderer. No Modo API.
//
// async_probe scene runtime ptx assets output threads repeats mode
//             [cellSize samplesPerChunk windowMs seed sampling]
// mode: 0 CPU only, 1 GPU only, 2 both. Writes run-<i>.rgba (raw float32 RGBA)
// into output and prints one JSON report.
#include "async_render.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;
namespace rdl = scene_rdl2::rdl2;
using Clock = std::chrono::steady_clock;

static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

int main(int argc, char** argv) {
    try {
        cpu::need(argc >= 9 && argc <= 14, "scene runtime ptx assets output threads repeats mode [cell spc window seed sampling]");
        const auto began = Clock::now();
        const fs::path out(argv[5]);
        const unsigned threads = unsigned(std::stoul(argv[6])), repeats = unsigned(std::stoul(argv[7]));
        const int mode = std::stoi(argv[8]);
        cpu::need(threads >= 1 && threads <= 64 && repeats >= 1 && repeats <= 16 && mode >= 0 && mode <= 2, "Probe bounds");
        async::RenderOptions options;
        options.threads = threads;
        options.mode = mode;
        if (argc > 9) options.grid.cellSize = unsigned(std::stoul(argv[9]));
        if (argc > 10) options.grid.samplesPerChunk = unsigned(std::stoul(argv[10]));
        if (argc > 11) options.windowMs = std::stod(argv[11]);
        if (const char* v = std::getenv("XPU2_ASYNC_NO_RESERVE")) options.reserveFeederCore = std::string(v) != "1";

        std::ifstream file(argv[3], std::ios::binary);
        cpu::need(bool(file), "PTX read");
        const std::string ptx((std::istreambuf_iterator<char>(file)), {});

        auto stamp = Clock::now();
        rdl::SceneContext source;
        source.setProxyModeEnabled(true);
        source.setDsoPath(argv[2]);
        rdl::readSceneFromFile(argv[1], source);
        const double readSeconds = since(stamp);

        stamp = Clock::now();
        CanonicalSession canonical(argv[2], {3301, 0, 0, 0});
        auto frame = canonical.prepare(source, out / "canonical", {3301, 1, 1, 1});
        auto plan = cpu::prepare(canonical, frame, {}, cpu::Limits{}, argv[4], cpu::Domain::SurfaceTextures);
        auto chosen = std::make_shared<cpu::Plan>(*plan);
        if (argc > 12) chosen->seed = unsigned(std::stoul(argv[12]));
        if (argc > 13) chosen->sampling = unsigned(std::stoul(argv[13]));
        cpu::need(chosen->sampling <= 3, "Sampling policy");
        plan = chosen;
        cpu::need(canonical.acknowledge(frame) && canonical.publish(frame), "Canonical publish");
        const double planSeconds = since(stamp);

        stamp = Clock::now();
        async::CpuScene cpuScene(plan);
        const double embreeSeconds = since(stamp);

        stamp = Clock::now();
        std::unique_ptr<async::GpuLane> gpu;
        if (mode != 0) {
            gpu = std::make_unique<async::GpuLane>(ptx);
            gpu->prepare(plan);
        }
        const double gpuSeconds = since(stamp);

        Json::Value report;
        report["renderer"] = "asynchronous: cellular grid, CPU and GPU lanes, device film";
        report["width"] = plan->width;
        report["height"] = plan->height;
        report["spp"] = plan->spp;
        report["threads"] = threads;
        report["mode"] = mode;
        report["cell_size"] = options.grid.cellSize;
        report["samples_per_chunk"] = options.grid.samplesPerChunk;
        report["window_ms"] = options.windowMs;
        report["seed"] = plan->seed;
        report["sampling_policy"] = plan->sampling;
        report["read_seconds"] = readSeconds;
        report["plan_seconds"] = planSeconds;
        report["embree_seconds"] = embreeSeconds;
        report["gpu_prepare_seconds"] = gpuSeconds;
        report["prepare_seconds"] = since(began);
        if (gpu) {
            report["fine_tiles"] = Json::UInt64(gpu->fineTiles());
            report["resident_mip_bytes"] = Json::UInt64(gpu->residentMipBytes());
        }

        async::Renderer renderer(plan, cpuScene, gpu.get());
        for (unsigned i = 0; i < repeats; ++i) {
            const auto r = renderer.render(options);
            cpu::need(!r.failed, r.error.empty() ? "Render failed" : r.error);
            const fs::path raw = out / ("run-" + std::to_string(i) + ".rgba");
            std::ofstream o(raw, std::ios::binary);
            o.write(reinterpret_cast<const char*>(r.rgba.data()), r.rgba.size() * sizeof(float));
            cpu::need(bool(o), "Image write");
            Json::Value row;
            row["index"] = i;
            row["sampling_seconds"] = r.seconds;
            row["cpu_samples"] = Json::UInt64(r.cpuSamples);
            row["gpu_samples"] = Json::UInt64(r.gpuSamples);
            row["gpu_share"] = double(r.gpuSamples) / double(r.cpuSamples + r.gpuSamples);
            row["launches"] = Json::UInt64(r.launches);
            row["parked_run"] = Json::UInt64(r.parkedRun);
            row["cpu_steals"] = Json::UInt64(r.cpuSteals);
            row["cpu_moves"] = Json::UInt64(r.cpuMoves);
            row["gpu_stolen_chunks"] = Json::UInt64(r.gpuStolenChunks);
            row["fine_loaded"] = Json::UInt64(r.fineLoaded);
            row["fine_evicted"] = Json::UInt64(r.fineEvicted);
            row["gpu_items_per_second"] = r.gpuItemsPerSecond;
            row["cpu_samples_per_second"] = r.cpuSamplesPerSecond;
            row["cpu_workers"] = r.cpuWorkers;
            row["cpu_busy_seconds"] = r.cpuBusySeconds;
            row["cpu_slowest_chunk"] = r.cpuSlowestChunk;
            row["cpu_first_claim"] = r.cpuFirstClaim;
            row["cpu_last_claim"] = r.cpuLastClaim;
            Json::Value timeline;
            timeline["first_launch"] = r.timeline.firstLaunch;
            timeline["grid_empty"] = r.timeline.gridEmpty;
            timeline["cpu_done"] = r.timeline.cpuDone;
            timeline["last_gpu_completion"] = r.timeline.lastGpuCompletion;
            timeline["film_landed"] = r.timeline.filmLanded;
            row["timeline"] = timeline;
            row["raw_file"] = raw.string();
            report["runs"].append(row);
        }
        if (gpu) {
            report["peak_device_bytes"] = Json::UInt64(gpu->driver.peakDevice);
            report["peak_pinned_bytes"] = Json::UInt64(gpu->driver.peakPinned);
        }
        report["status"] = "passed";
        Json::StreamWriterBuilder b;
        b["indentation"] = "";
        std::cout << Json::writeString(b, report) << std::endl;
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << std::endl;
        return 1;
    }
}
