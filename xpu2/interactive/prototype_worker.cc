// Local-only standalone adapter around the bounded native service. No Modo APIs.
// Control: bounded JSON lines on stdin. Output: LE uint32 JSON size, JSON, then
// rgba_bytes little-endian float32 bytes. The pipe has a dedicated draining host.
#include "mixed_service.h"
#include <OpenImageIO/imageio.h>
#include <json/json.h>
#include <fstream>
#include <iostream>
#include <mutex>
#include <optional>
#include <fcntl.h>
#include <io.h>
using namespace xpu2::interactive;
namespace rdl=scene_rdl2::rdl2;
struct Wire {Json::Value meta;std::vector<float> rgba;};
static void emit(const Wire& w){
 Json::StreamWriterBuilder b;b["indentation"]="";auto j=Json::writeString(b,w.meta);
 cpu::need(j.size()<=16384,"Wire header budget");uint32_t n=uint32_t(j.size());
 std::cout.write(reinterpret_cast<const char*>(&n),4);std::cout.write(j.data(),j.size());
 if(!w.rgba.empty())std::cout.write(reinterpret_cast<const char*>(w.rgba.data()),w.rgba.size()*4);
 std::cout.flush();cpu::need(bool(std::cout),"Output pipe closed");
}
static Json::Value epochs(Epoch e){Json::Value j; j["session"]=Json::UInt64(e.session);j["scene"]=Json::UInt64(e.scene);j["camera"]=Json::UInt64(e.camera);j["settings"]=Json::UInt64(e.settings);return j;}
static uint64_t number(const Json::Value& v,const char* name,uint64_t cap=~uint64_t(0)){
 cpu::need(v.isUInt64()&&v.asUInt64()<=cap,std::string("Invalid ")+name);return v.asUInt64();
}
static Epoch epoch(const Json::Value& j){return {number(j["session"],"session"),number(j["scene"],"scene"),number(j["camera"],"camera"),number(j["settings"],"settings")};}
static fs::path wirePath(const Json::Value& v){cpu::need(v.isString()&&v.asString().size()<16384,"Path bound");auto p=fs::u8path(v.asString());cpu::need(p.is_absolute(),"Absolute path required");return p;}
struct Inbox {
 std::mutex mutex;std::optional<Json::Value> value;
 std::atomic<uint64_t> latest{0};std::atomic<bool> closing{false};
 void read()noexcept{
  try{char line[65537];while(std::cin.getline(line,sizeof(line))){
   Json::CharReaderBuilder b;Json::Value j;std::string error;std::istringstream s(line);
   cpu::need(Json::parseFromStream(b,s,&j,&error),"Invalid input JSON");
   auto op=j["op"].asString();if(op=="close")break;
   cpu::need(op=="render"||op=="cancel","Unknown command");auto id=number(j["id"],"id",(1ull<<32)-1);
   cpu::need(id>latest.load(),"Non-monotonic request ID");
   {std::lock_guard<std::mutex> lock(mutex);value=std::move(j);latest.store(id,std::memory_order_release);}
  }}catch(...){}closing.store(true,std::memory_order_release);
 }
 std::optional<Json::Value> take(){std::lock_guard<std::mutex> lock(mutex);auto result=std::move(value);value.reset();return result;}
};
class Outbox {
 SpscRing<std::unique_ptr<Wire>,2> queue;std::atomic<bool> closing{false},failed{false};std::thread thread;
public:
 Outbox():thread([this]{try{while(true){std::unique_ptr<Wire> p;if(queue.tryPop(p)){emit(*p);continue;}if(closing.load())break;std::this_thread::sleep_for(std::chrono::milliseconds(1));}}catch(...){failed=true;}}){}
 bool push(std::unique_ptr<Wire>& p){return !failed.load()&&queue.tryPush(p);}
 bool bad()const{return failed.load();}
 void close(){closing=true;if(thread.joinable())thread.join();}
 ~Outbox(){close();}
};
static int decode(const char* file){
 auto in=OIIO::ImageInput::open(file);cpu::need(bool(in),"Cannot open reference EXR");auto spec=in->spec();
 cpu::need(!spec.deep&&spec.width>0&&spec.height>0&&size_t(spec.width)*spec.height<=1048576&&spec.depth==1&&spec.nchannels==4,"Reference display size/channels unsupported");
 cpu::need(spec.x==0&&spec.y==0&&spec.full_width==spec.width&&spec.full_height==spec.height,"Reference data window unsupported");
 for(unsigned i=0;i<4;++i)cpu::need(spec.channelnames[i]==std::string(1,"RGBA"[i]),"Reference channels must be RGBA");
 cpu::need(!in->seek_subimage(1,0)&&!in->seek_subimage(0,1),"Reference multipart/mipmap unsupported");
 Wire w;w.rgba.resize(size_t(spec.width)*spec.height*4);
 cpu::need(in->read_image(0,0,0,4,OIIO::TypeDesc::FLOAT,w.rgba.data()),"Reference pixels unreadable");
 // MoonRay native film and our wire use bottom-first rows; EXR is top-first.
 for(int y=0;y<spec.height/2;++y)for(int x=0;x<spec.width*4;++x)std::swap(w.rgba[size_t(y)*spec.width*4+x],w.rgba[size_t(spec.height-1-y)*spec.width*4+x]);
 for(float f:w.rgba)cpu::need(std::isfinite(f),"Nonfinite reference pixels");
 w.meta["kind"]="decoded";w.meta["width"]=spec.width;w.meta["height"]=spec.height;w.meta["rgba_bytes"]=Json::UInt64(w.rgba.size()*4);emit(w);return 0;
}
int main(int argc,char** argv){
 _setmode(_fileno(stdout),_O_BINARY);
 try{
  if(argc==3&&std::string(argv[1])=="--decode")return decode(argv[2]);
  cpu::need(argc==3||argc==4,"runtime ptx [--test-faults] required");bool testFaults=argc==4&&std::string(argv[3])=="--test-faults";
  std::ifstream input(argv[2]);cpu::need(bool(input),"PTX file unavailable");std::string ptx((std::istreambuf_iterator<char>(input)),{});
  Inbox inbox;Outbox outbox;std::thread reader([&]{inbox.read();});mixed::Service service(ptx,true);
  std::unique_ptr<CanonicalSession> canonical;std::unique_ptr<rdl::SceneContext> context;cpu::PlanView prior;
  uint64_t active=0,ticket=0,crashRequest=0;Epoch current{};std::unique_ptr<Wire> held;
  while(!inbox.closing.load()&&!outbox.bad()){
   if(auto request=inbox.take()){
    service.cancel();active=number((*request)["id"],"id");held.reset();
    if((*request)["op"]=="cancel")active=0;
    else{
     CanonicalView staged;
     try{
      current=epoch((*request)["epoch"]);auto file=wirePath((*request)["scene"]),folder=wirePath((*request)["staging"]),assets=wirePath((*request)["assets"]);
      auto threads=unsigned(number((*request)["threads"],"threads",12));cpu::need(threads>0,"Zero threads");
      auto window=unsigned(number((*request)["window_ms"],"window",100));cpu::need(window>0,"Window required");
      bool refill=false;if(request->isMember("refill_fine")){cpu::need((*request)["refill_fine"].isBool(),"Invalid refill option");refill=(*request)["refill_fine"].asBool();}
      auto publish=request->isMember("publish_ms")?unsigned(number((*request)["publish_ms"],"publish interval",1000)):0u;
      auto fault=unsigned(number((*request)["fault"],"fault",2));cpu::need(!fault||testFaults,"Fault injection is disabled");
      auto domainName=(*request)["domain"].asString();cpu::Domain domain;
      if(domainName=="surface-textures")domain=cpu::Domain::SurfaceTextures;
      else if(domainName=="planar-textures")domain=cpu::Domain::PlanarTextures;
      else if(domainName=="diffuse-mesh")domain=cpu::Domain::DiffuseMesh;
      else throw cpu::Unsupported("Unknown admission domain");
      cpu::need(file.extension()==".rdlb"&&fs::file_size(file)<=(128ull<<20),"Canonical input file bound");
      auto next=std::make_unique<rdl::SceneContext>();next->setProxyModeEnabled(true);next->setDsoPath(argv[1]);rdl::readSceneFromFile(file.string(),*next);
      if(!canonical)canonical=std::make_unique<CanonicalSession>(argv[1],Epoch{current.session,0,0,0});
      staged=canonical->prepare(*next,folder,current);auto plan=cpu::prepare(*canonical,staged,prior,cpu::Limits{},assets,domain);
      cpu::need(canonical->acknowledge(staged)&&canonical->publish(staged),"Canonical publication failed");staged.reset();context=std::move(next);prior=plan;
      if(inbox.latest.load()!=active)continue;
      cpu::need(service.request(plan,threads,ticket,fault==2?0:fault,0,0,window,refill,publish),"Native request queue full");crashRequest=fault==2?active:0;
     }catch(const std::exception& e){
      if(staged)canonical->reject(staged);
      held=std::make_unique<Wire>();held->meta["kind"]="error";held->meta["id"]=Json::UInt64(active);held->meta["epoch"]=epochs(current);held->meta["error"]=e.what();held->meta["rgba_bytes"]=0;
     }
    }
   }
   if(active&&inbox.latest.load()!=active){service.cancel();active=0;held.reset();}
   if(active&&!held){if(auto p=service.poll()){
    if(p->ticket!=ticket||!(p->epoch==current))continue;
    held=std::make_unique<Wire>();auto& m=held->meta;m["id"]=Json::UInt64(active);m["epoch"]=epochs(p->epoch);m["rgba_bytes"]=0;
    if(!p->error.empty()){m["kind"]="error";m["error"]=p->error;}
    else{m["kind"]="frame";m["tier"]="D";m["qualified"]=false;m["final"]=p->final;m["width"]=prior->width;m["height"]=prior->height;m["min_spp"]=p->image.samples;m["windows"]=Json::UInt64(p->image.windows);m["pending_paths"]=Json::UInt64(p->image.pendingPaths);m["gpu_samples"]=Json::UInt64(p->image.gpuSamples);m["cpu_samples"]=Json::UInt64(p->image.cpuSamples);m["fine_refills"]=Json::UInt64(p->image.fineRefills);m["migrated_paths"]=Json::UInt64(p->image.migratedPaths);held->rgba=std::move(p->image.rgba);m["rgba_bytes"]=Json::UInt64(held->rgba.size()*4);}
   }}
   if(held){bool final=held->meta["kind"]=="error"||held->meta["final"].asBool();if(outbox.push(held)){if(crashRequest==active)std::_Exit(42);if(final)active=0;}else if(!final)held.reset();}
   if(service.closed())break;
   std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  service.close();service.join();outbox.close();reader.join();return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
