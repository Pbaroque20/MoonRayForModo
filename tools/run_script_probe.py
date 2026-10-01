"""Run a project-owned Modo fixture with a bounded process lifetime."""
import pathlib
import subprocess
import sys
import shutil
root = pathlib.Path(__file__).resolve().parents[1]
script = (root/'tools'/sys.argv[1]).resolve()
assert script.parent == root/'tools' and script.is_file()
profile = root/'test-results/host-profile'
shutil.copytree(root/'kit/MoonRayForModo',profile/'Configs/MoonRayForModo',dirs_exist_ok=True)
process = subprocess.Popen([r'C:\Program Files\Modo16.1v9\modo\modo_cl.exe',
    '-path:user='+str(profile), '-config:'+str(profile/'MODO_CL16.1.CFG')],
    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
    creationflags=subprocess.CREATE_NO_WINDOW)
try:
    commands='@{%s}\n' % script
    if '--followup' in sys.argv:
        followup=(root/'tools'/sys.argv[sys.argv.index('--followup')+1]).resolve()
        assert followup.parent==root/'tools' and followup.is_file()
        commands+='@{%s}\n' % followup
    if '--material-undo' in sys.argv:
        commands+='select.item {MoonShine assignment test} set\nmoonray.material.assign\napp.undo\n@{%s}\n' % (root/'tools/probe_material_undo.py')
    output,_ = process.communicate(commands+'!app.quit\n',timeout=120)
except subprocess.TimeoutExpired:
    process.kill()
    output,_ = process.communicate()
    raise SystemExit('Probe timed out: '+output[-2000:])
print(output[-2500:])
if process.returncode or 'Script execution failed' in output:
    raise SystemExit(process.returncode or 1)
