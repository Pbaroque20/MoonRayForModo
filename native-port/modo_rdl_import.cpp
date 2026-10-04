#include <scene_rdl2/scene/rdl2/rdl2.h>
#include <json/json.h>
#include <iostream>
using namespace scene_rdl2::rdl2;
Json::Value value(bool v){return v;}
Json::Value value(int v){return v;}
Json::Value value(int64_t v){return Json::Int64(v);}
Json::Value value(float v){return v;}
Json::Value value(double v){return v;}
Json::Value value(const std::string& v){return v;}
Json::Value value(SceneObject* v){return v?Json::Value(v->getName()):Json::Value();}
template<class T> Json::Value components(const T& v,int n){Json::Value a(Json::arrayValue);for(int i=0;i<n;++i)a.append(v[i]);return a;}
Json::Value value(const Rgb& v){return components(v,3);} Json::Value value(const Rgba& v){return components(v,4);}
#define VECTOR(T,N) Json::Value value(const T& v){return components(v,N);}
VECTOR(Vec2f,2) VECTOR(Vec2d,2) VECTOR(Vec3f,3) VECTOR(Vec3d,3) VECTOR(Vec4f,4) VECTOR(Vec4d,4)
#define MATRIX(T,N) Json::Value value(const T& v){Json::Value a(Json::arrayValue);for(int i=0;i<N;++i)for(int j=0;j<N;++j)a.append(v[i][j]);return a;}
MATRIX(Mat4f,4) MATRIX(Mat4d,4) MATRIX(Mat3f,3) MATRIX(Mat3d,3)
template<class T> Json::Value collection(const T& v){Json::Value a(Json::arrayValue);for(const auto& x:v)a.append(value(x));return a;}
int main(int argc,char** argv){
 if(argc!=3)return 2;
 try{
  SceneContext context;context.setProxyModeEnabled(true);context.setDsoPath(argv[2]);readSceneFromFile(argv[1],context);
  Json::Value root(Json::objectValue);root["version"]=1;root["objects"]=Json::Value(Json::arrayValue);
  for(auto it=context.beginSceneObject();it!=context.endSceneObject();++it){
   const auto& obj=*it->second;const auto& cls=obj.getSceneClass();Json::Value record(Json::objectValue);
   record["name"]=obj.getName();record["type"]=cls.getName();
   for(auto a=cls.beginAttributes();a!=cls.endAttributes();++a){
    const auto& attr=**a;const auto name=attr.getName();Json::Value v;
    switch(attr.getType()){
#define SCALAR(K,T) case K:v=value(obj.get<T>(name));break;
#define ARRAY(K,T) case K:v=collection(obj.get<T>(name));break;
     SCALAR(TYPE_BOOL,Bool) SCALAR(TYPE_INT,Int) SCALAR(TYPE_LONG,Long) SCALAR(TYPE_FLOAT,Float) SCALAR(TYPE_DOUBLE,Double) SCALAR(TYPE_STRING,String)
     SCALAR(TYPE_RGB,Rgb) SCALAR(TYPE_RGBA,Rgba) SCALAR(TYPE_VEC2F,Vec2f) SCALAR(TYPE_VEC2D,Vec2d) SCALAR(TYPE_VEC3F,Vec3f) SCALAR(TYPE_VEC3D,Vec3d) SCALAR(TYPE_VEC4F,Vec4f) SCALAR(TYPE_VEC4D,Vec4d)
     SCALAR(TYPE_MAT4F,Mat4f) SCALAR(TYPE_MAT4D,Mat4d) SCALAR(TYPE_MAT3F,Mat3f) SCALAR(TYPE_MAT3D,Mat3d) SCALAR(TYPE_SCENE_OBJECT,SceneObject*)
     ARRAY(TYPE_INT_VECTOR,IntVector) ARRAY(TYPE_FLOAT_VECTOR,FloatVector) ARRAY(TYPE_DOUBLE_VECTOR,DoubleVector) ARRAY(TYPE_STRING_VECTOR,StringVector)
     ARRAY(TYPE_RGB_VECTOR,RgbVector) ARRAY(TYPE_VEC2F_VECTOR,Vec2fVector) ARRAY(TYPE_VEC3F_VECTOR,Vec3fVector) ARRAY(TYPE_MAT4F_VECTOR,Mat4fVector) ARRAY(TYPE_MAT4D_VECTOR,Mat4dVector)
     ARRAY(TYPE_SCENE_OBJECT_VECTOR,SceneObjectVector) ARRAY(TYPE_SCENE_OBJECT_INDEXABLE,SceneObjectIndexable)
     default:record["unsupported_attributes"].append(name);continue;
    }
    record["attributes"][name]=v;
    if(attr.isFilename())record["files"].append(name);
    if(attr.isBindable()){const auto* binding=obj.getBinding(attr);if(binding)record["bindings"][name]=binding->getName();}
    if(attr.isBlurrable())record["motion_attributes"].append(name);
   }
   root["objects"].append(record);
  }
  Json::StreamWriterBuilder writer;writer["indentation"]="";
  std::cout<<"\n@@MODO_RDL_JSON\n"<<Json::writeString(writer,root)<<std::endl;return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
