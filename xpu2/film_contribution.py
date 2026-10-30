"""Batch live contribution work inside the native resident sample window."""
from pathlib import Path
from xpu2.profile_patch import replace


def sampler(text):
    call="""            integrateBsdfSample(bSampler, lobeIndex,
                    lSampler, pv.pathThroughput, lCo, bsmp[s]);"""
    collect=Path(__file__).with_name('batched_collect.ispc.inc').read_text(encoding='utf-8')
    # Keep invalid-lane ticket retirement before the valid-lane contribution gate.
    text=replace(text,collect,'            if(!filmMode) {\n'+collect+'\n            }\n            if (!valid[slot]) { continue; }\n',2)
    loop="""            // Collect in the original sample order. No CPU-native pointer is
            // passed to the worker; light records stay in this live stack.
            for (uniform int slot=0; slot<count; ++slot) {"""
    prelude=Path(__file__).with_name('film_window.ispc.inc').read_text(encoding='utf-8')
    prelude=prelude.replace('@@COLLECT@@',collect)
    text=replace(text,loop,prelude+'\n'+loop,2)
    apply="""            if(!filmMode || (filmMode>2 && !(filmAccepted[slot]&(1<<programIndex)))) {
                integrateBsdfSample(bSampler,lobeIndex,lSampler,pv.pathThroughput,lCo,bsmp[s]);
            }
            if(filmMode && (filmAccepted[slot]&(1<<programIndex))) {
                int b=(slot*8+programIndex)*8;
                bsmp[s].distance=filmOut[b];
                bsmp[s].tDirect=Color_ctor(filmOut[b+1],filmOut[b+2],filmOut[b+3]);
                bsmp[s].tIndirect=Color_ctor(filmOut[b+4],filmOut[b+5],filmOut[b+6]);
            }"""
    decl='extern "C" uniform int xpu2FilmMode();\nextern "C" void xpu2FilmWindow(uniform float input[],uniform float reference[],uniform float output[],uniform int masks[],uniform int accepted[],uniform int count);\n'
    return decl+replace(text,call,apply,2)
