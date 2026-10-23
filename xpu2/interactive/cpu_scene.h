// Private experimental canonical-scene adapter. Preparation is NOT qualification.
#pragma once
#include "canonical_session.h"
#include "surface_core.h"
#include "host_texture.h"
#include <cmath>
#include <map>
#include <set>
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
struct MeshData {std::string name;std::vector<V3> positions;std::vector<Tri> triangles;std::vector<std::shared_ptr<const ix::Buffer>> signature;};
struct Mesh {std::shared_ptr<const MeshData> data;unsigned material;};
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
};
using PlanView=std::shared_ptr<const Plan>;
struct Limits {size_t vertices=1000000,triangles=1000000,bytes=64ull<<20,objects=4096,pixels=1048576;};
template<class T>inline T get(const rdl::SceneObject& o,const char* name){return o.get<T>(name);}
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
inline rdl::Mat4d affine(const rdl::SceneObject& obj){
 auto m=get<rdl::Mat4d>(obj,"node_xform");
 for(int i=0;i<4;++i)for(int j=0;j<4;++j)need(std::isfinite(m[i][j])&&std::abs(m[i][j])<=10000,"Spatial transform bound");
 need(m[0][3]==0&&m[1][3]==0&&m[2][3]==0&&m[3][3]==1,"Projective mesh transform unsupported");
 double det=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
 need(std::isfinite(det)&&det>1.e-12,"Singular/reflected transform unsupported");return m;
}
inline std::vector<std::shared_ptr<const ix::Buffer>> signature(const rdl::SceneObject& o,const CanonicalView& frame){
 auto entity=frame->routing->scene->entities.at(ri::objectId(o.getName()));std::vector<std::shared_ptr<const ix::Buffer>> value;
 for(auto& id:entity->dependencies){auto attr=frame->routing->scene->entities.at(id);for(auto& pair:attr->buffers)value.push_back(pair.second);}return value;
}
inline PlanView prepare(const rdl::SceneContext& context,const CanonicalView& frame,PlanView previous={},Limits limits={},const fs::path& assetRoot={},Domain domain=Domain::Planar,bool allowAdaptive=false){
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
   need(v.size()<=limits.vertices-verts&&t.size()<=limits.triangles-tris,"Geometry count budget");verts+=v.size();tris+=t.size();need(ind.size()==t.size()*3,"Only triangle topology supported");
  }
 }
 need(verts*sizeof(V3)+tris*sizeof(Tri)<=limits.bytes,"Prepared geometry byte budget");
 attributes(sv,{"camera","layer","image_width","image_height","pixel_samples","sampling_mode","min_adaptive_samples","max_adaptive_samples","target_adaptive_error","frame","lock_frame_noise","pixel_filter","pixel_filter_width","bsdf_samples","light_samples","max_depth","max_diffuse_depth","enable_dof","enable_motion_blur","sample_clamping_value","shadow_terminator_fix","two_stage_output","russian_roulette_threshold","lights_visible_in_camera"});
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
 need(get<rdl::Int>(sv,"bsdf_samples")==1&&get<rdl::Int>(sv,"light_samples")==1,"Primary splitting unsupported");
 int depth=get<rdl::Int>(sv,"max_depth"),diffuse=get<rdl::Int>(sv,"max_diffuse_depth");
 if(domain==Domain::SurfaceTextures)need(depth==0&&diffuse==0,"Spatial textures require direct-only transport until secondary derivatives are qualified");
 if(spatial){need(depth>=0&&depth<=7&&diffuse>=0&&diffuse<=7,"Spatial bounce budget (0..7 indirect)");plan->surfaceLimit=1+unsigned(std::min(depth,diffuse));}
 else need(depth==2&&diffuse==1,"Only the tested single diffuse event supported");
 need(get<rdl::Float>(sv,"sample_clamping_value")==0&&get<rdl::Float>(sv,"russian_roulette_threshold")==0,"Clamping/roulette unsupported");
 need(get<rdl::Int>(sv,"shadow_terminator_fix")==0,"Shadow terminator correction unsupported");
 need(!get<rdl::Bool>(sv,"lights_visible_in_camera"),"Visible environment background unsupported");
 float frameNumber=get<rdl::Float>(sv,"frame");need(std::isfinite(frameNumber)&&frameNumber>=0&&double(frameNumber)<=4294967295.&&std::floor(frameNumber)==frameNumber,"Invalid integer frame");
 plan->seed=surface::frameSeed(unsigned(frameNumber),0,get<rdl::Bool>(sv,"lock_frame_noise"));
 int filter=get<rdl::Int>(sv,"pixel_filter");plan->filterWidth=get<rdl::Float>(sv,"pixel_filter_width");need(filter>=0&&filter<=2&&surface::finite(plan->filterWidth)&&plan->filterWidth>0&&plan->filterWidth<=4,"Unsupported pixel filter");plan->filter=surface::Filter(filter);
 auto* camera=get<rdl::SceneObject*>(sv,"camera");auto* layerObject=get<rdl::SceneObject*>(sv,"layer");
 need(camera&&camera->getSceneClass().getName()=="PerspectiveCamera","Perspective camera required");need(layerObject&&layerObject->isA<rdl::Layer>(),"Layer required");auto& layer=*layerObject->asA<rdl::Layer>();
 attributes(*camera,{"node_xform","focal","film_width_aperture","near","far"});auto cm=translation(*camera);need(cm[3][2]>0,"Camera must face the planar surface from positive Z");
 float focal=get<rdl::Float>(*camera,"focal"),film=get<rdl::Float>(*camera,"film_width_aperture");
 auto& cam=plan->camera;cam.nearClip=get<rdl::Float>(*camera,"near");cam.farClip=get<rdl::Float>(*camera,"far");
 need(surface::finite(focal)&&surface::finite(film)&&focal>0&&film>0&&surface::finite(cam.nearClip)&&surface::finite(cam.farClip)&&cam.nearClip>0&&cam.farClip>cam.nearClip,"Invalid lens");
 for(int i=0;i<4;++i){cam.rasterToCamera.m[i][i]=1;for(int j=0;j<4;++j)cam.cameraToRender.m[i][j]=float(cm[i][j]);}
 cam.rasterToCamera.m[0][0]=cam.rasterToCamera.m[1][1]=film/(focal*width);
 cam.rasterToCamera.m[3][0]=-film/(2*focal);cam.rasterToCamera.m[3][1]=-film/(2*focal)*height/width;
 std::map<std::string,unsigned> materialIds;std::set<const rdl::SceneObject*> allGeometry,setGeometry;const rdl::SceneObject* sky=nullptr;
 unsigned outputCount=0;bool beauty=false,alpha=false;
 std::map<const rdl::SceneObject*,texture::Binding> maps;std::shared_ptr<OIIO::TextureSystem> texSystem;
 for(auto& pair:sorted){auto& o=*pair.second;if(o.getSceneClass().getName()!="ImageMap")continue;
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

 for(auto& pair:sorted){auto& o=*pair.second;auto cls=o.getSceneClass().getName();
  if(cls=="SceneVariables"||&o==camera||maps.count(&o))continue;
  if(cls=="UsdPreviewSurface"){
   attributes(o,{"diffuseColor","useSpecularWorkflow","specularColor","emissiveColor"},{"diffuseColor","emissiveColor"});
   need(get<rdl::Int>(o,"useSpecularWorkflow")==1&&zero(get<rdl::Rgb>(o,"specularColor")),o.getName()+": Fresnel/specular/metal is not diffuse-only");
   need(get<rdl::Float>(o,"opacity")==1&&get<rdl::Float>(o,"clearcoat")==0,o.getName()+": opacity/coat unsupported");
   materialIds[o.getName()]=unsigned(plan->materials.size());plan->materials.push_back({color(get<rdl::Rgb>(o,"diffuseColor")),color(get<rdl::Rgb>(o,"emissiveColor"))});
   for(auto name:{"diffuseColor","emissiveColor"}){auto* binding=o.getBinding(*o.getSceneClass().getAttribute(name));if(binding){need(maps.count(binding),"Unsupported material map");(std::string(name)=="diffuseColor"?plan->diffuseMaps:plan->emissionMaps).emplace(materialIds.at(o.getName()),maps.at(binding));}}
  }else if(cls=="EnvLight"){
   need(!sky,"Multiple environment lights unsupported");sky=&o;attributes(o,{"color","intensity","exposure","sample_upper_hemisphere_only"});need(!get<rdl::Bool>(o,"sample_upper_hemisphere_only"),"Hemisphere environment unsupported");
   auto c=color(get<rdl::Rgb>(o,"color"));float intensity=get<rdl::Float>(o,"intensity"),exposure=get<rdl::Float>(o,"exposure");need(surface::finite(intensity)&&intensity>=0&&surface::finite(exposure)&&std::abs(exposure)<=32,"Invalid light intensity");plan->sky=surface::mul(c,intensity*std::pow(2.f,exposure));need(surface::finite(plan->sky),"Environment radiance overflow");
  }else if(cls=="RdlMeshGeometry")allGeometry.insert(&o);
  else if(cls=="GeometrySet"){
   attributes(o,{"geometries"});for(auto* geom:o.asA<rdl::GeometrySet>()->getGeometries())need(setGeometry.insert(geom).second,"Repeated geometry sets unsupported");
  }else if(cls=="Layer"){
   need(&o==&layer,"Additional layers unsupported");attributes(o,{"geometries","parts","surface_shaders","lightsets","displacements","volume_shaders","lightfiltersets","shadowsets","shadowreceiversets"});
  }else if(cls=="LightSet")attributes(o,{"lights"});
  else if(cls=="RenderOutput"){
   attributes(o,{"file_name","result","channel_format","compression"});int result=get<rdl::Int>(o,"result");need(result==0||result==1,"Unsupported AOV");need(get<rdl::Int>(o,"channel_format")==0,"Only float32 outputs supported");++outputCount;(result?alpha:beauty)=true;
  }else throw Unsupported(o.getName()+": unsupported class "+cls);
 }
 need(sky&&outputCount==2&&beauty&&alpha,"One environment and beauty/alpha outputs required");need(allGeometry==setGeometry&&!allGeometry.empty(),"Geometry sets must contain exactly the rendered meshes");
 need(size_t(layer.getAssignmentCount())==allGeometry.size(),"Only one whole-mesh assignment supported");
 for(auto& pair:sorted){auto& o=*pair.second;if(!allGeometry.count(&o))continue;
  auto* geom=o.asA<rdl::Geometry>();int id=layer.getAssignmentId(geom,"");need(id>=0,"Part-specific assignment unsupported");
  auto* mat=layer.lookupMaterial(id);auto* lights=layer.lookupLightSet(id);
  need(mat&&materialIds.count(mat->getName()),o.getName()+": missing diffuse material");need(lights,"Missing light set");
  const auto& ls=lights->getLights();need(ls.size()==1&&ls[0]==sky,"Per-object light linking unsupported");
  need(!layer.lookupDisplacement(id)&&!layer.lookupVolumeShader(id)&&!layer.lookupLightFilterSet(id)&&!layer.lookupShadowSet(id)&&!layer.lookupShadowReceiverSet(id),o.getName()+": displacement/volume/filter/shadow links unsupported");
  auto sig=signature(o,frame);std::shared_ptr<const MeshData> data;
  if(previous&&previous->domain==domain)for(auto& old:previous->meshes)if(old.data->name==o.getName()&&old.data->signature==sig){data=old.data;++plan->reusedMeshes;break;}
  // All geometry attribute/binding identities match before validation is reused.
  // Material/light assignments are checked above for EVERY epoch.
  if(!data){
  attributes(o,{"vertex_list_0","face_vertex_count","vertices_by_index","is_subd","node_xform","smooth_normal"});need(!get<rdl::Bool>(o,"is_subd"),o.getName()+": subdivision unsupported");
  if(spatial)need(!get<rdl::Bool>(o,"smooth_normal"),"Spatial smooth normals unsupported");
  auto transform=spatial?affine(o):translation(o);if(!spatial)need(transform[3][2]==0,o.getName()+": only coplanar geometry supported");
   auto m=std::make_shared<MeshData>();m->name=o.getName();m->signature=std::move(sig);
   const auto& v=o.get<rdl::Vec3fVector>("vertex_list");const auto& counts=o.get<rdl::IntVector>("face_vertex_count");const auto& indices=o.get<rdl::IntVector>("vertices_by_index");need(!v.empty()&&!counts.empty(),"Empty mesh unsupported");
   m->positions.reserve(v.size());m->triangles.reserve(counts.size());
   for(auto p:v){need(std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z)&&(spatial||p.z==0),"Invalid spatial/planar vertex");
    V3 point{float(p.x*transform[0][0]+p.y*transform[1][0]+p.z*transform[2][0]+transform[3][0]),float(p.x*transform[0][1]+p.y*transform[1][1]+p.z*transform[2][1]+transform[3][1]),float(p.x*transform[0][2]+p.y*transform[1][2]+p.z*transform[2][2]+transform[3][2])};
    need(surface::finite(point)&&(!spatial||(std::abs(point.x)<=10000&&std::abs(point.y)<=10000&&std::abs(point.z)<=10000)),"Transformed vertex bound");m->positions.push_back(point);}
   for(size_t i=0;i<counts.size();++i){need(counts[i]==3,"Non-triangle mesh");unsigned ids[3];for(int j=0;j<3;++j){auto k=indices[i*3+j];need(k>=0&&size_t(k)<v.size(),"Vertex index out of bounds");ids[j]=k;}
    auto a=m->positions[ids[0]],b=m->positions[ids[1]],c=m->positions[ids[2]];double area=(double(b.x)-a.x)*(double(c.y)-a.y)-(double(b.y)-a.y)*(double(c.x)-a.x);if(spatial){V3 n;need(surface::normalize(surface::cross(surface::add(b,surface::mul(a,-1)),surface::add(c,surface::mul(a,-1))),n),"Degenerate triangle");}
    else need(std::isfinite(area)&&area>0,"Degenerate/reversed triangle unsupported");m->triangles.push_back({ids[0],ids[1],ids[2]});}
   data=std::move(m);++plan->preparedMeshes;
  }
  plan->bytes+=data->positions.size()*sizeof(V3)+data->triangles.size()*sizeof(Tri);plan->meshes.push_back({data,materialIds.at(mat->getName())});
 }
 if(gpuTextures(domain)){uint64_t total=0;std::set<texture::File*> files;
  for(auto* set:{&plan->diffuseMaps,&plan->emissionMaps})for(auto& pair:*set){auto& file=*pair.second.file;if(!files.insert(&file).second)continue;total+=file.decodedBytes;need(total<=64ull<<20,"Aggregate host texture budget");if(!file.pyramid)file.pyramid=std::make_shared<texture::Pyramid>(file.name.string());}
 }
 need(plan->bytes<=limits.bytes,"Prepared geometry budget");return plan;
}
inline PlanView prepare(CanonicalSession& session,const CanonicalView& frame,PlanView previous={},Limits limits={},const fs::path& assetRoot={},Domain domain=Domain::Planar,bool allowAdaptive=false){
 return session.inspectPrepared(frame,[&](const rdl::SceneContext& context,CanonicalView exact){return prepare(context,exact,previous,limits,assetRoot,domain,allowAdaptive);});
}
}
