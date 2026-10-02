"""Validate standalone denoiser input and propagate execution failures."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'upstream/openmoonray/moonray/moonray/cmd/denoise_cmd/main.cc'
s=p.read_text(encoding='utf-8')
s=s.replace('    // TODO: Should we check the number of channels here?', """    if (imageSpec.width <= 0 || imageSpec.height <= 0 ||
        (imageSpec.nchannels != 3 && imageSpec.nchannels != 4)) {
        throw scene_rdl2::except::IoError("Denoiser requires an RGB or RGBA image");
    }""")
s=s.replace('            std::cerr << "Error denoising: " << errorMsg << std::endl;', '            throw std::runtime_error("Error denoising: " + errorMsg);')
p.write_bytes(s.encode('utf-8'))

p=root/'toolchain/xpu/optix-dev/include/optix_stubs.h'
s=p.read_text(encoding='utf-8').replace('void* symbol = GetProcAddress( (HMODULE)*handlePtr, "optixQueryFunctionTable" );','void* symbol = reinterpret_cast<void*>(GetProcAddress( (HMODULE)*handlePtr, "optixQueryFunctionTable" ));')
p.write_bytes(s.encode('utf-8'))
