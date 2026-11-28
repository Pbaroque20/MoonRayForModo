# python
"""Command line: shader_tree_revert.run() called from this probe on the scene as it is, each Modo command it gives written
(and flushed) to MOONRAY_PROBE_OUT/trace.txt before it runs, to find the one a crash is in. Run after a conversion
(tools/launch_cl_steps.py ... probe_cl_shader_tree_revert.py moonray.material.moveShaderTreeTextures
probe_cl_shader_tree_revert.py probe_cl_shader_tree_revert_trace.py)."""
import os
import pathlib
import traceback
import lx

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results\shader-tree-revert')
trace = open(str(out / 'trace.txt'), 'w', encoding='utf-8')
real = lx.eval


def logged(command, *args, **named):
    trace.write(command + '\n')
    trace.flush()
    os.fsync(trace.fileno())
    return real(command, *args, **named)


lx.eval = logged
try:
    from moonray_modo import shader_tree_revert
    shader_tree_revert.lx.eval = logged
    report = shader_tree_revert.run()
    trace.write('DONE\n' + '\n'.join(report.lines()) + '\n')
except Exception:
    trace.write('ERROR\n' + traceback.format_exc())
finally:
    lx.eval = real
    trace.close()
