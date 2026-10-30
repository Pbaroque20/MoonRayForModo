// Private bounded CPU correctness lane. Planar diffuse subset only.
#pragma once
#include "cpu_scene.h"
#include "sample_tree.h"
#include "triangle_hit.h"
#include <embree4/rtcore.h>
#include <atomic>
#include <cstring>
#include <limits>
#include <thread>
namespace xpu2::interactive::cpu {
struct Device {
 RTCDevice handle=rtcNewDevice(nullptr);std::atomic<int> error{RTC_ERROR_NONE};
 static void onError(void* user,RTCError code,const char*) noexcept {
  auto& stored=static_cast<Device*>(user)->error;int expected=RTC_ERROR_NONE;
  stored.compare_exchange_strong(expected,int(code),std::memory_order_relaxed);
 }
 Device(){need(handle,"Embree device failure");rtcSetDeviceErrorFunction(handle,onError,this);}
 bool healthy()const{return error.load(std::memory_order_relaxed)==RTC_ERROR_NONE;}
 void check(){auto e=rtcGetDeviceError(handle);if(e!=RTC_ERROR_NONE)onError(this,e,nullptr);need(healthy(),"Embree error; whole epoch must use fallback");}
 ~Device(){rtcReleaseDevice(handle);}Device(const Device&)=delete;
};
struct Acceleration {
 std::shared_ptr<Device> device;RTCScene scene=nullptr;bool precise=false;std::vector<std::shared_ptr<const MeshData>> data;
 explicit Acceleration(std::shared_ptr<Device> d):device(std::move(d)),scene(rtcNewScene(device->handle)){need(scene,"Embree scene failure");}
 ~Acceleration(){if(scene)rtcReleaseScene(scene);}Acceleration(const Acceleration&)=delete;
};
using AccelView=std::shared_ptr<const Acceleration>;
// Immutable mesh data is leased by Acceleration for every callback. This
// scalar prototype uses the same double triangle test for closest-hit and shadow
// rays: the stock single-ray triangle kernel missed a verified near-edge hit.
// Embree still owns BVH construction/traversal; no scene-wide brute-force scan.
inline void preciseBounds(const RTCBoundsFunctionArguments* a){
 const auto& m=*static_cast<const MeshData*>(a->geometryUserPtr);auto t=m.triangles[a->primID];auto x=m.positions[t.a],y=m.positions[t.b],z=m.positions[t.c];auto& b=*a->bounds_o;
 b.lower_x=std::nextafter(std::min({x.x,y.x,z.x}),-INFINITY);b.lower_y=std::nextafter(std::min({x.y,y.y,z.y}),-INFINITY);b.lower_z=std::nextafter(std::min({x.z,y.z,z.z}),-INFINITY);
 b.upper_x=std::nextafter(std::max({x.x,y.x,z.x}),INFINITY);b.upper_y=std::nextafter(std::max({x.y,y.y,z.y}),INFINITY);b.upper_z=std::nextafter(std::max({x.z,y.z,z.z}),INFINITY);
}
inline bool preciseCandidate(const void* data,unsigned prim,RTCRayN* r,unsigned N,unsigned i,triangle::Coordinates& h){
 const auto& m=*static_cast<const MeshData*>(data);auto t=m.triangles[prim];
 surface::Ray ray{{RTCRayN_org_x(r,N,i),RTCRayN_org_y(r,N,i),RTCRayN_org_z(r,N,i)},
 {RTCRayN_dir_x(r,N,i),RTCRayN_dir_y(r,N,i),RTCRayN_dir_z(r,N,i)},{},{},RTCRayN_tnear(r,N,i),RTCRayN_tfar(r,N,i)};
 return triangle::coordinates(ray,m.positions[t.a],m.positions[t.b],m.positions[t.c],h)&&triangle::contains(h,ray);
}
struct PreciseContext {RTCRayQueryContext base;double closest=INFINITY;unsigned geom=~0u,prim=~0u;PreciseContext(){rtcInitRayQueryContext(&base);}};
inline void preciseIntersect(const RTCIntersectFunctionNArguments* a){
 auto r=RTCRayHitN_RayN(a->rayhit,a->N);auto h=RTCRayHitN_HitN(a->rayhit,a->N);
 for(unsigned i=0;i<a->N;++i){if(a->valid[i]!=-1)continue;triangle::Coordinates c;if(!preciseCandidate(a->geometryUserPtr,a->primID,r,a->N,i,c))continue;
  auto& context=*reinterpret_cast<PreciseContext*>(a->context);if(!triangle::nearer(c.t,a->geomID,a->primID,context.closest,context.geom,context.prim))continue;context.closest=c.t;context.geom=a->geomID;context.prim=a->primID;
  const auto& m=*static_cast<const MeshData*>(a->geometryUserPtr);auto t=m.triangles[a->primID];auto n=surface::cross(surface::add(m.positions[t.b],surface::mul(m.positions[t.a],-1)),surface::add(m.positions[t.c],surface::mul(m.positions[t.a],-1)));
  RTCRayN_tfar(r,a->N,i)=triangle::upperDistance(c.t);RTCHitN_u(h,a->N,i)=float(c.u);RTCHitN_v(h,a->N,i)=float(c.v);RTCHitN_Ng_x(h,a->N,i)=n.x;RTCHitN_Ng_y(h,a->N,i)=n.y;RTCHitN_Ng_z(h,a->N,i)=n.z;
  RTCHitN_geomID(h,a->N,i)=a->geomID;RTCHitN_primID(h,a->N,i)=a->primID;for(unsigned l=0;l<RTC_MAX_INSTANCE_LEVEL_COUNT;++l)RTCHitN_instID(h,a->N,i,l)=RTC_INVALID_GEOMETRY_ID;
 }
}
inline void preciseOccluded(const RTCOccludedFunctionNArguments* a){for(unsigned i=0;i<a->N;++i){if(a->valid[i]!=-1)continue;triangle::Coordinates c;if(preciseCandidate(a->geometryUserPtr,a->primID,a->ray,a->N,i,c))RTCRayN_tfar(a->ray,a->N,i)=-INFINITY;}}

inline AccelView acceleration(const PlanView& plan,AccelView old={}){
 need(bool(plan),"Missing prepared plan");bool same=old&&old->precise==isSpatial(plan->domain)&&old->device->healthy()&&old->data.size()==plan->meshes.size();
 if(same)for(size_t i=0;i<old->data.size();++i)same=same&&(old->data[i]==plan->meshes[i].data);
 if(same)return old;
 auto a=std::make_shared<Acceleration>(old&&old->device->healthy()?old->device:std::make_shared<Device>());
 // Select robust edge tests before the initial BVH build. Changing flags after
 // commit may retain an existing non-robust triangle acceleration structure.
 a->precise=isSpatial(plan->domain);if(a->precise)rtcSetSceneFlags(a->scene,RTC_SCENE_FLAG_ROBUST);
 for(unsigned i=0;i<plan->meshes.size();++i){auto m=plan->meshes[i].data;
  bool precise=isSpatial(plan->domain);RTCGeometry g=rtcNewGeometry(a->device->handle,precise?RTC_GEOMETRY_TYPE_USER:RTC_GEOMETRY_TYPE_TRIANGLE);need(g,"Embree geometry failure");
  try{if(precise){rtcSetGeometryUserPrimitiveCount(g,unsigned(m->triangles.size()));rtcSetGeometryUserData(g,const_cast<MeshData*>(m.get()));rtcSetGeometryBoundsFunction(g,preciseBounds,nullptr);rtcSetGeometryIntersectFunction(g,preciseIntersect);rtcSetGeometryOccludedFunction(g,preciseOccluded);}else{void* v=rtcSetNewGeometryBuffer(g,RTC_BUFFER_TYPE_VERTEX,0,RTC_FORMAT_FLOAT3,sizeof(V3),m->positions.size());
   void* t=rtcSetNewGeometryBuffer(g,RTC_BUFFER_TYPE_INDEX,0,RTC_FORMAT_UINT3,sizeof(Tri),m->triangles.size());need(v&&t,"Embree allocation failure");
   std::memcpy(v,m->positions.data(),m->positions.size()*sizeof(V3));std::memcpy(t,m->triangles.data(),m->triangles.size()*sizeof(Tri));}
   rtcCommitGeometry(g);rtcAttachGeometryByID(a->scene,g,i);rtcReleaseGeometry(g);g=nullptr;a->data.push_back(m);
  }catch(...){if(g)rtcReleaseGeometry(g);throw;}
 }
 rtcCommitScene(a->scene);a->device->check();return a;
}
struct JoinWorkers {
 std::vector<std::thread>& workers;
 ~JoinWorkers(){for(auto& worker:workers)if(worker.joinable())worker.join();}
};
struct Image {std::vector<float> rgba;film::Audit audit{};bool cancelled=false;};
inline Image render(PlanView plan,AccelView a,unsigned threads,const std::atomic<bool>* cancel=nullptr,std::atomic<uint64_t>* progress=nullptr,const std::atomic<uint64_t>* generation=nullptr,uint64_t ticket=0){
 need(plan&&plan->domain==Domain::Planar&&plan->diffuseMaps.empty()&&plan->emissionMaps.empty(),"Textured plan requires job renderer");
 need(plan&&a&&threads>0&&threads<=64,"Invalid CPU render request");
 need(a->data.size()==plan->meshes.size(),"Wrong acceleration structure");for(size_t i=0;i<a->data.size();++i)need(a->data[i]==plan->meshes[i].data,"Stale acceleration structure");
 a->device->check();
 auto e=plan->source->routing->epoch;film::Tree film({e.session,e.scene,e.camera,e.settings},plan->width*plan->height,threads);
 std::atomic<unsigned> next{0},failed{0};std::exception_ptr firstError;std::vector<std::thread> workers;workers.reserve(threads);JoinWorkers join{workers};
 auto cancelled=[&]{return (cancel&&cancel->load(std::memory_order_acquire))||(generation&&generation->load(std::memory_order_acquire)!=ticket);};
 auto stop=[&]{return cancelled()||failed.load(std::memory_order_relaxed)||!a->device->healthy();};
 try{for(unsigned w=0;w<threads;++w)workers.emplace_back([&]{try{for(unsigned pixel;(pixel=next.fetch_add(1))<plan->width*plan->height&&!stop();){
  for(unsigned s=0;s<plan->spp&&!stop();++s){film::Handle root;sample::Identity id;need(film.begin(pixel,plan->seed,root,id)==film::Status::Ok,"Sample reservation failed");
   float x,y;need(surface::filter(plan->filter,plan->filterWidth,sample::draw(id,0,plan->sampling),x)&&surface::filter(plan->filter,plan->filterWidth,sample::draw(id,1,plan->sampling),y),"Camera filter failure");
   surface::Ray ray;need(surface::cameraRay(plan->camera,float(pixel%plan->width)+x,float(pixel/plan->width)+y,ray),"Camera ray failure");
   RTCRayHit hit{};hit.ray.org_x=ray.origin.x;hit.ray.org_y=ray.origin.y;hit.ray.org_z=ray.origin.z;
   hit.ray.dir_x=ray.direction.x;hit.ray.dir_y=ray.direction.y;hit.ray.dir_z=ray.direction.z;hit.ray.tnear=ray.nearT;hit.ray.tfar=ray.farT;hit.ray.mask=~0u;hit.hit.geomID=RTC_INVALID_GEOMETRY_ID;
   RTCIntersectArguments args;rtcInitIntersectArguments(&args);rtcIntersect1(a->scene,&hit,&args);
   path::Record record{};record.epoch=root.epoch;record.id=id;path::Stage stage(record);std::array<film::Handle,15> children;path::Effects effects;
   if(hit.hit.geomID==RTC_INVALID_GEOMETRY_ID){need(stage.commit(record,effects,root.epoch,true)&&film.finish(root,effects,children)==film::Status::Ok,"Miss completion failure");}
   else{
    need(hit.hit.geomID<plan->meshes.size(),"Unexpected geometry id");
    V3 normal;need(surface::normalize({hit.hit.Ng_x,hit.hit.Ng_y,hit.hit.Ng_z},normal)&&normal.z>0,"Unexpected geometry normal");
    float u,v;need(stage.random(u)&&stage.random(v),"Random dimension limit");if(plan->sampling&2){u=sample::draw(id,16,plan->sampling);v=sample::draw(id,17,plan->sampling);}surface::Sample sample;
    need(surface::lambert(plan->materials.at(plan->meshes[hit.hit.geomID].material),normal,u,v,sample),"Material failure");need(stage.emit({0,{plan->materials.at(plan->meshes[hit.hit.geomID].material).emission.x,plan->materials.at(plan->meshes[hit.hit.geomID].material).emission.y,plan->materials.at(plan->meshes[hit.hit.geomID].material).emission.z,1}}),"Contribution capacity");
    // All admitted surfaces lie on Z=0. A minimum-normal offset avoids a fixed world
    // epsilon and cannot skip another accepted surface above this one.
    V3 origin=surface::add(ray.origin,surface::mul(ray.direction,hit.ray.tfar));origin.z=std::numeric_limits<float>::min();
    path::Ray child{{origin.x,origin.y,origin.z},{sample.wi.x,sample.wi.y,sample.wi.z},0,INFINITY,0};
    need(stage.spawn(0,child,0)&&stage.commit(record,effects,root.epoch,true),"Child capacity");need(film.finish(root,effects,children)==film::Status::Ok,"Parent commit failure");
    RTCRay shadow{};shadow.org_x=origin.x;shadow.org_y=origin.y;shadow.org_z=origin.z;shadow.dir_x=sample.wi.x;shadow.dir_y=sample.wi.y;shadow.dir_z=sample.wi.z;shadow.tnear=0;shadow.tfar=INFINITY;shadow.mask=~0u;
    RTCOccludedArguments oa;rtcInitOccludedArguments(&oa);rtcOccluded1(a->scene,&shadow,&oa);
    path::Effects light{};light.valueCount=1;if(shadow.tfar>=0&&sample.pdf>0)light.values[0]={0,{double(sample.f.x/sample.pdf)*plan->sky.x,double(sample.f.y/sample.pdf)*plan->sky.y,double(sample.f.z/sample.pdf)*plan->sky.z,0}};
    need(film.finish(children[0],light,children)==film::Status::Ok,"Child commit failure");
   }
   if(progress)progress->fetch_add(1,std::memory_order_release);
  }
 }}catch(...){if(failed.fetch_add(1)==0)firstError=std::current_exception();}});}catch(...){failed.store(1);throw;}
 for(auto& w:workers)w.join();if(firstError)std::rethrow_exception(firstError);need(!failed,"Native stage failed; whole epoch must use fallback");a->device->check();
 Image result;result.audit=film.audit();
 if(cancelled()){result.cancelled=true;result.audit.invalidated=result.audit.started;return result;}
 need(result.audit.active==0&&result.audit.started==uint64_t(plan->width)*plan->height*plan->spp&&result.audit.completed==result.audit.started,"Sample audit failure");
 auto pixels=film.snapshot();result.rgba.reserve(pixels.size()*4);for(auto& p:pixels){need(p.count==plan->spp,"Pixel sample count failure");for(double v:p.sum){float value=float(v/p.count);need(std::isfinite(value),"Nonfinite film output");result.rgba.push_back(value);}}
 return result;
}
}
