#define MODO_BUCKET_IMPLEMENTATION
#include "modo_bucket_tracker.h"
#include <atomic>
#include <cstdlib>
namespace {
struct alignas(64) Slot { std::atomic<uint64_t> rectangle{0}; };
Slot slots[4096];
const bool enabled=[](){const char* v=std::getenv("MOONRAY_MODO_BUCKETS");return v && v[0]=='1';}();
}
void modoBucketBegin(unsigned worker,unsigned x0,unsigned y0,unsigned x1,unsigned y1) {
    if (!enabled || worker>=4096 || x1>65535 || y1>65535) return;
    slots[worker].rectangle.store(uint64_t(x0)|(uint64_t(y0)<<16)|(uint64_t(x1)<<32)|(uint64_t(y1)<<48),std::memory_order_relaxed);
}
void modoBucketEnd(unsigned worker) {
    if(enabled && worker<4096) slots[worker].rectangle.store(0,std::memory_order_relaxed);
}
unsigned modoBucketSnapshot(uint64_t* output,unsigned capacity) {
    unsigned count=0;
    if(enabled) for(auto& slot:slots) {
        auto rectangle=slot.rectangle.load(std::memory_order_relaxed);
        if(rectangle && count<capacity) output[count++]=rectangle;
    }
    return count;
}
