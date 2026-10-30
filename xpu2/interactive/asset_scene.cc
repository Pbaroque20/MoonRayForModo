// Private RDL asset inventory/rewrite. No RDLA parsing and no renderer changes.
#include "../rdl_scene_index.h"
#include <json/json.h>
#include <fstream>
#include <iostream>
#include <filesystem>
namespace rdl=scene_rdl2::rdl2;
static bool input(const rdl::SceneObject& obj,const rdl::Attribute& attr){
    return attr.isFilename() || (obj.isA<rdl::RenderOutput>() && attr.getName()=="resume_file_name");
}
static Json::Value inventory(const rdl::SceneContext& context){
    Json::Value root(Json::objectValue);root["references"]=Json::Value(Json::arrayValue);
    root["unclassified_strings"]=Json::Value(Json::arrayValue);
    for(auto i=context.beginSceneObject();i!=context.endSceneObject();++i){auto& obj=*i->second;
        for(auto a=obj.getSceneClass().beginAttributes();a!=obj.getSceneClass().endAttributes();++a){
            if((*a)->getType()!=rdl::TYPE_STRING && (*a)->getType()!=rdl::TYPE_STRING_VECTOR){
                if((*a)->isFilename())throw std::runtime_error("Unsupported filename attribute type");continue;
            }
            for(int step=0;step<((*a)->isBlurrable()?2:1);++step){
                auto time=step?rdl::TIMESTEP_END:rdl::TIMESTEP_BEGIN;
                rdl::StringVector values;
                if((*a)->getType()==rdl::TYPE_STRING)values.push_back(obj.get<rdl::String>((*a)->getName(),time));
                else values=obj.get<rdl::StringVector>((*a)->getName(),time);
                for(size_t j=0;j<values.size();++j){if(values[j].empty())continue;
                    Json::Value r(Json::objectValue);r["object"]=obj.getName();r["class"]=obj.getSceneClass().getName();
                    r["attribute"]=(*a)->getName();r["step"]=step;r["index"]=int(j);r["vector"]=(*a)->getType()==rdl::TYPE_STRING_VECTOR;r["value"]=values[j];
                    if(input(obj,**a))root["references"].append(r);
                    else root["unclassified_strings"].append(r);
                }
            }
        }
    }
    root["coverage"]="flagged filename attributes and RenderOutput.resume_file_name; DSO-internal dependencies not discovered";
    return root;
}
int main(int argc,char** argv){try{
    if(argc<4)throw std::runtime_error("mode scene dso [mapping output | texture output]");
    rdl::SceneContext context;context.setProxyModeEnabled(true);context.setDsoPath(argv[3]);
    rdl::readSceneFromFile(argv[2],context);std::string mode=argv[1];
    if(mode=="rewrite"){
        if(argc!=6 || std::filesystem::exists(argv[5]))throw std::runtime_error("Fresh output required");
        Json::Value mapping;std::ifstream f(argv[4]);f>>mapping;
        auto expected=inventory(context)["references"];
        if(mapping.size()!=expected.size())throw std::runtime_error("Incomplete asset mapping");
        // Positional list generated from this exact immutable scene; verify every
        // selector and old path before any write, including vector and time index.
        for(unsigned int j=0;j<expected.size();++j){
            for(auto key:{"object","class","attribute","step","index","vector","value"})
                if(mapping[j][key]!=expected[j][key])throw std::runtime_error("Asset mapping mismatch");
            if(!mapping[j]["replacement"].isString() || mapping[j]["replacement"].asString().empty())throw std::runtime_error("Missing replacement");
        }
        for(const auto& r:mapping){auto* obj=context.getSceneObject(r["object"].asString());
            auto time=r["step"].asInt()?rdl::TIMESTEP_END:rdl::TIMESTEP_BEGIN;
            rdl::SceneObject::UpdateGuard guard(obj);auto name=r["attribute"].asString();
            if(r["vector"].asBool()){auto v=obj->get<rdl::StringVector>(name,time);v.at(r["index"].asUInt())=r["replacement"].asString();obj->set(name,v,time);}
            else obj->set<rdl::String>(name,r["replacement"].asString(),time);
        }
        rdl::BinaryWriter(context).toFile(argv[5]);
    }else if(mode=="fixture"){
        if(argc!=6 || std::filesystem::exists(argv[5]))throw std::runtime_error("Fresh fixture output required");
        auto* map=context.createSceneObject("ImageMap","/asset-test/image");
        {rdl::SceneObject::UpdateGuard g(map);map->set<rdl::String>("texture",argv[4]);}
        auto* material=context.getSceneObject("/modo/material/1");
        {rdl::SceneObject::UpdateGuard g(material);material->setBinding("diffuseColor",map);}
        rdl::BinaryWriter(context).toFile(argv[5]);
    }else if(mode!="inspect")throw std::runtime_error("Unknown mode");
    Json::StreamWriterBuilder b;b["indentation"]="";std::cout<<Json::writeString(b,inventory(context))<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
