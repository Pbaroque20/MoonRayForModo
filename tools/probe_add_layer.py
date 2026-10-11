# python
"""Isolated GUI test: what the Shader Tree's Add Layer list offers, and where the MoonRay materials are in it."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/add-layer'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    command = lx.service.Command().Spawn(lx.symbol.iCTAG_NULL, 'shader.create')
    hints = None
    tried = []
    for make in (lambda: lx.object.AttributesUI(command).UIValueHints(0), lambda: lx.object.Command(command).UIValueHints(0), lambda: command.UIValueHints(0)):
        try:
            hints = lx.object.UIValueHints(make())
            break
        except Exception as exc:
            tried.append(str(exc))
    result['tried'] = tried
    listed = []
    for index in range(hints.PopCount()):
        entry = [hints.PopInternalName(index), hints.PopUserName(index)]
        try:
            entry.append(hints.PopCategory())
        except Exception:
            pass
        listed.append(entry)
    result['count'] = len(listed)
    result['ours'] = [entry for entry in listed if 'material.dw.' in str(entry[0]) or 'moonray' in str(entry[0]).lower() or 'mtlx' in str(entry[0])]
    result['custom'] = [entry for entry in listed if any(word in str(entry[0]) for word in ('celShader', 'skinMaterial', 'hairMaterial'))]
    result['entries'] = [entry[:2] for entry in listed if 'moonrayAdd' in str(entry[0])][:40]
    result['trial_listed'] = [entry for entry in listed if 'trial' in str(entry).lower()]
    result['materials_listed'] = [entry[0] for entry in listed if 'aterial' in str(entry[0]) or 'Shader' in str(entry[0])]
    scene_service = lx.service.Scene()
    supers = {}
    for name in ('unrealShader', 'unityShader', 'glTFShader', 'AxFShader', 'material.celShader', 'material.skinMaterial', 'advancedMaterial',
                 'material.dwtrial', 'dwtrial', 'moonray.layer.DwaBaseMaterial', 'moonray.layer.MaterialX', 'material.dw.DwaBaseMaterial', 'material.moonrayMoonShine', 'material.mtlx', 'defaultShader', 'mask'):
        try:
            code = scene_service.ItemTypeLookup(name)
            chain = []
            while True:
                chain.append(scene_service.ItemTypeName(code))
                try:
                    code = scene_service.ItemTypeSuper(code)
                except Exception:
                    break
                if not code or len(chain) > 6:
                    break
            supers[name] = chain
        except Exception as exc:
            supers[name] = str(exc)
    result['supers'] = supers
    def note(step):
        result['reached'] = step
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    note('listed')
    # Chosen as the list chooses it: the entry is made, and a moment later the material stands in its place.
    made = {}
    for kind in ('material.moonrayAddDwaBaseMaterial',):
        try:
            lx.eval('shader.create {%s}' % kind)
            made[kind] = 'made'
        except Exception as exc:
            made[kind] = str(exc)
    result['shader_create'] = made
    note('entry made')
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def after():
    try:
        import modo
        scene = modo.Scene()
        result['after_choice'] = [[item.type, item.name, item.parent.name if item.parent else None] for item in scene.items() if item.type.startswith(('material.moonrayAdd', 'material.dw.'))]
        result['selected'] = [item.type for item in scene.selected]
    except Exception:
        result['after_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


from PySide2 import QtCore
QtCore.QTimer.singleShot(3000, after)
