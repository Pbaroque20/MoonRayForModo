// MoonRayForModo native preview adapter. Image calls run on Modo's UI thread.
#include <lx_plugin.hpp>
#include <lx_externalrender.hpp>
#include <lx_image.hpp>
#include <lx_rndjob.hpp>
#include <atomic>
#include <map>
#include <memory>
#include <mutex>
#include <cstring>
#include <vector>
#include <cstdio>
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
        std::lock_guard<std::mutex> lock(registryMutex);
        previews.erase(state->id);
    }
    LxResult rend_Start() override {state->running=1; ++state->revision; return LXe_OK;}
    LxResult rend_Stop() override {
        state->running=0;
        // A stopped viewport can be destroyed before module cleanup. Drop its
        // UI interfaces while the host is still processing Stop.
        state->queue.clear(); state->notifier.clear(); state->processing.clear();
        return LXe_OK;
    }
    LxResult rend_Pause() override {state->running=0; return LXe_OK;}
    LxResult rend_Reset() override {++state->revision; return LXe_OK;}
    LxResult rend_SetNotifier(ILxUnknownID value) override {
        state->notifier.clear(); if(value) state->notifier.set(value); return LXe_OK;
    }
    LxResult rend_SetBufferQueue(ILxUnknownID value) override {
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
    auto state=findPreview(id); return state?state->diagnostic:"Preview instance missing";
}
extern "C" __declspec(dllexport) int MR_preview_publish(unsigned id,const char* path,int completed) {
    auto state=findPreview(id); if(!state || !state->running || !path) return 0;
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
        LXtExternalRenderBuffer buffer{};
        buffer.w=image.Width(); buffer.h=image.Height(); buffer.fmt=LXiIMP_RGBAFP;
        const auto begin=state->queue.WriteBegin(&buffer);
        if(LXx_FAIL(begin)) {
            std::snprintf(state->diagnostic,sizeof(state->diagnostic),"WriteBegin=0x%08x (%ux%u fmt=%u)",
                unsigned(begin),buffer.w,buffer.h,buffer.fmt);
            return -2;
        }
        if(!buffer.ptr || !buffer.w || !buffer.h || buffer.fmt!=LXiIMP_RGBAFP) {
            std::snprintf(state->diagnostic,sizeof(state->diagnostic),
                "Invalid queue buffer: %ux%u fmt=%u ptr=%s",buffer.w,buffer.h,buffer.fmt,buffer.ptr?"present":"null");
            state->queue.WriteEnd(&buffer);
            return -3;
        }
        // WriteBegin returns the host's dimensions, not our requested preview
        // dimensions. Never resize or free that host-owned buffer.
        copyPreviewRgba(rgba.data(),image.Width(),image.Height(),
                        static_cast<float*>(buffer.ptr),buffer.w,buffer.h);
        if(LXx_FAIL(state->queue.WriteEnd(&buffer))) return -4;
        ++state->published;
        return 1;
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
        entry.second->queue.clear();
        entry.second->notifier.clear();
        entry.second->processing.clear();
    }
}
void cleanup() { MR_preview_shutdown(); }
