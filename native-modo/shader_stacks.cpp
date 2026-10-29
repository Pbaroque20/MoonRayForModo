// Which of a surface's Shader Tree layers apply to it, for every surface of a reading at once (evaluated.py,
// assign_materials). Modo's render cache gives each surface the layers of its host stack; a layer applies where every
// group above it, up to the render item, is enabled and rendered, and every mask above it names this surface's
// material and part (when it names one) and, when it is limited to items, one of them is this surface's item (its
// prototypes' too, with Apply to Instances), or a group holding it. The same rule as Python's, a channel read at a
// time: from Python it was 30,000 channel reads and 1.6 s for a car's 334 surfaces at every reading.
// Read-only. Runs on Modo's main thread, where Python called it.
#include <lx_action.hpp>
#include <lx_value.hpp>
#include <lx_item.hpp>
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Types {
    LXtItemType mask=0,polyRender=0,mesh=0,meshInst=0,replicator=0,groupLocator=0;
    explicit Types(CLxUser_SceneService& service) {
        auto lookup=[&](const char* name){LXtItemType type=0;service.ItemTypeLookup(name,&type);return type;};
        mask=lookup("mask");polyRender=lookup("polyRender");mesh=lookup("mesh");meshInst=lookup("meshInst");
        replicator=lookup("replicator");groupLocator=lookup("groupLocator");
    }
};

// A channel's value as Python's truth would have it (host.channel: the default where the item has no such channel).
struct Reader {
    CLxUser_ChannelRead chan;
    std::map<std::pair<std::string,std::string>,std::string> texts;
    bool truth(CLxUser_Item& item,const char* name,bool missing) {
        unsigned index=0;
        if(LXx_FAIL(item.ChannelLookup(name,&index))) return missing;
        unsigned type=0;item.ChannelType(index,&type);
        if(type==LXi_TYPE_FLOAT) return chan.FValue(item,index)!=0.0;
        if(type==LXi_TYPE_STRING){std::string value;chan.GetString(item,index,value);return !value.empty();}
        return chan.IValue(item,index)!=0;
    }
    // A string channel, or an integer one given as Python's mask_types.tag_kind reads it.
    std::string text(CLxUser_Item& item,const std::string& ident,const char* name) {
        auto key=std::make_pair(ident,std::string(name));
        auto found=texts.find(key);if(found!=texts.end()) return found->second;
        std::string value;unsigned index=0;
        if(LXx_OK(item.ChannelLookup(name,&index))) {
            unsigned type=0;item.ChannelType(index,&type);
            if(type==LXi_TYPE_STRING) chan.GetString(item,index,value);
            else if(type==LXi_TYPE_INTEGER) value="#"+std::to_string(chan.IValue(item,index));
        }
        return texts[key]=value;
    }
};

std::string lower(std::string value) {
    std::transform(value.begin(),value.end(),value.begin(),[](unsigned char c){return char(std::tolower(c));});
    return value;
}

// mask_types.tag_kind: 'material', 'part', or what else it is.
std::string tagKind(const std::string& value) {
    if(value.empty() || value=="#0") return "";
    if(value[0]=='#') {
        const long long code=std::stoll(value.substr(1));
        if(code>0 && code<(1LL<<32)) {
            const uint32_t v=uint32_t(code);
            for(int big=1;big>=0;--big) {
                std::string four;
                for(int i=0;i<4;++i) four+=char(big?(v>>(24-8*i))&0xff:(v>>(8*i))&0xff);
                four=lower(four);
                if(four=="matr") return "material";
                if(four=="part") return "part";
            }
        }
        return value.substr(1);
    }
    std::string key=value;
    key.erase(0,key.find_first_not_of(" \t\r\n"));key.erase(key.find_last_not_of(" \t\r\n")+1);
    key=lower(key);
    if(key=="matr" || key=="material") return "material";
    if(key=="part") return "part";
    return key;
}

std::string ident(CLxUser_Item& item) {const char* id=nullptr;item.Ident(&id);return id?id:"";}

struct Surface {std::string item,material,part;std::vector<std::string> layers;};

