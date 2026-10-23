#pragma once
#include "path_stage.h"
namespace xpu2 { namespace interactive { namespace sampletest {
using namespace sample;
X2_HD inline Words fixture(U64 i) {
    Identity id{U32(i*0x9e3779b9u),i*0xd2b74407b1ce6e93ull,0x8e1076d9e24a326bull,i>>18};
    U32 group=U32(i*0xbb67ae85u)&0x3fffffffu;
    if((i&7)==0){id.index=~i;id.pixel=~U32(i);id.branch=~(i>>18);}
    return block(id,group);
}
X2_HD inline bool words(Words a,Words b){
    return a.v[0]==b.v[0]&&a.v[1]==b.v[1]&&a.v[2]==b.v[2]&&a.v[3]==b.v[3];
}
// Bitmask diagnostics are identical under host and CUDA compilation.
X2_HD inline U32 checks() {
    U32 failed=0;
    if(!words(philox({{0,0,0,0}},{0,0}),{{0x6627e8d5u,0xe169c58du,0xbc57ac4cu,0x9b00dbd8u}}))failed|=1;
    if(!words(philox({{~0u,~0u,~0u,~0u}},{~0u,~0u}),{{0x408f276du,0x41c83b0eu,0xa20bc7c6u,0x6d5451fdu}}))failed|=2;
    if(!words(philox({{0x243f6a88u,0x85a308d3u,0x13198a2eu,0x03707344u}},{0xa4093822u,0x299f31d0u}),
                     {{0xd16cfe09u,0x94fdccebu,0x5001e420u,0x24126ea1u}}))failed|=4;
    using namespace path;
    Record record{};record.epoch={~U64(0),12,4,7};record.id={~0u,~U64(0),42,0};
    Effects output{};float first=0,again=0;
    Stage miss(record);miss.random(first);miss.draft().lpe[1]=42;
    miss.draft().media[0]={51,1.5f};miss.draft().mediumCount=1;
    miss.emit({2,{1,2,3,4}});miss.spawn(0,{},1);miss.miss();
    if(miss.commit(record,output,record.epoch,true)||record.cursor.offset||record.lpe[1]||record.mediumCount||output.childCount)failed|=8;
    Stage retry(record);retry.random(again);
    if(first!=again)failed|=16;
    retry.emit({2,{1,2,3,4}});retry.spawn(0,{},1);retry.draft().lpe[1]=42;
    retry.draft().media[0]={51,1.5f};retry.draft().mediumCount=1;
    if(retry.commit(record,output,record.epoch,false)||record.revision||output.valueCount)failed|=32;
    for(int i=0;i<4;++i){auto stale=record.epoch;
        if(i==0)--stale.session;if(i==1)++stale.scene;if(i==2)++stale.camera;if(i==3)++stale.settings;
        if(retry.commit(record,output,stale,true))failed|=64;
    }
    if(!retry.commit(record,output,record.epoch,true)||record.cursor.offset!=1||record.lpe[1]!=42||
       record.mediumCount!=1||record.media[0].material!=51||output.childCount!=1||output.valueCount!=1)failed|=128;
    if(retry.commit(record,output,record.epoch,true))failed|=256;
    Stage stale(record),newer(record);Effects effects{};
    if(!newer.commit(record,effects,record.epoch,true)||stale.commit(record,effects,record.epoch,true))failed|=512;
    Stage full(record);for(int i=0;i<17;++i)full.emit({0,{}});
    if(full.failure()!=Failure::Capacity||full.commit(record,effects,record.epoch,true))failed|=1024;
    Stage dup(record);dup.spawn(1,{},0);dup.spawn(1,{},0);
    if(dup.failure()!=Failure::Invalid||dup.commit(record,effects,record.epoch,true))failed|=2048;
    U64 address=0;
    if(child(~U64(0),0,address)||child(0,15,address)||!child(0,14,address)||address!=15)failed|=4096;
    record.cursor={MaxBounces-1,DimensionsPerBounce-1};Stage edge(record);edge.random(first);
    if(edge.random(first)||edge.failure()!=Failure::Dimension||edge.commit(record,effects,record.epoch,true))failed|=8192;
    if(unit(0)!=0 || unit(~0u)>=1 || unit(~0u)!=1.f-0x1p-24f)failed|=16384;
    Identity id{7,0xfedcba9876543210ull,11,9};
    auto b=block(id,0x3fffffffu);
    for(U32 i=0;i<4;++i)if(word(id,0xfffffffcu+i)!=b.v[i])failed|=32768;
    Stage invalid(record);invalid.draft().mediumCount=9;
    if(invalid.commit(record,effects,record.epoch,true))failed|=65536;
    return failed;
}
}}}
