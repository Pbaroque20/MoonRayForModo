"""Modo's shading models as MoonRay's specular lobes.

Modo's material draws its highlight by one of four models. GTR and Principled are the shape of MoonRay's GGX lobe.
Blinn and Ashikhmin are not: their highlights are the shape of MoonRay's Beckmann lobe, at another roughness than
Modo's. All but Principled also reflect less light than MoonRay's lobe, which gives back the light that bounces
between the facets of a rough surface: Blinn much less at any roughness, Ashikhmin and GTR less once they are rough.

What each needs was found by drawing Modo's own renders of a ball and a box under one light, over a range of
roughness, and looking for the lobe and roughness in MoonLightIPR whose picture had the same shape, and then for the
strength that made it as bright (tools/probe_shading_models.py, tools/check_shading_models.py fit). Between the
measured roughnesses the values are read along straight lines. A roughness that an image drives is left as the image
gives it.
"""

# For each model: Modo's roughness, then MoonRay's roughness and what the highlight's strength is multiplied by.
MEASURED = {
    'blinn': [(.1, .20, .301), (.2, .28, .363), (.35, .36, .520), (.5, .36, .590), (.7, .38, .598), (.9, .50, .730)],
    'ashikhmin': [(.1, .22, 1.0), (.2, .28, 1.0), (.35, .38, .855), (.5, .44, .809), (.7, .48, .785), (.9, .50, .770)],
    'gtr': [(.1, .10, 1.0), (.5, .50, 1.0), (.7, .70, .848), (.9, .90, .762)],
}
# The models whose highlight is MoonRay's Beckmann lobe; the others are its GGX.
BECKMANN = ('blinn', 'ashikhmin')


def translated(model, roughness):
    """(roughness, strength, Beckmann) for a material of that model and roughness as MoonRay is to draw it."""
    rows = MEASURED.get(model)
    if rows is None:
        return roughness, 1.0, False
    roughness, beckmann = float(roughness), model in BECKMANN
    if roughness <= rows[0][0]:
        # Below the smoothest that was measured, the roughness shrinks in proportion and the strength holds.
        return rows[0][1] * roughness / rows[0][0], rows[0][2], beckmann
    for (r0, to0, k0), (r1, to1, k1) in zip(rows, rows[1:]):
        if roughness <= r1:
            t = (roughness - r0) / (r1 - r0)
            return to0 + (to1 - to0) * t, k0 + (k1 - k0) * t, beckmann
    return rows[-1][1], rows[-1][2], beckmann
