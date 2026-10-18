# python
"""Command-line test: the sampling settings greyed by the sampling modes. Pixel Samples is live under uniform
sampling only, Minimum and Maximum Samples and Target Error under adaptive only, and Light Quality under adaptive
light sampling only; Light Samples is live under both. Each setting is asked whether it is enabled, as Modo greys its
control."""
import json
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\sampling-greyed')
out.mkdir(parents=True, exist_ok=True)
result = {}


def enabled(name):
    try:
        spawned = lx.object.Command(lx.service.Command().Spawn(lx.symbol.iCTAG_NULL, name))
    except Exception as exc:
        return 'error: %s' % exc
    try:
        spawned.Enable(lx.service.Message().Allocate())
        return True
    except Exception:
        return False


try:
    for mode, value in (('uniform', 0), ('adaptive', 1)):
        lx.eval('moonray.render.sampling_mode %d' % value)
        result[mode] = {key: enabled('moonray.render.' + key) for key in
                        ('samples', 'min_adaptive_samples', 'max_adaptive_samples', 'target_adaptive_error')}
    for mode, value in (('uniform lights', 0), ('adaptive lights', 1)):
        lx.eval('moonray.render.light_sampling_mode %d' % value)
        result[mode] = {key: enabled('moonray.render.' + key) for key in ('light_sampling_quality', 'light_samples')}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1))
