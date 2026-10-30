// Private shared triangle coordinates. Traversal bounds remain on Embree/OptiX.
#pragma once
#include "surface_core.h"
namespace xpu2::interactive::triangle {
struct Coordinates {double t,u,v;};
X2_HD inline bool coordinates(const surface::Ray& ray,surface::V3 a,surface::V3 b,surface::V3 c,Coordinates& out){
 double ax=a.x,ay=a.y,az=a.z;
 double ex=double(b.x)-ax,ey=double(b.y)-ay,ez=double(b.z)-az;
 double fx=double(c.x)-ax,fy=double(c.y)-ay,fz=double(c.z)-az;
 double dx=ray.direction.x,dy=ray.direction.y,dz=ray.direction.z;
 double px=dy*fz-dz*fy,py=dz*fx-dx*fz,pz=dx*fy-dy*fx;
 double determinant=(ex*px+ey*py)+ez*pz;
 if(determinant==0)return false;
 double tx=double(ray.origin.x)-ax,ty=double(ray.origin.y)-ay,tz=double(ray.origin.z)-az;
 double qx=ty*ez-tz*ey,qy=tz*ex-tx*ez,qz=tx*ey-ty*ex;
 double u=((tx*px+ty*py)+tz*pz)/determinant;
 double v=((dx*qx+dy*qy)+dz*qz)/determinant;
 double t=((fx*qx+fy*qy)+fz*qz)/determinant;
 if(!surface::finite(float(t))||!surface::finite(float(u))||!surface::finite(float(v)))return false;
 out={t,u,v};return true;
}
// Round traversal distance outward so a closer candidate is never culled merely
// because both distances occupy the same float bin. Exact distance and IDs pick
// the winner independently of BVH visitation order.
X2_HD inline float upperDistance(double t){float f=float(t);return double(f)<t?nextafterf(f,3.402823466e38f):f;}
X2_HD inline bool nearer(double t,unsigned g,unsigned p,double best,unsigned bg,unsigned bp){return t<best||(t==best&&(g<bg||(g==bg&&p<bp)));}
// No expanded edge tolerance: test the actual triangle and caller's ray interval.
X2_HD inline bool contains(const Coordinates& h,const surface::Ray& ray){return h.u>=0&&h.v>=0&&h.u+h.v<=1&&h.t>=ray.nearT&&h.t<=ray.farT;}
}
