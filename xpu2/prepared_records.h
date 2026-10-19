// Immutable CPU shading records shared by bounded queued sample packets.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <vector>
namespace xpu2::prepared {
struct Group {
    float common[192],samples[16*16];
    uint32_t masks[16],pixels[8];
    unsigned count=0;uint64_t revision=0,serial=0;
    void capture(const float* c,const float* s,const uint32_t* m,const uint32_t* p,unsigned n,uint64_t rev){
        if(!n||n>16||!rev)throw std::invalid_argument("Prepared record shape");
        for(unsigned i=0;i<n;++i)if(m[i]&~255u)throw std::invalid_argument("Prepared lane mask");
        std::memcpy(common,c,sizeof(common));std::memcpy(samples,s,n*16*sizeof(float));
        std::memcpy(masks,m,n*sizeof(uint32_t));std::memcpy(pixels,p,sizeof(pixels));count=n;revision=rev;
    }
    void expand(unsigned packet,float* output,uint32_t* ids=nullptr)const{
        if(packet>=count)throw std::out_of_range("Prepared record packet");
        std::memset(output,0,192*sizeof(float));
        for(unsigned lane=0;lane<8;++lane){
            const bool active=(masks[packet]&(1u<<lane))!=0;
            if(ids)ids[lane]=active?pixels[lane]:0xffffffffu;
            if(active){std::memcpy(output+lane*24,common+lane*24,96);
                std::memcpy(output+lane*24+11,samples+packet*16+lane*2,8);}
        }
    }
    void coordinates(unsigned packet,float* output)const{
        if(packet>=count)throw std::out_of_range("Prepared coordinates");
        std::memset(output,0,16*sizeof(float));
        for(unsigned lane=0;lane<8;++lane)if(masks[packet]&(1u<<lane))std::memcpy(output+lane*2,samples+packet*16+lane*2,8);
    }
};
class Pool {
    std::mutex mutex_;std::vector<std::shared_ptr<Group>> slots_;unsigned cursor_=0;
public:
    bool enabled=false;
    uint64_t acquired=0,reused=0,exhausted=0,recordBytes=0,equivalentBytes=0;
    std::atomic<uint64_t> queued{0},expanded{0};
    explicit Pool(int capacity=-1){
        const char* flag=std::getenv("XPU2_PREPARED_RECORDS");enabled=capacity>=0||(flag&&!std::strcmp(flag,"1"));
        if(!enabled)return;
        if(capacity<0){const char* c=std::getenv("XPU2_PREPARED_CAPACITY");capacity=c?std::atoi(c):128;}
        if(capacity<0||capacity>128)throw std::invalid_argument("Prepared pool capacity");
        slots_.reserve(capacity);for(int i=0;i<capacity;++i)slots_.push_back(std::make_shared<Group>());
    }
    std::shared_ptr<const Group> acquire(const float* common,const float* samples,const uint32_t* masks,const uint32_t* pixels,unsigned count,uint64_t revision){
        std::lock_guard<std::mutex> lock(mutex_);
        for(unsigned k=0;k<slots_.size();++k){unsigned i=(cursor_+k)%slots_.size();auto& g=slots_[i];
            // A retained pool reference is the sole owner only after all queues/windows release it.
            if(g.use_count()!=1)continue;
            g->capture(common,samples,masks,pixels,count,revision);
            if(g->serial==UINT64_MAX)throw std::overflow_error("Prepared record generation");
            reused+=g->serial!=0;++g->serial;++acquired;cursor_=(i+1)%slots_.size();
            recordBytes+=sizeof(g->common)+sizeof(g->pixels)+count*(16*sizeof(float)+sizeof(uint32_t));
            equivalentBytes+=count*(192*sizeof(float)+8*sizeof(uint32_t));return g;
        }
        ++exhausted;return {};
    }
    unsigned retained()const{unsigned n=0;for(const auto& g:slots_)n+=g.use_count()>1;return n;}
    void report()const{
        if(const char* name=std::getenv("XPU2_PREPARED_PROFILE"))if(FILE* f=std::fopen(name,"a")){
            std::fprintf(f,"{\"enabled\":%s,\"capacity\":%u,\"allocated_bytes\":%zu,\"acquired\":%llu,\"reused\":%llu,\"exhausted\":%llu,\"queued\":%llu,\"expanded\":%llu,\"retained\":%u,\"record_bytes\":%llu,\"equivalent_bytes\":%llu}\n",enabled?"true":"false",unsigned(slots_.size()),slots_.size()*sizeof(Group),(unsigned long long)acquired,(unsigned long long)reused,(unsigned long long)exhausted,(unsigned long long)queued.load(),(unsigned long long)expanded.load(),retained(),(unsigned long long)recordBytes,(unsigned long long)equivalentBytes);std::fclose(f);
        }
    }
};
}
