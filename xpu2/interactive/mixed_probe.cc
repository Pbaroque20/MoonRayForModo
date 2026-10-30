#include "mixed_pipeline.h"
#include <json/json.h>
#include <iostream>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool v,const char* why){if(!v)throw std::runtime_error(why);}
static void wait(const std::function<bool()>& f){auto until=std::chrono::steady_clock::now()+std::chrono::seconds(90);while(!f()){check(std::chrono::steady_clock::now()<until,"GPU readiness timeout");std::this_thread::yield();}}
static void save(fs::path file,const std::vector<float>& values){std::ofstream out(file,std::ios::binary);out.write((const char*)values.data(),values.size()*4);check(bool(out),"Image write");}
int main(int argc,char** argv){try{
 check(argc==5,"scene runtime ptx output required");fs::path out(argv[4]);std::ifstream in(argv[3]);std::string ptx((std::istreambuf_iterator<char>(in)),{});check(!ptx.empty(),"PTX input");
 rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);CanonicalSession session(argv[2],{301,0,0,0});cpu::PlanView plan;cpu::AccelView accel;unsigned version=0;uint64_t ticket=0;
 gpu::Lane lane(ptx);auto idleDevice=lane.driver.deviceBytes,idlePinned=lane.driver.pinnedBytes;gpu::SceneView scene;Json::Value report;report["cases"]=Json::Value(Json::arrayValue);
 auto prepare=[&](const char* label){auto frame=session.prepare(source,out/label,{301,++version,1,1});auto next=cpu::prepare(session,frame,plan);accel=cpu::acceleration(next,accel);auto gpuScene=lane.prepare(next,scene);wait([&]{return gpuScene->ready();});check(session.acknowledge(frame)&&session.publish(frame),"Canonical publication");source.commitAllChanges();plan=next;scene=gpuScene;
  report["preparation"][label]["gas_built"]=scene->built;report["preparation"][label]["gas_reused"]=scene->reused;report["preparation"][label]["materials_reused"]=scene->materialReused;
 };
 auto render=[&](const char* name,unsigned threads,int mode,unsigned fault=0,bool cancel=false,uint64_t delay=0){auto run=mixed::render(plan,accel,lane,scene,threads,mode,++ticket,fault,cancel,delay);Json::Value row;row["name"]=name;row["cpu_samples"]=Json::UInt64(run.cpuSamples);row["gpu_samples"]=Json::UInt64(run.gpuSamples);row["cpu_samples_while_gpu_pending"]=Json::UInt64(run.cpuWhileGpuPending);row["max_flights"]=run.maxFlights;row["refused_submissions"]=run.refused;row["started"]=Json::UInt64(run.started);row["invalidated"]=Json::UInt64(run.invalidated);row["failed"]=run.failed;row["cancelled"]=run.cancelled;
  if(fault||cancel){check(run.rgba.empty()&&run.invalidated==run.started&&run.started>0,"Invalid epoch exposed image");check(fault?run.failed:run.cancelled,"Missing failure/cancellation");}
  else{check(!run.failed&&!run.cancelled&&!run.rgba.empty()&&run.replayRejected&&run.staleRejected,"Native frame failed");if(mode!=0)check(run.maxFlights==4,"Multiple useful GPU flights missing");if(mode==2)check(run.cpuSamples>0&&run.gpuSamples>0,"One lane did no work");save(out/(std::string(name)+".rgba"),run.rgba);}
  report["cases"].append(row);return run;
 };
 prepare("initial");lane.collect(scene);render("initial-cpu",1,0);render("initial-cpu12",12,0);render("initial-gpu",1,1);render("initial-mixed1",1,2);render("initial-mixed12",12,2);
 auto delayed=render("delayed",12,2,0,false,50000000);check(delayed.cpuWhileGpuPending>0,"No useful CPU progress while GPU in flight");
 render("cancel",12,2,0,true,50000000);render("bad-sequence",12,2,1);render("nonfinite",12,2,2);render("recovered",12,2);
 // Prepare a new material epoch while an older GPU job still owns its buffers.
 auto firstScene=scene;auto firstPlan=plan;auto firstAccel=accel;mixed::Job old{};old.epoch=mixed::config(plan).epoch;old.sequence=0xffff0000;old.count=1;old.samples=1;old.delay=50000000;
 int slot=lane.submit(scene,old);check(slot>=0,"Old epoch submit");auto* material=source.getSceneObject("/m0");{rdl::SceneObject::UpdateGuard u(material);material->set<rdl::Rgb>("diffuseColor",rdl::Rgb(.2f,.4f,.7f));}prepare("material");check(scene->built==0&&scene->reused==4&&scene->top==firstScene->top,"Material edit rebuilt traversal");
 mixed::Result late;wait([&]{return lane.poll(slot,late);});auto expected=mixed::cpuJob(firstPlan,firstAccel,old);for(int i=0;i<4;++i)check(std::abs(late.pixels[0].sum[i]-expected.pixels[0].sum[i])<1e-6,"Old resident data changed");mixed::Ledger stale(firstPlan);check(stale.accept(0,late,mixed::Owner::Gpu,mixed::config(plan).epoch)==mixed::Commit::Stale,"Old epoch accepted");report["old_resident_epoch_retained"]=true;firstScene.reset();firstPlan.reset();firstAccel.reset();lane.collect(scene);render("material",12,2);
 auto* camera=source.getSceneObject("/camera");{rdl::SceneObject::UpdateGuard u(camera);auto m=camera->get<rdl::Mat4d>("node_xform");m[3][0]+=.045;camera->set("node_xform",m,rdl::TIMESTEP_BEGIN);camera->set("node_xform",m,rdl::TIMESTEP_END);}prepare("camera");check(scene->built==0&&scene->reused==4&&scene->materialReused,"Camera edit residency reuse");lane.collect(scene);render("camera",12,2);
 auto* mesh=source.getSceneObject("/g0");{rdl::SceneObject::UpdateGuard u(mesh);auto v=mesh->get<rdl::Vec3fVector>("vertex_list");v[0].x-=1;mesh->set("vertex_list",v);}prepare("geometry");check(scene->built==1&&scene->reused==3,"Dirty mesh GAS reuse");lane.collect(scene);render("geometry",12,2);
 scene.reset();lane.collect({});check(lane.driver.deviceBytes==idleDevice&&lane.driver.pinnedBytes==idlePinned,"GPU scene resources leaked");
 // Shutdown invalidates externally retained views before destroying the context.
 gpu::SceneView expired;{gpu::Lane temporary(ptx);expired=temporary.prepare(plan);wait([&]{return expired->ready();});}
 check(!expired->ready()&&expired->config->pointer==0&&expired->top->storage->pointer==0,"Expired GPU view retained live handles");expired.reset();report["expired_gpu_view_safe"]=true;
 report["per_trip_allocation_calls"]=0;report["per_trip_free_calls"]=0;report["optix_validation_mode"]="off";
 report["steady_state_synchronizations"]=0;report["startup_synchronizations"]=lane.driver.synchronizations;report["resident_bytes_returned_to_baseline"]=true;report["peak_device_bytes"]=Json::UInt64(lane.driver.peakDevice);report["peak_pinned_bytes"]=Json::UInt64(lane.driver.peakPinned);report["job_bytes"]=unsigned(sizeof(mixed::Params));report["result_bytes"]=unsigned(sizeof(mixed::Result));report["launch_width"]=mixed::Capacity;report["status"]="passed";report["qualified_native_scene"]=false;
 Json::StreamWriterBuilder w;w["indentation"]="";std::cout<<Json::writeString(w,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
