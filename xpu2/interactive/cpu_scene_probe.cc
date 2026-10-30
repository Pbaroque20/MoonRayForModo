#include "cpu_lane.h"
#include <fstream>
#include <iostream>
#include <chrono>
#include <json/json.h>
using namespace xpu2::interactive;namespace rdl=scene_rdl2::rdl2;
static void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static void write(const fs::path& file,const cpu::Image& image){std::ofstream out(file,std::ios::binary);out.write((const char*)image.rgba.data(),image.rgba.size()*sizeof(float));check(bool(out),"Image write failed");}
int main(int argc,char** argv){try{
 check(argc==4,"scene, runtime, out required");fs::path out(argv[3]);rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);
 CanonicalSession session(argv[2],{101,0,0,0});cpu::PlanView plan,initial;cpu::AccelView acceleration;unsigned version=0;
 Json::Value report;report["stages"]=Json::Value(Json::arrayValue);
 auto stage=[&](const char* name){auto frame=session.prepare(source,out/name,{101,++version,1,1});check(frame->routing->mode==Mode::Fallback,"Unqualified scene escaped production fallback");
  auto prepared=cpu::prepare(session,frame,plan);auto accel=cpu::acceleration(prepared,acceleration);check(session.acknowledge(frame)&&session.publish(frame),"Canonical publication failed");
  Json::Value r;r["name"]=name;r["meshes_reused"]=Json::UInt64(prepared->reusedMeshes);r["meshes_prepared"]=Json::UInt64(prepared->preparedMeshes);r["bytes"]=Json::UInt64(prepared->bytes);r["acceleration_reused"]=accel==acceleration;r["attributes_encoded"]=Json::UInt64(frame->attributesEncoded);
  auto one=cpu::render(prepared,accel,1),many=cpu::render(prepared,accel,12);check(one.rgba==many.rgba,"One/twelve-worker image mismatch");write(out/(std::string(name)+".rgba"),one);
  r["started"]=Json::UInt64(one.audit.started);r["completed"]=Json::UInt64(one.audit.completed);r["one_twelve_exact"]=true;report["stages"].append(r);
  source.commitAllChanges();plan=std::move(prepared);acceleration=std::move(accel);return frame;
 };
 stage("initial");initial=plan;auto firstAcceleration=acceleration;
 auto* material=source.getSceneObject("/m0");{rdl::SceneObject::UpdateGuard u(material);material->set<rdl::Rgb>("diffuseColor",rdl::Rgb(.2f,.4f,.7f));}
 stage("material");check(acceleration==firstAcceleration,"Material edit rebuilt BVH");
 auto* camera=source.getSceneObject("/camera");{rdl::SceneObject::UpdateGuard u(camera);auto m=camera->get<rdl::Mat4d>("node_xform");m[3][0]+=.045;camera->set("node_xform",m,rdl::TIMESTEP_BEGIN);camera->set("node_xform",m,rdl::TIMESTEP_END);}
 stage("camera");check(acceleration==firstAcceleration,"Camera edit rebuilt BVH");
 auto* mesh=source.getSceneObject("/g0");{rdl::SceneObject::UpdateGuard u(mesh);auto positions=mesh->get<rdl::Vec3fVector>("vertex_list");positions[0].x-=1;mesh->set("vertex_list",positions);}
 stage("geometry");check(acceleration!=firstAcceleration&&plan->reusedMeshes==3&&plan->preparedMeshes==1,"Dirty mesh preparation incorrect");
 // Old snapshots/BVHs remain renderable after all new versions publish.
 auto original=cpu::render(initial,firstAcceleration,1);write(out/"retained-initial.rgba",original);
 std::atomic<bool> cancel{false};std::atomic<uint64_t> progress{0};cpu::Image cancelled;
 std::atomic<bool> done{false};std::exception_ptr failure;
 std::thread worker([&]{try{cancelled=cpu::render(plan,acceleration,12,&cancel,&progress);}catch(...){failure=std::current_exception();}done.store(true,std::memory_order_release);});
 auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
 while(progress.load(std::memory_order_acquire)==0&&!done.load(std::memory_order_acquire)&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
 cancel.store(true,std::memory_order_release);worker.join();if(failure)std::rethrow_exception(failure);
 check(cancelled.cancelled&&cancelled.rgba.empty()&&cancelled.audit.started>0,"Cancellation exposed partial image");report["cancelled_samples"]=Json::UInt64(cancelled.audit.started);
 // Inject unsupported edits into pending replicas; reject and recover without
 // replacing the retained native plan. The canonical fallback is still intact.
 auto reject=[&](const char* name){auto prior=session.acquire();auto frame=session.prepare(source,out/name,{101,++version,1,1});std::string reason;
  try{cpu::prepare(session,frame,plan);}catch(const cpu::Unsupported& error){reason=error.what();}
  check(!reason.empty(),"Unsupported configuration admitted");check(session.reject(frame)&&session.acquire()==prior,"Rejection displaced active scene");
  bool stale=false;try{cpu::prepare(session,frame,plan);}catch(const std::logic_error&){stale=true;}check(stale,"Stale replica inspection accepted");report["rejections"][name]=reason;source.commitAllChanges();
 };
 {rdl::SceneObject::UpdateGuard u(material);material->set<rdl::Int>("useSpecularWorkflow",0);}reject("dielectric");
 {rdl::SceneObject::UpdateGuard u(material);material->set<rdl::Int>("useSpecularWorkflow",1);}
 auto* map=source.createSceneObject("ConstantColorMap","/unsupported-map");{rdl::SceneObject::UpdateGuard u(material);material->setBinding("diffuseColor",map);}reject("map");
 {rdl::SceneObject::UpdateGuard u(material);material->setBinding("diffuseColor",nullptr);}source.deleteSceneObject("/unsupported-map");
 {rdl::SceneObject::UpdateGuard u(mesh);mesh->set<rdl::Bool>("is_subd",true);}reject("subdivision");
 {rdl::SceneObject::UpdateGuard u(mesh);mesh->set<rdl::Bool>("is_subd",false);}
 auto& sv=source.getSceneVariables();{rdl::SceneObject::UpdateGuard u(&sv);sv.set<rdl::Int>("sampling_mode",1);}reject("adaptive");{rdl::SceneObject::UpdateGuard u(&sv);sv.set<rdl::Int>("sampling_mode",0);}
 {rdl::SceneObject::UpdateGuard u(&sv);sv.set<rdl::Float>("sample_clamping_value",10.f);}reject("clamping");{rdl::SceneObject::UpdateGuard u(&sv);sv.set<rdl::Float>("sample_clamping_value",0.f);}
 {rdl::SceneObject::UpdateGuard u(camera);auto m=camera->get<rdl::Mat4d>("node_xform");m[3][0]+=.1;camera->set("node_xform",m,rdl::TIMESTEP_END);}reject("motion");
 {rdl::SceneObject::UpdateGuard u(camera);camera->set("node_xform",camera->get<rdl::Mat4d>("node_xform"),rdl::TIMESTEP_END);}
 auto positions=mesh->get<rdl::Vec3fVector>("vertex_list");{rdl::SceneObject::UpdateGuard u(mesh);auto p=positions;p[0].z=.5f;mesh->set("vertex_list",p);}reject("nonplanar");{rdl::SceneObject::UpdateGuard u(mesh);mesh->set("vertex_list",positions);}
 auto indices=mesh->get<rdl::IntVector>("vertices_by_index");{rdl::SceneObject::UpdateGuard u(mesh);auto i=indices;i[0]=-1;mesh->set("vertices_by_index",i);}reject("bad-index");{rdl::SceneObject::UpdateGuard u(mesh);mesh->set("vertices_by_index",indices);}
 auto* output=source.getSceneObject("/beauty");{rdl::SceneObject::UpdateGuard u(output);output->set<rdl::Int>("result",2);}reject("aov");{rdl::SceneObject::UpdateGuard u(output);output->set<rdl::Int>("result",0);}
 auto frame=session.prepare(source,out/"budget",{101,++version,1,1});bool budget=false;try{cpu::prepare(session,frame,plan,{1,1,1,1,1});}catch(const cpu::Unsupported&){budget=true;}check(budget&&session.reject(frame),"Preparation budget ignored");report["budget_rejected"]=true;
 auto recovery=session.prepare(source,out/"recovery",{101,++version,1,1});auto recovered=cpu::prepare(session,recovery,plan);auto recoveredAcceleration=cpu::acceleration(recovered,acceleration);check(recoveredAcceleration==acceleration,"Recovery lost reusable geometry");check(session.acknowledge(recovery)&&session.publish(recovery),"Recovery publication failed");
 auto final=cpu::render(recovered,recoveredAcceleration,1);write(out/"recovered.rgba",final);
 bool staleAccel=false;try{cpu::render(recovered,firstAcceleration,1);}catch(const cpu::Unsupported&){staleAccel=true;}check(staleAccel,"Stale BVH accepted");
 // Synthetic error delivery tests ownership/recovery policy, not driver fault injection.
 cpu::Device::onError(recoveredAcceleration->device.get(),RTC_ERROR_UNKNOWN,"injected");
 bool deviceError=false;try{cpu::render(recovered,recoveredAcceleration,1);}catch(const cpu::Unsupported&){deviceError=true;}check(deviceError,"Device error ignored");
 auto renewed=cpu::acceleration(recovered,recoveredAcceleration);check(renewed->device!=recoveredAcceleration->device,"Failed device reused");
 check(cpu::render(recovered,renewed,1).rgba==final.rgba,"Device recovery image changed");report["synthetic_device_error_recovered"]=true;report["stale_accel_rejected"]=true;report["recovered"]=true;report["status"]="passed";report["qualified_native_scene"]=false;
 Json::StreamWriterBuilder b;b["indentation"]="";std::cout<<Json::writeString(b,report)<<std::endl;return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
