#include "texture_work.h"
#include <chrono>
#include <iostream>
using namespace xpu2;using namespace xpu2::texture;
static unsigned checks=0;
static void check(bool ok,const char* why){++checks;if(!ok)throw std::runtime_error(why);}
template<class F>static void rejects(F f){bool caught=false;try{f();}catch(const std::exception&){caught=true;}check(caught,"Expected rejection");}
template<class F>static void until(F f){auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);while(!f()){if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("Wait timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
struct Gate {std::mutex mutex;std::condition_variable cv;bool open=false,entered=false;
    void wait(){std::unique_lock<std::mutex> lock(mutex);entered=true;cv.notify_all();if(!cv.wait_for(lock,std::chrono::seconds(5),[&]{return open;}))throw std::runtime_error("Gate timeout");}
    void release(){std::lock_guard<std::mutex> lock(mutex);open=true;cv.notify_all();}
    bool started(){std::lock_guard<std::mutex> lock(mutex);return entered;}
};
struct Release{Gate& gate;~Release(){gate.release();}};
struct Page:DevicePage {Bytes bytes;explicit Page(const Bytes& b):bytes(b){}bool ready()override{return true;}void wait()override{}uint64_t address()const override{return reinterpret_cast<uint64_t>(bytes.data());}};
struct BackendTest:Backend{std::shared_ptr<DevicePage> upload(const Bytes& b)override{return std::make_shared<Page>(b);}void drain()override{}};
struct FenceTest:Fence{bool done=false;bool ready()override{return done;}void wait()override{done=true;}};
static Key key(unsigned rev=1){return {"a.tx","raw",rev};}
static Bytes bytes(const Key& k,size_t n){return Bytes(n,uint8_t(k.revision));}
static DependencyView dependencies(unsigned revision){
    indexed::SceneIndex index;auto empty=emptyDependencies(index.acquire());
    auto candidate=index.prepare(index.acquire(),{{"file",indexed::Kind::Attribute,{},std::set<std::string>{},{}},{"material",indexed::Kind::Material,{},std::set<std::string>{"file"},{}}},{},[](auto,auto,const auto& b){return b;});
    auto result=prepareDependencies(empty,candidate,{{"file",{{key(revision)}, {}}}},{});index.commit(candidate);return result;
}
int main(){try{
    {
        Gate gate;BackendTest backend;Cache cache(backend,{32,32,16});AsyncTextureLoader loader([&]{return [&](const Key& k,size_t n){gate.wait();return bytes(k,n);};},32,2);
        TextureWorkQueue queue(cache,loader,4,32);Release release{gate};auto deps=dependencies(1);queue.begin(1,deps);
        check(queue.submit(1,"material",{7},{{key(),16}},false),"Waiting work rejected");check(!queue.claim(),"Waiting work published early");until([&]{return gate.started();});
        check(queue.submit(2,"",{1,2,3}, {},false),"Ready work rejected");auto ready=queue.claim();check(ready&&ready->id==2,"Ready work blocked behind texture I/O");
        unsigned contribution=0;for(auto v:ready->payload)contribution+=v;check(contribution==6,"Owned ready work corrupted");
        check(queue.finish(ready)==TextureWorkQueue::Finish::Accepted&&queue.stats().bypasses==1,"Bypass publication failed");check(queue.finish(ready)==TextureWorkQueue::Finish::Invalid,"Duplicate completion accepted");
        check(!queue.submit(2,"",{}, {},false),"Duplicate logical work accepted");gate.release();TextureWorkQueue::Lease resumed;
        until([&]{resumed=queue.claim();return bool(resumed);});check(resumed->id==1&&cache.cpu(resumed->pages[0])==bytes(key(),16)&&resumed->payload==Bytes{7},"Waiting work resume changed identity/data");
        check(queue.finish(resumed)==TextureWorkQueue::Finish::Accepted,"Resume completion rejected");check(queue.close(),"Close failed");loader.close();check(cache.close(),"Cache close failed");
    }
    {
        Gate gate;BackendTest backend;Cache cache(backend,{32,32,16});AsyncTextureLoader loader([&]{return [&](const Key& k,size_t n){gate.wait();return bytes(k,n);};},32,2);
        TextureWorkQueue queue(cache,loader,2,16);Release release{gate};queue.begin(1,dependencies(1));queue.submit(1,"material",{1},{{key(),16}},false);queue.claim();until([&]{return gate.started();});
        queue.submit(2,"",{2}, {},false);auto old=queue.claim();check(old&&old->id==2,"Initial ready job absent");
        queue.begin(2,dependencies(2));check(loader.stats().heldBytes==16,"Cancelled decoder lost reservation early");
        check(queue.submit(2,"",{3}, {},false),"New-attempt logical ID rejected");check(!queue.submit(3,"",{}, {},false),"Revoked claimed job escaped capacity");
        auto current=queue.claim();check(current&&current->payload==Bytes{3},"New generation payload wrong");
        check(queue.finish(old)==TextureWorkQueue::Finish::Revoked&&queue.finish(current)==TextureWorkQueue::Finish::Accepted,"Old generation published");gate.release();
        queue.submit(4,"material",{},{{key(2),16}},false);TextureWorkQueue::Lease loaded;until([&]{loaded=queue.claim();return bool(loaded);});
        check(cache.cpu(loaded->pages[0])==bytes(key(2),16),"Cancelled revision aliased new data");queue.finish(loaded);check(queue.close(),"Revision close failed");loader.close();check(cache.close(),"Revision cache close failed");
    }
    {
        BackendTest backend;Cache cache(backend,{16,16,16});AsyncTextureLoader loader([]{return [](const Key&,size_t)->Bytes{throw std::runtime_error("Injected missing texture");};},16,1);
        TextureWorkQueue queue(cache,loader);queue.begin(1,dependencies(1));queue.submit(1,"material",{},{{key(),16}},false);TextureWorkQueue::Lease failed;
        until([&]{failed=queue.claim();return bool(failed);});check(!failed->failure.empty()&&failed->pages.empty(),"Failure manufactured sample");
        check(queue.finish(failed)==TextureWorkQueue::Finish::Failed,"Failed work accepted into film");queue.submit(2,"",{9},{},false);auto ready=queue.claim();check(ready&&queue.finish(ready)==TextureWorkQueue::Finish::Accepted,"Decode failure blocked unrelated work");
        rejects([&]{queue.submit(3,"material",{},{{key(),17}},false);});rejects([&]{queue.submit(4,"material",{},{{key(2),16}},false);});rejects([&]{queue.submit(5,"material",{},{{key(),8},{key(),8}},false);});
        check(queue.close(),"Failure close failed");loader.close();check(cache.close(),"Failure cache close failed");
    }
    {
        BackendTest backend;Cache cache(backend,{32,32,16});AsyncTextureLoader loader([]{return bytes;},32,2);TextureWorkQueue queue(cache,loader,2,16,2);queue.begin(1,dependencies(1));
        queue.submit(1,"material",{4},{{key(),16}},true);TextureWorkQueue::Lease gpu;until([&]{gpu=queue.claim();return bool(gpu);});
        rejects([&]{queue.finish(gpu);});auto fence=std::make_shared<FenceTest>();check(queue.finish(gpu,fence)==TextureWorkQueue::Finish::Pending,"GPU work retired before completion");
        check(!queue.close(),"Close dropped active GPU work");check(!cache.discard(key(),true),"GPU job lost pinned page");fence->done=true;
        check(queue.finish(gpu,fence)==TextureWorkQueue::Finish::Revoked,"Cancelled GPU work published");check(queue.close(),"Drained GPU close failed");
        queue.begin(2,dependencies(1));for(unsigned id=0;id<2;++id){queue.submit(id,"",{1},{},false);auto j=queue.claim();check(queue.finish(j)==TextureWorkQueue::Finish::Accepted,"Ledger job failed");}
        check(!queue.submit(3,"",{}, {},false),"Logical-ID ledger exceeded bound");check(queue.close(),"Ledger close failed");loader.close();check(cache.close(),"GPU cache close failed");
    }
    {
        // Two jobs that each fit but cannot coexist must not pin partial sets.
        BackendTest backend;Cache cache(backend,{16,16,8});AsyncTextureLoader loader([]{return bytes;},16,2);TextureWorkQueue queue(cache,loader);
        auto deps=dependencies(1);queue.begin(1,deps);auto tile0=key(),tile1=key(),tile2=key();tile1.x=1;tile2.x=2;
        queue.submit(1,"material",{1},{{tile0,8},{tile1,8}},false);queue.submit(2,"material",{2},{{tile1,8},{tile2,8}},false);
        unsigned done=0;until([&]{if(auto job=queue.claim()){check(job->pages.size()==2,"Partial working set dispatched");for(const auto& page:job->pages)check(cache.cpu(page)==Bytes(8,1),"Pressure page corrupted");check(queue.finish(job)==TextureWorkQueue::Finish::Accepted,"Pressure finish failed");++done;}return done==2;});
        check(queue.close(),"Pressure close failed");loader.close();check(cache.close(),"Pressure cache close failed");
    }
    std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"blocked_decode_bypass\":true,\"revision_cancel\":true,\"completion_fenced\":true}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
