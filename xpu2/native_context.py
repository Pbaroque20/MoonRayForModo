'''Opt-in retention of the native runtime primary CUDA context for material flights.'''
from . import native_shadow_work as shadow
from .native_gpu_paths import once
adapter=shadow.adapter
cpp=shadow.cpp
header=shadow.header
cuda=shadow.cuda
ispc=shadow.ispc
multisampler=shadow.multisampler
shadow_header=shadow.shadow_header
driver=shadow.driver

def queue(text):
    text=shadow.queue(text)
    text=once(text, '#undef DRIVER', '''    DRIVER(cuDevicePrimaryCtxGetState) DRIVER(cuDevicePrimaryCtxRetain)
    DRIVER(cuDevicePrimaryCtxRelease_v2) DRIVER(cuStreamSynchronize)
#undef DRIVER''')
    text=once(text, '#undef LOAD', '''        LOAD(cuDevicePrimaryCtxGetState) LOAD(cuDevicePrimaryCtxRetain)
        LOAD(cuDevicePrimaryCtxRelease_v2) LOAD(cuStreamSynchronize)
#undef LOAD''')
    text=once(text, '    CUcontext context=nullptr;', '''    CUcontext context=nullptr;
    CUdevice contextDevice=0;
    bool primaryMode=false,primaryRetained=false;
    int primaryActiveBefore=-1,primaryActiveAfter=-1;
    unsigned primaryRetains=0,primaryReleases=0;
    CUresult drainOwnedWork(){
        if(!primaryRetained)return fn_cuCtxSynchronize();
        // Synchronize only this bridge's streams, including partial uploads.
        // Never globally synchronize or reset the native renderer's context.
        for(auto& s:slots)if(s.stream){
            CUresult r=fn_cuStreamSynchronize(s.stream);
            if(r!=CUDA_SUCCESS)return r;
        }
        return CUDA_SUCCESS;
    }
    CUresult releaseContext(){
        if(!primaryRetained)return fn_cuCtxDestroy_v2(context);
        CUresult r=fn_cuDevicePrimaryCtxRelease_v2(contextDevice);
        if(r==CUDA_SUCCESS){
            primaryRetained=false;++primaryReleases;
            unsigned flags=0;
            if(fn_cuDevicePrimaryCtxGetState(contextDevice,&flags,&primaryActiveAfter)!=CUDA_SUCCESS)++cleanupErrors;
        }
        return r;
    }''')
    text=once(text, '            check(fn_cuCtxCreate_v2(&context,0,device));', '''            const char* choice=std::getenv("XPU2_CUDA_CONTEXT");
            primaryMode=choice && !std::strcmp(choice,"primary");
            contextDevice=device;
            if(primaryMode){
                const char* flights=std::getenv("XPU2_INFLIGHT_BATCHES");
                if(!flights || std::atoi(flights)<=0)throw std::runtime_error("Primary context requires owned nonblocking flight streams");
                unsigned flags=0;
                check(fn_cuDevicePrimaryCtxGetState(device,&flags,&primaryActiveBefore));
                if(!primaryActiveBefore)throw std::runtime_error("Native runtime primary context is not active");
                check(fn_cuDevicePrimaryCtxRetain(&context,device));
                primaryRetained=true;++primaryRetains;
                check(fn_cuCtxSetCurrent(context));
            }else check(fn_cuCtxCreate_v2(&context,0,device));''')
    text=once(text, 'if(!checked(fn_cuCtxSynchronize()))std::terminate();', 'if(!checked(drainOwnedWork()))std::terminate();')
    text=once(text, 'if(fn_cuCtxSynchronize()!=CUDA_SUCCESS)std::terminate();', 'if(drainOwnedWork()!=CUDA_SUCCESS)std::terminate();')
    text=once(text, 'if(checked(fn_cuCtxDestroy_v2(context)))', 'if(checked(releaseContext()))')
    text=once(text, '} catch(...) {fn_cuCtxSetCurrent(previous);throw;}', '} catch(...) {if(fn_cuCtxSetCurrent(previous)!=CUDA_SUCCESS)std::terminate();throw;}')
    text=once(text, '''            if(checked(fn_cuCtxPushCurrent_v2(context))) {''', '''            // Do not release retained ownership after an unsuccessful drain.
            if(!havePrevious)std::terminate();
            if(!checked(fn_cuCtxPushCurrent_v2(context)))std::terminate();
            {''')
    return text

def profile(text):
    text=shadow.profile(text)
    return once(text, '    shaderQueue.reset();', r'''    if(const char* name=std::getenv("XPU2_CONTEXT_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"primary\":%s,\"active_before\":%d,\"active_after\":%d,\"retains\":%u,\"releases\":%u,\"retained\":%s}\n",
            d.primaryMode?"true":"false",d.primaryActiveBefore,d.primaryActiveAfter,d.primaryRetains,d.primaryReleases,d.primaryRetained?"true":"false");std::fclose(f);
    }
    shaderQueue.reset();''')
