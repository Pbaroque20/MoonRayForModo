// Shared diagnostic DLL: correlate an actual ISPC sampler call with its Lambert call.
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <stdexcept>
namespace {
struct Context {std::array<uint32_t,8*28> words{};unsigned mask=0;};
thread_local Context context;
bool enabled(){const char* p=std::getenv("XPU2_CORRELATED_CAPTURE");return p && *p;}
struct Writer {std::mutex mutex;FILE* file=nullptr;unsigned records=0;~Writer(){if(file)std::fclose(file);}};
}
extern "C" __declspec(dllexport) void xpu2SetContext(const uint32_t* words,int mask) {
    context.mask=0;if(!enabled())return;
    if(mask & ~255)throw std::runtime_error("Invalid capture lane mask");
    for(unsigned i=0;i<8;++i)if(mask&(1u<<i))std::memcpy(context.words.data()+i*28,words+i*28,28*4);
    context.mask=unsigned(mask);
}
extern "C" __declspec(dllexport) void xpu2ClearContext() {context.mask=0;}
extern "C" __declspec(dllexport) void xpu2CorrelatedLambert(const float* input,const float* output,const int* lanes,int count) {
    if(!enabled() || !context.mask)return;
    if(count<1 || count>8)throw std::runtime_error("Invalid Lambert capture count");
    static Writer writer;std::lock_guard<std::mutex> lock(writer.mutex);
    unsigned seen=0;
    for(int n=0;n<count;++n){
        const int lane=lanes[n];
        if(lane<0 || lane>7 || !(context.mask&(1u<<lane)) || (seen&(1u<<lane)))throw std::runtime_error("Unowned capture lane");
        seen|=1u<<lane;const auto* meta=context.words.data()+lane*28;
        if(meta[0]!=((77u<<16)|96u) && meta[0]!=((96u<<16)|132u))continue;
        if(std::memcmp(meta+24,input+n*24+11,8))throw std::runtime_error("Sampler/Lambert random values differ");
        if(!writer.file){writer.file=std::fopen(std::getenv("XPU2_CORRELATED_CAPTURE"),"wb");
            if(!writer.file || std::fwrite("XCL1",1,4,writer.file)!=4)throw std::runtime_error("Cannot open correlated capture");}
        if(++writer.records>1024)throw std::runtime_error("Correlated capture overflow");
        if(std::fwrite(meta,4,28,writer.file)!=28 || std::fwrite(input+n*24,4,24,writer.file)!=24 ||
           std::fwrite(output+n*8,4,8,writer.file)!=8 || std::fflush(writer.file))
            throw std::runtime_error("Correlated capture write failed");
    }
}
