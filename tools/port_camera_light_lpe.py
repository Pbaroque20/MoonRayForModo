"""A camera ray seeing a light past every surface, in light path expressions.

RayHandlers.cc's miss handler declares two variables anew inside their branches: hitLight, so that the one its light path
code asks is always null, and lpeStateId in that code's case 1, so that the state it accumulates with stays -1. C<L.> and
every other light output has nothing where a camera ray sees a light past every surface. Scalar mode
(PathIntegrator::computeRadiance) has it right. The kit's Environment background output was black because of this.

Only when MoonRay is started with MOONRAY_MODO_CAMERA_LIGHT_LPE=1 (the plugin's preference), the light and its state are
kept. Without the variable MoonRay is as its source has it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/handlers/RayHandlers.cc'

SEEN_OLD = '''                const Light *hitLight = nullptr;
                if (rs->mRay.getDepth() == 0) {
'''
SEEN_NEW = '''                const Light *hitLight = nullptr;
                const Light *modoCameraLight = nullptr; // Modo: the light seen (tools/port_camera_light_lpe.py)
                if (rs->mRay.getDepth() == 0) {
'''
FOUND_OLD = '''                        sInfiniteLightDistance, lightChoiceSamples, hitLightIsect, numHits);

                    if (hitLight) {
                        // Evaluate the radiance on the selected light in camera.
'''
FOUND_NEW = '''                        sInfiniteLightDistance, lightChoiceSamples, hitLightIsect, numHits);
                    modoCameraLight = hitLight;

                    if (hitLight) {
                        // Evaluate the radiance on the selected light in camera.
'''
USED_OLD = '''                        lpeStateId = rs->mPathVertex.lpeStateIdLight;
                    }

                    if (lpeStateId >= 0) {
'''
USED_NEW = '''                        lpeStateId = rs->mPathVertex.lpeStateIdLight;
                    }
                    // Modo: what the two branches above lose as they end.
                    static const bool modoCameraLightOn = [] {
                        const char *value = std::getenv("MOONRAY_MODO_CAMERA_LIGHT_LPE");
                        return value && value[0] == '1';
                    }();
                    if (modoCameraLightOn && modoCameraLight && rs->mPathVertex.lpeStateId >= 0) {
                        lpeStateId = lightAovs.lightEventTransition(pbrTls, rs->mPathVertex.lpeStateId, modoCameraLight);
                    }

                    if (lpeStateId >= 0) {
'''
# This port's first form, which kept only the state, and so did nothing.
FIRST = (('''                            // Modo: the state above is lost as this branch ends (tools/port_camera_light_lpe.py).
                            modoCameraLightState = lpeStateId;
''', ''), ('''                    int modoCameraLightState = -1;
''', ''), ('''                    static const bool modoCameraLight = [] {
                        const char *value = std::getenv("MOONRAY_MODO_CAMERA_LIGHT_LPE");
                        return value && value[0] == '1';
                    }();
                    if (modoCameraLight && modoCameraLightState >= 0) lpeStateId = modoCameraLightState;
''', ''))


def main():
    # XPU mode's rays that miss on the graphics card have a copy of the same code.
    for path in (HANDLERS, HANDLERS.with_name('XPURayHandlers.cc')):
        raw = path.read_bytes().decode('utf-8')
        crlf = '\r\n' in raw
        text = raw.replace('\r\n', '\n')
        if 'modoCameraLightOn' in text:
            print('already applied', path.name)
            continue
        for old, new in FIRST:
            if old in text:
                text = text.replace(old, new)
        for old, new in ((SEEN_OLD, SEEN_NEW), (FOUND_OLD, FOUND_NEW), (USED_OLD, USED_NEW)):
            if text.count(old) != 1:
                raise SystemExit('%s: expected once, found %d: %s' % (path.name, text.count(old), old[:70]))
            text = text.replace(old, new)
        if '#include <cstdlib>' not in text:
            first = text.index('#include')
            text = text[:first] + '#include <cstdlib>\n' + text[first:]
        path.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode('utf-8'))
        print('patched', path.name)


if __name__ == '__main__':
    main()
