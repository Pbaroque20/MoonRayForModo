// Isolated XPU2 direct-light v1 queue. Owned numeric packets only.
#pragma once
#include <unordered_map>
namespace xpu2::lightqueue {
using Clock=std::chrono::steady_clock;
struct Job {
    uint64_t id=0,revision=0;std::thread::id owner;unsigned count=0;
    std::vector<float> input,output;
    bool done=false,consumed=false,canceled=false,released=false;
};
struct Queue {
    std::mutex mutex;std::condition_variable changed;std::deque<std::shared_ptr<Job>> pending;
    std::unordered_map<uint64_t,std::shared_ptr<Job>> owners;std::thread worker;
    bool stopping=false,broken=false;unsigned credits=0,capacity=4096,mode=0;uint64_t next=0;
    std::atomic<uint64_t> submitted{0},collected{0},canceled{0},refused{0},retired{0},batches{0},peakFlights{0},waits{0},errors{0},abandoned{0},gpuUsed{0},cpuUsed{0},verified{0},mismatch{0};
    struct Slot {CUstream stream=nullptr;CUevent done=nullptr;CUdeviceptr input=0,output=0;float* host=nullptr;unsigned count=0;bool busy=false;std::vector<std::shared_ptr<Job>> jobs;Clock::time_point started;};
    HMODULE lib=nullptr;CUcontext context=nullptr;CUmodule module=nullptr;CUfunction kernel=nullptr;Slot slots[2];
#define API(n) decltype(&n) f_##n=nullptr;
    API(cuInit) API(cuDeviceGet) API(cuCtxCreate_v2) API(cuCtxDestroy_v2) API(cuCtxSynchronize)
    API(cuModuleLoad) API(cuModuleGetFunction) API(cuModuleUnload) API(cuMemAlloc_v2) API(cuMemFree_v2)
    API(cuMemHostAlloc) API(cuMemFreeHost) API(cuStreamCreate) API(cuStreamDestroy_v2)
    API(cuEventCreate) API(cuEventDestroy_v2) API(cuEventRecord) API(cuEventQuery)
    API(cuMemcpyHtoDAsync_v2) API(cuMemcpyDtoHAsync_v2) API(cuLaunchKernel)
#undef API
    static void check(CUresult r){if(r!=CUDA_SUCCESS)throw std::runtime_error("Direct-light CUDA failure");}
    Queue(unsigned m):mode(m){if(std::getenv("XPU2_LIGHT_CAPACITY_ZERO"))capacity=0;worker=std::thread([this]{work();});}
    void init(){
        lib=LoadLibraryExA("nvcuda.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!lib)throw std::runtime_error("CUDA unavailable");
#define LOAD(n) f_##n=reinterpret_cast<decltype(f_##n)>(GetProcAddress(lib,#n));if(!f_##n)throw std::runtime_error(#n);
        LOAD(cuInit) LOAD(cuDeviceGet) LOAD(cuCtxCreate_v2) LOAD(cuCtxDestroy_v2) LOAD(cuCtxSynchronize)
        LOAD(cuModuleLoad) LOAD(cuModuleGetFunction) LOAD(cuModuleUnload) LOAD(cuMemAlloc_v2) LOAD(cuMemFree_v2)
        LOAD(cuMemHostAlloc) LOAD(cuMemFreeHost) LOAD(cuStreamCreate) LOAD(cuStreamDestroy_v2)
        LOAD(cuEventCreate) LOAD(cuEventDestroy_v2) LOAD(cuEventRecord) LOAD(cuEventQuery)
        LOAD(cuMemcpyHtoDAsync_v2) LOAD(cuMemcpyDtoHAsync_v2) LOAD(cuLaunchKernel)
#undef LOAD
        check(f_cuInit(0));CUdevice device;check(f_cuDeviceGet(&device,0));check(f_cuCtxCreate_v2(&context,0,device));
        const char* p=std::getenv("XPU2_LIGHT_PTX");if(!p)throw std::runtime_error("Missing direct-light PTX");
        check(f_cuModuleLoad(&module,p));check(f_cuModuleGetFunction(&kernel,module,"direct_light_unit"));
        for(auto& s:slots){check(f_cuStreamCreate(&s.stream,CU_STREAM_NON_BLOCKING));check(f_cuEventCreate(&s.done,CU_EVENT_DISABLE_TIMING));
            check(f_cuMemAlloc_v2(&s.input,512*128));check(f_cuMemAlloc_v2(&s.output,512*36));
            void* host=nullptr;check(f_cuMemHostAlloc(&host,512*164,0));s.host=static_cast<float*>(host);
        }
    }
    void release(const std::shared_ptr<Job>& j){if(j->done&&j->consumed&&!j->released){if(credits<j->count)std::terminate();credits-=j->count;j->released=true;++retired;}}
    uint64_t submit(const float* input,unsigned count,uint64_t revision){
        if(!count||count>128)throw std::logic_error("Invalid direct-light v1 packet count");
        std::lock_guard<std::mutex> lock(mutex);
        if(stopping||broken||count>capacity-std::min(credits,capacity)){++refused;return 0;}
        auto j=std::make_shared<Job>();j->input.assign(input,input+count*32);j->output.resize(count*9);j->count=count;j->revision=revision;j->owner=std::this_thread::get_id();j->id=++next;
        owners.emplace(j->id,j);try{pending.push_back(j);}catch(...){owners.erase(j->id);throw;}
        credits+=count;++submitted;changed.notify_all();return j->id;
    }
    void collect(moonray::pbr::TLState* tls,uint64_t id,uint64_t revision,float* output,unsigned count){
        std::fill(output,output+count*9,0.f);if(!id)return;
        std::unique_lock<std::mutex> lock(mutex);auto it=owners.find(id);
        if(it==owners.end())throw std::logic_error("Missing direct-light owner");auto j=it->second;
        if(j->revision!=revision||j->count!=count||j->owner!=std::this_thread::get_id()||j->consumed)throw std::logic_error("Stale direct-light result");
        bool waited=false;const auto deadline=Clock::now()+std::chrono::seconds(15);
        while(!j->done&&!tls->isCanceled()&&Clock::now()<deadline){if(!waited){++waits;waited=true;}changed.wait_for(lock,std::chrono::milliseconds(1));}
        if(tls->isCanceled()||!j->done){j->canceled=true;++canceled;}else{std::copy(j->output.begin(),j->output.end(),output);++collected;}
        j->consumed=true;owners.erase(id);release(j);changed.notify_all();
    }
    void finishSlot(Slot& s,bool failed){
        std::lock_guard<std::mutex> lock(mutex);unsigned offset=0;
        for(auto& j:s.jobs){
            if(!failed&&!j->canceled){std::copy(s.host+512*32+offset*9,s.host+512*32+(offset+j->count)*9,j->output.begin());
                if(mode==3)for(unsigned k=0;k<j->count;++k)if(j->output[k*9+8]==1.f)for(unsigned c=4;c<7;++c)j->output[k*9+c]*=0.5f;
            }
            j->done=true;release(j);offset+=j->count;
        }
        s.jobs.clear();s.count=0;s.busy=false;changed.notify_all();
    }
    void drainFailure(){++errors;{std::lock_guard<std::mutex> lock(mutex);broken=true;}
        // Only this queue's private context is synchronized. Buffers cannot be reused before drain.
        if(context && f_cuCtxSynchronize && f_cuCtxSynchronize()!=CUDA_SUCCESS)std::terminate();
        for(auto& s:slots)if(!s.jobs.empty())finishSlot(s,true);
        std::lock_guard<std::mutex> lock(mutex);while(!pending.empty()){auto j=pending.front();pending.pop_front();j->done=true;release(j);}changed.notify_all();
    }
    void close(){
        if(context){check(f_cuCtxSynchronize());for(auto& s:slots){if(s.input)check(f_cuMemFree_v2(s.input));if(s.output)check(f_cuMemFree_v2(s.output));if(s.host)check(f_cuMemFreeHost(s.host));if(s.done)check(f_cuEventDestroy_v2(s.done));if(s.stream)check(f_cuStreamDestroy_v2(s.stream));}
            if(module)check(f_cuModuleUnload(module));check(f_cuCtxDestroy_v2(context));context=nullptr;
        }
        if(lib){FreeLibrary(lib);lib=nullptr;}
    }
    void work(){
        bool attempted=false;
        for(;;){
            try{
                for(auto& s:slots){if(s.busy)continue;
                    {std::lock_guard<std::mutex> lock(mutex);
                        while(!pending.empty()&&s.count+pending.front()->count<=512){auto j=pending.front();pending.pop_front();if(j->canceled){j->done=true;release(j);continue;}s.jobs.push_back(j);s.count+=j->count;}
                    }
                    if(s.jobs.empty())continue;
                    if(!attempted){attempted=true;init();}
                    unsigned offset=0;for(auto& j:s.jobs){std::copy(j->input.begin(),j->input.end(),s.host+offset*32);offset+=j->count;}
                    check(f_cuMemcpyHtoDAsync_v2(s.input,s.host,s.count*128,s.stream));
                    if(std::getenv("XPU2_LIGHT_FAIL_UPLOAD")&&!batches)throw std::runtime_error("Injected direct-light upload failure");
                    if(std::getenv("XPU2_LIGHT_HOLD_FIRST")&&!batches)std::this_thread::sleep_for(std::chrono::milliseconds(150));
                    void* args[]={&s.input,&s.output,&s.count};check(f_cuLaunchKernel(kernel,(s.count+63)/64,1,1,64,1,1,0,s.stream,args,nullptr));
                    check(f_cuMemcpyDtoHAsync_v2(s.host+512*32,s.output,s.count*36,s.stream));check(f_cuEventRecord(s.done,s.stream));s.busy=true;s.started=Clock::now();++batches;
                    unsigned active=0;for(auto& f:slots)active+=f.busy;peakFlights.store(std::max(peakFlights.load(),uint64_t(active)));
                }
                bool progress=false;for(auto& s:slots)if(s.busy){CUresult r=f_cuEventQuery(s.done);if(r==CUDA_SUCCESS){finishSlot(s,false);progress=true;}else if(r!=CUDA_ERROR_NOT_READY||Clock::now()-s.started>std::chrono::seconds(20))throw std::runtime_error("Direct-light completion failed");}
                std::unique_lock<std::mutex> lock(mutex);bool active=false;for(auto& s:slots)active|=s.busy;
                if(stopping&&!active&&pending.empty())break;
                if(!active&&pending.empty())changed.wait(lock,[&]{return stopping||!pending.empty();});
                else if(!progress){lock.unlock();std::this_thread::yield();}
            }catch(...){drainFailure();std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return stopping;});break;}
        }
        try{close();}catch(...){std::terminate();}
    }
    void stop(){
        {std::lock_guard<std::mutex> lock(mutex);stopping=true;for(auto& v:owners){v.second->canceled=true;v.second->consumed=true;release(v.second);++abandoned;}owners.clear();changed.notify_all();}
        if(worker.joinable())worker.join();if(credits)throw std::logic_error("Direct-light queue retained credits");
        if(const char* p=std::getenv("XPU2_LIGHT_PROFILE"))if(FILE* f=std::fopen(p,"a")){
            std::fprintf(f,"{\"mode\":%u,\"submitted\":%llu,\"collected\":%llu,\"canceled\":%llu,\"refused\":%llu,\"retired\":%llu,\"batches\":%llu,\"peak_flights\":%llu,\"waits\":%llu,\"errors\":%llu,\"abandoned\":%llu,\"gpu_used\":%llu,\"cpu_used\":%llu,\"verified\":%llu,\"mismatch\":%llu,\"credits\":%u}\n",mode,(unsigned long long)submitted.load(),(unsigned long long)collected.load(),(unsigned long long)canceled.load(),(unsigned long long)refused.load(),(unsigned long long)retired.load(),(unsigned long long)batches.load(),(unsigned long long)peakFlights.load(),(unsigned long long)waits.load(),(unsigned long long)errors.load(),(unsigned long long)abandoned.load(),(unsigned long long)gpuUsed.load(),(unsigned long long)cpuUsed.load(),(unsigned long long)verified.load(),(unsigned long long)mismatch.load(),credits);std::fclose(f);
        }
    }
    ~Queue(){if(worker.joinable())stop();}
};
inline std::unique_ptr<Queue> queue;
inline void begin(){if(queue)throw std::logic_error("Old direct-light queue");const char* m=std::getenv("XPU2_DIRECT_LIGHT");unsigned mode=m&&!std::strcmp(m,"1")?1:m&&!std::strcmp(m,"verify")?2:m&&!std::strcmp(m,"sentinel")?3:0;if(mode)queue=std::make_unique<Queue>(mode);}
inline void end(){if(queue){queue->stop();queue.reset();}}
}
extern "C" int CPP_lightMode(moonray::pbr::TLState* tls){return xpu2::lightqueue::queue&&CPP_gpuEarlyEnabled(tls)?xpu2::lightqueue::queue->mode:0;}
extern "C" uint64_t CPP_lightSubmit(const float* input,unsigned count){auto& q=xpu2::lightqueue::queue;if(!q)return 0;return q->submit(input,count,xpu2::nativepath::epoch);}
extern "C" void CPP_lightCollect(moonray::pbr::TLState* tls,uint64_t handle,float* output,unsigned count){if(!xpu2::lightqueue::queue){std::fill(output,output+count*9,0.f);return;}xpu2::lightqueue::queue->collect(tls,handle,xpu2::nativepath::epoch,output,count);}
extern "C" void CPP_lightUsed(unsigned gpu,unsigned cpu){if(auto& q=xpu2::lightqueue::queue){q->gpuUsed+=gpu;q->cpuUsed+=cpu;}}
extern "C" void CPP_lightVerified(unsigned checked,unsigned mismatch){auto& q=xpu2::lightqueue::queue;q->verified+=checked;q->mismatch+=mismatch;if(mismatch)throw std::logic_error("Direct-light native mismatch");}
