// Included in Bridge. Upload invariant lobe inputs once for repeated samples.
bool compact=std::getenv("XPU2_SHARED_INPUTS") && !std::strcmp(std::getenv("XPU2_SHARED_INPUTS"),"1");
CUfunction compactKernel=nullptr;
unsigned long long compactBatches=0,compactUploadBytes=0,regularUploadBytes=0,lastTransferBytes=0;
size_t encodeCompact(FlightSlot& slot,const float* input,int count) {
    U* packed=static_cast<U*>(slot.compactHost);
    packed[0]=count;U* descriptors=packed+2;U* common=descriptors+count*3;
    unsigned previous[8];for(auto& i:previous)i=~0u;
    unsigned used=0;
    for(int i=0;i<count;++i){
        const auto* src=reinterpret_cast<const unsigned char*>(input+i*24);
        unsigned index=previous[i%8];
        const auto* old=index==~0u?nullptr:reinterpret_cast<const unsigned char*>(common+index*24);
        if(!old || std::memcmp(src,old,44) || std::memcmp(src+52,old+52,44)){
            index=used++;std::memcpy(common+index*24,src,96);previous[i%8]=index;
        }
        descriptors[i*3]=index;std::memcpy(descriptors+i*3+1,src+44,8);
    }
    packed[1]=used;
    return 8+count*12+used*96;
}
