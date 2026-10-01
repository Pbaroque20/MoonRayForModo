// Decode images on Modo's idle thread; transfer pixels on an SDK-initialized worker.
#include <lx_plugin.hpp>
#include <lx_externalrender.hpp>
#include <lx_image.hpp>
#include <lx_rndjob.hpp>
#include <lx_thread.hpp>
#include <atomic>
#include <map>
#include <memory>
#include <mutex>
#include <cstring>
#include <vector>
#include <cstdio>
#include <thread>
#include <exception>
#include "image_resample.hpp"
namespace {
struct PreviewState {
    unsigned id;
    std::atomic<int> running{0};
    std::atomic<unsigned> revision{0};
    std::atomic<unsigned> published{0};
    CLxLoc_ExternalRenderNotifier notifier;
    CLxLoc_ExternalRenderBufferQueue queue;
    CLxLoc_ImageProcessing processing;
    LXtRenderOutputProcess output{};
    char diagnostic[512]{};
    std::mutex diagnosticMutex;
    std::thread writer;
    CLxLoc_ThreadService threadService;
    std::atomic<int> transferResult{0};
    std::string transferPath;
    void finishWriter() { if(writer.joinable()) writer.join(); }
    void describe(const char* message) {
        std::lock_guard<std::mutex> lock(diagnosticMutex);
        std::snprintf(diagnostic,sizeof(diagnostic),"%s",message);
    }
};
std::mutex registryMutex;
std::map<unsigned,std::shared_ptr<PreviewState>> previews;
unsigned nextId=0;
std::shared_ptr<PreviewState> findPreview(unsigned id) {
    std::lock_guard<std::mutex> lock(registryMutex);
    auto i=previews.find(id);
    return i==previews.end()?nullptr:i->second;
}
class PreviewServer : public CLxImpl_ExternalRender {
    std::shared_ptr<PreviewState> state;
public:
    static LXtTagInfoDesc descInfo[];
    PreviewServer():state(std::make_shared<PreviewState>()) {
        std::lock_guard<std::mutex> lock(registryMutex);
        state->id=++nextId;
        previews[state->id]=state;
    }
    ~PreviewServer() override {
        state->running=0; state->finishWriter();
        std::lock_guard<std::mutex> lock(registryMutex);
        previews.erase(state->id);
    }
    LxResult rend_Start() override {
        if(!state->running.exchange(1)) ++state->revision;
        return LXe_OK;
    }
    LxResult rend_Stop() override {
        state->running=0;
        state->finishWriter();
        // A stopped viewport can be destroyed before module cleanup. Drop its
        // UI interfaces while the host is still processing Stop.
        state->queue.clear(); state->notifier.clear(); state->processing.clear();
        return LXe_OK;
    }
    LxResult rend_Pause() override {state->running=0; state->finishWriter(); return LXe_OK;}
    LxResult rend_Reset() override {++state->revision; return LXe_OK;}
    LxResult rend_SetNotifier(ILxUnknownID value) override {
        state->notifier.clear(); if(value) state->notifier.set(value); return LXe_OK;
    }
    LxResult rend_SetBufferQueue(ILxUnknownID value) override {
        state->finishWriter(); state->transferPath.clear(); state->transferResult=0;
        state->queue.clear(); if(value) state->queue.set(value); return LXe_OK;
    }
};
LXtTagInfoDesc PreviewServer::descInfo[]={{LXsSRV_USERNAME,"MoonRay CPU"},{nullptr,nullptr}};
}
extern "C" __declspec(dllexport) unsigned MR_preview_ids(unsigned* ids,unsigned capacity) {
    std::lock_guard<std::mutex> lock(registryMutex);
    unsigned n=0;
    for(const auto& entry:previews) {if(n<capacity && ids) ids[n]=entry.first; ++n;}
    return n;
}
extern "C" __declspec(dllexport) int MR_preview_state(unsigned id,unsigned* revision) {
    auto state=findPreview(id); if(!state) return -1;
    if(revision) *revision=state->revision.load();
    return state->running.load();
}
extern "C" __declspec(dllexport) int MR_preview_status(unsigned id,const char* text) {
    auto state=findPreview(id); if(!state || !state->notifier.test()) return 0;
    return LXx_OK(state->notifier.SetStatusText(text));
}
extern "C" __declspec(dllexport) unsigned MR_preview_frames(unsigned id) {
    auto state=findPreview(id); return state?state->published.load():0;
}
extern "C" __declspec(dllexport) const char* MR_preview_diagnostic(unsigned id) {
    static thread_local char text[512];
    auto state=findPreview(id); if(!state) return "Preview instance missing";
    std::lock_guard<std::mutex> lock(state->diagnosticMutex);
    std::snprintf(text,sizeof(text),"%s",state->diagnostic); return text;
}
extern "C" __declspec(dllexport) const char* MR_preview_image_debug(const char* path) {
    static thread_local char text[1024];
    CLxUser_ImageService service; CLxUser_Image image;
    if(!service.LoadNoCache(image,path)) return "Load failed";
    std::vector<float> row(static_cast<size_t>(image.Width())*4);
    float maximum=0, center[4]{};
    for(unsigned y=0;y<image.Height();++y) {
        const float* pixels=(const float*)image.GetLine(y,LXiIMP_RGBAFP,row.data());
        if(pixels) for(unsigned x=0;x<image.Width();++x)
            maximum=std::max(maximum,pixels[x*4]);
    }
    const auto result=image.GetPixel(image.Width()/2,image.Height()/2,LXiIMP_RGBAFP,center);
    std::snprintf(text,sizeof(text),"%ux%u format=%u max=%g center=[%g,%g,%g,%g] pixelResult=%x",
        image.Width(),image.Height(),image.Format(),maximum,center[0],center[1],center[2],center[3],unsigned(result));
    return text;
}
extern "C" __declspec(dllexport) int MR_preview_publish(unsigned id,const char* path,int completed) {
    auto state=findPreview(id); if(!state || !state->running || !path) return 0;
    try {
    if(state->writer.joinable()) {
        if(state->transferResult.load()==2) return 2;
        state->finishWriter();
    }
    if(state->transferPath==path) {
        const int result=state->transferResult.load();
        if(result==1 || result < -2) return result;
    }
    CLxUser_ImageService service;
    CLxUser_Image image;
    if(!service.LoadNoCache(image,path) || !image.Width() || !image.Height()) return -1;
    if(state->queue.test()) {
        std::vector<float> rgba(static_cast<size_t>(image.Width())*image.Height()*4);
        for(unsigned y=0;y<image.Height();++y) {
            auto* row=rgba.data()+static_cast<size_t>(y)*image.Width()*4;
            const void* pixels=image.GetLine(y,LXiIMP_RGBAFP,row);
            if(!pixels) return -6;
            if(pixels!=row) std::memcpy(row,pixels,image.Width()*4*sizeof(float));
        }
        const unsigned width=image.Width(),height=image.Height();
        state->transferPath=path; state->transferResult=2;
        state->writer=std::thread([state,rgba=std::move(rgba),width,height]() {
            if(LXx_FAIL(state->threadService.InitThread())) {
                state->describe("Modo could not initialize the image transfer thread");
                state->transferResult=-10; return;
            }
            struct ThreadScope {
                CLxLoc_ThreadService& service;
                ~ThreadScope() { service.CleanupThread(); }
            } threadScope{state->threadService};
            LXtExternalRenderBuffer buffer{};
            buffer.w=width; buffer.h=height; buffer.fmt=LXiIMP_RGBAFP;
            const auto begin=state->queue.WriteBegin(&buffer);
            char detail[512];
            if(LXx_FAIL(begin)) {
                std::snprintf(detail,sizeof(detail),"WriteBegin=0x%08x (%ux%u fmt=%u)",
                    unsigned(begin),buffer.w,buffer.h,buffer.fmt);
                state->describe(detail); state->transferResult=-2; return;
            }
            if(!buffer.ptr || !buffer.w || !buffer.h || buffer.fmt!=LXiIMP_RGBAFP) {
                state->describe("PView supplied an invalid image buffer");
                state->queue.WriteEnd(&buffer); state->transferResult=-3; return;
            }
            copyPreviewRgba(rgba.data(),width,height,static_cast<float*>(buffer.ptr),buffer.w,buffer.h);
            const float center=rgba[(static_cast<size_t>(height/2)*width+width/2)*4];
            const auto end=state->queue.WriteEnd(&buffer);
            if(LXx_FAIL(end)) {state->describe("PView rejected WriteEnd"); state->transferResult=-4; return;}
            std::snprintf(detail,sizeof(detail),"Transferred %ux%u, center=%g",buffer.w,buffer.h,center);
            state->describe(detail);
            ++state->published; state->transferResult=1;
        });
        return 2;
    }
    if(state->notifier.test()) {
        if(!state->processing.test()) {
            CLxLoc_ImageProcessingService processingService;
            if(LXx_FAIL(processingService.Create(state->processing))) return -7;
        }
        if(LXx_FAIL(state->processing.CopyToRenderProcess(&state->output))) return -8;
        state->output.type=LXiRENDEROUTPUT_COLOR;
        state->output.typeSize=3;
        state->output.alphaIndex=3;
        state->output.sourceImageGamma=1.0f;
        state->output.invResX=1.0f/image.Width();
        state->output.invResY=1.0f/image.Height();
        std::strcpy(state->output.userName,"MoonRay Beauty");
        std::strcpy(state->output.identity,"moonray.beauty");
        const auto notified=state->notifier.Notify(&state->output,image,completed);
        if(LXx_FAIL(notified)) {
            std::snprintf(state->diagnostic,sizeof(state->diagnostic),
                "Notify=0x%08x; no image queue supplied",unsigned(notified));
            return -9;
        }
        ++state->published;
        return 1;
    }
    return -5;
    } catch(const std::exception& error) {
        state->describe(error.what()); state->transferResult=-11; return -11;
    } catch(...) {
        state->describe("Unexpected error preparing the preview image");
        state->transferResult=-11; return -11;
    }
}
void initialize() {
    auto* server=new CLxPolymorph<PreviewServer>;
    server->AddInterface(new CLxIfc_ExternalRender<PreviewServer>);
    server->AddInterface(new CLxIfc_StaticDesc<PreviewServer>);
    lx::AddServer("moonray.cpu",server);
}
extern "C" __declspec(dllexport) void MR_preview_shutdown() {
    // Release host-owned interfaces while Modo's services are still alive.
    std::map<unsigned,std::shared_ptr<PreviewState>> remaining;
    {
        std::lock_guard<std::mutex> lock(registryMutex);
        remaining.swap(previews);
    }
    for(auto& entry:remaining) {
        entry.second->running=0;
        entry.second->finishWriter();
        entry.second->queue.clear();
        entry.second->notifier.clear();
        entry.second->processing.clear();
    }
}
void cleanup() { MR_preview_shutdown(); }
