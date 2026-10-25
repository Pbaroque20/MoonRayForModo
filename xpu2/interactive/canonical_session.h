// Private scene-service adapter. Call only on its owning scene-service thread.
// Renderers receive immutable RDLB files, never pointers into the mutable replica.
#pragma once
#include "routing_index.h"
#include "snapshot_budget.h"
#include "../rdl_replica.h"
#include <filesystem>
#include <optional>

namespace xpu2::interactive {
namespace ri=xpu2::rdlindex;
namespace fs=std::filesystem;
struct CanonicalFrame {
    View routing;
    fs::path scene;
    size_t attributesEncoded,sourceBytes;
};
using CanonicalView=std::shared_ptr<const CanonicalFrame>;

class CanonicalSession {
    ix::SceneIndex index_;
    Router router_;
    ri::NativeReplica replica_;
    CanonicalView active_,pendingFrame_;
    SnapshotBudget budget_;
    std::optional<Router::Pending> pending_;
    const ri::rdl::SceneContext *source_=nullptr,*pendingSource_=nullptr;
    // The classification of an RDL object (entity_classes.h through the session); none: every object falls back.
    std::function<Decision(const ri::rdl::SceneObject&)> classify_;
    static ix::Bytes retain(ix::Kind,ix::Field,const ix::Bytes& bytes){return bytes;}
    bool current(const CanonicalView& frame) const {
        // Router's thread check also protects these coordinator-owned fields.
        router_.acquire();return frame && frame==pendingFrame_ && pending_.has_value();
    }
public:
    CanonicalSession(std::string dso,Epoch initial,ix::Limits limits={},RetainedLimits retained={})
      :index_(limits),router_(index_,initial),replica_(std::move(dso),index_.acquire()),budget_(retained) {}
    CanonicalSession(const CanonicalSession&)=delete;
    CanonicalSession& operator=(const CanonicalSession&)=delete;
    CanonicalView acquire() const {router_.acquire();return active_;}
    // Set before the first scene: the router classifies every object then, and each changed one after.
    void classifier(std::function<Decision(const ri::rdl::SceneObject&)> classify) {router_.acquire();classify_=std::move(classify);}
    RetainedUsage retainedUsage() {router_.acquire();return budget_.usage();}
    const ri::rdl::SceneContext& replica() const {return replica_.context();}

    // One in-flight preparation, bounded by index limits. Failed serialization or
    // native application leaves the old publication in place and repairs replica.
    // No file is overwritten. Failed staging directories remain as local evidence.
    CanonicalView prepare(const ri::rdl::SceneContext& source,const fs::path& folder,Epoch epoch) {
        router_.acquire();
        if(pending_)throw std::logic_error("Reject or publish pending scene first");
        if(!folder.is_absolute())throw std::invalid_argument("Absolute staging directory required");
        const auto base=index_.acquire();
        // A replacement canonical context may have clean dirty flags. Recapture
        // all attributes on that boundary; normal edits remain incremental.
        auto captured=ri::capture(source,base,source_!=&source);
        std::set<std::string> present,removed;
        std::map<std::string,const ri::rdl::SceneObject*> objects;
        for(auto i=source.beginSceneObject();i!=source.endSceneObject();++i){
            const std::string id=ri::objectId(i->second->getName());
            present.insert(id);objects[id]=i->second;
        }
        for(const auto& group:base->kinds)if(group.first!=ix::Kind::Attribute)
            for(const auto& id:group.second)if(!present.count(id)){
                removed.insert(id);
                const auto& attributes=base->entities.at(id)->dependencies;
                removed.insert(attributes.begin(),attributes.end());
            }
        auto candidate=index_.prepare(base,captured.edits,removed,retain);
        // Each changed object classified (unknown ones fall back); without a classifier everything falls back.
        Classify classify;
        if(classify_)classify=[&](const std::string& id,const ix::View&){
            const auto it=objects.find(id);
            return it==objects.end()?Decision{}:classify_(*it->second);};
        auto routed=router_.prepare(candidate,epoch,0,classify);
        // Backpressure before touching the native replica or writing any files.
        // Candidate construction is separately bounded by SceneIndex limits.
        budget_.admit(candidate.view());
        if(!fs::create_directory(folder))throw std::invalid_argument("Fresh staging directory required");
        try {
            if(removed.empty())replica_.applyCandidate(candidate);
            else replica_.rebuild(candidate.view());
            const auto temporary=folder/"scene.rdlb.pending";
            const auto ready=folder/"scene.rdlb";
            ri::rdl::BinaryWriter(replica_.context()).toFile(temporary.string());
            fs::rename(temporary,ready);
            auto frame=std::make_shared<const CanonicalFrame>(CanonicalFrame{
                routed.view(),ready,captured.attributes,captured.bytes});
            pending_.emplace(std::move(routed));
            pendingFrame_=std::move(frame);pendingSource_=&source;
            return pendingFrame_;
        }catch(...) {
            replica_.rebuild(base);
            throw;
        }
    }
    // Preparation callback runs on the scene-service owner and can only inspect
    // the exact pending replica. It must return owned, immutable data, never a
    // SceneObject/reference into the mutable context. No renderer calls this.
    template<class Prepare>
    auto inspectPrepared(const CanonicalView& frame,Prepare&& prepare) const {
        if(!current(frame))throw std::logic_error("Only the current pending scene can be prepared");
        return prepare(replica_.context(),frame);
    }
    // The caller acknowledges ONLY after its fallback adapter accepts the frozen
    // input. This file-level adapter does not claim GPU allocations are ready.
    bool acknowledge(const CanonicalView& frame) {
        if(!current(frame))return false;
        // The backends the routed mode asks for: fallback, the CPU lane, or both lanes.
        const Mode mode=pending_->view()->mode;
        if(mode==Mode::Fallback)return router_.acknowledge(*pending_,Backend::Fallback);
        bool ok=router_.acknowledge(*pending_,Backend::Cpu);
        if(mode==Mode::NativeMixed)ok=router_.acknowledge(*pending_,Backend::Gpu)&&ok;
        return ok;
    }
    bool publish(const CanonicalView& frame) {
        if(!current(frame)||!router_.commit(*pending_))return false;
        active_=pendingFrame_;source_=pendingSource_;
        pending_.reset();pendingFrame_.reset();pendingSource_=nullptr;return true;
    }
    bool reject(const CanonicalView& frame) {
        if(!current(frame))return false;
        replica_.rebuild(index_.acquire());
        pending_.reset();pendingFrame_.reset();pendingSource_=nullptr;return true;
    }
};
}
