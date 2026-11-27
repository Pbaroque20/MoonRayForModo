"""Short purpose descriptions for the node library, backed by bundled schemas."""
from . import nodes,shader_library,map_library

DESCRIPTIONS={
 'constant':'Outputs one fixed RGB color. Connect it to albedo or another color input.',
 'ConstantColorMap':'Outputs one fixed RGB color. Connect color_value to a material through its output socket.',
 'ConstantScalarMap':'Outputs one fixed number for controls such as roughness or a blend weight.',
 'image':'Reads an image with UV mapping, color-space and image-addressing controls. Ticked Sequence, its file is an image sequence\'s pattern (seq.[####].png): each frame reads its own file, from First Frame at Start Frame, held, repeated or ping-ponged past its ends as Modo\'s image sequence clips are.',
 'texcoord':'Provides named UV coordinates to image or procedural inputs.',
 'normalmap':'Converts an RGB normal texture into a shading-normal input; scale controls its strength.',
 'bump':'Turns a height (a greyscale bump image) into a shading normal, as a Shader Tree Bump layer; amplitude is how high white stands, in scene units. Connect it to a material\'s normal input. A MoonRay Source Override (Bump node in MoonShine graphs), on by default.',
 'ocean':'An ocean: wind-driven waves (Tessendorf\'s FFT ocean) worked out for each frame, choppy crests and all: a vector texture, red the push along U, green the height, blue the push along V. Wire it into a Vector Displacement node\'s Vector and set that as the displacement output (or select the Ocean node and choose Set / Clear Displacement Output, which does both). The surface needs UVs. Waves too short for MoonRay to split the surface for reach it as shading, as in MoonLightIPR (MoonRay Source Override Small ocean waves as shading). With Fit to Mesh on (as it starts), Tiles Across says how many seamless tiles cover the mesh, the whole sea scaled to them whatever the size of the mesh; off, Repeat lays 80 m tiles. A MoonRay Source Override (Ocean nodes in MoonShine graphs), on by default.',
 'ocean_foam':'The foam on an ocean\'s crests, from 0 to 1, where the waves fold over: mix it into the colour or roughness. Left with no settings of its own, it follows the graph\'s Ocean node. A MoonRay Source Override (Ocean nodes in MoonShine graphs), on by default.',
 'ocean_crest':'Where an ocean\'s waves stand highest, from 0 to 1, for the light that shines through their crests: mix a brighter, greener water colour in by it (as the Ocean Plane does). Crest Start sets where it begins. Left with no wave settings of its own, it follows the graph\'s Ocean node. A MoonRay Source Override (Ocean nodes in MoonShine graphs), on by default.',
 'checker':'Creates alternating checker colors, with independent horizontal and vertical scale.',
 'swizzle':'Reorders or extracts color/vector components, such as selecting a single channel.',
 'combine':'Combines three scalar inputs into RGB components.',
 'add':'Adds two inputs component by component.', 'subtract':'Subtracts the second input from the first.',
 'multiply':'Multiplies two inputs component by component; useful for tinting or scaling.',
 'divide':'Divides the first input by the second. Avoid zero divisors.',
 'mix':'Blends background and foreground using a mix weight.',
 'modo_blend':"Lays the foreground over the background as a Modo Shader Tree layer does: by one of Modo's 15 blend modes (Normal, Multiply, Add, Subtract, Screen, Divide, Difference, Darken, Lighten, Overlay, Hard Light, Exclusion, Soft Light, Color Dodge, Color Burn), at its opacity, where its mask lets it (an alpha, a Layer Mask). Chain them to stack layers.",
 'modo_procedural':"A Modo procedural texture (Noise, Cellular, Checker, Grid, Dots, Wood, Weave, Ripples, and the Enhance: Modo patterns) worked out through the object as Modo's Solid projection lays it, with its own settings, colours and alphas; or a Modo Gradient layer. Output Alpha gives its alpha, to wire into a Modo Blend's mask.",
 'modo_projection':"Texture coordinates as a Modo Texture Locator lays them: UV (with its repeats, offset and turn), Planar, Cubic, Spherical, Cylindrical or Front, worked out on the meshes as for Shader Tree layers. Wire it into an image's texcoord.",
 'modo_vertex_map':"A mesh's vertex map by name: a weight map's weight, an RGB map's colour or an RGBA map's alpha at each point, as the kit sends Modo's maps to the renderers. 0 where a mesh has no map of that name.",
 'modo_mask':"0 to 1 for whether a point is in a Shader Tree group mask: by item, Selection Set, Part, Material Tag, weight map or particle (a Replicator's copies), with Invert and Opacity. Wire it into a Modo Blend's mask to do in one graph what a nested mask does.",
 'modo_falloff':"A Texture Locator's falloff: 1 near the locator, fading to 0 away from it (Cubic, Spherical, Linear X, Y or Z, in the locator's own space and size). Wire it into a Modo Blend's mask for decals and wear.",
 'modo_driver':"Driver A to D: a value laid once (a chain of layers) and read by every Gradient wired to it, as Modo's driver effects let one layer drive several others.",
 'modo_environment':"An Environment's output: the colour it shows all around the scene, which lights it. Wire the top Modo Blend of the environment's layers into Color. The kit makes the environment's picture from it as it does from the Shader Tree's environment layers, for MoonRay, XPU2 and MoonLightIPR alike.",
 'modo_environment_image':"An image all around the scene, as a Modo environment Image Map lays it: by its Texture Locator's projection (Spherical, the latitude-longitude HDRI, or Cubic, Light Probe, Planar, Cylindrical, Box, Triplanar), its repeats and turn, with the layer's alpha, channel, flips and colour corrections. While Locator names a Texture Locator in the scene, the image is placed by it (turn it to turn the HDRI); the numbers here are what it was when the layer moved.",
 'modo_environment_sky':"Modo's Environment Material: one colour, a two- or four-colour gradient, overcast, or a Physical Sky lit by its Sun Light (Sun names it; empty, the scene's one Sun Light), as the kit renders them.",
 'modo_environment_procedural':"A Modo Grid or Dots texture all around the scene, laid by its Texture Locator's projection as Modo lays it in an environment, with its colours and alphas.",
 'lerp':'Interpolates between background and foreground using component-wise mix weights.',
 'clamp':'Limits values to the specified low and high bounds.',
 'smoothstep':'Creates a smooth transition between low and high thresholds.',
 'contrast':'Adjusts contrast around a pivot value.',
 'luminance':'Converts a color into brightness using the supplied luminance coefficients.',
 'range':'Remaps one value range to another, with gamma and optional clamping.',
 'convert':'Passes a value through the graph as a color-compatible input.',
 'sign':'Returns the sign of each input component.', 'sqrt':'Computes the square root of each component.',
 'exp':'Computes the exponential of each component.',
 'ifgreater':'Chooses between two inputs by comparing whether value1 is greater than value2.',
 'ifgreatereq':'Chooses between two inputs using a greater-than-or-equal comparison.',
 'ifequal':'Chooses between two inputs by comparing equality.',
 'DwaBaseMaterial':'General surface material with diffuse, metallic, transmission, coat and subsurface controls. Set it as Output to render it.',
 'DwaMetalMaterial':'Models metallic reflection with metal color and roughness controls.',
 'DwaFabricMaterial':'Models fabric shading and its directional fiber response.',
 'DwaRefractiveMaterial':'Models a refractive surface such as glass; use closed geometry for a solid object.',
 'DwaSolidDielectricMaterial':'Models a non-metallic solid surface with dielectric reflection.',
 'DwaSkinMaterial':'Models skin with subsurface scattering and surface reflection.',
 'DwaEmissiveMaterial':'Creates a light-emitting surface material.',
 'DwaLayerMaterial':'Layers a foreground material over a background material; connect material inputs.',
 'DwaMixMaterial':'Blends two connected materials using a mix amount.',
 'DwaAdjustMaterial':'Adjusts properties of a connected material without rebuilding its graph.',
 'DwaColorCorrectMaterial':'Applies color adjustments to a connected material.',
 'DwaSwitchMaterial':'Selects between connected material inputs.',
 'DwaTwoSidedMaterial':'Uses separate material inputs for front and back faces.',
 'DwaToonMaterial':'Provides stylized surface shading for a toon look.',
 'DwaVelvetMaterial_v2':'Models velvet-like surface response.',
 'HairMaterial_v3':'Shades exported hair strands; a mesh preview cannot reproduce strand behavior.',
 'HairDiffuseMaterial':'Provides diffuse hair shading for strand geometry.',
 'HairLayerMaterial':'Layers connected hair materials for strand geometry.',
 'HairColorCorrectMaterial':'Color-corrects a connected hair material.',
 'HairToonMaterial':'Provides stylized shading for hair strands.',
 'RaySwitchMaterial':'Selects a material according to ray type.',
 'SwitchMaterial':'Selects among connected material inputs.',
 'UsdPreviewSurface':'A general USD preview surface with diffuse, metallic, roughness and opacity controls.',
 'TestInputsMaterial':'An upstream diagnostic material for examining shader inputs, rather than a finished surface preset.',
 'AttributeMap':'Reads a named geometry attribute for use in shading.',
 'AxisAngleMap':'Rotates an input using an axis and angle.',
 'BlendMap':'Blends input colors using its blend controls.',
 'CheckerboardMap':'Generates an alternating checker pattern.',
 'ClampMap':'Clamps input values to a range.',
 'CurvatureMap':'Derives a shading value from surface curvature.',
 'DebugMap':'Visualizes shading-state data to help diagnose a scene.',
 'DeformationMap':'Uses deformation-related surface information to drive a map.',
 'DirectionalMap':'Creates a directional response for shading.',
 'ExtraAovMap':'Writes a labeled map value for extra AOV output.',
 'FloatToRgbMap':'Combines scalar values into an RGB color.',
 'GradientMap':'Generates a gradient for material inputs.',
 'HairColorPresetsMap':'Provides preset hair colors.',
 'HairColumnMap':'Provides hair-column data for strand shading.',
 'HairMap':'Maps hair-related shading information.',
 'HsvToRgbMap':'Converts hue, saturation and value components to RGB.',
 'ImageMap':'Reads a texture image for color or data shading.',
 'ImageNormalMap':'Reads a tangent-space normal texture to perturb shading normals.',
 'LODMap':'Selects shading detail through level-of-detail controls.',
 'ListMap':'Chooses a value from a list of inputs.',
 'MultiChannelToFloatMap':'Extracts a scalar from a multi-channel input.',
 'NormalDisplacement':'Displaces a surface along its normal using a scalar input. Connect to Displacement output.',
 'VectorDisplacement':'Displaces a surface using a vector input. Connect to Displacement output and set appropriate bounds.',
 'CombineDisplacement':'Combines connected displacement inputs.',
 'SwitchDisplacement':'Selects one of up to 64 connected displacement inputs by its choice (0 to 63).',
 'CombineNormalMap':'Combines normal-map inputs.',
 'DistortNormalMap':'Distorts a normal-map input.',
 'NormalToRgbMap':'Encodes a normal as RGB values.',
 'OpMap':'Performs a selectable mathematical operation on its inputs.',
 'OpSqrtMap':'Applies a square-root operation to an input.',
 'OpenVdbMap':'Samples data from an OpenVDB grid; requires a VDB asset.',
 'RampMap':'Maps values through a configurable color ramp.',
 'RandomMap':'Generates random shading values using its selection and seed controls.',
 'RandomNormalMap':'Generates randomized normal variation.',
 'RemapMap':'Remaps values using its input and output controls.',
 'RgbToFloatMap':'Extracts a scalar value from RGB.',
 'RgbToHsvMap':'Converts RGB into hue, saturation and value components.',
 'RgbToLabMap':'Converts RGB into Lab color components.',
 'RgbToNormalMap':'Interprets RGB values as a shading normal.',
 'ToonMap':'Produces stylized map values for toon shading.',
 'TransformNormalMap':'Transforms a normal between its supported coordinate spaces.',
 'TransformSpaceMap':'Transforms shading values between coordinate spaces.',
 'TwoSidedMap':'Uses different map values for front and back faces.',
 'UVTransformMap':'Transforms UV texture coordinates.',
 'UsdTransform2d':'Applies a two-dimensional UV transform.',
 'UsdUVTexture':'Reads an image with USD-style UV addressing and channel outputs.',
 'WireframeMap':'Produces a wireframe pattern from geometry edges.'}


