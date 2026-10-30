// Included after early dispatch declarations. No native pointer crosses the queue.
namespace xpu2::nativepath {
inline std::atomic<uint64_t> stageCalls{0},stageResumes{0},stageTokens{0},stageReady{0},stagePending{0};
inline void stageReset(){stageCalls=0;stageResumes=0;stageTokens=0;stageReady=0;stagePending=0;}
inline void stageFinish(){
    if(stageCalls!=stageResumes)throw std::logic_error("Unbalanced material continuation");
    if(const char* name=std::getenv("XPU2_MATERIAL_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"calls\":%llu,\"resumes\":%llu,\"tokens\":%llu,\"ready_on_resume\":%llu,\"pending_on_resume\":%llu}\n",
            (unsigned long long)stageCalls.load(),(unsigned long long)stageResumes.load(),(unsigned long long)stageTokens.load(),(unsigned long long)stageReady.load(),(unsigned long long)stagePending.load());std::fclose(f);
    }
}
}
extern "C" int CPP_gpuMaterialStageMode(moonray::pbr::TLState* tls){
    if(!CPP_gpuEarlyEnabled(tls))return 0;
    const char* mode=std::getenv("XPU2_MATERIAL_STAGE");
    return mode&&!std::strcmp(mode,"setup")?1:mode&&!std::strcmp(mode,"lights")?2:0;
}
extern "C" void CPP_gpuMaterialStageBegin(const uint64_t* tokens,unsigned count){
    using namespace xpu2::nativepath;
    ++stageCalls;++activeCpu;
    for(unsigned i=0;i<count;++i)stageTokens+=tokens[i]!=0;
}
extern "C" void CPP_gpuMaterialStageResume(const uint64_t* tokens,unsigned count){
    using namespace xpu2::nativepath;
    --activeCpu;++stageResumes;
    std::lock_guard<std::mutex> lock(shaderQueue->mutex);
    for(unsigned i=0;i<count;++i)if(tokens[i]){
        const auto& ticket=*reinterpret_cast<Queue::Ticket*>(tokens[i]);
        if(ticket->revision!=epoch || ticket->cancelled || ticket->consumed)throw std::logic_error("Invalid material ticket");
        if(ticket->done)++stageReady;else ++stagePending;
    }
}
