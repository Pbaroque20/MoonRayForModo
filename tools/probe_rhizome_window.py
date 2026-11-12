# python
"""Isolated GUI test: the Rhizome window in Modo (MoonRay > Rhizome: Decentralized Rendering).

A small scene is opened at 320 x 180, the window opened by its menu command, a node started from its node page, and
frames 1-2 rendered with its Render button: the scene exported by the window itself, a master started on it, the
node taking part. Each page is pictured; the pictures written, the master's log and what each page said go into
test-results/rhizome-modo/result.json. The node is stopped and Modo quits.

The machines listen on 127.0.0.1 alone (no Windows Firewall question), the node given the master's address; the
Rhizome folders are the test's own (test-results/rhizome-modo/folders), not this user's."""
import json
import os
import pathlib
import time
import traceback

import lx
import modo
from PySide2 import QtCore, QtWidgets

# (Modo runs a probe without a reliable __file__: the worktree by its path, as the other probes do.)
here = pathlib.Path(r'C:\Users\Raphael Tobar\mrfm-rhizome-kit')
steps_file = here / 'test-results' / 'rhizome-modo-steps.txt'


def step(text):
    # Each step written at once and closed: a crash leaves the last one said.
    with open(str(steps_file), 'a', encoding='utf-8') as f:
        f.write('%.1f %s\n' % (time.time(), text))


