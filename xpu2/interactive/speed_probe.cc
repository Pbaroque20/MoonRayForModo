// Private timing harness; unchanged prototype renderWindows path, no Modo API.
#include "deadline_pipeline.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
using Clock=std::chrono::steady_clock;
static double seconds(Clock::time_point start){return std::chrono::duration<double>(Clock::now()-start).count();}
static void raw(fs::path path,const mixed::Run& image){std::ofstream o(path,std::ios::binary);o.write((const char*)image.rgba.data(),image.rgba.size()*sizeof(float));cpu::need(bool(o),"Image write");}
int main(int argc,char** argv){try{
 cpu::need(argc>=8&&argc<=10,"scene runtime ptx assets output threads repeats");
 auto began=Clock::now();fs::path out(argv[5]);unsigned threads=unsigned(std::stoul(argv[6])),repeats=unsigned(std::stoul(argv[7]));cpu::need((threads==1||threads==12)&&repeats>0&&repeats<=8,"Benchmark bounds");
 std::ifstream file(argv[3]);cpu::need(bool(file),"PTX read");std::string ptx((std::istreambuf_iterator<char>(file)),{});
 auto readStart=Clock::now();rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);double readSeconds=seconds(readStart);
 auto indexStart=Clock::now();CanonicalSession canonical(argv[2],{3301,0,0,0});auto frame=canonical.prepare(source,out/"canonical",{3301,1,1,1});
 auto plan=cpu::prepare(canonical,frame,{},cpu::Limits{},argv[4],cpu::Domain::SurfaceTextures);auto chosen=std::make_shared<cpu::Plan>(*plan);if(argc>=9)chosen->sampling=unsigned(std::stoul(argv[8]));if(argc>=10)chosen->seed=unsigned(std::stoul(argv[9]));cpu::need(chosen->sampling<=3,"Sampling policy");plan=chosen;cpu::need(canonical.acknowledge(frame)&&canonical.publish(frame),"Canonical publish");double indexSeconds=seconds(indexStart);
 auto accelStart=Clock::now();auto accel=cpu::acceleration(plan);double accelSeconds=seconds(accelStart);
 auto gpuStart=Clock::now();gpu::Lane lane(ptx);auto scene=lane.prepare(plan);auto limit=Clock::now()+std::chrono::seconds(120);while(!scene->ready()){cpu::need(Clock::now()<limit,"Scene timeout");std::this_thread::yield();}lane.collect(scene);double gpuSeconds=seconds(gpuStart);mixed::CpuPool pool;
 Json::Value report;report["width"]=plan->width;report["height"]=plan->height;report["spp"]=plan->spp;report["threads"]=threads;report["sampling_policy"]=plan->sampling;report["seed"]=plan->seed;report["read_seconds"]=readSeconds;report["canonical_and_plan_seconds"]=indexSeconds;report["embree_seconds"]=accelSeconds;report["gpu_prepare_seconds"]=gpuSeconds;report["prepare_seconds"]=seconds(began);report["window_ms"]=2;report["mode"]="unchanged progressive renderWindows; no custom throughput implementation";
 auto allocations=uint64_t(lane.driver.allocations),sync=uint64_t(lane.driver.synchronizations);
 for(unsigned i=0;i<repeats;++i){
  auto start=Clock::now();double first=-1,coverage=-1;uint64_t previews=0;
  auto image=resume::renderWindows(plan,accel,lane,scene,pool,threads,100+i,2,[&](const mixed::Run& preview){++previews;if(first<0)first=seconds(start);if(coverage<0&&preview.samples>0)coverage=seconds(start);});
  double elapsed=seconds(start);if(first<0)first=elapsed;if(coverage<0)coverage=elapsed;
  cpu::need(!image.failed&&!image.cancelled&&image.pendingPaths==0&&image.samples==plan->spp,"Incomplete timed image");
  cpu::need(image.cpuSamples+image.gpuSamples==uint64_t(plan->width)*plan->height*plan->spp,"Sample accounting");
  cpu::need(image.gpuSamples>0,"No samples completed on GPU");
  Json::Value row;row["index"]=i;row["sampling_seconds"]=elapsed;row["first_partial_seconds"]=first;row["first_full_coverage_seconds"]=coverage;row["previews"]=Json::UInt64(previews);row["windows"]=Json::UInt64(image.windows);row["cpu_committed_samples"]=Json::UInt64(image.cpuSamples);row["gpu_committed_samples"]=Json::UInt64(image.gpuSamples);row["pending_paths"]=Json::UInt64(image.pendingPaths);row["raw_file"]=(out/("run-"+std::to_string(i)+".rgba")).string();report["runs"].append(row);raw(out/("run-"+std::to_string(i)+".rgba"),image);
 }
 report["steady_gpu_allocations"]=Json::UInt64(uint64_t(lane.driver.allocations)-allocations);report["steady_gpu_synchronizations"]=Json::UInt64(uint64_t(lane.driver.synchronizations)-sync);report["resident_texture_bytes"]=Json::UInt64(scene->textureBytes);report["resident_texture_pages"]=Json::UInt64(scene->texturePages);pool.close();auto c=pool.counts();report["workers_created"]=Json::UInt64(c.created);report["workers_joined"]=Json::UInt64(c.joined);report["cpu_jobs_submitted"]=Json::UInt64(c.submitted);report["cpu_jobs_collected"]=Json::UInt64(c.collected);cpu::need(c.submitted==c.collected&&c.created==c.joined,"Outstanding CPU jobs");
 report["status"]="passed";Json::StreamWriterBuilder b;b["indentation"]="";std::cout<<Json::writeString(b,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
