// Fixed-capacity task metadata. Caller holds the queue mutex; no native pointers.
#pragma once
#include <array>
#include <cstdint>
#include <stdexcept>
namespace xpu2 {
template<class Policy> class LightWindow {
public:
    enum class Phase {Empty,Pending,Reserved,Preparing,Submitted,CpuOwned,Complete};
    struct Item {Phase phase=Phase::Empty;uint32_t mask=0,tile=0xffffffffu;bool eligible=false,preferGpu=false;uint64_t queued[2]{};};
    struct Stats {uint64_t windows=0,closed=0,descriptors=0,cpu=0,gpu=0,cpuSteals=0,gpuSteals=0,packed=0,fallback=0;};
    struct Candidate {uint32_t tile;uint64_t queuedClaim;unsigned index;};
    struct Candidates {
        std::array<Candidate,32> data{};unsigned count=0;
        size_t size()const{return count;}
        const Candidate* front()const{return &data[0];}
        const Candidate* operator[](size_t i)const{return &data[i];}
    };
    std::array<Item,32> items{};Policy cpuPolicy,gpuPolicy;Stats stats;
    uint64_t generation=0,revision=0;unsigned count=0,lanes=0,reserved=0;bool active=false;
    explicit LightWindow(bool neighbor=false){cpuPolicy.neighbor=gpuPolicy.neighbor=neighbor;cpuPolicy.scanLimit=gpuPolicy.scanLimit=16;}
    uint64_t open(const uint32_t* masks,const uint32_t* tiles,uint32_t eligible,unsigned n,unsigned width,uint64_t rev){
        if(active||!masks||!tiles||(eligible&~255u)||!n||n>32||(n&1)||!width||width>128||(width%8)||(n/2)*width>512||!rev||generation==UINT64_MAX)throw std::logic_error("Invalid lazy light window");
        for(unsigned i=0;i<n;++i)if(masks[i]&~255u)throw std::logic_error("Invalid light lane mask");
        items={};count=n;lanes=width;revision=rev;reserved=0;active=true;++generation;++stats.windows;
        for(unsigned i=0;i<count;++i){
            auto& item=items[i];item.mask=masks[i];if(!item.mask)continue;
            item.phase=Phase::Pending;item.tile=tiles[i];item.eligible=bool(masks[i]&eligible);item.preferGpu=bool(i&1);
            item.queued[0]=cpuPolicy.claims;item.queued[1]=gpuPolicy.claims;++stats.descriptors;
        }
        return generation;
    }
    void check(uint64_t token,uint64_t rev)const{if(!active||token!=generation||rev!=revision)throw std::logic_error("Stale lazy light window");}
    int choose(bool gpu,bool preference){
        Candidates choices;
        for(unsigned i=0;i<count;++i){const auto& item=items[i];
            if(item.phase!=Phase::Pending || (gpu&&!item.eligible) || item.preferGpu!=preference)continue;
            choices.data[choices.count++]={item.tile,item.queued[gpu?1:0],i};
        }
        if(!choices.count)return -1;
        auto& policy=gpu?gpuPolicy:cpuPolicy;
        return int(choices.data[policy.choose(choices)].index);
    }
    bool readyToReserve()const{
        if(!active||reserved+lanes>512)return false;
        for(unsigned i=0;i<count;++i)if(items[i].phase==Phase::Pending&&items[i].eligible)return true;
        return false;
    }
    void reserveGpu(){
        while(readyToReserve()){
            int i=choose(true,true);if(i<0)i=choose(true,false);if(i<0)return;
            auto& item=items[i];item.phase=Phase::Reserved;reserved+=lanes;++stats.gpu;if(!item.preferGpu)++stats.gpuSteals;
        }
    }
    // GPU-reserved work is prepared first. CPU claims only untouched descriptors.
    int next(uint64_t token,uint64_t rev){
        check(token,rev);
        for(unsigned i=0;i<count;++i)if(items[i].phase==Phase::Reserved){items[i].phase=Phase::Preparing;return 32+int(i);}
        int i=choose(false,false);if(i<0)i=choose(false,true);if(i<0)return -1;
        items[i].phase=Phase::CpuOwned;++stats.cpu;if(items[i].preferGpu)++stats.cpuSteals;return i;
    }
    void prepared(uint64_t token,uint64_t rev,unsigned i,bool submitted){
        check(token,rev);if(i>=count||items[i].phase!=Phase::Preparing)throw std::logic_error("Duplicate lazy light preparation");
        ++stats.packed;
        if(submitted)items[i].phase=Phase::Submitted;
        else{items[i].phase=Phase::Complete;reserved-=lanes;++stats.fallback;}
    }
    void completed(uint64_t token,uint64_t rev,unsigned i){
        check(token,rev);if(i>=count||items[i].phase!=Phase::Submitted)throw std::logic_error("Duplicate lazy light completion");
        items[i].phase=Phase::Complete;reserved-=lanes;
    }
    void close(uint64_t token,uint64_t rev){
        check(token,rev);if(reserved)throw std::logic_error("Lazy light reservations retained");
        for(unsigned i=0;i<count;++i)if(items[i].phase!=Phase::Empty&&items[i].phase!=Phase::CpuOwned&&items[i].phase!=Phase::Complete)throw std::logic_error("Unconsumed lazy light descriptor");
        active=false;++stats.closed;
    }
};
}
