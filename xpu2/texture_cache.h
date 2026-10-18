// Bounded, coordinator-owned read-only mip-tile cache. No native texture sampler yet.
#pragma once
#include <algorithm>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <tuple>
#include <vector>
namespace xpu2::texture {
using Bytes=std::vector<uint8_t>;
struct Key {
    std::string asset, interpretation; // Content identity and working-space/format signature.
    uint64_t revision=0;
    uint32_t mip=0,x=0,y=0,layer=0;
    auto fields() const {return std::tie(asset,interpretation,revision,mip,x,y,layer);}
    bool operator<(const Key& other) const {return fields()<other.fields();}
    bool operator==(const Key& other) const {return fields()==other.fields();}
};
struct Fence {virtual ~Fence()=default;virtual bool ready()=0;virtual void wait()=0;};
struct DevicePage: Fence {virtual uint64_t address() const=0;};
struct Backend {
    virtual ~Backend()=default;
    // Owns a pinned staging copy until ready(). No borrowed host pointers survive.
    virtual std::shared_ptr<DevicePage> upload(const Bytes&)=0;
    virtual void drain()=0;
};
struct Limits {size_t ram=256<<20,vram=256<<20,staging=16<<20,entries=65536,leases=4096,uploads=64;};
struct Residency {Key key;size_t bytes=0;bool cpu=false,gpu=false,cpuPinned=false,gpuPinned=false,uploading=false;};
struct Stats {
    uint64_t loads=0,cpuHits=0,gpuHits=0,h2dBytes=0,d2hBytes=0;
    uint64_t cpuEvictions=0,gpuEvictions=0,blocked=0,failedLoads=0,pendingUploads=0,uploadPolls=0;
    size_t ram=0,vram=0,staging=0,peakRam=0,peakVram=0,peakStaging=0;
};
class Cache {
    struct Record {
        size_t bytes=0;std::shared_ptr<const Bytes> cpu;
        std::shared_ptr<DevicePage> gpu;
        size_t cpuPins=0,gpuPins=0;uint64_t touched=0;
        bool uploading=false,cpuSpeculative=true,gpuSpeculative=true;
    };
public:
    struct Lease {
        std::shared_ptr<const int> owner;uint64_t serial=0;Key key;bool device=false;
    };
    using Loader=std::function<Bytes(const Key&,size_t)>;
private:
    struct Use {Lease lease;std::shared_ptr<Fence> fence;};
    Backend& backend_;Limits limits_;Stats stats_;
    const std::shared_ptr<const int> owner_=std::make_shared<const int>(0);
    std::map<Key,Record> pages_;std::map<uint64_t,Use> uses_;std::set<Key> uploading_;
    uint64_t clock_=0,serial_=0;bool closed_=false;
    const std::thread::id coordinator_=std::this_thread::get_id();
    void check() const {if(std::this_thread::get_id()!=coordinator_||closed_)throw std::logic_error("Texture cache coordinator/closed violation");}
    void peaks(){stats_.peakRam=std::max(stats_.peakRam,stats_.ram);stats_.peakVram=std::max(stats_.peakVram,stats_.vram);stats_.peakStaging=std::max(stats_.peakStaging,stats_.staging);}
    void empty(const Key& key){auto it=pages_.find(key);if(it!=pages_.end()&&!it->second.cpu&&!it->second.gpu)pages_.erase(it);}
    bool room(size_t bytes,bool gpu,bool speculative,const Key& protect){
        auto& used=gpu?stats_.vram:stats_.ram;auto cap=gpu?limits_.vram:limits_.ram;
        if(bytes>cap)throw std::length_error("Texture tile exceeds cache budget");
        while(bytes>cap-used){
            auto victim=pages_.end();
            for(auto it=pages_.begin();it!=pages_.end();++it){
                auto& r=it->second;if(it->first==protect)continue;
                bool free=gpu ? bool(r.gpu)&&!r.gpuPins&&!r.uploading&&(!speculative||r.gpuSpeculative)
                              : bool(r.cpu)&&!r.cpuPins&&(!speculative||r.cpuSpeculative);
                if(free&&(victim==pages_.end()||r.touched<victim->second.touched))victim=it;
            }
            if(victim==pages_.end()){++stats_.blocked;return false;}
            auto key=victim->first;auto& r=victim->second;
            if(gpu){r.gpu.reset();++stats_.gpuEvictions;}else{r.cpu.reset();++stats_.cpuEvictions;}
            used-=r.bytes;empty(key); // Clean backed tiles require no device-to-host copy.
        }
        return true;
    }
    bool entryRoom(bool speculative){
        if(pages_.size()<limits_.entries)return true;
        auto victim=pages_.end();
        for(auto it=pages_.begin();it!=pages_.end();++it){const auto& r=it->second;
            if(r.cpuPins||r.gpuPins||r.uploading||(speculative&&((r.cpu&&!r.cpuSpeculative)||(r.gpu&&!r.gpuSpeculative))))continue;
            if(victim==pages_.end()||r.touched<victim->second.touched)victim=it;
        }
        if(victim==pages_.end()){++stats_.blocked;return false;}
        const auto& r=victim->second;
        if(r.cpu){stats_.ram-=r.bytes;++stats_.cpuEvictions;}
        if(r.gpu){stats_.vram-=r.bytes;++stats_.gpuEvictions;}
        pages_.erase(victim);return true;
    }
    bool ensure(const Key& key,size_t bytes,const Loader& load,bool gpu,bool speculative){
        check();poll();
        if(key.asset.empty()||key.interpretation.empty()||!bytes||!load)throw std::invalid_argument("Incomplete texture page description");
        if(bytes>limits_.ram||(gpu&&(bytes>limits_.vram||bytes>limits_.staging)))throw std::length_error("Tile cannot fit texture budgets");
        auto existing=pages_.find(key);
        if(existing!=pages_.end()&&existing->second.bytes!=bytes)throw std::invalid_argument("Immutable tile size changed without revision");
        if(existing!=pages_.end()&&((gpu&&existing->second.gpu)||(!gpu&&existing->second.cpu))){
            auto& r=existing->second;r.touched=++clock_;
            if(gpu){if(!speculative)r.gpuSpeculative=false;if(r.uploading){++stats_.pendingUploads;return false;}++stats_.gpuHits;}
            else{if(!speculative)r.cpuSpeculative=false;++stats_.cpuHits;}
            return true;
        }
        // Avoid disk reads if GPU/staging admission is already blocked.
        if(gpu&&(bytes>limits_.staging-stats_.staging||uploading_.size()>=limits_.uploads)){++stats_.blocked;return false;}
        if(gpu&&!room(bytes,true,speculative,key))return false;
        if(existing==pages_.end()&&!entryRoom(speculative))return false;
        if(existing==pages_.end()||!existing->second.cpu){
            if(!room(bytes,false,speculative,key))return false;
            Bytes loaded;
            try{loaded=load(key,bytes);if(loaded.size()!=bytes)throw std::invalid_argument("Texture loader returned wrong tile size");}
            catch(...){++stats_.failedLoads;throw;}
            auto& r=pages_[key];r.bytes=bytes;r.cpu=std::make_shared<const Bytes>(std::move(loaded));
            r.cpuSpeculative=speculative;stats_.ram+=bytes;++stats_.loads;peaks();
        }
        auto& r=pages_.at(key);r.touched=++clock_;if(!speculative)r.cpuSpeculative=false;
        if(!gpu)return true;
        uploading_.insert(key);std::shared_ptr<DevicePage> page;
        try{page=backend_.upload(*r.cpu);if(!page)throw std::runtime_error("Texture upload returned no page");}
        catch(...){uploading_.erase(key);throw;}
        r.gpu=std::move(page);r.uploading=true;r.gpuSpeculative=speculative;
        stats_.vram+=bytes;stats_.staging+=bytes;stats_.h2dBytes+=bytes;peaks();
        poll();return !r.uploading;
    }
    Use& use(const Lease& lease){
        auto it=uses_.find(lease.serial);
        if(lease.owner!=owner_||it==uses_.end()||!(it->second.lease.key==lease.key)||it->second.lease.device!=lease.device)
            throw std::invalid_argument("Stale/foreign texture lease");
        return it->second;
    }
public:
    explicit Cache(Backend& backend,Limits limits={}):backend_(backend),limits_(limits){if(!limits.ram||!limits.vram||!limits.staging||!limits.entries||!limits.leases||!limits.uploads)throw std::invalid_argument("Empty texture budget");}
    Cache(const Cache&)=delete;Cache& operator=(const Cache&)=delete;
    // Backend outlives cache. Call close() after retiring every lease. Exceptional
    // teardown drains the device before dropping allocations; CPU borrows must end.
    ~Cache(){if(!closed_){try{backend_.drain();}catch(...){std::terminate();}}}
    void poll(){
        check();
        for(auto it=uploading_.begin();it!=uploading_.end();){auto& r=pages_.at(*it);++stats_.uploadPolls;
            if(r.gpu->ready()){r.uploading=false;stats_.staging-=r.bytes;it=uploading_.erase(it);}else ++it;
        }
        for(auto it=uses_.begin();it!=uses_.end();){
            if(it->second.fence&&it->second.fence->ready()){--pages_.at(it->second.lease.key).gpuPins;it=uses_.erase(it);}else ++it;
        }
    }
    bool prefetch(const Key& key,size_t bytes,const Loader& load){return ensure(key,bytes,load,true,true);}
    std::optional<Lease> acquire(const Key& key,size_t bytes,const Loader& load,bool gpu){
        check();poll();if(uses_.size()>=limits_.leases){++stats_.blocked;return {};}
        if(!ensure(key,bytes,load,gpu,false))return {};
        auto& r=pages_.at(key);Lease lease{owner_,++serial_,key,gpu};
        uses_.emplace(lease.serial,Use{lease,{}});if(gpu)++r.gpuPins;else ++r.cpuPins;return lease;
    }
    const Bytes& cpu(const Lease& lease){check();auto& u=use(lease);if(u.lease.device)throw std::logic_error("Expected CPU texture lease");return *pages_.at(lease.key).cpu;}
    uint64_t gpu(const Lease& lease){check();auto& u=use(lease);if(!u.lease.device||u.fence)throw std::logic_error("Expected active GPU texture lease");return pages_.at(lease.key).gpu->address();}
    void release(const Lease& lease){check();auto& u=use(lease);if(u.lease.device)throw std::logic_error("GPU texture needs a completion fence");--pages_.at(lease.key).cpuPins;uses_.erase(lease.serial);}
    void retire(const Lease& lease,std::shared_ptr<Fence> completion){check();auto& u=use(lease);if(!u.lease.device||u.fence||!completion)throw std::invalid_argument("Invalid GPU completion fence");u.fence=std::move(completion);poll();}
    // Coordinator snapshots and guarded eviction for the residency policy.
    bool hasBacking(const Key& key,size_t bytes,bool gpu){check();poll();auto i=pages_.find(key);if(i==pages_.end())return false;
        if(i->second.bytes!=bytes)throw std::invalid_argument("Immutable tile size changed without revision");return bool(i->second.cpu)||(gpu&&bool(i->second.gpu));}
    std::vector<Residency> residency(){check();poll();std::vector<Residency> out;out.reserve(pages_.size());
        for(const auto& p:pages_){const auto& r=p.second;out.push_back({p.first,r.bytes,bool(r.cpu),bool(r.gpu),r.cpuPins!=0,r.gpuPins!=0,r.uploading});}return out;
    }
    bool discard(const Key& key,bool device){check();poll();auto it=pages_.find(key);if(it==pages_.end())return true;auto& r=it->second;
        if(device){if(r.gpuPins||r.uploading)return false;if(r.gpu){r.gpu.reset();stats_.vram-=r.bytes;++stats_.gpuEvictions;}}
        else{if(r.cpuPins)return false;if(r.cpu){r.cpu.reset();stats_.ram-=r.bytes;++stats_.cpuEvictions;}}
        empty(key);return true;
    }
    const Stats& stats() const {return stats_;}
    bool close(){check();poll();if(!uses_.empty())return false;backend_.drain();pages_.clear();uploading_.clear();stats_.ram=stats_.vram=stats_.staging=0;closed_=true;return true;}
};
} // namespace xpu2::texture
