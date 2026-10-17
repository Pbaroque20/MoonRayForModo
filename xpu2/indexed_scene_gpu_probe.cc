// Real CUDA queue consuming owned indexed material packets; no native scene import.
#include "native_lambert_queue.cc"
#include "indexed_scene.h"
#include <array>
#include <fstream>
#include <iostream>
using namespace xpu2::indexed;
static void require(bool ok,const char* msg) { if(!ok) throw std::runtime_error(msg); }
template<class F> static void waitFor(F f) {
    auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);
    while(!f()) { require(std::chrono::steady_clock::now()<end,"GPU wait timed out"); std::this_thread::sleep_for(std::chrono::milliseconds(1)); }
}
struct Packet { std::array<float,192> input{}; std::array<float,64> native{}; };
static Bytes pack(const Packet& packet) {
    Bytes bytes(sizeof(packet)); std::memcpy(bytes.data(),&packet,sizeof(packet)); return bytes;
}
static Packet unpack(const View& view) {
    const auto& bytes=view->entities.at("material")->buffers.at(Field::Shading)->prepared;
    require(bytes.size()==sizeof(Packet),"Invalid indexed material packet");
    Packet packet;std::memcpy(&packet,bytes.data(),sizeof(packet));return packet;
}
int main(int argc,char** argv) {
 try {
    require(argc==2,"Capture required");
    std::ifstream stream(argv[1],std::ios::binary);
    Bytes data((std::istreambuf_iterator<char>(stream)),{});
    require(data.size()>=4+8*164 && std::memcmp(data.data(),"XNI1",4)==0,"Bad capture");
    Packet packet;
    for(int lane=0;lane<8;++lane) {
        auto src=data.data()+4+lane*164;
        std::memcpy(packet.input.data()+lane*24,src,96);std::memcpy(packet.native.data()+lane*8,src+96,28);
        uint32_t valid;std::memcpy(&valid,src+124,4);packet.native[lane*8+7]=float(valid);
    }
    SceneIndex index;unsigned preparations=0;
    auto encode=[&](Kind,Field,const Bytes& bytes){++preparations;return bytes;};
    { auto start=index.prepare(index.acquire(),{
        {"material",Kind::Material,{{Field::Shading,pack(packet)}},{},{}},
        {"geometry",Kind::Geometry,{{Field::Positions,Bytes(1024*1024,42)}},{},{}},
        {"object",Kind::Instance,{{Field::Transform,{0}}},std::set<std::string>{"geometry","material"},{}}
    },{},encode);
    require(index.commit(start),"Commit failed"); } auto old=index.acquire();
    Queue queue;
    // Hold device lock after job admission to guarantee an overlapping scene edit.
    std::unique_lock<std::mutex> paused(queue.device.mutex);
    auto oldPacket=unpack(old);
    auto ticket=queue.submit(oldPacket.input.data(),oldPacket.native.data(),8,old->revision,old);
    require(bool(ticket),"Old job not admitted");
    waitFor([&]{std::lock_guard<std::mutex> lock(queue.mutex);return queue.pending.empty();});
    for(int lane=0;lane<8;++lane) {
        for(int c=14;c<17;++c)packet.input[lane*24+c]*=.5f;
        for(int c=3;c<6;++c)packet.native[lane*8+c]*=.5f;
    }
    { auto changed=index.prepare(old,{{"material",Kind::Material,{{Field::Shading,pack(packet)}},{},{}}},{},encode);
    require(changed.view()->changes.preparedBuffers==1 && preparations==4,"Unchanged resources prepared");
    require(changed.view()->entities.at("geometry")==old->entities.at("geometry"),"Geometry not reused");
    require(index.commit(changed)&&!index.current(old),"Stale result not rejected"); }
    std::weak_ptr<const Snapshot> retained=old;
    old.reset();require(!retained.expired(),"Queue lost retained indexed scene");
    paused.unlock();
    std::array<float,64> output{};
    waitFor([&]{return queue.tryCollect(ticket,1,output.data())==Collect::Ready;});
    auto expected=oldPacket.native;
    for(int lane=0;lane<8;++lane)for(int c=3;c<6;++c)expected[lane*8+c]*=.5f;
    require(output==expected,"Old indexed GPU result changed");
    require(retained.expired(),"Retired index snapshot leaked");
    auto fresh=index.acquire();auto freshPacket=unpack(fresh);
    auto current=queue.submit(freshPacket.input.data(),freshPacket.native.data(),8,fresh->revision,fresh);
    require(bool(current),"Fresh job not admitted");
    waitFor([&]{return queue.tryCollect(current,fresh->revision,output.data())==Collect::Ready;});
    expected=freshPacket.native;
    for(int lane=0;lane<8;++lane)for(int c=3;c<6;++c)expected[lane*8+c]*=.5f;
    require(output==expected&&index.current(fresh),"New indexed GPU result invalid");
    require(queue.stop(std::chrono::milliseconds(5000))&&queue.cleanupOk&&!queue.device.cleanupErrors,"CUDA drain failed");
    require(!ticket->retainedResources&&!current->retainedResources,"Job retained scenes after drain");
    std::cout<<"{\"passed\":true,\"gpu_jobs\":2,\"samples\":16,\"prepared_buffers\":4,\"material_update_buffers\":1,\"geometry_reused\":true,\"stale_rejected\":true}\n";
    return 0;
 } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
