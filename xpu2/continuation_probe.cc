// Real GPU queue + owned resume metadata; NOT a MoonRay RayState continuation.
#include "native_lambert_queue.cc"
#include "continuation_mailbox.h"
#include <fstream>
#include <iostream>

static std::vector<std::array<uint32_t,88>> nativeSurfaces;
struct OwnedState {
    std::array<uint64_t,8> paths{};
    std::array<uint32_t,8> pixels{};
    std::array<uint8_t,64> ownedBytes{};
    std::array<uint32_t,88> nativeSurface{}; // Optional real capture, bit-preserved; not paired to this shader packet.
    bool operator==(const OwnedState& b) const {
        return paths==b.paths && pixels==b.pixels && ownedBytes==b.ownedBytes && nativeSurface==b.nativeSurface;
    }
};
using Mailbox=xpu2::ContinuationMailbox<OwnedState,Queue>;
struct Packet {
    std::array<float,192> input{};
    std::array<float,64> native{},expected{};
    OwnedState state;
};
static void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static Packet packet(const std::vector<unsigned char>& data,size_t n,bool missing=false) {
    Packet p;
    if(!nativeSurfaces.empty())p.state.nativeSurface=nativeSurfaces[n%nativeSurfaces.size()];
    for(size_t lane=0;lane<8;++lane) {
        const auto* src=data.data()+4+(n*8+lane)*164;
        std::memcpy(p.input.data()+lane*24,src,96);
        std::memcpy(p.native.data()+lane*8,src+96,28);
        uint32_t valid;std::memcpy(&valid,src+124,4);p.native[lane*8+7]=float(valid);
        p.state.paths[lane]=n*8+lane;p.state.pixels[lane]=uint32_t(100+n+lane);
    }
    for(size_t k=0;k<64;++k)p.state.ownedBytes[k]=uint8_t(n+k);
    p.expected=p.native;
    if(!missing)for(int lane=0;lane<8;++lane)for(int c=3;c<6;++c)p.expected[lane*8+c]*=0.5f;
    return p;
}
template<class F> static void waitFor(F predicate) {
    const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);
    while(!predicate()) {require(std::chrono::steady_clock::now()<end,"Timed out waiting for queue stage");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
}
static Mailbox::Lease take(Mailbox& box,const Mailbox::Token& token) {
    Mailbox::Lease lease;
    waitFor([&]{auto r=box.claim(token,lease);require(r!=Mailbox::Claim::Rejected,"Expected claim was rejected");return r==Mailbox::Claim::Ready;});
    return lease;
}
static void check(const Mailbox::Lease& lease,const Packet& p,uint64_t attempt,uint64_t revision) {
    require(lease.resume && lease.resume->state==p.state && lease.resume->values==p.expected &&
            lease.resume->count==8 && lease.resume->attempt==attempt && lease.resume->revision==revision,"Resume state/result identity mismatch");
}
int main(int argc,char** argv) {
    try {
        require(argc==3 || argc==4,"scenario, shader capture and optional surface capture required");std::string mode=argv[1];
        if(argc==4) {
            std::ifstream input(argv[3],std::ios::binary);
            std::vector<unsigned char> raw((std::istreambuf_iterator<char>(input)),{});
            require(raw.size()>=356 && raw.size()<=4+1024*352 && (raw.size()-4)%352==0 && !std::memcmp(raw.data(),"XNS1",4),"Invalid native surface fixture");
            nativeSurfaces.resize((raw.size()-4)/352);
            for(size_t n=0;n<nativeSurfaces.size();++n)std::memcpy(nativeSurfaces[n].data(),raw.data()+4+n*352,352);
        }
        bool missing=mode=="missing_ptx";
        std::ifstream f(argv[2],std::ios::binary);std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)),{});
        require(data.size()>=4+66*8*164 && !std::memcmp(data.data(),"XNI1",4),"Invalid capture");
        Queue q;Mailbox box(q,mode=="leased_restart" ? 1u : 64u);box.begin(1,17);
        unsigned accepted=0,revoked=0;
        if(mode=="pressure" || missing) {
            std::unique_lock<std::mutex> held(q.device.mutex);
            std::array<Packet,64> packets;std::array<Mailbox::Token,64> tokens;
            std::array<Mailbox::Lease,64> leases;
            for(size_t n=0;n<64;++n) {
                packets[n]=packet(data,n,missing);auto input=packets[n];
                tokens[n]=box.submit(input.state,input.input.data(),input.native.data(),8);
                require(bool(tokens[n]),"Admission unexpectedly refused");
                input.input.fill(-42);input.native.fill(-43);input.state=OwnedState{};
            }
            Mailbox::Lease unchanged;
            require(box.claim(tokens[0],unchanged)==Mailbox::Claim::Pending && !unchanged.resume,"Pending claim modified destination");
            Mailbox foreign(q);foreign.begin(1,17);
            require(foreign.claim(tokens[0],unchanged)==Mailbox::Claim::Rejected && !unchanged.resume,"Foreign continuation accepted");
            require(foreign.close(),"Foreign mailbox did not close");
            bool wrongThread=false;
            std::thread wrong([&]{try{box.claim(tokens[0],unchanged);}catch(const std::logic_error&){wrongThread=true;}});wrong.join();
            require(wrongThread,"Foreign coordinator thread accepted");
            held.unlock();
            for(int n=63;n>=0;--n) {leases[n]=take(box,tokens[n]);check(leases[n],packets[n],1,17);}
            {std::lock_guard<std::mutex> lock(q.mutex);require(q.retainedAsync==0,"Collected shader credits retained");}
            require(box.outstanding()==64,"CPU leases lost their budget");
            auto extra=packet(data,64,missing);
            require(!box.submit(extra.state,extra.input.data(),extra.native.data(),8),"Slow CPU consumer bypassed bound");
            // CPU consumers can read independent immutable snapshots on other threads.
            std::array<bool,64> consumed{};std::vector<std::thread> consumers;
            for(unsigned t=0;t<4;++t)consumers.emplace_back([&,t]{for(unsigned n=t;n<64;n+=4)consumed[n]=leases[n].resume->state==packets[n].state && leases[n].resume->values==packets[n].expected;});
            for(auto& t:consumers)t.join();
            for(int n=63;n>=0;--n) {
                require(consumed[n],"CPU consumer observed corrupted owned state");
                Mailbox::Lease destination=leases[n];
                require(box.claim(tokens[n],destination)==Mailbox::Claim::Rejected && destination.resume==leases[n].resume,"Duplicate claim changed destination");
                require(box.finish(leases[n])==Mailbox::Finish::Accepted,"Valid CPU lease rejected");++accepted;
                require(box.finish(leases[n])==Mailbox::Finish::Invalid,"CPU lease accepted twice");
            }
            require(q.stop(std::chrono::milliseconds(5000)),"Queue stop failed");
            auto token=box.submit(extra.state,extra.input.data(),extra.native.data(),8);
            auto fallback=take(box,token);extra.expected=extra.native;check(fallback,extra,1,17);
            require(fallback.resume->route==Mailbox::Route::AdmissionFallback,"Closed GPU queue not routed to CPU");
            require(box.finish(fallback)==Mailbox::Finish::Accepted,"Closed-queue CPU fallback failed");++accepted;
        } else if(mode=="restart") {
            std::unique_lock<std::mutex> held(q.device.mutex);
            auto p=packet(data,0);std::array<Mailbox::Token,4> old;
            old[0]=box.submit(p.state,p.input.data(),p.native.data(),8);
            waitFor([&]{std::lock_guard<std::mutex> lock(q.mutex);return q.pending.empty();});
            for(int n=1;n<4;++n)old[n]=box.submit(p.state,p.input.data(),p.native.data(),8);
            box.begin(2,17); // Same scene revision, different render attempt.
            Mailbox::Lease noWrite;
            for(auto& token:old)require(box.claim(token,noWrite)==Mailbox::Claim::Rejected && !noWrite.resume,"Old attempt resumed");
            auto fresh=box.submit(p.state,p.input.data(),p.native.data(),8);
            require(bool(fresh) && fresh.serial!=old[0].serial,"Recycled slot aliased old token");held.unlock();
            auto lease=take(box,fresh);check(lease,p,2,17);
            require(box.finish(lease)==Mailbox::Finish::Accepted,"New attempt failed");++accepted;
            for(auto& token:old)require(!box.cancel(token),"Stale token cancelled recycled slot");
        } else if(mode=="leased_restart") {
            auto p=packet(data,0);auto token=box.submit(p.state,p.input.data(),p.native.data(),8);
            auto lease=take(box,token);check(lease,p,1,17);
            box.begin(2,18);box.begin(3,19);
            require(box.outstanding()==1,"Restart abandoned a live CPU lease");
            require(!box.submit(p.state,p.input.data(),p.native.data(),8),"Restarts bypassed revoked CPU lease budget");
            require(!box.close(),"Close ignored outstanding revoked CPU lease");
            require(box.finish(lease)==Mailbox::Finish::Revoked,"Old CPU work allowed publication");++revoked;
            require(box.finish(lease)==Mailbox::Finish::Invalid,"Revoked CPU lease counted twice");
            box.begin(4,19);auto fresh=box.submit(p.state,p.input.data(),p.native.data(),8);
            auto latest=take(box,fresh);check(latest,p,4,19);
            require(box.finish(latest)==Mailbox::Finish::Accepted,"New CPU lease failed");++accepted;
        } else if(mode=="ready_restart") {
            auto p=packet(data,0);auto token=box.submit(p.state,p.input.data(),p.native.data(),8);
            waitFor([&]{std::lock_guard<std::mutex> lock(q.mutex);return q.merged==1;});
            box.begin(2,18);Mailbox::Lease unchanged;
            require(box.claim(token,unchanged)==Mailbox::Claim::Rejected && !unchanged.resume,"Ready old result resumed");
            {std::lock_guard<std::mutex> lock(q.mutex);require(q.retainedAsync==0 && q.explicitCancelled==1 && q.late==1,"Ready result not cancelled/released");}
            auto fresh=box.submit(p.state,p.input.data(),p.native.data(),8);auto lease=take(box,fresh);check(lease,p,2,18);
            require(box.finish(lease)==Mailbox::Finish::Accepted,"Ready restart recovery failed");++accepted;
        } else if(mode=="admission_fallback") {
            auto p=packet(data,0,true);Mailbox::Lease empty;
            require(!box.submit(p.state,p.input.data(),p.native.data(),0),"Invalid count admitted");
            require(!box.submit(p.state,nullptr,p.native.data(),8),"Null input admitted");
            auto token=box.submit(p.state,p.input.data(),p.native.data(),8);auto lease=take(box,token);check(lease,p,1,17);
            require(lease.resume->route==Mailbox::Route::AdmissionFallback,"Zero GPU capacity did not fall back");
            auto forged=lease;forged.resume=std::make_shared<Mailbox::Resume>(*lease.resume);
            require(box.finish(forged)==Mailbox::Finish::Invalid,"Different lease payload accepted");
            require(box.cancel(token) && !box.cancel(token),"Claimed cancellation not idempotent");
            require(box.finish(lease)==Mailbox::Finish::Revoked,"Cancelled CPU lease allowed publication");++revoked;
            auto fresh=box.submit(p.state,p.input.data(),p.native.data(),8);auto next=take(box,fresh);
            bool badAttempt=false;try{box.begin(1,999);}catch(const std::invalid_argument&){badAttempt=true;}
            require(badAttempt && box.finish(next)==Mailbox::Finish::Accepted,"Invalid restart corrupted current attempt");++accepted;
        } else throw std::runtime_error("Unknown scenario");
        require(box.close() && box.outstanding()==0,"Continuation owner not drained");
        require(!box.submit(OwnedState{},nullptr,nullptr,8),"Closed mailbox admitted work");
        require(q.stop(std::chrono::milliseconds(5000)),"Worker cleanup failed");
        require(q.cleanupOk && !q.worker.joinable() && !q.device.cleanupErrors,"GPU resources not released");
        {std::lock_guard<std::mutex> lock(q.mutex);require(q.retainedAsync==0,"Leaked GPU ticket credit");q.snapshot();}
        std::cout<<"{\"case\":\""<<mode<<"\",\"accepted_cpu_resumes\":"<<accepted<<",\"revoked_cpu_resumes\":"<<revoked<<",\"outstanding\":0,\"passed\":true}\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
