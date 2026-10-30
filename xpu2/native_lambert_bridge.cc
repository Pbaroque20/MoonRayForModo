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
    HMODULE lib=nullptr;
    CUcontext context=nullptr;
    CUmodule module=nullptr; CUfunction kernel=nullptr;
    CUdeviceptr buffers[4]={};
#define DRIVER(name) decltype(&name) fn_##name=nullptr;
    DRIVER(cuInit) DRIVER(cuDeviceGet) DRIVER(cuCtxCreate_v2) DRIVER(cuCtxGetCurrent)
    DRIVER(cuCtxSetCurrent) DRIVER(cuCtxPushCurrent_v2) DRIVER(cuCtxPopCurrent_v2)
    DRIVER(cuModuleLoad) DRIVER(cuModuleGetFunction) DRIVER(cuMemAlloc_v2)
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
            const size_t sizes[]={8*96,8*4,8*96,8*36};
            for(int i=0;i<4;++i)check(fn_cuMemAlloc_v2(&buffers[i],sizes[i]));
            check(fn_cuCtxSetCurrent(previous));ready=true;
        } catch(...) {fn_cuCtxSetCurrent(previous);throw;}
    }
    void run(float* input,float* output,int count) {
        if(!mode || (std::strcmp(mode,"audit") && std::strcmp(mode,"replace") && std::strcmp(mode,"sentinel")))return;
        std::lock_guard<std::mutex> lock(mutex);
        if(count<1 || count>8) {++errors;return;}
        ++batches;samples+=count;
        bool pushed=false;
        try {
            if(!attempted)initialize();
            if(!ready) {++errors;return;}
            check(fn_cuCtxPushCurrent_v2(context));pushed=true;
            U lengths[8],result[8*9],returned[8*24];
            for(int i=0;i<count;++i)lengths[i]=96;
            check(fn_cuMemcpyHtoD_v2(buffers[0],input,count*96));
            check(fn_cuMemcpyHtoD_v2(buffers[1],lengths,count*4));
            CUdeviceptr empty=0; U n=count;
            void* args[]={&buffers[0],&buffers[1],&buffers[2],&buffers[3],&empty,&empty,&n};
            check(fn_cuLaunchKernel(kernel,1,1,1,32,1,1,0,nullptr,args,nullptr));
            check(fn_cuCtxSynchronize());
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
            ++errors;
            if(pushed) {CUcontext ignored=nullptr;fn_cuCtxPopCurrent_v2(&ignored);}
            if(log){std::fprintf(log,"CUDA_ERROR %s\n",e.what());std::fflush(log);}
        }
        if(batches%256==0)summary();
    }
};
}
extern "C" void xpu2NativeLambert(float* input,float* output,int count) {
    static Bridge bridge;
    bridge.run(input,output,count);
}
