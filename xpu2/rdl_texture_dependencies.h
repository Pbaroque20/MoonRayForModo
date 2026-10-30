// Native metadata discovery; resolver supplies verified file/content identities.
#pragma once
#include "rdl_scene_index.h"
#include "texture_dependencies.h"
namespace xpu2::rdlindex {
struct TextureInputs {texture::SourceCatalog sources;texture::Assignments assignments;};
using TextureResolver=std::function<texture::TextureSource(const std::string&,const std::string&,const std::string&)>;
inline TextureInputs textureInputs(const rdl::SceneContext& context,const TextureResolver& resolve){
    if(!resolve)throw std::invalid_argument("Missing texture resolver");TextureInputs out;
    for(auto it=context.beginSceneObject();it!=context.endSceneObject();++it){const auto& object=*it->second;
        if(object.isA<rdl::Map>()||object.isA<rdl::NormalMap>()){
            for(auto a=object.getSceneClass().beginAttributes();a!=object.getSceneClass().endAttributes();++a){const auto& attribute=**a;
                if(!attribute.isFilename())continue;auto slot=attributeId(object.getName(),attribute.getName());
                texture::TextureSource source;
                if(attribute.getType()==rdl::TYPE_STRING&&!attribute.isBlurrable()){auto path=object.get<rdl::String>(attribute.getName());
                    if(!path.empty()){source=resolve(object.getSceneClass().getName(),attribute.getName(),path);
                        if(source.resources.empty()&&source.unresolved.empty())source.unresolved.insert(path);}
                }else source.unresolved.insert(object.getName()+":"+attribute.getName()+" (unsupported filename type or motion samples)");
                out.sources.emplace(slot,std::move(source));
            }
        }
        if(object.isA<rdl::Layer>()){
            auto& layer=static_cast<const rdl::Layer&>(object);
            for(int32_t n=0;n<layer.getAssignmentCount();++n){auto pair=layer.lookupGeomAndPart(n);auto material=layer.lookupMaterial(n);
                if(pair.first&&material)out.assignments.emplace(texture::Assignment{objectId(layer.getName()),objectId(pair.first->getName()),pair.second},objectId(material->getName()));
            }
        }
    }
    return out;
}
} // namespace xpu2::rdlindex
