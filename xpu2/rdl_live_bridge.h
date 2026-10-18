// Diagnostic bridge: apply owned index deltas to a stopped native renderer.
// Only the isolated builder installs these hooks; the shipping XPU path is unchanged.
#pragma once
#include "rdl_scene_index.h"
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <unordered_map>
namespace xpu2::rdllive {
using namespace rdlindex;
inline bool enabled(){const char* p=std::getenv("XPU2_RDL_INDEX");return p&&std::string(p)=="1";}
inline Bytes identity(Kind,Field,const Bytes& data){return data;}
struct State {
    SceneIndex index;
    rdl::SceneContext source;
    bool invalid=false;
    size_t updates=0;
    explicit State(const rdl::SceneContext& target) {
        source.setProxyModeEnabled(true);source.setDsoPath(target.getDsoPath());
        auto initial=capture(target,index.acquire(),true);
        auto candidate=index.prepare(index.acquire(),initial.edits,{},identity);
        rdlindex::apply(candidate.view(),source,true);source.commitAllChanges();
        if(!index.commit(candidate))throw std::runtime_error("Initial native index commit rejected");
    }
};
// Native coordinator owns these contexts and invokes all hooks on one thread.
inline auto& states(){static thread_local std::unordered_map<const rdl::SceneContext*,std::unique_ptr<State>> value;return value;}
inline void forget(const rdl::SceneContext* target){states().erase(target);}
inline void healthy(const rdl::SceneContext& target){
    auto it=states().find(&target);
    if(it!=states().end()&&it->second&&it->second->invalid)throw std::runtime_error("Indexed native scene invalid; full context reload required");
}
inline void record(const State& state,const Capture& captured,bool initialized,long long initUs,long long readUs,long long captureUs,long long prepareUs,long long applyUs,bool noOp){
    const char* path=std::getenv("XPU2_RDL_INDEX_TRACE");if(!path||!*path)return;
    std::ofstream f(path,std::ios::app);
    f<<"{\"event\":\"indexed_update\",\"update\":"<<state.updates<<",\"revision\":"<<state.index.acquire()->revision
     <<",\"initialized\":"<<(initialized?"true":"false")<<",\"noop\":"<<(noOp?"true":"false")
     <<",\"objects_scanned\":"<<captured.objects<<",\"attributes_encoded\":"<<captured.attributes<<",\"bytes_encoded\":"<<captured.bytes
     <<",\"initialization_us\":"<<initUs<<",\"read_us\":"<<readUs<<",\"capture_us\":"<<captureUs<<",\"prepare_us\":"<<prepareUs<<",\"apply_us\":"<<applyUs<<"}\n";
    if(!f)throw std::runtime_error("Cannot write native index diagnostic");
}
template<class ReadDelta> void update(rdl::SceneContext& target,bool rendering,ReadDelta read){
    if(rendering)throw std::logic_error("Cannot apply indexed scene while rendering");
    healthy(target);
    auto start=std::chrono::steady_clock::now();
    auto& slot=states()[&target];bool initialized=!slot;
    if(!slot)slot=std::make_unique<State>(target);
    auto& state=*slot;auto init=std::chrono::steady_clock::now();
    try {
        read(state.source);auto readEnd=std::chrono::steady_clock::now();
        auto captured=capture(state.source,state.index.acquire());auto capturedAt=std::chrono::steady_clock::now();
        auto candidate=state.index.prepare(state.index.acquire(),captured.edits,{},identity);auto prepared=std::chrono::steady_clock::now();
        bool noOp=candidate.view()==state.index.acquire();
        if(!noOp)rdlindex::apply(candidate.view(),target); // Keep native dirty flags for startFrame().
        auto applied=std::chrono::steady_clock::now();
        if(!state.index.commit(candidate))throw std::runtime_error("Native index commit rejected");
        state.source.commitAllChanges();++state.updates;
        auto us=[](auto a,auto b){return std::chrono::duration_cast<std::chrono::microseconds>(b-a).count();};
        record(state,captured,initialized,us(start,init),us(init,readEnd),us(readEnd,capturedAt),us(capturedAt,prepared),us(prepared,applied),noOp);
    } catch(...) {
        // Mutation is not rollback-safe. No later start/update is allowed until
        // the RenderContext is destroyed/recreated; never render a partial scene.
        state.invalid=true;throw;
    }
}
} // namespace xpu2::rdllive

