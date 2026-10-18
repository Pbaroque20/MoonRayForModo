// Isolated CUDA transfer backend. A native renderer must supply its own context/streams.
#pragma once
#include "texture_cache.h"
#include <windows.h>
#include <cuda.h>
#include <cstring>
namespace xpu2::texture {
struct CudaBackend: Backend {
    HMODULE library=nullptr;CUcontext context=nullptr,previous=nullptr;
    CUstream uploads=nullptr,consumers=nullptr;unsigned objects=0,cleanupErrors=0;
    uint64_t verificationReadbackBytes=0;double uploadMilliseconds=0;
#define FN(n) decltype(&n) n##_=nullptr;
    FN(cuInit) FN(cuDeviceGet) FN(cuCtxCreate_v2) FN(cuCtxGetCurrent) FN(cuCtxSetCurrent) FN(cuCtxDestroy_v2) FN(cuCtxSynchronize)
    FN(cuStreamCreate) FN(cuStreamDestroy_v2) FN(cuStreamSynchronize)
    FN(cuMemAlloc_v2) FN(cuMemFree_v2) FN(cuMemAllocHost_v2) FN(cuMemFreeHost)
    FN(cuMemcpyHtoDAsync_v2) FN(cuMemcpyDtoDAsync_v2) FN(cuMemcpyDtoHAsync_v2)
    FN(cuEventElapsedTime) FN(cuEventCreate) FN(cuEventRecord) FN(cuEventQuery) FN(cuEventSynchronize) FN(cuEventDestroy_v2)
#undef FN
    static void check(CUresult code){if(code!=CUDA_SUCCESS)throw std::runtime_error("CUDA texture status "+std::to_string(int(code)));}
    void cleanup(CUresult code){if(code!=CUDA_SUCCESS)++cleanupErrors;}
    struct Arena {
        CudaBackend& d;bool host;size_t cap,reserved=0,active=0,peak=0;uint64_t allocations=0,reuses=0;
        std::map<size_t,std::vector<uint64_t>> idle;
        Arena(CudaBackend& driver,bool pinned,size_t limit):d(driver),host(pinned),cap(limit){}
        void freeBlock(uint64_t pointer){if(host)d.cleanup(d.cuMemFreeHost_(reinterpret_cast<void*>(pointer)));else d.cleanup(d.cuMemFree_v2_(pointer));}
        uint64_t take(size_t bytes){
            if(bytes>cap||active>cap-bytes)throw std::length_error("CUDA texture arena capacity exceeded");
            auto match=idle.find(bytes);
            if(match!=idle.end()&&!match->second.empty()){auto p=match->second.back();match->second.pop_back();if(match->second.empty())idle.erase(match);active+=bytes;++reuses;return p;}
            while(reserved>cap-bytes){
                auto victim=std::find_if(idle.begin(),idle.end(),[](const auto& p){return !p.second.empty();});
                if(victim==idle.end())throw std::logic_error("CUDA arena accounting mismatch");
                freeBlock(victim->second.back());victim->second.pop_back();reserved-=victim->first;if(victim->second.empty())idle.erase(victim);
            }
            uint64_t pointer=0;
            if(host){void* p=nullptr;check(d.cuMemAllocHost_v2_(&p,bytes));pointer=reinterpret_cast<uint64_t>(p);}
            else{CUdeviceptr p;check(d.cuMemAlloc_v2_(&p,bytes));pointer=p;}
            active+=bytes;reserved+=bytes;peak=std::max(peak,reserved);++allocations;return pointer;
        }
        void put(uint64_t pointer,size_t bytes){idle[bytes].push_back(pointer);active-=bytes;}
        void close(){if(active){++d.cleanupErrors;return;}for(auto& size:idle)for(auto p:size.second)freeBlock(p);idle.clear();reserved=0;}
    };
    std::unique_ptr<Arena> vramArena,stagingArena;
    explicit CudaBackend(size_t vramBudget=256<<20,size_t stagingBudget=16<<20){try{
        library=LoadLibraryExA("nvcuda.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!library)throw std::runtime_error("CUDA driver unavailable");
#define LOAD(n) n##_=reinterpret_cast<decltype(n##_)>(GetProcAddress(library,#n));if(!n##_)throw std::runtime_error("Missing CUDA function " #n);
        LOAD(cuInit) LOAD(cuDeviceGet) LOAD(cuCtxCreate_v2) LOAD(cuCtxGetCurrent) LOAD(cuCtxSetCurrent) LOAD(cuCtxDestroy_v2) LOAD(cuCtxSynchronize)
        LOAD(cuStreamCreate) LOAD(cuStreamDestroy_v2) LOAD(cuStreamSynchronize)
        LOAD(cuMemAlloc_v2) LOAD(cuMemFree_v2) LOAD(cuMemAllocHost_v2) LOAD(cuMemFreeHost)
        LOAD(cuMemcpyHtoDAsync_v2) LOAD(cuMemcpyDtoDAsync_v2) LOAD(cuMemcpyDtoHAsync_v2)
        LOAD(cuEventElapsedTime) LOAD(cuEventCreate) LOAD(cuEventRecord) LOAD(cuEventQuery) LOAD(cuEventSynchronize) LOAD(cuEventDestroy_v2)
#undef LOAD
        check(cuInit_(0));CUdevice device;check(cuDeviceGet_(&device,0));check(cuCtxGetCurrent_(&previous));check(cuCtxCreate_v2_(&context,0,device));
        check(cuStreamCreate_(&uploads,CU_STREAM_NON_BLOCKING));check(cuStreamCreate_(&consumers,CU_STREAM_NON_BLOCKING));
        vramArena=std::make_unique<Arena>(*this,false,vramBudget);stagingArena=std::make_unique<Arena>(*this,true,stagingBudget);
    }catch(...){close();throw;}}
    ~CudaBackend(){close();}
    void drain()override{if(context)check(cuCtxSynchronize_());}
    bool close(){
        if(objects)return false;
        if(context){cleanup(cuCtxSetCurrent_(context));cleanup(cuCtxSynchronize_());
            if(vramArena)vramArena->close();if(stagingArena)stagingArena->close();
            if(uploads){cleanup(cuStreamDestroy_v2_(uploads));uploads=nullptr;}
            if(consumers){cleanup(cuStreamDestroy_v2_(consumers));consumers=nullptr;}
            cleanup(cuCtxDestroy_v2_(context));context=nullptr;cleanup(cuCtxSetCurrent_(previous));}
        if(library){if(!FreeLibrary(library))++cleanupErrors;library=nullptr;}
        return !cleanupErrors;
    }
    struct Event: Fence {
        CudaBackend& d;CUevent event=nullptr;
        Event(CudaBackend& driver,CUstream stream,unsigned flags=CU_EVENT_DISABLE_TIMING):d(driver){check(d.cuEventCreate_(&event,flags));try{check(d.cuEventRecord_(event,stream));}catch(...){d.cleanup(d.cuEventDestroy_v2_(event));throw;}++d.objects;}
        ~Event(){d.cleanup(d.cuEventDestroy_v2_(event));--d.objects;}
        bool ready()override{auto code=d.cuEventQuery_(event);if(code==CUDA_ERROR_NOT_READY)return false;check(code);return true;}
        void wait()override{check(d.cuEventSynchronize_(event));}
    };
    struct Page: DevicePage {
        CudaBackend& d;size_t size;CUdeviceptr memory=0;void* staging=nullptr;std::shared_ptr<Event> begin,event;bool measured=false;
        Page(CudaBackend& driver,const Bytes& bytes):d(driver),size(bytes.size()){try{
            memory=d.vramArena->take(size);staging=reinterpret_cast<void*>(d.stagingArena->take(size));std::memcpy(staging,bytes.data(),bytes.size());
            begin=std::make_shared<Event>(d,d.uploads,CU_EVENT_DEFAULT);
            check(d.cuMemcpyHtoDAsync_v2_(memory,staging,bytes.size(),d.uploads));event=std::make_shared<Event>(d,d.uploads,CU_EVENT_DEFAULT);++d.objects;
        }catch(...){d.cleanup(d.cuStreamSynchronize_(d.uploads));if(staging)d.stagingArena->put(reinterpret_cast<uint64_t>(staging),size);if(memory)d.vramArena->put(memory,size);throw;}}
        ~Page(){if(staging){d.cleanup(d.cuStreamSynchronize_(d.uploads));d.stagingArena->put(reinterpret_cast<uint64_t>(staging),size);}d.vramArena->put(memory,size);--d.objects;}
        void releaseStaging(){if(!measured){float ms;check(d.cuEventElapsedTime_(&ms,begin->event,event->event));d.uploadMilliseconds+=ms;measured=true;}if(staging){d.stagingArena->put(reinterpret_cast<uint64_t>(staging),size);staging=nullptr;}}
        bool ready()override{if(!event->ready())return false;releaseStaging();return true;}
        void wait()override{event->wait();releaseStaging();}
        uint64_t address()const override{return memory;}
    };
    std::shared_ptr<DevicePage> upload(const Bytes& bytes)override{return std::make_shared<Page>(*this,bytes);}
    // Test consumer uses a separate CUDA stream. Its D2H bytes are validation
    // outputs, NOT texture-cache eviction/writeback traffic or shading execution.
    struct Consumer {
        CudaBackend& d;size_t size;CUdeviceptr output=0;void* host=nullptr;std::shared_ptr<Event> completion;
        Consumer(CudaBackend& driver,uint64_t source,size_t bytes):d(driver),size(bytes){try{
            check(d.cuMemAlloc_v2_(&output,size));check(d.cuMemAllocHost_v2_(&host,size));
            check(d.cuMemcpyDtoDAsync_v2_(output,source,size,d.consumers));check(d.cuMemcpyDtoHAsync_v2_(host,output,size,d.consumers));
            completion=std::make_shared<Event>(d,d.consumers);d.verificationReadbackBytes+=size;++d.objects;
        }catch(...){d.cleanup(d.cuStreamSynchronize_(d.consumers));if(host)d.cleanup(d.cuMemFreeHost_(host));if(output)d.cleanup(d.cuMemFree_v2_(output));throw;}}
        ~Consumer(){d.cleanup(d.cuStreamSynchronize_(d.consumers));if(host)d.cleanup(d.cuMemFreeHost_(host));if(output)d.cleanup(d.cuMemFree_v2_(output));--d.objects;}
        Bytes result(){completion->wait();auto* data=static_cast<uint8_t*>(host);return Bytes(data,data+size);}
    };
};
} // namespace xpu2::texture
