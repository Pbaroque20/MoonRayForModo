// MoonRayForModo persistent preview protocol v1. Included after the CLI class.
// Scene mutations and start/stop always execute on the driver's owning thread.
#include <filesystem>
#include <fstream>
#include <thread>
#include <chrono>
#include <memory>
#include <scene_rdl2/common/fb_util/FbTypes.h>
#include <scene_rdl2/common/fb_util/VariablePixelBuffer.h>
#include <moonray/rendering/rndr/RenderOutputDriver.h>
#include <cctype>
#include <cmath>
#include <limits>
#include <vector>
#include "modo_bucket_output.h"
#include "modo_shared_image.h"
#include "modo_scene_memory.h"

void moonray::RaasCommandLineApplication::renderPersistent(const std::string& directory)
{
    namespace fs = std::filesystem;
    const auto mailbox = fs::u8path(directory) / "command.txt";
    ModoSceneCommand command(std::getenv("MOONRAY_MODO_COMMAND"));
    auto waiting = [&]() { return command.enabled()?command.ready():fs::exists(mailbox); };
    auto event = [](const char* kind, const std::string& id) {
        std::cout << "\n@@MODO_SESSION " << kind << " " << id << std::endl;
    };
    std::string id = std::getenv("MOONRAY_MODO_GENERATION") ? std::getenv("MOONRAY_MODO_GENERATION") : "0";
    std::unique_ptr<rndr::RenderContext> context;
    auto load = [&]() {
        context.reset();
        context.reset(new rndr::RenderContext(mOptions, &mInitMessages));
        context->initialize(mInitMessages, rndr::RenderContext::LoggingConfiguration::ATHENA_DISABLED);
        context->setRenderMode(rndr::RenderMode::PROGRESSIVE);
        std::cout << "Modo native progressive preview / worker tiles" << std::endl;
        context->setRenderPrepCallBack({}, waiting);
    };
    load();
    ModoSharedImage sharedImage;
    const bool useShared=std::getenv("MOONRAY_MODO_SHARED")!=nullptr;
    for (;;) {
        event("APPLIED", id);
        bool complete = false;
        bool requireReload = false;
        if (!waiting()) {
            const auto prep = context->startFrame();
            if (prep == rndr::RenderContext::RP_RESULT::FINISHED) {
                auto driver = rndr::getRenderDriver();
                const char* tileNames[]={"Top to bottom","Bottom to top","Left to right","Right to left","Morton","Random","Spiral square","Spiral rectangle","Morton shift / flip"};
                const unsigned tileOrder=driver->getFrameState().mTileSchedulerType;
                std::cout << "MoonRay tile dispatch order: " << (tileOrder<9?tileNames[tileOrder]:"Unknown")
                          << "; adaptive skipping and parallel completion can appear scattered." << std::endl;
                auto lastSnapshot = std::chrono::steady_clock::now();
                unsigned lastFilmActivity=0;
                bool published=false;
                std::string lastView;
                auto selectedView=[&]() {
                    std::string key="beauty",selected;
                    std::ifstream view(fs::u8path(directory)/"view.txt");
                    if(std::getline(view,selected) && !selected.empty() && selected.size()<=64 &&
                       std::all_of(selected.begin(),selected.end(),[](unsigned char c){return std::isalnum(c)||c=='_';}))key=selected;
                    return key;
                };
                bool reportedMissingSamples=false;
                // The last value shown for each pixel of a view. A pixel a worker was adding to
                // while its picture was taken can be caught part way, lighter or darker than it
                // is; such a pixel keeps the value it last had when it was at rest.
                std::string steadyView;
                std::vector<float> steady;

                auto snapshot = [&](const std::string& key) -> bool {
                    if(useShared && !sharedImage.ready())return false;
                    const auto preview=fs::u8path(directory)/("preview_"+id+"_"+key+".pfm");
                    if (fs::exists(preview) || !context->isFrameReadyForDisplay()) return false;
                    // Snapshot sample coverage BEFORE color. Coverage alpha is unrelated:
                    // the environment can have zero alpha and valid, sampled RGB.
                    scene_rdl2::fb_util::FloatBuffer sampleWeights;
                    driver->snapshotWeightBuffer(&sampleWeights, true, false);
                    scene_rdl2::fb_util::RenderBuffer pixels;
                    context->snapshotRenderBuffer(&pixels, true, false, false);
                    if (!pixels.getWidth() || !pixels.getHeight()) return false;
                    scene_rdl2::fb_util::VariablePixelBuffer aov;
                    unsigned channels=0;
                    if (key!="beauty") {
                        const auto* outputs=context->getRenderOutputDriver();
                        for (unsigned i=0;i<outputs->getNumberOfRenderOutputs();++i) {
                            if (outputs->getRenderOutput(i)->getName()!="/modo/preview/"+key) continue;
                            if (outputs->requiresDeepBuffer(i)||outputs->requiresCryptomatteBuffer(i)) break;
                            scene_rdl2::fb_util::HeatMapBuffer heat;
                            scene_rdl2::fb_util::FloatBuffer weight;
                            scene_rdl2::fb_util::RenderBuffer odd;
                            if(outputs->requiresHeatMap(i))context->snapshotHeatMapBuffer(&heat,true,false);
                            if(outputs->requiresWeightBuffer(i))context->snapshotWeightBuffer(&weight,true,false);
                            if(outputs->requiresRenderBufferOdd(i))context->snapshotRenderBufferOdd(&odd,true,false);
                            context->snapshotRenderOutput(&aov,i,&pixels,&pixels,
                                outputs->requiresHeatMap(i)?&heat:nullptr,outputs->requiresWeightBuffer(i)?&weight:nullptr,
                                outputs->requiresRenderBufferOdd(i)?&odd:nullptr,true,false);
                            channels=outputs->getNumberOfChannels(i);break;
                        }
                        if (!channels || channels>3 || aov.getWidth()!=pixels.getWidth() || aov.getHeight()!=pixels.getHeight()) return false;
                    }
                    if(sampleWeights.getWidth()!=pixels.getWidth() || sampleWeights.getHeight()!=pixels.getHeight())return false;
                    // Coverage again, after the colours: where it differs from before, a worker
                    // touched the pixel in between.
                    scene_rdl2::fb_util::FloatBuffer weightsAfter;
                    driver->snapshotWeightBuffer(&weightsAfter, true, false);
                    const bool compare=weightsAfter.getWidth()==pixels.getWidth() && weightsAfter.getHeight()==pixels.getHeight();
                    const size_t count=size_t(pixels.getWidth())*pixels.getHeight();
                    if(steadyView!=key || steady.size()!=count*3){steadyView=key;steady.assign(count*3,std::numeric_limits<float>::quiet_NaN());}
                    size_t missingSamples=0;
                    auto readPixel=[&](size_t i,float* rgb) {
                        const unsigned x=i%pixels.getWidth(),y=i/pixels.getWidth();
                        const auto& pixel=pixels.getRow(y)[x];
                        rgb[0]=pixel[0];rgb[1]=pixel[1];rgb[2]=pixel[2];
                        if(channels){const float* value=reinterpret_cast<const float*>(aov.getData())+i*channels;
                            rgb[0]=value[0];rgb[1]=channels>1?value[1]:value[0];rgb[2]=channels>2?value[2]:(channels==1?value[0]:0);}
                        // Preserve MoonRay's coarse-pass reconstruction; do not replace
                        // it using a weight snapshot captured at a different instant.
                        if(!(sampleWeights.getRow(y)[x]>0.f))++missingSamples;
                        float* kept=&steady[i*3];
                        if(compare && weightsAfter.getRow(y)[x]!=sampleWeights.getRow(y)[x] && !std::isnan(kept[0])){
                            rgb[0]=kept[0];rgb[1]=kept[1];rgb[2]=kept[2];
                        } else {kept[0]=rgb[0];kept[1]=rgb[1];kept[2]=rgb[2];}
                    };
                    auto reportMissing=[&]() {
                        if(missingSamples && !reportedMissingSamples){
                            std::cerr << "MoonRay preview: coarse pixels use native reconstruction; worker outlines indicate sampled tile activity." << std::endl;
                            reportedMissingSamples=true;
                        }
                    };
                    if(useShared && sharedImage.publish(id,key,pixels.getWidth(),pixels.getHeight(),readPixel)){reportMissing();return true;}
                    const auto temporary = fs::u8path(directory) / ("preview_" + id + ".tmp");
                    std::ofstream file(temporary, std::ios::binary);
                    file << "PF\n" << pixels.getWidth() << " " << pixels.getHeight() << "\n-1.0\n";
                    for (size_t i=0; i<size_t(pixels.getWidth())*pixels.getHeight(); ++i) {
                        float rgb[3];readPixel(i,rgb);
                        file.write(reinterpret_cast<const char*>(rgb), sizeof(rgb));
                    }
                    reportMissing();
                    file.close();
                    if (!file) { fs::remove(temporary); return false; }
                    fs::rename(temporary, preview);
                    event(("FRAME_"+key).c_str(), id);
                    return true;
                };
                while (!context->isFrameComplete() && !waiting()) {
                    std::this_thread::sleep_for(std::chrono::milliseconds(20));
                    if(waiting())break;
                    const auto now=std::chrono::steady_clock::now();
                    const auto filmActivity=context->getFilmActivity();
                    const auto key=selectedView();
                    if ((!published || now-lastSnapshot >= std::chrono::milliseconds(100)) &&
                        (filmActivity!=lastFilmActivity || key!=lastView || !published) && context->isFrameReadyForDisplay()) {
                        printStatusLine(*context, driver->getLastFrameMcrtStartTime(), false);
                        modoBucketOutput(id,driver->getWidth(),driver->getHeight());
                        {
                            // How far the frame is, for the host's time estimate.
                            std::size_t submitted=0,total=0;
                            const float fraction=context->getFrameProgressFraction(&submitted,&total);
                            std::cout << "\n@@MODO_PROGRESS " << id << " " << fraction << std::endl;
                        }
                        try {
                            if(snapshot(key)){published=true;lastFilmActivity=filmActivity;lastView=key;}
                        } catch (const std::exception& e) {
                            std::cerr << "Modo progressive snapshot: " << e.what() << std::endl;
                        }
                        lastSnapshot=std::chrono::steady_clock::now();
                    }
                }
                complete = context->isFrameComplete() && !waiting();
                // Show a finished short pass before the output writer performs disk I/O.
                if(complete) {
                    try { snapshot(selectedView()); }
                    catch(const std::exception& e){std::cerr << "Modo final snapshot: " << e.what() << std::endl;}
                }
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
            std::ifstream file;std::istringstream memory;
            if(command.enabled())memory.str(command.receive());else file.open(mailbox);
            std::istream& input=command.enabled()?static_cast<std::istream&>(memory):static_cast<std::istream&>(file);
            if (!std::getline(input,id) || !std::getline(input,mode) ||
                !std::getline(input,delta) || !std::getline(input,full))
                throw std::runtime_error("Incomplete Modo session command");
        }
        if(!command.enabled())fs::remove(mailbox);
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
