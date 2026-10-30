// Included inside Bridge. All driver work stays on its owning queue thread.
struct FlightSlot {
    CUstream stream=nullptr;
    CUevent begin=nullptr,end=nullptr,done=nullptr;
    CUdeviceptr device[4]={};
    void* host=nullptr;
    bool busy=false;
    float* input(){return static_cast<float*>(host);}
    U* lengths(){return reinterpret_cast<U*>(static_cast<char*>(host)+512*96);}
    U* returned(){return reinterpret_cast<U*>(static_cast<char*>(host)+512*100);}
    U* result(){return reinterpret_cast<U*>(static_cast<char*>(host)+512*196);}
};
FlightSlot slots[4];
bool flightsReady=false,flightBroken=false;
unsigned flightLimit=0;
unsigned long long flightSubmitted=0,flightCompleted=0,flightQueries=0,flightPending=0,flightDrains=0;
#define FLIGHT_DRIVER(name) decltype(&name) fn_##name=nullptr;
FLIGHT_DRIVER(cuMemHostAlloc) FLIGHT_DRIVER(cuMemFreeHost)
FLIGHT_DRIVER(cuStreamCreate) FLIGHT_DRIVER(cuStreamDestroy_v2)
FLIGHT_DRIVER(cuMemcpyHtoDAsync_v2) FLIGHT_DRIVER(cuMemcpyDtoHAsync_v2)
#undef FLIGHT_DRIVER
void allocateFlights(unsigned limit) {
    // Called with this context current; finish allocation before any submission.
    for(unsigned i=0;i<limit;++i){
        auto& s=slots[i];
        check(fn_cuStreamCreate(&s.stream,CU_STREAM_NON_BLOCKING));
        check(fn_cuEventCreate(&s.begin,0));check(fn_cuEventCreate(&s.end,0));
        check(fn_cuEventCreate(&s.done,CU_EVENT_DISABLE_TIMING));
        check(fn_cuMemHostAlloc(&s.host,512*232,0));
        const size_t sizes[]={512*96,512*4,512*96,512*36};
        for(unsigned k=0;k<4;++k)check(fn_cuMemAlloc_v2(&s.device[k],sizes[k]));
        for(unsigned k=0;k<512;++k)s.lengths()[k]=96;
    }
    flightLimit=limit;flightsReady=true;
}
void closeFlights() {
    // Caller has synchronized the context before freeing any staging allocation.
    auto release=[&](CUresult r){if(r!=CUDA_SUCCESS){++cleanupErrors;return false;}return true;};
    for(auto& s:slots){
        for(auto& p:s.device)if(p && release(fn_cuMemFree_v2(p)))p=0;
        if(s.begin && release(fn_cuEventDestroy_v2(s.begin)))s.begin=nullptr;
        if(s.end && release(fn_cuEventDestroy_v2(s.end)))s.end=nullptr;
        if(s.done && release(fn_cuEventDestroy_v2(s.done)))s.done=nullptr;
        if(s.stream && release(fn_cuStreamDestroy_v2(s.stream)))s.stream=nullptr;
        if(s.host && release(fn_cuMemFreeHost(s.host)))s.host=nullptr;
        s.busy=false;
    }
    flightsReady=false;
}
void flightFailure(bool pushed,const char* message) {
    ++errors;flightBroken=true;
    // Do not recycle buffers or deliver fallback while queued copies can touch them.
    if(pushed){
        ++flightDrains;
        if(fn_cuCtxSynchronize()!=CUDA_SUCCESS)std::terminate(); // fatal device loss: fail closed
        CUcontext popped=nullptr;
        if(fn_cuCtxPopCurrent_v2(&popped)!=CUDA_SUCCESS || popped!=context)std::terminate();
    }
    if(log){std::fprintf(log,"CUDA_FLIGHT_ERROR %s\n",message);std::fflush(log);}
}
bool startFlight(unsigned index,unsigned limit,const float* input,int count) {
    std::lock_guard<std::mutex> lock(mutex);
    if(!mode || (std::strcmp(mode,"execute") && std::strcmp(mode,"execute_sentinel") && std::strcmp(mode,"replace") && std::strcmp(mode,"audit") && std::strcmp(mode,"sentinel")))return false;
    if(count<1 || count>512 || index>=limit || limit>4 || !limit){++errors;return false;}
    ++batches;samples+=count;
    if(flightBroken){++errors;return false;}
    bool pushed=false;
    try {
        if(!attempted)initialize();
        if(!ready){++errors;return false;}
        check(fn_cuCtxPushCurrent_v2(context));pushed=true;
        if(!flightsReady)allocateFlights(limit);
        if(limit!=flightLimit || slots[index].busy)throw std::logic_error("Flight slot reuse");
        auto& s=slots[index];
        std::memcpy(s.input(),input,count*96);
        check(fn_cuMemcpyHtoDAsync_v2(s.device[0],s.input(),count*96,s.stream));
        check(fn_cuMemcpyHtoDAsync_v2(s.device[1],s.lengths(),count*4,s.stream));
        if(std::getenv("XPU2_FLIGHT_FAIL_AFTER_UPLOAD") && !flightSubmitted)throw std::runtime_error("Injected upload failure");
        CUdeviceptr empty=0;U n=count;
        void* args[]={&s.device[0],&s.device[1],&s.device[2],&s.device[3],&empty,&empty,&n};
        check(fn_cuEventRecord(s.begin,s.stream));
        check(fn_cuLaunchKernel(kernel,(count+63)/64,1,1,64,1,1,0,s.stream,args,nullptr));
        check(fn_cuEventRecord(s.end,s.stream));
        check(fn_cuMemcpyDtoHAsync_v2(s.returned(),s.device[2],count*96,s.stream));
        check(fn_cuMemcpyDtoHAsync_v2(s.result(),s.device[3],count*36,s.stream));
        check(fn_cuEventRecord(s.done,s.stream));
        CUcontext popped=nullptr;check(fn_cuCtxPopCurrent_v2(&popped));pushed=false;
        if(popped!=context)std::terminate();
        s.busy=true;++flightSubmitted;return true;
    } catch(const std::exception& e){flightFailure(pushed,e.what());return false;}
}
int pollFlight(unsigned index) {
    std::lock_guard<std::mutex> lock(mutex);
    if(flightBroken)return -1;
    bool pushed=false;
    try {
        check(fn_cuCtxPushCurrent_v2(context));pushed=true;
        ++flightQueries;auto& s=slots[index];
        CUresult status=fn_cuEventQuery(s.done);
        if(status!=CUDA_ERROR_NOT_READY)check(status);
        if(status==CUDA_ERROR_NOT_READY){
            ++flightPending;
            if(activeCpu.load() && fn_cuEventQuery(s.begin)==CUDA_SUCCESS && fn_cuEventQuery(s.end)==CUDA_ERROR_NOT_READY)++kernelOverlap;
        }
        CUcontext popped=nullptr;check(fn_cuCtxPopCurrent_v2(&popped));pushed=false;
        if(popped!=context)std::terminate();
        return status==CUDA_SUCCESS?1:0;
    } catch(const std::exception& e){flightFailure(pushed,e.what());return -1;}
}
void finishFlight(unsigned index,float* input,float* output,int count,bool failed) {
    std::lock_guard<std::mutex> lock(mutex);auto& s=slots[index];
    if(!failed){
        // The completion event includes both D2H copies.
        bool pushed=false;
        try {
            check(fn_cuCtxPushCurrent_v2(context));pushed=true;
            float ms=0;check(fn_cuEventElapsedTime(&ms,s.begin,s.end));
            kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));
            CUcontext popped=nullptr;check(fn_cuCtxPopCurrent_v2(&popped));pushed=false;
            if(popped!=context)std::terminate();
        } catch(const std::exception& e){flightFailure(pushed,e.what());failed=true;}
    }
    if(!failed){
        const bool raw=!std::strcmp(mode,"execute")||!std::strcmp(mode,"execute_sentinel");
        U* returned=s.returned();U* result=s.result();
        // VALIDATION_BODY
    }
    s.busy=false;++flightCompleted;
}
