# Optional pinned-memory CUDA transfers; correctness validation remains mandatory.
from xpu2.profile_patch import replace

def apply(code):
    def edit(old,new,count=1):
        nonlocal code
        code=replace(code,old,new,count)
    edit('X(unsupported) X(invalid) X(mismatch) X(errors)',
         'X(unsupported) X(invalid) X(mismatch) X(errors) X(async_batches) X(async_completions) X(staging_ns)')
    edit('CUdeviceptr buffers[4]={};',r'''CUdeviceptr buffers[4]={};
    void* pinned[4]={};
    CUstream transferStream=nullptr;
    CUevent transferDone=nullptr;
    bool asyncTransfers=false;
    const char* failStage=std::getenv("XPU2_ASYNC_FAIL_STAGE");
    void failAt(const char* stage) {if(failStage && !std::strcmp(failStage,stage))throw std::runtime_error("Injected async transfer failure");}
    bool asyncReleased() const {return !transferStream && !transferDone && !pinned[0] && !pinned[1] && !pinned[2] && !pinned[3];}''')
    edit('#undef DRIVER',r'''    DRIVER(cuMemHostAlloc) DRIVER(cuMemFreeHost) DRIVER(cuStreamCreate) DRIVER(cuStreamDestroy_v2)
    DRIVER(cuStreamSynchronize) DRIVER(cuMemcpyHtoDAsync_v2) DRIVER(cuMemcpyDtoHAsync_v2)
#undef DRIVER''')
    edit('#undef LOAD',r'''        const char* asyncFlag=std::getenv("XPU2_ASYNC_TRANSFERS");
        asyncTransfers=asyncFlag && !std::strcmp(asyncFlag,"1");
        if(asyncTransfers) {
            LOAD(cuMemHostAlloc) LOAD(cuMemFreeHost) LOAD(cuStreamCreate) LOAD(cuStreamDestroy_v2)
            LOAD(cuStreamSynchronize) LOAD(cuMemcpyHtoDAsync_v2) LOAD(cuMemcpyDtoHAsync_v2)
        }
#undef LOAD''')
    edit('for(int i=0;i<4;++i)check(fn_cuMemAlloc_v2(&buffers[i],sizes[i]));',r'''for(int i=0;i<4;++i)check(fn_cuMemAlloc_v2(&buffers[i],sizes[i]));
            if(asyncTransfers) {
                check(fn_cuStreamCreate(&transferStream,CU_STREAM_NON_BLOCKING));
                check(fn_cuEventCreate(&transferDone,CU_EVENT_DISABLE_TIMING|CU_EVENT_BLOCKING_SYNC));
                for(int i=0;i<4;++i){check(fn_cuMemHostAlloc(&pinned[i],sizes[i],0));if(i==1)failAt("pinned_2");}
            }''')
    edit('checked(fn_cuCtxSynchronize());',r'''if(!checked(fn_cuCtxSynchronize()) && asyncTransfers) {
                    // Never free DMA storage after an unconfirmed drain.
                    CUcontext popped=nullptr;checked(fn_cuCtxPopCurrent_v2(&popped));return false;
                }
                if(asyncTransfers) {
                    for(auto& host:pinned)if(host && checked(fn_cuMemFreeHost(host)))host=nullptr;
                    if(transferDone && checked(fn_cuEventDestroy_v2(transferDone)))transferDone=nullptr;
                    if(transferStream && checked(fn_cuStreamDestroy_v2(transferStream)))transferStream=nullptr;
                }''')
    edit('if(checked(fn_cuCtxDestroy_v2(context))) {', 'if(asyncTransfers && !asyncReleased())return false;\n            if(checked(fn_cuCtxDestroy_v2(context))) {')
    edit('return !cleanupErrors && !context && !lib;', 'return !cleanupErrors && !context && !lib && asyncReleased();')
    start=code.index('            for(int i=0;i<count;++i)lengths[i]=96;')
    end=code.index('            CUcontext popped=nullptr; check(fn_cuCtxPopCurrent_v2(&popped));pushed=false;',start)
    sync=code[start:end]
    async_code=r'''            if(asyncTransfers) {
                xpu2profile::add(prof.async_batches);
                {xpu2profile::Span t(prof.staging_ns);
                 std::memcpy(pinned[0],input,count*96);
                 auto* lens=static_cast<U*>(pinned[1]);for(int i=0;i<count;++i)lens[i]=96;}
                {xpu2profile::Span t(prof.htod_ns);
                 check(fn_cuMemcpyHtoDAsync_v2(buffers[0],pinned[0],count*96,transferStream));
                 check(fn_cuMemcpyHtoDAsync_v2(buffers[1],pinned[1],count*4,transferStream));}
                failAt("uploaded");
                CUdeviceptr empty=0;U n=count;
                void* args[]={&buffers[0],&buffers[1],&buffers[2],&buffers[3],&empty,&empty,&n};
                {xpu2profile::Span t(prof.launch_ns);
                 check(fn_cuEventRecord(beginEvent,transferStream));gpuPending.store(true);
                 check(fn_cuLaunchKernel(kernel,(count+63)/64,1,1,64,1,1,0,transferStream,args,nullptr));
                 check(fn_cuEventRecord(endEvent,transferStream));}
                failAt("launched");
                {xpu2profile::Span t(prof.dtoh_ns);
                 check(fn_cuMemcpyDtoHAsync_v2(pinned[2],buffers[2],count*96,transferStream));
                 check(fn_cuMemcpyDtoHAsync_v2(pinned[3],buffers[3],count*36,transferStream));
                 check(fn_cuEventRecord(transferDone,transferStream));}
                failAt("readback");
                {xpu2profile::Span t(prof.device_wait_ns);check(fn_cuEventSynchronize(transferDone));}
                gpuPending.store(false);xpu2profile::add(prof.async_completions);
                float ms=0;check(fn_cuEventElapsedTime(&ms,beginEvent,endEvent));
                kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));
                xpu2profile::add(prof.kernel_gpu_ns,(unsigned long long)(ms*1000000));
                {xpu2profile::Span t(prof.staging_ns);
                 std::memcpy(returned,pinned[2],count*96);std::memcpy(result,pinned[3],count*36);}
            }else {
'''
    code=code[:start]+async_code+sync+'            }\n'+code[end:]
    edit('if(pushed) {CUcontext ignored=nullptr;fn_cuCtxPopCurrent_v2(&ignored);}',r'''if(asyncTransfers) {
                ready=false; // A failed batch cannot reuse uncertain staging memory.
                if(pushed && transferStream && fn_cuStreamSynchronize(transferStream)!=CUDA_SUCCESS)++cleanupErrors;
            }
            if(pushed) {CUcontext ignored=nullptr;fn_cuCtxPopCurrent_v2(&ignored);}''')
    return '#define XPU2_ASYNC_TRANSFERS_BUILT 1\n'+code
