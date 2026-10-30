#include "deadline_pipeline.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool v,const char* why){if(!v)throw std::runtime_error(why);}
template<class F>static void wait(F f){auto end=resume::Clock::now()+std::chrono::seconds(120);while(!f()){check(resume::Clock::now()<end,"Deadline test timeout");std::this_thread::yield();}}
static void write(fs::path path,const mixed::Run& r){std::ofstream out(path,std::ios::binary);out.write((const char*)r.rgba.data(),r.rgba.size()*4);check(bool(out),"Image write");}
int main(int argc,char** argv){try{
 check(argc==6,"scene runtime ptx output assets required");fs::path out(argv[4]);std::ifstream in(argv[3]);std::string ptx((std::istreambuf_iterator<char>(in)),{});
 rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);CanonicalSession canonical(argv[2],{801,0,0,0});auto frame=canonical.prepare(source,out/"canonical",{801,1,1,1});auto plan=cpu::prepare(canonical,frame,{},cpu::Limits{},argv[5]);check(canonical.acknowledge(frame)&&canonical.publish(frame),"Publication");auto accel=cpu::acceleration(plan);auto epoch=mixed::config(plan).epoch;
 gpu::Lane lane(ptx);auto scene=lane.prepare(plan);wait([&]{return scene->ready();});lane.collect(scene);mixed::CpuPool pool;Json::Value report;bool textured=!plan->diffuseMaps.empty()||!plan->emissionMaps.empty();
 auto oracle=mixed::render(plan,accel,lane,scene,1,0,1);write(out/"uninterrupted.rgba",oracle);
 auto allocation=lane.driver.allocations,sync=uint64_t(lane.driver.synchronizations);uint64_t ticket=10;
 auto pollOnly=[&](resume::Session& s){auto expired=resume::Clock::now()-std::chrono::seconds(1);s.tick(epoch,expired,expired);};
 auto singleStep=[&](resume::Session& s){auto end=resume::Clock::now()+std::chrono::seconds(1);s.tick(epoch,end,end,1);wait([&]{pollOnly(s);return !s.busy();});};
 auto finish=[&](resume::Session& s){unsigned frames=0;wait([&]{
   auto begin=resume::Clock::now();auto end=begin+std::chrono::milliseconds(2);auto cutoff=begin+std::chrono::microseconds(1600);s.frame();++frames;
   while(resume::Clock::now()<end&&!s.done()&&!s.failed()){s.tick(epoch,cutoff,end,64);std::this_thread::yield();}
   pollOnly(s);check(!s.failed(),"Resumed epoch failed");return s.done();
  });s.drain();return frames;};
 for(unsigned threads:{1u,12u}){
  resume::Session s(plan,accel,lane,scene,pool,threads,0,++ticket);for(unsigned i=0;i<3;++i)singleStep(s);
  auto before=s.audit();auto states=s.phases();check(states[resume::Shadow]>0&&before.pending>0,"No suspended CPU shadow paths");auto paused=s.snapshot();for(auto& p:paused.raw)if(p.pad==resume::Shadow){check(p.count==0,"Unfinished sample committed");for(double c:p.sum)check(c==0,"Pending contribution reached film");}
  std::this_thread::sleep_for(std::chrono::milliseconds(5));pollOnly(s);check(s.audit().started==before.started&&s.audit().completed==before.completed,"Paused work advanced without grant");
  unsigned frames=finish(s);auto image=s.snapshot();check(image.rgba==oracle.rgba,"CPU resumption changes pixels");write(out/("cpu"+std::to_string(threads)+".rgba"),image);auto a=s.audit();check(a.pending==0&&a.completed==uint64_t(plan->width)*plan->height*plan->spp&&a.started==a.completed,"CPU sample audit");report["cpu"+std::to_string(threads)]["windows"]=frames;report["cpu"+std::to_string(threads)]["slices"]=Json::UInt64(a.slices);report["cpu"+std::to_string(threads)]["completed"]=Json::UInt64(a.completed);
 }
 if(!textured)for(int mode:{1,2}){
  resume::Session s(plan,accel,lane,scene,pool,12,mode,++ticket);for(unsigned i=0;i<3;++i)singleStep(s);check(s.phases()[resume::Shadow]>0&&s.audit().pending>0,"No suspended GPU/mixed paths");auto held=lane.held();check(held>0&&!lane.busy(),"GPU state not retained while paused");
  bool collectRejected=false;try{lane.collect(scene);}catch(...){collectRejected=true;}check(collectRejected,"Paused GPU scenes retired");
  auto frames=finish(s);auto image=s.snapshot();check(image.rgba==oracle.rgba,"GPU resumption changes pixels");write(out/(mode==1?"gpu.rgba":"mixed.rgba"),image);auto a=s.audit();check(a.pending==0&&a.completed==uint64_t(plan->width)*plan->height*plan->spp&&lane.held()==0,"GPU sample audit");std::string key=mode==1?"gpu":"mixed";report[key]["windows"]=frames;report[key]["slices"]=Json::UInt64(a.slices);report[key]["completed"]=Json::UInt64(a.completed);report[key]["peak_gpu_slots"]=a.peakGpuHeld;report[key]["peak_cpu_jobs"]=a.peakCpuHeld;
 }
 // Change the epoch while a real path and its pending shadow are parked. None of
 // that epoch's completed or incomplete samples may survive in the next image.
 {resume::Session s(plan,accel,lane,scene,pool,12,textured?0:2,++ticket);for(unsigned i=0;i<3;++i)singleStep(s);auto before=s.audit();auto changed=epoch;++changed.camera;auto end=resume::Clock::now()+std::chrono::seconds(1);s.tick(changed,end,end);s.drain();check(s.cancelled()&&!s.failed()&&s.snapshot().rgba.empty()&&s.audit().invalidated==before.started&&lane.held()==0,"Epoch invalidation lost suspended work");report["changed_epoch_invalidated_samples"]=Json::UInt64(s.audit().invalidated);}
 // Cancel while slices execute; collect ownership before releasing device memory.
 {resume::Session s(plan,accel,lane,scene,pool,12,textured?0:2,++ticket);auto end=resume::Clock::now()+std::chrono::seconds(1);s.tick(epoch,end,end,32);s.cancel();s.drain();check(s.snapshot().rgba.empty()&&pool.counts().outstanding==0&&lane.held()==0,"Active cancellation ownership");report["active_cancel_invalidated_samples"]=Json::UInt64(s.audit().invalidated);}
 if(!textured){resume::Session s(plan,accel,lane,scene,pool,12,2,++ticket,1);auto end=resume::Clock::now()+std::chrono::seconds(1);s.tick(epoch,end,end);wait([&]{pollOnly(s);return s.failed();});s.drain();check(s.snapshot().rgba.empty()&&lane.held()==0,"Malformed slice exposed pixels");report["malformed_slice_rejected"]=true;}
 {resume::Session s(plan,accel,lane,scene,pool,12,textured?0:2,++ticket);finish(s);check(s.snapshot().rgba==oracle.rgba,"Recovery changed image");report["recovery_exact"]=true;}
 check(lane.driver.allocations==allocation&&lane.driver.synchronizations==sync,"Per-slice GPU allocation or synchronization");check(pool.counts().created==12&&pool.counts().joined==0&&pool.counts().submitted==pool.counts().collected,"Pool not retained");pool.close();check(pool.counts().joined==12,"Pool shutdown");
 report["state_bytes_per_path"]=unsigned(sizeof(resume::State));report["batch_bytes"]=unsigned(sizeof(resume::Batch));report["gpu_resident_batches"]=4;report["cpu_batch_cap"]=24;report["no_per_slice_gpu_allocation_or_sync"]=true;report["status"]="passed";Json::StreamWriterBuilder writer;writer["indentation"]="";std::cout<<Json::writeString(writer,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
