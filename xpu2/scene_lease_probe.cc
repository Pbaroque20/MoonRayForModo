// Real diagnostic CUDA work with synthetic owned scene data; NOT a native scene.
#include "native_lambert_queue.cc"
#include "scene_lease.h"
#include <fstream>
#include <iostream>
#include <array>
struct Audit {
    std::thread::id coordinator=std::this_thread::get_id();
    std::atomic<unsigned> destroyed{0},wrongThread{0};
};
struct OwnedScene {
    Audit& audit;const uint64_t color;
    OwnedScene(Audit& a,uint64_t c):audit(a),color(c) {}
    ~OwnedScene(){if(std::this_thread::get_id()!=audit.coordinator)++audit.wrongThread;++audit.destroyed;}
};
using Gate=xpu2::SceneLeaseGate<OwnedScene>;
static void check(bool ok,const char* msg) {if(!ok)throw std::runtime_error(msg);}
template<class F> void waitFor(F f) {
    auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);
    while(!f()){check(std::chrono::steady_clock::now()<end,"Timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
}
static xpu2::ShadowRequest request(const Gate::Lease& l) {
    xpu2::ShadowRequest q{};q.scene=l.scene();q.revision=l.revision();q.request=1;q.mask=4;q.direction[2]=1;q.farT=100;return q;
}
int main(int argc,char** argv) {
 try {
    check(argc==3,"mode and capture required");std::string mode=argv[1];
    std::ifstream stream(argv[2],std::ios::binary);std::vector<unsigned char> data((std::istreambuf_iterator<char>(stream)),{});
    check(data.size()>=4+8*164 && std::memcmp(data.data(),"XNI1",4)==0,"Bad fixture");
    std::array<float,192> input{};std::array<float,64> native{},output{},expected{};
    for(int lane=0;lane<8;++lane) {
        auto src=data.data()+4+lane*164;std::memcpy(input.data()+lane*24,src,96);std::memcpy(native.data()+lane*8,src+96,28);
        uint32_t valid;std::memcpy(&valid,src+124,4);native[lane*8+7]=float(valid);
    }
    expected=native;for(int lane=0;lane<8;++lane)for(int c=3;c<6;++c)expected[lane*8+c]*=.5f;
    Audit audit;Gate gate(2);Queue queue;
    auto first=std::make_unique<OwnedScene>(audit,123);check(gate.publish(1,1,first,{111}),"Initial publish");
    auto old=gate.acquire();const auto q=request(old);uint64_t light=0;
    Gate other(1);check(!other.current(old)&&other.close(),"Foreign gate accepted lease");
    check(!gate.current(Gate::Lease()),"Empty lease accepted");
    bool rejected=false;try{gate.restart(1);}catch(const std::invalid_argument&){rejected=true;}
    check(rejected&&gate.current(old),"Invalid restart corrupted active scene");
    check(old.resolve(q,light)&&light==111,"Original binding");
    // Deterministic delay before GPU dispatch, after the queue takes ownership.
    std::unique_lock<std::mutex> paused(queue.device.mutex);
    auto ticket=queue.submit(input.data(),native.data(),8,old.revision(),std::make_shared<const Gate::Lease>(old));check(bool(ticket),"Admission failed");
    waitFor([&]{std::lock_guard<std::mutex> lock(queue.mutex);return queue.pending.empty();});
    {std::lock_guard<std::mutex> lock(queue.mutex);check(bool(ticket->retainedResources),"GPU job did not retain scene");}
    unsigned denied=0,accepted=0;
    if(mode=="replace") {
        auto second=std::make_unique<OwnedScene>(audit,456);check(gate.publish(2,2,second,{222}),"Replacement");
        auto fresh=gate.acquire();check(!gate.current(old)&&gate.current(fresh),"Stale scene accepted");++denied;
        check(old.resolve(q,light)&&light==111,"Old binding changed");check(!fresh.resolve(q,light)&&!light,"Cross-scene binding accepted");
        check(audit.destroyed==0,"Delayed work lost its scene");
        auto third=std::make_unique<OwnedScene>(audit,789);
        for(int i=0;i<100;++i)check(!gate.publish(3,3,third,{333})&&third&&gate.current(fresh),"Retention bound bypassed");
        fresh={};paused.unlock();
        waitFor([&]{return queue.tryCollect(ticket,old.revision(),output.data())==Collect::Ready;});
        check(output==expected,"GPU result changed");check(!gate.current(old),"Late old result published");++denied;
        old={};check(gate.collect()==1&&audit.destroyed==1,"Old scene not retired on coordinator");
        check(gate.publish(3,3,third,{333}),"Backpressure did not recover");
        auto latest=gate.acquire();check(gate.current(latest)&&latest.resource().color==789,"Latest scene");++accepted;latest={};
    } else if(mode=="restart") {
        gate.restart(2);check(!gate.current(old),"Same scene old attempt accepted");++denied;
        auto fresh=gate.acquire();check(fresh.scene()==old.scene()&&gate.current(fresh),"Same scene restart identity");
        paused.unlock();waitFor([&]{return queue.tryCollect(ticket,old.revision(),output.data())==Collect::Ready;});
        check(output==expected&&!gate.current(old),"Old completion accepted after restart");++denied;
        check(gate.current(fresh),"New attempt rejected");++accepted;old={};fresh={};
    } else if(mode=="cancel") {
        check(queue.cancel(ticket),"Cancellation rejected");check(!gate.close()&&!gate.current(old)&&audit.destroyed==0,"Close freed in-flight scene");++denied;
        // Cancellation acknowledgement is NOT device quiescence: keep the lease.
        check(queue.tryCollect(ticket,old.revision(),output.data())==Collect::Cancelled,"Cancelled result delivered");
        old={}; // Only the GPU job and registry now retain the old scene.
        check(gate.collect()==1&&audit.destroyed==0,"Caller release freed GPU scene");
        check(!queue.stop(std::chrono::milliseconds(5))&&audit.destroyed==0,"Stop timeout freed resources");
        {std::lock_guard<std::mutex> lock(queue.mutex);check(bool(ticket->retainedResources),"Timed-out stop dropped scene");}
        paused.unlock();check(queue.stop(std::chrono::milliseconds(5000)),"Cancelled GPU cleanup failed");
        old={};check(gate.close()&&audit.destroyed==1,"Cancelled scene retirement failed");
    } else if(mode=="readers") {
        std::array<Gate::Lease,8> leases;for(auto& lease:leases)lease=old;
        std::atomic<unsigned> reads{0},wrongThreadRejected{0};std::atomic<bool> release{false};std::vector<std::thread> readers;
        for(int i=0;i<8;++i)readers.emplace_back([&,i,lease=std::move(leases[i])]() mutable {
            for(int k=0;k<10000;++k){uint64_t id=0;if(lease.resource().color==123&&lease.resolve(q,id)&&id==111)++reads;}
            try{gate.collect();}catch(const std::logic_error&){++wrongThreadRejected;}
            while(!release.load())std::this_thread::yield();lease={};
        });
        check(!gate.close()&&audit.destroyed==0,"Close invalidated readers");++denied;
        paused.unlock();waitFor([&]{return queue.tryCollect(ticket,old.revision(),output.data())==Collect::Ready;});
        check(output==expected&&!gate.current(old),"Closed result delivered");++denied;old={};
        release=true;for(auto& t:readers)t.join();
        check(reads==80000&&wrongThreadRejected==8&&audit.destroyed==0,"Reader lifetime/thread failure");
        check(gate.collect()==0&&audit.destroyed==1,"Coordinator cleanup failed");
    } else throw std::runtime_error("Unknown scenario");
    check(gate.close()&&!gate.acquire(),"Scene leases leaked or closed admission");check(queue.stop(std::chrono::milliseconds(5000)),"GPU stop failed");
    check(queue.cleanupOk&&!queue.device.cleanupErrors&&!audit.wrongThread&&!ticket->retainedResources,"Cleanup failure or retained job scene");
    {std::lock_guard<std::mutex> lock(queue.mutex);check(!queue.retainedAsync&&!queue.failed,"Outstanding GPU work");queue.snapshot();}
    std::cout<<"{\"case\":\""<<mode<<"\",\"denied\":"<<denied<<",\"accepted\":"<<accepted<<",\"destroyed\":"<<audit.destroyed<<",\"job_retention\":true,\"wrong_thread_destroy\":"<<audit.wrongThread<<",\"passed\":true}\n";
    return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
