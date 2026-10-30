// Bounded coordinator dispatch at an owned-work boundary. No native stack pointers.
#pragma once
#include "texture_dependencies.h"
#include "texture_async.h"
namespace xpu2::texture {
class TextureWorkQueue {
public:
    struct Need {Key key;size_t bytes;};
    struct Ready {
        uint64_t id=0,attempt=0,serial=0;
        std::shared_ptr<const int> owner;
        DependencyView dependencies;
        Bytes payload; // Caller must serialize independently owned work, never borrowed pointers.
        std::vector<Cache::Lease> pages;
        bool gpu=false;std::string failure;
    };
    using Lease=std::shared_ptr<const Ready>;
    enum class Finish {Accepted,Revoked,Failed,Pending,Invalid};
    struct Stats {uint64_t admitted=0,claimed=0,accepted=0,revoked=0,failed=0,bypasses=0,waitingPolls=0;size_t peakJobs=0,peakPayload=0;};
private:
    struct Done:Fence {bool ready()override{return true;}void wait()override{}};
    struct Entry {std::shared_ptr<Ready> ready;std::vector<Need> needs;bool claimed=false,revoked=false;};
    Cache& cache_;AsyncTextureLoader& loader_; // Exclusive loader ownership during this queue's lifetime.
    const std::thread::id coordinator_=std::this_thread::get_id();
    const std::shared_ptr<const int> owner_=std::make_shared<const int>(0);
    DependencyView dependencies_;uint64_t attempt_=0,serial_=0;bool accepting_=false;
    size_t maxJobs_,maxPayload_,maxIdentities_,payload_=0;
    std::map<uint64_t,Entry> jobs_;std::set<uint64_t> seen_;
    std::map<Key,AsyncTextureLoader::Ticket> loading_;Stats stats_;
    void check()const{if(std::this_thread::get_id()!=coordinator_)throw std::logic_error("Texture work coordinator violation");}
    void release(const std::vector<Cache::Lease>& pages,const std::shared_ptr<Fence>& fence){for(const auto& p:pages){if(p.device)cache_.retire(p,fence);else cache_.release(p);}}
    void prune(){std::set<Key> wanted;for(const auto& [id,job]:jobs_)if(!job.claimed)for(const auto& n:job.needs)wanted.insert(n.key);
        for(auto i=loading_.begin();i!=loading_.end();){if(!wanted.count(i->first)){loader_.cancel(i->second);i=loading_.erase(i);}else ++i;}}
    void cancelPending(){for(auto i=jobs_.begin();i!=jobs_.end();){if(i->second.claimed){i->second.revoked=true;++i;}else{payload_-=i->second.ready->payload.size();i=jobs_.erase(i);}}prune();}
    std::optional<Cache::Lease> acquire(const Need& n,bool gpu,bool drive){
        if(auto hit=cache_.acquireResident(n.key,n.bytes,gpu))return hit;
        if(!drive)return {};
        if(cache_.hasBacking(n.key,n.bytes,gpu))return cache_.acquire(n.key,n.bytes,[](const Key&,size_t)->Bytes{throw std::logic_error("Unexpected work cache miss");},gpu);
        auto i=loading_.find(n.key);
        if(i==loading_.end()){auto ticket=loader_.submit(n.key,n.bytes);if(!ticket)return {};i=loading_.emplace(n.key,*ticket).first;}
        auto ticket=i->second;auto state=loader_.state(ticket);
        if(state==AsyncTextureLoader::State::Failed){loading_.erase(i);loader_.take(ticket);throw std::runtime_error("Missing decode failure");}
        if(state!=AsyncTextureLoader::State::Ready)return {};
        return cache_.acquire(n.key,n.bytes,[&](const Key&,size_t){auto bytes=loader_.take(ticket);loading_.erase(n.key);if(!bytes)throw std::logic_error("Lost ready decode");return std::move(*bytes);},gpu);
    }
public:
    TextureWorkQueue(Cache& cache,AsyncTextureLoader& loader,size_t jobs=64,size_t payloadBytes=1<<20,size_t identities=65536)
      :cache_(cache),loader_(loader),maxJobs_(jobs),maxPayload_(payloadBytes),maxIdentities_(identities){if(!jobs||jobs>4096||!payloadBytes||!identities)throw std::invalid_argument("Invalid texture work limits");}
    TextureWorkQueue(const TextureWorkQueue&)=delete;TextureWorkQueue& operator=(const TextureWorkQueue&)=delete;
    ~TextureWorkQueue(){if(!close())std::terminate();}
    void begin(uint64_t attempt,DependencyView dependencies){check();if(!dependencies||!attempt||attempt<=attempt_)throw std::invalid_argument("Work attempt must increase");
        cancelPending();seen_.clear();attempt_=attempt;dependencies_=std::move(dependencies);accepting_=true;
    }
    bool submit(uint64_t id,const std::string& material,Bytes payload,std::vector<Need> needs,bool gpu){check();
        if(!accepting_||seen_.count(id)||jobs_.size()>=maxJobs_||seen_.size()>=maxIdentities_||payload.size()>maxPayload_-payload_)return false;
        if(needs.size()>64)throw std::length_error("Texture working set too large");
        const auto& limits=cache_.limits();std::set<Key> keys;size_t bytes=0;
        for(const auto& n:needs){
            if(!n.bytes||!keys.insert(n.key).second)throw std::invalid_argument("Duplicate/empty job tile");
            auto m=dependencies_->materials.find(material);
            if(m==dependencies_->materials.end()||!m->second->unresolved.empty()||!m->second->resources.count(resourceKey(n.key)))throw std::invalid_argument("Unresolved/unindexed material work");
            if(n.bytes>limits.ram||(gpu&&(n.bytes>limits.vram||n.bytes>limits.staging))||n.bytes>SIZE_MAX-bytes)throw std::length_error("Unserviceable texture tile");bytes+=n.bytes;
        }
        if(bytes>(gpu?limits.vram:limits.ram)||needs.size()>limits.leases)throw std::length_error("Working set cannot fit cache");
        if(serial_==UINT64_MAX)throw std::overflow_error("Texture work serial exhausted");
        auto ready=std::make_shared<Ready>();ready->owner=owner_;ready->id=id;ready->attempt=attempt_;ready->serial=++serial_;ready->dependencies=dependencies_;ready->payload=std::move(payload);ready->gpu=gpu;ready->pages.reserve(needs.size());
        auto [i,inserted]=jobs_.emplace(ready->serial,Entry{ready,std::move(needs)});
        try{seen_.insert(id);}catch(...){jobs_.erase(i);throw;}
        payload_+=ready->payload.size();++stats_.admitted;stats_.peakJobs=std::max(stats_.peakJobs,jobs_.size());stats_.peakPayload=std::max(stats_.peakPayload,payload_);return true;
    }
    Lease claim(){check();bool drive=true,waited=false;
        for(auto& [serial,job]:jobs_){if(job.claimed)continue;auto& ready=*job.ready;bool complete=true;
            try{for(const auto& need:job.needs){auto page=acquire(need,ready.gpu,drive);if(!page){complete=false;break;}ready.pages.push_back(*page);}}
            catch(const std::exception& e){ready.failure=e.what();complete=true;}
            if(!complete||!ready.failure.empty()){release(ready.pages,std::make_shared<Done>());ready.pages.clear();}
            if(!complete){drive=false;waited=true;++stats_.waitingPolls;continue;}
            job.claimed=true;++stats_.claimed;if(waited)++stats_.bypasses;prune();return job.ready;
        }
        return {};
    }
    // Caller must finish GPU work with its completion fence before publishing.
    // Failed/revoked work may release resources, but never contributes to the film.
    Finish finish(const Lease& lease,std::shared_ptr<Fence> completion={}){check();
        if(!lease||lease->owner!=owner_)return Finish::Invalid;auto i=jobs_.find(lease->serial);
        if(i==jobs_.end()||!i->second.claimed||i->second.ready!=lease)return Finish::Invalid;
        if(lease->gpu&&!lease->pages.empty()){if(!completion)throw std::invalid_argument("GPU job requires completion fence");if(!completion->ready())return Finish::Pending;}
        bool revoked=i->second.revoked||!accepting_||lease->attempt!=attempt_||lease->dependencies!=dependencies_;
        auto result=revoked?Finish::Revoked:lease->failure.empty()?Finish::Accepted:Finish::Failed;
        release(lease->pages,completion);payload_-=lease->payload.size();jobs_.erase(i);prune();
        if(result==Finish::Accepted)++stats_.accepted;else if(result==Finish::Revoked)++stats_.revoked;else ++stats_.failed;return result;
    }
    bool close(){check();accepting_=false;cancelPending();return jobs_.empty();}
    const Stats& stats()const{check();return stats_;}
};
} // namespace xpu2::texture
