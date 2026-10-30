# Optional combined readback with explicit audit/performance selection.
from xpu2.profile_patch import replace

def apply(code):
    def edit(old,new,count=1):
        nonlocal code
        code=replace(code,old,new,count)
    edit('X(async_batches) X(async_completions) X(staging_ns)',
         'X(async_batches) X(async_completions) X(staging_ns) X(readback_calls) X(readback_bytes) X(echo_checks) X(audit_samples) X(performance_samples) X(routing_checks)')
    edit('bool asyncTransfers=false;',r'''bool asyncTransfers=false,packedReadback=false,shaderAudit=true;
    const char* corruptResult=std::getenv("XPU2_TEST_CORRUPT_RESULT");''')
    edit('if(asyncTransfers) {\n            LOAD(cuMemHostAlloc)',r'''const char* pack=std::getenv("XPU2_PACKED_READBACK");packedReadback=pack && !std::strcmp(pack,"1");
        const char* audit=std::getenv("XPU2_SHADER_AUDIT");shaderAudit=!(audit && !std::strcmp(audit,"0"));
        if((packedReadback && !asyncTransfers) || (!shaderAudit && !packedReadback))throw std::runtime_error("Unsafe readback mode combination");
        if(asyncTransfers) {
            LOAD(cuMemHostAlloc)''')
    edit('const size_t sizes[]={512*96,512*4,512*96,512*36};',
         'const size_t sizes[]={512*96,512*4,512*(packedReadback?132:96),512*36};')
    edit('CUdeviceptr empty=0;U n=count;\n                void* args[]={&buffers[0],&buffers[1],&buffers[2],&buffers[3],&empty,&empty,&n};',r'''CUdeviceptr empty=0;U n=count;
                // Keep allocation bases unchanged for cleanup; only the kernel's
                // result pointer aliases the packed allocation after this echo.
                CUdeviceptr resultsDevice=packedReadback?buffers[2]+count*96:buffers[3];
                void* args[]={&buffers[0],&buffers[1],&buffers[2],&resultsDevice,&empty,&empty,&n};''')
    edit('check(fn_cuMemcpyDtoHAsync_v2(pinned[2],buffers[2],count*96,transferStream));\n                 check(fn_cuMemcpyDtoHAsync_v2(pinned[3],buffers[3],count*36,transferStream));',r'''if(packedReadback) {
                     const size_t bytes=count*(shaderAudit?132:36);
                     check(fn_cuMemcpyDtoHAsync_v2(pinned[2],shaderAudit?buffers[2]:resultsDevice,bytes,transferStream));
                     xpu2profile::add(prof.readback_calls);xpu2profile::add(prof.readback_bytes,bytes);
                 }else {
                     check(fn_cuMemcpyDtoHAsync_v2(pinned[2],buffers[2],count*96,transferStream));
                     check(fn_cuMemcpyDtoHAsync_v2(pinned[3],buffers[3],count*36,transferStream));
                     xpu2profile::add(prof.readback_calls,2);xpu2profile::add(prof.readback_bytes,count*132);
                 }''')
    edit('std::memcpy(returned,pinned[2],count*96);std::memcpy(result,pinned[3],count*36);',r'''if(packedReadback) {
                     if(shaderAudit)std::memcpy(returned,pinned[2],count*96);
                     const auto* src=static_cast<const unsigned char*>(pinned[2])+(shaderAudit?count*96:0);
                     std::memcpy(result,src,count*36);
                 }else {std::memcpy(returned,pinned[2],count*96);std::memcpy(result,pinned[3],count*36);}''')
    edit('if(std::memcmp(returned+i*24,input+i*24,96)) {++errors;xpu2profile::add(prof.errors);continue;}',r'''if(shaderAudit) {
                    xpu2profile::add(prof.echo_checks);
                    if(std::memcmp(returned+i*24,input+i*24,96)) {++errors;xpu2profile::add(prof.errors);continue;}
                }''')
    edit('U* gpu=result+i*9;',r'''U* gpu=result+i*9;
                // Test-only fault injection after completed DMA, before acceptance.
                if(corruptResult && !std::strcmp(corruptResult,"nan"))gpu[4]=0x7fc00000u;
                if(corruptResult && !std::strcmp(corruptResult,"pdf"))gpu[7]^=1u;
                if(corruptResult && !std::strcmp(corruptResult,"rgb")) {
                    float value;std::memcpy(&value,gpu+4,4);value*=.5f;std::memcpy(gpu+4,&value,4);
                }''')
    edit('if(std::memcmp(native,gpu+1,32)){++mismatch;xpu2profile::add(prof.mismatch);continue;}',r'''bool malformed=gpu[8]>1;
                for(int k=1;k<8;++k)if((gpu[k]&0x7f800000u)==0x7f800000u)malformed=true;
                if((gpu[7]&0x80000000u) && (gpu[7]&0x7fffffffu))malformed=true;
                if(malformed){++invalid;xpu2profile::add(prof.invalid);continue;}
                if(shaderAudit) {
                    xpu2profile::add(prof.audit_samples);
                    if(std::memcmp(native,gpu+1,32)){++mismatch;xpu2profile::add(prof.mismatch);continue;}
                }else {
                    // Native lighting already used wi/pdf/validity. Those words
                    // must still agree; only the redundant RGB audit is omitted.
                    xpu2profile::add(prof.routing_checks);
                    if(std::memcmp(native,gpu+1,12) || native[6]!=gpu[7] || native[7]!=gpu[8]){++mismatch;xpu2profile::add(prof.mismatch);continue;}
                    xpu2profile::add(prof.performance_samples);
                }''')
    return '#define XPU2_PACKED_READBACK_BUILT 1\n'+code
