// Diagnostic bounded batched handoff. Native stack/arena stays alive until collect.
// GPU requests own numeric copies only; no native pointer escapes to the worker.
#include "native_lambert_queue.cc"
#include <array>
namespace {
struct Scope {
    bool open=false, sampling=false, light=false;
    unsigned calls=0;
    int count=0;
    std::array<int,8> lanes{};
    std::array<float,64> native{};
    Queue::Ticket ticket;
};
constexpr int batchLimit=16;
thread_local std::array<Scope,batchLimit> scopes;
thread_local int currentSlot=0;
Scope& current(){return scopes[currentSlot];}
void selectSlot(int slot){
    if(slot<0 || slot>=batchLimit)throw std::runtime_error("Invalid native batch slot");
    if(current().sampling || current().light)throw std::runtime_error("Unfinished native sample stage");
    currentSlot=slot;
}
Queue& deferredQueue(){static Queue* q=new Queue;return *q;} // Process-lifetime probe only.
struct Metrics {
    std::mutex mutex;
    FILE* file=nullptr;
    unsigned long long scopes=0,submitted=0,collected=0,lightCalls=0,lightPending=0,
        open=0,peakOpen=0,waits=0,guardFallback=0,multipleHooks=0,timeout=0,publishedLanes=0;
    Metrics(){const char* p=std::getenv("XPU2_DEFERRED_LOG");if(p)file=std::fopen(p,"wb");}
    void write(){
        if(!file)return;
        std::fprintf(file,"{\"open\":%llu,\"peak_open\":%llu,\"scopes\":%llu,\"submitted\":%llu,\"collected\":%llu,\"light_calls\":%llu,\"light_while_gpu_pending\":%llu,\"wait_polls\":%llu,\"guard_fallback\":%llu,\"multiple_hooks\":%llu,\"timeouts\":%llu,\"published_lanes\":%llu}\n",
            open,peakOpen,scopes,submitted,collected,lightCalls,lightPending,waits,guardFallback,multipleHooks,timeout,publishedLanes);
        std::fflush(file);
    }
};
Metrics& metrics(){static Metrics* m=new Metrics;return *m;}
bool enabled(){
    const char* m=std::getenv("XPU2_NATIVE_LAMBERT");
    return m && (!std::strcmp(m,"replace") || !std::strcmp(m,"audit") || !std::strcmp(m,"sentinel"));
}
}
extern "C" __declspec(dllexport) void xpu2BatchedBegin(int slot){
    selectSlot(slot);
    if(current().open)throw std::runtime_error("Nested deferred native scope");
    if(!enabled())return;
    current()=Scope{};current().open=true;current().sampling=true;
    auto& m=metrics();std::lock_guard<std::mutex> lock(m.mutex);++m.scopes;++m.open;m.peakOpen=std::max(m.peakOpen,m.open);
}
extern "C" __declspec(dllexport) void xpu2BatchedSampleEnd(){current().sampling=false;}
extern "C" __declspec(dllexport) void xpu2BatchedLambert(const float* input,const float* output,const int* lanes,int count){
    if(!current().open || !current().sampling)return;
    auto& q=deferredQueue();
    if(++current().calls!=1){
        if(current().ticket){q.cancel(current().ticket);current().ticket.reset();}
        auto& m=metrics();std::lock_guard<std::mutex> lock(m.mutex);++m.multipleHooks;return;
    }
    if(count<1 || count>8)throw std::runtime_error("Invalid deferred packet");
    unsigned mask=0;
    for(int i=0;i<count;++i){
        if(lanes[i]<0 || lanes[i]>7 || (mask&(1u<<lanes[i])))throw std::runtime_error("Invalid deferred lane");
        mask|=1u<<lanes[i];current().lanes[i]=lanes[i];
    }
    current().count=count;std::memcpy(current().native.data(),output,count*32);
    current().ticket=q.submit(input,output,count,1);
    if(current().ticket){auto& m=metrics();std::lock_guard<std::mutex> lock(m.mutex);++m.submitted;}
}
extern "C" __declspec(dllexport) void xpu2BatchedLightBegin(){
    if(!current().ticket)return;
    if(current().light)throw std::runtime_error("Nested light region");
    current().light=true;++activeCpu;
    auto& m=metrics();std::lock_guard<std::mutex> lock(m.mutex);++m.lightCalls;if(gpuPending.load())++m.lightPending;
}
extern "C" __declspec(dllexport) void xpu2BatchedLightEnd(){
    if(current().light){--activeCpu;current().light=false;}
}
extern "C" __declspec(dllexport) void xpu2BatchedCollect(float* post,int mask,int slot){
    selectSlot(slot);
    if(!current().open)return;
    if(current().sampling || current().light)throw std::runtime_error("Incomplete deferred native stage");
    auto& m=metrics();
    if(current().ticket){
        auto& q=deferredQueue();bool guarded=true;
        // Reject wrappers that transformed the Lambert answer before this handoff.
        // Only f is written back: light intersection and validity used native wi/pdf.
        // Bridge::run has already required an exact GPU/native match before substitution.
        for(int i=0;i<current().count;++i){
            const int lane=current().lanes[i];
            if(!(mask&(1<<lane)) || std::memcmp(post+lane*8,current().native.data()+i*8,28))guarded=false;
        }
        if(!guarded){
            q.cancel(current().ticket);std::lock_guard<std::mutex> lock(m.mutex);++m.guardFallback;
        }else{
            std::array<float,64> result{};
            const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
            for(;;){
                const auto status=q.tryCollect(current().ticket,1,result.data());
                if(status==Collect::Ready){
                    for(int i=0;i<current().count;++i)std::memcpy(post+current().lanes[i]*8+3,result.data()+i*8+3,12);
                    std::lock_guard<std::mutex> lock(m.mutex);++m.collected;m.publishedLanes+=current().count;break;
                }
                if(status!=Collect::Pending)throw std::runtime_error("Deferred ticket identity failure");
                if(std::chrono::steady_clock::now()>=deadline){
                    q.cancel(current().ticket);std::lock_guard<std::mutex> lock(m.mutex);++m.timeout;break;
                }
                {std::lock_guard<std::mutex> lock(m.mutex);++m.waits;}
                // Sleep on the ticket's completion event instead of burning a CPU
                // core while this resident native stack must wait for the result.
                // The predicate covers completion between tryCollect and locking.
                std::unique_lock<std::mutex> lock(q.mutex);
                current().ticket->completed.wait_until(lock,deadline,[&]{
                    return current().ticket->done || current().ticket->cancelled;
                });
            }
        }
    }
    current()=Scope{};
    std::lock_guard<std::mutex> lock(m.mutex);--m.open;m.write();
}

extern "C" __declspec(dllexport) int xpu2BatchedWidth(){
    const char* value=std::getenv("XPU2_NATIVE_BATCH_WIDTH");
    const int width=value ? std::atoi(value) : 4;
    if(width<1 || width>batchLimit)throw std::runtime_error("Invalid native batch width");
    return width;
}
