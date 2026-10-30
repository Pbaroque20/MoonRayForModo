// Native RDL attributes -> owned indexed bytes -> a separate native SceneContext.
// Capture/apply only while the native scene is quiescent on its coordinator.
#pragma once
#include <scene_rdl2/scene/rdl2/rdl2.h>
#include "indexed_scene.h"
#include <cstring>
#include <type_traits>

namespace xpu2::rdlindex {
namespace rdl = scene_rdl2::rdl2;
using namespace indexed;
inline std::string objectId(const std::string& name) { return "o:"+std::to_string(name.size())+":"+name; }
inline std::string attributeId(const std::string& object, const std::string& name) {
    return "a:"+std::to_string(object.size())+":"+object+std::to_string(name.size())+":"+name;
}
struct Writer {
    Bytes bytes;
    std::set<std::string> dependencies;
    void append(const void* data,size_t size) {
        if(size>bytes.max_size()-bytes.size())throw std::length_error("RDL resource too large");
        const auto* p=static_cast<const uint8_t*>(data);bytes.insert(bytes.end(),p,p+size);
    }
};
struct Reader {
    const Bytes& bytes;size_t offset=0;
    rdl::SceneContext* context=nullptr;
    void take(void* data,size_t size) {
        if(size>bytes.size()-offset)throw std::invalid_argument("Truncated indexed RDL attribute");
        std::memcpy(data,bytes.data()+offset,size);offset+=size;
    }
    size_t remaining() const{return bytes.size()-offset;}
    void finish() const {if(remaining())throw std::invalid_argument("Trailing indexed RDL bytes");}
};
// Internal same-build, little-endian ABI. No struct padding or pointers encoded.
// A durable cross-version archive must continue to use MoonRay's RDLB format.
template<class T> struct Codec {
    static_assert(std::is_arithmetic<T>::value,"Missing RDL value codec");
    static void put(Writer& w,const T& v){w.append(&v,sizeof(v));}
    static T get(Reader& r){T v;r.take(&v,sizeof(v));return v;}
};
template<> struct Codec<bool> {
    static void put(Writer& w,bool v){Codec<uint8_t>::put(w,v?1:0);}
    static bool get(Reader& r){auto v=Codec<uint8_t>::get(r);if(v>1)throw std::invalid_argument("Invalid bool");return v!=0;}
};
template<> struct Codec<std::string> {
    static void put(Writer& w,const std::string& v){Codec<uint64_t>::put(w,v.size());w.append(v.data(),v.size());}
    static std::string get(Reader& r){auto n=Codec<uint64_t>::get(r);if(n>r.remaining())throw std::invalid_argument("Invalid string length");std::string v(size_t(n),'\0');r.take(v.data(),v.size());return v;}
};
template<> struct Codec<rdl::SceneObject*> {
    static void put(Writer& w,rdl::SceneObject* v){
        Codec<bool>::put(w,v!=nullptr);
        if(v){Codec<std::string>::put(w,v->getName());w.dependencies.insert(objectId(v->getName()));}
    }
    static rdl::SceneObject* get(Reader& r){
        if(!Codec<bool>::get(r))return nullptr;
        auto name=Codec<std::string>::get(r);
        if(!r.context)throw std::invalid_argument("Missing native reference context");
        return r.context->getSceneObject(name);
    }
};
#define XPU2_VECTOR(T,N) template<> struct Codec<rdl::T> { \
 static void put(Writer& w,const rdl::T& v){for(int i=0;i<N;++i)Codec<std::decay_t<decltype(v[i])>>::put(w,v[i]);} \
 static rdl::T get(Reader& r){rdl::T v;for(int i=0;i<N;++i)v[i]=Codec<std::decay_t<decltype(v[i])>>::get(r);return v;} };
XPU2_VECTOR(Rgb,3) XPU2_VECTOR(Rgba,4)
XPU2_VECTOR(Vec2f,2) XPU2_VECTOR(Vec2d,2) XPU2_VECTOR(Vec3f,3) XPU2_VECTOR(Vec3d,3) XPU2_VECTOR(Vec4f,4) XPU2_VECTOR(Vec4d,4)
#undef XPU2_VECTOR
#define XPU2_MATRIX(T,N) template<> struct Codec<rdl::T> { \
 static void put(Writer& w,const rdl::T& v){for(int i=0;i<N;++i)for(int j=0;j<N;++j)Codec<std::decay_t<decltype(v[i][j])>>::put(w,v[i][j]);} \
 static rdl::T get(Reader& r){rdl::T v;for(int i=0;i<N;++i)for(int j=0;j<N;++j)v[i][j]=Codec<std::decay_t<decltype(v[i][j])>>::get(r);return v;} };
