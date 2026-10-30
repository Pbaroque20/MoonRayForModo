#include <optix.h>
#include <optix_device.h>
#include "gpu_jobs.h"
#include "resume_core.h"
using namespace xpu2::interactive;
extern "C" {__constant__ mixed::Params params{};}
static __device__ float3 f3(surface::V3 v){return make_float3(v.x,v.y,v.z);}
extern "C" __global__ void __miss__primary(){optixSetPayload_0(0xffffffffu);}
extern "C" __global__ void __miss__shadow(){optixSetPayload_0(0);}
extern "C" __global__ void __closesthit__surface(){if(params.scene->spatial)return;optixSetPayload_0(optixGetInstanceId());optixSetPayload_1(__float_as_uint(optixGetRayTmax()));if(params.scene->spatial||params.scene->textures){auto uv=optixGetTriangleBarycentrics();optixSetPayload_2(optixGetPrimitiveIndex());optixSetPayload_3(__float_as_uint(uv.x));optixSetPayload_4(__float_as_uint(uv.y));}}

// A shared exact triangle membership test, with OptiX retaining the GPU BVH.
// Primary payload: geometry, primitive, double distance low/high, ray kind.
// Shadow payload: hit flag, unused, unused, unused, kind=1.
extern "C" __global__ void __intersection__triangle(){
 unsigned geom=optixGetInstanceId(),prim=optixGetPrimitiveIndex();auto m=params.geometry[geom];auto t=m.triangles[prim];auto o=optixGetWorldRayOrigin(),d=optixGetWorldRayDirection();surface::Ray ray{{o.x,o.y,o.z},{d.x,d.y,d.z},{},{},optixGetRayTmin(),optixGetRayTmax()};triangle::Coordinates h;
 if(!triangle::coordinates(ray,m.vertices[t.a],m.vertices[t.b],m.vertices[t.c],h)||!triangle::contains(h,ray))return;
 bool shadow=optixGetPayload_4()!=0;
 if(!shadow&&!triangle::nearer(h.t,geom,prim,__hiloint2double(optixGetPayload_3(),optixGetPayload_2()),optixGetPayload_0(),optixGetPayload_1()))return;
 if(optixReportIntersection(triangle::upperDistance(h.t),0)){
  optixSetPayload_0(shadow?1u:geom);if(!shadow){optixSetPayload_1(prim);optixSetPayload_2(__double2loint(h.t));optixSetPayload_3(__double2hiint(h.t));}
 }
}

