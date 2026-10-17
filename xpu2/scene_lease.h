// Experimental batch-scoped retention. Resource must OWN its full dependency graph.
#pragma once
#include "shadow_request.h"
#include <atomic>
#include <limits>
#include <memory>
#include <stdexcept>
#include <thread>
namespace xpu2 {
inline uint64_t nextSceneIdentity() {
    static std::atomic<uint64_t> serial{0};
    auto previous=serial.load();
    do {
        if(previous==std::numeric_limits<uint64_t>::max()) throw std::overflow_error("Scene identity exhausted");
    } while(!serial.compare_exchange_weak(previous,previous+1));
    return previous+1;
}
// Coordinator publishes/retires; workers may COPY and READ leases. No mutable
// native scene pointer becomes owned merely by putting it inside Resource.
template<class Resource> class SceneLeaseGate {
    struct Snapshot {
        const uint64_t scene,revision;
        std::unique_ptr<const Resource> resource;
        const ShadowBindings bindings;
        Snapshot(uint64_t s,uint64_t r,std::unique_ptr<Resource>& value,std::vector<uint64_t> lights)
          :scene(s),revision(r),resource(std::move(value)),bindings(s,r,std::move(lights)) {}
    };
public:
    class Lease {
        friend class SceneLeaseGate;
        std::shared_ptr<const Snapshot> snapshot;
        std::shared_ptr<const int> owner;
        uint64_t attempt_=0;
        Lease(std::shared_ptr<const Snapshot> s,std::shared_ptr<const int> o,uint64_t a)
          :snapshot(std::move(s)),owner(std::move(o)),attempt_(a) {}
    public:
        Lease()=default;
        explicit operator bool() const {return bool(snapshot);}
        uint64_t scene() const {return snapshot ? snapshot->scene : 0;}
        uint64_t revision() const {return snapshot ? snapshot->revision : 0;}
        uint64_t attempt() const {return attempt_;}
        const Resource& resource() const {if(!snapshot)throw std::logic_error("Empty scene lease");return *snapshot->resource;}
        bool resolve(const ShadowRequest& q,uint64_t& light) const {
            light=0;return snapshot && snapshot->bindings.resolve(q,light);
        }
    };
private:
    const std::thread::id coordinator=std::this_thread::get_id();
    const std::shared_ptr<const int> owner=std::make_shared<const int>(0);
    const size_t capacity;
    std::vector<std::shared_ptr<const Snapshot>> retained;
    std::shared_ptr<const Snapshot> active;
    uint64_t attempt_=0,revision_=0;
    void checkThread() const {if(std::this_thread::get_id()!=coordinator)throw std::logic_error("Foreign scene coordinator");}
public:
    explicit SceneLeaseGate(size_t limit=2):capacity(limit) {
        if(!limit || limit>64)throw std::invalid_argument("Invalid scene retention bound");
        retained.reserve(limit); // Publication cannot allocate after consuming Resource.
    }
    SceneLeaseGate(const SceneLeaseGate&)=delete;
    SceneLeaseGate& operator=(const SceneLeaseGate&)=delete;
    ~SceneLeaseGate() {if(active || !retained.empty())std::terminate();}
    size_t collect() {
        checkThread();
        for(auto it=retained.begin();it!=retained.end();) {
            if(*it!=active && it->use_count()==1)it=retained.erase(it);
            else ++it;
        }
        return retained.size();
    }
    // False means backpressure; caller keeps its candidate and current scene.
    bool publish(uint64_t revision,uint64_t attempt,std::unique_ptr<Resource>& value,std::vector<uint64_t> lights) {
        checkThread();
        if(!value || revision<=revision_ || attempt<=attempt_)throw std::invalid_argument("Scene/restart identity must increase");
        collect();
        if(retained.size()==capacity && (!active || active.use_count()!=2))return false;
        auto next=std::make_shared<const Snapshot>(nextSceneIdentity(),revision,value,std::move(lights));
        active.reset();collect();
        retained.push_back(next);active=std::move(next);attempt_=attempt;revision_=revision;
        return true;
    }
    void restart(uint64_t attempt) {
        checkThread();if(!active || attempt<=attempt_)throw std::invalid_argument("Invalid render restart");attempt_=attempt;
    }
    Lease acquire() const {checkThread();return active ? Lease(active,owner,attempt_) : Lease();}
    // Scene validity only, NOT exactly-once result acceptance. Pair with a request
    // mailbox. Call and publish results on this coordinator without yielding.
    bool current(const Lease& lease) const {
        checkThread();return active && lease.owner==owner && lease.snapshot==active && lease.attempt_==attempt_;
    }
    // Closing revokes publication, but never destroys a resource held by a worker.
    bool close() {checkThread();active.reset();return collect()==0;}
};
}
