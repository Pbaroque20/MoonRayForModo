// Guard tests with the same bridge and real GPU queue as the native adapter.
#include "batched_bridge.cc"
#include <fstream>
#include <iostream>
static void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
int main(int argc,char** argv){
    try{
        require(argc==3,"case and correlated capture required");
        const std::string mode=argv[1];
        std::ifstream file(argv[2],std::ios::binary);
        std::vector<char> raw((std::istreambuf_iterator<char>(file)),{});
        require(raw.size()>=244 && !std::memcmp(raw.data(),"XCL1",4),"Missing native event");
#ifdef XPU2_ASYNC_TRANSFERS_BUILT
        if(mode.rfind("async_",0)==0) {
            std::array<float,24> in{};std::array<float,8> native{};
            std::memcpy(in.data(),raw.data()+4+112,96);std::memcpy(native.data(),raw.data()+4+208,32);
            Bridge bridge;
            if(mode=="async_reuse") {
                for(int count: {1,8,72,512,3}) {
                    std::vector<float> input(count*24),output(count*8),expected(count*8);
                    for(int i=0;i<count;++i) {
                        std::copy(in.begin(),in.end(),input.begin()+i*24);
                        std::copy(native.begin(),native.end(),output.begin()+i*8);
                    }
                    expected=output;for(int i=0;i<count;++i)for(int c=3;c<6;++c)expected[i*8+c]*=.5f;
                    bridge.run(input.data(),output.data(),count);
                    require(output==expected && !bridge.errors && !bridge.mismatch,"Async staging result corrupted");
                    std::fill(input.begin(),input.end(),-999);std::fill(output.begin(),output.end(),-777);
                }
                require(bridge.batches==5 && bridge.replaced==596,"Async varying-size batches missing");
            }else {
                auto output=native;bridge.run(in.data(),output.data(),1);
                require(output==native && bridge.errors && !bridge.replaced && !bridge.ready,"Async failure published output");
                bridge.run(in.data(),output.data(),1);
                require(output==native && !bridge.replaced,"Failed staging reused");
            }
            require(bridge.close() && bridge.asyncReleased() && !bridge.context && !bridge.lib,"Async resources leaked");
            std::cout<<"{\"case\":\""<<mode<<"\",\"passed\":true,\"cleanup\":true}\n";return 0;
        }
#endif
#ifdef XPU2_WINDOW_DISPATCH_BUILT
        if(mode=="publication") {
            std::array<float,24> in{};std::array<float,8> native{},out{},expected{};
            std::memcpy(in.data(),raw.data()+4+112,96);std::memcpy(native.data(),raw.data()+4+208,32);
            expected=native;for(int c=3;c<6;++c)expected[c]*=.5f;
            Queue q,other;q.capacity=2;
            auto a=q.submit(in.data(),native.data(),1,7,true);
            auto b=q.submit(in.data(),native.data(),1,7,true);
            auto foreign=other.submit(in.data(),native.data(),1,7,true);
            require(a && b && foreign && !q.submit(in.data(),native.data(),1,7,true),"Held requests escaped capacity");
            require(!q.publish({a,a},7) && !q.publish({a,foreign},7) && !q.publish({a},8) && !q.publish({},7),"Invalid publication accepted");
            require(!q.publish(std::vector<Queue::Ticket>(17,a),7),"Oversized publication accepted");
            {std::lock_guard<std::mutex> lock(q.mutex);require(!q.hasDispatchable() && !a->done && !b->done && q.merged==0,"Held work dispatched");}
            require(q.cancel(b) && !q.publish({a,b},7),"Cancelled publication accepted");
            auto c=q.submit(in.data(),native.data(),1,7,true);
            require(c && q.publish({c},7),"Independent ready producer blocked");
            auto collect=[&](const Queue::Ticket& ticket){
                {std::unique_lock<std::mutex> lock(q.mutex);
                 require(ticket->completed.wait_for(lock,std::chrono::seconds(5),[&]{return ticket->done;}),"Published request stalled");}
                require(q.tryCollect(ticket,7,out.data())==Collect::Ready && out==expected,"Published result differs");
            };
            collect(c);
            {std::lock_guard<std::mutex> lock(q.mutex);require(!a->dispatchable && !a->done,"Foreign window prematurely released");}
            require(q.publish({a},7) && !q.publish({a},7),"Duplicate publication accepted");collect(a);
            auto held=q.submit(in.data(),native.data(),1,7,true);
            auto ready=q.submit(in.data(),native.data(),1,7,true);
            require(held && ready && q.publish({ready},7),"Shutdown setup failed");
            require(q.stop(std::chrono::milliseconds(5000)),"Window shutdown failed");
            require(q.tryCollect(held,7,out.data())==Collect::Cancelled,"Shutdown published incomplete work");
            collect(ready);
            require(!q.publish({held},7) && !q.retainedAsync && !q.worker.joinable(),"Shutdown retained credits");
            require(other.stop(std::chrono::milliseconds(5000)) && !other.retainedAsync && !other.worker.joinable(),"Other held queue failed cleanup");
            std::cout<<"{\"case\":\"publication\",\"passed\":true,\"cleanup\":true}\n";return 0;
        }
#endif
        if(mode=="window"){
            std::array<std::array<float,64>,16> output{},expected{};
            const size_t records=(raw.size()-4)/240;
            for(int n=0;n<16;++n){
                std::array<float,24> input{};std::array<float,8> value{};
                const char* record=raw.data()+4+(n%records)*240;
                std::memcpy(input.data(),record+112,96);std::memcpy(value.data(),record+208,32);
                int lane=n%8;std::copy(value.begin(),value.end(),output[n].begin()+lane*8);
                expected[n]=output[n];for(int c=3;c<6;++c)expected[n][lane*8+c]*=.5f;
                xpu2BatchedBegin(n);xpu2BatchedLambert(input.data(),value.data(),&lane,1);xpu2BatchedSampleEnd();
                input.fill(-99);value.fill(-77);
            }
            require(metrics().open==16 && metrics().peakOpen==16,"Batch ownership not bounded/retained");
            for(int n: {-1,16,0}){
                bool rejected=false;try{xpu2BatchedBegin(n);}catch(const std::runtime_error&){rejected=true;}
                require(rejected,"Invalid/reused slot accepted");
            }
            for(int n=15;n>=0;--n){
                xpu2BatchedCollect(output[n].data(),1<<(n%8),n);
                require(output[n]==expected[n],"Batch slot/lane result misrouted");
            }
            auto& q=deferredQueue();
            require(!metrics().open && metrics().collected==16 && q.stop(std::chrono::milliseconds(5000)) &&
                    !q.worker.joinable() && !q.retainedAsync && !q.device.cleanupErrors,"Batch resources retained");
            std::cout<<"{\"case\":\"window\",\"passed\":true,\"cleanup\":true}\n";return 0;
        }
        std::array<float,24> input;std::array<float,8> native;
        std::memcpy(input.data(),raw.data()+4+112,96);std::memcpy(native.data(),raw.data()+4+208,32);
        std::array<float,64> post{};std::copy(native.begin(),native.end(),post.begin());
        int lane=0;
        xpu2BatchedBegin(0);
        if(mode=="nested"){
            bool rejected=false;try{xpu2BatchedBegin(0);}catch(const std::runtime_error&){rejected=true;}
            require(rejected,"Nested native scope accepted");
        }
        xpu2BatchedLambert(input.data(),native.data(),&lane,1);
        require(bool(current().ticket),"Missing ticket");
        if(mode=="multiple")xpu2BatchedLambert(input.data(),native.data(),&lane,1);
        xpu2BatchedSampleEnd();
        if(mode=="transformed")post[3]+=1.f;
        auto original=post;
        xpu2BatchedCollect(post.data(),mode=="mask" ? 0 : 1,0);
        require(!current().open && !current().ticket && activeCpu.load()==0,"Scope leaked");
        auto& q=deferredQueue();
        require(q.stop(std::chrono::milliseconds(5000)) && !q.worker.joinable(),"Queue cleanup failed");
        require(q.retainedAsync==0 && !q.device.cleanupErrors,"Resources retained");
        if(mode=="transformed" || mode=="mask"){
            require(metrics().guardFallback==1 && !metrics().collected && post==original,"Changed post-sampler data published");
        }else if(mode=="multiple"){
            require(metrics().multipleHooks==1 && !metrics().collected && post==original,"Nested lobe output published");
        }else if(mode=="nested" || mode=="positive"){
            for(int i=3;i<6;++i)original[i]*=.5f;
            require(metrics().collected==1 && post==original,"Deferred GPU result not consumed");
        }else throw std::runtime_error("Unknown case");
        std::cout<<"{\"case\":\""<<mode<<"\",\"passed\":true,\"cleanup\":true}\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
