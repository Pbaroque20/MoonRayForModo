// Experimental static-triangle image fixture, not a general scene importer.
#include "surface_core.h"
#include "sample_tree.h"
#include <embree4/rtcore.h>
#include <fstream>
#include <thread>
#include <atomic>
#include <cstdio>
using namespace xpu2::interactive;
using surface::V3;
constexpr unsigned W=64,H=48,Spp=256;
static void check(bool v){if(!v)throw std::runtime_error("Fixture failed");}
int main(int argc,char** argv){
 if(argc!=4)return 2;unsigned threads=unsigned(std::stoul(argv[2])),frame=unsigned(std::stoul(argv[3]));if(!threads||threads>12)return 2;
 RTCDevice device=rtcNewDevice(nullptr);check(device);RTCScene scene=rtcNewScene(device);check(scene);
 RTCGeometry geom=rtcNewGeometry(device,RTC_GEOMETRY_TYPE_TRIANGLE);check(geom);
 auto* verts=(V3*)rtcSetNewGeometryBuffer(geom,RTC_BUFFER_TYPE_VERTEX,0,RTC_FORMAT_FLOAT3,sizeof(V3),9);
 for(int y=0;y<3;++y)for(int x=0;x<3;++x)verts[y*3+x]={float((x-1)*10),float((y-1)*10),0};
 struct Tri{unsigned a,b,c;};auto* tris=(Tri*)rtcSetNewGeometryBuffer(geom,RTC_BUFFER_TYPE_INDEX,0,RTC_FORMAT_UINT3,sizeof(Tri),8);
 for(unsigned q=0;q<4;++q){unsigned v=(q/2)*3+q%2;tris[2*q]={v,v+1,v+4};tris[2*q+1]={v,v+4,v+3};}
 rtcCommitGeometry(geom);rtcAttachGeometry(scene,geom);rtcReleaseGeometry(geom);rtcCommitScene(scene);check(rtcGetDeviceError(device)==RTC_ERROR_NONE);
 surface::Camera camera{};for(int i=0;i<4;++i)camera.rasterToCamera.m[i][i]=camera.cameraToRender.m[i][i]=1;
 camera.rasterToCamera.m[0][0]=camera.rasterToCamera.m[1][1]=.72f/W;
 camera.rasterToCamera.m[3][0]=-.36f;camera.rasterToCamera.m[3][1]=-.36f*H/W;camera.cameraToRender.m[3][2]=4;
 camera.nearClip=.001f;camera.farClip=1000;
 surface::Lambert materials[]={{{.7f,.03f,.4f}},{{.08f,.6f,.12f}},{{.12f,.2f,.8f}},{{.6f,.6f,.6f}}};
 V3 sky={.8f,.7f,.6f};film::Tree film({123,1,frame+1ull,1},W*H,threads);
 std::atomic<unsigned> next{0},failed{0};std::vector<std::thread> workers;
 for(unsigned w=0;w<threads;++w)workers.emplace_back([&]{try{for(unsigned pixel;(pixel=next.fetch_add(1))<W*H;){
  for(unsigned s=0;s<Spp;++s){film::Handle root;sample::Identity id;check(film.begin(pixel,surface::frameSeed(frame,0,false),root,id)==film::Status::Ok);
   float x,y;check(surface::filter(surface::Filter::Box,1,sample::unit(sample::word(id,0)),x));check(surface::filter(surface::Filter::Box,1,sample::unit(sample::word(id,1)),y));
   surface::Ray ray;check(surface::cameraRay(camera,float(pixel%W)+x,float(pixel/W)+y,ray));
   RTCRayHit hit{};hit.ray.org_x=ray.origin.x;hit.ray.org_y=ray.origin.y;hit.ray.org_z=ray.origin.z;
   hit.ray.dir_x=ray.direction.x;hit.ray.dir_y=ray.direction.y;hit.ray.dir_z=ray.direction.z;hit.ray.tnear=ray.nearT;hit.ray.tfar=ray.farT;hit.ray.mask=~0u;hit.hit.geomID=RTC_INVALID_GEOMETRY_ID;
   RTCIntersectArguments args;rtcInitIntersectArguments(&args);rtcIntersect1(scene,&hit,&args);check(hit.hit.geomID!=RTC_INVALID_GEOMETRY_ID);
   V3 normal;check(surface::normalize({hit.hit.Ng_x,hit.hit.Ng_y,hit.hit.Ng_z},normal));
   path::Record record{};record.epoch=root.epoch;record.id=id;path::Stage stage(record);float u,v;check(stage.random(u)&&stage.random(v));
   surface::Sample material;check(surface::lambert(materials[hit.hit.primID/2],normal,u,v,material));check(stage.emit({0,{0,0,0,1}}));
   V3 origin=surface::add(surface::add(ray.origin,surface::mul(ray.direction,hit.ray.tfar)),surface::mul(normal,.001f));
   path::Ray childRay{{origin.x,origin.y,origin.z},{material.wi.x,material.wi.y,material.wi.z},0,1000,0};
   check(stage.spawn(0,childRay,0));path::Effects effects;check(stage.commit(record,effects,root.epoch,true));std::array<film::Handle,15> children;
   check(film.finish(root,effects,children)==film::Status::Ok);
   RTCRay shadow{};shadow.org_x=origin.x;shadow.org_y=origin.y;shadow.org_z=origin.z;
   shadow.dir_x=material.wi.x;shadow.dir_y=material.wi.y;shadow.dir_z=material.wi.z;shadow.tnear=0;shadow.tfar=1000;shadow.mask=~0u;
   RTCOccludedArguments oa;rtcInitOccludedArguments(&oa);rtcOccluded1(scene,&shadow,&oa);
   path::Effects light{};light.valueCount=1;
   if(shadow.tfar>=0&&material.pdf>0)light.values[0]={0,{double(material.f.x/material.pdf)*sky.x,double(material.f.y/material.pdf)*sky.y,double(material.f.z/material.pdf)*sky.z,0}};
   check(film.finish(children[0],light,children)==film::Status::Ok);
  }
 } }catch(...){++failed;}});
 for(auto& w:workers)w.join();check(!failed);auto audit=film.audit();check(audit.started==W*H*Spp&&audit.completed==audit.started&&audit.active==0);
 auto image=film.snapshot();std::ofstream output(argv[1],std::ios::binary);check(bool(output));
 for(auto& pixel:image){check(pixel.count==Spp);float rgba[4];for(int c=0;c<4;++c)rgba[c]=float(pixel.sum[c]/pixel.count);output.write((char*)rgba,sizeof(rgba));}output.close();check(bool(output));
 check(rtcGetDeviceError(device)==RTC_ERROR_NONE);rtcReleaseScene(scene);rtcReleaseDevice(device);
 std::printf("{\"width\":%u,\"height\":%u,\"spp\":%u,\"threads\":%u,\"frame\":%u,\"started\":%llu,\"completed\":%llu,\"active\":%llu,\"tier\":\"experimental-unqualified-raw\"}\n",W,H,Spp,threads,frame,audit.started,audit.completed,audit.active);
}
