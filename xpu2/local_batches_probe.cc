// Isolated local chunk claiming and bulk CUDA stage. No film or path migration.
#define main xpu2_alternating_main
#include "alternating_workers_probe.cc"
#undef main
struct Range {unsigned begin,end;};
struct LocalResult {uint64_t wall,hash=1469598103934665603ull;unsigned cpuPackets=0,gpuPackets=0,claims=0;};
static LocalResult localRun(Pool& pool,Bridge& device,const std::vector<Packet>& packets,unsigned workers,
                            unsigned cpuChunk,unsigned gpuChunk,const std::string& policy,unsigned total){
    std::vector<float> output(size_t(total)*64);
    std::vector<std::vector<Range>> leases(workers+1);for(auto& v:leases)v.reserve(total);
    std::atomic<unsigned> next{0};std::atomic<bool> abort{false};std::mutex errors;std::exception_ptr error;
    auto start=Time::now();
    pool.run([&](unsigned id){const bool gpu=id==workers;if((gpu && policy=="cpu") || (!gpu && policy=="gpu"))return;
        try{
            // Scratch is local to the worker for the complete run, not per job.
            std::vector<float> input(gpu?gpuChunk*192:0);
            for(;;){if(abort.load())return;unsigned begin=next.fetch_add(gpu?gpuChunk:cpuChunk);if(begin>=total)return;
                unsigned end=std::min(total,begin+(gpu?gpuChunk:cpuChunk));
                if(gpu){for(unsigned p=begin;p<end;++p){const auto& packet=packets[p%packets.size()];
                    std::memcpy(input.data()+(p-begin)*192,packet.input.data(),768);
                    std::memcpy(output.data()+p*64,packet.native.data(),256);}
                    const auto before=device.replaced;device.run(input.data(),output.data()+begin*64,(end-begin)*8);
                    check(device.replaced-before==(end-begin)*8,"Bulk GPU fallback or rejection");
                }else cpu(packets,begin,end-begin,output.data()+begin*64);
                leases[id].push_back({begin,end});
            }
        }catch(...){std::lock_guard<std::mutex> lock(errors);error=std::current_exception();abort.store(true);}
    });
    LocalResult result;result.wall=elapsed(start);if(error)std::rethrow_exception(error);
    std::vector<Range> all;
    for(unsigned id=0;id<leases.size();++id)for(auto r:leases[id]){all.push_back(r);++result.claims;
        if(id==workers)result.gpuPackets+=r.end-r.begin;else result.cpuPackets+=r.end-r.begin;}
    std::sort(all.begin(),all.end(),[](Range a,Range b){return a.begin<b.begin;});unsigned cursor=0;
    for(auto r:all){check(r.begin==cursor && r.end>r.begin && r.end<=total,"Missing or duplicate range");cursor=r.end;}
    check(cursor==total && result.cpuPackets+result.gpuPackets==total,"Missing samples");
    for(unsigned p=0;p<total;++p)check(!std::memcmp(output.data()+p*64,packets[p%packets.size()].native.data(),256),"Bulk output mismatch");
    const auto* bytes=reinterpret_cast<const unsigned char*>(output.data());
    for(size_t i=0;i<output.size()*4;++i){result.hash^=bytes[i];result.hash*=1099511628211ull;}
    return result;
}
int main(int argc,char** argv){try{
    check(argc==2,"Capture required");std::ifstream f(argv[1],std::ios::binary);std::vector<char> raw((std::istreambuf_iterator<char>(f)),{});
    check(raw.size()>4 && (raw.size()-4)%240==0 && !std::memcmp(raw.data(),"XCL1",4),"Invalid capture");
    std::vector<Packet> packets((raw.size()-4)/240);
    for(unsigned p=0;p<packets.size();++p)for(unsigned lane=0;lane<8;++lane){const char* row=raw.data()+4+p*240;
        std::memcpy(packets[p].input.data()+lane*24,row+112,96);std::memcpy(packets[p].native.data()+lane*8,row+208,32);}
    bool comma=false;uint64_t digest=0,totalGpu=0,totalBatches=0;std::cout<<"{\"runs\":[";
    for(unsigned workers:{1u,6u}){Pool pool(workers+1);Bridge device;
        try{
            localRun(pool,device,packets,workers,64,2048,"gpu",2048); // GPU initialization and maximum-size warmup.
            for(unsigned repeat=0;repeat<3;++repeat){
                struct Case {unsigned cpu,gpu;std::string policy;};std::vector<Case> cases;
                for(unsigned chunk:{1u,64u}){cases.push_back({chunk,16,"cpu"});
                    for(unsigned bulk:{16u,64u,256u,1024u,2048u})cases.push_back({chunk,bulk,"shared"});}
                if(workers==6)for(unsigned bulk:{16u,64u,256u,1024u,2048u})cases.push_back({64,bulk,"gpu"});
                std::rotate(cases.begin(),cases.begin()+(repeat*5)%cases.size(),cases.end());
                for(auto c:cases){auto r=localRun(pool,device,packets,workers,c.cpu,c.gpu,c.policy,32768);
                    if(!digest)digest=r.hash;check(r.hash==digest,"Schedule-dependent result");
                    if(comma)std::cout<<',';comma=true;
                    std::cout<<"{\"policy\":\""<<c.policy<<"\",\"workers\":"<<workers<<",\"cpu_chunk\":"<<c.cpu*8<<",\"gpu_chunk\":"<<c.gpu*8
                      <<",\"repeat\":"<<repeat<<",\"samples\":262144,\"wall_ns\":"<<r.wall<<",\"claims\":"<<r.claims
                      <<",\"cpu_samples\":"<<r.cpuPackets*8<<",\"gpu_samples\":"<<r.gpuPackets*8<<",\"digest\":\""<<r.hash<<"\"}";
                }
            }
        }catch(...){pool.run([&](unsigned id){if(id==workers)device.close();});throw;}
        bool closed=false;pool.run([&](unsigned id){if(id==workers)closed=device.close();});
        check(closed && device.asyncReleased() && !device.cleanupErrors,"Bulk resources not released");
        check(device.samples==device.accepted && device.samples==device.replaced && !device.errors && !device.invalid && !device.mismatch && !device.unsupported,"GPU failed");
        totalGpu+=device.samples;totalBatches+=device.batches;
    }
    std::cout<<"],\"passed\":true,\"gpu_samples\":"<<totalGpu<<",\"gpu_batches\":"<<totalBatches<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
