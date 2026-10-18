// Frame-scoped instrumentation. Numeric inputs only; no native state migrates.
#include <atomic>
#include <chrono>
namespace xpu2::nativepath {
inline bool integrationProfile=false;
inline int vectorPackingMode=0;
inline std::atomic<uint64_t> integrationNs[10]{},integrationCalls[10]{};
inline std::atomic<uint64_t> packingGroups{0},packingPackets{0},packingVerified{0},packingMismatch{0};
inline uint64_t integrationBegin(){
    if(!integrationProfile)return 0;
    return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());
}
inline void integrationEnd(unsigned phase,uint64_t start){
    if(!start)return;
    if(phase>=10)throw std::logic_error("Invalid integration profile phase");
    integrationNs[phase]+=integrationBegin()-start;++integrationCalls[phase];
}
struct IntegrationTimer {
    unsigned phase;uint64_t start;
    explicit IntegrationTimer(unsigned p):phase(p),start(integrationBegin()){}
    ~IntegrationTimer(){integrationEnd(phase,start);}
};
inline void integrationReset(){
    integrationProfile=std::getenv("XPU2_INTEGRATION_PROFILE")!=nullptr;
    auto flag=[](const char* n){const char* p=std::getenv(n);return p && !std::strcmp(p,"1");};
    vectorPackingMode=flag("XPU2_VECTOR_PACK_VERIFY")?2:flag("XPU2_VECTOR_PACK")?1:0;
    for(unsigned i=0;i<10;++i){integrationNs[i]=0;integrationCalls[i]=0;}
    packingGroups=0;packingPackets=0;packingVerified=0;packingMismatch=0;
}
inline void integrationFinish(){
    if(const char* name=std::getenv("XPU2_INTEGRATION_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        const char* names[]={"window_prepare","submit_record","submit_replay","cpu_lobes","resume","collect","publish","group_record","group_replay","group_direct"};
        std::fprintf(f,"{");
        for(unsigned i=0;i<10;++i)std::fprintf(f,"%s\"%s\":{\"ns\":%llu,\"calls\":%llu}",i?",":"",names[i],(unsigned long long)integrationNs[i].load(),(unsigned long long)integrationCalls[i].load());
        std::fprintf(f,"}\n");std::fclose(f);
    }
    if(const char* name=std::getenv("XPU2_VECTOR_PACK_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"mode\":%d,\"groups\":%llu,\"packets\":%llu,\"verified\":%llu,\"mismatch\":%llu}\n",vectorPackingMode,(unsigned long long)packingGroups.load(),(unsigned long long)packingPackets.load(),(unsigned long long)packingVerified.load(),(unsigned long long)packingMismatch.load());std::fclose(f);
    }
}
}
extern "C" uint64_t CPP_gpuIntegrationBegin(){return xpu2::nativepath::integrationBegin();}
extern "C" void CPP_gpuIntegrationEnd(unsigned phase,uint64_t start){xpu2::nativepath::integrationEnd(phase,start);}
extern "C" int CPP_gpuVectorPackingMode(){return xpu2::nativepath::vectorPackingMode;}
extern "C" void CPP_gpuPackingCount(unsigned count){using namespace xpu2::nativepath;++packingGroups;packingPackets+=count;}
extern "C" void CPP_gpuVerifyPacking(const float* input,const uint32_t* pixels,const float* expected,const uint32_t* expectedPixels){
    using namespace xpu2::nativepath;++packingVerified;
    if(std::memcmp(input,expected,192*sizeof(float)) || std::memcmp(pixels,expectedPixels,8*sizeof(uint32_t))){++packingMismatch;throw std::logic_error("Vector packing differs from native lane packing");}
}
