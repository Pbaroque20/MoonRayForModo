// Version-acknowledged, exclusively owned native scene replica.
#pragma once
#include "rdl_scene_index.h"
namespace xpu2::rdlindex {
class NativeReplica {
    std::string dso_;
    std::unique_ptr<rdl::SceneContext> context_;
    View applied_;
    const std::thread::id coordinator_=std::this_thread::get_id();
    void checkThread() const {if(std::this_thread::get_id()!=coordinator_)throw std::logic_error("Foreign native scene coordinator");}
    std::unique_ptr<rdl::SceneContext> empty() const {
        auto context=std::make_unique<rdl::SceneContext>();context->setProxyModeEnabled(true);context->setDsoPath(dso_);return context;
    }
public:
    NativeReplica(std::string dso,const View& initial):dso_(std::move(dso)),applied_(initial) {
        if(!initial||initial->revision||!initial->entities.empty())throw std::invalid_argument("Empty initial index required");
        context_=empty();
    }
    const rdl::SceneContext& context() const {checkThread();if(!context_)throw std::logic_error("Native replica invalid; rebuild required");return *context_;}
    View acknowledged() const {checkThread();return applied_;}
    bool valid() const {checkThread();return bool(context_);}
    void applyCandidate(const SceneIndex::Candidate& candidate) {
        checkThread();
        if(!context_)throw std::logic_error("Native replica invalid; rebuild required");
        if(candidate.baseView()!=applied_)throw std::invalid_argument("Native replica base mismatch");
        if(candidate.view()==applied_)return;
        try {
            apply(candidate.view(),*context_,applied_->revision==0);
            context_->commitAllChanges();applied_=candidate.view();
        } catch(...) {
            // No renderer borrows this replica. Unexpected native mutation failure
            // discards it completely; the index is still at its prior committed base.
            context_.reset();applied_.reset();throw;
        }
    }
    void rebuild(const View& snapshot) {
        checkThread();if(!snapshot)throw std::invalid_argument("Missing rebuild snapshot");
        auto fresh=empty();apply(snapshot,*fresh,true);fresh->commitAllChanges();
        context_=std::move(fresh);applied_=snapshot;
    }
};
} // namespace xpu2::rdlindex
