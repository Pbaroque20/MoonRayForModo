#pragma once
#include "surface_core.h"
namespace xpu2 { namespace interactive {
X2_HD inline void surfaceFixture(unsigned i,float* row){
 sample::Identity id{i*2654435761u,i,0x1feedee3ull,0};
 float u=sample::unit(sample::word(id,0)),v=sample::unit(sample::word(id,1)),width=1+3*sample::unit(sample::word(id,2));
 for(unsigned f=0;f<3;++f)surface::filter(surface::Filter(f),width,u,row[f]);
 surface::V3 normal;surface::normalize({2*u-1,2*v-1,(i&1)?-.7f:.7f},normal);
 surface::Sample s;surface::lambert({{.7f,.03f,.4f}},normal,u,v,s);
 row[3]=s.wi.x;row[4]=s.wi.y;row[5]=s.wi.z;row[6]=s.f.x;row[7]=s.f.y;row[8]=s.f.z;row[9]=s.pdf;
 surface::Camera cam{};for(int c=0;c<4;++c)cam.rasterToCamera.m[c][c]=cam.cameraToRender.m[c][c]=1;
 cam.rasterToCamera.m[0][0]=cam.rasterToCamera.m[1][1]=.01125f;cam.rasterToCamera.m[3][0]=-.36f;cam.rasterToCamera.m[3][1]=-.27f;
 cam.cameraToRender.m[3][2]=4;cam.nearClip=.001f;cam.farClip=1000;
 surface::Ray ray;surface::cameraRay(cam,(i%64)+u,((i/64)%48)+v,ray);
 row[10]=ray.direction.x;row[11]=ray.direction.y;row[12]=ray.direction.z;row[13]=ray.dx.x;row[14]=ray.dy.y;row[15]=ray.nearT;
}
}}
