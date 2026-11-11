"""Rhizome (MoonRay menu > Rhizome...): XPU2 across the studio's machines, from Modo.

Four pages:
- Render: the scene (this frame or a range) exported and rendered by this machine as the master, with every node it
  finds; its progress and log, and the pictures in the folder chosen.
- This Machine as a Node: a headless node started here (or stopped), so this machine renders for another's master. It
  keeps running once Modo is closed; this page stops it later.
- Swarm: the machines as the master or the node here sees them, each second.
- Approvals and Firewall: this machine's hashes, the machines waiting to be approved, revoking one, trusting an
  approver, and the Windows Firewall rule that lets the other machines reach this one.

Everything goes through XPU2's command line (moonray_xpu2 rhizome ...) and the status.json each running node or master
writes (RHIZOME_API.md in XPU2's sources). The master's and the node's folders are under %LOCALAPPDATA%\\MoonRayForModo
\\Rhizome: each keeps its machine's key, so an approval lasts; a folder inside the kit would be moved away by the next
install."""
import ctypes
import json
import os
import subprocess
import time
from pathlib import Path

from PySide2 import QtCore, QtGui, QtWidgets

ROLES = ('master', 'node')
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


# ---- the command line and the folders

def base_folder():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MoonRayForModo' / 'Rhizome'


def folder(role):
    """The master's or the node's folder (its key, approvals, status and log)."""
    path = base_folder() / role
    path.mkdir(parents=True, exist_ok=True)
    return path


def executable():
    from . import native
    return native.xpu2_runtime() / 'moonray_xpu2.exe'


def environment():
    """XPU2's environment, as its preview session has it (its libraries and scene classes first)."""
    from . import native
    from .preferences import Preferences
    runtime = native.find_runtime(Preferences().get('runtime') or native.default_runtime())
    env = dict(os.environ)
    env.update({k: str(v) for k, v in native.xpu2_environment(runtime).items()})
    return env


def device_mode():
    """--mode from Device Management: 2 both, 1 the graphics cards, 0 the processor."""
    try:
        from . import native
        return {'both': '2', 'gpu': '1', 'cpu': '0'}[native.xpu2_devices()]
    except Exception:
        return '2'


