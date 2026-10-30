#include "cpu_service.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
template<class F>static void wait(F f){auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(90);while(!f()){if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("Service timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
static void write(fs::path file,const cpu::Image& image){std::ofstream out(file,std::ios::binary);out.write((const char*)image.rgba.data(),image.rgba.size()*4);check(bool(out),"Image write failure");}
int main(int argc,char** argv){try{
 check(argc==4,"scene runtime output required");fs::path folder(argv[3]);Json::Value report;
 {SpscRing<uint64_t,4> ring;for(uint64_t i=0;i<4;++i){auto v=i;check(ring.tryPush(v),"Ring admission");}uint64_t rejected=77;check(!ring.tryPush(rejected)&&rejected==77,"Ring backpressure lost input");for(uint64_t i=0;i<4;++i){uint64_t value;check(ring.tryPop(value)&&value==i,"Ring order");}}
 {SpscRing<uint64_t,64> ring;std::atomic<bool> valid{true};std::thread producer([&]{for(uint64_t i=0;i<1000000;++i){auto value=i;while(!ring.tryPush(value))std::this_thread::yield();}});
  for(uint64_t i=0;i<1000000;++i){uint64_t v;while(!ring.tryPop(v))std::this_thread::yield();if(v!=i)valid.store(false);}producer.join();check(valid.load(),"Concurrent ring sequence mismatch");report["ring_handoffs"]=1000000;}
 rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);CanonicalSession session(argv[2],{201,0,0,0});cpu::PlanView plan;unsigned version=0;
 auto prepare=[&](const char* name){auto frame=session.prepare(source,folder/name,{201,++version,1,1});if(version==1){cpu::Limits tooLarge;tooLarge.bytes=SIZE_MAX;bool refused=false;try{cpu::prepare(session,frame,plan,tooLarge);}catch(const cpu::Unsupported&){refused=true;}check(refused,"Hard preparation limit bypass");report["hard_limit_rejected"]=true;}auto next=cpu::prepare(session,frame,plan);check(session.acknowledge(frame)&&session.publish(frame),"Canonical publication");source.commitAllChanges();plan=next;return next;};
 auto first=prepare("initial");cpu::Service service;uint64_t ticket;
 auto submit=[&](cpu::PlanView p,unsigned workers){wait([&]{return service.request(p,workers,ticket);});return ticket;};
 auto rendering=[&](uint64_t t){wait([&]{check(!service.closed(),"Service closed unexpectedly");return service.active()==t&&service.progress()>=16;});};
 auto result=[&](uint64_t t){cpu::PacketPtr packet;wait([&]{check(!service.closed(),"Service closed unexpectedly");packet=service.poll();if(packet)check(packet->ticket==t,"Obsolete output published");return bool(packet);});return packet;};
 auto t=submit(first,1);rendering(t);
 auto* material=source.getSceneObject("/m0");{rdl::SceneObject::UpdateGuard u(material);material->set<rdl::Rgb>("diffuseColor",rdl::Rgb(.2f,.4f,.7f));}
 auto second=prepare("material");for(int i=0;i<4;++i)t=submit(second,12);
 // Wait for publication without consuming it, then supersede that queued result.
 wait([&]{check(!service.closed(),"Service closed unexpectedly");return service.counts().published>0;});
 t=submit(second,12);auto image=result(t);
 check(image->error.empty()&&!image->qualified&&image->tier=='D'&&image->epoch==second->source->routing->epoch,"Invalid result tier or epoch");write(folder/"material.rgba",image->image);image.reset();
 check(service.counts().cancelled>0&&service.counts().discarded>0,"Superseded work not retired");report["scene_supersession"]=true;report["stale_completed_output_retired"]=true;
 bool stale=false;try{service.request(first,1,ticket);}catch(const cpu::Unsupported&){stale=true;}check(stale,"Stale epoch accepted");
 bool wrongThread=false;std::thread other([&]{try{service.poll();}catch(const std::logic_error&){wrongThread=true;}});other.join();check(wrongThread,"Second coordinator accepted");
 // Synthetic corrupt native plan: canonical state is valid and unaffected. This
 // checks propagation of a render-worker exception, not admission of that plan.
 auto valid=prepare("failure");auto broken=std::make_shared<cpu::Plan>(*valid);broken->materials.clear();t=submit(broken,12);auto error=result(t);check(!error->error.empty()&&error->image.rgba.empty(),"Worker error exposed pixels");report["worker_failure"]=error->error;error.reset();
 auto recovered=prepare("recovery");t=submit(recovered,12);auto again=result(t);check(again->error.empty(),"Recovery failed");write(folder/"recovered.rgba",again->image);again.reset();
 auto cancelled=service.counts().cancelled;t=submit(recovered,12);rendering(t);service.cancel();wait([&]{return service.active()==0&&service.counts().cancelled>cancelled;});check(!service.poll(),"Explicit cancel published pixels");
 t=submit(recovered,12);rendering(t);service.close();service.join();check(service.closed()&&service.active()==0&&!service.poll(),"Shutdown failed");
 bool closed=false;try{service.request(recovered,1,ticket);}catch(const cpu::Unsupported&){closed=true;}check(closed,"Closed service accepted request");
 auto counts=service.counts();report["counts"]["submitted"]=Json::UInt64(counts.submitted);report["counts"]["started"]=Json::UInt64(counts.started);report["counts"]["coalesced"]=Json::UInt64(counts.coalesced);report["counts"]["published"]=Json::UInt64(counts.published);report["counts"]["cancelled"]=Json::UInt64(counts.cancelled);report["counts"]["discarded"]=Json::UInt64(counts.discarded);report["counts"]["failed"]=Json::UInt64(counts.failed);report["counts"]["acceleration_reuses"]=Json::UInt64(counts.reusedAcceleration);
 check(counts.failed==1&&counts.cancelled>=3,"Unexpected service outcome counts");report["status"]="passed";report["qualified_native_scene"]=false;report["stale_epoch_rejected"]=true;report["coordinator_guard"]=true;report["cancellation_recovery_shutdown"]=true;
 Json::StreamWriterBuilder writer;writer["indentation"]="";std::cout<<Json::writeString(writer,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