def tooltip(kind):
    schema=shader_library.catalog().get(kind) or map_library.catalog().get(kind) or {}
    description=DESCRIPTIONS.get(kind)
    if not description:
        if kind.startswith('ColorCorrect'):
            operation=kind[len('ColorCorrect'):].removesuffix('Map') or 'combined color'
            description='Adjusts '+operation.lower()+' of an incoming color map.'
        elif kind.startswith('Project'):
            projection=next((v for v in ('Triplanar','Cylindrical','Spherical','Planar','Camera') if v in kind),'spatial')
            description='Projects '+('normal textures' if 'Normal' in kind else 'texture images')+' using '+projection.lower()+' mapping.'
            if 'Udim' in kind:description+=' Supports a UDIM texture set.'
        elif kind.startswith('Noise'):description='Generates '+('cellular Worley' if 'Worley' in kind else 'procedural')+' noise for material variation.'
        elif kind.startswith('LayerMap'):description='Combines map layers using blend and mask controls.'
        elif kind.startswith('Switch'):description='Selects between connected '+('normal' if 'Normal' in kind else 'scalar' if 'Float' in kind else 'color')+' inputs.'
        elif kind.startswith('UsdPrimvarReader'):description='Reads a named geometry primvar as '+kind.split('_')[-1]+' data for shading.'
        else:description=str(schema.get('comment') or 'Produces '+nodes.category(kind)+' output from its configured inputs.')
    details=[]
    for key,spec in nodes.specs(kind).items():
        comment=str(spec.get('comment','')).strip()
        if comment:details.append(key+': '+comment[:240])
        if len(details)==2:break
    return kind+'\n\n'+description+('\n\n'+'\n'.join(details) if details else '')+'\n\nClick to add to the graph.'