XPU2_MATRIX(Mat3f,3) XPU2_MATRIX(Mat3d,3) XPU2_MATRIX(Mat4f,4) XPU2_MATRIX(Mat4d,4)
#undef XPU2_MATRIX
// Whether a vector's values lie in memory exactly as their codec writes them one by one: whole numbers and floats
// (not bool), and RDL's vectors and colours of N of them with no padding. Such a vector is written and read as one
// block, the same bytes (a heavy scene's gigabyte of geometry went value by value: 12 s of 32 s preparing a car).
template<class T,class=void> struct Packed : std::integral_constant<bool,std::is_arithmetic<T>::value&&!std::is_same<T,bool>::value> {};
template<class T> struct PackedOf : std::false_type {};
#define XPU2_PACKED(T,C,N) template<> struct PackedOf<rdl::T> : std::integral_constant<bool,sizeof(rdl::T)==N*sizeof(C)&&  std::is_trivially_copyable<rdl::T>::value> {};
XPU2_PACKED(Rgb,float,3) XPU2_PACKED(Rgba,float,4)
XPU2_PACKED(Vec2f,float,2) XPU2_PACKED(Vec2d,double,2) XPU2_PACKED(Vec3f,float,3) XPU2_PACKED(Vec3d,double,3) XPU2_PACKED(Vec4f,float,4) XPU2_PACKED(Vec4d,double,4)
#undef XPU2_PACKED
template<class Container> struct SequenceCodec {
    using T=typename Container::value_type;
    static constexpr bool block=(Packed<T>::value||PackedOf<T>::value)&&
        std::is_same<Container,std::vector<T,typename Container::allocator_type>>::value;
    static void put(Writer& w,const Container& values){
        Codec<uint64_t>::put(w,values.size());
        if constexpr(block){w.append(values.data(),values.size()*sizeof(T));}
        else for(const auto& v:values)Codec<T>::put(w,v);
    }
    static Container get(Reader& r){
        auto count=Codec<uint64_t>::get(r);
        if(count>r.remaining())throw std::invalid_argument("Invalid indexed vector length");
        Container values;
        if constexpr(block){
            if(count>r.remaining()/sizeof(T))throw std::invalid_argument("Truncated indexed RDL attribute");
            values.resize(size_t(count));r.take(values.data(),size_t(count)*sizeof(T));
        }else for(uint64_t i=0;i<count;++i)values.push_back(Codec<T>::get(r));
        return values;
    }
};
template<class T,class A> struct Codec<std::vector<T,A>> : SequenceCodec<std::vector<T,A>> {};
template<> struct Codec<rdl::BoolVector> : SequenceCodec<rdl::BoolVector> {};
template<> struct Codec<rdl::SceneObjectIndexable> : SequenceCodec<rdl::SceneObjectIndexable> {};
#define XPU2_ATTRIBUTE_TYPES(M) \
 M(TYPE_BOOL,Bool) M(TYPE_INT,Int) M(TYPE_LONG,Long) M(TYPE_FLOAT,Float) M(TYPE_DOUBLE,Double) M(TYPE_STRING,String) \
 M(TYPE_RGB,Rgb) M(TYPE_RGBA,Rgba) M(TYPE_VEC2F,Vec2f) M(TYPE_VEC2D,Vec2d) M(TYPE_VEC3F,Vec3f) M(TYPE_VEC3D,Vec3d) M(TYPE_VEC4F,Vec4f) M(TYPE_VEC4D,Vec4d) \
 M(TYPE_MAT3F,Mat3f) M(TYPE_MAT3D,Mat3d) M(TYPE_MAT4F,Mat4f) M(TYPE_MAT4D,Mat4d) M(TYPE_SCENE_OBJECT,SceneObject*) \
 M(TYPE_BOOL_VECTOR,BoolVector) M(TYPE_INT_VECTOR,IntVector) M(TYPE_LONG_VECTOR,LongVector) M(TYPE_FLOAT_VECTOR,FloatVector) M(TYPE_DOUBLE_VECTOR,DoubleVector) M(TYPE_STRING_VECTOR,StringVector) \
 M(TYPE_RGB_VECTOR,RgbVector) M(TYPE_RGBA_VECTOR,RgbaVector) M(TYPE_VEC2F_VECTOR,Vec2fVector) M(TYPE_VEC2D_VECTOR,Vec2dVector) M(TYPE_VEC3F_VECTOR,Vec3fVector) M(TYPE_VEC3D_VECTOR,Vec3dVector) M(TYPE_VEC4F_VECTOR,Vec4fVector) M(TYPE_VEC4D_VECTOR,Vec4dVector) \
 M(TYPE_MAT3F_VECTOR,Mat3fVector) M(TYPE_MAT3D_VECTOR,Mat3dVector) M(TYPE_MAT4F_VECTOR,Mat4fVector) M(TYPE_MAT4D_VECTOR,Mat4dVector) M(TYPE_SCENE_OBJECT_VECTOR,SceneObjectVector) M(TYPE_SCENE_OBJECT_INDEXABLE,SceneObjectIndexable)
