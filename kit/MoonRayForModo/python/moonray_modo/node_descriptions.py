"""Short purpose descriptions for the node library, backed by bundled schemas."""
from . import nodes,shader_library,map_library

DESCRIPTIONS={
 'constant':'Outputs one fixed RGB color. Connect it to albedo or another color input.',
 'ConstantColorMap':'Outputs one fixed RGB color. Connect color_value to a material through its output socket.',
 'ConstantScalarMap':'Outputs one fixed number for controls such as roughness or a blend weight.',
 'image':'Reads an image with UV mapping, color-space and image-addressing controls.',
 'texcoord':'Provides named UV coordinates to image or procedural inputs.',
 'normalmap':'Converts an RGB normal texture into a shading-normal input; scale controls its strength.',
 'checker':'Creates alternating checker colors, with independent horizontal and vertical scale.',
 'swizzle':'Reorders or extracts color/vector components, such as selecting a single channel.',
 'combine':'Combines three scalar inputs into RGB components.',
 'add':'Adds two inputs component by component.', 'subtract':'Subtracts the second input from the first.',
 'multiply':'Multiplies two inputs component by component; useful for tinting or scaling.',
 'divide':'Divides the first input by the second. Avoid zero divisors.',
 'mix':'Blends background and foreground using a mix weight.',
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
