// Experimental owned Lambert-stage dispatcher. No native RayState/TLS pointers.
#pragma once
#include "texture_work.h"
#include "continuation_mailbox.h"
#include <cstring>

namespace xpu2 {
struct ShadingJob {
    std::array<float,192> input{};       // Up to eight native AVX8 Lambert inputs.
    std::array<float,64> native{};       // Matching CPU oracle/fallback, not recomputed here.
    std::array<uint64_t,8> paths{};
    std::array<uint32_t,224> context{};  // Owned same-call numerical sampler metadata.
    int count=0;
};

// Coordinator-only. Dependencies and RAM tiles are consumed before GPU dispatch;
// only numerical values cross into the GPU queue's independent CUDA context.
// Prepare must only read resident tiles and fill owned numerical inputs/oracles.
// It must not block for I/O, call native scene APIs, or retain a tile reference.
// This is a stage dispatcher, NOT restoration of a native integrator stack.
template<class QueueType> class ShadingDispatch {
public:
    enum class Route { QueueResult, AdmissionFallback, Failed };
    enum class Finish { Accepted, Revoked, Failed, Invalid };
    struct Token {
        std::shared_ptr<const int> owner;
        uint64_t serial=0;unsigned slot=0;
        explicit operator bool()const{return bool(owner);}
    };
    struct Result {
        ShadingJob job;
        std::array<float,64> values{};
        uint64_t id=0,attempt=0,revision=0;
        Route route=Route::QueueResult;
        std::string failure;
    };
    struct Lease {Token token;std::shared_ptr<const Result> result;};
    using Prepare=std::function<void(ShadingJob&,const texture::TextureWorkQueue::Ready&,texture::Cache&)>;
    struct Stats {uint64_t admitted=0,dispatched=0,accepted=0,revoked=0,failed=0,cancelled=0;unsigned peak=0;};
private:
    using Mailbox=ContinuationMailbox<ShadingJob,QueueType>;
    enum class Phase {Empty,Textures,Gpu,Ready,Claimed,Revoked};
    struct Entry {Phase phase=Phase::Empty;uint64_t serial=0;std::shared_ptr<Result> result;typename Mailbox::Token gpu;};
    texture::Cache& cache_;
    texture::TextureWorkQueue textures_;
    Mailbox mailbox_;
    Prepare prepare_;
    const std::thread::id coordinator_=std::this_thread::get_id();
    const std::shared_ptr<const int> owner_=std::make_shared<const int>(0);
    std::array<Entry,64> entries_{};
    unsigned limit_,used_=0;
    uint64_t serial_=0,attempt_=0,revision_=0;
    bool accepting_=false;
    Stats stats_;
    void check()const{if(std::this_thread::get_id()!=coordinator_)throw std::logic_error("Shading dispatcher coordinator violation");}
    Entry* find(const Token& t){if(t.owner!=owner_||t.slot>=limit_)return nullptr;auto& e=entries_[t.slot];return e.phase!=Phase::Empty&&e.serial==t.serial?&e:nullptr;}
    // Bit inspection also works under the native renderer's -ffast-math build.
    static bool finite(float value){uint32_t bits;std::memcpy(&bits,&value,4);return (bits&0x7f800000u)!=0x7f800000u;}
    static bool valuesValid(const std::array<float,64>& values,int count){for(int i=0;i<count*8;++i)if(!finite(values[i]))return false;return true;}
    static bool numeric(const ShadingJob& job){
        if(job.count<1||job.count>8||!valuesValid(job.native,job.count))return false;
        for(int lane=0;lane<job.count;++lane)for(int field=2;field<20;++field)if(!finite(job.input[lane*24+field]))return false;
        return true;
    }
    void retire(Entry& e){e=Entry{};--used_;}
    void invalidate(){for(auto& e:entries_){if(e.phase==Phase::Claimed)e.phase=Phase::Revoked;else if(e.phase!=Phase::Empty&&e.phase!=Phase::Revoked){retire(e);++stats_.cancelled;}}}
public:
    ShadingDispatch(texture::Cache& cache,texture::AsyncTextureLoader& loader,QueueType& queue,Prepare prepare,unsigned capacity=64)
      :cache_(cache),textures_(cache,loader,capacity),mailbox_(queue,capacity),prepare_(std::move(prepare)),limit_(capacity){
        if(!prepare_)throw std::invalid_argument("Missing bounded shading preparation");
    }
    ShadingDispatch(const ShadingDispatch&)=delete;ShadingDispatch& operator=(const ShadingDispatch&)=delete;
    ~ShadingDispatch(){if(!close())std::terminate();}
    void begin(uint64_t attempt,uint64_t revision,texture::DependencyView dependencies){
        check();if(!dependencies||!attempt||attempt<=attempt_)throw std::invalid_argument("Shading attempt must increase");
        textures_.begin(attempt,std::move(dependencies));mailbox_.begin(attempt,revision);invalidate();
        attempt_=attempt;revision_=revision;accepting_=true;
    }
    Token submit(uint64_t id,const std::string& material,const ShadingJob& job,std::vector<texture::TextureWorkQueue::Need> needs={}){
        check();if(!accepting_||used_==limit_||!numeric(job))return {};
        if(serial_==UINT64_MAX)throw std::overflow_error("Shading job serial exhausted");
        unsigned slot=0;while(entries_[slot].phase!=Phase::Empty)++slot;
        auto result=std::make_shared<Result>();result->job=job;result->values=job.native;result->id=id;result->attempt=attempt_;result->revision=revision_;
        // CPU-resident leases: no synchronous GPU upload in a coordinator poll.
        if(!textures_.submit(id,material,{},std::move(needs),false))return {};
        entries_[slot]={Phase::Textures,++serial_,std::move(result),{}};++used_;++stats_.admitted;stats_.peak=std::max(stats_.peak,used_);
        return {owner_,serial_,slot};
    }
    // Bounded polling: never waits for decoding or GPU completion. Can allocate
    // and acquire mutexes; neither lock-free nor a hard real-time guarantee.
    unsigned pump(unsigned budget=8){
        check();if(!accepting_||!budget)return 0;budget=std::min(budget,limit_);unsigned progress=0;
        for(unsigned n=0;n<budget;++n){
            auto ready=textures_.claim();if(!ready)break;
            Entry* entry=nullptr;
            for(auto& e:entries_)if(e.phase==Phase::Textures&&e.result->attempt==ready->attempt&&e.result->id==ready->id){entry=&e;break;}
            if(!entry){textures_.finish(ready);throw std::logic_error("Lost owned shading job");}
            auto& r=*entry->result;
            try{
                if(!ready->failure.empty())throw std::runtime_error(ready->failure);
                auto prepared=r.job;prepare_(prepared,*ready,cache_);
                // Preparation cannot silently change sample ownership or count.
                if(prepared.count!=r.job.count||prepared.paths!=r.job.paths||prepared.context!=r.job.context)throw std::logic_error("Preparation changed sample identity");
                if(!numeric(prepared))throw std::invalid_argument("Nonfinite prepared shading values");
                r.job=std::move(prepared);r.values=r.job.native;
                entry->gpu=mailbox_.submit(r.job,r.job.input.data(),r.job.native.data(),r.job.count);
                if(!entry->gpu)throw std::runtime_error("Shading continuation admission failed");
                entry->phase=Phase::Gpu;++stats_.dispatched;
            }catch(const std::exception& e){r.route=Route::Failed;r.failure=e.what();entry->phase=Phase::Ready;}
            catch(...){r.route=Route::Failed;r.failure="Unknown shading preparation failure";entry->phase=Phase::Ready;}
            // Numeric inputs were copied. GPU never borrows RAM tile addresses.
            auto ended=textures_.finish(ready);
            if(ended!=texture::TextureWorkQueue::Finish::Accepted&&r.route!=Route::Failed){
                if(entry->gpu)mailbox_.cancel(entry->gpu);r.route=Route::Failed;r.failure="Texture work revoked during dispatch";entry->phase=Phase::Ready;
            }
            ++progress;
        }
        for(auto& e:entries_)if(e.phase==Phase::Gpu){
            typename Mailbox::Lease lease;auto state=mailbox_.claim(e.gpu,lease);
            if(state==Mailbox::Claim::Pending)continue;
            if(state==Mailbox::Claim::Ready){
                e.result->values=lease.resume->values;
                e.result->route=lease.resume->route==Mailbox::Route::AdmissionFallback?Route::AdmissionFallback:Route::QueueResult;
                if(mailbox_.finish(lease)!=Mailbox::Finish::Accepted)throw std::logic_error("Current shading resume revoked");
                if(!valuesValid(e.result->values,e.result->job.count)){e.result->route=Route::Failed;e.result->failure="Nonfinite completed shading values";}
            }else{e.result->route=Route::Failed;e.result->failure="GPU continuation rejected";}
            e.phase=Phase::Ready;++progress;
        }
        return progress;
    }
    bool claim(const Token& token,Lease& destination){check();auto* e=find(token);if(!e||e->phase!=Phase::Ready||!accepting_)return false;e->phase=Phase::Claimed;destination={token,e->result};return true;}
    // Publication must be conditional on Accepted, on this same coordinator,
    // before any subsequent begin/close. Failed jobs do not supply film values.
    Finish finish(const Lease& lease){
        check();auto* e=find(lease.token);if(!e||(e->phase!=Phase::Claimed&&e->phase!=Phase::Revoked)||e->result!=lease.result)return Finish::Invalid;
        const auto state=e->phase==Phase::Revoked||!accepting_||lease.result->attempt!=attempt_||lease.result->revision!=revision_?Finish::Revoked:
            lease.result->route==Route::Failed?Finish::Failed:Finish::Accepted;
        retire(*e);if(state==Finish::Accepted)++stats_.accepted;else if(state==Finish::Revoked)++stats_.revoked;else ++stats_.failed;return state;
    }
    bool close(){check();accepting_=false;const bool texturesClosed=textures_.close();const bool mailboxClosed=mailbox_.close();invalidate();return texturesClosed&&mailboxClosed&&used_==0;}
    unsigned outstanding()const{check();return used_;}
    const Stats& stats()const{check();return stats_;}
};
} // namespace xpu2
