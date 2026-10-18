
#include <moonray/rendering/rndr/RenderDriver.h>
namespace xpu2::nativepath {
inline std::atomic<uint64_t> helpCalls{0},helpWork{0},helpNested{0};
inline thread_local bool helpingMaterial=false;
inline void helpReset(){helpCalls=0;helpWork=0;helpNested=0;}
inline void helpFinish(){
    if(const char* name=std::getenv("XPU2_MATERIAL_HELP_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"calls\":%llu,\"work\":%llu,\"nested_bypass\":%llu}\n",(unsigned long long)helpCalls.load(),(unsigned long long)helpWork.load(),(unsigned long long)helpNested.load());std::fclose(f);
    }
}
}
bool xpu2HelpMaterial(moonray::pbr::TLState* tls){
    using namespace xpu2::nativepath;
    const char* mode=std::getenv("XPU2_MATERIAL_HELP");
    if(!mode || std::strcmp(mode,"1") || !CPP_gpuMaterialStageMode(tls))return false;
    if(helpingMaterial){++helpNested;return false;}
    if(tls->isCanceled() || tls->mTopLevelTls->checkForHandlerStackOverflowRisk())return false;
    struct Guard { Guard(){helpingMaterial=true;++activeCpu;}~Guard(){--activeCpu;helpingMaterial=false;} } guard;
    ++helpCalls;
    auto count=tls->flushLocalQueues();
    if(!tls->isCanceled())count+=moonray::rndr::getRenderDriver()->flushXPUQueues(tls->mTopLevelTls,tls->mArena);
    helpWork+=count;return count!=0;
}
