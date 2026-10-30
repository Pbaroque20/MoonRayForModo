// Real native AVX8 / CUDA Lambert stage ownership experiment, not a path renderer.
#include "batched_bridge.cc"
#include <array>
#include <fstream>
#include <iostream>
#include <functional>
extern "C" void xpu2_lambert_sample(float*,int,int,float*);
using Time=std::chrono::steady_clock;
static uint64_t elapsed(Time::time_point t){return std::chrono::duration_cast<std::chrono::nanoseconds>(Time::now()-t).count();}
static void check(bool b,const char* s){if(!b)throw std::runtime_error(s);}
struct Packet {std::array<float,192> input{};std::array<float,64> native{};};
struct Job {unsigned pattern,epoch;int owner=-1;unsigned state=0;std::vector<float> result;};
struct Stats {uint64_t busy=0;unsigned jobs=0;};
// Workers live across all measured runs. Queue ownership changes only after
// completion, never by moving an in-flight ticket or terminating a thread.
struct Pool {
    std::mutex mutex;std::condition_variable wake,complete;
    unsigned generation=0,finished=0;bool stopping=false;
    std::function<void(unsigned)> work;std::vector<std::thread> threads;
    explicit Pool(unsigned n){for(unsigned id=0;id<n;++id)threads.emplace_back([this,id]{
        unsigned seen=0;std::unique_lock<std::mutex> lock(mutex);
        for(;;){wake.wait(lock,[&]{return stopping || generation!=seen;});if(stopping)return;
            seen=generation;auto fn=work;lock.unlock();fn(id);lock.lock();++finished;complete.notify_one();}
    });}
    void run(std::function<void(unsigned)> fn){std::unique_lock<std::mutex> lock(mutex);work=fn;finished=0;++generation;wake.notify_all();complete.wait(lock,[&]{return finished==threads.size();});}
    ~Pool(){{std::lock_guard<std::mutex> lock(mutex);stopping=true;wake.notify_all();}for(auto& t:threads)t.join();}
};
static void cpu(const std::vector<Packet>& packets,unsigned base,unsigned count,float* output){
    for(unsigned p=0;p<count;++p){auto input=packets[(base+p)%packets.size()].input;
        unsigned reflection;std::memcpy(&reflection,&input[20],4);
        for(unsigned lane=0;lane<8;++lane)for(unsigned k=20;k<24;++k){unsigned u;std::memcpy(&u,&input[lane*24+k],4);input[lane*24+k]=float(u);}
        xpu2_lambert_sample(input.data(),8,int(reflection),output+p*64);
    }
}
static void gpu(Queue& q,const std::vector<Packet>& packets,unsigned base,unsigned count,float* output){
    std::vector<Queue::Ticket> tickets;
    for(unsigned p=0;p<count;++p){auto& packet=packets[(base+p)%packets.size()];auto t=q.submit(packet.input.data(),packet.native.data(),8,17,true);check(bool(t),"GPU admission failed");tickets.push_back(t);}
    check(q.publish(tickets,17),"GPU publication failed");
    for(unsigned p=0;p<count;++p){auto& t=tickets[p];{std::unique_lock<std::mutex> lock(q.mutex);check(t->completed.wait_for(lock,std::chrono::seconds(10),[&]{return t->done;}),"GPU timeout");}
        check(q.tryCollect(t,17,output+p*64)==Collect::Ready,"GPU collect failed");
        check(q.tryCollect(t,17,output+p*64)==Collect::Duplicate,"Duplicate GPU collect accepted");}
}
struct Result {uint64_t wall,hash=1469598103934665603ull;Stats cpu,gpu;unsigned swaps=0;};
static Result run(Pool& pool,Queue& q,const std::vector<Packet>& packets,const std::string& policy,unsigned cpuWorkers,unsigned size,unsigned epochs){
    const unsigned patterns=64;std::vector<Job> jobs;std::vector<unsigned> next(patterns,0);std::vector<bool> active(patterns,false);
    for(unsigned e=0;e<epochs;++e)for(unsigned p=0;p<patterns;++p)jobs.push_back({p,e,-1,0,std::vector<float>(size*64)});
    std::deque<unsigned> ready;for(unsigned p=0;p<patterns;++p)ready.push_back(p);
    std::mutex mutex;std::condition_variable changed;unsigned done=0;bool abort=false;std::exception_ptr error;std::vector<Stats> stats(cpuWorkers+1);
    auto start=Time::now();
    pool.run([&](unsigned worker){bool device=worker==cpuWorkers;if(device && policy=="cpu")return;
        try{for(;;){unsigned id=0,selected=0;{
            std::unique_lock<std::mutex> lock(mutex);
            auto find=[&](){if(abort || done==jobs.size())return true;
                unsigned minimum=*std::min_element(next.begin(),next.end());
                for(unsigned position=0;position<ready.size();++position){unsigned p=ready[position],e=next[p];check(!active[p] && e<epochs,"Invalid ready entry");
                    if(policy=="barrier" && e!=minimum)continue;
                    if((policy=="barrier" || policy=="alternating") && ((p+e)%2)!=unsigned(device))continue;
                    id=e*patterns+p;selected=position;return true;}return false;};
            changed.wait(lock,find);if(abort || done==jobs.size())return;
            ready.erase(ready.begin()+selected);
            auto& job=jobs[id];check(!job.state && !active[job.pattern],"Duplicate claim");job.state=1;job.owner=device;active[job.pattern]=true;
        }
        auto begin=Time::now();auto& job=jobs[id];unsigned base=(id*size)%packets.size();
        if(device)gpu(q,packets,base,size,job.result.data());else cpu(packets,base,size,job.result.data());
        stats[worker].busy+=elapsed(begin);++stats[worker].jobs;
        {std::lock_guard<std::mutex> lock(mutex);check(job.state==1 && job.owner==int(device) && next[job.pattern]==job.epoch,"Owner changed in flight");
            job.state=2;active[job.pattern]=false;++next[job.pattern];if(next[job.pattern]<epochs)ready.push_back(job.pattern);++done;changed.notify_all();}
    }}catch(...){std::lock_guard<std::mutex> lock(mutex);error=std::current_exception();abort=true;changed.notify_all();}});
    Result result;result.wall=elapsed(start);if(error)std::rethrow_exception(error);
    check(done==jobs.size(),"Lost jobs");
    // Canonical publication order and full numerical comparison are outside timing.
    for(unsigned id=0;id<jobs.size();++id){auto& job=jobs[id];check(job.state==2,"Unfinished job");
        unsigned base=(id*size)%packets.size();for(unsigned p=0;p<size;++p)check(!std::memcmp(job.result.data()+p*64,packets[(base+p)%packets.size()].native.data(),256),"Native/GPU parity failed");
        if(job.epoch && job.owner!=jobs[id-patterns].owner)++result.swaps;
        for(auto byte:std::vector<unsigned char>(reinterpret_cast<unsigned char*>(job.result.data()),reinterpret_cast<unsigned char*>(job.result.data()+job.result.size()))){result.hash^=byte;result.hash*=1099511628211ull;}
    }
    for(unsigned w=0;w<cpuWorkers;++w){result.cpu.busy+=stats[w].busy;result.cpu.jobs+=stats[w].jobs;}result.gpu=stats.back();return result;
}
int main(int argc,char** argv){
    try{
        check(argc==2,"Capture required");std::ifstream f(argv[1],std::ios::binary);std::vector<char> raw((std::istreambuf_iterator<char>(f)),{});
        check(raw.size()>4 && (raw.size()-4)%240==0 && !std::memcmp(raw.data(),"XCL1",4),"Bad capture");
        // Reflection must be uniform across each native SIMD packet. Construct
        // each packet from one captured record; vary records between packets.
        std::vector<Packet> packets((raw.size()-4)/240);
        for(unsigned p=0;p<packets.size();++p)for(unsigned lane=0;lane<8;++lane){const char* row=raw.data()+4+p*240;std::memcpy(packets[p].input.data()+lane*24,row+112,96);std::memcpy(packets[p].native.data()+lane*8,row+208,32);}
        Queue q;bool comma=false;std::cout<<"{\"runs\":[";
        try{for(unsigned workers:{1u,6u}){Pool pool(workers+1);
            run(pool,q,packets,"shared",workers,16,2); // Exclude initialization/warmup.
            for(unsigned size:{1u,16u}){uint64_t digest=0;const std::array<std::string,4> policies={"cpu","barrier","alternating","shared"};
                for(unsigned repeat=0;repeat<5;++repeat)for(unsigned offset=0;offset<4;++offset){auto policy=policies[(repeat+offset)%4];
                    auto r=run(pool,q,packets,policy,workers,size,16);
                    if(!digest)digest=r.hash;check(r.hash==digest,"Schedule-dependent digest");
                    if(policy=="barrier" || policy=="alternating")check(r.cpu.jobs==512 && r.gpu.jobs==512 && r.swaps==960,"Incorrect alternation");
                    if(comma)std::cout<<',';comma=true;
                    std::cout<<"{\"policy\":\""<<policy<<"\",\"workers\":"<<workers<<",\"samples_per_job\":"<<size*8<<",\"repeat\":"<<repeat<<",\"wall_ns\":"<<r.wall<<",\"cpu_jobs\":"<<r.cpu.jobs<<",\"gpu_jobs\":"<<r.gpu.jobs<<",\"cpu_busy_ns\":"<<r.cpu.busy<<",\"gpu_busy_ns\":"<<r.gpu.busy<<",\"swaps\":"<<r.swaps<<",\"digest\":\""<<r.hash<<"\"}";
                }
            }
        }}catch(...){q.stop(std::chrono::milliseconds(10000));throw;}
        check(q.stop(std::chrono::milliseconds(10000)) && q.cleanupOk && q.device.asyncReleased() && !q.device.cleanupErrors,"Cleanup failure");
        check(q.submitted==q.delivered && !q.retainedAsync && !q.full && !q.failed,"Queue accounting failure");
        check(q.device.samples==q.submitted*8 && q.device.accepted==q.device.samples && q.device.replaced==q.device.samples && !q.device.errors && !q.device.mismatch && !q.device.invalid && !q.device.unsupported,"GPU fallback or failure");
        std::cout<<"],\"passed\":true,\"gpu_samples\":"<<q.device.samples<<",\"gpu_batches\":"<<q.merged<<"}\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