class Stacks {
public:
    Stacks(CLxUser_Scene& scene,double time):scene(scene),types(service) {
        if(!scene.GetChannels(reader.chan,time)) throw std::runtime_error("Scene channels");
        scene.GetGraph("shadeLoc",shadeLoc);scene.GetGraph("source",source);
    }
    std::vector<std::string> applying(const Surface& surface) {
        // The surface's item and the prototypes its instances come from (an instance of an instance among them).
        std::set<std::string> sources{surface.item};
        CLxUser_Item at;
        if(scene.GetItemByIdent(surface.item.c_str(),at)) {
            while(at.Type()==types.meshInst && source.test()) {
                if(source.Forward(at)!=1) break;
                CLxUser_Item next;
                if(!source.Forward(at,0,next)) break;
                const std::string id=ident(next);
                if(sources.count(id)) break;
                sources.insert(id);at=next;
            }
        }
        std::vector<std::string> kept;
        for(const std::string& layer:surface.layers) {
            CLxUser_Item item;
            if(!scene.GetItemByIdent(layer.c_str(),item)) continue;
            if(matches(item,surface,sources)) kept.push_back(layer);
        }
        return kept;
    }

private:
    bool contains(CLxUser_Item& target,const std::set<std::string>& applicable) {
        if(applicable.count(ident(target))) return true;
        if(target.Type()!=types.groupLocator) return false;
        unsigned count=0;target.SubCount(&count);
        for(unsigned i=0;i<count;++i) {
            CLxUser_Item child;
            if(target.GetSubItem(i,child) && contains(child,applicable)) return true;
        }
        return false;
    }
    bool matches(CLxUser_Item& item,const Surface& surface,const std::set<std::string>& sources) {
        CLxUser_Item parent;
        bool has=item.Type()==types.mask?parent.copy(item):item.GetParent(parent);
        while(has && parent.Type()!=types.polyRender) {
            if(!reader.truth(parent,"enable",true) || !reader.truth(parent,"render",true)) return false;
            if(parent.Type()==types.mask) {
                const std::string id=ident(parent);
                const std::string kind=tagKind(reader.text(parent,id,"ptyp")),value=reader.text(parent,id,"ptag");
                if(kind=="material" && !value.empty() && value!=surface.material) return false;
                if(kind=="part" && !value.empty() && value!=surface.part) return false;
                std::vector<CLxUser_Item> targets;
                if(shadeLoc.test()) {
                    const unsigned count=shadeLoc.Forward(parent);
                    for(unsigned i=0;i<count;++i) {
                        CLxUser_Item target;
                        if(!shadeLoc.Forward(parent,i,target)) continue;
                        const LXtItemType type=target.Type();
                        if(type==types.mesh || type==types.meshInst || type==types.replicator || type==types.groupLocator) targets.push_back(target);
                    }
                }
                const std::set<std::string> applicable=reader.truth(parent,"instApply",false)?sources:std::set<std::string>{surface.item};
                if(!targets.empty()) {
                    bool any=false;
                    for(auto& target:targets) if(contains(target,applicable)){any=true;break;}
                    if(!any) return false;
                }
            }
            CLxUser_Item up;
            has=parent.GetParent(up);
            if(has) parent.copy(up);
        }
        return true;
    }
    CLxUser_Scene& scene;
    CLxUser_SceneService service;
    Types types;
    Reader reader;
    CLxUser_ItemGraph shadeLoc,source;
};

std::vector<std::string> split(const std::string& text,char by) {
    std::vector<std::string> parts;std::string part;std::istringstream in(text);
    while(std::getline(in,part,by)) parts.push_back(part);
    return parts;
}
}

// request: one surface a line, "item\tmaterial\tpart\tlayer;layer;...". The answer: the layers that apply, one surface a
// line in the same order, or a line beginning "!" with what went wrong.
extern "C" __declspec(dllexport) const char* MR_shader_stacks(void* object,double time,const char* request) {
    static thread_local std::string result;
    try {
        CLxUser_Scene scene;
        if(!scene.set(reinterpret_cast<ILxUnknownID>(object))) throw std::runtime_error("No scene");
        Stacks stacks(scene,time);
        std::ostringstream out;
        for(const std::string& line:split(request?request:"",'\n')) {
            const auto fields=split(line,'\t');
            Surface surface;
            surface.item=fields.size()>0?fields[0]:"";surface.material=fields.size()>1?fields[1]:"";surface.part=fields.size()>2?fields[2]:"";
            if(fields.size()>3) for(const auto& layer:split(fields[3],';')) if(!layer.empty()) surface.layers.push_back(layer);
            const auto kept=stacks.applying(surface);
            for(size_t i=0;i<kept.size();++i) out<<(i?";":"")<<kept[i];
            out<<'\n';
        }
        result=out.str();
    } catch(const std::exception& error) {
        result=std::string("!")+error.what();
    }
    return result.c_str();
}
