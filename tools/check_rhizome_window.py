"""Exercise the Rhizome window (kit/.../rhizome_window.py) under Qt, outside Modo: a real node and master on this machine.

Run with Modo's bundled interpreter (PySide2), offscreen:
  check_rhizome_window.py <runtime-xpu2 folder with Rhizome> <scene.rdla> <scratch folder>
The window is built (its runtime asked whether it has Rhizome), a node is started from its node page, a master on the
scene from the module's start(), and the window's pages read their state: the node running, the frame's progress, the
swarm's table, this machine's hashes and the firewall's rule. Both are stopped by their PIDs at the end. Machines listen
on 127.0.0.1 alone (no Windows Firewall question); the export of a Modo scene and the Render button need Modo."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from PySide2 import QtWidgets  # noqa: E402

runtime, scene, scratch = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
from moonray_modo import rhizome_window as rw  # noqa: E402

# This check's own runtime, folders and environment; machines on this machine only.
rw.executable = lambda: runtime / 'moonray_xpu2.exe'
rw.base_folder = lambda: scratch
env = dict(os.environ, PATH=str(runtime) + os.pathsep + os.environ.get('PATH', ''), RDL2_DSO_PATH=str(runtime), REZ_MOONRAY_ROOT=str(runtime))
rw.environment = lambda: env
rw.device_mode = lambda: '0'
started = rw.start
# (A broadcast goes out on the network adapter, and a node answers from that address, which a node listening on
# 127.0.0.1 does not take: the node is given the master's address instead, discovery off.)
rw.start = lambda role, arguments: started(role, list(arguments) + ['--bind', '127.0.0.1', '--no-discovery'] +
                                           (['--master', '127.0.0.1:47110'] if role == 'node' else []))

failures = []


def check(ok, what):
    print(('ok   ' if ok else 'FAIL ') + what, flush=True)
    if not ok:
        failures.append(what)


def until(test, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if test():
            return True
        time.sleep(0.25)
    return False


app = QtWidgets.QApplication([])
window = rw.Window()
check(window.tabs.isEnabled(), 'the window finds Rhizome in the runtime')
window.key.setText('rhizome window check')
window.node_threads.setValue(2)
try:
    # A node from the node page.
    window.tabs.setCurrentIndex(1)
    window.start_node()
    check(until(lambda: rw.running_pid('node') and rw.read_status('node'), 60), 'Start Node: a node runs, its status read')
    window.refresh()
    check('waiting for a master' in window.node_state.text(), 'the node page says it waits for a master (%s)' % window.node_state.text())
    check(not window.node_start.isEnabled() and window.node_stop.isEnabled(), 'Start Node greyed, Stop Node live')
    # A master on the scene, as Render starts one.
    out = scratch / 'beauty.pfm'
    rw.start('master', ['-in', str(scene), '-out', str(out), '--key', 'rhizome window check', '--nodes', '1', '--wait', '60', '--cell', '64',
                        '--chunk', '4', '--mode', '0', '-threads', '2', '--fresh', '--shaders', 'skip'])
    window.tabs.setCurrentIndex(0)
    check(until(lambda: (rw.read_status('master') or {}).get('frame', {}).get('back', 0) > 0, 300), 'the master renders: chunks come back')
    window.refresh()
    check(window.progress.value() > 0 and not window.render_button.isEnabled() and window.stop_button.isEnabled(),
          'the Render page shows the frame going (%d of %d) and Stop live' % (window.progress.value(), window.progress.maximum()))
    check('chunks' in window.master_log.toPlainText() or 'cells' in window.master_log.toPlainText(), 'the master\'s log shown')
    # The swarm as the master sees it.
    window.tabs.setCurrentIndex(2)
    window.seen_by.setCurrentIndex(0)
    window.refresh()
    roles = sorted(window.table.item(r, 2).text() for r in range(window.table.rowCount()))
    here = [window.table.item(r, 0).text() for r in range(window.table.rowCount()) if '(here)' in window.table.item(r, 0).text()]
    check(roles == ['master', 'node'] and len(here) == 1, 'the Swarm page: the master and the node, this machine marked (%s)' % roles)
    # Approvals and firewall.
    window.tabs.setCurrentIndex(3)
    window.refresh()
    hashes = window.hashes.text()
    check(hashes.count('-') == 0 and len(hashes.split()) >= 4, 'this machine\'s hashes shown, as master and as node')
    check(bool(window.firewall_state.text()), 'the firewall rule\'s state shown (%s)' % window.firewall_state.text())
finally:
    master_stopped, node_stopped = rw.stop('master'), rw.stop('node')
    until(lambda: not rw.running_pid('master') and not rw.running_pid('node'), 20)
    check(not rw.running_pid('master') and not rw.running_pid('node'), 'Stop: the master and the node ended by their PIDs')
print(json.dumps({'failures': len(failures)}))
sys.exit(1 if failures else 0)
