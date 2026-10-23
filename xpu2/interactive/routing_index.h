// Private XPU2 routing/publication layer over the existing immutable scene index.
// Classifier evidence and RDL2 capture are separate adapters. Unknown = fallback.
#pragma once
#include "../indexed_scene.h"
#include <array>
#include <functional>
#include <memory>
#include <string>
#include <thread>

namespace xpu2::interactive {
namespace ix = xpu2::indexed;
enum class Support { Fallback, Cpu, Both };
enum class Backend { Cpu, Gpu, Fallback };
enum class Mode { NativeMixed, NativeCpu, Fallback };
struct Epoch {
    uint64_t session, scene, camera, settings;
    bool operator==(const Epoch& b) const {
        return session==b.session && scene==b.scene && camera==b.camera && settings==b.settings;
    }
};
struct Decision {
    Support support = Support::Fallback;
    // Nonempty conformance identity required before a feature can be native.
    std::string evidence;
};
struct Snapshot {
    ix::View scene;
    Epoch epoch;
    uint64_t policyRevision;
    ix::PersistentMap<std::string,Decision> decisions;
    std::array<size_t,3> totals{};
    Mode mode = Mode::Fallback;
    size_t classified = 0;
};
using View = std::shared_ptr<const Snapshot>;
using Classify = std::function<Decision(const std::string&,const ix::View&)>;

class Router {
public:
    class Pending {
        friend class Router;
        std::shared_ptr<const int> owner;
        View base;
        std::shared_ptr<Snapshot> next;
        ix::SceneIndex::Candidate scene;
        std::set<Backend> ready;
        Pending(std::shared_ptr<const int> o, View b, std::shared_ptr<Snapshot> n,
                ix::SceneIndex::Candidate c):owner(std::move(o)),base(std::move(b)),
                next(std::move(n)),scene(std::move(c)) {}
    public:
        View view() const {return next;}
    };
    explicit Router(ix::SceneIndex& index,Epoch epoch):index_(index) {
        active_=std::make_shared<const Snapshot>(Snapshot{index.acquire(),epoch,0,{},{},Mode::Fallback,0});
    }
    Router(const Router&) = delete;
    Router& operator=(const Router&) = delete;
    View acquire() const { checkThread(); return active_; }

    Pending prepare(const ix::SceneIndex::Candidate& scene,Epoch epoch,
                    uint64_t policyRevision,const Classify& classify={}) {
        checkThread();
        if(scene.baseView()!=active_->scene || !index_.current(active_->scene))
            throw std::invalid_argument("Routing base is stale");
        if(epoch.session!=active_->epoch.session ||
           epoch.scene<active_->epoch.scene || epoch.camera<active_->epoch.camera ||
           epoch.settings<active_->epoch.settings || epoch==active_->epoch ||
           policyRevision<active_->policyRevision)
            throw std::invalid_argument("Invalid routing generation");
        if(scene.view()!=scene.baseView() && epoch.scene==active_->epoch.scene)
            throw std::invalid_argument("Scene data changed without scene epoch");
        if(policyRevision!=active_->policyRevision && epoch.settings==active_->epoch.settings)
            throw std::invalid_argument("Support/residency policy changed without settings epoch");
        auto next=std::make_shared<Snapshot>(Snapshot{scene.view(),epoch,policyRevision,
                     active_->decisions,active_->totals,Mode::Fallback,0});
        auto remove=[&](const std::string& id) {
            auto old=next->decisions.find(id);
            if(old!=next->decisions.end()) {
                --next->totals[static_cast<unsigned>(old->second.support)];
                next->decisions.erase(id);
            }
        };
        // A no-op scene candidate can retain earlier change metadata; only use
        // that set when the underlying index revision actually changed.
        if(scene.view()!=scene.baseView())
            for(const auto& id:scene.view()->changes.removed) remove(id);
        std::set<std::string> dirty;
        if(policyRevision!=active_->policyRevision || active_->decisions.empty()) {
            for(const auto& item:scene.view()->entities)
                if(item.second->kind!=ix::Kind::Attribute) dirty.insert(item.first);
        } else if(scene.view()!=scene.baseView()) {
            dirty=scene.view()->changes.affected;
        }
        for(const auto& id:dirty) {
            auto item=scene.view()->entities.find(id);
            if(item==scene.view()->entities.end() || item->second->kind==ix::Kind::Attribute)
                continue;
            Decision d=classify?classify(id,scene.view()):Decision{};
            if(d.support!=Support::Fallback && d.support!=Support::Cpu && d.support!=Support::Both)
                throw std::invalid_argument("Unknown support value");
            if(d.support!=Support::Fallback && d.evidence.empty())
                throw std::invalid_argument("Native support lacks conformance identity");
            remove(id);
            next->decisions.set(id,d);
            ++next->totals[static_cast<unsigned>(d.support)];
            ++next->classified;
        }
        if(next->totals[0] || next->decisions.empty()) next->mode=Mode::Fallback;
        else if(next->totals[2]) next->mode=Mode::NativeMixed;
        else next->mode=Mode::NativeCpu;
        return Pending(owner_,active_,std::move(next),scene);
    }

    bool acknowledge(Pending& pending,Backend backend) {
        checkThread();
        if(!current(pending)) return false;
        const auto needs=required(pending.next->mode);
        if(!needs.count(backend)) return false;
        pending.ready.insert(backend);
        return true;
    }

    bool commit(const Pending& pending) {
        checkThread();
        if(!current(pending) || pending.ready!=required(pending.next->mode)) return false;
        if(!index_.commit(pending.scene)) return false;
        active_=pending.next;
        return true;
    }

private:
    bool current(const Pending& p) const {
        return p.owner==owner_ && p.base==active_ && index_.current(p.scene.baseView());
    }
    static std::set<Backend> required(Mode m) {
        if(m==Mode::Fallback) return {Backend::Fallback};
        if(m==Mode::NativeCpu) return {Backend::Cpu};
        return {Backend::Cpu,Backend::Gpu};
    }
    void checkThread() const {
        if(std::this_thread::get_id()!=thread_)throw std::logic_error("Foreign routing coordinator");
    }
    ix::SceneIndex& index_;
    View active_;
    const std::thread::id thread_=std::this_thread::get_id();
    const std::shared_ptr<const int> owner_=std::make_shared<const int>(0);
};
}
