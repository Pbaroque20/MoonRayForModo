"""The AOVs MoonLightIPR makes, for motion graphics: what a composite is made with.

The light in four passes that add up to the beauty (fog's light before the first surface apart): Diffuse (with
subsurface), Glossy (with hair, mirror reflections and refraction), Emission and the Environment background, as the
first surface the camera sees decides. They are gathered beside the beauty from its own paths, so that they add up to
it sample by sample.

From what the camera sees first: Albedo, Camera depth, Shading normal, World position, Alpha and Motion vectors (how far
it moves in pixels from the shutter's opening to its closing, as MoonRay's say it: objects and the camera, not yet a
mesh changing shape), by a small program of their own.

All of them are gathered at once from the first one chosen, which begins the render again once; after that, choosing
another (or the beauty) is only another picture sent, at once (tools/check_moonlightipr_passes.py). Cryptomatte is
MoonRay's alone.

Each is the kit's buffer key and the number the session takes for it ("aov <n> <key>", moonlightipr_session.cpp): 1 to 4
the light passes (AovPass in moonlightipr/src/device/shared.h), 5 on the geometry AOVs (AovSlot, from 0). Diffuse and
Glossy are MoonLightIPR's own buffers: MoonRay's are split into direct and indirect light.
"""

AOVS = {
    'moonlightipr_diffuse': 1,
    'moonlightipr_glossy': 2,
    'emission': 3,
    'environment_background': 4,
    'albedo': 5,
    'depth': 6,
    'normal': 7,
    'position': 8,
    'alpha': 9,
    # The motion vectors: read with the shutter's two ends, held at the frame's moment where motion blur is off.
    'motion_vectors': 10,
    # A shadow matte, how much of the direct light at what the camera sees was blocked: 0 lit to 1 in full shadow.
    'moonlightipr_shadow': 11,
}

# MoonLightIPR's own buffers, listed first after the beauty, and only while MoonLightIPR is the engine. Glossy is
# MoonRay's direct and indirect glossy together (what compositors call specular): highlights from lights, glossy and mirror reflections, refraction, hair.
OWN = (('Diffuse', 'moonlightipr_diffuse'), ('Glossy', 'moonlightipr_glossy'), ('Shadow', 'moonlightipr_shadow'))
OWN_KEYS = frozenset(key for _, key in OWN)


def kind(key):
    """The session's number for a buffer, 0 for the beauty or a buffer MoonLightIPR does not make."""
    return AOVS.get(key, 0)
