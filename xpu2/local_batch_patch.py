"""Isolated bulk endpoint capacity; native queue and installed runtime unchanged."""
from xpu2.profile_patch import replace


def apply(code, capacity=16384):
    if type(capacity) is not int or capacity < 512 or capacity > 16384 or capacity % 8:
        raise ValueError('Bulk capacity must be an eight-lane multiple in [512,16384]')
    code = replace(code, 'const size_t sizes[]={512*96,512*4,512*(packedReadback?132:96),512*36};',
                   'const size_t sizes[]={%d*96,%d*4,%d*(packedReadback?132:96),%d*36};' % ((capacity,)*4))
    code = replace(code, 'if(count<1 || count>512)', 'if(count<1 || count>%d)' % capacity)
    # Reuse bounded heap scratch, avoiding a multi-megabyte worker stack frame.
    code = replace(code, 'bool asyncTransfers=false,packedReadback=false,shaderAudit=true;',
                   'std::vector<U> bulkLengths=std::vector<U>(%d),bulkResult=std::vector<U>(%d*9),bulkReturned=std::vector<U>(%d*24);\n    bool asyncTransfers=false,packedReadback=false,shaderAudit=true;' % ((capacity,)*3))
    code = replace(code, 'U lengths[512],result[512*9],returned[512*24];',
                   'U* lengths=bulkLengths.data();U* result=bulkResult.data();U* returned=bulkReturned.data();')
    return code
