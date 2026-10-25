"""Display filter test scene: make_df_scene.py <folder>. The first AOV scene (aov1/aov-all.rdla) with every MoonRay
display filter (but the image one) reading its outputs, one chained after another, each written as an output."""
import re
import sys
from pathlib import Path
here = Path(__file__).resolve().parent
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
t = (here / 'aov1' / 'aov-all.rdla').read_text(encoding='utf-8')
t = re.sub(r'\["pixel_samples"\]=\d+', '["pixel_samples"]=8', t)
F = '''ToonDisplayFilter("/df/toon") { ["input_diffuse"]=RenderOutput("/diffuse"), ["input_glossy"]=RenderOutput("/glossy"), ["input_albedo"]=RenderOutput("/albedo"), ["input_depth"]=RenderOutput("/depth"), ["input_normal"]=RenderOutput("/N"), ["num_cels"]=3, ["ambient"]=Rgb(0.05,0.05,0.05) }
ConvolutionDisplayFilter("/df/conv") { ["input"]=RenderOutput("/beauty"), ["kernel_size"]=5 }
BlendDisplayFilter("/df/blend") { ["input1"]=RenderOutput("/diffuse"), ["input2"]=RenderOutput("/glossy"), ["blendAmt"]=0.3 }
OpDisplayFilter("/df/op") { ["operation"]=1, ["input1"]=RenderOutput("/diffuse"), ["input2"]=RenderOutput("/glossy") }
ColorCorrectDisplayFilter("/df/cc") { ["input"]=RenderOutput("/beauty"), ["exposure"]=-5.0, ["saturation"]=0.5, ["contrast"]=0.2, ["gamma"]=1.2 }
ClampDisplayFilter("/df/clamp") { ["input"]=RenderOutput("/beauty"), ["max"]=Rgb(50,50,50) }
DiscretizeDisplayFilter("/df/disc") { ["input"]=ColorCorrectDisplayFilter("/df/cc"), ["num_bins"]=4 }
DofDisplayFilter("/df/dof") { ["input"]=RenderOutput("/beauty"), ["depth"]=RenderOutput("/depth"), ["use_camera_attributes"]=false, ["aperture"]=2.0, ["focal_length"]=35.0, ["focus_distance"]=7.0 }
HalftoneDisplayFilter("/df/half") { ["input"]=RenderOutput("/albedo"), ["size"]=5 }
OverDisplayFilter("/df/over") { ["input_top"]=RenderOutput("/diffuse"), ["input_bottom"]=RenderOutput("/glossy"), ["alpha"]=RenderOutput("/alpha"), ["mix"]=0.7 }
RampDisplayFilter("/df/ramp") { ["input"]=RenderOutput("/depth") }
RemapDisplayFilter("/df/remap") { ["input"]=RenderOutput("/beauty"), ["input_max"]=100.0 }
RgbToFloatDisplayFilter("/df/tofloat") { ["input"]=RenderOutput("/beauty") }
RgbToHsvDisplayFilter("/df/hsv") { ["input"]=RenderOutput("/beauty") }
ShadowDisplayFilter("/df/shadow") { ["occluded"]=RenderOutput("/diffuse"), ["unoccluded"]=RenderOutput("/unshadowed"), ["density"]=0.8 }
TangentSpaceDisplayFilter("/df/tangent") { ["input"]=RenderOutput("/N"), ["N"]=RenderOutput("/N"), ["dPds"]=RenderOutput("/dPds") }
ConstantDisplayFilter("/df/const") { ["color"]=Rgb(0.2,0.3,0.4) }
BlendDisplayFilter("/df/chain") { ["input1"]=ToonDisplayFilter("/df/toon"), ["input2"]=ConvolutionDisplayFilter("/df/conv"), ["blendAmt"]=0.5 }
'''
names = re.findall(r'^(\w+)\("(/df/\w+)"\)', F, re.M)
outs = ''.join('RenderOutput("/out%s") { ["file_name"]="OUTPUT", ["channel_format"]=0, ["compression"]=1, ["result"]=15, ["display_filter"]=%s("%s"), ["channel_name"]="%s" }\n'
               % (n.replace('/df', ''), c, n, n.split('/')[-1]) for c, n in names)
# Display filters read outputs: declare them after the outputs they read.
t = t.replace('RenderOutput("/beauty") {', 'RenderOutput("/beauty") {', 1)
t = t + F + outs
(folder / 'df.rdla').write_text(t, encoding='utf-8')
print(len(names), 'filters')