inline Writer encodeAttribute(const rdl::SceneObject& obj,const rdl::Attribute& attr) {
    Writer w;Codec<uint32_t>::put(w,0x31494158); // XAI1
    Codec<std::string>::put(w,obj.getName());Codec<std::string>::put(w,attr.getName());
    Codec<uint32_t>::put(w,uint32_t(attr.getType()));Codec<bool>::put(w,attr.isBlurrable());Codec<bool>::put(w,attr.isBindable());
    if(attr.isBindable())Codec<rdl::SceneObject*>::put(w,obj.getBinding(attr));
    for(int step=0;step<(attr.isBlurrable()?2:1);++step) {
        auto time=step?rdl::TIMESTEP_END:rdl::TIMESTEP_BEGIN;
        switch(attr.getType()) {
#define ENCODE(K,T) case rdl::K:Codec<rdl::T>::put(w,obj.get<rdl::T>(attr.getName(),time));break;
        XPU2_ATTRIBUTE_TYPES(ENCODE)
#undef ENCODE
        default:throw std::invalid_argument("Unsupported RDL attribute type");
        }
    }
    return w;
}
inline void applyAttribute(const Bytes& bytes,rdl::SceneContext& context,bool validateOnly=false) {
    Reader r{bytes,0,&context};if(Codec<uint32_t>::get(r)!=0x31494158)throw std::invalid_argument("Unknown indexed RDL encoding");
    auto object=Codec<std::string>::get(r),name=Codec<std::string>::get(r);
    auto* obj=context.getSceneObject(object);const auto* attr=obj->getSceneClass().getAttribute(name);
    auto type=Codec<uint32_t>::get(r);auto blur=Codec<bool>::get(r),bind=Codec<bool>::get(r);
    if(type!=uint32_t(attr->getType())||blur!=attr->isBlurrable()||bind!=attr->isBindable())throw std::invalid_argument("RDL schema mismatch");
    rdl::SceneObject* binding=bind?Codec<rdl::SceneObject*>::get(r):nullptr;
    // Caller prevalidates every payload; unexpected native mutation failure must
    // discard this replica. Never continue rendering a partially applied scene.
    std::unique_ptr<rdl::SceneObject::UpdateGuard> guard;
    if(!validateOnly)guard=std::make_unique<rdl::SceneObject::UpdateGuard>(obj);
    if(bind&&!validateOnly)obj->setBinding(*attr,binding);
    for(int step=0;step<(blur?2:1);++step) {
        auto time=step?rdl::TIMESTEP_END:rdl::TIMESTEP_BEGIN;
        switch(attr->getType()) {
#define DECODE(K,T) case rdl::K:{auto value=Codec<rdl::T>::get(r);if(!validateOnly)obj->set(name,value,time);break;}
        XPU2_ATTRIBUTE_TYPES(DECODE)
#undef DECODE
        default:throw std::invalid_argument("Unsupported indexed attribute");
        }
    }
    r.finish();
}
#undef XPU2_ATTRIBUTE_TYPES
inline Kind kind(const rdl::SceneObject& object) {
    if(object.isA<rdl::Geometry>())return Kind::Geometry;
    if(object.isA<rdl::Camera>())return Kind::Camera;
    if(object.isA<rdl::VolumeShader>())return Kind::Volume;
    if(object.isA<rdl::Material>())return Kind::Material;
    if(object.isA<rdl::EnvMap>())return Kind::Environment;
    if(object.isA<rdl::Light>())return Kind::Light;
    if(object.isA<rdl::Map>()||object.isA<rdl::NormalMap>())return Kind::Texture;
    return Kind::Auxiliary; // Layers, sets, outputs, filters and scene variables.
}
inline Field field(const rdl::Attribute& attr) {
    const auto& name=attr.getName();
    if(name=="node_xform")return Field::Transform;
    if(name=="vertex_list"||name=="vertex_list_0"||name=="vertex_list_1")return Field::Positions;
    if(name=="vertices_by_index"||name=="face_vertex_count")return Field::Topology;
    return Field::Parameters;
}
// Native binding-update bits can survive commitAllChanges(). Compare the small
// owned binding header instead of re-encoding attributes with stale update bits.
inline bool sameBinding(const rdl::SceneObject& object,const rdl::Attribute& attr,const Entity& record) {
    if(!attr.isBindable())return true;
    Reader r{record.buffers.begin()->second->source};
    if(Codec<uint32_t>::get(r)!=0x31494158)throw std::invalid_argument("Unknown indexed binding header");
    Codec<std::string>::get(r);Codec<std::string>::get(r);Codec<uint32_t>::get(r);Codec<bool>::get(r);
    if(!Codec<bool>::get(r))return false;
    bool present=Codec<bool>::get(r);auto* actual=object.getBinding(attr);
    if(present!=(actual!=nullptr))return false;
    return !present||Codec<std::string>::get(r)==actual->getName();
}
struct Capture {
    std::vector<Edit> edits;size_t objects=0,attributes=0,bytes=0;
};
inline Capture capture(const rdl::SceneContext& context,const View& base,bool full=false) {
    Capture result;
    for(auto it=context.beginSceneObject();it!=context.endSceneObject();++it) {
        const auto& obj=*it->second;auto id=objectId(obj.getName());
        bool created=!base->entities.count(id);++result.objects;
        if(!created&&!full&&!obj.isDirty())continue;
        std::set<std::string> attributes;
        for(auto a=obj.getSceneClass().beginAttributes();a!=obj.getSceneClass().endAttributes();++a) {
            const auto& attr=**a;auto aid=attributeId(obj.getName(),attr.getName());attributes.insert(aid);
            if(!created&&!full&&base->entities.count(aid)&&!obj.isAttributeSet(&attr)&&
               sameBinding(obj,attr,*base->entities.at(aid)))continue;
            auto w=encodeAttribute(obj,attr);++result.attributes;result.bytes+=w.bytes.size();
            result.edits.push_back({aid,Kind::Attribute,{{field(attr),std::move(w.bytes)}},std::move(w.dependencies),{}});
        }
        Writer metadata;Codec<std::string>::put(metadata,obj.getName());Codec<std::string>::put(metadata,obj.getSceneClass().getName());
        result.edits.push_back({id,kind(obj),{{Field::Parameters,std::move(metadata.bytes)}},std::move(attributes),{}});
    }
    return result;
}
inline void apply(const View& scene,rdl::SceneContext& target,bool full=false) {
    if(!full&&!scene->changes.removed.empty())throw std::invalid_argument("Native removals require a fresh replica");
    const auto& ids=scene->changes.direct;
    std::vector<const Entity*> objects, attributes;
    auto collect = [&](const std::shared_ptr<const Entity>& entity) {
        (entity->kind==Kind::Attribute ? attributes : objects).push_back(entity.get());
    };
    if(full)for(const auto& pair:scene->entities)collect(pair.second);
    else for(const auto& id:ids)collect(scene->entities.at(id));
    // Construct all objects before resolving attribute references/cycles.
    for(const auto* entity:objects) {
        Reader r{entity->buffers.at(Field::Parameters)->ready()};
        auto name=Codec<std::string>::get(r),cls=Codec<std::string>::get(r);r.finish();
        target.createSceneObject(cls,name);
    }
    // Validate all changed values before any attribute is applied.
    for(bool validation:{true,false})for(const auto* entity:attributes) {
        if(entity->buffers.size()!=1)throw std::invalid_argument("Invalid attribute record");
        applyAttribute(entity->buffers.begin()->second->ready(),target,validation);
    }
}
} // namespace xpu2::rdlindex
