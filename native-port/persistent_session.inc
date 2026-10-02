// MoonRayForModo persistent preview protocol v1. Included after the CLI class.
// Scene mutations and start/stop always execute on the driver's owning thread.
#include <filesystem>
#include <fstream>
#include <thread>
#include <chrono>
#include <memory>

void moonray::RaasCommandLineApplication::renderPersistent(const std::string& directory)
{
    namespace fs = std::filesystem;
    const auto mailbox = fs::u8path(directory) / "command.txt";
    auto waiting = [&]() { return fs::exists(mailbox); };
    auto event = [](const char* kind, const std::string& id) {
        std::cout << "\n@@MODO_SESSION " << kind << " " << id << std::endl;
    };
    std::string id = std::getenv("MOONRAY_MODO_GENERATION") ? std::getenv("MOONRAY_MODO_GENERATION") : "0";
    std::unique_ptr<rndr::RenderContext> context;
    auto load = [&]() {
        context.reset();
        context.reset(new rndr::RenderContext(mOptions, &mInitMessages));
        context->initialize(mInitMessages, rndr::RenderContext::LoggingConfiguration::ATHENA_DISABLED);
        context->setRenderMode(rndr::RenderMode::BATCH);
        context->setRenderPrepCallBack({}, waiting);
    };
    load();
    for (;;) {
        event("APPLIED", id);
        bool complete = false;
        bool requireReload = false;
        if (!waiting()) {
            const auto prep = context->startFrame();
            if (prep == rndr::RenderContext::RP_RESULT::FINISHED) {
                auto driver = rndr::getRenderDriver();
                while (!context->isFrameComplete() && !waiting()) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                    printStatusLine(*context, driver->getLastFrameMcrtStartTime(), false);
                }
                complete = context->isFrameComplete() && !waiting();
                context->stopFrame();
            } else {
                // Render preparation can leave partial geometry. Recover from the full snapshot.
                requireReload = true;
            }
        }
        if (complete) {
            renderOutput(*context);
            event("DONE", id);
        } else {
            event("CANCELED", id);
        }
        while (!waiting()) std::this_thread::sleep_for(std::chrono::milliseconds(50));
        std::string mode, delta, full;
        {
            std::ifstream input(mailbox);
            if (!std::getline(input,id) || !std::getline(input,mode) ||
                !std::getline(input,delta) || !std::getline(input,full))
                throw std::runtime_error("Incomplete Modo session command");
        }
        fs::remove(mailbox);
        if (mode == "quit") return;
        if (mode == "full" || (mode == "delta" && requireReload)) {
            mOptions.setSceneFiles({full});
            load();
            event("RELOADED", id);
        } else if (mode == "delta") {
            // Use the same update -> startFrame path as the upstream CLI's -deltas.
            // startFrame regenerates changed geometry and rebuilds acceleration as needed.
            context->updateScene(delta);
        } else throw std::runtime_error("Unknown Modo session command");
    }
}
