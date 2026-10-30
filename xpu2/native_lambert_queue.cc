// Experimental bounded producer queue; not a production plugin lifecycle.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <memory>
#include <thread>
#include <vector>
#include <algorithm>
namespace {
std::atomic<unsigned> activeCpu{0};
std::atomic<bool> gpuPending{false};
std::atomic<unsigned long long> kernelOverlap{0}, kernelMicroseconds{0};
}
// Isolated correctness probe. CPU validation is intentionally retained: no speed claim.
#include <windows.h>
#include <cuda.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>

namespace {
using U=uint32_t;
struct Bridge {
    std::mutex mutex;
    const char* mode=std::getenv("XPU2_NATIVE_LAMBERT");
    FILE* log=nullptr; FILE* records=nullptr;
    unsigned long long batches=0, samples=0, accepted=0, replaced=0, unsupported=0, invalid=0, mismatch=0, errors=0;
    bool ready=false, attempted=false;
    unsigned cleanupErrors=0;
    HMODULE lib=nullptr;
    CUcontext context=nullptr;
    CUmodule module=nullptr; CUfunction kernel=nullptr;
    CUevent beginEvent=nullptr,endEvent=nullptr;
    CUdeviceptr buffers[4]={};
#define DRIVER(name) decltype(&name) fn_##name=nullptr;
    DRIVER(cuInit) DRIVER(cuDeviceGet) DRIVER(cuCtxCreate_v2) DRIVER(cuCtxGetCurrent)
    DRIVER(cuCtxSetCurrent) DRIVER(cuCtxPushCurrent_v2) DRIVER(cuCtxPopCurrent_v2)
    DRIVER(cuModuleLoad) DRIVER(cuModuleGetFunction) DRIVER(cuMemAlloc_v2)
    DRIVER(cuEventCreate) DRIVER(cuEventRecord) DRIVER(cuEventQuery) DRIVER(cuEventSynchronize) DRIVER(cuEventElapsedTime)
    DRIVER(cuMemFree_v2) DRIVER(cuEventDestroy_v2) DRIVER(cuModuleUnload) DRIVER(cuCtxDestroy_v2)
    DRIVER(cuMemcpyHtoD_v2) DRIVER(cuMemcpyDtoH_v2) DRIVER(cuLaunchKernel) DRIVER(cuCtxSynchronize)
#undef DRIVER
    static void check(CUresult r) {if(r!=CUDA_SUCCESS)throw std::runtime_error("CUDA status "+std::to_string(int(r)));}
    void summary() {
        if(!log)return;
        std::fprintf(log,"{\"batches\":%llu,\"samples\":%llu,\"accepted\":%llu,\"replaced\":%llu,\"unsupported\":%llu,\"invalid\":%llu,\"mismatch\":%llu,\"errors\":%llu}\n",
                     batches,samples,accepted,replaced,unsupported,invalid,mismatch,errors);
        std::fflush(log);
    }
    ~Bridge() { summary(); if(log)std::fclose(log); if(records)std::fclose(records); }
    // Called by the owning worker after its final batch, including partial initialization.
    bool close() {
        std::lock_guard<std::mutex> lock(mutex);
        auto checked=[&](CUresult result){if(result!=CUDA_SUCCESS){++cleanupErrors;return false;}return true;};
        if(context) {
            CUcontext previous=nullptr;
            bool havePrevious=checked(fn_cuCtxGetCurrent(&previous));
            if(checked(fn_cuCtxPushCurrent_v2(context))) {
                checked(fn_cuCtxSynchronize());
                for(auto& buffer:buffers)if(buffer && checked(fn_cuMemFree_v2(buffer)))buffer=0;
                if(beginEvent && checked(fn_cuEventDestroy_v2(beginEvent)))beginEvent=nullptr;
                if(endEvent && checked(fn_cuEventDestroy_v2(endEvent)))endEvent=nullptr;
                if(module && checked(fn_cuModuleUnload(module))){module=nullptr;kernel=nullptr;}
                CUcontext popped=nullptr;
                if(checked(fn_cuCtxPopCurrent_v2(&popped)) && popped!=context)++cleanupErrors;
                CUcontext restored=nullptr;
                if(havePrevious && checked(fn_cuCtxGetCurrent(&restored)) && restored!=previous)++cleanupErrors;
            }
            if(checked(fn_cuCtxDestroy_v2(context))) {
                context=nullptr;module=nullptr;kernel=nullptr;beginEvent=nullptr;endEvent=nullptr;
                for(auto& buffer:buffers)buffer=0;
            }
        }
        ready=false;
        if(lib && !context){if(FreeLibrary(lib))lib=nullptr;else ++cleanupErrors;}
        summary();
        if(log){std::fclose(log);log=nullptr;}
        if(records){std::fclose(records);records=nullptr;}
        return !cleanupErrors && !context && !lib;
    }
    void initialize() {
        attempted=true;
        const char* path=std::getenv("XPU2_NATIVE_LAMBERT_LOG");
        if(path)log=std::fopen(path,"wb");
        path=std::getenv("XPU2_NATIVE_LAMBERT_RECORDS");
        if(path) {records=std::fopen(path,"wb");if(records)std::fwrite("XNI1",1,4,records);}
        lib=LoadLibraryExA("nvcuda.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);
        if(!lib)throw std::runtime_error("CUDA driver unavailable");
#define LOAD(name) fn_##name=reinterpret_cast<decltype(fn_##name)>(GetProcAddress(lib,#name)); if(!fn_##name)throw std::runtime_error(#name);
        LOAD(cuInit) LOAD(cuDeviceGet) LOAD(cuCtxCreate_v2) LOAD(cuCtxGetCurrent)
        LOAD(cuCtxSetCurrent) LOAD(cuCtxPushCurrent_v2) LOAD(cuCtxPopCurrent_v2)
        LOAD(cuModuleLoad) LOAD(cuModuleGetFunction) LOAD(cuMemAlloc_v2)
        LOAD(cuEventCreate) LOAD(cuEventRecord) LOAD(cuEventQuery) LOAD(cuEventSynchronize) LOAD(cuEventElapsedTime)
        LOAD(cuMemFree_v2) LOAD(cuEventDestroy_v2) LOAD(cuModuleUnload) LOAD(cuCtxDestroy_v2)
        LOAD(cuMemcpyHtoD_v2) LOAD(cuMemcpyDtoH_v2) LOAD(cuLaunchKernel) LOAD(cuCtxSynchronize)
#undef LOAD
        check(fn_cuInit(0)); CUdevice device; check(fn_cuDeviceGet(&device,0));
        CUcontext previous=nullptr; check(fn_cuCtxGetCurrent(&previous));
        try {
            check(fn_cuCtxCreate_v2(&context,0,device));
            const char* ptx=std::getenv("XPU2_NATIVE_LAMBERT_PTX");
            if(!ptx)throw std::runtime_error("Missing diagnostic PTX");
            check(fn_cuModuleLoad(&module,ptx));
            check(fn_cuModuleGetFunction(&kernel,module,"lambert_sample_vector"));
            check(fn_cuEventCreate(&beginEvent,0));check(fn_cuEventCreate(&endEvent,0));
            const size_t sizes[]={512*96,512*4,512*96,512*36};
            for(int i=0;i<4;++i)check(fn_cuMemAlloc_v2(&buffers[i],sizes[i]));
            check(fn_cuCtxSetCurrent(previous));ready=true;
        } catch(...) {fn_cuCtxSetCurrent(previous);throw;}
    }
    void run(float* input,float* output,int count) {
        if(!mode || (std::strcmp(mode,"audit") && std::strcmp(mode,"replace") && std::strcmp(mode,"sentinel")))return;
        std::lock_guard<std::mutex> lock(mutex);
        if(count<1 || count>512) {++errors;return;}
        ++batches;samples+=count;
        bool pushed=false;
        try {
            if(!attempted)initialize();
            if(!ready) {++errors;return;}
            check(fn_cuCtxPushCurrent_v2(context));pushed=true;
            U lengths[512],result[512*9],returned[512*24];
            for(int i=0;i<count;++i)lengths[i]=96;
            check(fn_cuMemcpyHtoD_v2(buffers[0],input,count*96));
            check(fn_cuMemcpyHtoD_v2(buffers[1],lengths,count*4));
            CUdeviceptr empty=0; U n=count;
            void* args[]={&buffers[0],&buffers[1],&buffers[2],&buffers[3],&empty,&empty,&n};
            check(fn_cuEventRecord(beginEvent,nullptr));
            gpuPending.store(true);
            check(fn_cuLaunchKernel(kernel,(count+63)/64,1,1,64,1,1,0,nullptr,args,nullptr));
            check(fn_cuEventRecord(endEvent,nullptr));
            for(;;) {
                CUresult done=fn_cuEventQuery(endEvent);
                if(done==CUDA_SUCCESS)break;
                if(done!=CUDA_ERROR_NOT_READY)check(done);
                if(fn_cuEventQuery(beginEvent)==CUDA_SUCCESS && activeCpu.load()>0)++kernelOverlap;
                std::this_thread::yield();
            }
            gpuPending.store(false);
            float ms=0;check(fn_cuEventElapsedTime(&ms,beginEvent,endEvent));
            kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));
            check(fn_cuMemcpyDtoH_v2(returned,buffers[2],count*96));
            check(fn_cuMemcpyDtoH_v2(result,buffers[3],count*36));
            CUcontext popped=nullptr; check(fn_cuCtxPopCurrent_v2(&popped));pushed=false;
            if(popped!=context)throw std::runtime_error("Context restore mismatch");
            for(int i=0;i<count;++i) {
                U native[8];std::memcpy(native,output+i*8,28);native[7]=U(output[i*8+7]);
                if(records) {std::fwrite(input+i*24,1,96,records);std::fwrite(native,1,32,records);std::fwrite(result+i*9,1,36,records);}
                if(std::memcmp(returned+i*24,input+i*24,96)) {++errors;continue;}
                U* gpu=result+i*9;
                if(gpu[0]==1){++unsupported;continue;}
                if(gpu[0]==2){++invalid;continue;}
                if(gpu[0]!=0){++errors;continue;}
                if(std::memcmp(native,gpu+1,32)){++mismatch;continue;}
                ++accepted;
                if(!std::strcmp(mode,"replace") || !std::strcmp(mode,"sentinel")) {
                    std::memcpy(output+i*8,gpu+1,28);++replaced;
                    // Deliberate negative control: proves returned values reach the native film.
                    if(!std::strcmp(mode,"sentinel"))for(int c=3;c<6;++c)output[i*8+c]*=0.5f;
                }
            }
        } catch(const std::exception& e) {
            ++errors;gpuPending.store(false);
            if(pushed) {CUcontext ignored=nullptr;fn_cuCtxPopCurrent_v2(&ignored);}
            if(log){std::fprintf(log,"CUDA_ERROR %s\n",e.what());std::fflush(log);}
        }
        if(batches%256==0)summary();
    }
};
}
extern "C" void xpu2SynchronousLambertUnused(float* input,float* output,int count) {
    static Bridge bridge;
    bridge.run(input,output,count);
}

