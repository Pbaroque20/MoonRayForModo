"""Enable upstream's XPU-first Auto branch while retaining feature fallback."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'upstream/openmoonray/moonray/moonray/lib/rendering/rndr/RenderContext.cc'
s=p.read_text(encoding='utf-8')
start=s.find('            // Uncomment the following to have AUTO mode start with XPU:')
if start>=0:
    end=s.index('            mExecutionMode = ExecutionMode::VECTORIZED;',start)+len('            mExecutionMode = ExecutionMode::VECTORIZED;')
    s=s[:start]+'''            // MoonRayForModo: Auto prioritizes feature support, then XPU > Vector > Scalar.
            executionModeString = "Executing an XPU render since execution mode was set to auto.";
            allowUnsupportedXPUFeatures = false;
            mExecutionMode = ExecutionMode::XPU;'''+s[end:]
    p.write_bytes(s.encode('utf-8'))
elif '// MoonRayForModo: Auto prioritizes feature support' not in s:
    raise RuntimeError('Unknown Auto implementation; review upstream before patching')
print('XPU-first Auto selection enabled')
