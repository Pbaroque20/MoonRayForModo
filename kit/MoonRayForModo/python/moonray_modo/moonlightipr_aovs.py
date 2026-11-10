"""The AOVs MoonLightIPR gathers, one at a time (the one looked at), for motion graphics: what a composite is made with.

The light in four passes that add up to the beauty, fog's light apart: Diffuse (with subsurface), Glossy (with mirror
reflections and refraction), Emission and the Environment background. From what the camera sees first: Alpha, Camera
depth, Shading normal, World position and Albedo. Cryptomatte is MoonRay's alone.

Each is the kit's buffer key and the kernel's number for it (AovKind, moonlightipr/src/device/shared.h). Diffuse and
Glossy are MoonLightIPR's own buffers: MoonRay's are split into direct and indirect light.
"""

AOVS = {
    'albedo': 1,
    'moonlightipr_diffuse': 2,
    'moonlightipr_glossy': 3,
    'emission': 4,
    'environment_background': 5,
    'alpha': 6,
    'depth': 7,
    'normal': 8,
    'position': 9,
}

# MoonLightIPR's own buffers, listed after MoonRay's, and only while MoonLightIPR is the engine.
OWN = (('Diffuse', 'moonlightipr_diffuse'), ('Glossy', 'moonlightipr_glossy'))
OWN_KEYS = frozenset(key for _, key in OWN)


def kind(key):
    """The kernel's number for a buffer, 0 for the beauty or a buffer MoonLightIPR does not gather."""
    return AOVS.get(key, 0)