namespace {
struct Request {
    float input[8*24],output[8*8];
    int count=0;
    unsigned long long id=0;
    bool done=false,cancelled=false,consumed=false,credit=false;
    std::shared_ptr<const int> owner;
    uint64_t revision=0;
    // Batch resources survive cancellation until the worker acknowledges completion.
    // Their scene registry must defer native destruction to its owning thread.
    std::shared_ptr<const void> retainedResources;
    std::condition_variable completed;
};
enum class Collect { Pending, Ready, Cancelled, Duplicate, WrongOwner, Stale };
struct Queue {
    using Ticket=std::shared_ptr<Request>;
    const std::shared_ptr<const int> ownerToken=std::make_shared<const int>(0);
    unsigned long long retainedAsync=0,explicitCancelled=0;
    std::mutex mutex;
    std::condition_variable available,stopped;
    std::mutex lifecycleMutex;
    std::thread worker;
    bool cleanupOk=false;
    bool stopping=false,workerExited=false;
    std::deque<std::shared_ptr<Request>> pending;
    Bridge device;
    FILE* log=nullptr;
    unsigned capacity=32,coalesceUs=0;
    bool mixed=false,split=false;
    unsigned producers=0;
    unsigned long long emptyBatches=0;
    unsigned long long next=0,submitted=0,delivered=0,cpu=0,full=0,timeouts=0,late=0,pruned=0,closed=0,merged=0,maxBatch=0,maxQueue=0,cpuPending=0,failed=0;
    Queue() {
        const char* p=std::getenv("XPU2_QUEUE_POLICY");mixed=p && !std::strcmp(p,"mixed");split=p && !std::strcmp(p,"split");
        p=std::getenv("XPU2_QUEUE_COALESCE_US");if(p)coalesceUs=std::min(1000,std::max(0,std::atoi(p)));
        p=std::getenv("XPU2_QUEUE_CAPACITY");if(p)capacity=std::min(64,std::max(0,std::atoi(p)));
        p=std::getenv("XPU2_QUEUE_LOG");if(p)log=std::fopen(p,"wb");
        worker=std::thread([this]{work();});
    }
    ~Queue(){if(worker.joinable())std::terminate();if(log)std::fclose(log);}
    void snapshot() {
        if(!log)return;
        std::fprintf(log,"{\"calls\":%llu,\"submitted\":%llu,\"delivered\":%llu,\"cpu_batches\":%llu,\"queue_full\":%llu,\"timeouts\":%llu,\"late_discarded\":%llu,\"cancelled_before_dispatch\":%llu,\"closed_fallback\":%llu,\"cancelled_requests\":%llu,\"retained_async\":%llu,\"worker_failures\":%llu,\"worker_batches\":%llu,\"max_batch_samples\":%llu,\"max_queue\":%llu,\"cpu_completed_while_gpu_pending\":%llu,\"kernel_window_cpu_observations\":%llu,\"kernel_microseconds\":%llu}\n",
          next,submitted,delivered,cpu,full,timeouts,late,pruned,closed,explicitCancelled,retainedAsync,failed,merged,maxBatch,maxQueue,cpuPending,kernelOverlap.load(),kernelMicroseconds.load());
        std::fflush(log);
    }
    // Explicit owner operation, never called from DLL detach. A timed-out stop
    // retains the worker and all resources; callers must quiesce before deletion.
    bool stop(std::chrono::milliseconds deadline) {
        std::lock_guard<std::mutex> lifecycle(lifecycleMutex);
        std::unique_lock<std::mutex> lock(mutex);
        stopping=true;available.notify_all();
        if(!stopped.wait_for(lock,deadline,[&]{return workerExited;}))return false;
        lock.unlock();
        if(worker.joinable())worker.join();
        return cleanupOk;
    }
    // Nonblocking with respect to GPU completion. These operations can acquire
    // the queue mutex and allocate; they are not lock-free or real-time APIs.
    Ticket submit(const float* input,const float* native,int count,uint64_t revision,
                  std::shared_ptr<const void> resources={}) {
        if(count<1 || count>8)return {};
        std::lock_guard<std::mutex> lock(mutex);
        const auto id=next++;
        if(stopping){++closed;snapshot();return {};}
        // Credit includes completed but uncollected results, not just pending work.
        if(retainedAsync>=capacity || pending.size()>=capacity){++full;snapshot();return {};}
        auto request=std::make_shared<Request>();request->id=id;request->count=count;
        request->owner=ownerToken;request->revision=revision;request->credit=true;
        request->retainedResources=std::move(resources);
        std::memcpy(request->input,input,count*96);std::memcpy(request->output,native,count*32);
        pending.push_back(request);++submitted;++retainedAsync;
        maxQueue=std::max(maxQueue,(unsigned long long)pending.size());available.notify_one();
        snapshot();return request;
    }
    void releaseCredit(const Ticket& request) {
        if(request->credit){request->credit=false;--retainedAsync;}
        request->retainedResources.reset();
    }
    bool cancelLocked(const Ticket& request) {
        if(!request || request->owner!=ownerToken || request->cancelled || request->consumed)return false;
        request->cancelled=true;++explicitCancelled;
        auto queued=std::find(pending.begin(),pending.end(),request);
        if(queued!=pending.end()){pending.erase(queued);++pruned;releaseCredit(request);}
        else if(request->done){++late;releaseCredit(request);}
        // In-flight cancellation retains its credit until the worker discards it.
        snapshot();return true;
    }
    bool cancel(const Ticket& request) {
        std::lock_guard<std::mutex> lock(mutex);return cancelLocked(request);
    }
    Collect tryCollect(const Ticket& request,uint64_t revision,float* output) {
        std::lock_guard<std::mutex> lock(mutex);
        if(!request || request->owner!=ownerToken)return Collect::WrongOwner;
        if(request->consumed)return Collect::Duplicate;
        if(request->cancelled)return Collect::Cancelled;
        if(request->revision!=revision){cancelLocked(request);return Collect::Stale;}
        if(!request->done)return Collect::Pending;
        std::memcpy(output,request->output,request->count*32);
        request->consumed=true;++delivered;releaseCredit(request);
        if(log)std::fprintf(log,"{\"delivered_id\":%llu,\"samples\":%d}\n",request->id,request->count);
        snapshot();return Collect::Ready;
    }
    void run(float* input,float* output,int count) {
        if(count<1 || count>8)return;
        std::unique_lock<std::mutex> lock(mutex);
        auto id=next++;
        if(stopping){++closed;snapshot();return;}
        thread_local int role=-1;
        if(role<0)role=int(producers++);
        if((mixed && id%2==0) || (split && role%2==0)) {++cpu;if(gpuPending.load())++cpuPending;snapshot();return;}
        if(pending.size()>=capacity){++full;snapshot();return;}
        auto request=std::make_shared<Request>();request->id=id;request->count=count;
        std::memcpy(request->input,input,count*96);std::memcpy(request->output,output,count*32);
        pending.push_back(request);++submitted;maxQueue=std::max(maxQueue,(unsigned long long)pending.size());available.notify_one();
        if(!request->completed.wait_for(lock,std::chrono::seconds(10),[&]{return request->done;})) {
            request->cancelled=true;++timeouts;
            // Both queue membership and cancellation are protected by the same lock.
            // If the worker already owns it, retain late-publication suppression.
            auto queued=std::find(pending.begin(),pending.end(),request);
            if(queued!=pending.end()){pending.erase(queued);++pruned;}
            snapshot();return; // Never publish after caller gives up.
        }
        std::memcpy(output,request->output,count*32);++delivered;
        if(log)std::fprintf(log,"{\"delivered_id\":%llu,\"samples\":%d}\n",id,count);
        snapshot();
    }
    void work() {
        for(;;) {
            std::vector<std::shared_ptr<Request>> batch;
            {
                std::unique_lock<std::mutex> lock(mutex);
                available.wait(lock,[&]{return stopping || !pending.empty();});
                if(stopping && pending.empty()){
                    lock.unlock();bool cleaned=device.close();lock.lock();
                    cleanupOk=cleaned;workerExited=true;snapshot();stopped.notify_all();return;
                }
                // Bounded coalescing opportunity; a single producer cannot deadlock waiting for a full batch.
                if(coalesceUs) {
                    const auto until=std::chrono::steady_clock::now()+std::chrono::microseconds(coalesceUs);
                    while(!stopping && pending.size()<4 && std::chrono::steady_clock::now()<until) {
                        lock.unlock();std::this_thread::yield();lock.lock();
                    }
                }
                while(!pending.empty() && batch.size()<64){batch.push_back(pending.front());pending.pop_front();}
                // Callers may remove all pending work while coalescing releases the lock.
                if(batch.empty()){++emptyBatches;snapshot();continue;}
            }
            int count=0;for(auto &r:batch)count+=r->count;
            std::vector<float> input(count*24),output(count*8);
            int offset=0;
            for(auto &r:batch){std::memcpy(input.data()+offset*24,r->input,r->count*96);std::memcpy(output.data()+offset*8,r->output,r->count*32);offset+=r->count;}
            bool failure=false;
            try {device.run(input.data(),output.data(),count);device.summary();if(device.records)std::fflush(device.records);}
            catch(...) {failure=true;}
            {
                std::lock_guard<std::mutex> lock(mutex);
                ++merged;maxBatch=std::max(maxBatch,(unsigned long long)count);if(failure)++failed;
                offset=0;
                for(auto &r:batch) {
                    if(r->cancelled){++late;releaseCredit(r);}
                    else {if(!failure)std::memcpy(r->output,output.data()+offset*8,r->count*32);r->done=true;r->completed.notify_one();}
                    offset+=r->count;
                }
                snapshot();
            }
        }
    }
};
}
extern "C" void xpu2NativeCpuBegin(){++activeCpu;}
extern "C" void xpu2NativeLambert(float* input,float* output,int count) {
    --activeCpu;
    const char* mode=std::getenv("XPU2_NATIVE_LAMBERT");
    if(!mode || (std::strcmp(mode,"replace") && std::strcmp(mode,"audit") && std::strcmp(mode,"sentinel")))return;
    // Process-owned diagnostic worker. No DLL-unload/reusable-kit lifecycle is claimed.
    static Queue* queue=new Queue;
    queue->run(input,output,count);
}
