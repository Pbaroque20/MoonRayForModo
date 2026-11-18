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


# Render Settings' MoonLightIPR Outputs (AOVs), in the buffer list's order: a tick lists the buffer while MoonLightIPR
# is the engine (Alpha alone in a new scene, scene_settings). (label, key, tip)
_ON = 'On: the preview window lists it among its buffers while MoonLightIPR is the engine'
LISTED = (
    ('Diffuse', 'moonlightipr_diffuse', _ON + '. Diffuse light, subsurface with it: one of the four passes that add up to the beauty'),
    ('Glossy', 'moonlightipr_glossy', _ON + '. Highlights from lights, glossy and mirror reflections, refraction and hair: one of the four passes that add up to the beauty'),
    ('Shadow', 'moonlightipr_shadow', _ON + '. A shadow matte: 0 lit, 1 where the direct light is blocked'),
    ('Emission', 'emission', _ON + '. One of the four passes that add up to the beauty'),
    ('Environment background', 'environment_background', _ON + '. The environment seen past everything: one of the four passes that add up to the beauty'),
    ('Albedo', 'albedo', _ON),
    ('Camera depth', 'depth', _ON),
    ('Shading normal', 'normal', _ON),
    ('World position', 'position', _ON),
    ('Alpha', 'alpha', _ON + ', and Render Animation writes it into each frame (the EXR, and a PNG, TIFF or Targa saved beside it). On in a new scene'),
    ('Motion vectors', 'motion_vectors', _ON + '. How far what the camera sees moves, in pixels, over the shutter'),
)


def listed(settings):
    """The MoonLightIPR AOVs ticked in a scene's Render Settings."""
    held = settings.get('moonlightipr_aovs') if isinstance(settings, dict) else None
    return set(held if isinstance(held, (list, tuple)) else ['alpha'])


def kind(key):
    """The session's number for a buffer, 0 for the beauty or a buffer MoonLightIPR does not make."""
    return AOVS.get(key, 0)
