#include "mixed_service.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
template<class F>static void wait(F f){auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(90);while(!f()){check(std::chrono::steady_clock::now()<deadline,"Progressive timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
static void write(fs::path f,const mixed::Run& run){std::ofstream out(f,std::ios::binary);out.write((const char*)run.rgba.data(),run.rgba.size()*4);check(bool(out),"Image write");}
int main(int argc,char** argv){try{
 check(argc==6,"scene runtime ptx output assetroot required");fs::path folder(argv[4]),assets(argv[5]);std::ifstream pt(argv[3]);std::string ptx((std::istreambuf_iterator<char>(pt)),{});check(!ptx.empty(),"Missing PTX");
 rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);
 CanonicalSession session(argv[2],{501,0,0,0});auto frame=session.prepare(source,folder/"canonical",{501,1,1,1});auto plan=cpu::prepare(session,frame,{},cpu::Limits{},assets);check(session.acknowledge(frame)&&session.publish(frame),"Canonical publication");
 Json::Value report;bool textured=!plan->diffuseMaps.empty()||!plan->emissionMaps.empty();auto accel=cpu::acceleration(plan);
 {gpu::Lane lane(ptx);auto gpu=lane.prepare(plan);wait([&]{return gpu->ready();});lane.collect(gpu);
  for(unsigned threads:{1u,12u}){auto run=mixed::render(plan,accel,lane,gpu,threads,0,threads);check(!run.failed,"CPU material job");write(folder/("cpu"+std::to_string(threads)+".rgba"),run);}
  auto run=mixed::render(plan,accel,lane,gpu,12,2,20);check(!run.failed,"Mixed material job");write(folder/"mixed.rgba",run);
  report["cpu_samples"]=Json::UInt64(run.cpuSamples);report["gpu_samples"]=Json::UInt64(run.gpuSamples);report["textured_cpu_route"]=run.cpuTextureRoute;
  std::atomic<uint64_t> generation{40},submitted{0};
  auto cancelled=mixed::progressive(plan,accel,lane,gpu,12,2,40,16,[&](const mixed::Run& partial){check(partial.samples==16,"Cancellation boundary");generation.store(41);},0,0,&generation,nullptr,&submitted);
  check(cancelled.cancelled&&cancelled.rgba.empty()&&cancelled.raw.empty()&&cancelled.started==uint64_t(plan->width)*plan->height*16&&cancelled.invalidated==cancelled.started&&cancelled.cpuSamples+cancelled.gpuSamples==cancelled.started&&submitted.load()==cancelled.started,"Prior progressive samples omitted from cancellation audit");report["cancelled_prefix_audit"]=true;
  if(textured){check(run.cpuTextureRoute&&run.gpuSamples==0,"Texture escaped CPU route");mixed::Job job{};job.epoch=mixed::config(plan).epoch;job.count=1;job.samples=1;job.sequence=42;bool rejected=false;try{lane.submit(gpu,job);}catch(...){rejected=true;}check(rejected,"Unqualified GPU texture accepted");report["gpu_texture_rejected"]=true;
   const auto& maps=plan->diffuseMaps.empty()?plan->emissionMaps:plan->diffuseMaps;auto file=maps.begin()->second.file;auto path=fs::path(file->name.string());HANDLE h=CreateFileW(path.c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);bool protectedFile=h==INVALID_HANDLE_VALUE;if(!protectedFile)CloseHandle(h);check(protectedFile,"Frozen texture writable during render");report["texture_read_lease"]=true;report["stored_mip_levels"]=file->levels;
   bool noRoot=false;try{cpu::prepare(source,frame);}catch(...){noRoot=true;}check(noRoot,"Texture admission without root");report["missing_asset_admission_rejected"]=true;
   auto retained=cpu::prepare(source,frame,plan,cpu::Limits{},assets);auto& retainedMaps=retained->diffuseMaps.empty()?retained->emissionMaps:retained->diffuseMaps;check(retainedMaps.begin()->second.file==file,"Host texture cache not reused");report["host_texture_cache_reused"]=true;
  }
 }
 mixed::Service service(ptx);uint64_t ticket=0;check(service.request(plan,12,ticket,0,0,16),"Progressive request");
 // Intentionally do not consume previews: the output queue must skip snapshots,
 // retain every sample, and eventually deliver a complete image after draining.
 wait([&]{check(!service.closed(),"Service failure");return service.counts().progressiveSkipped>0;});
 unsigned previous=0,partials=0;bool done=false;
 wait([&]{auto packet=service.poll();if(!packet)return false;check(packet->ticket==ticket&&packet->epoch==frame->routing->epoch&&packet->error.empty()&&!packet->qualified&&packet->tier=='D',"Progressive identity");check(packet->image.samples>previous&&packet->image.samples<=plan->spp,"Progressive monotonic samples");previous=packet->image.samples;
  for(auto& p:packet->image.raw)check(p.count==previous,"Per-pixel progressive sample count");
  if(packet->final){check(previous==plan->spp,"Incomplete final");write(folder/"progressive.rgba",packet->image);done=true;}
  else{++partials;check(previous<plan->spp,"Partial labelled complete");write(folder/("partial-"+std::to_string(previous)+".rgba"),packet->image);}return done;});
 check(partials>=1,"No early image");report["partial_images_consumed"]=partials;report["final_samples_per_pixel"]=previous;
 // Cancel after publishing an actual early image, then recover with a new ticket.
 check(service.request(plan,12,ticket,0,0,1),"Cancellation request");wait([&]{auto p=service.poll();if(!p)return false;check(!p->final,"No progressive cancellation window");return true;});service.cancel();check(!service.poll(),"Cancelled preview surfaced");
 check(service.request(plan,12,ticket,0,0,32),"Recovery request");wait([&]{auto p=service.poll();if(!p)return false;check(p->ticket==ticket&&p->error.empty(),"Old or failed recovery");if(p->final){write(folder/"recovered.rgba",p->image);return true;}return false;});
 if(!textured){
  check(service.request(plan,12,ticket,3,0,16),"Late failure request");wait([&]{return service.counts().failed==1;});
  wait([&]{auto p=service.poll();if(!p)return false;check(p->ticket==ticket&&p->final&&!p->error.empty()&&p->image.rgba.empty(),"Invalid progressive epoch surfaced");return true;});
  check(service.request(plan,12,ticket,0,0,32),"Post-failure recovery request");wait([&]{auto p=service.poll();if(!p)return false;check(p->error.empty(),"Post-failure recovery error");if(p->final){write(folder/"post-failure.rgba",p->image);return true;}return false;});report["failure_after_partial_retired"]=true;
 }
 wait([&]{auto c=service.counts();return c.cpuWorkersCreated==12&&c.cpuParked==12;});
 auto idle=service.counts();check(idle.cpuWorkersJoined==0&&idle.cpuJobsSubmitted==idle.cpuJobsCollected&&idle.cpuPeakOutstanding<=24,"Persistent worker idle audit");
 service.join();check(service.closed(),"Shutdown");auto c=service.counts();
 check(c.cpuWorkersCreated==12&&c.cpuWorkersJoined==12&&c.cpuJobsDiscarded==0&&c.cpuJobsSubmitted==c.cpuJobsCollected&&c.cpuPasses>16,"Workers recreated, leaked or jobs lost");report["persistent_cpu_workers"]=Json::UInt64(c.cpuWorkersCreated);report["cpu_worker_joins_at_shutdown"]=Json::UInt64(c.cpuWorkersJoined);report["cpu_jobs_submitted"]=Json::UInt64(c.cpuJobsSubmitted);report["cpu_jobs_collected"]=Json::UInt64(c.cpuJobsCollected);report["cpu_passes"]=Json::UInt64(c.cpuPasses);report["cpu_peak_outstanding"]=c.cpuPeakOutstanding;report["idle_workers_parked"]=idle.cpuParked;report["progressive_published"]=Json::UInt64(c.progressivePublished);report["progressive_snapshots_skipped"]=Json::UInt64(c.progressiveSkipped);report["cancelled_runs"]=Json::UInt64(c.cancelled);report["discarded_packets"]=Json::UInt64(c.discarded);report["status"]="passed";
 Json::StreamWriterBuilder b;b["indentation"]="";std::cout<<Json::writeString(b,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
