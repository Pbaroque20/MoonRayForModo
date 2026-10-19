# python
"""Command-line test: every channel of Modo's standard material, with its value in a new scene."""
import json
import pathlib
import traceback
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\material-channels')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    material = next(iter(modo.Scene().items('advancedMaterial')))
    for index in range(material.ChannelCount()):
        name = material.ChannelName(index)
        try:
            value = material.channel(name).get()
            result[name] = value if isinstance(value, (int, float, str)) else str(type(value).__name__)
        except Exception as exc:
            result[name] = 'unread'
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
