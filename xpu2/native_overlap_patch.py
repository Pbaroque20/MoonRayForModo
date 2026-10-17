"""Optional resident-stack native CPU-light/GPU overlap; no path suspension."""
from xpu2.profile_patch import replace


def bridge(code):
    block = r'''    if(windowPending) {
        std::vector<Queue::Ticket> tickets;
        for(const auto& scope:scopes) {
            if(scope.sampling || scope.light)throw std::runtime_error("Unfinished window publication");
            if(scope.ticket)tickets.push_back(scope.ticket);
        }
        if(!tickets.empty() && !deferredQueue().publish(tickets,1))throw std::runtime_error("Window publication rejected");
        windowPending=false;
    }'''
    code = replace(code, block, '    publishNativeWindow();')
    helper = r'''
namespace {
bool publishNativeWindow() {
    if(!windowPending)return false;
    std::vector<Queue::Ticket> tickets;
    for(const auto& scope:scopes) {
        if(scope.sampling || scope.light)throw std::runtime_error("Unfinished window publication");
        if(scope.ticket)tickets.push_back(scope.ticket);
    }
    if(!tickets.empty() && !deferredQueue().publish(tickets,1))throw std::runtime_error("Window publication rejected");
    windowPending=false;return !tickets.empty();
}
}
extern "C" __declspec(dllexport) int xpu2NativeLightOverlap(){
    static const bool use=[] {const char* value=std::getenv("XPU2_NATIVE_LIGHT_OVERLAP");return value && !std::strcmp(value,"1");}();
    return use && enabled();
}
extern "C" __declspec(dllexport) void xpu2BatchedPublish(){
    if(publishNativeWindow())xpu2profile::add(xpu2profile::metrics().native_overlap_windows);
}
extern "C" __declspec(dllexport) void xpu2BatchedSelect(int slot){
    selectSlot(slot);
    if(enabled() && !current().open)throw std::runtime_error("Missing native overlap scope");
}
'''
    code = replace(code, 'extern "C" __declspec(dllexport) void xpu2BatchedBegin(int slot){',
                   helper+'\nextern "C" __declspec(dllexport) void xpu2BatchedBegin(int slot){')
    code = replace(code, 'X(routing_checks)',
                   'X(routing_checks) X(native_overlap_windows) X(native_light_pending_checks) X(native_light_pending_observations)')
    code = replace(code, 'if(current().light)throw std::runtime_error("Nested light region");', r'''if(current().light)throw std::runtime_error("Nested light region");
    if(xpu2NativeLightOverlap()) {
        auto& q=deferredQueue();std::lock_guard<std::mutex> lock(q.mutex);
        xpu2profile::add(xpu2profile::metrics().native_light_pending_checks);
        if(!current().ticket->done)xpu2profile::add(xpu2profile::metrics().native_light_pending_observations);
    }''')
    return '#define XPU2_NATIVE_OVERLAP_BUILT 1\n'+code


def sampler(text):
    start = text.index('void\ndrawBsdfSamples(')
    end = text.index('\nvoid chooseLightsToSample(', start)
    body = text[start:end]
    overlap = replace(body, 'drawBsdfSamples(', 'drawBsdfSamplesOverlapped(')
    overlap = replace(overlap, '        varying bool valid[16];',
                      '        varying bool valid[16];\n        varying LightFilterRandomValues filterValues[16];')
    overlap = replace(overlap, '            valid[slot]=isValid;',
                      '            valid[slot]=isValid;\n            if(lightFilterNeedsSamples)filterValues[slot]=lightFilterSample;')
    first = overlap.index('            if (isValid) {')
    last = overlap.index('            contributions[slot]=lCo;\n            }', first)
    last += len('            contributions[slot]=lCo;\n            }')
    light = overlap[first:last].replace('if (isValid)', 'if (valid[slot])')
    overlap = overlap[:first]+overlap[last:]
    stage = r'''            // GPU owns copied numeric packets. All native state stays live here.
            xpu2BatchedPublish();
            for (uniform int slot=0; slot<count; ++slot) {
                const varying int i=first+slot;
                const uniform int s=base+first+slot;
                if (i>=lobeSampleCount) { continue; }
                xpu2BatchedSelect(slot);
                LightFilterRandomValues lightFilterSample;
                if(lightFilterNeedsSamples)lightFilterSample=filterValues[slot];
''' + light + '\n            }\n'
    overlap = replace(overlap, '            // Collect in the original sample order.',
                      stage+'            // Collect in the original sample order.')
    serial = replace(body, 'drawBsdfSamples(', 'drawBsdfSamplesSerial(')
    signature = body[:body.index('\n{')]
    args = 'pbrTls, shadingTls, bSampler, lSampler, sp, pv, P, cullingNormal, time, sequenceID, bsmp, clampingDepth, clampingValue, indirectFlags, rayDirFootprint, parentLobeLightSets'
    wrapper = signature+'\n{\n    if(xpu2NativeLightOverlap())drawBsdfSamplesOverlapped('+args+');\n    else drawBsdfSamplesSerial('+args+');\n}\n'
    declarations = 'extern "C" uniform int xpu2NativeLightOverlap();\nextern "C" void xpu2BatchedPublish();\nextern "C" void xpu2BatchedSelect(uniform int slot);\n'
    return declarations+text[:start]+serial+overlap+wrapper+text[end:]
