#!/bin/sh
# Tests for cpu-63: mapped volumes against the references already rendered, moving instances, VDB light filters and
# subdivided mesh lights, object-space vector displacement, isolated glass.
S="C:/Users/RAPHAE~1/AppData/Local/Temp/claude/C--Users-Raphael-Tobar-MoonRayForModo/b3bced51-6a38-43de-8c04-9d72d0b73706/scratchpad"
T="C:/Users/Raphael Tobar/MoonRayForModo-xpu2/test-results"
X="$T/xpu2-cpu-63/runtime-xpu2/moonray_xpu2.exe"
RT="/c/Users/Raphael Tobar/AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime"
TOOL="$RT/oiiotool.exe"
cd "$S" || exit 1
for c in hv-density hv-intensity-div hv-voxel-size hv-albedo hv-anisotropy hv-match hv-density-subd hv-emission; do
  python xpu2_only.py hv1 "$X" $c --name x63 >> hv1/run63.txt 2>&1
  PATH="$RT:$PATH" python block_cmp.py "$TOOL" hv1/$c-moonray.exr hv1/$c-x63.exr hv1/$c-moonray1.exr >> hv1/run63.txt 2>&1
done
python feature_compare.py mi1 "$X" mi-points-sliding mi-points-turning mi-points-own mi-curves-sliding mi-curves-turning mi-curves-own cv-ssr-moving > mi1/run63.txt 2>&1
python feature_compare.py lm1 "$X" lfv-basic lfv-remap lfv-blur lfv-sphere-blur lfv-quadratic lfv-missing ml-subd ml-subd-part > lm1/run63.txt 2>&1
python feature_compare.py vdo1 "$X" vdo-noise vdo-const vdo-noise-still > vdo1/run63.txt 2>&1
python feature_compare.py gl2 "$X" g2-dwa g2-dwa-env g2-usd g2-usd-env g2-dwa-rough g2-dwa-thin > gl2/run63.txt 2>&1
for c in g2-dwa g2-dwa-env g2-usd g2-usd-env g2-dwa-rough g2-dwa-thin; do
  echo "== $c" >> gl2/grid.txt; python region_grid.py gl2/$c-moonray.exr gl2/$c-xpu2.exr gl2/$c-moonray1.exr 2>&1 | head -16 >> gl2/grid.txt
done
echo done
