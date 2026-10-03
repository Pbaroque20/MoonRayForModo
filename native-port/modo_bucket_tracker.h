#pragma once
#include <cstdint>
// This MinGW target uses automatic DLL exports, like the other renderer APIs.
#define MODO_BUCKET_API
extern "C" {
MODO_BUCKET_API void modoBucketBegin(unsigned worker, unsigned x0, unsigned y0, unsigned x1, unsigned y1);
MODO_BUCKET_API void modoBucketEnd(unsigned worker);
MODO_BUCKET_API unsigned modoBucketSnapshot(uint64_t* output, unsigned capacity);
}
struct ModoBucketScope {
    unsigned worker;
    ModoBucketScope(unsigned w,unsigned x0,unsigned y0,unsigned x1,unsigned y1):worker(w) { modoBucketBegin(w,x0,y0,x1,y1); }
    ~ModoBucketScope() { modoBucketEnd(worker); }
    ModoBucketScope(const ModoBucketScope&)=delete;
    ModoBucketScope& operator=(const ModoBucketScope&)=delete;
};
