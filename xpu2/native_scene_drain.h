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
#include <limits>
#include <thread>
#include <vector>
namespace xpu2drain {
inline bool enabled(){const char* p=std::getenv("XPU2_NATIVE_SCENE_DRAIN");return p&&std::strcmp(p,"1")==0;}
inline bool dedicated(){const char* p=std::getenv("XPU2_NATIVE_DEDICATED_QUEUE");return enabled()&&p&&std::strcmp(p,"1")==0;}
struct State {
    std::mutex mutex;std::condition_variable cv;std::thread worker;
    moonray::rt::GPUAccelerator* accelerator=nullptr;
    unsigned nativeSlots=0,sourceQueue=0,workerQueue=0,progress=0,iterations=0;
    bool active=false,stopping=false;
    bool accepting=false,captured=false,released=false,done=false;unsigned generation=0,count=0,mismatch=0,blocked=0;int error=0;
};
inline State& state(){static State* s=new State;return *s;}
inline void event(const char* name,const State& s){
    std::fprintf(xpu2TraceOutput(),"XPU2_NATIVE_DRAIN {\"event\":\"%s\",\"generation\":%u,\"count\":%u,\"mismatches\":%u,\"blocked\":%u,\"error\":%d,\"dedicated\":%d,\"native_slots\":%u,\"source_queue\":%u,\"worker_queue\":%u,\"native_progress\":%u,\"iterations\":%u}\n",
        name,s.generation,s.count,s.mismatch,s.blocked,s.error,int(dedicated()),s.nativeSlots,s.sourceQueue,s.workerQueue,s.progress,s.iterations);
    std::fflush(xpu2TraceOutput());
}
inline unsigned queueSlots(unsigned nativeSlots) {
    if(!dedicated())return nativeSlots;
    if(!nativeSlots||nativeSlots==std::numeric_limits<unsigned>::max())std::abort();
    return nativeSlots+1;
}
inline void registerAccelerator(moonray::rt::GPUAccelerator* accelerator,unsigned nativeSlots) {
    if(!dedicated())return;auto& s=state();std::lock_guard<std::mutex> lock(s.mutex);
    if(s.worker.joinable()||!accelerator||!nativeSlots)std::abort();
    s.accelerator=accelerator;s.nativeSlots=nativeSlots;s.workerQueue=nativeSlots;
    event("queue_reserved",s);
}
inline void forgetAccelerator() {
    if(!dedicated())return;auto& s=state();std::lock_guard<std::mutex> lock(s.mutex);
    if(s.worker.joinable())std::abort();s.accelerator=nullptr;s.nativeSlots=0;
}
// These events demonstrate a native query completing inside the diagnostic
// service window. They do not establish simultaneous hardware kernel execution.
inline bool nativeBegin(moonray::rt::GPUAccelerator* accelerator,unsigned queue) {
    if(!dedicated())return false;auto& s=state();std::lock_guard<std::mutex> lock(s.mutex);
    if(accelerator!=s.accelerator||queue>=s.nativeSlots)std::abort();
    return s.active;
}
inline void nativeEnd(bool beganDuringService) {
    if(!dedicated()||!beganDuringService)return;auto& s=state();std::lock_guard<std::mutex> lock(s.mutex);
    if(s.active&&!s.stopping){++s.progress;if(s.progress==1)event("native_progress",s);}
}
inline void markStop() {
    if(!dedicated())return;auto& s=state();std::lock_guard<std::mutex> lock(s.mutex);
    s.stopping=true;event("stop_requested",s);
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
    s.progress=s.iterations=0;s.active=s.stopping=false;
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
    const bool independent=dedicated();
    if(independent&&(accel!=s.accelerator||queue>=s.nativeSlots))std::abort();
    s.sourceQueue=queue;s.workerQueue=independent?s.nativeSlots:queue;
    queue=s.workerQueue;s.released=independent;
    s.captured=true;s.count=count;event("captured",s);
    s.worker=std::thread([&s,accel,queue,context,push,pop,independent,owned=std::move(owned),reference=std::move(reference)] {
        {std::unique_lock<std::mutex> wait(s.mutex);s.cv.wait(wait,[&]{return s.released;});}
        // The old path waits until stopFrame. The dedicated path owns an extra
        // native pipeline, stream and buffer slot and starts immediately.
        if(!independent)std::this_thread::sleep_for(std::chrono::milliseconds(20));
        int error=0;unsigned mismatch=0,blocked=0,iterations=0;bool pushed=false;
        try {
            error=int(push(context));pushed=error==0;
            if(pushed) {
                {std::lock_guard<std::mutex> begin(s.mutex);s.active=true;event("worker_begin",s);}
                // Bounded diagnostic stress, not additional film samples or a
                // benchmark. Repetitions make native/service interleaving observable.
                for(unsigned repeat=0;repeat<(independent?4096u:1u);++repeat) {
                    accel->occluded(queue,unsigned(owned.size()),owned.data(),nullptr,0);
                    auto result=accel->getOutputOcclusionBuf(queue);
                    for(size_t i=0;i<owned.size();++i){mismatch+=bool(result[i])!=bool(reference[i]);blocked+=bool(result[i]);}
                    ++iterations;
                }
            }
        }catch(...){error=-902;}
        if(pushed){CUcontext popped=nullptr;int code=int(pop(&popped));if(code||popped!=context)error=code?code:-903;}
        {std::lock_guard<std::mutex> finish(s.mutex);s.active=false;s.iterations=iterations;s.count=unsigned(owned.size())*iterations;s.error=error;s.mismatch=mismatch;s.blocked=blocked;s.done=true;event("worker_done",s);s.cv.notify_all();}
    });
}
}
