"""The lights-seen-by-the-camera change, put into MoonLightIPR's source as of form L (the XPU2 kit's base), as scene
mark 'l': the same as L with one number more in each local light, whether the camera sees it."""
import sys
from pathlib import Path

root = Path(sys.argv[1]) / 'moonlightipr'


def rep(path, old, new):
    text = path.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise SystemExit('%s: expected once: %r' % (path.name, old[:70]))
    path.write_text(text.replace(old, new), encoding='utf-8')


rep(root / 'include/moonlightipr/moonlightipr.h',
    "    int32_t texture = -1;               // a picture across the light, from addTexture; not for a portal or a mesh\n",
    "    int32_t texture = -1;               // a picture across the light, from addTexture; not for a portal or a mesh\n"
    "    bool visibleInCamera = false;       // whether the camera sees it shining where it stands; never a portal\n")
loader = root / 'session/scene_loader.cpp'
rep(loader, "    if (mark != 0x4c534c4d)", "    // 'l': form L with whether the camera sees each local light (the XPU2 kit's own).\n    if (mark != 0x6c534c4d)")
rep(loader, "this MoonLightIPR reads 'L')", "this MoonLightIPR reads 'l')")
text = loader.read_text(encoding='utf-8')
old = "        light.texture = image(in.value<int32_t>());\n        lightFilters[l].resize(in.value<uint32_t>());"
if text.count(old) != 1:
    raise SystemExit('loader: local light texture line not found once')
loader.write_text(text.replace(old, "        light.texture = image(in.value<int32_t>());\n        light.visibleInCamera = in.value<uint32_t>() != 0;\n"
                                    "        lightFilters[l].resize(in.value<uint32_t>());"), encoding='utf-8')
renderer = root / 'src/renderer.cpp'
rep(renderer, "        if (light.kind == Light::Mesh) {\n",
    "        // Whether the camera sees the light itself, as MoonRay shows a light whose Visible in Camera is on.\n"
    "        out.pad = light.visibleInCamera && light.kind != Light::Portal ? 1u : 0u;\n        if (light.kind == Light::Mesh) {\n")
rep(renderer, "            // A mesh light has no cone; the number says instead whether the camera sees the surface shining.\n"
              "            out.pad = light.outerConeDegrees > 0.5f ? 1u : 0u;\n", "")
kernel = root / 'src/device/kernel.cu'
rep(kernel, "        for (unsigned i = 0; !camera && !emerged && i < params.lightCount; ++i) {\n",
    """        if (camera) {
            // A light whose Visible in Camera is on is seen where it stands, its picture on it, as MoonRay shows it:
            // in front of what is behind it, which it hides. The nearest one before the surface hit is what is seen.
            float nearest = lightReach;
            float3 shining = vec(0.0f);
            bool seenLight = false;
            for (unsigned i = 0; i < params.lightCount; ++i) {
                if (!lights[i].pad || lights[i].type == LIGHT_MESH) continue;
                float pdf, reached = 0.0f;
                float3 emitted;
                if (!hitLightShape(lights[i], origin, direction, nearest, pdf, emitted, reached)) continue;
                if (lights[i].texture || lights[i].filterCount) emitted = emitted * lightTint(lights[i], origin, direction, reached);
                nearest = reached;
                shining = emitted;
                seenLight = true;
            }
            if (seenLight) {
                radiance += throughput * shining;
                guideAlbedo = make_float3(fminf(shining.x, 1.0f), fminf(shining.y, 1.0f), fminf(shining.z, 1.0f));
                guideNormal = -direction;
                break;
            }
        }
        for (unsigned i = 0; !camera && !emerged && i < params.lightCount; ++i) {
""")
print('backported')

# 2026-10-28, later: the ray offset made a few float steps (1e-6), as the repo's kernel: Dose's water drops, whose
# undersides lie on the label within hundredths of a millimetre, were black at 1e-4. Applied by hand to kernel.cu here.
