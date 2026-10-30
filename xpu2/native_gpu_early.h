// Experimental pre-evaluation Lambert dispatch; native arenas remain on their owner.
#pragma once
#include <limits>
namespace xpu2::nativepath {
inline std::atomic<uint64_t> earlySubmitted{0},earlyCollected{0},earlyWaits{0},earlyFallback{0},earlyTimeouts{0};
inline void earlyReset(){earlySubmitted=0;earlyCollected=0;earlyWaits=0;earlyFallback=0;earlyTimeouts=0;}
inline void earlyFinish(){
    if(const char* name=std::getenv("XPU2_NATIVE_EARLY_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"submitted_packets\":%llu,\"gpu_lanes\":%llu,\"fallback_lanes\":%llu,\"waits\":%llu,\"timeouts\":%llu}\n",
          (unsigned long long)earlySubmitted.load(),(unsigned long long)earlyCollected.load(),(unsigned long long)earlyFallback.load(),(unsigned long long)earlyWaits.load(),(unsigned long long)earlyTimeouts.load());std::fclose(f);
    }
}
}
extern "C" bool CPP_gpuEarlyEnabled(moonray::pbr::TLState* tls){
    using namespace xpu2::nativepath;
    return enabled&&fixed&&tls->mFs->mExecutionMode==moonray::mcrt_common::ExecutionMode::XPU&&tls->mFs->mAovSchema->empty();
}
extern "C" uint64_t CPP_gpuEarlySubmit(const float* input){
    using namespace xpu2::nativepath;
    float empty[64];std::fill(empty,empty+64,std::numeric_limits<float>::quiet_NaN());
    auto owner=std::make_unique<Queue::Ticket>();
    *owner=shaderQueue->submit(input,empty,8,epoch);
    if(!*owner)return 0;
    ++earlySubmitted;return reinterpret_cast<uint64_t>(owner.release());
}
extern "C" void CPP_gpuEarlyCollect(moonray::pbr::TLState* tls,uint64_t token,float* result){
    using namespace xpu2::nativepath;
    std::fill(result,result+64,std::numeric_limits<float>::quiet_NaN());
    if(!token){earlyFallback+=8;return;}
    std::unique_ptr<Queue::Ticket> owner(reinterpret_cast<Queue::Ticket*>(token));
    const auto& ticket=*owner;const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);bool waited=false;
    for(;;){
        if(tls->isCanceled()){shaderQueue->cancel(ticket);earlyFallback+=8;return;}
        auto status=shaderQueue->tryCollect(ticket,epoch,result);
        if(status==Collect::Ready)break;
        if(status!=Collect::Pending)throw std::logic_error("Invalid early GPU completion");
        if(!waited){waited=true;++earlyWaits;}
        if(std::chrono::steady_clock::now()>=deadline){shaderQueue->cancel(ticket);earlyFallback+=8;++earlyTimeouts;return;}
        std::unique_lock<std::mutex> lock(shaderQueue->mutex);
        ticket->completed.wait_for(lock,std::chrono::milliseconds(2),[&]{return ticket->done||ticket->cancelled;});
    }
    for(unsigned lane=0;lane<8;++lane){if(finiteBits(result[lane*8+3]))++earlyCollected;else ++earlyFallback;}
}
extern "C" void CPP_gpuEarlyCpuEnd(){--activeCpu;}