out = here / 'test-results' / 'rhizome-modo'
pictures = out / 'pictures'
scene_file = pathlib.Path(os.environ.get('MOONRAY_PROBE_SCENE', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\checker-variants\checker_variants.lxo'))
out.mkdir(parents=True, exist_ok=True)
result = {'checks': [], 'notes': []}
state = {'began': time.time(), 'render_began': 0.0, 'pictured_running': False}


def check(ok, what):
    result['checks'].append({'ok': bool(ok), 'what': what})


def save():
    result['failures'] = sum(1 for c in result['checks'] if not c['ok'])
    (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


def grab(window, name):
    try:
        window.grab().save(str(out / (name + '.png')))
    except Exception as exc:
        result['notes'].append('picture %s: %s' % (name, exc))


def finish():
    try:
        from moonray_modo import rhizome_window as rw
        result['stopped'] = {'master': rw.stop('master'), 'node': rw.stop('node')}
    except Exception:
        result['notes'].append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!!app.quit'))


def guarded(step):
    def run():
        try:
            step()
        except Exception:
            result['notes'].append(traceback.format_exc())
            finish()
    return run


def begin():
    # The last run's pictures and job folder gone (the window makes job\ inside the pictures folder).
    import shutil
    shutil.rmtree(str(pictures), ignore_errors=True)
    shutil.rmtree(str(out / 'folders'), ignore_errors=True)
    step('begin: opening the scene')
    lx.eval('!!scene.open {%s}' % scene_file)
    step('scene open')
    # Through Modo's own command (a channel written directly outside a command is refused).
    render = modo.Scene().renderItem
    lx.eval('item.channel resX 320 item:{%s}' % render.id)
    lx.eval('item.channel resY 180 item:{%s}' % render.id)
    step('render size %s x %s' % (render.channel('resX').get(), render.channel('resY').get()))
    from moonray_modo import rhizome_window as rw
    rw.base_folder = lambda: out / 'folders'
    # The window's own calls logged too: its refresh (the first ten) and each moonray_xpu2 command.
    refresh, verb, counted = rw.Window.refresh, rw.run_verb, {'n': 0}

    def logged_refresh(self):
        counted['n'] += 1
        if counted['n'] <= 10:
            step('refresh %d on page %d' % (counted['n'], self.tabs.currentIndex()))
        refresh(self)
        if counted['n'] <= 10:
            step('refresh %d done' % counted['n'])
    rw.Window.refresh = logged_refresh

    def logged_verb(arguments, timeout=60):
        step('run_verb %s' % ' '.join(arguments))
        answer = verb(arguments, timeout)
        step('run_verb done: %d' % answer[0])
        return answer
    rw.run_verb = logged_verb
    started = rw.start
    rw.start = lambda role, arguments: started(role, list(arguments) + ['--bind', '127.0.0.1', '--no-discovery'] +
                                               (['--master', '127.0.0.1:47110'] if role == 'node' else []))
    # The menu's command.
    step('moonray.rhizome')
    lx.eval('moonray.rhizome')
    window = rw._window
    step('window open: %s' % (window is not None))
    check(window is not None and window.isVisible(), 'moonray.rhizome opens the window')
    check(window.tabs.isEnabled(), 'the kit\'s XPU2 has Rhizome (%s)' % window.status.text())
    window.key.setText('rhizome modo probe')
    window.range.setChecked(True)
    window.first.setValue(1)
    window.last.setValue(2)
    window.step.setValue(1)
    window.output.setText(str(pictures))
    window.nodes.setValue(1)
    window.wait.setValue(90)
    window.cell.setCurrentIndex(window.cell.findData(64))
    window.chunk.setValue(8)
    window.node_threads.setValue(4)
    step('fields set')
    grab(window, '1-render-page')
    step('render page pictured')
    window.tabs.setCurrentIndex(1)
    step('node page shown')
    window.start_node()
    step('node started: %s' % window.status.text())
    QtCore.QTimer.singleShot(1000, guarded(lambda: node_up(window)))


def node_up(window):
    from moonray_modo import rhizome_window as rw
    if not (rw.running_pid('node') and rw.read_status('node')):
        if time.time() - state['began'] > 120:
            check(False, 'the node starts from the node page')
            return finish()
        return QtCore.QTimer.singleShot(1000, guarded(lambda: node_up(window)))
    window.refresh()
    check(True, 'the node starts from the node page')
    result['node_page'] = window.node_state.text()
    grab(window, '2-node-page')
    window.tabs.setCurrentIndex(0)
    state['render_began'] = time.time()
    step('render pressed')
    window.render()
    step('render returned: %s' % window.status.text())
    result['after_render_pressed'] = window.status.text()
    check(window.master_process is not None, 'Render exports the scene and starts the master (%s)' % window.status.text())
    QtCore.QTimer.singleShot(2000, guarded(lambda: rendering(window)))


def rendering(window):
    from moonray_modo import rhizome_window as rw
    window.refresh()
    master = rw.read_status('master')
    if master and not state['pictured_running'] and master.get('frame', {}).get('back', 0) > 0:
        state['pictured_running'] = True
        result['render_page_running'] = {'progress': [window.progress.value(), window.progress.maximum()], 'status': window.status.text()}
        grab(window, '3-render-page-running')
        window.tabs.setCurrentIndex(2)
        window.refresh()
        result['swarm'] = [[window.table.item(r, c).text() for c in (0, 2, 3, 7, 9)] for r in range(window.table.rowCount())]
        grab(window, '4-swarm-page')
        window.tabs.setCurrentIndex(0)
    if window.master_process is not None:
        if time.time() - state['render_began'] > 900:
            check(False, 'the render finishes within 15 minutes')
            return finish()
        return QtCore.QTimer.singleShot(2000, guarded(lambda: rendering(window)))
    result['render_seconds'] = round(time.time() - state['render_began'], 1)
    result['render_status'] = window.status.text()
    result['master_log'] = rw.log_tail('master', 40).splitlines()
    written = sorted(p.name for p in pictures.glob('*') if p.is_file())
    result['pictures'] = written
    check(window.status.text().startswith('Done'), 'the master finishes: %s' % window.status.text())
    check(any(n.endswith('.0001.exr') for n in written) and any(n.endswith('.0002.exr') for n in written),
          'frames 1 and 2 written as the scene\'s outputs (%s)' % ', '.join(written))
    swarm = result.get('swarm', [])
    check(any(row[1] == 'node' for row in swarm) and any(row[1] == 'master' for row in swarm),
          'the Swarm page showed the master and the node while it rendered')
    log = '\n'.join(result['master_log'])
    check('chunks by node' in log, 'the master\'s log shows the frames done')
    grab(window, '5-render-page-done')
    window.tabs.setCurrentIndex(3)
    window.refresh()
    result['approvals'] = {'hashes': window.hashes.text(), 'firewall': window.firewall_state.text()}
    check(window.hashes.text().count('-') == 0, 'the Approvals page shows this machine\'s hashes')
    grab(window, '6-approvals-page')
    finish()


step('probe loaded')
QtCore.QTimer.singleShot(4000, guarded(begin))
