// Deterministic coordinator-side policy; no texture approximation or device dispatch.
#pragma once
#include "texture_cache.h"
#include <cmath>
namespace xpu2::texture {
struct Placement {
    Key key;bool gpu=false;
    bool operator==(const Placement& v)const{return key==v.key&&gpu==v.gpu;}
    bool operator<(const Placement& v)const{return key<v.key||(!(v.key<key)&&gpu<v.gpu);}
};
struct TextureRequest {
    std::string material;Key key;size_t bytes=0;bool gpu=false,demand=true;
    double importance=0,expectedUses=1,savedSeconds=0,uploadSeconds=0;
    uint64_t waitingEpochs=0;
};
struct ResidencyBudget {
    size_t ram=0,deviceTotal=0,deviceReserve=0,staging=0;
    size_t gpu()const{if(deviceReserve>deviceTotal)throw std::invalid_argument("VRAM reserve exceeds device budget");return deviceTotal-deviceReserve;}
};
struct TexturePlan {
    // Caller-supplied material dependencies; distinct mips/versions never collapse.
    using Branch=std::tuple<std::string,std::string,std::string,uint64_t,uint32_t,uint32_t>;
    std::map<Branch,std::set<Key>> hierarchy;
    std::set<Placement> keep;
    std::vector<Placement> drop,admit,defer;
    size_t ram=0,gpu=0;bool pinnedOverBudget=false;
};
inline TexturePlan planTextures(const std::vector<Residency>& resident,const std::vector<TextureRequest>& requests,ResidencyBudget budget){
    if(resident.size()>65536||requests.size()>65536)throw std::length_error("Texture planner input limit");
    const size_t gpuCap=budget.gpu();TexturePlan out;
    struct Item {Placement place;size_t bytes=0;bool resident=false,pinned=false,requested=false,demand=false,beneficial=false;double priority=0;};
    std::map<Placement,Item> items;std::map<Key,size_t> sizes;
    auto sizeOf=[&](const Key& key,size_t bytes){
        if(key.asset.empty()||key.interpretation.empty()||!bytes)throw std::invalid_argument("Invalid texture identity/size");
        auto [it,inserted]=sizes.emplace(key,bytes);if(!inserted&&it->second!=bytes)throw std::invalid_argument("Immutable texture size mismatch");
    };
    auto addSize=[&](size_t& used,size_t bytes){if(bytes>SIZE_MAX-used)throw std::overflow_error("Texture byte accounting overflow");used+=bytes;};
    for(const auto& r:resident){
        sizeOf(r.key,r.bytes);if((r.cpuPinned&&!r.cpu)||(r.gpuPinned&&!r.gpu)||(r.uploading&&!r.gpu))throw std::invalid_argument("Invalid resident state");
        for(bool gpu:{false,true})if(gpu?r.gpu:r.cpu){Placement p{r.key,gpu};Item v{p,r.bytes,true,gpu?(r.gpuPinned||r.uploading):r.cpuPinned};
            if(!items.emplace(p,v).second)throw std::invalid_argument("Duplicate residency record");
            if(v.pinned){out.keep.insert(p);addSize(gpu?out.gpu:out.ram,r.bytes);}
        }
    }
    for(const auto& r:requests){
        sizeOf(r.key,r.bytes);if(r.material.empty())throw std::invalid_argument("Missing material dependency");
        for(double v:{r.importance,r.expectedUses,r.savedSeconds,r.uploadSeconds})if(!std::isfinite(v)||v<0)throw std::invalid_argument("Invalid texture cost/priority");
        if(r.importance>1||r.waitingEpochs>1000000000)throw std::invalid_argument("Texture priority range");
        double saved=r.expectedUses*r.savedSeconds;if(!std::isfinite(saved))throw std::overflow_error("Texture cost overflow");
        out.hierarchy[{r.material,r.key.asset,r.key.interpretation,r.key.revision,r.key.layer,r.key.mip}].insert(r.key);
        Placement p{r.key,r.gpu};auto [it,inserted]=items.emplace(p,Item{p,r.bytes});auto& v=it->second;
        // Normalized benefit density, age and importance. Existing residency
        // avoids an upload and receives a small retention preference.
        double net=std::max(0.,saved-(v.resident?0:r.uploadSeconds));
        double benefit=std::min(4.,net/double(r.bytes)*1e6);
        double priority=double(r.waitingEpochs)+4*r.importance+benefit+(v.resident?.25:0);
        v.priority=std::max(v.priority,priority);v.demand|=r.demand;v.beneficial|=v.resident||saved>r.uploadSeconds;v.requested=true;
    }
    out.pinnedOverBudget=out.ram>budget.ram||out.gpu>gpuCap;
    std::vector<const Item*> order;for(const auto& item:items)if(item.second.requested&&!item.second.pinned)order.push_back(&item.second);
    std::stable_sort(order.begin(),order.end(),[](const Item* a,const Item* b){if(a->demand!=b->demand)return a->demand>b->demand;return a->priority>b->priority;});
    for(const Item* v:order){auto& used=v->place.gpu?out.gpu:out.ram;size_t cap=v->place.gpu?gpuCap:budget.ram;
        // Uploading a missing GPU page also requires a RAM tile and staging slot.
        bool fits=(v->demand||v->beneficial)&&!out.pinnedOverBudget&&used<=cap&&v->bytes<=cap-used;
        if(v->place.gpu&&!v->resident)fits= fits&&v->bytes<=budget.ram&&v->bytes<=budget.staging;
        if(fits){out.keep.insert(v->place);used+=v->bytes;out.admit.push_back(v->place);}else out.defer.push_back(v->place);
    }
    // Requested pinned pages are ready/retained, never evicted for new priority.
    for(const auto& item:items)if(item.second.requested&&item.second.pinned)out.admit.push_back(item.first);
    // Retain otherwise idle pages if they fit; no needless demotion/readback.
    for(const auto& item:items){const auto& v=item.second;if(v.requested||v.pinned)continue;
        auto& used=v.place.gpu?out.gpu:out.ram;size_t cap=v.place.gpu?gpuCap:budget.ram;
        if(!out.pinnedOverBudget&&used<=cap&&v.bytes<=cap-used){out.keep.insert(v.place);used+=v.bytes;}
    }
    for(const auto& item:items)if(item.second.resident&&!out.keep.count(item.first))out.drop.push_back(item.first);
    return out;
}
// Apply only evictions. Admission still uses Cache::acquire and its live budgets,
// leases, upload fences and errors; a plan is not a readiness or execution promise.
inline bool trimTextures(Cache& cache,const TexturePlan& plan){bool complete=true;for(const auto& p:plan.drop)if(!cache.discard(p.key,p.gpu))complete=false;return complete;}
} // namespace xpu2::texture
