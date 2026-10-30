// Experimental owner-thread bookkeeping; GPU and film order are unchanged.
namespace xpu2::nativepath {
inline bool coordEarly=false,coordClaim=false;
inline std::atomic<uint64_t> coordClaimed{0},coordConsumed{0};
inline void coordReset(){
    const char* mode=std::getenv("XPU2_COORDINATION");
    coordEarly=mode && (!std::strcmp(mode,"early") || !std::strcmp(mode,"both"));
    coordClaim=mode && (!std::strcmp(mode,"claim") || !std::strcmp(mode,"both"));
    coordClaimed=0;coordConsumed=0;
}
inline void coordFinish(){
    if(coordClaimed!=coordConsumed)throw std::logic_error("Unconsumed claimed shading result");
    if(const char* name=std::getenv("XPU2_COORDINATION_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"early\":%s,\"claim\":%s,\"claimed\":%llu,\"consumed\":%llu}\n",coordEarly?"true":"false",coordClaim?"true":"false",(unsigned long long)coordClaimed.load(),(unsigned long long)coordConsumed.load());std::fclose(f);
    }
}
}
extern "C" bool CPP_gpuCoordEarly(){return xpu2::nativepath::coordEarly;}
