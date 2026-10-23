// Private bounded shared stage transaction; no concurrent queue publication here.
#pragma once
#include "sample_stream.h"
namespace xpu2 { namespace interactive { namespace path {
using sample::U32;using sample::U64;
struct Epoch { U64 session,scene,camera,settings; };
X2_HD inline bool equal(Epoch a,Epoch b) {
    return a.session==b.session && a.scene==b.scene && a.camera==b.camera && a.settings==b.settings;
}
struct Ray { float origin[3],direction[3],nearT,farT,time; };
struct Medium { U64 material; float ior; };
struct Record {
    Epoch epoch; sample::Identity id; U64 revision=0;
    sample::Cursor cursor; Ray ray{}; float throughput[3]={1,1,1};
    Medium media[8]{}; U32 mediumCount=0; U64 lpe[4]{};
};
struct Contribution { U32 aov; double rgba[4]; };
struct Child { sample::Identity id; Ray ray; float weight[3]; U32 kind; };
struct Effects { Contribution values[16]{}; Child children[15]{}; U32 valueCount=0,childCount=0; };
enum class Failure:U32 { None,TextureMiss,Capacity,Dimension,Invalid };
class Stage {
    Record base_,next_; Effects effects_{}; Failure failure_=Failure::None; bool consumed_=false;
public:
    X2_HD explicit Stage(const Record& input):base_(input),next_(input){}
    X2_HD Record& draft(){return next_;}
    X2_HD const Effects& effects() const{return effects_;}
    X2_HD Failure failure() const{return failure_;}
    X2_HD void miss(){failure_=Failure::TextureMiss;}
    X2_HD bool random(float& v){
        if(failure_!=Failure::None || consumed_)return false;
        if(!sample::next(next_.id,next_.cursor,v)){failure_=Failure::Dimension;return false;}
        return true;
    }
    X2_HD bool emit(Contribution value){
        if(failure_!=Failure::None || consumed_)return false;
        if(effects_.valueCount==16){failure_=Failure::Capacity;return false;}
        effects_.values[effects_.valueCount++]=value;return true;
    }
    X2_HD bool spawn(U32 slot,Ray ray,U32 kind){
        if(failure_!=Failure::None || consumed_)return false;
        U64 branch;
        if(effects_.childCount==15 || !sample::child(next_.id.branch,slot,branch)){
            failure_=Failure::Capacity;return false;
        }
        for(U32 i=0;i<effects_.childCount;++i)if(effects_.children[i].id.branch==branch){
            failure_=Failure::Invalid;return false;
        }
        Child child{next_.id,ray,{next_.throughput[0],next_.throughput[1],next_.throughput[2]},kind};
        child.id.branch=branch;effects_.children[effects_.childCount++]=child;return true;
    }
    // Caller reserves all output capacity first, while owning the input path.
    // A rejection leaves both the path and output unchanged. Reservation and
    // actual queue publication/parent counts belong to the future queue adapter.
    X2_HD bool commit(Record& target,Effects& output,Epoch current,bool reserved) {
        if(consumed_ || failure_!=Failure::None || !reserved || !equal(base_.epoch,current) ||
           !equal(target.epoch,base_.epoch) || target.revision!=base_.revision || base_.revision==~U64(0) ||
           target.id.pixel!=base_.id.pixel || target.id.index!=base_.id.index ||
           target.id.stream!=base_.id.stream || target.id.branch!=base_.id.branch)return false;
        if(!equal(next_.epoch,base_.epoch) || next_.mediumCount>8 || next_.id.pixel!=base_.id.pixel ||
           next_.id.index!=base_.id.index || next_.id.stream!=base_.id.stream || next_.id.branch!=base_.id.branch){
            failure_=Failure::Invalid;return false;
        }
        next_.revision=base_.revision+1;target=next_;output=effects_;consumed_=true;return true;
    }
};
}}}
