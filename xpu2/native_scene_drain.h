// Windows diagnostic only: delayed native OptiX queries, drained before mutation.
#pragma once
#include "trace_output.h"
#include <windows.h>
#include <cuda.h>
#include <moonray/rendering/rt/gpu/GPUAccelerator.h>
#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <vector>
namespace xpu2drain {
inline bool enabled(){const char* p=std::getenv("XPU2_NATIVE_SCENE_DRAIN");return p&&std::strcmp(p,"1")==0;}
struct State {
    std::mutex mutex;std::condition_variable cv;std::thread worker;
    bool accepting=false,captured=false,released=false,done=false;unsigned generation=0,count=0,mismatch=0,blocked=0;int error=0;
};
inline State& state(){static State* s=new State;return *s;}
inline void event(const char* name,const State& s){
    std::fprintf(xpu2TraceOutput(),"XPU2_NATIVE_DRAIN {\"event\":\"%s\",\"generation\":%u,\"count\":%u,\"mismatches\":%u,\"blocked\":%u,\"error\":%d}\n",name,s.generation,s.count,s.mismatch,s.blocked,s.error);std::fflush(xpu2TraceOutput());
}
inline void drain(const char* boundary) {
    if(!enabled())return;auto& s=state();std::unique_lock<std::mutex> lock(s.mutex);s.accepting=false;
    if(s.worker.joinable()) {
        event("drain_begin",s);s.released=true;s.cv.notify_all();
        if(!s.cv.wait_for(lock,std::chrono::seconds(10),[&]{return s.done;})) {
            s.error=-900;event("drain_timeout",s);
            // Fail closed in this disposable process: never free a borrowed native
            // accelerator while a worker might use it. Production needs owner retention.
            std::abort();
        }
        lock.unlock();s.worker.join();lock.lock();
        if(s.error||s.mismatch){event("drain_failed",s);std::abort();}
        event("drained",s);
    }
    event(boundary,s);
}
inline void openFrame() {
    if(!enabled())return;auto& s=state();std::lock_guard<std::mutex> lock(s.mutex);
    if(s.worker.joinable())std::abort();
    ++s.generation;s.count=s.mismatch=s.blocked=0;s.error=0;s.captured=s.released=s.done=false;s.accepting=true;event("frame_open",s);
}
inline void capture(moonray::rt::GPUAccelerator* accel,unsigned queue,unsigned count,const moonray::rt::GPURay* rays,const unsigned char* answers) {
    if(!enabled())return;auto& s=state();std::unique_lock<std::mutex> lock(s.mutex);
    if(!s.accepting||s.captured||!count)return;
    auto library=GetModuleHandleA("nvcuda.dll");
    auto get=reinterpret_cast<decltype(&cuCtxGetCurrent)>(GetProcAddress(library,"cuCtxGetCurrent"));
    auto push=reinterpret_cast<decltype(&cuCtxPushCurrent_v2)>(GetProcAddress(library,"cuCtxPushCurrent_v2"));
    auto pop=reinterpret_cast<decltype(&cuCtxPopCurrent_v2)>(GetProcAddress(library,"cuCtxPopCurrent_v2"));
    CUcontext context=nullptr;
    if(!get||!push||!pop||get(&context)!=CUDA_SUCCESS||!context){s.error=-901;event("capture_failed",s);std::abort();}
    count=std::min(count,32768u);
    std::vector<moonray::rt::GPURay> owned(rays,rays+count);std::vector<unsigned char> reference(answers,answers+count);
    s.captured=true;s.count=count;event("captured",s);
    s.worker=std::thread([&s,accel,queue,context,push,pop,owned=std::move(owned),reference=std::move(reference)] {
        {std::unique_lock<std::mutex> wait(s.mutex);s.cv.wait(wait,[&]{return s.released;});}
        // Native workers are already stopped; their queue slot cannot be reused concurrently.
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
        int error=0;unsigned mismatch=0,blocked=0;bool pushed=false;
        try {
            error=int(push(context));pushed=error==0;
            if(pushed) {
                accel->occluded(queue,unsigned(owned.size()),owned.data(),nullptr,0);
                auto result=accel->getOutputOcclusionBuf(queue);
                for(size_t i=0;i<owned.size();++i){mismatch+=bool(result[i])!=bool(reference[i]);blocked+=bool(result[i]);}
            }
        }catch(...){error=-902;}
        if(pushed){CUcontext popped=nullptr;int code=int(pop(&popped));if(code||popped!=context)error=code?code:-903;}
        {std::lock_guard<std::mutex> finish(s.mutex);s.error=error;s.mismatch=mismatch;s.blocked=blocked;s.done=true;event("worker_done",s);s.cv.notify_all();}
    });
}
}
