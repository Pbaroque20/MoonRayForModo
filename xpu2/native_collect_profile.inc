// Experimental bounded completion spin; frame flags remain immutable during work.
#include <immintrin.h>
namespace xpu2::nativepath {
inline unsigned collectSpinUs=0;
inline std::atomic<uint64_t> collectFastCalls{0},collectImmediate{0},collectSpinReady{0},collectSlept{0},collectPolls{0},collectCanceled{0},collectZero{0};
inline void collectReset(){
    const char* value=std::getenv("XPU2_COLLECT_SPIN_US");
    collectSpinUs=value && !std::strcmp(value,"64")?64:value && !std::strcmp(value,"256")?256:0;
    collectFastCalls=0;collectImmediate=0;collectSpinReady=0;collectSlept=0;collectPolls=0;collectCanceled=0;collectZero=0;
}
inline void collectFinish(){
    if(const char* name=std::getenv("XPU2_COLLECT_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"spin_us\":%u,\"calls\":%llu,\"immediate\":%llu,\"spin_ready\":%llu,\"slept\":%llu,\"polls\":%llu,\"canceled\":%llu,\"zero\":%llu}\n",collectSpinUs,
        (unsigned long long)collectFastCalls.load(),(unsigned long long)collectImmediate.load(),(unsigned long long)collectSpinReady.load(),(unsigned long long)collectSlept.load(),(unsigned long long)collectPolls.load(),(unsigned long long)collectCanceled.load(),(unsigned long long)collectZero.load());std::fclose(f);
    }
}
}
