// Private bounded diffuse path state, shared CPU/CUDA. No general material tree.
#pragma once
#include "gpu_jobs.h"
#include "triangle_hit.h"
namespace xpu2::interactive::resume {
using mixed::U32;using mixed::U64;
enum Phase:U32 {Camera,Trace,Shade,Shadow,Finish,Complete,Error,TextureWait};
// origin is offset to the side the ray came from; below, to the other side (refracted and
// transmitted rays start there).
// epsilon: a curve hit's ray epsilon hint (1.5 times the curve's radius there; zero for a triangle). Rays leave a
// curve from the hit point itself and skip what is nearer than it (normal: a round cubic's geometric normal, else
// the reversed ray).
struct Hit {U32 geom=~0u,prim=0;float t=0,u=0,v=0;surface::V3 normal{},origin{},below{},point{};float epsilon=0;};
// Interpolate the hit from resident triangle vertices. Offset by a conservative
// float arithmetic bound along the facing geometric normal, then round outward.
// This is a restricted triangle prototype, not a proof for displacement/curves.
X2_HD inline bool geometryHit(Hit& h,const surface::Ray& ray,surface::V3 a,surface::V3 b,surface::V3 c){
 using namespace surface;V3 e1=add(b,mul(a,-1)),e2=add(c,mul(a,-1));
 if(!normalize(cross(e1,e2),h.normal))return false;
 if(dot(h.normal,ray.direction)>0)h.normal=mul(h.normal,-1);
 // Embree and OptiX identify the primitive; reconstruct its coordinates with
 // the same arithmetic on both devices. Device-specific float barycentrics can
 // move a shadow origin across an occluder edge. Compute from immutable float
 // vertices and the original ray in double, then round once to path precision.
 // This does not change triangle membership or replace hardware traversal.
 triangle::Coordinates precise;
 if(!triangle::coordinates(ray,a,b,c,precise))return false;
 h.t=float(precise.t);h.u=float(precise.u);h.v=float(precise.v);
 V3 p={float(double(a.x)+((double(b.x)-a.x)*precise.u+(double(c.x)-a.x)*precise.v)),
       float(double(a.y)+((double(b.y)-a.y)*precise.u+(double(c.y)-a.y)*precise.v)),
       float(double(a.z)+((double(b.z)-a.z)*precise.u+(double(c.z)-a.z)*precise.v))};
 h.point=p;
 V3 error{fabsf(a.x)+fabsf(e1.x)+fabsf(e2.x),fabsf(a.y)+fabsf(e1.y)+fabsf(e2.y),fabsf(a.z)+fabsf(e1.z)+fabsf(e2.z)};
 // Include primitive extent even for an axis plane through the origin: its
 // normal component has zero coordinate error but traversal can still self-hit.
 float extent=fmaxf(fmaxf(fabsf(e1.x),fabsf(e1.y)),fmaxf(fabsf(e1.z),fmaxf(fabsf(e2.x),fmaxf(fabsf(e2.y),fabsf(e2.z)))));
 float d=16*0x1p-23f*(fabsf(h.normal.x)*error.x+fabsf(h.normal.y)*error.y+fabsf(h.normal.z)*error.z+extent);
 h.origin=add(p,mul(h.normal,d));
 if(h.normal.x!=0)h.origin.x=nextafterf(h.origin.x,h.normal.x>0?3.402823466e38f:-3.402823466e38f);
 if(h.normal.y!=0)h.origin.y=nextafterf(h.origin.y,h.normal.y>0?3.402823466e38f:-3.402823466e38f);
 if(h.normal.z!=0)h.origin.z=nextafterf(h.origin.z,h.normal.z>0?3.402823466e38f:-3.402823466e38f);
 h.below=add(p,mul(h.normal,-d));
 if(h.normal.x!=0)h.below.x=nextafterf(h.below.x,h.normal.x>0?-3.402823466e38f:3.402823466e38f);
 if(h.normal.y!=0)h.below.y=nextafterf(h.below.y,h.normal.y>0?-3.402823466e38f:3.402823466e38f);
 if(h.normal.z!=0)h.below.z=nextafterf(h.below.z,h.normal.z>0?-3.402823466e38f:3.402823466e38f);
 return finite(h.origin)&&finite(h.below);
}
struct State {
 mixed::Pixel film;surface::Ray ray{};Hit hit{};surface::Sample bsdf{};
 surface::V3 emission{},shadowOrigin{};U32 phase=Camera,visible=0,child=0;
 // A whole camera sample owns all indirect radiance until its terminal stage.
 double radiance[3]{},throughput[3]{1,1,1};U32 depth=0,primaryHit=0;
};
struct Batch {path::Epoch epoch{};U64 sequence=0;U32 revision=0,count=0,first=0,samples=0;State paths[mixed::Capacity]{};};
X2_HD inline void initialize(Batch& b,const mixed::Job& j){
 b.epoch=j.epoch;b.sequence=j.sequence;b.revision=0;b.count=j.count;b.first=j.first;b.samples=j.samples;
 for(U32 i=0;i<j.count;++i){b.paths[i]=State{};b.paths[i].film.pixel=j.pixels[i];}
}
X2_HD inline bool matches(const Batch& b,const mixed::Job& j){return path::equal(b.epoch,j.epoch)&&b.sequence==j.sequence&&b.count==j.count&&b.first==j.first&&b.samples==j.samples&&b.revision!=~0u;}
X2_HD inline bool active(U32 phase){return (phase>Camera&&phase<Complete)||phase==TextureWait;}
X2_HD inline void fail(State& s,U32 why){s.film.status=why;s.phase=Error;}
// One stage owns its effects. No film write until Finish; identities and pending
// visibility/emission remain in State across every yield. No resampling on resume.
template<class Backend>X2_HD inline void spatialStep(State& s,const mixed::Job& j,const mixed::Config& c,Backend& backend){
 using namespace surface;
 if(c.surfaceLimit==0||c.surfaceLimit>8){fail(s,30);return;}
 sample::Identity id{s.film.pixel,j.first+s.film.count,c.seed,0};
 switch(s.phase){
 case Camera:{s.depth=s.primaryHit=s.child=0;for(int k=0;k<3;++k){s.radiance[k]=0;s.throughput[k]=1;}
  float x,y;if(!filter(c.filter,c.filterWidth,sample::draw(id,0,c.sampling),x)||!filter(c.filter,c.filterWidth,sample::draw(id,1,c.sampling),y)||!cameraRay(c.camera,float(s.film.pixel%c.width)+x,float(s.film.pixel/c.width)+y,s.ray)){fail(s,31);return;}s.phase=Trace;break;}
 case Trace:s.hit=backend.trace(s.ray);s.child=0;
  if(s.hit.geom==~0u){if(s.depth){s.radiance[0]+=s.throughput[0]*c.sky.x;s.radiance[1]+=s.throughput[1]*c.sky.y;s.radiance[2]+=s.throughput[2]*c.sky.z;}s.phase=Finish;}
  else {if(!s.depth)s.primaryHit=1;s.phase=Shade;}break;
 case Shade:{Lambert mat;unsigned dim=16+2*s.depth;
  unsigned status=backend.material(s.hit,s.ray,mat);if(status==tex::Miss){s.phase=TextureWait;return;}if(status!=tex::Ready||!lambert(mat,s.hit.normal,sample::draw(id,dim,c.sampling),sample::draw(id,dim+1,c.sampling),s.bsdf)){fail(s,32);return;}
  s.radiance[0]+=s.throughput[0]*mat.emission.x;s.radiance[1]+=s.throughput[1]*mat.emission.y;s.radiance[2]+=s.throughput[2]*mat.emission.z;
  if(s.bsdf.pdf<=0){s.phase=Finish;break;}
  s.throughput[0]*=s.bsdf.f.x/s.bsdf.pdf;s.throughput[1]*=s.bsdf.f.y/s.bsdf.pdf;s.throughput[2]*=s.bsdf.f.z/s.bsdf.pdf;
  s.shadowOrigin=s.hit.origin;s.child=1;
  if(++s.depth==c.surfaceLimit){s.phase=Shadow;}
  else{s.ray={s.hit.origin,s.bsdf.wi,{},{},0,3.402823466e38f};s.phase=Trace;}break;}
 case Shadow:if(backend.visible(s.shadowOrigin,s.bsdf.wi)){s.radiance[0]+=s.throughput[0]*c.sky.x;s.radiance[1]+=s.throughput[1]*c.sky.y;s.radiance[2]+=s.throughput[2]*c.sky.z;}s.child=0;s.phase=Finish;break;
 case Finish:if(s.child){fail(s,33);return;}for(int k=0;k<3;++k)s.film.sum[k]+=s.radiance[k];s.film.sum[3]+=s.primaryHit;++s.film.count;s.phase=s.film.count==j.samples?Complete:Camera;break;
 default:fail(s,34);break;
 }
}
template<class Backend>X2_HD inline void step(State& s,const mixed::Job& j,const mixed::Config& c,Backend& backend){
 if(s.phase>=Complete)return;
 if(s.film.count>=j.samples||s.film.pixel>=c.width*c.height){fail(s,10);return;}
 if(c.spatial){spatialStep(s,j,c,backend);return;}
 sample::Identity id{s.film.pixel,j.first+s.film.count,c.seed,0};
 switch(s.phase){
 case Camera:{float x,y;if(!surface::filter(c.filter,c.filterWidth,sample::draw(id,0,c.sampling),x)||!surface::filter(c.filter,c.filterWidth,sample::draw(id,1,c.sampling),y)){fail(s,2);return;}
  if(!surface::cameraRay(c.camera,float(s.film.pixel%c.width)+x,float(s.film.pixel/c.width)+y,s.ray)){fail(s,3);return;}
  s.phase=Trace;break;}
 case Trace:s.hit=backend.trace(s.ray);s.phase=s.hit.geom==~0u?Finish:Shade;break;
 case Shade:{surface::Lambert mat;unsigned status=backend.material(s.hit,s.ray,mat);if(status==tex::Miss){s.phase=TextureWait;return;}if(status!=tex::Ready||!surface::lambert(mat,s.hit.normal,sample::draw(id,16,c.sampling),sample::draw(id,17,c.sampling),s.bsdf)){fail(s,5);return;}
  s.emission=mat.emission;s.shadowOrigin=surface::add(s.ray.origin,surface::mul(s.ray.direction,s.hit.t));s.shadowOrigin.z=0x1p-126f;s.child=1;s.phase=Shadow;break;}
 case Shadow:s.visible=backend.visible(s.shadowOrigin,s.bsdf.wi)?1:0;s.child=0;s.phase=Finish;break;
 case Finish:
  if(s.child){fail(s,11);return;}
  if(s.hit.geom!=~0u){if(s.visible&&s.bsdf.pdf>0){s.film.sum[0]+=double(s.bsdf.f.x/s.bsdf.pdf)*c.sky.x;s.film.sum[1]+=double(s.bsdf.f.y/s.bsdf.pdf)*c.sky.y;s.film.sum[2]+=double(s.bsdf.f.z/s.bsdf.pdf)*c.sky.z;}
   s.film.sum[0]+=s.emission.x;s.film.sum[1]+=s.emission.y;s.film.sum[2]+=s.emission.z;s.film.sum[3]+=1;}
  ++s.film.count;s.visible=0;s.phase=s.film.count==j.samples?Complete:Camera;break;
 default:fail(s,12);break;
 }
}
#if !defined(__CUDACC_RTC__)
// The image packet and transferred state must describe exactly the same fence.
// This validates metadata and numerical state before granting CPU ownership.
inline bool validateMigration(const Batch& b,const mixed::Job& j,const mixed::Result& r){
 if(!matches(b,j)||b.revision!=r.pad||!path::equal(r.epoch,j.epoch)||r.sequence!=j.sequence||r.count!=j.count)return false;
 for(unsigned i=0;i<j.count;++i){const auto& s=b.paths[i];const auto& p=r.pixels[i];if(s.film.pixel!=j.pixels[i]||s.film.pixel!=p.pixel||s.film.count!=p.count||s.film.status||p.status||s.phase!=p.pad||s.film.count>j.samples||s.phase==Error||s.phase>TextureWait)return false;
  if((s.phase==Complete)!=(s.film.count==j.samples))return false;for(unsigned c=0;c<4;++c)if(s.film.sum[c]!=p.sum[c]||!(p.sum[c]<=1.7976931348623157e308&&p.sum[c]>=-1.7976931348623157e308))return false;
  if(s.phase==TextureWait&&(s.child||s.hit.geom==~0u))return false;
  if(s.phase!=Camera&&s.phase!=Complete){if(!surface::finite(s.ray.origin)||!surface::finite(s.ray.direction)||!surface::finite(s.ray.dx)||!surface::finite(s.ray.dy)||!surface::finite(s.hit.normal)||!surface::finite(s.hit.t)||!surface::finite(s.hit.u)||!surface::finite(s.hit.v))return false;}
 }
 return true;
}
#endif
X2_HD inline mixed::Pixel snapshot(const State& s){auto p=s.film;p.pad=s.phase;return p;}
}
