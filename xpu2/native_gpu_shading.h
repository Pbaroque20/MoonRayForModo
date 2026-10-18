// Owned native indirect-Lambert stage. Only numerical shader packets enter CUDA.
#pragma once
#include "native_lambert_queue.cc"
#include <array>
namespace xpu2::nativepath {
struct Shader {
    std::array<float,192> input{};
    std::array<float,64> native{}, result{};
    std::array<float,24> parent{};
    std::array<float,8> factor{};
    std::array<unsigned,24> order{};
    Queue::Ticket ticket;
    uint64_t epoch=0;
    unsigned count=0;
    bool resolved=false;
};
inline std::unique_ptr<Queue> shaderQueue;
inline std::atomic<uint64_t> shaderLanes{0},shaderFallback{0},shaderGuards{0},shaderWaits{0},shaderReady{0},shaderTimeouts{0},shaderReturns{0};
inline float orderedProduct(float a,float b,float c,unsigned order){
    // Preserve the captured native multiplication grouping, including fast-math builds.
    volatile float first=order==0?a*b:order==1?b*c:a*c;
    volatile float result=first*(order==0?c:order==1?a:b);
    return result;
}
inline bool sameBits(float a,float b){return std::memcmp(&a,&b,4)==0;}
inline bool finiteBits(float a){uint32_t b;std::memcpy(&b,&a,4);return (b&0x7f800000u)!=0x7f800000u;}
inline void shaderBegin(){
    if(shaderQueue)throw std::logic_error("Old native GPU queue still active");
    shaderLanes=0;shaderFallback=0;shaderGuards=0;shaderWaits=0;shaderReady=0;shaderTimeouts=0;shaderReturns=0;
    shaderQueue=std::make_unique<Queue>();
}
template<class Paths> void cancelShaders(const Paths& paths){
    if(!shaderQueue)return;
    for(const auto& p:paths)if(p.shader&&p.shader->ticket)shaderQueue->cancel(p.shader->ticket);
}
template<class Paths> void prepareShaders(Paths& paths,size_t start,unsigned n,const float* payload,const unsigned* indices,uint64_t epoch){
    for(unsigned base=0;base<n;base+=8){
        auto packet=std::make_shared<Shader>();packet->epoch=epoch;packet->count=std::min(8u,n-base);
        bool eligible=true;
        for(unsigned lane=0;lane<packet->count;++lane){
            auto& path=paths[start+base+lane];const float* v=payload+size_t(indices[base+lane])*40;
            if(v[36]!=1.f){eligible=false;break;}
            for(unsigned k=2;k<20;++k)if(!finiteBits(v[k]))eligible=false;
            for(unsigned k=24;k<36;++k)if(!finiteBits(v[k]))eligible=false;
            std::copy(v,v+24,packet->input.begin()+lane*24);
            std::copy(v+24,v+32,packet->native.begin()+lane*8);
            packet->factor[lane]=v[35];
            const float nativeThroughput[]={path.vertex.pathThroughput.r,path.vertex.pathThroughput.g,path.vertex.pathThroughput.b};
            for(unsigned c=0;c<3;++c){
                packet->parent[lane*3+c]=v[32+c];unsigned order=0;
                while(order<3&&!sameBits(orderedProduct(v[32+c],v[27+c],v[35],order),nativeThroughput[c]))++order;
                if(order==3)eligible=false;packet->order[lane*3+c]=order;
            }
        }
        if(!eligible){shaderGuards+=packet->count;continue;}
        packet->result=packet->native;
        packet->ticket=shaderQueue->submit(packet->input.data(),packet->native.data(),packet->count,epoch);
        if(packet->ticket)shaderLanes+=packet->count;else shaderFallback+=packet->count;
        for(unsigned lane=0;lane<packet->count;++lane){auto& p=paths[start+base+lane];p.shader=packet;p.shaderLane=lane;}
    }
}
inline bool resolveShader(moonray::pbr::TLState* tls,Shader& packet,uint64_t epoch){
    if(packet.epoch!=epoch)throw std::logic_error("Stale native shader packet");
    if(packet.resolved)return !tls->isCanceled();
    packet.resolved=true;
    if(!packet.ticket)return !tls->isCanceled();
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
    bool waited=false;
    for(;;){
        if(tls->isCanceled()){shaderQueue->cancel(packet.ticket);return false;}
        auto status=shaderQueue->tryCollect(packet.ticket,epoch,packet.result.data());
        if(status==Collect::Ready){if(!waited)++shaderReady;return true;}
        if(status!=Collect::Pending)throw std::logic_error("Invalid native GPU completion");
        if(!waited){waited=true;++shaderWaits;}
        if(std::chrono::steady_clock::now()>=deadline){shaderQueue->cancel(packet.ticket);packet.result=packet.native;++shaderTimeouts;return true;}
        std::unique_lock<std::mutex> lock(shaderQueue->mutex);
        packet.ticket->completed.wait_for(lock,std::chrono::milliseconds(2),[&]{return packet.ticket->done||packet.ticket->cancelled;});
    }
}
template<class P> void applyShader(moonray::pbr::RayState& ray,const P& p){
    if(!p.shader)return;
    const auto& s=*p.shader;if(!s.resolved)throw std::logic_error("Unresolved native shader publication");
    const unsigned lane=p.shaderLane;float rgb[3];
    for(unsigned c=0;c<3;++c)rgb[c]=orderedProduct(s.parent[lane*3+c],s.result[lane*8+3+c],s.factor[lane],s.order[lane*3+c]);
    ray.mPathVertex.pathThroughput=scene_rdl2::math::Color(rgb[0],rgb[1],rgb[2]);
}
inline void shaderFinish(uint64_t epoch){
    if(!shaderQueue)return;
    if(!shaderQueue->stop(std::chrono::seconds(10)))throw std::runtime_error("Native shader queue did not quiesce");
    const auto& d=shaderQueue->device;
    if(const char* name=std::getenv("XPU2_NATIVE_GPU_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"epoch\":%llu,\"queued_lanes\":%llu,\"admission_fallback_lanes\":%llu,\"guard_fallback_lanes\":%llu,\"wait_barriers\":%llu,\"ready_at_barrier\":%llu,\"timeouts\":%llu,\"deferred_returns\":%llu,\"gpu_accepted\":%llu,\"gpu_replaced\":%llu,\"gpu_mismatch\":%llu,\"gpu_errors\":%llu,\"retained\":%llu,\"cleanup_errors\":%u,\"kernel_cpu_observations\":%llu}\n",
            (unsigned long long)epoch,(unsigned long long)shaderLanes.load(),(unsigned long long)shaderFallback.load(),(unsigned long long)shaderGuards.load(),(unsigned long long)shaderWaits.load(),(unsigned long long)shaderReady.load(),(unsigned long long)shaderTimeouts.load(),(unsigned long long)shaderReturns.load(),d.accepted,d.replaced,d.mismatch,d.errors,shaderQueue->retainedAsync,d.cleanupErrors,kernelOverlap.load());std::fclose(f);
    }
    if(shaderQueue->retainedAsync)throw std::logic_error("Native GPU queue retained credits");
    shaderQueue.reset();
}
}
