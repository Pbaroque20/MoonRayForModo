// Bounded single-worker decode queue. No CUDA or host-scene APIs on the worker.
#pragma once
#include "texture_cache.h"
#include <condition_variable>
#include <deque>
#include <mutex>
namespace xpu2::texture {
class AsyncTextureLoader {
public:
    enum class State {Queued,Loading,Ready,Failed,Cancelled,Gone};
    struct Ticket {std::shared_ptr<const int> owner;uint64_t id=0;};
    struct Stats {size_t heldBytes=0,peakBytes=0,heldRecords=0,peakRecords=0;uint64_t loads=0,failures=0,cancellations=0,duplicates=0,blocked=0;};
    using Factory=std::function<Cache::Loader()>;
private:
    struct Entry {uint64_t id;Key key;size_t bytes;State state=State::Queued;Bytes data;std::exception_ptr error;};
    size_t maxBytes_,maxRecords_;std::shared_ptr<const int> owner_=std::make_shared<const int>(0);
    std::thread::id coordinator_=std::this_thread::get_id();std::thread worker_;
    mutable std::mutex mutex_;std::condition_variable wake_;bool stopping_=false,closed_=false;
    uint64_t serial_=0;Stats stats_;std::deque<uint64_t> queued_;
    std::map<uint64_t,std::shared_ptr<Entry>> entries_;std::map<Key,uint64_t> keys_;
    void ownerCheck()const{if(std::this_thread::get_id()!=coordinator_)throw std::logic_error("Async loader coordinator violation");}
    void ticketCheck(const Ticket& t)const{if(t.owner!=owner_||!t.id||t.id>serial_)throw std::invalid_argument("Foreign texture ticket");}
    void unlink(const std::shared_ptr<Entry>& e){auto k=keys_.find(e->key);if(k!=keys_.end()&&k->second==e->id)keys_.erase(k);}
    void erase(std::shared_ptr<Entry> e){unlink(e);Bytes().swap(e->data);entries_.erase(e->id);stats_.heldBytes-=e->bytes;--stats_.heldRecords;}
    void cancelEntry(std::shared_ptr<Entry> e){
        if(e->state==State::Cancelled)return;++stats_.cancellations;unlink(e);
        if(e->state==State::Loading){e->state=State::Cancelled;return;}
        if(e->state==State::Queued){auto q=std::find(queued_.begin(),queued_.end(),e->id);if(q!=queued_.end())queued_.erase(q);}
        erase(e);
    }
    void run(Factory factory){
        Cache::Loader load;std::exception_ptr startup;
        try{load=factory();if(!load)throw std::invalid_argument("Empty worker loader");}catch(...){startup=std::current_exception();}
        for(;;){
            std::shared_ptr<Entry> e;
            {std::unique_lock<std::mutex> lock(mutex_);wake_.wait(lock,[&]{return stopping_||!queued_.empty();});if(stopping_)return;
             auto id=queued_.front();queued_.pop_front();e=entries_.at(id);e->state=State::Loading;}
            Bytes data;std::exception_ptr error;
            try{if(startup)std::rethrow_exception(startup);data=load(e->key,e->bytes);if(data.size()!=e->bytes)throw std::invalid_argument("Decoded tile size mismatch");}
            catch(...){error=std::current_exception();}
            {std::lock_guard<std::mutex> lock(mutex_);
             if(e->state==State::Cancelled){Bytes().swap(data);erase(e);continue;}
             if(error){Bytes().swap(data);e->error=error;e->state=State::Failed;++stats_.failures;}
             else{e->data=std::move(data);e->state=State::Ready;++stats_.loads;}}
        }
        // Loader and decoder state are created and destroyed on this worker.
    }
public:
    AsyncTextureLoader(Factory factory,size_t maxBytes=16<<20,size_t maxRecords=64):maxBytes_(maxBytes),maxRecords_(maxRecords){
        if(!factory||!maxBytes||!maxRecords)throw std::invalid_argument("Empty async loader limits/factory");
        worker_=std::thread([this,factory=std::move(factory)]{run(factory);});
    }
    AsyncTextureLoader(const AsyncTextureLoader&)=delete;AsyncTextureLoader& operator=(const AsyncTextureLoader&)=delete;
    ~AsyncTextureLoader(){close();}
    std::optional<Ticket> submit(const Key& key,size_t bytes){ownerCheck();std::lock_guard<std::mutex> lock(mutex_);
        if(closed_||stopping_)throw std::logic_error("Async loader closed");
        if(key.asset.empty()||key.interpretation.empty()||!bytes)throw std::invalid_argument("Incomplete async texture request");
        if(bytes>maxBytes_)throw std::length_error("Decode tile exceeds queue budget");
        auto existing=keys_.find(key);if(existing!=keys_.end()){auto e=entries_.at(existing->second);if(e->bytes!=bytes)throw std::invalid_argument("Immutable queued size changed");++stats_.duplicates;return Ticket{owner_,e->id};}
        if(stats_.heldRecords>=maxRecords_||bytes>maxBytes_-stats_.heldBytes){++stats_.blocked;return {};}
        if(serial_==UINT64_MAX)throw std::overflow_error("Texture ticket overflow");
        auto e=std::make_shared<Entry>(Entry{++serial_,key,bytes});entries_.emplace(e->id,e);
        try{keys_.emplace(key,e->id);queued_.push_back(e->id);}catch(...){unlink(e);entries_.erase(e->id);throw;}
        stats_.heldBytes+=bytes;++stats_.heldRecords;stats_.peakBytes=std::max(stats_.peakBytes,stats_.heldBytes);stats_.peakRecords=std::max(stats_.peakRecords,stats_.heldRecords);wake_.notify_one();return Ticket{owner_,e->id};
    }
    State state(const Ticket& t)const{ownerCheck();std::lock_guard<std::mutex> lock(mutex_);ticketCheck(t);auto i=entries_.find(t.id);return i==entries_.end()?State::Gone:i->second->state;}
    std::optional<Bytes> take(const Ticket& t){ownerCheck();std::lock_guard<std::mutex> lock(mutex_);ticketCheck(t);auto i=entries_.find(t.id);if(i==entries_.end())return {};
        auto e=i->second;if(e->state==State::Failed){auto error=e->error;erase(e);std::rethrow_exception(error);}if(e->state!=State::Ready)return {};
        Bytes data=std::move(e->data);erase(e);return data;
    }
    void cancel(const Ticket& t){ownerCheck();std::lock_guard<std::mutex> lock(mutex_);ticketCheck(t);auto i=entries_.find(t.id);if(i!=entries_.end())cancelEntry(i->second);}
    void cancelAll(){ownerCheck();std::lock_guard<std::mutex> lock(mutex_);std::vector<std::shared_ptr<Entry>> entries;for(auto& e:entries_)entries.push_back(e.second);for(auto& e:entries)cancelEntry(e);}
    Stats stats()const{ownerCheck();std::lock_guard<std::mutex> lock(mutex_);return stats_;}
    void close(){ownerCheck();if(closed_)return;cancelAll();{std::lock_guard<std::mutex> lock(mutex_);stopping_=true;}wake_.notify_one();if(worker_.joinable())worker_.join();closed_=true;}
};
// Poll-only bridge: decoding never runs in the cache loader callback. Ready data
// stays charged to the decode queue until cache admission actually consumes it.
inline std::optional<Cache::Lease> acquireAsync(Cache& cache,AsyncTextureLoader& worker,const Key& key,size_t bytes,bool gpu){
    if(cache.hasBacking(key,bytes,gpu))return cache.acquire(key,bytes,[](const Key&,size_t)->Bytes{throw std::logic_error("Unexpected async cache miss");},gpu);
    auto ticket=worker.submit(key,bytes);if(!ticket)return {};
    auto state=worker.state(*ticket);if(state==AsyncTextureLoader::State::Failed){worker.take(*ticket);throw std::logic_error("Missing loader error");}
    if(state!=AsyncTextureLoader::State::Ready)return {};
    return cache.acquire(key,bytes,[&](const Key&,size_t){auto data=worker.take(*ticket);if(!data)throw std::logic_error("Async ready tile disappeared");return std::move(*data);},gpu);
}
} // namespace xpu2::texture
