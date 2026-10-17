// Standalone latency-hiding experiment. CPU work is synthetic, not a native path.
#include "batched_bridge.cc"
#include "continuation_mailbox.h"
#include <immintrin.h>
#include <fstream>
#include <iostream>
#include <iomanip>
static void require(bool ok,const char* text){if(!ok)throw std::runtime_error(text);}
using Clock=std::chrono::steady_clock;
static uint64_t ns(Clock::time_point start){return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();}
struct State { uint64_t id=0; std::array<float,8> seed{}; };
// Hold every request until a complete nine-packet batch can be published. This
// keeps batch count/size identical between the serial and overlapped schedules.
struct ScheduledQueue:Queue {
    std::vector<Ticket> tickets;
    Ticket submit(const float* in,const float* native,int count,uint64_t revision){
        auto t=Queue::submit(in,native,count,revision,true);require(bool(t),"Unexpected GPU admission fallback");
        tickets.push_back(t);return t;
    }
    void publishBatch(){require(tickets.size()==9 && publish(tickets,17),"Publication rejected");}
    bool lastPending(){std::lock_guard<std::mutex> lock(mutex);return !tickets.back()->done;}
    void wait(const Ticket& t){std::unique_lock<std::mutex> lock(mutex);require(t->completed.wait_for(lock,std::chrono::seconds(10),[&]{return t->done;}),"GPU timeout");}
};
using Box=xpu2::ContinuationMailbox<State,ScheduledQueue>;
struct Packet {std::array<float,192> input;std::array<float,64> native;};
static uint64_t mix(uint64_t h,const void* data,size_t bytes){
    const auto* p=static_cast<const unsigned char*>(data);
    for(size_t i=0;i<bytes;++i){h^=p[i];h*=1099511628211ull;}return h;
}
// A bounded numerical CPU workload with eight independent AVX lanes. Its result
// is consumed and compared, so the compiler cannot eliminate it. This measures
// scheduling only: it is NOT MoonRay shading or an estimate of its CPU cost.
__attribute__((noinline)) static std::array<float,8> independent(const State& s,unsigned steps){
    __m256 v=_mm256_loadu_ps(s.seed.data());
    const __m256 a=_mm256_set1_ps(.99991f),b=_mm256_set1_ps(.000031f);
    for(unsigned i=0;i<steps;++i)v=_mm256_add_ps(_mm256_mul_ps(v,a),b);
    std::array<float,8> out;_mm256_storeu_ps(out.data(),v);return out;
}
struct Result {uint64_t wall=0,cpu=0,wait=0,hash=1469598103934665603ull;unsigned pendingBefore=0,pendingAfter=0;};
static Result run(ScheduledQueue& q,Box& box,const std::array<Packet,9>& packets,bool overlap,unsigned steps,unsigned rounds,bool sentinel){
    Result result;auto start=Clock::now();
    for(unsigned round=0;round<rounds;++round){
        q.tickets.clear();std::array<Box::Token,9> tokens;std::array<State,9> states;
        std::array<Box::Lease,9> leases;std::array<std::array<float,8>,9> cpu;
        for(unsigned n=0;n<9;++n){
            states[n].id=uint64_t(round)*9+n;
            for(unsigned lane=0;lane<8;++lane)states[n].seed[lane]=.125f+float((states[n].id+lane)%97)*.003f;
            tokens[n]=box.submit(states[n],packets[n].input.data(),packets[n].native.data(),8);
            require(bool(tokens[n]),"Mailbox full");
        }
        q.publishBatch();
        auto collect=[&]{
            auto begin=Clock::now();
            for(int n=8;n>=0;--n){q.wait(q.tickets[n]);require(box.claim(tokens[n],leases[n])==Box::Claim::Ready,"Claim failed");}
            result.wait+=ns(begin);
        };
        auto compute=[&]{
            result.pendingBefore+=q.lastPending();auto begin=Clock::now();
            for(unsigned n=0;n<9;++n)cpu[n]=independent(states[n],steps);
            result.cpu+=ns(begin);result.pendingAfter+=q.lastPending();
        };
        if(overlap){compute();collect();}else{collect();compute();}
        for(unsigned n=0;n<9;++n){
            const auto& r=*leases[n].resume;auto expected=packets[n].native;
            if(sentinel)for(unsigned lane=0;lane<8;++lane)for(unsigned c=3;c<6;++c)expected[lane*8+c]*=.5f;
            require(r.state.id==states[n].id && r.state.seed==states[n].seed && r.attempt==1 && r.revision==17,"Owned identity changed");
            require(!std::memcmp(r.values.data(),expected.data(),sizeof(expected)),"Numeric parity failed");
            result.hash=mix(result.hash,&r.state.id,sizeof(r.state.id));
            result.hash=mix(result.hash,r.values.data(),sizeof(r.values));
            result.hash=mix(result.hash,cpu[n].data(),sizeof(cpu[n]));
            require(box.finish(leases[n])==Box::Finish::Accepted,"Lease finish failed");
            require(box.finish(leases[n])==Box::Finish::Invalid,"Duplicate lease finish accepted");
        }
        require(box.outstanding()==0,"Leaked CPU lease");
    }
    result.wall=ns(start);return result;
}
int main(int argc,char** argv){
    try{
        require(argc==3,"capture and mode required");const bool sentinel=std::string(argv[2])=="sentinel";
        std::ifstream f(argv[1],std::ios::binary);std::vector<char> raw((std::istreambuf_iterator<char>(f)),{});
        require(raw.size()>4 && (raw.size()-4)%240==0 && !std::memcmp(raw.data(),"XCL1",4),"Invalid capture");
        std::array<Packet,9> packets;
        for(unsigned n=0;n<9;++n)for(unsigned lane=0;lane<8;++lane){
            const char* row=raw.data()+4+((n*8+lane)%((raw.size()-4)/240))*240;
            std::memcpy(packets[n].input.data()+lane*24,row+112,96);
            std::memcpy(packets[n].native.data()+lane*8,row+208,32);
        }
        if(sentinel){bool differs=false;
            for(const auto& p:packets)for(unsigned lane=0;lane<8;++lane)for(unsigned c=3;c<6;++c)
                differs=differs || p.native[lane*8+c]*.5f!=p.native[lane*8+c];
            require(differs,"Sentinel fixture contains no nonzero RGB");
        }
        ScheduledQueue q;Box box(q);box.begin(1,17);
        run(q,box,packets,false,128,32,sentinel); // Initialization and warmup excluded.
        std::cout<<"{\"runs\":[";bool comma=false;
        const unsigned rounds=sentinel?32:512,repeats=sentinel?1:5;
        for(unsigned steps:{0u,128u,1024u,8192u}){
            uint64_t expectedHash=0;
            for(unsigned repeat=0;repeat<repeats;++repeat)for(unsigned order=0;order<2;++order){
                const bool overlap=(order+repeat)%2==1;unsigned long long before;
                {std::lock_guard<std::mutex> lock(q.mutex);before=q.merged;}
                auto r=run(q,box,packets,overlap,steps,rounds,sentinel);
                {std::lock_guard<std::mutex> lock(q.mutex);require(q.merged-before==rounds,"Batch size/count changed");}
                if(!expectedHash)expectedHash=r.hash;require(r.hash==expectedHash,"Schedule-dependent result");
                if(!overlap)require(!r.pendingBefore && !r.pendingAfter,"Serial stage overlapped");
                if(comma)std::cout<<',';comma=true;
                std::cout<<"{\"schedule\":\""<<(overlap?"overlap":"serial")<<"\",\"steps\":"<<steps<<",\"repeat\":"<<repeat
                    <<",\"rounds\":"<<rounds<<",\"wall_ns\":"<<r.wall<<",\"cpu_ns\":"<<r.cpu<<",\"collect_ns\":"<<r.wait
                    <<",\"cpu_started_pending\":"<<r.pendingBefore<<",\"cpu_finished_pending\":"<<r.pendingAfter<<",\"digest\":\""<<r.hash<<"\"}";
            }
        }
        require(box.close() && q.stop(std::chrono::milliseconds(5000)),"Shutdown failed");
        require(q.cleanupOk && q.device.asyncReleased() && !q.device.cleanupErrors && !q.worker.joinable(),"Resource leak");
        require(q.retainedAsync==0 && q.submitted==q.delivered && !q.full && !q.failed,"Queue accounting failed");
        require(q.device.samples==q.submitted*8 && q.device.accepted==q.device.samples && q.device.replaced==q.device.samples
            && !q.device.errors && !q.device.invalid && !q.device.mismatch && !q.device.unsupported,"GPU did not execute all samples");
        std::cout<<"],\"passed\":true,\"cleanup\":true,\"gpu_samples\":"<<q.device.samples<<",\"gpu_batches\":"<<q.merged<<"}\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