def run_verb(arguments, timeout=60):
    """moonray_xpu2 rhizome <arguments>, waited for: its exit code and output."""
    try:
        done = subprocess.run([str(executable()), 'rhizome'] + list(arguments), env=environment(), capture_output=True, text=True,
                              timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return done.returncode, (done.stdout or '') + (done.stderr or '')
    except FileNotFoundError:
        return -1, 'This kit has no XPU2 runtime (runtime-xpu2).'
    except subprocess.TimeoutExpired:
        return -2, 'moonray_xpu2 rhizome %s did not answer in %d s.' % (' '.join(arguments), timeout)


def available():
    """Whether this kit's XPU2 has Rhizome (an older one answers rhizome with an error)."""
    code, out = run_verb(['--help'], timeout=20)
    return code == 0 and 'node' in out and 'master' in out


def read_status(role):
    """The running master's or node's status.json (format 1), or None when none runs from its folder."""
    path = folder(role) / 'status.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    if data.get('rhizome') != 1 or time.time() - float(data.get('written', 0)) > 5:
        return None
    return data


def hash_of(role):
    """The master's or the node's hash (made the first time), or ''."""
    code, out = run_verb(['id', '--folder', str(folder(role))], timeout=20)
    line = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else ''
    return line if len(line) == 64 else ''


# ---- processes of our own, by the PID each folder keeps

def _kernel():
    """kernel32 with the handle types right (ctypes' default int cuts a 64-bit handle)."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    return kernel


def _image_of(pid):
    """The executable a process runs, or '' (gone, or not ours to ask)."""
    from ctypes import wintypes
    kernel = _kernel()
    handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ''
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        code = wintypes.DWORD(0)
        if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return ''
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ''
        return buffer.value
    finally:
        kernel.CloseHandle(handle)


def running_pid(role):
    """The PID of the master or node started from this window (this run of Modo or an earlier one), while it runs."""
    try:
        pid = int((folder(role) / 'process.pid').read_text().split()[0])
    except Exception:
        return 0
    image = _image_of(pid)
    same = image and os.path.normcase(os.path.realpath(image)) == os.path.normcase(os.path.realpath(str(executable())))
    return pid if same else 0


def start(role, arguments):
    """moonray_xpu2 rhizome <role> <arguments>, detached: it goes on if Modo closes. Its output in run.log."""
    here = folder(role)
    log = open(here / 'run.log', 'w', encoding='utf-8', errors='replace')
    command = [str(executable()), 'rhizome', role, '--folder', str(here)] + list(arguments)
    flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:
        process = subprocess.Popen(command, env=environment(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, close_fds=True)
    except OSError:
        # Modo's job may not let a process break away: then it ends with Modo.
        process = subprocess.Popen(command, env=environment(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags, close_fds=True)
    log.close()
    (here / 'process.pid').write_text('%d\n' % process.pid)
    return process


def stop(role):
    """Ends the master or node started from this window (by its PID, checked to be this kit's moonray_xpu2.exe). A
    master stopped part way takes its job up again from its checkpoint when started on it again."""
    pid = running_pid(role)
    if not pid:
        return False
    kernel = _kernel()
    handle = kernel.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if not handle:
        return False
    try:
        return bool(kernel.TerminateProcess(handle, 1))
    finally:
        kernel.CloseHandle(handle)


def log_tail(role, lines=200):
    try:
        text = (folder(role) / 'run.log').read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ''
    return '\n'.join(line.replace('MoonRay XPU2 Rhizome: ', '') for line in text.splitlines()[-lines:])


# ---- the scene, exported for the master

def export_job(directory, name, frames, progress=None):
    """The scene as MoonRay reads it, a file a frame (<name>.####.rdla, or <name>.rdla for one frame) in directory/job,
    its render outputs in directory (<name>.####.exr). Returns the -in path and the -out path for the master."""
    import lx
    import modo
    from . import host, rdla
    from .scene_setup import configure, values as scene_values
    held = scene_values()
    job = Path(directory) / 'job'
    job.mkdir(parents=True, exist_ok=True)
    many = len(frames) > 1
    selection = lx.service.Selection()
    now = selection.GetTime()
    fps = float(modo.Scene().fps)
    try:
        for index, frame in enumerate(frames):
            if progress:
                progress(index, len(frames))
            if frame is not None:
                selection.SetTime(frame / fps)
            if held.get('final_motion'):
                from .animation import capture_current
                snapshot = capture_current(held['surface'] == 2)
            else:
                snapshot = host.snapshot(evaluated_geometry=held['surface'] == 2)
            configure(snapshot, held)
            stem = '%s.%04d' % (name, frame) if many else name
            text = rdla.scene_text(snapshot, snapshot['width'], snapshot['height'], held['samples'], held['environment'],
                                   str(Path(directory) / (stem + '.exr')))
            (job / (stem + '.rdla')).write_text(text, encoding='utf-8')
    finally:
        selection.SetTime(now)
    scene = job / ((name + '.####.rdla') if many else (name + '.rdla'))
    out = job / ((name + '.####.pfm') if many else (name + '.pfm'))
    return scene, out


# ---- the window

class Window(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window)
        self.setWindowTitle('Rhizome')
        self.resize(900, 640)
        self.settings = QtCore.QSettings('MoonRayForModo', 'Rhizome')
        self.master_process = None
        layout = QtWidgets.QVBoxLayout(self)

        # The rhizome key: shared by every machine of the studio's swarm, never sent.
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel('Rhizome key'))
        self.key = QtWidgets.QLineEdit(str(self.settings.value('key', '')))
        self.key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key.setToolTip('The same words on every machine of the swarm. Machines with another key never meet. It is kept in '
                            'this user\'s settings on this machine and never sent over the network.')
        self.key.editingFinished.connect(lambda: self.settings.setValue('key', self.key.text()))
        show = QtWidgets.QCheckBox('Show')
        show.toggled.connect(lambda on: self.key.setEchoMode(QtWidgets.QLineEdit.Normal if on else QtWidgets.QLineEdit.Password))
        top.addWidget(self.key, 1)
        top.addWidget(show)
        layout.addLayout(top)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._render_page(), 'Render')
        self.tabs.addTab(self._node_page(), 'This Machine as a Node')
        self.tabs.addTab(self._swarm_page(), 'Swarm')
        self.tabs.addTab(self._approvals_page(), 'Approvals and Firewall')
        layout.addWidget(self.tabs, 1)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        if not available():
            self.status.setText('This kit\'s XPU2 (runtime-xpu2) has no Rhizome: install a kit whose XPU2 has it.')
            self.tabs.setEnabled(False)
        self.refresh()

    # -- Render
    def _render_page(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        frames = QtWidgets.QHBoxLayout()
        self.this_frame = QtWidgets.QRadioButton('This frame')
        self.range = QtWidgets.QRadioButton('Frames')
        self.first, self.last, self.step = QtWidgets.QSpinBox(), QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        for box in (self.first, self.last):
            box.setRange(-100000, 100000)
        self.step.setRange(1, 1000)
        self.step.setPrefix('every ')
        frames.addWidget(self.this_frame)
        frames.addWidget(self.range)
        frames.addWidget(self.first)
        frames.addWidget(QtWidgets.QLabel('to'))
        frames.addWidget(self.last)
        frames.addWidget(self.step)
        frames.addStretch(1)
        self.this_frame.setChecked(str(self.settings.value('render/range', 'false')) != 'true')
        self.range.setChecked(not self.this_frame.isChecked())
        form.addRow('Render', frames)
        where = QtWidgets.QHBoxLayout()
        self.output = QtWidgets.QLineEdit(str(self.settings.value('render/folder', str(Path.home() / 'Rhizome'))))
        browse = QtWidgets.QPushButton('Browse...')
        browse.clicked.connect(self._browse)
        where.addWidget(self.output, 1)
        where.addWidget(browse)
        form.addRow('Pictures in', where)
        self.nodes = QtWidgets.QSpinBox()
        self.nodes.setRange(0, 1000)
        self.nodes.setSpecialValueText('every node found')
        self.nodes.setValue(int(self.settings.value('render/nodes', 0)))
        self.nodes.setToolTip('Start once this many nodes are ready. "Every node found": once every node found is ready and no new one '
                              'has joined for 3 seconds.')
        form.addRow('Wait for', self.nodes)
        self.wait = QtWidgets.QSpinBox()
        self.wait.setRange(5, 3600)
        self.wait.setSuffix(' s')
        self.wait.setValue(int(self.settings.value('render/wait', 30)))
        self.wait.setToolTip('The longest wait for the nodes: then the first frame starts with those ready.')
        form.addRow('At most', self.wait)
        self.addresses = QtWidgets.QLineEdit(str(self.settings.value('render/addresses', '')))
        self.addresses.setPlaceholderText('host:port, host:port (machines discovery cannot reach)')
        form.addRow('Nodes by address', self.addresses)
        self.scan = QtWidgets.QLineEdit(str(self.settings.value('render/scan', '')))
        self.scan.setPlaceholderText('10.8.0.0/24 (a VPN or a routed network), or * for each of this machine\'s networks')
        form.addRow('Look for nodes in', self.scan)
        self.approved_only = QtWidgets.QCheckBox('Only machines approved (Approvals and Firewall)')
        self.approved_only.setChecked(str(self.settings.value('render/approved', 'false')) == 'true')
        form.addRow('', self.approved_only)
        sizes = QtWidgets.QHBoxLayout()
        self.cell = QtWidgets.QComboBox()
        for px in (64, 128, 256, 512):
            self.cell.addItem('%d px' % px, px)
        self.cell.setCurrentIndex(max(0, self.cell.findData(int(self.settings.value('render/cell', 256)))))
        self.chunk = QtWidgets.QSpinBox()
        self.chunk.setRange(1, 4096)
        self.chunk.setValue(int(self.settings.value('render/chunk', 16)))
        sizes.addWidget(QtWidgets.QLabel('Cells'))
        sizes.addWidget(self.cell)
        sizes.addWidget(QtWidgets.QLabel('Samples a piece of work'))
        sizes.addWidget(self.chunk)
        sizes.addStretch(1)
        form.addRow('Work', sizes)
        buttons = QtWidgets.QHBoxLayout()
        self.render_button = QtWidgets.QPushButton('Render on the Swarm')
        self.render_button.clicked.connect(self.render)
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.stop_button.clicked.connect(self.stop_render)
        self.open_button = QtWidgets.QPushButton('Open Pictures Folder')
        self.open_button.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.output.text())))
        buttons.addWidget(self.render_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(self.open_button)
        form.addRow(buttons)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setFormat('%p%')
        form.addRow('Frame', self.progress)
        self.master_log = QtWidgets.QPlainTextEdit()
        self.master_log.setReadOnly(True)
        self.master_log.setMaximumBlockCount(400)
        form.addRow(self.master_log)
        self._scene_range()
        return page

    def _scene_range(self):
        try:
            import modo
            render = modo.Scene().renderItem
            self.first.setValue(int(round(float(render.channel('first').get()))))
            self.last.setValue(int(round(float(render.channel('last').get()))))
            self.step.setValue(max(1, int(round(float(render.channel('step').get())))))
        except Exception:
            pass

    def _browse(self):
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, 'Pictures in', self.output.text())
        if chosen:
            self.output.setText(chosen)

    def _key(self):
        key = self.key.text().strip()
        if not key:
            self.status.setText('Give the rhizome key first: the same words on every machine of the swarm.')
        else:
            self.settings.setValue('key', key)
        return key

    def render(self):
        key = self._key()
        if not key:
            return
        if running_pid('master'):
            self.status.setText('A master started from here is rendering. Stop it first.')
            return
        import modo
        import lx
        directory = Path(self.output.text().strip() or str(Path.home() / 'Rhizome'))
        name = Path(modo.Scene().filename).stem if getattr(modo.Scene(), 'filename', None) else 'scene'
        if self.range.isChecked():
            frames = list(range(self.first.value(), self.last.value() + 1, self.step.value()))
            if not frames:
                self.status.setText('The frame range is empty.')
                return
        else:
            fps = float(modo.Scene().fps)
            frames = [int(round(lx.service.Selection().GetTime() * fps))]
        for key_name, value in (('render/range', 'true' if self.range.isChecked() else 'false'), ('render/folder', str(directory)),
                                ('render/nodes', self.nodes.value()), ('render/wait', self.wait.value()),
                                ('render/addresses', self.addresses.text()), ('render/scan', self.scan.text()),
                                ('render/approved', 'true' if self.approved_only.isChecked() else 'false'),
                                ('render/cell', self.cell.currentData()), ('render/chunk', self.chunk.value())):
            self.settings.setValue(key_name, value)

        def progress(index, count):
            self.status.setText('Exporting the scene: frame %d of %d...' % (index + 1, count))
            QtWidgets.QApplication.processEvents()
        try:
            scene, out = export_job(directory, name, frames, progress)
        except Exception as exc:
            self.status.setText('The scene could not be exported: %s' % exc)
            return
        arguments = ['-in', str(scene), '-out', str(out), '--key', key, '--wait', str(self.wait.value()), '--cell', str(self.cell.currentData()),
                     '--chunk', str(self.chunk.value()), '--mode', device_mode(), '--fresh', '--shaders', 'skip']
        if len(frames) > 1:
            arguments += ['--frames', '%d-%d:%d' % (frames[0], frames[-1], self.step.value())]
        if self.nodes.value():
            arguments += ['--nodes', str(self.nodes.value())]
        for address in (a.strip() for a in self.addresses.text().split(',')):
            if address:
                arguments += ['--node', address]
        scan = self.scan.text().strip()
        if scan == '*':
            arguments += ['--scan']
        elif scan:
            arguments += ['--scan', scan.replace(' ', '')]
        if self.approved_only.isChecked():
            arguments += ['--approve']
        try:
            self.master_process = start('master', arguments)
        except Exception as exc:
            self.status.setText('The master did not start: %s' % exc)
            return
        self.status.setText('Rendering %d frame%s on the swarm; pictures in %s' % (len(frames), '' if len(frames) == 1 else 's', directory))

    def stop_render(self):
        if stop('master'):
            self.status.setText('The master is stopped. Started again on the same frames, it takes the job up where it was.')

    # -- This machine as a node
    def _node_page(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.node_state = QtWidgets.QLabel()
        form.addRow('Node', self.node_state)
        self.node_threads = QtWidgets.QSpinBox()
        self.node_threads.setRange(0, 1024)
        self.node_threads.setSpecialValueText('every processor thread')
        self.node_threads.setValue(int(self.settings.value('node/threads', 0)))
        form.addRow('Threads', self.node_threads)
        self.idle = QtWidgets.QSpinBox()
        self.idle.setRange(0, 86400)
        self.idle.setSpecialValueText('always')
        self.idle.setSuffix(' s without keyboard or mouse')
        self.idle.setValue(int(self.settings.value('node/idle', 0)))
        form.addRow('Render', self.idle)
        hours = QtWidgets.QHBoxLayout()
        self.use_hours = QtWidgets.QCheckBox('Only from')
        self.use_hours.setChecked(str(self.settings.value('node/use_hours', 'false')) == 'true')
        self.hour_from, self.hour_to = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        for box, held in ((self.hour_from, 19), (self.hour_to, 8)):
            box.setRange(0, 23)
            box.setSuffix(':00')
            box.setValue(int(self.settings.value('node/' + ('from' if box is self.hour_from else 'to'), held)))
        hours.addWidget(self.use_hours)
        hours.addWidget(self.hour_from)
        hours.addWidget(QtWidgets.QLabel('to'))
        hours.addWidget(self.hour_to)
        hours.addStretch(1)
        form.addRow('Hours', hours)
        self.busy = QtWidgets.QSpinBox()
        self.busy.setRange(0, 1024)
        self.busy.setSpecialValueText('step back')
        self.busy.setSuffix(' threads')
        self.busy.setValue(int(self.settings.value('node/busy', 0)))
        self.busy.setToolTip('While the machine is in use: step back (its work goes to the others), or go on with this many threads.')
        form.addRow('While in use', self.busy)
        buttons = QtWidgets.QHBoxLayout()
        self.node_start = QtWidgets.QPushButton('Start Node')
        self.node_start.clicked.connect(self.start_node)
        self.node_stop = QtWidgets.QPushButton('Stop Node')
        self.node_stop.clicked.connect(lambda: stop('node') and self.status.setText('The node here is stopped.'))
        buttons.addWidget(self.node_start)
        buttons.addWidget(self.node_stop)
        buttons.addStretch(1)
        form.addRow(buttons)
        note = QtWidgets.QLabel('The node renders for whichever master of the swarm finds it, with the devices Device Management '
                                'chooses. It goes on running once Modo is closed; Stop Node stops it.')
        note.setWordWrap(True)
        form.addRow(note)
        self.node_log = QtWidgets.QPlainTextEdit()
        self.node_log.setReadOnly(True)
        self.node_log.setMaximumBlockCount(400)
        form.addRow(self.node_log)
        return page

    def start_node(self):
        key = self._key()
        if not key or running_pid('node'):
            return
        for key_name, value in (('node/threads', self.node_threads.value()), ('node/idle', self.idle.value()),
                                ('node/use_hours', 'true' if self.use_hours.isChecked() else 'false'), ('node/from', self.hour_from.value()),
                                ('node/to', self.hour_to.value()), ('node/busy', self.busy.value())):
            self.settings.setValue(key_name, value)
        arguments = ['--key', key, '--mode', device_mode(), '--shaders', 'skip']
        if self.node_threads.value():
            arguments += ['-threads', str(self.node_threads.value())]
        if self.idle.value():
            arguments += ['--when-idle', str(self.idle.value())]
        if self.use_hours.isChecked():
            arguments += ['--hours', '%d-%d' % (self.hour_from.value(), self.hour_to.value())]
        if self.busy.value():
            arguments += ['--busy-threads', str(self.busy.value())]
        try:
            start('node', arguments)
            self.status.setText('The node here is starting.')
        except Exception as exc:
            self.status.setText('The node did not start: %s' % exc)

    # -- Swarm
    def _swarm_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('As seen by'))
        self.seen_by = QtWidgets.QComboBox()
        self.seen_by.addItem('the master here', 'master')
        self.seen_by.addItem('the node here', 'node')
        row.addWidget(self.seen_by)
        self.swarm_head = QtWidgets.QLabel()
        row.addWidget(self.swarm_head, 1)
        layout.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(['Machine', 'Address', 'Role', 'State', 'Tier', 'Ms/s', 'Round trip', 'Pieces of work',
                                              'Memory given', 'GPU programs'])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)
        return page

    def _fill_swarm(self, data):
        rows = data.get('members', []) if data else []
        self.table.setRowCount(len(rows))
        for r, m in enumerate(rows):
            given = (int(m.get('ramGiven', 0)) + int(m.get('vramGiven', 0))) / 2 ** 30
            cells = [m.get('hash', '')[:12] + (' (here)' if m.get('self') else ''), m.get('address', ''), m.get('role', ''), m.get('state', ''),
                     m.get('tier', ''), '%.2f' % (float(m.get('rate', 0)) / 1e6) if m.get('rate') else '-',
                     '%.1f ms' % (float(m.get('rtt', 0)) * 1000) if float(m.get('rtt', -1)) > 0 else '-', str(m.get('chunks', 0)),
                     '%.1f GB' % given if given else '-', m.get('gpuPrograms', '') or '-']
            for c, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                item.setData(QtCore.Qt.UserRole, m.get('hash', ''))
                self.table.setItem(r, c, item)
        if not data:
            self.swarm_head.setText('Not running here.')
        else:
            frame = data.get('frame', {})
            text = data.get('job') or 'waiting for a job'
            if frame.get('chunks'):
                text += ': %d of %d pieces of work back' % (frame.get('back', 0), frame.get('chunks', 0))
            self.swarm_head.setText(text)

    # -- Approvals and firewall
    def _approvals_page(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.hashes = QtWidgets.QLabel('...')
        self.hashes.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        form.addRow('This machine', self.hashes)
        self.waiting = QtWidgets.QListWidget()
        self.waiting.setToolTip('Machines asking to join a master started from here with "Only machines approved".')
        form.addRow('Waiting', self.waiting)
        approve_row = QtWidgets.QHBoxLayout()
        approve = QtWidgets.QPushButton('Approve')
        approve.clicked.connect(self.approve)
        self.as_approver = QtWidgets.QCheckBox('As an approver too (it may approve others, and take over as master)')
        approve_row.addWidget(approve)
        approve_row.addWidget(self.as_approver)
        approve_row.addStretch(1)
        form.addRow(approve_row)
        other = QtWidgets.QHBoxLayout()
        self.other_hash = QtWidgets.QLineEdit()
        self.other_hash.setPlaceholderText('A machine\'s hash (64 characters; rhizome id on it, or the Swarm page)')
        revoke = QtWidgets.QPushButton('Revoke')
        revoke.clicked.connect(lambda: self._identity_verb('revoke', self.other_hash.text().strip()))
        trust = QtWidgets.QPushButton('Trust as Approver')
        trust.clicked.connect(lambda: self._identity_verb('trust', self.other_hash.text().strip()))
        other.addWidget(self.other_hash, 1)
        other.addWidget(revoke)
        other.addWidget(trust)
        form.addRow('Another machine', other)
        firewall = QtWidgets.QHBoxLayout()
        self.firewall_state = QtWidgets.QLabel()
        self.firewall_state.setWordWrap(True)
        add = QtWidgets.QPushButton('Add Rule...')
        add.setToolTip('Windows asks for an administrator, then one inbound rule lets this XPU2 take connections on private and domain networks.')
        add.clicked.connect(lambda: self._firewall([]))
        remove = QtWidgets.QPushButton('Remove Rule...')
        remove.clicked.connect(lambda: self._firewall(['--remove']))
        firewall.addWidget(self.firewall_state, 1)
        firewall.addWidget(add)
        firewall.addWidget(remove)
        form.addRow('Firewall', firewall)
        self._identity_shown = False
        return page

    def _show_identity(self):
        master, node = hash_of('master'), hash_of('node')
        self.hashes.setText('as master  %s\nas node      %s' % (master or '-', node or '-'))
        code, out = run_verb(['firewall', '--check'], timeout=20)
        self.firewall_state.setText(out.strip().splitlines()[0].replace('MoonRay XPU2 Rhizome: ', '') if out.strip() else '')
        self._identity_shown = True

    def approve(self):
        item = self.waiting.currentItem()
        if not item:
            self.status.setText('Choose a machine waiting to be approved.')
            return
        extra = ['--approver'] if self.as_approver.isChecked() else []
        self._identity_verb('approve', item.data(QtCore.Qt.UserRole), extra)

    def _identity_verb(self, verb, subject, extra=()):
        if len(subject) != 64:
            self.status.setText('A machine\'s hash is 64 characters.')
            return
        # The master's folder holds the approvals a master started from here admits by; the node's trusts the same approvers.
        outs = []
        for role in (('master',) if verb == 'approve' else ROLES):
            code, out = run_verb([verb, subject, '--folder', str(folder(role))] + list(extra))
            outs.append(out.strip().splitlines()[0] if out.strip() else ('exit %d' % code))
        self.status.setText(' / '.join(outs))

    def _firewall(self, extra):
        # Windows' administrator prompt comes up; the answer is waited for away from the window's own thread.
        process = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment()
        for k, v in environment().items():
            env.insert(k, v)
        process.setProcessEnvironment(env)
        process.finished.connect(lambda *a: (self._show_identity(), process.deleteLater()))
        process.start(str(executable()), ['rhizome', 'firewall'] + extra)
        self.status.setText('Windows asks for an administrator to change the firewall rule...')

    # -- each second
    def refresh(self):
        if not self.tabs.isEnabled():
            return
        master = read_status('master')
        master_pid = running_pid('master')
        self.render_button.setEnabled(not master_pid)
        self.stop_button.setEnabled(bool(master_pid))
        frame = master.get('frame', {}) if master else {}
        self.progress.setMaximum(max(1, int(frame.get('chunks', 0))))
        self.progress.setValue(int(frame.get('back', 0)))
        if self.tabs.currentIndex() == 0:
            text = log_tail('master')
            if text != self.master_log.toPlainText():
                self.master_log.setPlainText(text)
                self.master_log.moveCursor(QtGui.QTextCursor.End)
        if self.master_process is not None and self.master_process.poll() is not None:
            code = self.master_process.returncode
            self.master_process = None
            self.status.setText('Done: the pictures are in %s.' % self.output.text() if code == 0 else
                                'The master stopped (exit %d): its log says why.' % code)
        node_pid = running_pid('node')
        node = read_status('node')
        self.node_start.setEnabled(not node_pid)
        self.node_stop.setEnabled(bool(node_pid))
        if node_pid:
            state = 'running (process %d)' % node_pid
            if node:
                state += ', ' + ('rendering for master %s' % node['master'][:12] if node.get('master') else 'waiting for a master to find it')
        else:
            state = 'not running'
        self.node_state.setText(state)
        if self.tabs.currentIndex() == 1:
            text = log_tail('node')
            if text != self.node_log.toPlainText():
                self.node_log.setPlainText(text)
                self.node_log.moveCursor(QtGui.QTextCursor.End)
        if self.tabs.currentIndex() == 2:
            self._fill_swarm(master if self.seen_by.currentData() == 'master' else node)
        if self.tabs.currentIndex() == 3:
            if not self._identity_shown:
                self._show_identity()
            hashes = [m['hash'] for m in (master or {}).get('members', []) if m.get('role') == 'waiting']
            shown = [self.waiting.item(i).data(QtCore.Qt.UserRole) for i in range(self.waiting.count())]
            if hashes != shown:
                self.waiting.clear()
                for h in hashes:
                    item = QtWidgets.QListWidgetItem(h)
                    item.setData(QtCore.Qt.UserRole, h)
                    self.waiting.addItem(item)

    def closeEvent(self, event):
        # The master and the node go on: the window only shows them.
        self.timer.stop()
        super().closeEvent(event)

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)


_window = None


def show(parent=None):
    global _window
    if _window is None:
        _window = Window(parent)
    _window.show()
    _window.raise_()
    _window.activateWindow()
