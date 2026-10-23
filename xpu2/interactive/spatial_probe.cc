#include "deadline_pipeline.h"
#include <fstream>
#include <iostream>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool v,const char* why){if(!v)throw std::runtime_error(why);}
template<class F>static void wait(F f){auto end=resume::Clock::now()+std::chrono::seconds(120);while(!f()){check(resume::Clock::now()<end,"Spatial timeout");std::this_thread::yield();}}
static void write(fs::path path,const mixed::Run& r){std::ofstream out(path,std::ios::binary);out.write((const char*)r.rgba.data(),r.rgba.size()*4);check(bool(out),"Image write");}
static void chainCheck(){
 struct Backend {unsigned hits=0;resume::Hit trace(const surface::Ray&){resume::Hit h;h.geom=0;h.normal={0,0,1};++hits;return h;}
 bool material(const resume::Hit&,const surface::Ray&,surface::Lambert& m){m={{.5f,.5f,.5f},{1,1,1}};return true;}
 bool visible(surface::V3,surface::V3){return true;}} backend;
 mixed::Config c{};c.width=c.height=1;c.spatial=1;c.surfaceLimit=4;c.filter=surface::Filter::Box;c.filterWidth=1;c.sky={1,1,1};c.camera.nearClip=.001f;c.camera.farClip=100;
 for(int i=0;i<4;++i)c.camera.rasterToCamera.m[i][i]=c.camera.cameraToRender.m[i][i]=1;
 mixed::Job j{};j.count=j.samples=1;resume::State s;
 unsigned stages=0;while(s.phase<resume::Complete){check(++stages<64,"Unbounded chain");resume::step(s,j,c,backend);if(s.phase!=resume::Complete)check(s.film.count==0&&s.film.sum[0]==0,"Partial chain committed");}
 check(s.film.status==0&&s.film.count==1&&backend.hits==4&&s.film.sum[3]==1,"Chain accounting");check(std::abs(s.film.sum[0]-1.9375)<1e-6,"Lost/duplicated indirect contribution");
}
int main(int argc,char** argv){try{
 check(argc==5,"scene runtime ptx output required");chainCheck();fs::path out(argv[4]);std::ifstream in(argv[3]);std::string ptx((std::istreambuf_iterator<char>(in)),{});
 rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);CanonicalSession canonical(argv[2],{901,0,0,0});auto frame=canonical.prepare(source,out/"canonical",{901,1,1,1});auto plan=cpu::prepare(canonical,frame,{},cpu::Limits{},{},cpu::Domain::DiffuseMesh);Json::Value report;
 bool rejected=false;try{cpu::prepare(canonical,frame,plan);}catch(const cpu::Unsupported&){rejected=true;}check(rejected,"Spatial plan leaked into default domain");
 auto same=cpu::prepare(canonical,frame,plan,cpu::Limits{},{},cpu::Domain::DiffuseMesh);check(same->reusedMeshes==plan->meshes.size(),"Spatial immutable mesh reuse");check(canonical.acknowledge(frame)&&canonical.publish(frame),"Publication");auto accel=cpu::acceleration(plan);auto epoch=mixed::config(plan).epoch;
 gpu::Lane lane(ptx);auto scene=lane.prepare(plan);wait([&]{return scene->ready();});lane.collect(scene);mixed::CpuPool pool;
 auto cpu=mixed::render(plan,accel,lane,scene,1,0,1);write(out/"cpu.rgba",cpu);auto gpu=mixed::render(plan,accel,lane,scene,12,1,2);write(out/"gpu.rgba",gpu);
 auto allocations=lane.driver.allocations;auto sync=lane.driver.synchronizations;uint64_t ticket=10;
 auto pollOnly=[&](resume::Session& s){auto expired=resume::Clock::now()-std::chrono::seconds(1);s.tick(epoch,expired,expired);};
 auto one=[&](resume::Session& s){auto end=resume::Clock::now()+std::chrono::seconds(1);s.tick(epoch,end,end,1);wait([&]{pollOnly(s);return !s.busy();});};
 auto finish=[&](resume::Session& s){wait([&]{auto now=resume::Clock::now();s.frame();s.tick(epoch,now+std::chrono::milliseconds(2),now+std::chrono::milliseconds(3),64);check(!s.failed(),"Spatial epoch failed");return s.done();});s.drain();};
 for(int mode:{0,1,2}){for(unsigned threads:{1u,12u}){if(mode==1&&threads==1)continue;
  resume::Session s(plan,accel,lane,scene,pool,threads,mode,++ticket);for(unsigned i=0;i<3;++i)one(s);
  auto a=s.audit();check(a.pending>0&&a.completed==0,"No pending primary shading");auto image=s.snapshot();for(const auto& v:image.raw)for(auto x:v.sum)check(x==0,"Incomplete sample in film");
  if(plan->surfaceLimit>1)check(s.phases()[resume::Trace]>0,"No parked secondary paths");
  auto before=a.started;pollOnly(s);check(s.audit().started==before,"Expired tick started work");finish(s);image=s.snapshot();
  for(unsigned pix=0;pix<plan->width*plan->height;++pix){bool onGpu=mode==1||(mode==2&&((pix%plan->width/8+pix/plan->width/8)&1));const auto& expected=onGpu?gpu:cpu;for(int c=0;c<4;++c)check(image.rgba[pix*4+c]==expected.rgba[pix*4+c],"Resumption or checkerboard changes device result");}
  a=s.audit();check(a.pending==0&&a.started==a.completed&&a.completed==uint64_t(plan->width)*plan->height*plan->spp,"Multi-bounce sample count");
  std::string key="mode"+std::to_string(mode)+"-t"+std::to_string(threads);write(out/(key+".rgba"),image);report[key]["slices"]=Json::UInt64(a.slices);report[key]["completed"]=Json::UInt64(a.completed);report[key]["cpu_samples"]=Json::UInt64(image.cpuSamples);report[key]["gpu_samples"]=Json::UInt64(image.gpuSamples);
 }}
 {resume::Session s(plan,accel,lane,scene,pool,12,2,++ticket);for(unsigned i=0;i<3;++i)one(s);auto changed=epoch;++changed.scene;auto end=resume::Clock::now()+std::chrono::seconds(1);s.tick(changed,end,end);s.drain();check(s.cancelled()&&s.snapshot().rgba.empty()&&!lane.held()&&!pool.counts().outstanding,"Stale secondary paths survived");report["secondary_epoch_cancel"]=true;}
 for(unsigned fault:{1u,2u}){resume::Session s(plan,accel,lane,scene,pool,12,2,++ticket,fault);wait([&]{auto end=resume::Clock::now()+std::chrono::seconds(1);s.tick(epoch,end,end);return s.failed();});s.drain();check(s.snapshot().rgba.empty()&&!lane.held(),"Bad result published");}
 {resume::Session s(plan,accel,lane,scene,pool,12,1,++ticket);finish(s);check(s.snapshot().rgba==gpu.rgba,"Spatial GPU recovery failed");}
 // Invalid settings must be refused, never silently approximated by native shading.
 auto reject=[&](const char* label,auto mutate,auto restore){mutate();bool no=false;try{cpu::prepare(source,frame,{},cpu::Limits{},{},cpu::Domain::DiffuseMesh);}catch(const cpu::Unsupported&){no=true;}restore();check(no,label);report["rejected"][label]=true;};
 auto* mesh=source.getSceneObject("/g0");reject("smooth normals",[&]{rdl::SceneObject::UpdateGuard g(mesh);mesh->set<rdl::Bool>("smooth_normal",true);},[&]{rdl::SceneObject::UpdateGuard g(mesh);mesh->set<rdl::Bool>("smooth_normal",false);});
 auto& sv=source.getSceneVariables();auto old=sv.get<rdl::Int>("max_diffuse_depth");reject("bounce budget",[&]{rdl::SceneObject::UpdateGuard g(&sv);sv.set<rdl::Int>("max_diffuse_depth",8);},[&]{rdl::SceneObject::UpdateGuard g(&sv);sv.set<rdl::Int>("max_diffuse_depth",old);});
 auto transform=mesh->get<rdl::Mat4d>("node_xform");reject("singular transform",[&]{rdl::SceneObject::UpdateGuard g(mesh);auto m=transform;m[0][0]=m[0][1]=m[0][2]=0;mesh->set<rdl::Mat4d>("node_xform",m);},[&]{rdl::SceneObject::UpdateGuard g(mesh);mesh->set<rdl::Mat4d>("node_xform",transform);});
 check(lane.driver.allocations==allocations&&lane.driver.synchronizations==sync,"Per-slice allocation/sync");check(pool.counts().submitted==pool.counts().collected,"Lost CPU slice");pool.close();
 report["exact_resumption_by_device"]=true;report["checkerboard_matches_owned_device"]=true;report["analytical_four_surface_chain"]=true;report["resident_geometry"]=true;report["surface_limit"]=plan->surfaceLimit;report["state_bytes"]=unsigned(sizeof(resume::State));report["batch_bytes"]=unsigned(sizeof(resume::Batch));report["cpu_workers"]=pool.counts().created;report["no_per_slice_gpu_allocation_or_sync"]=true;report["status"]="passed";
 Json::StreamWriterBuilder writer;writer["indentation"]="";std::cout<<Json::writeString(writer,report)<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
