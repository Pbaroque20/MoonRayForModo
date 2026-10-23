// Private timing harness; unchanged prototype renderWindows path, no Modo API.
#include "deadline_pipeline.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
using Clock=std::chrono::steady_clock;
static double seconds(Clock::time_point start){return std::chrono::duration<double>(Clock::now()-start).count();}
static void raw(fs::path path,const mixed::Run& image){std::ofstream o(path,std::ios::binary);o.write((const char*)image.rgba.data(),image.rgba.size()*sizeof(float));cpu::need(bool(o),"Image write");}
namespace xpu2::interactive::resume {
template<class Publish>inline mixed::Run renderModeWindows(cpu::PlanView plan,cpu::AccelView accel,gpu::Lane& lane,gpu::SceneView scene,mixed::CpuPool& pool,unsigned threads,uint64_t ticket,unsigned windowMs,Publish publish,unsigned fault=0,const std::atomic<uint64_t>* generation=nullptr,const std::atomic<bool>* closing=nullptr,std::atomic<uint64_t>* submitted=nullptr,unsigned publishEveryMs=0,int mode=2){
 cpu::need(windowMs>0&&windowMs<=100,"Trace window budget");Session session(plan,accel,lane,scene,pool,threads,mode,ticket,fault);auto epoch=mixed::config(plan).epoch;auto limit=Clock::now()+std::chrono::seconds(120);uint64_t published=0;auto nextPublish=Clock::now();cpu::need(publishEveryMs<=1000,"Publish interval budget");
 while(!session.done()&&!session.cancelled()){
  cpu::need(Clock::now()<limit,"Deadline renderer timeout");session.frame();auto begin=Clock::now();auto end=begin+std::chrono::milliseconds(windowMs);auto cutoff=begin+std::chrono::microseconds(windowMs*800);
  do{
   if((generation&&generation->load(std::memory_order_acquire)!=ticket)||(closing&&closing->load(std::memory_order_acquire)))session.cancel();
   session.tick(epoch,cutoff,end);if(session.done()||session.cancelled())break;std::this_thread::yield();
  }while(Clock::now()<end);
  auto a=session.audit();if(submitted)submitted->store(a.started,std::memory_order_release);
  if(!session.done()&&!session.cancelled()&&a.completed>published&&Clock::now()>=nextPublish){publish(session.snapshot());published=a.completed;nextPublish=Clock::now()+std::chrono::milliseconds(publishEveryMs);}
 }
 session.drain();auto image=session.snapshot();if(submitted)submitted->store(image.cancelled?image.invalidated:image.started,std::memory_order_release);return image;
}
}
int main(int argc,char** argv){try{
 cpu::need(argc>=8&&argc<=13,"scene runtime ptx assets output threads repeats");
 auto began=Clock::now();fs::path out(argv[5]);unsigned threads=unsigned(std::stoul(argv[6])),repeats=unsigned(std::stoul(argv[7]));cpu::need((threads==1||threads==12)&&repeats>0&&repeats<=8,"Benchmark bounds");
 std::ifstream file(argv[3]);cpu::need(bool(file),"PTX read");std::string ptx((std::istreambuf_iterator<char>(file)),{});
 auto readStart=Clock::now();rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);double readSeconds=seconds(readStart);
 auto indexStart=Clock::now();CanonicalSession canonical(argv[2],{3301,0,0,0});auto frame=canonical.prepare(source,out/"canonical",{3301,1,1,1});
 auto plan=cpu::prepare(canonical,frame,{},cpu::Limits{},argv[4],cpu::Domain::SurfaceTextures);auto chosen=std::make_shared<cpu::Plan>(*plan);if(argc>=9)chosen->sampling=unsigned(std::stoul(argv[8]));if(argc>=10)chosen->seed=unsigned(std::stoul(argv[9]));cpu::need(chosen->sampling<=3,"Sampling policy");plan=chosen;cpu::need(canonical.acknowledge(frame)&&canonical.publish(frame),"Canonical publish");double indexSeconds=seconds(indexStart);
 auto accelStart=Clock::now();auto accel=cpu::acceleration(plan);double accelSeconds=seconds(accelStart);
 auto gpuStart=Clock::now();gpu::Lane lane(ptx);gpu::TextureOptions options;bool refill=argc>=11&&std::stoul(argv[10])!=0;unsigned publishMs=argc>=12?unsigned(std::stoul(argv[11])):0;if(refill){options.texelBudget=64ull<<20;options.refillFine=true;}auto scene=lane.prepare(plan,{},options);auto limit=Clock::now()+std::chrono::seconds(120);while(!scene->ready()){cpu::need(Clock::now()<limit,"Scene timeout");std::this_thread::yield();}lane.collect(scene);double gpuSeconds=seconds(gpuStart);mixed::CpuPool pool;
 Json::Value report;report["width"]=plan->width;report["height"]=plan->height;report["spp"]=plan->spp;report["threads"]=threads;report["sampling_policy"]=plan->sampling;report["seed"]=plan->seed;report["read_seconds"]=readSeconds;report["canonical_and_plan_seconds"]=indexSeconds;report["embree_seconds"]=accelSeconds;report["gpu_prepare_seconds"]=gpuSeconds;report["prepare_seconds"]=seconds(began);report["window_ms"]=2;report["refill_fine"]=refill;report["publish_ms"]=publishMs;report["mode"]="unchanged progressive renderWindows; no custom throughput implementation";
 auto allocations=uint64_t(lane.driver.allocations),sync=uint64_t(lane.driver.synchronizations);
 for(unsigned i=0;i<repeats;++i){
  auto beforeAlloc=lane.driver.allocations;auto start=Clock::now();double first=-1,coverage=-1;uint64_t previews=0;
  auto image=resume::renderModeWindows(plan,accel,lane,scene,pool,threads,100+i,2,[&](const mixed::Run& preview){++previews;if(first<0)first=seconds(start);if(coverage<0&&preview.samples>0)coverage=seconds(start);},0,nullptr,nullptr,nullptr,publishMs,argc>=13?std::stoi(argv[12]):2);
  double elapsed=seconds(start);if(first<0)first=elapsed;if(coverage<0)coverage=elapsed;
  cpu::need(!image.failed&&!image.cancelled&&image.pendingPaths==0&&image.samples==plan->spp,"Incomplete timed image");
  cpu::need(image.cpuSamples+image.gpuSamples==uint64_t(plan->width)*plan->height*plan->spp,"Sample accounting");
  cpu::need(argc>=13&&std::stoi(argv[12])==0||image.gpuSamples>0,"No samples completed on GPU");
  Json::Value row;row["index"]=i;row["fine_refills"]=Json::UInt64(image.fineRefills);row["gpu_texture_retries"]=Json::UInt64(image.gpuTextureRetries);row["texture_misses_to_cpu"]=Json::UInt64(image.textureMisses);row["migrated_paths"]=Json::UInt64(image.migratedPaths);row["render_allocations"]=Json::UInt64(lane.driver.allocations-beforeAlloc);row["sampling_seconds"]=elapsed;row["first_partial_seconds"]=first;row["first_full_coverage_seconds"]=coverage;row["previews"]=Json::UInt64(previews);row["windows"]=Json::UInt64(image.windows);row["cpu_committed_samples"]=Json::UInt64(image.cpuSamples);row["gpu_committed_samples"]=Json::UInt64(image.gpuSamples);row["pending_paths"]=Json::UInt64(image.pendingPaths);row["raw_file"]=(out/("run-"+std::to_string(i)+".rgba")).string();report["runs"].append(row);raw(out/("run-"+std::to_string(i)+".rgba"),image);
 }
 report["steady_gpu_allocations"]=Json::UInt64(uint64_t(lane.driver.allocations)-allocations);report["steady_gpu_synchronizations"]=Json::UInt64(uint64_t(lane.driver.synchronizations)-sync);auto active=scene->fineReplacement?scene->fineReplacement:scene;report["active_texture_bytes"]=Json::UInt64(active->textureBytes);report["active_missing_pages"]=Json::UInt64(active->missingTexturePages);report["peak_device_bytes"]=Json::UInt64(lane.driver.peakDevice);report["peak_pinned_bytes"]=Json::UInt64(lane.driver.peakPinned);report["resident_texture_bytes"]=Json::UInt64(scene->textureBytes);report["resident_texture_pages"]=Json::UInt64(scene->texturePages);pool.close();auto c=pool.counts();report["workers_created"]=Json::UInt64(c.created);report["workers_joined"]=Json::UInt64(c.joined);report["cpu_jobs_submitted"]=Json::UInt64(c.submitted);report["cpu_jobs_collected"]=Json::UInt64(c.collected);cpu::need(c.submitted==c.collected&&c.created==c.joined,"Outstanding CPU jobs");
 report["status"]="passed";Json::StreamWriterBuilder b;b["indentation"]="";std::cout<<Json::writeString(b,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
