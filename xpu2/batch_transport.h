// Backend-independent batch ownership; native integration is opt-in and experimental.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <exception>
#include <limits>
#include <stdexcept>

namespace xpu2::transport {
struct Layout {
    static constexpr unsigned maxSamples=512, maxPackets=64, packetSamples=8;
    static constexpr unsigned inputFloats=24, outputFloats=8, resultWords=9;
    static constexpr unsigned inputBytes=inputFloats*sizeof(float);
    static constexpr unsigned outputBytes=outputFloats*sizeof(float);
    // Input, lengths, returned-input validation and result/status buffers.
    static constexpr unsigned wireBytes=inputBytes+sizeof(uint32_t)+inputBytes+resultWords*sizeof(uint32_t);
};
static_assert(sizeof(float)==4 && sizeof(uint32_t)==4 && Layout::wireBytes==232);
// Allocate an identity once per slot lifetime, never per sample or batch.
// Tokens are local to the binary owning this library, not a cross-process ABI.
inline std::atomic<uint64_t> nextOwner{1};
inline uint64_t allocateOwner(){
    uint64_t id=nextOwner.load(std::memory_order_relaxed);
    for(;;){
        if(id==std::numeric_limits<uint64_t>::max())throw std::overflow_error("Batch owner identity");
        if(nextOwner.compare_exchange_weak(id,id+1,std::memory_order_relaxed))return id;
    }
}
struct PacketView {const float* input;const float* fallback;unsigned samples;};
struct PacketRange {unsigned first=0,samples=0;};
enum class Phase {Empty,Packed,InFlight,CancelPending,Ready,Failed};
enum class Completion {Rejected,Publish,Retired,Failed};

// One dispatch worker owns this slot. Cross-thread requests must pass through
// the existing queue lock/mailbox; this class deliberately adds no locking.
// Buffers are reused, never freed/reallocated while a device may access them.
class Batch {
public:
    struct Token {uint64_t owner=0,serial=0,revision=0;};
private:
    const uint64_t owner_=allocateOwner();
    Phase phase_=Phase::Empty;
    uint64_t serial_=0,revision_=0;
    unsigned samples_=0,packets_=0;
    std::array<float,Layout::maxSamples*Layout::inputFloats> input_;
    std::array<float,Layout::maxSamples*Layout::outputFloats> fallback_;
    std::array<PacketRange,Layout::maxPackets> ranges_{};
    bool owns(Token t)const{return t.owner==owner_ && t.serial==serial_ && t.revision==revision_ && phase_!=Phase::Empty;}
public:
    Batch()=default;
    Batch(const Batch&)=delete;Batch& operator=(const Batch&)=delete;
    Batch(Batch&&)=delete;Batch& operator=(Batch&&)=delete;
    // Destruction must follow completion, including cancelled/failed uploads.
    ~Batch(){if(phase_==Phase::InFlight || phase_==Phase::CancelPending)std::terminate();}
    Phase phase()const{return phase_;}
    unsigned samples()const{return samples_;}
    unsigned packets()const{return packets_;}
    const float* input()const{return input_.data();}
    const float* fallback()const{return fallback_.data();}
    // The dispatch owner may fill result storage only after its backend event
    // confirms completion. Failure leaves the original packed fallback intact.
    float* resultStorage(Token t){
        if(!owns(t)||phase_!=Phase::InFlight)throw std::logic_error("Batch result ownership");
        return fallback_.data();
    }
    PacketRange range(unsigned i)const{if(i>=packets_)throw std::out_of_range("Batch packet");return ranges_[i];}
    Token pack(const PacketView* views,unsigned count,uint64_t revision){
        if(phase_!=Phase::Empty || !views || !count || count>Layout::maxPackets || !revision)throw std::invalid_argument("Batch admission");
        if(serial_==std::numeric_limits<uint64_t>::max())throw std::overflow_error("Batch generation");
        unsigned total=0;
        // Validate the complete group before modifying storage or ownership.
        for(unsigned i=0;i<count;++i){
            const auto& v=views[i];
            if(!v.input || !v.fallback || !v.samples || v.samples>Layout::packetSamples)throw std::invalid_argument("Batch packet");
            total+=v.samples;
        }
        if(total>Layout::maxSamples)throw std::invalid_argument("Batch capacity");
        unsigned offset=0;
        for(unsigned i=0;i<count;++i){
            const auto& v=views[i];ranges_[i]={offset,v.samples};
            std::memcpy(input_.data()+offset*Layout::inputFloats,v.input,v.samples*Layout::inputBytes);
            std::memcpy(fallback_.data()+offset*Layout::outputFloats,v.fallback,v.samples*Layout::outputBytes);
            offset+=v.samples;
        }
        samples_=total;packets_=count;revision_=revision;++serial_;phase_=Phase::Packed;
        return {owner_,serial_,revision_};
    }
    bool submit(Token t){if(!owns(t)||phase_!=Phase::Packed)return false;phase_=Phase::InFlight;return true;}
    // Cancel only revokes publication. In-flight storage remains owned until
    // the backend event (or a failed-upload stream drain) confirms completion.
    bool cancel(Token t){
        if(!owns(t))return false;
        if(phase_==Phase::InFlight || phase_==Phase::CancelPending)phase_=Phase::CancelPending;
        else phase_=Phase::Empty;
        return true;
    }
    Completion complete(Token t,bool success){
        if(!owns(t))return Completion::Rejected;
        if(phase_==Phase::CancelPending){phase_=Phase::Empty;return Completion::Retired;}
        if(phase_!=Phase::InFlight)return Completion::Rejected;
        phase_=success?Phase::Ready:Phase::Failed;
        return success?Completion::Publish:Completion::Failed;
    }
    bool release(Token t){
        if(!owns(t)||(phase_!=Phase::Ready && phase_!=Phase::Failed))return false;
        phase_=Phase::Empty;return true;
    }
};
}
