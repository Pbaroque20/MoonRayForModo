// Private shared CPU/CUDA surface subset. Derived from MoonRay Apache-2.0
// PixelFilter.h, Sampling.ispc, ReferenceFrame.h and BsdfLambert.h.
// Copyright 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include "sample_stream.h"
#if !defined(__CUDACC_RTC__)
#include <math.h>
#endif
namespace xpu2 { namespace interactive { namespace surface {
struct V3 { float x,y,z; };
struct Triangle { unsigned a,b,c; };
X2_HD inline V3 cross(V3 a,V3 b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
X2_HD inline V3 add(V3 a,V3 b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
X2_HD inline V3 mul(V3 a,float b){return {a.x*b,a.y*b,a.z*b};}
X2_HD inline float dot(V3 a,V3 b){return (a.x*b.x+a.y*b.y)+a.z*b.z;}
X2_HD inline bool finite(float a){return a==a && a<=3.402823466e38f && a>=-3.402823466e38f;}
X2_HD inline bool finite(V3 a){return finite(a.x)&&finite(a.y)&&finite(a.z);}
X2_HD inline bool normalize(V3 a,V3& b){float l=dot(a,a);if(!finite(l)||l<=0)return false;b=mul(a,1.0f/sqrtf(l));return true;}
constexpr float Pi=3.14159265358979323846f,InvPi=0.31830988618379067154f;
// Same frame/eye/lock mapping as MoonRay RenderContext::getInitialSeed.
X2_HD inline sample::U32 frameSeed(sample::U32 frame,sample::U32 eye,bool lock){
    return lock?0u:(frame+8429u)*(2u*(1193047u+eye+6037u)+1u);
}
enum class Filter:unsigned {Box=0,Cubic=1,Quadratic=2};
// Fixed software root on [0,1]. Identical operations on both devices; no pow
// library discrepancy. Filter conformance uses an explicit absolute tolerance.
X2_HD inline float cubeRootUnit(float x){
    if(x==0 || x==1)return x;
    float lo=0,hi=1;
    for(int i=0;i<32;++i){float m=(lo+hi)*.5f;if((m*m)*m<x)lo=m;else hi=m;}
    return (lo+hi)*.5f;
}
X2_HD inline float cubicMiddle(float r){
    float u=r;
    for(int i=0;i<5;++i)u=(11*r+u*u*(6+u*(8-9*u)))/(4+12*u*(1+u*(1-u)));
    return u;
}
X2_HD inline bool filter(Filter kind,float width,float r,float& out){
    if(!finite(width)||width<=0 || !finite(r)||r<0||r>1)return false;
    float v=0;
    if(kind==Filter::Box){out=(r-.5f)*width+.5f;return finite(out);}
    if(kind==Filter::Cubic){
        if(r<1.f/24)v=sqrtf(sqrtf(24*r))-2;
        else if(r<.5f)v=cubicMiddle(24.f/11*(r-1.f/24))-1;
        else if(r<23.f/24)v=1-cubicMiddle(24.f/11*(23.f/24-r));
        else v=2-sqrtf(sqrtf(24*(1-r)));
        out=v*(width/4)+.5f;
    }else if(kind==Filter::Quadratic){
        if(r<1.f/6)v=cubeRootUnit(6*r)-1.5f;
        else if(r<5.f/6){v=(6*r-3)/4;for(int i=0;i<4;++i)v=(8*v*v*v-12*r+6)/(12*v*v-9);}
        else v=1.5f-cubeRootUnit(6*(1-r));
        out=v*(width/3)+.5f;
    }else return false;
    return finite(out);
}
// Prepared matrices use MoonRay/scene_rdl2 row-vector convention. Host adapter
// supplies inverse(projection * screen-to-raster), copied into immutable data.
struct Matrix { float m[4][4]; };
// MoonRay's camera types (pbr/camera); camera_core.h makes the path tracer's rays for each.
enum CameraType : unsigned {CameraPerspective=0,CameraOrthographic=1,CameraSpherical=2,CameraFisheye=3,CameraDome=4,CameraBake=5};
struct Camera {Matrix rasterToCamera,cameraToRender; float nearClip,farClip;
    // The rest of MoonRay's camera (camera_core.h): its type, the region window's offset into the aperture window
    // (Camera::createRay) and the aperture window's size, the stereo eye (PerspectiveCamera's focal point, camera
    // space), the lens (ProjectiveCamera's depth of field, LensDistribution's bokeh: 0 disk, 1 polygon, 2 image),
    // and the other types' settings (k, flags and mode; camera_core.h says which). bokehImage is a lights::Image,
    // map a DomeMaster3D interocular map or a BakeCamera's position map (camera_core.h's CameraMap).
    unsigned type=CameraPerspective;float regionX=0,regionY=0,apertureWidth=0,apertureHeight=0;
    V3 focalPoint{0,0,0};
    unsigned dof=0,bokeh=0;int bokehSides=0;float lensRadius=0,focusDistance=0,bokehAngle=0;
    const void* bokehImage=nullptr;
    unsigned flags=0;int mode=0;float k[12]={0,0,0,0,0,0,0,0,0,0,0,0};
    const void* map=nullptr;};
// mask: rdl2's VisibilityType bits of the ray (CAMERA, SHADOW, a lobe type's), which a geometry's visibility must share.
// ox, oy: the auxiliary rays' origins less the ray's (an orthographic or bake camera's; zero for rays from one point).
struct Ray {V3 origin,direction,dx,dy;float nearT,farT;unsigned mask=0xffffffffu;V3 ox{0,0,0},oy{0,0,0};};
X2_HD inline V3 vector(const Matrix& m,V3 a){return {
    (a.x*m.m[0][0]+a.y*m.m[1][0])+a.z*m.m[2][0],
    (a.x*m.m[0][1]+a.y*m.m[1][1])+a.z*m.m[2][1],
    (a.x*m.m[0][2]+a.y*m.m[1][2])+a.z*m.m[2][2]};}
X2_HD inline bool point(const Matrix& m,V3 a,V3& out){
    V3 v=add(vector(m,a),{m.m[3][0],m.m[3][1],m.m[3][2]});
    float w=((a.x*m.m[0][3]+a.y*m.m[1][3])+a.z*m.m[2][3])+m.m[3][3];
    if(!finite(w)||w==0)return false;out=mul(v,1.f/w);return finite(out);
}
X2_HD inline bool cameraRay(const Camera& c,float x,float y,Ray& out){
    if(!finite(x)||!finite(y)||!finite(c.nearClip)||!finite(c.farClip)||c.nearClip<=0||c.farClip<=c.nearClip)return false;
    Ray v{};V3 d,dx,dy,n;
    if(!point(c.rasterToCamera,{x,y,-1},d)||!point(c.rasterToCamera,{x+1,y,-1},dx)||
       !point(c.rasterToCamera,{x,y+1,-1},dy)||!normalize(d,n)||n.z>=0)return false;
    if(!point(c.cameraToRender,{0,0,0},v.origin)||!normalize(vector(c.cameraToRender,d),v.direction)||
       !normalize(vector(c.cameraToRender,dx),v.dx)||!normalize(vector(c.cameraToRender,dy),v.dy))return false;
    v.nearT=-c.nearClip/n.z;v.farT=-c.farClip/n.z;
    if(!finite(v.nearT)||!finite(v.farT))return false;out=v;return true;
}
// Constant opaque diffuse-only USD Preview Surface subset. Admission MUST reject
// dielectric/metal/coat/maps/normal changes until their own port exists.
struct Lambert {V3 albedo;V3 emission{0,0,0};};
struct Sample {V3 wi,f;float pdf;};
X2_HD inline V3 localToGlobal(V3 n,V3 p){
    float sign=copysignf(1.f,n.z),a=-1/(sign+n.z),b=n.x*n.y*a;
    V3 x={1+sign*n.x*n.x*a,sign*b,-sign*n.x},y={b,sign+n.y*n.y*a,-n.y};
    return add(add(mul(x,p.x),mul(y,p.y)),mul(n,p.z));
}
// Shared sine/cosine polynomial (ISPC 1.31 coefficients, Intel BSD-3-Clause).
// Domain [0,2*pi], no intrinsic trig or hardware texture operation.
X2_HD inline void sincosSample(float angle,float& sn,float& cs){
    float kf=floorf(angle*.6366197466850281f),x=angle-kf*1.5707963705062866f,x2=x*x;
    int k=int(kf)&3;
    float s=-2.5029327943570934e-8f;s=s*x2+.000002760012648650445f;s=s*x2-.00019842604524455965f;
    s=s*x2+.008333347737789154f;s=s*x2-.1666666716337204f;s=(s*x2+1)*x;
    float c=-.0000002596301840185333f;c=c*x2+.000024756234779488295f;c=c*x2-.001388833043165505f;
    c=c*x2+.04166664183139801f;c=c*x2-.5f;c=c*x2+1;
    sn=k==0?s:k==1?c:k==2?-s:-c;cs=k==0?c:k==1?-s:k==2?-c:s;
}
X2_HD inline bool lambert(const Lambert& mat,V3 normal,float u,float v,Sample& out){
    if(!finite(mat.albedo)||mat.albedo.x<0||mat.albedo.y<0||mat.albedo.z<0||
       !finite(normal)||fabsf(dot(normal,normal)-1)>2e-5f||!finite(u)||!finite(v)||u<0||u>1||v<0||v>1)return false;
    float sn,cs;sincosSample(v*(2*Pi),sn,cs);float s=sqrtf(1-u);
    Sample r{};r.wi=localToGlobal(normal,{s*cs,s*sn,sqrtf(u)});
    float cosine=fmaxf(dot(normal,r.wi),0);r.pdf=cosine*InvPi;
    r.f=mul(mul(mat.albedo,InvPi),cosine);out=r;return true;
}
}}}
