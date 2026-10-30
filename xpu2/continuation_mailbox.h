// Experimental CPU-resume ownership boundary. No native RayState/arena pointers.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <thread>
#include <type_traits>

namespace xpu2 {
// State must be an independently owned value snapshot. Copying a native RayState
// does NOT satisfy this contract: it contains arena pointers and external handles.
// QueueType supplies the diagnostic Queue's submit/tryCollect/cancel interface.
template<class State, class QueueType> class ContinuationMailbox {
public:
    enum class Route { QueueResult, AdmissionFallback };
    enum class Claim { Pending, Ready, Rejected };
    enum class Finish { Accepted, Revoked, Invalid };
    struct Token {
        std::shared_ptr<const int> owner;
        uint64_t serial=0;
        unsigned slot=0;
        explicit operator bool() const { return bool(owner); }
    };
    struct Resume {
        State state;
        std::array<float,64> values{};
        uint64_t attempt=0,revision=0;
        int count=0;
        Route route=Route::QueueResult; // May contain preserved CPU values on GPU failure.
    };
    struct Lease {
        Token token;
        std::shared_ptr<const Resume> resume;
    };
private:
    enum class Phase { Empty, Waiting, Claimed, Revoked };
    struct Entry {
        Phase phase=Phase::Empty;
        uint64_t serial=0;
        typename QueueType::Ticket ticket;
        std::shared_ptr<Resume> resume;
    };
    QueueType& queue;
    const std::thread::id coordinator=std::this_thread::get_id();
    const std::shared_ptr<const int> identity=std::make_shared<const int>(0);
    std::array<Entry,64> entries{};
    unsigned limit,used=0;
    uint64_t nextSerial=0,attempt=0,revision=0;
    bool accepting=false;
    void checkThread() const {
        if(std::this_thread::get_id()!=coordinator)
            throw std::logic_error("Continuation coordinator used from a foreign thread");
    }
    Entry* find(const Token& token) {
        if(token.owner!=identity || token.slot>=limit)return nullptr;
        auto& e=entries[token.slot];
        return e.phase!=Phase::Empty && e.serial==token.serial ? &e : nullptr;
    }
    void retire(Entry& e) { e=Entry{};--used; }
    void invalidate() {
        for(auto& e:entries) {
            if(e.phase==Phase::Waiting) {
                if(e.ticket)queue.cancel(e.ticket);
                retire(e);
            } else if(e.phase==Phase::Claimed) {
                // CPU consumers still own this lease. Keep its capacity credit
                // until return, even across arbitrarily many render restarts.
                e.phase=Phase::Revoked;
            }
        }
    }
public:
    explicit ContinuationMailbox(QueueType& q,unsigned capacity=64):queue(q),limit(capacity) {
        if(!limit || limit>entries.size())throw std::invalid_argument("Invalid continuation capacity");
    }
    ContinuationMailbox(const ContinuationMailbox&)=delete;
    ContinuationMailbox& operator=(const ContinuationMailbox&)=delete;
    ~ContinuationMailbox() {
        // Owners must explicitly close and return all CPU leases before deletion.
        if(accepting || used)std::terminate();
    }
    void begin(uint64_t newAttempt,uint64_t newRevision) {
        checkThread();
        if(!newAttempt || newAttempt<=attempt)throw std::invalid_argument("Attempt must increase");
        invalidate();attempt=newAttempt;revision=newRevision;accepting=true;
    }
    Token submit(const State& state,const float* input,const float* native,int count) {
        checkThread();
        if(!accepting || used==limit || count<1 || count>8 || !input || !native)return {};
        if(nextSerial==std::numeric_limits<uint64_t>::max())throw std::overflow_error("Continuation serial exhausted");
        unsigned slot=0;while(entries[slot].phase!=Phase::Empty)++slot;
        auto resume=std::make_shared<Resume>();resume->state=state;resume->attempt=attempt;
        resume->revision=revision;resume->count=count;
        std::copy(native,native+count*8,resume->values.begin());
        auto ticket=queue.submit(input,native,count,revision);
        if(!ticket)resume->route=Route::AdmissionFallback;
        auto& e=entries[slot];e.serial=++nextSerial;e.phase=Phase::Waiting;
        e.ticket=std::move(ticket);e.resume=std::move(resume);++used;
        return {identity,e.serial,slot};
    }
    Claim claim(const Token& token,Lease& destination) {
        checkThread();auto* e=find(token);
        if(!e || e->phase!=Phase::Waiting || !accepting ||
           e->resume->attempt!=attempt || e->resume->revision!=revision)return Claim::Rejected;
        if(e->ticket) {
            const auto result=queue.tryCollect(e->ticket,revision,e->resume->values.data());
            if(result==Collect::Pending)return Claim::Pending;
            if(result!=Collect::Ready) {queue.cancel(e->ticket);retire(*e);return Claim::Rejected;}
            e->ticket.reset();
        }
        e->phase=Phase::Claimed;
        destination={token,e->resume};return Claim::Ready;
    }
    Finish finish(const Lease& lease) {
        checkThread();auto* e=find(lease.token);
        if(!e || (e->phase!=Phase::Claimed && e->phase!=Phase::Revoked) ||
           e->resume!=lease.resume)return Finish::Invalid;
        const bool valid=e->phase==Phase::Claimed && accepting &&
                         e->resume->attempt==attempt && e->resume->revision==revision;
        retire(*e);return valid ? Finish::Accepted : Finish::Revoked;
    }
    bool cancel(const Token& token) {
        checkThread();auto* e=find(token);if(!e || e->phase==Phase::Revoked)return false;
        if(e->phase==Phase::Claimed)e->phase=Phase::Revoked;
        else {if(e->ticket)queue.cancel(e->ticket);retire(*e);}
        return true;
    }
    bool close() {checkThread();accepting=false;invalidate();return used==0;}
    unsigned outstanding() const {checkThread();return used;}
};
} // namespace xpu2