struct GpuStageBackend {
 __device__ resume::Hit trace(const surface::Ray& ray){unsigned g=~0u,t=0,prim=0,u=0,v=0;if(params.scene->spatial){double best=__longlong_as_double(0x7ff0000000000000ull);unsigned lo=__double2loint(best),hi=__double2hiint(best),kind=0;optixTrace(params.traversable,f3(ray.origin),f3(ray.direction),ray.nearT,ray.farT,0,255,OPTIX_RAY_FLAG_DISABLE_ANYHIT,0,1,0,g,prim,lo,hi,kind);}
  else optixTrace(params.traversable,f3(ray.origin),f3(ray.direction),ray.nearT,ray.farT,0,255,OPTIX_RAY_FLAG_DISABLE_ANYHIT,0,1,0,g,t,prim,u,v);resume::Hit h;h.geom=g;h.t=__uint_as_float(t);h.normal={0,0,1};h.prim=prim;h.u=__uint_as_float(u);h.v=__uint_as_float(v);
  if(g!=~0u&&params.scene->spatial){h.prim=prim;h.u=__uint_as_float(u);h.v=__uint_as_float(v);if(g>=params.scene->meshes||!params.geometry){h.normal={};return h;}auto m=params.geometry[g];if(prim>=m.triangleCount){h.normal={};return h;}auto tri=m.triangles[prim];if(tri.a>=m.vertexCount||tri.b>=m.vertexCount||tri.c>=m.vertexCount||!resume::geometryHit(h,ray,m.vertices[tri.a],m.vertices[tri.b],m.vertices[tri.c]))h.normal={};}return h;}
 __device__ __noinline__ unsigned material(const resume::Hit& h,const surface::Ray& ray,surface::Lambert& out){
  if(h.geom>=params.scene->meshes)return tex::Invalid;out=params.materials[h.geom];if(!params.scene->textures)return tex::Ready;
  if(!params.geometry||!params.maps)return tex::Invalid;auto m=params.geometry[h.geom];if(h.prim>=m.triangleCount)return tex::Invalid;auto t=m.triangles[h.prim];if(t.a>=m.vertexCount||t.b>=m.vertexCount||t.c>=m.vertexCount)return tex::Invalid;
  tex::Footprint f;if(!tex::footprint(m.vertices[t.a],m.vertices[t.b],m.vertices[t.c],ray,h.u,h.v,params.scene->spp,f,params.scene->spatial!=0))return tex::Invalid;
  auto maps=params.maps[h.geom];surface::V3* bases[2]={&out.albedo,&out.emission};tex::Binding bindings[2]={maps.diffuse,maps.emission};
  for(int i=0;i<2;++i){auto& b=bindings[i];auto& v=*bases[i];if(!b.image||(v.x==0&&v.y==0&&v.z==0))continue;surface::V3 c;auto status=tex::lookup(b,f,c);if(status!=tex::Ready)return status;v={v.x*c.x,v.y*c.y,v.z*c.z};}return tex::Ready;
 }
 __device__ bool visible(surface::V3 o,surface::V3 d){unsigned shadow=1,dummy=0;if(params.scene->spatial){unsigned a=0,b=0,c=0,kind=1;optixTrace(params.traversable,f3(o),f3(d),0,__int_as_float(0x7f800000),0,255,OPTIX_RAY_FLAG_DISABLE_ANYHIT|OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT|OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT,0,1,1,shadow,a,b,c,kind);return shadow==0;}optixTrace(params.traversable,f3(o),f3(d),0,__int_as_float(0x7f800000),0,255,OPTIX_RAY_FLAG_DISABLE_ANYHIT|OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT|OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT|(params.scene->spatial?0:OPTIX_RAY_FLAG_CULL_BACK_FACING_TRIANGLES),0,1,1,shadow,dummy);return shadow==0;}
};
static __device__ void resumeSlice(unsigned lane){
 auto& b=*params.continuation;const auto& j=params.job;auto& out=params.result->pixels[lane];
 // Metadata has a single writer. No lane reads revision or metadata that another
 // lane writes in this launch; the host retains exclusive slot ownership.
 if(lane==0){if(params.reset){b.epoch=j.epoch;b.sequence=j.sequence;b.count=j.count;b.first=j.first;b.samples=j.samples;b.revision=0;}++b.revision;params.result->epoch=j.epoch;params.result->sequence=j.sequence;params.result->count=j.count;params.result->pad=b.revision;}
 if(lane>=j.count)return;auto& state=b.paths[lane];if(params.reset){state=resume::State{};state.film.pixel=j.pixels[lane];}
 if(!mixed::same(j,*params.scene)||!params.stageSteps||params.stageSteps>64||state.film.pixel!=j.pixels[lane]){resume::fail(state,20);out=resume::snapshot(state);return;}
 if(j.delay){auto start=clock64();while(clock64()-start<j.delay){}}
 // A host-authorized retry keeps the sample identity and all path state.
 if(state.phase==resume::TextureWait)state.phase=resume::Shade;
 GpuStageBackend backend;for(unsigned n=0;n<params.stageSteps&&state.phase<resume::Complete;++n)resume::step(state,j,*params.scene,backend);
 out=resume::snapshot(state);if(lane==0&&j.fault==1)params.result->sequence^=1;if(lane==0&&j.fault==2)out.sum[0]=__int_as_float(0x7fc00000);
}
extern "C" __global__ void __raygen__render(){
 const unsigned lane=optixGetLaunchIndex().x;if(params.continuation){resumeSlice(lane);return;}auto& output=params.result->pixels[lane];output=mixed::Pixel{};
 if(lane==0){params.result->epoch=params.job.epoch;params.result->sequence=params.job.sequence;params.result->count=params.job.count;params.result->pad=0;}
 if(lane>=params.job.count)return;
 const auto& j=params.job;const auto& c=*params.scene;output.pixel=j.pixels[lane];
 if(!mixed::same(j,c)||output.pixel>=c.width*c.height){output.status=1;return;}
 if(j.delay){auto start=clock64();while(clock64()-start<j.delay){}}
 if(c.spatial){resume::State state{};state.film.pixel=output.pixel;GpuStageBackend backend;while(state.phase<resume::Complete)resume::step(state,j,c,backend);output=resume::snapshot(state);if(lane==0&&j.fault==1)params.result->sequence^=1;if(lane==0&&j.fault==2)output.sum[0]=__int_as_float(0x7fc00000);return;}
 for(unsigned s=0;s<j.samples;++s){sample::Identity id{output.pixel,j.first+s,c.seed,0};float x,y;
  if(!surface::filter(c.filter,c.filterWidth,sample::draw(id,0,c.sampling),x)||!surface::filter(c.filter,c.filterWidth,sample::draw(id,1,c.sampling),y)){output.status=2;return;}
  surface::Ray ray;if(!surface::cameraRay(c.camera,float(output.pixel%c.width)+x,float(output.pixel/c.width)+y,ray)){output.status=3;return;}
  unsigned geom=0xffffffffu,t=0;
  optixTrace(params.traversable,f3(ray.origin),f3(ray.direction),ray.nearT,ray.farT,0,255,OPTIX_RAY_FLAG_DISABLE_ANYHIT,0,1,0,geom,t);
  if(geom!=0xffffffffu){
   if(geom>=c.meshes){output.status=4;return;}
   surface::Sample sample;float u=sample::draw(id,16,c.sampling),v=sample::draw(id,17,c.sampling);
   if(!surface::lambert(params.materials[geom],{0,0,1},u,v,sample)){output.status=5;return;}
   auto origin=surface::add(ray.origin,surface::mul(ray.direction,__uint_as_float(t)));origin.z=0x1p-126f;
   // Admission guarantees every triangle lies on Z=0 with +Z winding.
   // A +Z-hemisphere shadow cannot legitimately hit a back face in this domain.
   // Cull numerical self-hits: RT traversal can round the minimum-normal offset to zero.
   unsigned shadow=1,dummy=0;
   optixTrace(params.traversable,f3(origin),f3(sample.wi),0,__int_as_float(0x7f800000),0,255,OPTIX_RAY_FLAG_DISABLE_ANYHIT|OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT|OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT|OPTIX_RAY_FLAG_CULL_BACK_FACING_TRIANGLES,0,1,1,shadow,dummy);
   if(!shadow&&sample.pdf>0){output.sum[0]+=double(sample.f.x/sample.pdf)*c.sky.x;output.sum[1]+=double(sample.f.y/sample.pdf)*c.sky.y;output.sum[2]+=double(sample.f.z/sample.pdf)*c.sky.z;}
   output.sum[0]+=params.materials[geom].emission.x;output.sum[1]+=params.materials[geom].emission.y;output.sum[2]+=params.materials[geom].emission.z;
   output.sum[3]+=1;
  }
  ++output.count;
 }
 if(lane==0&&j.fault==1)params.result->sequence^=1;
 if(lane==0&&j.fault==2)output.sum[0]=__int_as_float(0x7fc00000);
}
