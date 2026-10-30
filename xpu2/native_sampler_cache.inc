namespace xpu2::nativepath {
inline bool samplerCacheEnabled=false,samplerCacheVerify=false,samplerCacheMiss=false;
inline std::atomic<uint64_t> samplerStored{0},samplerReused{0},samplerRejected{0},samplerDiscarded{0},samplerVerified{0};
inline std::atomic<unsigned> samplerBytes{0};
inline void samplerCacheReset(){
    auto flag=[](const char* n){const char* p=std::getenv(n);return p && !std::strcmp(p,"1");};
    samplerCacheEnabled=flag("XPU2_SAMPLER_CACHE");samplerCacheVerify=flag("XPU2_SAMPLER_VERIFY");samplerCacheMiss=flag("XPU2_SAMPLER_MISS");
    samplerStored=0;samplerReused=0;samplerRejected=0;samplerDiscarded=0;samplerVerified=0;samplerBytes=0;
}
inline void samplerCacheFinish(){
    if(samplerStored!=samplerReused+samplerRejected+samplerDiscarded)throw std::logic_error("Unretired sampler cache");
    if(const char* name=std::getenv("XPU2_SAMPLER_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"enabled\":%s,\"verify\":%s,\"forced_miss\":%s,\"stored\":%llu,\"reused\":%llu,\"rejected\":%llu,\"discarded\":%llu,\"verified\":%llu,\"bytes_per_block\":%u}\n",
            samplerCacheEnabled?"true":"false",samplerCacheVerify?"true":"false",samplerCacheMiss?"true":"false",
            (unsigned long long)samplerStored.load(),(unsigned long long)samplerReused.load(),(unsigned long long)samplerRejected.load(),
            (unsigned long long)samplerDiscarded.load(),(unsigned long long)samplerVerified.load(),samplerBytes.load());std::fclose(f);
    }
}
}
extern "C" unsigned char* CPP_gpuSamplerRead(unsigned bytes){
    using namespace xpu2::nativepath;
    if(!samplerCacheEnabled || !currentWindow || !currentWindow->replay)return nullptr;
    if(currentWindow->revision!=epoch)throw std::logic_error("Stale sampler revision");
    auto& b=*currentWindow->replay;
    if(!b.samplerStored)return nullptr;
    if(bytes!=b.samplerSize)throw std::logic_error("Sampler layout changed");
    return reinterpret_cast<unsigned char*>(b.sampler.data());
}
extern "C" unsigned char* CPP_gpuSamplerWrite(unsigned bytes){
    using namespace xpu2::nativepath;
    if(!samplerCacheEnabled || !recordingWindow())return nullptr;
    if(!bytes || bytes>32768 || currentWindow->revision!=epoch)throw std::logic_error("Invalid sampler storage");
    auto& b=*currentWindow->record;
    if(b.samplerStored)throw std::logic_error("Duplicate sampler publication");
    b.sampler.resize((bytes+63)/64);b.samplerSize=bytes;samplerBytes=bytes;
    return reinterpret_cast<unsigned char*>(b.sampler.data());
}
extern "C" void CPP_gpuSamplerCommit(){
    using namespace xpu2::nativepath;
    if(!recordingWindow() || !currentWindow->record->samplerSize)throw std::logic_error("Missing sampler owner");
    currentWindow->record->samplerStored=true;++samplerStored;
}
extern "C" bool CPP_gpuSamplerVerify(){return xpu2::nativepath::samplerCacheVerify;}
extern "C" bool CPP_gpuSamplerForceMiss(){return xpu2::nativepath::samplerCacheMiss;}
extern "C" void CPP_gpuSamplerResult(bool reused,bool verified,bool equal){
    using namespace xpu2::nativepath;
    if(!currentWindow || !currentWindow->replay || !currentWindow->replay->samplerStored)throw std::logic_error("Missing sampler replay owner");
    if(!equal)throw std::logic_error("Cached sampler differs from native initializer");
    currentWindow->replay->samplerStored=false;
    if(reused)++samplerReused;else ++samplerRejected;
    if(verified)++samplerVerified;
}
