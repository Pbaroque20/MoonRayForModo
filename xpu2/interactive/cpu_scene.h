// Private experimental canonical-scene adapter. Preparation is NOT qualification.
#pragma once
#include "canonical_session.h"
#include "surface_core.h"
#include "light_core.h"
#include "shade_material.h"
#include "curve_core.h"
#include "volume_core.h"
#include <cstdlib>
#include <cstring>
#include <fstream>
#include "host_texture.h"
#include <cmath>
#include <map>
#include <array>
#include <functional>
#include <set>
#include <mutex>
namespace xpu2::interactive::cpu {
namespace rdl=scene_rdl2::rdl2;
using surface::V3;
struct Unsupported:std::runtime_error{using std::runtime_error::runtime_error;};
inline void need(bool ok,const std::string& why){if(!ok)throw Unsupported(why);}
// Fixed diagnostic text needs no heap allocation on successful validation.
inline void need(bool ok,const char* why){if(!ok)throw Unsupported(why);}
using Tri=surface::Triangle;
enum class Domain {Planar,DiffuseMesh,PlanarTextures,SurfaceTextures};
inline bool isSpatial(Domain d){return d==Domain::DiffuseMesh||d==Domain::SurfaceTextures;}
inline bool gpuTextures(Domain d){return d==Domain::PlanarTextures||d==Domain::SurfaceTextures;}
struct MeshData {std::string name;std::vector<V3> positions;std::vector<Tri> triangles;std::vector<std::shared_ptr<const ix::Buffer>> signature;
 // The path tracer's shading attributes (shade::MeshAttributes): render-space normals and texture coordinates.
 std::vector<V3> normals;std::vector<float> uvs;unsigned normalRate=shade::RateNone,uvRate=shade::RateNone;
 float worldToObject[12]={1,0,0,0,0,1,0,0,0,0,1,0};
 // Its primitive attributes (UserData) and their values.
 std::vector<shade::PrimAttr> prims;std::vector<float> primData;
 // A curve set in place of triangles (curve_core.h's curves::Set): its type (curves::Basis, BasisNone for a mesh),
 // whether round, the flat cubic programs' quads a span; the control points (x, y, z, radius, render space), the
 // spans (first control point, curve, place along the curve) and each curve's span count.
 unsigned curveBasis=0,curveRound=0,curveSegments=4;std::vector<float> curvePoints;std::vector<unsigned> curveSpans,curveSpanCounts;};
// A mesh: its data, its material (~0u: none, a volume alone), and the volume it bounds (volume_core.h; -1: none).
struct Mesh {std::shared_ptr<const MeshData> data;unsigned material;int volume=-1;};
// A plan mesh's curve set (curve_core.h) over its own arrays (host memory).
inline curves::Set curveSet(const MeshData& m){curves::Set c;if(!m.curveBasis)return c;
 c.points=m.curvePoints.data();c.spans=m.curveSpans.data();c.curveSpans=m.curveSpanCounts.data();c.spanCount=unsigned(m.curveSpans.size()/3);
 c.pointCount=unsigned(m.curvePoints.size()/4);c.basis=m.curveBasis;c.round=m.curveRound;c.segments=m.curveSegments;return c;}
struct Plan {
    CanonicalView source;surface::Camera camera{};unsigned width=0,height=0,spp=0,seed=0,sampling=3;
    surface::Filter filter=surface::Filter::Box;float filterWidth=1;
    Domain domain=Domain::Planar;unsigned surfaceLimit=1;
    std::vector<surface::Lambert> materials;std::map<unsigned,texture::Binding> diffuseMaps,emissionMaps;std::vector<Mesh> meshes;V3 sky{};
    size_t bytes=0,reusedMeshes=0,preparedMeshes=0;
    // No production route changes merely because preparation succeeds.
    bool qualified=false;
    // MoonRay adaptive sampling (sampling_mode 2), admitted only where the caller
    // renders it (the asynchronous renderer); spp is then the maximum.
    bool adaptive=false;unsigned minSamples=0,maxSamples=0;float targetError=0;
    // MoonRay's path tracer (PATH_TRACER.md), admitted only where the caller
    // renders it (the asynchronous renderer): its lights, each mesh's light set
    // as a mask over them, and the integrator's settings.
    bool paths=false;std::vector<lights::Light> lights;std::vector<unsigned> meshLights;
    unsigned bsdfSamples=1,lightSamples=1,maxDepth=0,maxDiffuseDepth=0,clampDepth=1;float rrThreshold=0,clampValue=0;
    unsigned maxGlossyDepth=0,maxMirrorDepth=0,maxHairDepth=0,maxPresenceDepth=0,shadowTerminatorFix=0;float roughnessClamping=0,transparencyThreshold=1;
    unsigned bssrdfSamples=4,maxSubsurfacePerPath=1,enableSss=1;
    // The path tracer's materials (shade_material.h): one record per material, parameters in a pool.
    std::vector<shade::MaterialRecord> materialRecords;std::vector<float> materialPool;
    // World to MoonRay's render space: the camera's space at its first motion step (3x4 rows).
    float worldToRender[12]={1,0,0,0,0,1,0,0,0,0,1,0};
    // The volumes bound to meshes (volume_core.h), and MoonRay's volume scene variables.
    std::vector<volume::Shader> volumes;unsigned maxVolumeDepth=1,volumeIlluminationSamples=4,volumeOverlapMode=0;
    float volumeTransmittanceThreshold=0.005f,volumeAttenuationFactor=0.65f,volumeContributionFactor=0.65f,volumePhaseAttenuationFactor=0.5f;
    // The DwaBase parameter slots the deepest material tree needs (shade_dwalayer.h); whether a material has glitter
    // (the shading threads then need a glitter scratch, shade_glitter.h).
    unsigned dwaSlots=0;bool glitter=false;
    // A random-walk subsurface material, and then MoonRay's integrator sequences its walk draws from (walkSequences).
    bool randomWalk=false;std::shared_ptr<const std::vector<float>> walkSequences;
    // The textures the path tracer's maps read (shade_mapnodes.h): each file once, and its host mip pyramid.
    std::vector<std::shared_ptr<texture::File>> textures;std::vector<const tex::Image*> textureImages;
};
using PlanView=std::shared_ptr<const Plan>;
// What a scene may hold: room for scenes from Modo (an RTX 3090 holds this much several times over).
struct Limits {size_t vertices=16000000,triangles=16000000,bytes=1ull<<30,objects=1000000,pixels=8388608;};
template<class T>inline T get(const rdl::SceneObject& o,const char* name){return o.get<T>(name);}
template<class T>inline T get(const rdl::SceneObject& o,const std::string& name){return o.get<T>(name);}
struct State {bool isDefault,stationary;};
template<class T>inline bool equal(const T& a,const T& b){return a==b;}
inline bool equal(const rdl::SceneObjectIndexable& a,const rdl::SceneObjectIndexable& b){return a.size()==b.size()&&std::equal(a.begin(),a.end(),b.begin());}
template<class T>inline State state(const rdl::SceneObject& o,const rdl::Attribute& a){
 const auto& begin=o.get<T>(a.getName(),rdl::TIMESTEP_BEGIN);
 const auto& end=o.get<T>(a.getName(),a.isBlurrable()?rdl::TIMESTEP_END:rdl::TIMESTEP_BEGIN);
 // Exact value comparisons, with no temporary serialization or padding reads.
 // Object pointers are compared only within this one canonical replica.
 const auto& defaults=a.getDefaultValue<T>();
 bool stationary=!a.isBlurrable()||equal(begin,end);
 return {stationary&&equal(begin,defaults),stationary};
}
inline State state(const rdl::SceneObject& o,const rdl::Attribute& a){
#define CASE(K,T) case rdl::K:return state<rdl::T>(o,a);
 switch(a.getType()){
 CASE(TYPE_BOOL,Bool) CASE(TYPE_INT,Int) CASE(TYPE_LONG,Long) CASE(TYPE_FLOAT,Float) CASE(TYPE_DOUBLE,Double) CASE(TYPE_STRING,String)
 CASE(TYPE_RGB,Rgb) CASE(TYPE_RGBA,Rgba) CASE(TYPE_VEC2F,Vec2f) CASE(TYPE_VEC2D,Vec2d) CASE(TYPE_VEC3F,Vec3f) CASE(TYPE_VEC3D,Vec3d) CASE(TYPE_VEC4F,Vec4f) CASE(TYPE_VEC4D,Vec4d)
 CASE(TYPE_MAT3F,Mat3f) CASE(TYPE_MAT3D,Mat3d) CASE(TYPE_MAT4F,Mat4f) CASE(TYPE_MAT4D,Mat4d) CASE(TYPE_SCENE_OBJECT,SceneObject*)
 CASE(TYPE_BOOL_VECTOR,BoolVector) CASE(TYPE_INT_VECTOR,IntVector) CASE(TYPE_LONG_VECTOR,LongVector) CASE(TYPE_FLOAT_VECTOR,FloatVector) CASE(TYPE_DOUBLE_VECTOR,DoubleVector) CASE(TYPE_STRING_VECTOR,StringVector)
 CASE(TYPE_RGB_VECTOR,RgbVector) CASE(TYPE_RGBA_VECTOR,RgbaVector) CASE(TYPE_VEC2F_VECTOR,Vec2fVector) CASE(TYPE_VEC2D_VECTOR,Vec2dVector) CASE(TYPE_VEC3F_VECTOR,Vec3fVector) CASE(TYPE_VEC3D_VECTOR,Vec3dVector) CASE(TYPE_VEC4F_VECTOR,Vec4fVector) CASE(TYPE_VEC4D_VECTOR,Vec4dVector)
 CASE(TYPE_MAT3F_VECTOR,Mat3fVector) CASE(TYPE_MAT3D_VECTOR,Mat3dVector) CASE(TYPE_MAT4F_VECTOR,Mat4fVector) CASE(TYPE_MAT4D_VECTOR,Mat4dVector) CASE(TYPE_SCENE_OBJECT_VECTOR,SceneObjectVector) CASE(TYPE_SCENE_OBJECT_INDEXABLE,SceneObjectIndexable)
 default:throw Unsupported(o.getName()+" / unknown attribute type");}
#undef CASE
}
inline void attributes(const rdl::SceneObject& obj,const std::set<std::string>& changed,const std::set<std::string>& bindings={}){
 for(auto i=obj.getSceneClass().beginAttributes();i!=obj.getSceneClass().endAttributes();++i){auto& a=**i;
  std::string why=obj.getName()+" / "+a.getName();
  need(!a.isBindable()||!obj.getBinding(a)||bindings.count(a.getName()),why+": map binding unsupported");
  auto s=state(obj,a);need(s.stationary,why+": animated value unsupported");
  need(s.isDefault||changed.count(a.getName()),why+": nondefault setting unsupported");
 }
}
inline bool zero(rdl::Rgb c){return c.r==0&&c.g==0&&c.b==0;}
inline V3 color(rdl::Rgb c){V3 v{c.r,c.g,c.b};need(surface::finite(v)&&v.x>=0&&v.y>=0&&v.z>=0,"Invalid color");return v;}
inline rdl::Mat4d translation(const rdl::SceneObject& obj){
 auto m=get<rdl::Mat4d>(obj,"node_xform");
 for(int i=0;i<4;++i)for(int j=0;j<4;++j){need(std::isfinite(m[i][j]),obj.getName()+": nonfinite transform");if(i==3&&j<3)continue;need(m[i][j]==(i==j?1:0),obj.getName()+": only translations supported");}
 return m;
}
// Explicit spatial opt-in, bounded static positive-determinant affine transforms.
// A camera turned and moved but not scaled or sheared: the path tracer's camera (rotations are MoonRay's
// node_xform as the camera-to-render transform).
inline rdl::Mat4d rigid(const rdl::SceneObject& obj){
 auto m=get<rdl::Mat4d>(obj,"node_xform");
 for(int i=0;i<4;++i)for(int j=0;j<4;++j)need(std::isfinite(m[i][j]),obj.getName()+": nonfinite transform");
 need(m[0][3]==0&&m[1][3]==0&&m[2][3]==0&&m[3][3]==1,obj.getName()+": projective transform unsupported");
 for(int i=0;i<3;++i)for(int j=0;j<3;++j){double d=m[i][0]*m[j][0]+m[i][1]*m[j][1]+m[i][2]*m[j][2];need(std::abs(d-(i==j?1:0))<=1e-5,obj.getName()+": only rotations and translations supported");}
 double det=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
 need(det>0,obj.getName()+": reflected transform unsupported");return m;
}
inline rdl::Mat4d affine(const rdl::SceneObject& obj){
 auto m=get<rdl::Mat4d>(obj,"node_xform");
 for(int i=0;i<4;++i)for(int j=0;j<4;++j)need(std::isfinite(m[i][j])&&std::abs(m[i][j])<=10000,"Spatial transform bound");
 need(m[0][3]==0&&m[1][3]==0&&m[2][3]==0&&m[3][3]==1,"Projective mesh transform unsupported");
 double det=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
 need(std::isfinite(det)&&det>1.e-12,"Singular/reflected transform unsupported");return m;
}
// One of MoonRay's lights as the path tracer's record (light_core.h), or false
// when it is off. Settings beyond these fall back. The arithmetic of each
// light's update(): radiance, normalization by area (and scene scale), and its
// local frame, the node transform turned about X by 180 degrees.
inline bool admitLight(const rdl::SceneObject& o,float sceneScale,lights::Light& out){
 auto cls=o.getSceneClass().getName();
 // A label names the light for light path expressions only (light AOVs fall back).
 std::set<std::string> allowed{"on","color","intensity","exposure","node_xform","normalized","apply_scene_scale","sidedness","label"};
 if(cls=="RectLight")allowed.insert({"width","height"});else if(cls=="DiskLight"||cls=="SphereLight")allowed.insert("radius");else if(cls=="DistantLight")allowed.insert("angular_extent");
 else if(cls=="SpotLight")allowed.insert({"lens_radius","aspect_ratio","focal_plane_distance","outer_cone_angle","inner_cone_angle","angle_falloff_type","black_level"});
 attributes(o,allowed);
 if(!get<rdl::Bool>(o,"on"))return false;
 lights::Light l{};
 auto c=color(get<rdl::Rgb>(o,"color"));float intensity=get<rdl::Float>(o,"intensity"),exposure=get<rdl::Float>(o,"exposure");
 need(surface::finite(intensity)&&intensity>=0&&surface::finite(exposure)&&std::abs(exposure)<=32,o.getName()+": invalid light intensity");
 V3 radiance=surface::mul(c,intensity*std::pow(2.f,exposure));
 if(cls=="EnvLight"){
  need(!get<rdl::Bool>(o,"sample_upper_hemisphere_only"),"Hemisphere environment unsupported");
  l.type=lights::Env;l.invArea=1/(4*lights::Pi);l.radiance=radiance;out=l;return surface::finite(radiance);
 }
 auto m=get<rdl::Mat4d>(o,"node_xform");
 for(int i=0;i<4;++i)for(int j=0;j<4;++j)need(std::isfinite(m[i][j])&&std::abs(m[i][j])<=10000,o.getName()+": light transform bound");
 need(m[0][3]==0&&m[1][3]==0&&m[2][3]==0&&m[3][3]==1,o.getName()+": projective light transform unsupported");
 // Rows of sRotateX180 * node_xform; Disk and Sphere scale the rotation by their radius first.
 double rows[4][3];
 for(int i=0;i<4;++i)for(int j=0;j<3;++j)rows[i][j]=(i==1||i==2?-m[i][j]:m[i][j]);
 auto length=[&](int i){return std::sqrt(rows[i][0]*rows[i][0]+rows[i][1]*rows[i][1]+rows[i][2]*rows[i][2]);};
 const bool normalized=get<rdl::Bool>(o,"normalized");
 constexpr double pi=3.14159265358979323846;
 if(cls=="DistantLight"){
  // Mat4f::orthonormalize: x from y and z, y from z and x, z from both.
  auto cross=[](const double a[3],const double b[3],double r[3]){r[0]=a[1]*b[2]-a[2]*b[1];r[1]=a[2]*b[0]-a[0]*b[2];r[2]=a[0]*b[1]-a[1]*b[0];};
  auto unit=[](double r[3]){double s=std::sqrt(r[0]*r[0]+r[1]*r[1]+r[2]*r[2]);need(s>1e-12,"Degenerate light transform");for(int k=0;k<3;++k)r[k]/=s;};
  double x[3],y[3],z[3];cross(rows[1],rows[2],x);unit(x);cross(rows[2],x,y);unit(y);cross(x,y,z);
  for(int k=0;k<3;++k){rows[0][k]=x[k];rows[1][k]=y[k];rows[2][k]=z[k];}
  float extent=std::max(get<rdl::Float>(o,"angular_extent"),lights::Epsilon);need(std::isfinite(extent)&&extent<=360,o.getName()+": invalid angular extent");
  float thetaMax=0.5f*extent*float(pi/180.0),s=std::sin(thetaMax*0.5f);
  l.type=lights::Distant;l.cosThetaMax=std::cos(thetaMax);l.versineThetaMax=2*s*s;l.invArea=1/(l.versineThetaMax*lights::TwoPi);
  if(normalized){float h=std::sin(std::min(thetaMax,lights::Pi/2));radiance=surface::mul(radiance,1/(h*h));}
  for(int i=0;i<3;++i)l.local2Render[i]={float(rows[i][0]),float(rows[i][1]),float(rows[i][2])};
  l.direction=l.local2Render[2];l.radiance=radiance;out=l;return surface::finite(radiance);
 }
 if(cls!="SpotLight"){int sidedness=get<rdl::Int>(o,"sidedness");need(sidedness>=0&&sidedness<=2,o.getName()+": invalid sidedness");l.sidedness=unsigned(sidedness);}
 float width=1,height=1;
 if(cls=="RectLight"){width=get<rdl::Float>(o,"width");height=get<rdl::Float>(o,"height");need(std::isfinite(width)&&std::isfinite(height)&&width>0&&height>0,o.getName()+": invalid size");}
 else if(cls=="SpotLight"){}
 else{float r=get<rdl::Float>(o,"radius");need(std::isfinite(r)&&r>0,o.getName()+": invalid radius");for(int i=0;i<3;++i)for(int j=0;j<3;++j)rows[i][j]*=r;}
 double x=length(0),y=length(1),z=length(2),scale;
 if(std::abs(x-y)<=0.0001&&std::abs(x-z)<=0.0001)scale=(x+y+z)/3;
 else{
  need(cls=="RectLight",o.getName()+": non-uniform light scale unsupported");
  // RectLight takes non-uniform scale into its size and keeps a unit frame.
  width*=float(x);height*=float(y);for(int i=0;i<3;++i){double s=length(i);for(int j=0;j<3;++j)rows[i][j]/=s;}scale=1;
 }
 need(scale>1e-12,o.getName()+": degenerate light transform");
 double det=rows[0][0]*(rows[1][1]*rows[2][2]-rows[1][2]*rows[2][1])-rows[0][1]*(rows[1][0]*rows[2][2]-rows[1][2]*rows[2][0])+rows[0][2]*(rows[1][0]*rows[2][1]-rows[1][1]*rows[2][0]);
 need(std::abs(std::abs(det/(scale*scale*scale))-1)<=0.01,o.getName()+": invalid light transform");
 // The inverse of the linear part, rows again.
 double inv[3][3];
 for(int i=0;i<3;++i)for(int j=0;j<3;++j){int a=(j+1)%3,b=(j+2)%3,cc=(i+1)%3,d=(i+2)%3;inv[i][j]=(rows[a][cc]*rows[b][d]-rows[a][d]*rows[b][cc])/det;}
 for(int i=0;i<3;++i){l.local2Render[i]={float(rows[i][0]),float(rows[i][1]),float(rows[i][2])};
  l.render2Local[i]={float(inv[i][0]),float(inv[i][1]),float(inv[i][2])};
  l.render2LocalRot[i]={float(inv[i][0]*scale),float(inv[i][1]*scale),float(inv[i][2]*scale)};}
 l.position={float(rows[3][0]),float(rows[3][1]),float(rows[3][2])};
 l.direction={float(rows[2][0]/scale),float(rows[2][1]/scale),float(rows[2][2]/scale)};
 l.planeOffset=-surface::dot(l.direction,l.position);l.scale=float(scale);
 double area;
 if(cls=="RectLight"){l.type=lights::Rect;l.halfWidth=width*0.5f;l.halfHeight=height*0.5f;area=double(width)*scale*double(height)*scale;}
 else if(cls=="DiskLight"){l.type=lights::Disk;area=pi*scale*scale;}
 else if(cls=="SpotLight"){
  // SpotLight::update: its lens, cones and focal plane.
  float aspect=get<rdl::Float>(o,"aspect_ratio"),lens=get<rdl::Float>(o,"lens_radius"),outer=get<rdl::Float>(o,"outer_cone_angle"),inner=get<rdl::Float>(o,"inner_cone_angle"),focal=get<rdl::Float>(o,"focal_plane_distance");
  need(std::isfinite(aspect)&&aspect>0&&std::isfinite(lens)&&lens>0&&std::isfinite(outer)&&std::isfinite(inner)&&std::isfinite(focal),o.getName()+": invalid spot light");
  int type=get<rdl::Int>(o,"angle_falloff_type");need(type>=0&&type<=4,o.getName()+": invalid falloff");
  float rcpAspect=1/aspect;l.lensRadius=lens;l.rcpLensRadius=1/lens;l.lensRadiusY=lens*rcpAspect;l.rcpLensRadiusY=1/l.lensRadiusY;
  outer=std::min(std::max(outer,-179.999f),179.999f);inner=std::min(std::max(inner,-179.999f),outer);
  float tanOuter=std::tan(float(outer*0.5*pi/180.0)),tanInner=std::tan(float(inner*0.5*pi/180.0)),tanDiff=tanOuter-tanInner;
  if(focal<0.0001f)focal=0.0001f;if(tanOuter<0.0f)focal=std::min(focal,-0.999f*lens/tanOuter);
  l.focalDistance=focal;l.focalRadius=tanOuter*focal+lens;l.rcpFocalRadius=1/l.focalRadius;l.focalRadiusY=l.focalRadius*rcpAspect;l.rcpFocalRadiusY=1/l.focalRadiusY;
  l.falloffGradient=l.focalRadius/std::max(tanDiff*focal,1.0e-10f);l.crossOverDistance=focal*lens/(lens+l.focalRadius);l.falloffType=unsigned(type);
  l.type=lights::Spot;area=pi*(double(lens)*scale)*(double(l.lensRadiusY)*scale);
  double ratio=double(lens)/l.focalRadius;l.focalPlanePdfConst=float(ratio*ratio/area);
 }
 else{l.type=lights::Sphere;l.radius=float(scale);l.radiusSq=l.radius*l.radius;l.rcpRadius=1/l.radius;area=4*pi*scale*scale;need(l.sidedness!=lights::TwoSided,o.getName()+": two-sided sphere unsupported");}
 l.invArea=float(1/area);
 // computeLightRadiance: normalized lights spread their power over their area, in scene units.
 if(normalized){double inverse=1/area;if(get<rdl::Bool>(o,"apply_scene_scale"))inverse*=1/(double(sceneScale)*sceneScale)/pi;radiance=surface::mul(radiance,float(inverse));}
 l.radiance=radiance;out=l;return surface::finite(radiance);
}
inline bool isCurves(const std::string& cls){return cls=="RdlCurveGeometry"||cls=="ModoFurGeometry";}
inline bool isLight(const std::string& cls){return cls=="EnvLight"||cls=="RectLight"||cls=="DiskLight"||cls=="SphereLight"||cls=="DistantLight"||cls=="SpotLight";}
// A BaseVolume (moonray dso/volume/Base) as volume_core.h shades it: homogeneous (no attribute bound), not emissive;
// its ramps over the depth a ray travels through it as RampControl builds them.
inline volume::Shader admitVolume(const rdl::SceneObject& o,unsigned lightMask){
 need(o.getSceneClass().getName()=="BaseVolume",o.getName()+": only BaseVolume volume shaders are rendered");
 std::set<std::string> all;for(auto i=o.getSceneClass().beginAttributes();i!=o.getSceneClass().endAttributes();++i)all.insert((*i)->getName());
 attributes(o,all);
 for(auto i=o.getSceneClass().beginAttributes();i!=o.getSceneClass().endAttributes();++i){const rdl::Attribute& a=**i;
  need(!a.isBindable()||!o.getBinding(a),o.getName()+": a volume with bound attributes (heterogeneous) is not rendered yet");}
 auto rgb=[&](const char* n){auto c=get<rdl::Rgb>(o,n);need(std::isfinite(c.r)&&std::isfinite(c.g)&&std::isfinite(c.b),o.getName()+": invalid "+n);return V3{c.r,c.g,c.b};};
 auto f1=[&](const char* n){float f=get<rdl::Float>(o,n);need(std::isfinite(f),o.getName()+": invalid "+n);return f;};
 const V3 emission=rgb("emission_color");const float emissionIntensity=f1("emission_intensity");
 need(emissionIntensity==0.0f||(emission.x==0&&emission.y==0&&emission.z==0),o.getName()+": emissive volumes are not rendered yet");
 volume::Shader s{};
 s.attenuationColor=rgb("attenuation_color");s.albedoColor=rgb("diffuse_color");
 s.intensity=f1("attenuation_intensity");s.factor=f1("attenuation_factor");
 s.g=std::min(std::max(f1("anisotropy"),-1.0f),1.0f);
 s.flags=(get<rdl::Bool>(o,"use_attenuation_ramp")?volume::UseAttenuationRamp:0u)|(get<rdl::Bool>(o,"use_diffuse_ramp")?volume::UseAlbedoRamp:0u)|
         (get<rdl::Bool>(o,"match_diffuse")?volume::MatchAlbedo:0u)|(get<rdl::Bool>(o,"invert_attenuation_color")?volume::InvertAttenuation:0u);
 s.lightMask=lightMask;
 s.attenuationMin=f1("attenuation_min_depth");s.attenuationMax=f1("attenuation_max_depth");
 s.albedoMin=f1("diffuse_min_depth");s.albedoMax=f1("diffuse_max_depth");
 s.densityMin=f1("density_min_depth");s.densityMax=f1("density_max_depth");
 auto colorRamp=[&](const char* pos,const char* values,const char* interps,shade::ColorRamp& r){
  const auto& p=get<rdl::FloatVector>(o,pos);const auto& v=get<rdl::RgbVector>(o,values);const auto& in=get<rdl::IntVector>(o,interps);
  need(p.size()<=shade::RampMaxPoints&&v.size()>=p.size()&&in.size()>=p.size(),o.getName()+": a volume ramp of more than ten points");
  float ip[shade::RampMaxPoints];shade::Color out[shade::RampMaxPoints];unsigned it[shade::RampMaxPoints];
  for(size_t i=0;i<p.size();++i){ip[i]=p[i];out[i]=shade::Color{v[i].r,v[i].g,v[i].b};need(in[i]>=0&&in[i]<=6,o.getName()+": invalid ramp interpolation");it[i]=unsigned(in[i]);}
  shade::rampInit(r,unsigned(p.size()),ip,out,it,shade::RampRgb);};
 colorRamp("attenuation_distances","attenuation_colors","attenuation_interpolations",s.attenuationRamp);
 colorRamp("diffuse_distances","diffuse_colors","diffuse_interpolations",s.albedoRamp);
 {const auto& p=get<rdl::FloatVector>(o,"density_distances");const auto& v=get<rdl::FloatVector>(o,"densities");const auto& in=get<rdl::IntVector>(o,"density_interpolations");
  need(p.size()<=shade::RampMaxPoints&&v.size()>=p.size()&&in.size()>=p.size(),o.getName()+": a volume ramp of more than ten points");
  float ip[shade::RampMaxPoints],out[shade::RampMaxPoints];unsigned it[shade::RampMaxPoints];
  for(size_t i=0;i<p.size();++i){ip[i]=p[i];out[i]=v[i];need(in[i]>=0&&in[i]<=6,o.getName()+": invalid ramp interpolation");it[i]=unsigned(in[i]);}
  shade::rampInit(s.densityRamp,unsigned(p.size()),ip,out,it);}
 return s;
}
inline std::vector<std::shared_ptr<const ix::Buffer>> signature(const rdl::SceneObject& o,const CanonicalView& frame){
 auto entity=frame->routing->scene->entities.at(ri::objectId(o.getName()));std::vector<std::shared_ptr<const ix::Buffer>> value;
 for(auto& id:entity->dependencies){auto attr=frame->routing->scene->entities.at(id);for(auto& pair:attr->buffers)value.push_back(pair.second);}return value;
}
}
#include "map_admission.h"
#include "dwa_admission.h"
#include "mesh_displacement.h"
namespace xpu2::interactive::cpu {
// A NormalDisplacement or a tangent-space VectorDisplacement (mesh_displacement.h), its maps in a program of its own.
inline displace::Shader admitDisplacement(const rdl::SceneObject& o,std::vector<float>& pool,TextureContext& textures,int depth=0){
 const std::string cls=o.getSceneClass().getName();
 need(depth<16,o.getName()+": displacement tree too deep");
 // CombineDisplacement: its two inputs (each a displacement or none), their scales and the operation.
 if(cls=="CombineDisplacement"){
  attributes(o,{"operation","input_1","scale_1","input_2","scale_2"});displace::Shader d;d.kind=displace::Shader::Combine;
  d.operation=get<rdl::Int>(o,"operation");d.scale1=get<rdl::Float>(o,"scale_1");d.scale2=get<rdl::Float>(o,"scale_2");
  need(std::isfinite(d.scale1)&&std::isfinite(d.scale2),o.getName()+": invalid scale");
  for(int k=1;k<=2;++k){const rdl::SceneObject* in=get<rdl::SceneObject*>(o,("input_"+std::to_string(k)).c_str());
   if(!in)continue;need(in->isA<rdl::Displacement>(),o.getName()+": an input that is not a displacement");
   auto s=std::make_shared<displace::Shader>(admitDisplacement(*in,pool,textures,depth+1));(k==1?d.input1:d.input2)=s;}
  return d;
 }
 // SwitchDisplacement: its choice (cycled through 64) at preparation, none for an empty one.
 if(cls=="SwitchDisplacement"){
  // choice is a float read as an int (getAttrChoice): a binding on it is not evaluated.
  {std::set<std::string> all;for(auto i=o.getSceneClass().beginAttributes();i!=o.getSceneClass().endAttributes();++i)all.insert((*i)->getName());attributes(o,all,{"choice"});}
  const int choice=int(get<rdl::Float>(o,"choice"))%64;displace::Shader none;none.kind=displace::Shader::None;
  if(choice<0)return none;
  const rdl::SceneObject* in=get<rdl::SceneObject*>(o,("displacement"+std::to_string(choice)).c_str());
  if(!in)return none;need(in->isA<rdl::Displacement>(),o.getName()+": its choice is not a displacement");
  return admitDisplacement(*in,pool,textures,depth+1);
 }
 MapProgramBuilder maps{pool,textures};displace::Shader d;
 auto bound=[&](const char* n)->unsigned{const rdl::SceneObject* m=o.getBinding(*o.getSceneClass().getAttribute(n));return m?maps.reg(*m):shade::MapNoRegister;};
 auto f1=[&](const char* n){float f=get<rdl::Float>(o,n);need(std::isfinite(f),o.getName()+": invalid "+n);return f;};
 if(cls=="NormalDisplacement"){
  attributes(o,{"height","zero_value","height_multiplier","bound_padding"},{"height","height_multiplier"});
  d.kind=displace::Shader::Normal;d.height=f1("height");d.zero=f1("zero_value");d.multiplier=f1("height_multiplier");
  d.heightReg=bound("height");d.multiplierReg=bound("height_multiplier");
 }else if(cls=="VectorDisplacement"){
  attributes(o,{"vector","factor","source_space","tangent_space_style","bound_padding"},{"vector"});
  need(get<rdl::Int>(o,"source_space")==0,o.getName()+": object-space vector displacement is not rendered yet");
  const int style=get<rdl::Int>(o,"tangent_space_style");need(style==0||style==1,o.getName()+": invalid tangent space style");
  const auto v=get<rdl::Vec3f>(o,"vector");d.kind=displace::Shader::Vector;d.vector=V3{v.x,v.y,v.z};need(surface::finite(d.vector),o.getName()+": invalid vector");
  d.factor=f1("factor");d.style=style;d.vectorReg=bound("vector");
 }else throw Unsupported(o.getName()+": displacement class "+cls+" is not rendered yet");
 need(!maps.polyVertices&&maps.required.empty(),o.getName()+": polygon and attribute-requiring maps in a displacement are not rendered yet");
 d.program=maps.finish();
 return d;
}
// UserData primitive attributes (geom/PrimitiveUserData processArbitraryData) at a geometry's rate counts: constant,
// uniform (a face, or a curve), vertex, varying, face varying; pickRate's guess from the count when the rate is auto.
inline void primitiveAttributes(const rdl::SceneObject& o,MeshData& m,size_t uniformCount,size_t vertexCount,size_t varyingCount,size_t faceVaryingCount){
 for(auto* object:o.get<rdl::SceneObjectVector>("primitive_attributes")){
  need(object&&object->getSceneClass().getName()=="UserData",o.getName()+": a primitive attribute that is not UserData");
  attributes(*object,{"bool_key","bool_values","int_key","int_values","float_key","float_values_0","float_values_1","string_key","string_values","color_key","color_values_0","color_values_1","vec2f_key","vec2f_values_0","vec2f_values_1","vec3f_key","vec3f_values_0","vec3f_values_1","mat3f_key","mat3f_values_0","mat3f_values_1","mat4f_key","mat4f_values_0","mat4f_values_1","rate"});
  const int explicitRate=get<rdl::Int>(*object,"rate");
  auto pick=[&](size_t n)->unsigned{
   switch(explicitRate){case 1:return n==1?1u:0u;case 3:return n==uniformCount?3u:0u;case 4:return n==vertexCount?4u:0u;case 5:return n==varyingCount?5u:0u;case 6:return faceVaryingCount&&n==faceVaryingCount?6u:0u;case 0:break;default:return 0u;}
   if(n==0)return 0u;if(n==1)return 1u;if(faceVaryingCount&&n==faceVaryingCount)return 6u;if(n==uniformCount)return 3u;if(n==vertexCount)return 4u;if(n==varyingCount)return 5u;return 0u;};
  auto add=[&](const std::string& key,unsigned type,unsigned components,const std::vector<float>& values,size_t count){
   if(key.empty())return;const unsigned r=pick(count);need(r!=0,o.getName()+": primitive attribute "+key+" has an unsupported rate or size");
   for(float f:values)need(std::isfinite(f),o.getName()+": invalid primitive attribute "+key);
   m.prims.push_back(shade::PrimAttr{shade::primKey(key.c_str(),type),components,r,unsigned(m.primData.size())});m.primData.insert(m.primData.end(),values.begin(),values.end());};
  {const auto& d=get<rdl::FloatVector>(*object,"float_values_0");add(get<rdl::String>(*object,"float_key"),shade::PrimFloat,1,std::vector<float>(d.begin(),d.end()),d.size());}
  {const auto& d=get<rdl::IntVector>(*object,"int_values");std::vector<float> f;for(int i:d)f.push_back(float(i));add(get<rdl::String>(*object,"int_key"),shade::PrimInt,1,f,d.size());}
  {const auto& d=get<rdl::RgbVector>(*object,"color_values_0");std::vector<float> f;for(auto c:d){f.push_back(c.r);f.push_back(c.g);f.push_back(c.b);}add(get<rdl::String>(*object,"color_key"),shade::PrimRgb,3,f,d.size());}
  {const auto& d=get<rdl::Vec2fVector>(*object,"vec2f_values_0");std::vector<float> f;for(auto c:d){f.push_back(c.x);f.push_back(c.y);}add(get<rdl::String>(*object,"vec2f_key"),shade::PrimVec2f,2,f,d.size());}
  {const auto& d=get<rdl::Vec3fVector>(*object,"vec3f_values_0");std::vector<float> f;for(auto c:d){f.push_back(c.x);f.push_back(c.y);f.push_back(c.z);}add(get<rdl::String>(*object,"vec3f_key"),shade::PrimVec3f,3,f,d.size());}
 }
}
inline bool hasPrim(const MeshData& m,const char* name,unsigned type){const unsigned k=shade::primKey(name,type);for(auto& a:m.prims)if(a.key==k)return true;return false;}
// MoonRay's curves (geom/prim/Curves.h) from RdlCurveGeometry or ModoFurGeometry (the plugin's fur: its fibres in a
// file written by modo_fur_grow, linear curves with a texture coordinate a point). The control points go to render
// space with their radii scaled as Primitive::applyTransformation scales them; the spans are numbered as
// LineSegments, BezierSpanChains and BSpline number them; uv_list becomes the "uv" primitive attribute at its rate.
inline void admitCurves(const rdl::SceneObject& o,const rdl::Mat4d& transform,MeshData& m){
 const bool fur=o.getSceneClass().getName()=="ModoFurGeometry";
 std::vector<unsigned> counts;std::vector<float> points;  // object space: x, y, z, radius
 int type=0;
 if(fur){
  attributes(o,{"file","curves_subtype","tessellation_rate","node_xform"});
  const std::string path=get<rdl::String>(o,"file");std::ifstream source(path,std::ios::binary);
  char magic[4];uint32_t fibres=0;uint64_t total=0;float ends[2];
  need(bool(source.read(magic,4))&&std::memcmp(magic,"MFC1",4)==0&&bool(source.read(reinterpret_cast<char*>(&fibres),4))&&bool(source.read(reinterpret_cast<char*>(&total),8))&&bool(source.read(reinterpret_cast<char*>(ends),8)),o.getName()+": cannot read the fur file");
  need(fibres>0&&total>0&&total<=(uint64_t(1)<<28),o.getName()+": empty or oversized fur");
  counts.resize(fibres);points.resize(size_t(total)*4);std::vector<float> across(size_t(total)*2);
  need(bool(source.read(reinterpret_cast<char*>(counts.data()),counts.size()*4))&&bool(source.read(reinterpret_cast<char*>(points.data()),points.size()*4))&&bool(source.read(reinterpret_cast<char*>(across.data()),across.size()*4)),o.getName()+": the fur file is cut short");
  uint64_t counted=0;for(auto c:counts)counted+=c;need(counted==total,o.getName()+": the fur file does not add up");
  m.prims.push_back(shade::PrimAttr{shade::primKey("uv",shade::PrimVec2f),2,shade::PrimVertex,unsigned(m.primData.size())});m.primData.insert(m.primData.end(),across.begin(),across.end());
  m.prims.push_back(shade::PrimAttr{shade::primKey("modo_fine",shade::PrimFloat),1,shade::PrimConstant,unsigned(m.primData.size())});m.primData.push_back(1.0f);
 }else{
  attributes(o,{"curves_vertex_count","vertex_list_0","radius_list","uv_list","curve_type","curves_subtype","tessellation_rate","node_xform","primitive_attributes"});
  type=get<rdl::Int>(o,"curve_type");need(type>=0&&type<=2,o.getName()+": unknown curve type");
  const auto& c=o.get<rdl::IntVector>("curves_vertex_count");const auto& v=o.get<rdl::Vec3fVector>("vertex_list_0");
  for(int n:c){need(n>0,o.getName()+": invalid curve vertex count");counts.push_back(unsigned(n));}
  // The radii (RdlCurveGeometry::generate): constant, a curve, a vertex, or a span end (varying), else 0.5.
  const size_t vertCount=v.size(),curves=counts.size();
  const size_t varyingCount=type==0?vertCount:type==1?(vertCount-curves)/3+curves:vertCount-2*curves;
  const auto& rv=o.get<rdl::FloatVector>("radius_list");std::vector<float> radius;
  const size_t n=rv.size();
  if(n==0)radius.assign(vertCount,0.5f);
  else if(n==1)radius.assign(vertCount,rv[0]);
  else if(n==curves){for(size_t i=0;i<curves;++i)for(size_t k=counts[i];k--;)radius.push_back(rv[i]);}
  else if(n==vertCount)radius.assign(rv.begin(),rv.end());
  else if(n==varyingCount){
   if(type==0)radius.assign(rv.begin(),rv.end());
   // MoonRay's Bezier expansion writes more radii than points (its loop runs to the curve's last point): refused.
   else if(type==1)throw Unsupported(o.getName()+": Bezier radii a span end");
   else{size_t i=0;for(size_t count:counts){radius.push_back(2*rv[i]-rv[i+1]);for(size_t j=0;j<count-2;j++)radius.push_back(rv[i++]);radius.push_back(2*rv[i-1]-rv[i-2]);}}
  }else throw Unsupported(o.getName()+": radius_list has an unsupported rate");
  need(radius.size()==vertCount,o.getName()+": radii do not match the curves");
  points.reserve(vertCount*4);for(size_t i=0;i<vertCount;++i){points.push_back(v[i].x);points.push_back(v[i].y);points.push_back(v[i].z);points.push_back(radius[i]);}
  primitiveAttributes(o,m,curves,vertCount,varyingCount,0);
  // uv_list, unless the primitive attributes already give "st" or "uv".
  const auto& ul=o.get<rdl::Vec2fVector>("uv_list");
  if(!ul.empty()&&!hasPrim(m,"st",shade::PrimVec2f)&&!hasPrim(m,"uv",shade::PrimVec2f)){
   const size_t un=ul.size();const unsigned r=un==1?1u:un==curves?3u:un==vertCount?4u:un==varyingCount?5u:0u;need(r!=0,o.getName()+": uv_list has an unsupported rate");
   m.prims.push_back(shade::PrimAttr{shade::primKey("uv",shade::PrimVec2f),2,r,unsigned(m.primData.size())});
   for(auto u:ul){need(std::isfinite(u.x)&&std::isfinite(u.y),o.getName()+": invalid uv");m.primData.push_back(u.x);m.primData.push_back(u.y);}
  }
 }
 const int subtype=get<rdl::Int>(o,"curves_subtype");need(subtype==0||subtype==1,o.getName()+": normal-oriented curves (MoonRay XPU draws them facing the ray)");
 const int rate=get<rdl::Int>(o,"tessellation_rate");need(rate>=1&&rate<=64,o.getName()+": tessellation rate out of range");
 // Curves::checkPrimitiveData: whole spans, as many points as the curves say.
 size_t vertices=0;for(auto c:counts){vertices+=c;need(type==0?c>=2:type==1?(c>=4&&(c-1)%3==0):c>=4,o.getName()+": a curve with an invalid number of points");}
 need(vertices*4==points.size()&&vertices>0,o.getName()+": curve points do not match the counts");
 m.curveBasis=type==0?curves::BasisLinear:type==1?curves::BasisBezier:curves::BasisBspline;m.curveRound=unsigned(subtype);m.curveSegments=unsigned(rate);
 // Render space: the points as the mesh's; the radii scaled by the transform's mean axis length.
 const float radiusScale=(float(std::sqrt(transform[0][0]*transform[0][0]+transform[0][1]*transform[0][1]+transform[0][2]*transform[0][2]))+
  float(std::sqrt(transform[1][0]*transform[1][0]+transform[1][1]*transform[1][1]+transform[1][2]*transform[1][2]))+
  float(std::sqrt(transform[2][0]*transform[2][0]+transform[2][1]*transform[2][1]+transform[2][2]*transform[2][2])))/3.f;
 m.curvePoints.reserve(points.size());
 for(size_t i=0;i<vertices;++i){const double x=points[4*i],y=points[4*i+1],z=points[4*i+2];
  const float p[3]={float(x*transform[0][0]+y*transform[1][0]+z*transform[2][0]+transform[3][0]),float(x*transform[0][1]+y*transform[1][1]+z*transform[2][1]+transform[3][1]),float(x*transform[0][2]+y*transform[1][2]+z*transform[2][2]+transform[3][2])};
  const float r=points[4*i+3]*radiusScale;
  need(std::isfinite(p[0])&&std::isfinite(p[1])&&std::isfinite(p[2])&&std::isfinite(r)&&r>=0&&std::abs(p[0])<=10000&&std::abs(p[1])<=10000&&std::abs(p[2])<=10000,o.getName()+": invalid curve point");
  m.curvePoints.insert(m.curvePoints.end(),{p[0],p[1],p[2],r});}
 // The index buffer: a span's first point, its curve, its place along the curve.
 unsigned offset=0;
 for(unsigned chain=0;chain<counts.size();++chain){const unsigned c=counts[chain];
  const unsigned spans=type==0?c-1:type==1?(c-1)/3:c-3;m.curveSpanCounts.push_back(spans);
  for(unsigned j=0;j<spans;++j){m.curveSpans.insert(m.curveSpans.end(),{offset,chain,j});offset+=type==1?3u:1u;}
  offset+=type==0?1u:type==1?1u:3u;}
 need(m.curveSpans.size()/3<(1u<<30),o.getName()+": too many curve spans");
}

// Where MoonRay's sampler tables are (beside the GPU program in a build), and the tables a random walk draws from:
// pbr/sampler's bc_1D integrator sequences (4096 of 1024 floats) then its ppd_2D ones (4096 of 1024 pairs), loaded
// once and shared.
inline fs::path& sequenceDirectory(){static fs::path p;return p;}
inline std::shared_ptr<const std::vector<float>> walkSequences(){
 static std::mutex m;static std::weak_ptr<const std::vector<float>> cache;std::lock_guard<std::mutex> lock(m);
 if(auto p=cache.lock())return p;
 auto v=std::make_shared<std::vector<float>>(size_t(4096)*1024*3);
 auto read=[&](const char* name,float* dst,size_t n){std::ifstream f(sequenceDirectory()/name,std::ios::binary);
  need(bool(f),std::string("Missing MoonRay sampler table ")+name);f.read(reinterpret_cast<char*>(dst),std::streamsize(n*sizeof(float)));
  need(size_t(f.gcount())==n*sizeof(float),std::string("Short MoonRay sampler table ")+name);};
 read("bc_1D_integrator_points_4096_sequences_of_1024.bin",v->data(),size_t(4096)*1024);
 read("ppd_2D_integrator_points_4096_sequences_of_1024.bin",v->data()+size_t(4096)*1024,size_t(4096)*1024*2);
 cache=v;return v;
}
// MoonRay's polygon meshes (geom/PolygonMesh.cc). With no face above four vertices, a QuadMesh when its quads are
// fewer primitives than triangles would be: each face a quad, a triangle's as v0 v1 v2 v2 (QuadMesh::splitNGons),
// which Embree and XPU's GPU split as (0, 1, 3) and (2, 3, 1). Otherwise a TriMesh: each face a fan (0, k, k + 1),
// but a planar n-gon above four vertices of some area, which it ear-clips in object space (TriMesh::splitNGons).
// Each triangle keeps its face and its corners' face-vertices.
struct PolygonSplit {
 bool quads=false;
 std::vector<int> quadVertices;  // a QuadMesh's quads, four vertex indices each (its smooth normals)
 std::vector<unsigned> corners;  // three face-vertex indices a triangle
 std::vector<unsigned> faceOf;   // each triangle's face
};
namespace polygon {
struct F3{float x,y,z;};
inline F3 sub(F3 a,F3 b){return {a.x-b.x,a.y-b.y,a.z-b.z};}
inline F3 crs(F3 a,F3 b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
inline float dt(F3 a,F3 b){return a.x*b.x+a.y*b.y+a.z*b.z;}
inline F3 nrm(F3 a){const float r=1.0f/std::sqrt(dt(a,a));return {a.x*r,a.y*r,a.z*r};}
inline unsigned loop(int i,int n){return unsigned(i>=0&&i<n?i:i>=n?i%n:i%n+n);}
inline F3 at(const rdl::Vec3fVector& v,const rdl::IntVector& ind,size_t k){const auto& q=v[size_t(ind[k])];return {q.x,q.y,q.z};}
// TriMesh.cc's unitNormal, calculateConcaveNGonArea, calculateConcaveNGonNormal, isPlanar and pointInTriangle.
inline F3 unitNormal(F3 a,F3 b,F3 c){
 auto det=[](F3 r0,F3 r1,F3 r2){return dt(r0,crs(r1,r2));};
 const float x=det({1,a.y,a.z},{1,b.y,b.z},{1,c.y,c.z}),y=det({a.x,1,a.z},{b.x,1,b.z},{c.x,1,c.z}),z=det({a.x,a.y,1},{b.x,b.y,1},{c.x,c.y,1});
 const float m=std::max(1e-6f,std::sqrt(x*x+y*y+z*z));return {x/m,y/m,z/m};}
inline float area(const rdl::Vec3fVector& v,const rdl::IntVector& ind,int n,size_t o){
 F3 t{0,0,0};for(int i=0;i<n;++i){const F3 c=crs(at(v,ind,o+loop(i,n)),at(v,ind,o+loop(i+1,n)));t={t.x+c.x,t.y+c.y,t.z+c.z};}
 return dt(t,unitNormal(at(v,ind,o),at(v,ind,o+1),at(v,ind,o+2)))/2.f;}
inline F3 normal(const rdl::Vec3fVector& v,const rdl::IntVector& ind,int n,size_t o){
 const float a=area(v,ind,n,o);F3 t{0,0,0};
 for(int i=0;i<n;++i){const F3 c=crs(at(v,ind,o+size_t(i)),at(v,ind,o+loop(i+1,n)));t={t.x+c.x,t.y+c.y,t.z+c.z};}
 if(a<0.f)t={-t.x,-t.y,-t.z};return nrm(t);}
inline bool planar(const rdl::Vec3fVector& v,const rdl::IntVector& ind,int n,size_t o){
 const F3 a=at(v,ind,o),b=at(v,ind,o+1),c=at(v,ind,o+2),N=crs(sub(a,b),sub(c,b));
 for(int i=3;i<n;++i)if(!(std::abs(dt(nrm(sub(a,at(v,ind,o+size_t(i)))),N))<=1e-6f))return false;
 return true;}
inline bool inside(F3 N,F3 p,F3 a,F3 b,F3 c){
 (void)N;const F3 v0=sub(b,a),v1=sub(c,a),v2=sub(p,a);
 const float d00=dt(v0,v0),d01=dt(v0,v1),d11=dt(v1,v1),d20=dt(v2,v0),d21=dt(v2,v1),den=d00*d11-d01*d01;
 const float y=(d11*d20-d01*d21)/den,w=(d00*d21-d01*d20)/den,u=1.0f-y-w;return u>=0&&y>=0&&w>=0;}
}
inline PolygonSplit splitPolygons(const rdl::Vec3fVector& v,const rdl::IntVector& counts,const rdl::IntVector& ind,const std::string& name){
 using namespace polygon;
 PolygonSplit out;size_t tris=0,quads=0,total=0;int most=0;
 for(int n:counts){need(n>=3,name+": a face of fewer than three vertices");tris+=size_t(n-2);quads+=size_t((n-1)>>1);total+=size_t(n);most=std::max(most,n);}
 need(total==ind.size(),name+": face vertex counts do not match the vertex indices");
 for(int k:ind)need(k>=0&&size_t(k)<v.size(),"Vertex index out of bounds");
 auto tri=[&](size_t f,unsigned a,unsigned b,unsigned c){out.corners.insert(out.corners.end(),{a,b,c});out.faceOf.push_back(unsigned(f));};
 out.quads=most<=4&&quads*4<tris*3;
 size_t o=0;
 for(size_t f=0;f<counts.size();o+=size_t(counts[f]),++f){
  const int n=counts[f];const unsigned b=unsigned(o);
  if(out.quads){
   const unsigned q[4]={b,b+1,b+2,n==3?b+2:b+3};
   for(unsigned k:q)out.quadVertices.push_back(ind[k]);
   tri(f,q[0],q[1],q[3]);if(n==4)tri(f,q[2],q[3],q[1]);
   continue;}
  const float a=area(v,ind,n,o);const bool some=!std::isnan(a)&&a>=1e-6f;
  bool clipped=false;
  if(n>4&&some&&planar(v,ind,n,o)){
   // Ear clipping (TriMesh::splitNGons): MoonRay writes the face's triangles from its end, so they run last
   // triangle first, then the ears in the reverse of the order they were clipped.
   const F3 N=normal(v,ind,n,o);std::vector<unsigned> local(static_cast<size_t>(n),0u);for(int i=0;i<n;++i)local[size_t(i)]=unsigned(i);
   std::vector<std::array<unsigned,3>> ears;bool ok=true;
   while(local.size()>3&&ok){
    ok=false;const int m=int(local.size());
    for(int i=m-1;i>=0;--i){
     const unsigned ia=local[size_t(i)],ib=local[loop(i-1,m)],ic=local[loop(i+1,m)];
     const F3 va=at(v,ind,o+ia),vb=at(v,ind,o+ib),vc=at(v,ind,o+ic);
     if(dt(crs(sub(vc,va),sub(vb,va)),N)<0.f)continue;
     bool interior=false;
     for(int j=0;j<m;++j){const unsigned l=local[size_t(j)];if(l==ia||l==ib||l==ic)continue;if(inside(N,at(v,ind,o+l),vb,va,vc)){interior=true;break;}}
     if(interior)continue;
     ears.push_back({b+ib,b+ia,b+ic});local.erase(local.begin()+i);ok=true;break;}
   }
   if(ok){clipped=true;tri(f,b+local[0],b+local[1],b+local[2]);for(size_t e=ears.size();e-->0;)tri(f,ears[e][0],ears[e][1],ears[e][2]);}
  }
  if(!clipped)for(int k=1;k+1<n;++k)tri(f,b,b+unsigned(k),b+unsigned(k+1));
 }
 return out;
}
inline PlanView prepare(const rdl::SceneContext& context,const CanonicalView& frame,PlanView previous={},Limits limits={},const fs::path& assetRoot={},Domain domain=Domain::Planar,bool allowAdaptive=false,bool paths=false){
 need(bool(frame),"Missing canonical snapshot");
 const Limits hard{};
 need(limits.vertices>0&&limits.vertices<=hard.vertices&&limits.triangles>0&&limits.triangles<=hard.triangles&&
      limits.bytes>0&&limits.bytes<=hard.bytes&&limits.objects>0&&limits.objects<=hard.objects&&limits.pixels>0&&limits.pixels<=hard.pixels,"Invalid preparation limits");
 auto plan=std::make_shared<Plan>();plan->source=frame;plan->domain=domain;need(domain==Domain::Planar||domain==Domain::DiffuseMesh||gpuTextures(domain),"Unknown scene domain");bool spatial=isSpatial(domain);
 const auto& sv=context.getSceneVariables();
 // Bound native geometry reads BEFORE copying prepared values.
 size_t objects=0,verts=0,tris=0;
 std::map<std::string,const rdl::SceneObject*> sorted;
 for(auto i=context.beginSceneObject();i!=context.endSceneObject();++i){auto* o=i->second;need(++objects<=limits.objects,"Object budget");sorted.emplace(o->getName(),o);
  if(o->getSceneClass().getName()=="RdlMeshGeometry"){
   auto& v=o->get<rdl::Vec3fVector>("vertex_list");auto& t=o->get<rdl::IntVector>("face_vertex_count");auto& ind=o->get<rdl::IntVector>("vertices_by_index");
   size_t faces=0,corners=0;for(int n:t){faces+=n>=3?size_t(n-2):0;corners+=n>0?size_t(n):0;}need(corners==ind.size(),"Face vertex counts do not match the vertex indices");
   need(v.size()<=limits.vertices-verts&&faces<=limits.triangles-tris,"Geometry count budget");verts+=v.size();tris+=faces;
  }
 }
 need(verts*sizeof(V3)+tris*sizeof(Tri)<=limits.bytes,"Prepared geometry byte budget");
 attributes(sv,{"camera","layer","image_width","image_height","pixel_samples","sampling_mode","min_adaptive_samples","max_adaptive_samples","target_adaptive_error","frame","lock_frame_noise","pixel_filter","pixel_filter_width","bsdf_samples","light_samples","max_depth","max_diffuse_depth","enable_dof","enable_motion_blur","sample_clamping_value","shadow_terminator_fix","two_stage_output","russian_roulette_threshold","lights_visible_in_camera","max_glossy_depth","max_mirror_depth","sample_clamping_depth","scene_scale",
  "max_hair_depth","max_presence_depth","roughness_clamping_factor","transparency_threshold","bssrdf_samples","max_subsurface_per_path",
  "enable_subsurface_scattering","max_volume_depth","volume_quality","volume_shadow_quality","volume_illumination_samples",
  "volume_opacity_threshold","volume_overlap_mode","volume_attenuation_factor","volume_contribution_factor","volume_phase_attenuation_factor",
  // What changes only MoonRay's scheduling, its texture cache's size, or motion blur, which is refused unless off.
  "progressive_tile_order","checkpoint_tile_order","batch_tile_order","texture_cache_size","fps","motion_steps","max_geometry_resolution"});
 int width=get<rdl::Int>(sv,"image_width"),height=get<rdl::Int>(sv,"image_height"),grid=get<rdl::Int>(sv,"pixel_samples");
 need(width>0&&height>0&&size_t(width)*height<=limits.pixels,"Image budget");need(grid>0&&grid<=64,"Sample budget");plan->width=width;plan->height=height;plan->spp=unsigned(grid*grid);
 int samplingMode=get<rdl::Int>(sv,"sampling_mode");need(samplingMode==0||(samplingMode==2&&allowAdaptive),"Adaptive sampling unsupported");
 if(samplingMode==2){
  // The same clamping as MoonRay's RenderContext: at least 2 samples, a maximum no
  // lower than the minimum, and the target error divided by 10,000.
  plan->adaptive=true;plan->minSamples=unsigned(std::max(2,get<rdl::Int>(sv,"min_adaptive_samples")));
  plan->maxSamples=unsigned(std::max(int(plan->minSamples),get<rdl::Int>(sv,"max_adaptive_samples")));
  plan->targetError=std::max(0.000001f,get<rdl::Float>(sv,"target_adaptive_error")/10000.0f);
  need(plan->maxSamples<=16384,"Adaptive sample budget");plan->spp=plan->maxSamples;
 }
 need(!get<rdl::Bool>(sv,"enable_motion_blur")&&!get<rdl::Bool>(sv,"enable_dof"),"Motion/DOF unsupported");
 int depth=get<rdl::Int>(sv,"max_depth"),diffuse=get<rdl::Int>(sv,"max_diffuse_depth");
 if(paths){
  need(spatial,"The path tracer renders spatial scenes");
  int bsdfSamples=get<rdl::Int>(sv,"bsdf_samples"),lightSamples=get<rdl::Int>(sv,"light_samples"),clampDepth=get<rdl::Int>(sv,"sample_clamping_depth");
  float rr=get<rdl::Float>(sv,"russian_roulette_threshold"),clamp=get<rdl::Float>(sv,"sample_clamping_value");
  // MoonRay's bsdf_samples and light_samples are square roots: a lobe takes bsdf_samples squared samples at the first hit.
  need(bsdfSamples>=1&&bsdfSamples<=8&&lightSamples>=1&&lightSamples<=8,"Sample splitting budget (1..8)");
  need(depth>=0&&depth<=16&&diffuse>=0&&diffuse<=16&&clampDepth>=0&&clampDepth<=16,"Bounce budget");
  need(std::isfinite(rr)&&rr>=0&&rr<=1&&std::isfinite(clamp)&&clamp>=0,"Invalid roulette/clamping");
  plan->paths=true;plan->bsdfSamples=unsigned(bsdfSamples*bsdfSamples);plan->lightSamples=unsigned(lightSamples*lightSamples);plan->maxDepth=unsigned(depth);
  plan->maxDiffuseDepth=unsigned(diffuse);plan->rrThreshold=rr;plan->clampDepth=unsigned(clampDepth);
  // PathIntegrator::initPrimaryRay: the clamp is divided by the BSDF sample count, so the look does not change with it.
  plan->clampValue=clamp/float(bsdfSamples*bsdfSamples);
  int glossy=get<rdl::Int>(sv,"max_glossy_depth"),mirror=get<rdl::Int>(sv,"max_mirror_depth"),hair=get<rdl::Int>(sv,"max_hair_depth"),presenceDepth=get<rdl::Int>(sv,"max_presence_depth");
  need(glossy>=0&&glossy<=16&&mirror>=0&&mirror<=16&&hair>=0&&hair<=16&&presenceDepth>=0&&presenceDepth<=64,"Bounce budget");
  plan->maxGlossyDepth=unsigned(glossy);plan->maxMirrorDepth=unsigned(mirror);plan->maxHairDepth=unsigned(hair);plan->maxPresenceDepth=unsigned(presenceDepth);
  int stf=get<rdl::Int>(sv,"shadow_terminator_fix");need(stf>=0&&stf<=4,"Invalid shadow terminator fix");plan->shadowTerminatorFix=unsigned(stf);
  float roughnessClamping=get<rdl::Float>(sv,"roughness_clamping_factor"),transparency=get<rdl::Float>(sv,"transparency_threshold");
  need(std::isfinite(roughnessClamping)&&roughnessClamping>=0&&std::isfinite(transparency),"Invalid roughness clamping/transparency threshold");
  plan->roughnessClamping=roughnessClamping;plan->transparencyThreshold=transparency;
  // PathIntegrator: bssrdf_samples is a square root (at least two samples); the subsurface integrator keeps
  // at most sixteen exit samples a hit.
  int bssrdf=get<rdl::Int>(sv,"bssrdf_samples"),maxSss=get<rdl::Int>(sv,"max_subsurface_per_path");
  need(bssrdf>=1&&bssrdf<=4&&maxSss>=0&&maxSss<=16,"Subsurface sample budget");
  plan->bssrdfSamples=unsigned(std::max(2,bssrdf*bssrdf));plan->maxSubsurfacePerPath=unsigned(maxSss);
  plan->enableSss=get<rdl::Bool>(sv,"enable_subsurface_scattering")?1u:0u;
  // The volume settings (RenderContext's integrator parameters): the transmittance threshold from the opacity one, the
  // factors clamped to [0, 1]. Volume quality only steps heterogeneous volumes (none are admitted).
  int maxVolumeDepth=get<rdl::Int>(sv,"max_volume_depth"),illumination=get<rdl::Int>(sv,"volume_illumination_samples"),overlap=get<rdl::Int>(sv,"volume_overlap_mode");
  need(maxVolumeDepth>=0&&maxVolumeDepth<=16&&illumination>=0&&illumination<=64&&overlap>=0&&overlap<=2,"Volume settings budget");
  auto unit=[](float f){return std::isfinite(f)?std::min(std::max(f,0.0f),1.0f):0.0f;};
  plan->maxVolumeDepth=unsigned(maxVolumeDepth);plan->volumeIlluminationSamples=unsigned(illumination);plan->volumeOverlapMode=unsigned(overlap);
  plan->volumeTransmittanceThreshold=unit(1.0f-get<rdl::Float>(sv,"volume_opacity_threshold"));
  plan->volumeAttenuationFactor=unit(get<rdl::Float>(sv,"volume_attenuation_factor"));
  plan->volumeContributionFactor=unit(get<rdl::Float>(sv,"volume_contribution_factor"));
  plan->volumePhaseAttenuationFactor=unit(get<rdl::Float>(sv,"volume_phase_attenuation_factor"));
 }else{
 need(get<rdl::Int>(sv,"bsdf_samples")==1&&get<rdl::Int>(sv,"light_samples")==1,"Primary splitting unsupported");
 if(domain==Domain::SurfaceTextures)need(depth==0&&diffuse==0,"Spatial textures require direct-only transport until secondary derivatives are qualified");
 if(spatial){need(depth>=0&&depth<=7&&diffuse>=0&&diffuse<=7,"Spatial bounce budget (0..7 indirect)");plan->surfaceLimit=1+unsigned(std::min(depth,diffuse));}
 else need(depth==2&&diffuse==1,"Only the tested single diffuse event supported");
 need(get<rdl::Float>(sv,"sample_clamping_value")==0&&get<rdl::Float>(sv,"russian_roulette_threshold")==0,"Clamping/roulette unsupported");
 }
 need(paths||get<rdl::Int>(sv,"shadow_terminator_fix")==0,"Shadow terminator correction unsupported");
 need(!get<rdl::Bool>(sv,"lights_visible_in_camera"),"Visible environment background unsupported");
 float frameNumber=get<rdl::Float>(sv,"frame");need(std::isfinite(frameNumber)&&frameNumber>=0&&double(frameNumber)<=4294967295.&&std::floor(frameNumber)==frameNumber,"Invalid integer frame");
 plan->seed=surface::frameSeed(unsigned(frameNumber),0,get<rdl::Bool>(sv,"lock_frame_noise"));
 int filter=get<rdl::Int>(sv,"pixel_filter");plan->filterWidth=get<rdl::Float>(sv,"pixel_filter_width");need(filter>=0&&filter<=2&&surface::finite(plan->filterWidth)&&plan->filterWidth>0&&plan->filterWidth<=4,"Unsupported pixel filter");plan->filter=surface::Filter(filter);
 auto* camera=get<rdl::SceneObject*>(sv,"camera");auto* layerObject=get<rdl::SceneObject*>(sv,"layer");
 need(camera&&camera->getSceneClass().getName()=="PerspectiveCamera","Perspective camera required");need(layerObject&&layerObject->isA<rdl::Layer>(),"Layer required");auto& layer=*layerObject->asA<rdl::Layer>();
 // The lens's depth of field, bokeh and shutter count only with depth of field or motion blur, which are refused.
 attributes(*camera,{"node_xform","focal","film_width_aperture","near","far","dof_aperture","dof_focus_distance","bokeh_sides","bokeh_angle",
  "bokeh_weight_location","bokeh_weight_strength","mb_shutter_open","mb_shutter_close","mb_shutter_bias"});auto cm=plan->paths?rigid(*camera):translation(*camera);need(plan->paths||cm[3][2]>0,"Camera must face the planar surface from positive Z");
 float focal=get<rdl::Float>(*camera,"focal"),film=get<rdl::Float>(*camera,"film_width_aperture");
 auto& cam=plan->camera;cam.nearClip=get<rdl::Float>(*camera,"near");cam.farClip=get<rdl::Float>(*camera,"far");
 need(surface::finite(focal)&&surface::finite(film)&&focal>0&&film>0&&surface::finite(cam.nearClip)&&surface::finite(cam.farClip)&&cam.nearClip>0&&cam.farClip>cam.nearClip,"Invalid lens");
 for(int i=0;i<4;++i){cam.rasterToCamera.m[i][i]=1;for(int j=0;j<4;++j)cam.cameraToRender.m[i][j]=float(cm[i][j]);}
 {const auto w=cm.inverse();const double rows[12]={w[0][0],w[1][0],w[2][0],w[3][0],w[0][1],w[1][1],w[2][1],w[3][1],w[0][2],w[1][2],w[2][2],w[3][2]};
  for(int i=0;i<12;++i)plan->worldToRender[i]=float(rows[i]);}
 cam.rasterToCamera.m[0][0]=cam.rasterToCamera.m[1][1]=film/(focal*width);
 cam.rasterToCamera.m[3][0]=-film/(2*focal);cam.rasterToCamera.m[3][1]=-film/(2*focal)*height/width;
 std::map<std::string,unsigned> materialIds;std::set<const rdl::SceneObject*> allGeometry,setGeometry;const rdl::SceneObject* sky=nullptr;
 std::map<const rdl::SceneObject*,unsigned> lightIds;
 unsigned outputCount=0;bool beauty=false,alpha=false;
 std::map<const rdl::SceneObject*,texture::Binding> maps;std::shared_ptr<OIIO::TextureSystem> texSystem;
 // The meshes to displace (plan mesh, edge vertex count, shader) once their maps' textures are read.
 struct Displaced{size_t mesh;int edgeVertices;displace::Shader shader;};std::vector<Displaced> displaced;
 TextureContext textureContext{assetRoot,&texSystem,&plan->textures,previous?&previous->textures:nullptr};
 for(auto& pair:sorted){auto& o=*pair.second;if(paths||o.getSceneClass().getName()!="ImageMap")continue;
  need(!spatial||domain==Domain::SurfaceTextures,"Spatial map derivatives not implemented; use reference");
  need(!assetRoot.empty()&&maps.size()<8,"Textured preparation requires frozen asset admission; at most 8 maps");
  attributes(o,{"texture","wrap_around","gamma","scale","offset","mip_bias"});
  need(get<rdl::Int>(o,"texture_coordinates")==0&&!get<rdl::Bool>(o,"alpha_only"),"Only RGB mesh-ST ImageMap supported");
  texture::Binding binding;
  auto texturePath=get<rdl::String>(o,"texture");texture::admittedPath(fs::path(texturePath),assetRoot);
  // A retained File holds a Windows read lease, so unchanged assets are still
  // immutable and the same host mip cache can survive camera/material edits.
  for(auto& admitted:maps)if(admitted.second.file->name.string()==texturePath)binding.file=admitted.second.file;
  if(!binding.file&&previous)for(auto* set:{&previous->diffuseMaps,&previous->emissionMaps})for(auto& old:*set)if(old.second.file->name.string()==texturePath)binding.file=old.second.file;
  if(binding.file)texSystem=binding.file->system;else {if(!texSystem)texSystem=texture::system();binding.file=std::make_shared<texture::File>(fs::path(texturePath),assetRoot,texSystem);}
  auto scale=get<rdl::Vec2f>(o,"scale"),offset=get<rdl::Vec2f>(o,"offset");binding.sx=scale.x;binding.sy=scale.y;binding.ox=offset.x;binding.oy=offset.y;
  binding.wrap=get<rdl::Bool>(o,"wrap_around");binding.mipBias=get<rdl::Float>(o,"mip_bias");int gamma=get<rdl::Int>(o,"gamma");need(gamma>=0&&gamma<=2,"Invalid gamma mode");binding.gamma=gamma!=0;
  need(std::isfinite(scale.x)&&std::isfinite(scale.y)&&std::abs(scale.x)<=256&&std::abs(scale.y)<=256&&std::isfinite(offset.x)&&std::isfinite(offset.y)&&std::abs(offset.x)<=256&&std::abs(offset.y)<=256&&std::isfinite(binding.mipBias)&&binding.mipBias>=-1&&binding.mipBias<=32,"Texture transform/bias budget");maps.emplace(&o,std::move(binding));
 }

 std::vector<const rdl::SceneObject*> switches;
 for(auto& pair:sorted){auto& o=*pair.second;auto cls=o.getSceneClass().getName();
  if(cls=="SceneVariables"||&o==camera||maps.count(&o))continue;
  // On the path tracer a map is admitted where a material is bound to it (map_admission.h).
  if(paths&&(o.isA<rdl::Map>()||o.isA<rdl::NormalMap>()))continue;
  // A displacement is admitted with the assignment that binds it (admitDisplacement).
  if(paths&&o.isA<rdl::Displacement>())continue;
  if(cls=="UsdPreviewSurface"&&paths){
   // The whole material (shade_material.h); maps on its diffuse and emissive colours.
   attributes(o,{"diffuseColor","emissiveColor","useSpecularWorkflow","specularColor","metallic","roughness","clearcoat","clearcoatRoughness","opacity","opacityThreshold","ior","normal","displacement","occlusion"},{"diffuseColor","emissiveColor","specularColor","metallic","roughness","clearcoat","clearcoatRoughness","opacity","ior","normal"});
   shade::UsdPreviewSurfaceParams q{};
   auto c3=[&](const char* n){auto c=get<rdl::Rgb>(o,n);V3 v{c.r,c.g,c.b};need(surface::finite(v),o.getName()+": invalid colour");return v;};
   auto f1=[&](const char* n){float f=get<rdl::Float>(o,n);need(std::isfinite(f),o.getName()+": invalid value");return f;};
   q.diffuseColor=c3("diffuseColor");q.emissiveColor=c3("emissiveColor");q.specularColor=c3("specularColor");
   int workflow=get<rdl::Int>(o,"useSpecularWorkflow");need(workflow==0||workflow==1,o.getName()+": invalid workflow");q.useSpecularWorkflow=float(workflow);
   q.metallic=f1("metallic");q.roughness=f1("roughness");q.clearcoat=f1("clearcoat");q.clearcoatRoughness=f1("clearcoatRoughness");
   q.opacity=f1("opacity");q.opacityThreshold=f1("opacityThreshold");q.ior=f1("ior");need(q.ior>0,o.getName()+": invalid ior");
   auto n=get<rdl::Vec3f>(o,"normal");q.normal={n.x,n.y,n.z};need(surface::finite(q.normal),o.getName()+": invalid normal");
   // Cut outs (presence 0) would need shadow rays that pass them; they fall back.
   need(!(q.opacityThreshold>0&&q.opacity<q.opacityThreshold),o.getName()+": opacity cut out unsupported");
   need(!(q.opacityThreshold>0&&o.getBinding(*o.getSceneClass().getAttribute("opacity"))),o.getName()+": opacity cut out unsupported");
   shade::MaterialRecord rec;rec.kind=shade::MatUsdPreviewSurface;rec.offset=unsigned(plan->materialPool.size());rec.count=shade::UsdPreviewSurfaceFloats;
   // MoonRay reads MOONRAY_MODO_USD_SPECULAR (UsdPreviewSurface.cc) from its environment; so does the renderer here.
   const char* modoSpecular=std::getenv("MOONRAY_MODO_USD_SPECULAR");
   if(modoSpecular&&modoSpecular[0]==49)rec.flags|=shade::MatModoUsdSpecular;
   const float* qf=reinterpret_cast<const float*>(&q);plan->materialPool.insert(plan->materialPool.end(),qf,qf+shade::UsdPreviewSurfaceFloats);
   // Its bound attributes and the maps behind them (map_admission.h).
   {MapProgramBuilder program{plan->materialPool,textureContext};std::vector<shade::MapBinding> bindings;using U=shade::UsdPreviewSurfaceParams;
    program.bindingsOf(o,{{"diffuseColor",X2_OFF(U,diffuseColor)},{"emissiveColor",X2_OFF(U,emissiveColor)},{"specularColor",X2_OFF(U,specularColor)},{"metallic",X2_OFF(U,metallic)},{"roughness",X2_OFF(U,roughness)},{"clearcoat",X2_OFF(U,clearcoat)},{"clearcoatRoughness",X2_OFF(U,clearcoatRoughness)},{"opacity",X2_OFF(U,opacity)},{"ior",X2_OFF(U,ior)},{"normal",X2_OFF(U,normal)}},bindings);
    rec.bindings=unsigned(plan->materialPool.size());rec.bindingCount=unsigned(bindings.size());
    for(auto& b:bindings){const float* bf=reinterpret_cast<const float*>(&b);plan->materialPool.insert(plan->materialPool.end(),bf,bf+sizeof(b)/sizeof(float));}
    rec.maps=program.finish();if(program.polyVertices)rec.flags|=shade::MatPolyVertices;}
   materialIds[o.getName()]=unsigned(plan->materials.size());plan->materials.push_back({q.diffuseColor,q.emissiveColor});plan->materialRecords.push_back(rec);
  }else if(paths&&(cls=="SwitchMaterial"||cls=="RaySwitchMaterial")){
   // Their records once every material is read (shade_material.h SwitchRecord).
   {std::set<std::string> all;for(auto i=o.getSceneClass().beginAttributes();i!=o.getSceneClass().endAttributes();++i)all.insert((*i)->getName());attributes(o,all);}
   materialIds[o.getName()]=unsigned(plan->materials.size());plan->materials.push_back({V3{0,0,0},V3{0,0,0}});plan->materialRecords.push_back(shade::MaterialRecord{});switches.push_back(&o);
  }else if(paths&&(dwaClass(cls)||dwaCombinator(cls)||hairCombinator(cls))){
   // The DwaBase family and its combinators (shade_dwabase.h, shade_dwalayer.h, dwa_admission.h): each material its
   // own tree, its inputs' trees inside it.
   shade::MaterialRecord rec=admitDwaTree(o,plan->materialPool,plan->dwaSlots,textureContext,&plan->glitter,&plan->randomWalk);
   materialIds[o.getName()]=unsigned(plan->materials.size());plan->materials.push_back({V3{0,0,0},V3{0,0,0}});plan->materialRecords.push_back(rec);
  }else if(cls=="UsdPreviewSurface"){
   attributes(o,{"diffuseColor","useSpecularWorkflow","specularColor","emissiveColor"},{"diffuseColor","emissiveColor"});
   need(get<rdl::Int>(o,"useSpecularWorkflow")==1&&zero(get<rdl::Rgb>(o,"specularColor")),o.getName()+": Fresnel/specular/metal is not diffuse-only");
   need(get<rdl::Float>(o,"opacity")==1&&get<rdl::Float>(o,"clearcoat")==0,o.getName()+": opacity/coat unsupported");
   materialIds[o.getName()]=unsigned(plan->materials.size());plan->materials.push_back({color(get<rdl::Rgb>(o,"diffuseColor")),color(get<rdl::Rgb>(o,"emissiveColor"))});
   for(auto name:{"diffuseColor","emissiveColor"}){auto* binding=o.getBinding(*o.getSceneClass().getAttribute(name));if(binding){need(maps.count(binding),"Unsupported material map");(std::string(name)=="diffuseColor"?plan->diffuseMaps:plan->emissionMaps).emplace(materialIds.at(o.getName()),maps.at(binding));}}
  }else if(paths&&isLight(cls)){
   lights::Light l;if(admitLight(o,get<rdl::Float>(sv,"scene_scale"),l)){need(plan->lights.size()<32,"At most 32 lights");lightIds[&o]=unsigned(plan->lights.size());plan->lights.push_back(l);}
  }else if(cls=="EnvLight"){
   need(!sky,"Multiple environment lights unsupported");sky=&o;attributes(o,{"color","intensity","exposure","sample_upper_hemisphere_only"});need(!get<rdl::Bool>(o,"sample_upper_hemisphere_only"),"Hemisphere environment unsupported");
   auto c=color(get<rdl::Rgb>(o,"color"));float intensity=get<rdl::Float>(o,"intensity"),exposure=get<rdl::Float>(o,"exposure");need(surface::finite(intensity)&&intensity>=0&&surface::finite(exposure)&&std::abs(exposure)<=32,"Invalid light intensity");plan->sky=surface::mul(c,intensity*std::pow(2.f,exposure));need(surface::finite(plan->sky),"Environment radiance overflow");
  }else if(cls=="RdlMeshGeometry"||(paths&&isCurves(cls)))allGeometry.insert(&o);
  else if(cls=="GeometrySet"){
   attributes(o,{"geometries"});for(auto* geom:o.asA<rdl::GeometrySet>()->getGeometries())need(setGeometry.insert(geom).second,"Repeated geometry sets unsupported");
  }else if(cls=="Layer"){
   need(&o==&layer,"Additional layers unsupported");attributes(o,{"geometries","parts","surface_shaders","lightsets","displacements","volume_shaders","lightfiltersets","shadowsets","shadowreceiversets"});
  }else if(cls=="LightSet")attributes(o,{"lights"});
  else if(cls=="RenderOutput"){
   attributes(o,{"file_name","result","channel_format","compression"});int result=get<rdl::Int>(o,"result");need(result==0||result==1,"Unsupported AOV");need(paths||get<rdl::Int>(o,"channel_format")==0,"Only float32 outputs supported");++outputCount;(result?alpha:beauty)=true;
  }else if(paths&&(cls=="PerspectiveCamera"||cls=="OrthographicCamera")){
   // Another camera: a projector, read by the maps that name it (ProjectCameraMap_v2).
  }else if(paths&&cls=="BaseVolume"){
   // Admitted with the assignment that binds it (admitVolume).
  }else if(paths&&cls=="UserData"){
   // Read where a geometry lists it among its primitive attributes.
  }else throw Unsupported(o.getName()+": unsupported class "+cls);
 }
 // The switches' records: copies of their materials' (a switch's switch first; a material not shaded fails the scene).
 {std::map<const rdl::SceneObject*,int> state;
  std::function<void(const rdl::SceneObject*)> fill=[&](const rdl::SceneObject* s){
   int& st=state[s];if(st==2)return;need(st==0,s->getName()+": switch materials in a cycle");st=1;
   auto sub=[&](const rdl::SceneObject* m){shade::MaterialRecord rec{};if(!m)return rec;
    need(materialIds.count(m->getName()),s->getName()+": its material "+m->getName()+" is not shaded");
    const std::string mc=m->getSceneClass().getName();if(mc=="SwitchMaterial"||mc=="RaySwitchMaterial")fill(m);
    return plan->materialRecords[materialIds.at(m->getName())];};
   shade::SwitchRecord r{};
   if(s->getSceneClass().getName()=="SwitchMaterial"){const int choice=get<rdl::Int>(*s,"choice");
    if(choice>=0&&choice<64)r.def=sub(get<rdl::SceneObject*>(*s,("material"+std::to_string(choice)).c_str()));}
   else{r.byRay=1;r.cutout=get<rdl::Bool>(*s,"cutout_camera_rays")?1:0;r.def=sub(get<rdl::SceneObject*>(*s,"default_material"));
    r.camera=sub(get<rdl::SceneObject*>(*s,"camera_ray_material"));r.mirror=sub(get<rdl::SceneObject*>(*s,"indirect_mirror_ray_material"));
    r.glossy=sub(get<rdl::SceneObject*>(*s,"indirect_glossy_ray_material"));r.diffuse=sub(get<rdl::SceneObject*>(*s,"indirect_diffuse_ray_material"));}
   shade::MaterialRecord rec{};rec.kind=shade::MatSwitch;rec.offset=unsigned(plan->materialPool.size());rec.count=shade::SwitchRecordFloats;
   for(const auto* sr:{&r.def,&r.camera,&r.mirror,&r.glossy,&r.diffuse})rec.flags|=sr->flags&shade::MatPolyVertices;
   const float* f=reinterpret_cast<const float*>(&r);plan->materialPool.insert(plan->materialPool.end(),f,f+shade::SwitchRecordFloats);
   plan->materialRecords[materialIds.at(s->getName())]=rec;st=2;};
  for(auto* s:switches)fill(s);}
 // The path tracer's caller writes the outputs it asks for: a beauty, an alpha, or both.
 need((paths||sky)&&(paths?outputCount>=1:outputCount==2&&beauty&&alpha),"One environment and beauty/alpha outputs required");need(allGeometry==setGeometry&&!allGeometry.empty(),"Geometry sets must contain exactly the rendered meshes");
 need(size_t(layer.getAssignmentCount())==allGeometry.size(),"Only one whole-mesh assignment supported");
 for(auto& pair:sorted){auto& o=*pair.second;if(!allGeometry.count(&o))continue;
  auto* geom=o.asA<rdl::Geometry>();int id=layer.getAssignmentId(geom,"");need(id>=0,"Part-specific assignment unsupported");
  auto* mat=layer.lookupMaterial(id);auto* lights=layer.lookupLightSet(id);
  // A volume shader: the mesh bounds a volume (with or without a surface of its own).
  const rdl::SceneObject* volumeShader=paths?layer.lookupVolumeShader(id):nullptr;
  need((mat&&materialIds.count(mat->getName()))||(volumeShader&&!mat),o.getName()+": missing diffuse material");need(lights,"Missing light set");
  const auto& ls=lights->getLights();
  if(paths){unsigned mask=0;for(auto* light:ls){auto it=lightIds.find(light);if(it!=lightIds.end())mask|=1u<<it->second;else need(!light->get<rdl::Bool>("on")||isLight(light->getSceneClass().getName()),o.getName()+": unsupported light");}plan->meshLights.push_back(mask);}
  else need(ls.size()==1&&ls[0]==sky,"Per-object light linking unsupported");
  const rdl::SceneObject* displacementShader=paths?layer.lookupDisplacement(id):nullptr;
  need((paths||!layer.lookupDisplacement(id))&&(paths||!layer.lookupVolumeShader(id))&&!layer.lookupLightFilterSet(id)&&!layer.lookupShadowSet(id)&&!layer.lookupShadowReceiverSet(id),o.getName()+": displacement/volume/filter/shadow links unsupported");
  int volumeIndex=-1;
  if(volumeShader){
   need(!isCurves(o.getSceneClass().getName()),o.getName()+": a volume bound to curves is not rendered");
   need(plan->volumes.size()<volume::MaxVolumes,"At most 32 volumes");
   volumeIndex=int(plan->volumes.size());plan->volumes.push_back(admitVolume(*volumeShader,plan->meshLights.back()));
  }
  // A displacement (mesh_displacement.h): MoonRay tessellates the mesh uniformly to its mesh resolution (adaptive
  // tessellation needs the camera's frustum, not ported) and displaces it.
  int edgeVertices=0;displace::Shader displacement;
  if(displacementShader){
   need(!isCurves(o.getSceneClass().getName()),o.getName()+": a displacement on curves is not rendered");
   need(get<rdl::Float>(o,"adaptive_error")<=0.0f,o.getName()+": adaptive tessellation is not rendered yet");
   const float resolution=get<rdl::Float>(o,"mesh_resolution");need(std::isfinite(resolution)&&resolution<=64.0f,o.getName()+": a mesh resolution above 64");
   edgeVertices=std::max(0,std::max(1,int(resolution))-1);
   displacement=admitDisplacement(*displacementShader,plan->materialPool,textureContext);
   // MoonRay tessellates a displaced mesh into quads: polygon maps would read four polyvertices.
   need(!mat||!(plan->materialRecords.at(materialIds.at(mat->getName())).flags&shade::MatPolyVertices),o.getName()+": polygon maps on a displaced mesh are not rendered yet");
  }
  auto sig=signature(o,frame);std::shared_ptr<const MeshData> data;
  // The fur file can change under the same name: fur is read again each time.
  const bool curveGeometry=isCurves(o.getSceneClass().getName());
  if(previous&&previous->domain==domain&&o.getSceneClass().getName()!="ModoFurGeometry"&&!displacementShader)for(auto& old:previous->meshes)if(old.data->name==o.getName()&&old.data->signature==sig){data=old.data;++plan->reusedMeshes;break;}
  if(!data&&curveGeometry){auto m=std::make_shared<MeshData>();m->name=o.getName();m->signature=std::move(sig);const auto transform=affine(o);
   {const auto w=transform.inverse();const double rows[12]={w[0][0],w[1][0],w[2][0],w[3][0],w[0][1],w[1][1],w[2][1],w[3][1],w[0][2],w[1][2],w[2][2],w[3][2]};
    for(int i=0;i<12;++i)m->worldToObject[i]=float(rows[i]);}
   admitCurves(o,transform,*m);data=std::move(m);++plan->preparedMeshes;}
  // All geometry attribute/binding identities match before validation is reused.
  // Material/light assignments are checked above for EVERY epoch.
  if(!data){
  if(paths)attributes(o,{"vertex_list_0","face_vertex_count","vertices_by_index","is_subd","node_xform","smooth_normal","normal_list","uv_list","primitive_attributes","mesh_resolution","adaptive_error"});
  else attributes(o,{"vertex_list_0","face_vertex_count","vertices_by_index","is_subd","node_xform","smooth_normal"});
  need(!get<rdl::Bool>(o,"is_subd"),o.getName()+": subdivision unsupported");
  // Supplied normals are the shading normals; on the path tracer a mesh without them smooths its own (PolyMeshCalcNv).
  if(spatial)need(!get<rdl::Bool>(o,"smooth_normal")||paths,"Spatial smooth normals unsupported");
  auto transform=spatial?affine(o):translation(o);if(!spatial)need(transform[3][2]==0,o.getName()+": only coplanar geometry supported");
   auto m=std::make_shared<MeshData>();m->name=o.getName();m->signature=std::move(sig);
   {const auto w=transform.inverse();const double rows[12]={w[0][0],w[1][0],w[2][0],w[3][0],w[0][1],w[1][1],w[2][1],w[3][1],w[0][2],w[1][2],w[2][2],w[3][2]};
    for(int i=0;i<12;++i)m->worldToObject[i]=float(rows[i]);}
   const auto& v=o.get<rdl::Vec3fVector>("vertex_list");const auto& counts=o.get<rdl::IntVector>("face_vertex_count");const auto& indices=o.get<rdl::IntVector>("vertices_by_index");need(!v.empty()&&!counts.empty(),"Empty mesh unsupported");
   m->positions.reserve(v.size());m->triangles.reserve(counts.size());
   for(auto p:v){need(std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z)&&(spatial||p.z==0),"Invalid spatial/planar vertex");
    V3 point{float(p.x*transform[0][0]+p.y*transform[1][0]+p.z*transform[2][0]+transform[3][0]),float(p.x*transform[0][1]+p.y*transform[1][1]+p.z*transform[2][1]+transform[3][1]),float(p.x*transform[0][2]+p.y*transform[1][2]+p.z*transform[2][2]+transform[3][2])};
    need(surface::finite(point)&&(!spatial||(std::abs(point.x)<=10000&&std::abs(point.y)<=10000&&std::abs(point.z)<=10000)),"Transformed vertex bound");m->positions.push_back(point);}
   PolygonSplit split;
   if(paths){split=splitPolygons(v,counts,indices,o.getName());
    // MoonRay's QuadMesh hands polygon maps four polyvertices; a displaced mesh is tessellated from its faces.
    need(!split.quads||!mat||!(plan->materialRecords.at(materialIds.at(mat->getName())).flags&shade::MatPolyVertices),o.getName()+": polygon maps on a quad mesh are not rendered yet");
    need(!displacementShader||(!split.quads&&split.faceOf.size()==counts.size()),o.getName()+": a displacement on a mesh with faces of more than three vertices is not rendered yet");}
   else for(size_t i=0;i<counts.size();++i){need(counts[i]==3,"Non-triangle mesh");split.corners.insert(split.corners.end(),{unsigned(i*3),unsigned(i*3+1),unsigned(i*3+2)});split.faceOf.push_back(unsigned(i));}
   std::vector<unsigned> kept;  // the split's triangles kept, in order
   for(size_t i=0;i<split.faceOf.size();++i){unsigned ids[3];for(int j=0;j<3;++j){auto k=indices[split.corners[i*3+size_t(j)]];need(k>=0&&size_t(k)<v.size(),"Vertex index out of bounds");ids[j]=unsigned(k);}
    auto a=m->positions[ids[0]],b=m->positions[ids[1]],c=m->positions[ids[2]];double area=(double(b.x)-a.x)*(double(c.y)-a.y)-(double(b.y)-a.y)*(double(c.x)-a.x);
    if(spatial){V3 n;const bool some=surface::normalize(surface::cross(surface::add(b,surface::mul(a,-1)),surface::add(c,surface::mul(a,-1))),n);
     if(!some&&paths)continue;need(some,"Degenerate triangle");}
    else need(std::isfinite(area)&&area>0,"Degenerate/reversed triangle unsupported");m->triangles.push_back({ids[0],ids[1],ids[2]});kept.push_back(unsigned(i));}
   need(!m->triangles.empty(),o.getName()+": no triangle of any area");
   // Face-varying values a kept triangle's corner, uniform ones its face's (QuadMesh/TriMesh splitNGons).
   auto byCorner=[&](const std::vector<float>& d,unsigned n){std::vector<float> r;r.reserve(kept.size()*3*n);
    for(unsigned t:kept)for(int j=0;j<3;++j){const size_t c=split.corners[size_t(t)*3+size_t(j)];r.insert(r.end(),d.begin()+std::ptrdiff_t(c*n),d.begin()+std::ptrdiff_t((c+1)*n));}return r;};
   auto byFace=[&](const std::vector<float>& d,unsigned n){std::vector<float> r;r.reserve(kept.size()*n);
    for(unsigned t:kept){const size_t f=split.faceOf[t];r.insert(r.end(),d.begin()+std::ptrdiff_t(f*n),d.begin()+std::ptrdiff_t((f+1)*n));}return r;};
   if(paths){
    // pickRate: face-varying when there is one value a face-vertex, else one a vertex.
    auto rate=[&](size_t n)->unsigned{if(n==0)return shade::RateNone;if(n==indices.size())return shade::RateFaceVarying;if(n==v.size())return shade::RateVertex;throw Unsupported(o.getName()+": unsupported attribute rate");};
    const auto& nl=o.get<rdl::Vec3fVector>("normal_list");m->normalRate=rate(nl.size());
    // No normals and smooth_normal: each vertex's the normalized sum of its triangles' (PolyMeshCalcNv).
    // A QuadMesh sums each quad's normal (QuadMeshCalcNv), a TriMesh each triangle's.
    if(nl.empty()&&get<rdl::Bool>(o,"smooth_normal")){
     if(split.quads)m->normals=displace::smoothNormals(m->positions,split.quadVertices,4);
     else{std::vector<int> faces;faces.reserve(m->triangles.size()*3);
      for(auto& t:m->triangles)faces.insert(faces.end(),{int(t.a),int(t.b),int(t.c)});
      m->normals=displace::smoothNormals(m->positions,faces,3);}
     m->normalRate=shade::RateVertex;}
    if(!nl.empty()){
     // Normals transform by the inverse transpose of the node transform (row vectors: n * inverse(M)^T).
     double M[3][3];for(int i=0;i<3;++i)for(int j=0;j<3;++j)M[i][j]=transform[i][j];
     double det=M[0][0]*(M[1][1]*M[2][2]-M[1][2]*M[2][1])-M[0][1]*(M[1][0]*M[2][2]-M[1][2]*M[2][0])+M[0][2]*(M[1][0]*M[2][1]-M[1][1]*M[2][0]);
     double inv[3][3];for(int i=0;i<3;++i)for(int j=0;j<3;++j){int a=(j+1)%3,b=(j+2)%3,cc=(i+1)%3,d=(i+2)%3;inv[i][j]=(M[a][cc]*M[b][d]-M[a][d]*M[b][cc])/det;}
     m->normals.reserve(nl.size());
     for(auto n:nl){double x=n.x*inv[0][0]+n.y*inv[0][1]+n.z*inv[0][2],y=n.x*inv[1][0]+n.y*inv[1][1]+n.z*inv[1][2],z=n.x*inv[2][0]+n.y*inv[2][1]+n.z*inv[2][2];
      double l=std::sqrt(x*x+y*y+z*z);need(std::isfinite(l)&&l>0,o.getName()+": invalid normal");m->normals.push_back({float(x/l),float(y/l),float(z/l)});}
     if(m->normalRate==shade::RateFaceVarying){std::vector<float> f;for(auto& n:m->normals)f.insert(f.end(),{n.x,n.y,n.z});f=byCorner(f,3);
      m->normals.clear();for(size_t i=0;i<f.size();i+=3)m->normals.push_back({f[i],f[i+1],f[i+2]});}
    }
    // primitive_attributes: UserData of floats, colours, vectors and ints (geom/PrimitiveUserData processArbitraryData).
    for(auto* object:o.get<rdl::SceneObjectVector>("primitive_attributes")){
     need(object&&object->getSceneClass().getName()=="UserData",o.getName()+": a primitive attribute that is not UserData");
     attributes(*object,{"bool_key","bool_values","int_key","int_values","float_key","float_values_0","float_values_1","string_key","string_values","color_key","color_values_0","color_values_1","vec2f_key","vec2f_values_0","vec2f_values_1","vec3f_key","vec3f_values_0","vec3f_values_1","mat3f_key","mat3f_values_0","mat3f_values_1","mat4f_key","mat4f_values_0","mat4f_values_1","rate"});
     const int explicitRate=get<rdl::Int>(*object,"rate");
     // pickRate: the explicit rate when its count fits, else guessed from the count (auto).
     auto pick=[&](size_t n)->unsigned{const size_t fv=indices.size(),uni=counts.size(),vert=v.size();
      switch(explicitRate){case 1:return n==1?1u:0u;case 3:return n==uni?3u:0u;case 4:return n==vert?4u:0u;case 5:return n==vert?5u:0u;case 6:return n==fv?6u:0u;case 0:break;default:return 0u;}
      if(n==0)return 0u;if(n==1)return 1u;if(n==fv)return 6u;if(n==uni)return 3u;if(n==vert)return 4u;return 0u;};
     auto add=[&](const std::string& key,unsigned type,unsigned components,const std::vector<float>& values,size_t count){
      if(key.empty())return;const unsigned r=pick(count);need(r!=0,o.getName()+": primitive attribute "+key+" has an unsupported rate or size");
      for(float f:values)need(std::isfinite(f),o.getName()+": invalid primitive attribute "+key);
      const std::vector<float> expanded=r==6?byCorner(values,components):r==3?byFace(values,components):values;
      m->prims.push_back(shade::PrimAttr{shade::primKey(key.c_str(),type),components,r,unsigned(m->primData.size())});m->primData.insert(m->primData.end(),expanded.begin(),expanded.end());};
     {const auto& d=get<rdl::FloatVector>(*object,"float_values_0");add(get<rdl::String>(*object,"float_key"),shade::PrimFloat,1,std::vector<float>(d.begin(),d.end()),d.size());}
     {const auto& d=get<rdl::IntVector>(*object,"int_values");std::vector<float> f;for(int i:d)f.push_back(float(i));add(get<rdl::String>(*object,"int_key"),shade::PrimInt,1,f,d.size());}
     {const auto& d=get<rdl::RgbVector>(*object,"color_values_0");std::vector<float> f;for(auto c:d){f.push_back(c.r);f.push_back(c.g);f.push_back(c.b);}add(get<rdl::String>(*object,"color_key"),shade::PrimRgb,3,f,d.size());}
     {const auto& d=get<rdl::Vec2fVector>(*object,"vec2f_values_0");std::vector<float> f;for(auto c:d){f.push_back(c.x);f.push_back(c.y);}add(get<rdl::String>(*object,"vec2f_key"),shade::PrimVec2f,2,f,d.size());}
     {const auto& d=get<rdl::Vec3fVector>(*object,"vec3f_values_0");std::vector<float> f;for(auto c:d){f.push_back(c.x);f.push_back(c.y);f.push_back(c.z);}add(get<rdl::String>(*object,"vec3f_key"),shade::PrimVec3f,3,f,d.size());}
    }
    const auto& ul=o.get<rdl::Vec2fVector>("uv_list");m->uvRate=rate(ul.size());
    m->uvs.reserve(ul.size()*2);for(auto u:ul){need(std::isfinite(u.x)&&std::isfinite(u.y),o.getName()+": invalid uv");m->uvs.push_back(u.x);m->uvs.push_back(u.y);}
    if(m->uvRate==shade::RateFaceVarying)m->uvs=byCorner(m->uvs,2);
   }
   data=std::move(m);++plan->preparedMeshes;
  }
  plan->bytes+=data->positions.size()*sizeof(V3)+data->triangles.size()*sizeof(Tri)+data->curvePoints.size()*sizeof(float)+data->curveSpans.size()*sizeof(unsigned);plan->meshes.push_back({data,mat?materialIds.at(mat->getName()):~0u,volumeIndex});
  if(displacementShader)displaced.push_back({plan->meshes.size()-1,edgeVertices,displacement});
 }
 if(gpuTextures(domain)){uint64_t total=0;std::set<texture::File*> files;
  for(auto* set:{&plan->diffuseMaps,&plan->emissionMaps})for(auto& pair:*set){auto& file=*pair.second.file;if(!files.insert(&file).second)continue;total+=file.decodedBytes;need(total<=(4ull<<30),"Aggregate host texture budget");if(!file.pyramid)file.pyramid=std::make_shared<texture::Pyramid>(file.name.string());}
  for(auto& f:plan->textures){auto& file=*f;if(files.insert(&file).second){total+=file.decodedBytes;need(total<=(4ull<<30),"Aggregate host texture budget");}if(!file.pyramid)file.pyramid=std::make_shared<texture::Pyramid>(file.name.string());plan->textureImages.push_back(&file.pyramid->image);}
 }
 if(plan->paths&&plan->randomWalk)plan->walkSequences=walkSequences();
 // The displaced meshes (mesh_displacement.h), their maps' textures read.
 if(!displaced.empty()){const displace::Textures textures{plan->textureImages.data(),unsigned(plan->textureImages.size())};
  for(auto& d:displaced){auto& mesh=plan->meshes[d.mesh];const MeshData& base=*mesh.data;
   auto out=displace::displaceMesh(base,d.edgeVertices,d.shader,plan->materialPool.data(),textures,plan->worldToRender);
   need(out->positions.size()<=limits.vertices&&out->triangles.size()<=limits.triangles&&!out->triangles.empty(),base.name+": displaced mesh budget");
   plan->bytes+=out->positions.size()*sizeof(V3)+out->triangles.size()*sizeof(Tri);plan->bytes-=base.positions.size()*sizeof(V3)+base.triangles.size()*sizeof(Tri);
   mesh.data=std::move(out);}}
 // Textures at bounced hits need MoonRay's ray differentials through lobes (PATH_TRACER.md, phase 1b).
 if(plan->paths&&(!plan->diffuseMaps.empty()||!plan->emissionMaps.empty()))need(plan->maxDepth==0||plan->maxDiffuseDepth==0,"Textured bounces need secondary ray differentials");
 if(plan->paths){unsigned samples=0;for(auto mask:plan->meshLights)samples=std::max(samples,unsigned(__builtin_popcount(mask))*plan->lightSamples);need(samples<=64,"At most 64 light samples a hit");}
 need(plan->bytes<=limits.bytes,"Prepared geometry budget");return plan;
}
inline PlanView prepare(CanonicalSession& session,const CanonicalView& frame,PlanView previous={},Limits limits={},const fs::path& assetRoot={},Domain domain=Domain::Planar,bool allowAdaptive=false,bool paths=false){
 return session.inspectPrepared(frame,[&](const rdl::SceneContext& context,CanonicalView exact){return prepare(context,exact,previous,limits,assetRoot,domain,allowAdaptive,paths);});
}
}
