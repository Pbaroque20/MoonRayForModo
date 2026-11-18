"""LXO to RDL: Modo scenes on disk written as MoonRay scenes in the background, by Modo's command-line engine (modo_cl) and
the kit's scripts/export_moonray.py, one modo_cl for each scene, a few at a time. The scene open in Modo is not touched,
and Modo goes on working. MoonRay > Convert LXO to RDL is its window (lxo_convert_window.py); the kit's bin/lxo2rdl.exe
does the same from the command line, Modo closed or not (native-port/lxo2rdl.cpp).

The RDL is what Export as MoonRay Scene writes (scene_export.export), each scene by its own MoonRay render settings."""
import re
import tempfile
from pathlib import Path

from PySide2 import QtCore

# The export's formats, as Export as MoonRay Scene names them, and the file each writes (split: both, by one name).
from .scene_export import FORMATS
SUFFIX = {'rdla': '.rdla', 'rdlb': '.rdlb', 'split': '.rdla'}
WROTE = re.compile(r'Wrote (.+?\.rdl[ab])\s*$')
NOTICE = re.compile(r'Notice: (.+?)\s*$')


def kit_folder():
    return Path(__file__).resolve().parents[2]


def script():
    """The kit's export script, by its full path: modo_cl runs it as it finds it."""
    return kit_folder() / 'scripts' / 'export_moonray.py'


def modo_cl():
    """Modo's command-line engine, beside the Modo running this (else the usual place for Modo 16.1); None where there
    is none."""
    try:
        import ctypes
        held = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetModuleFileNameW(None, held, len(held)):
            found = Path(held.value).with_name('modo_cl.exe')
            if found.is_file():
                return found
    except (AttributeError, OSError):
        pass
    for found in sorted(Path('C:/Program Files').glob('Modo*/modo/modo_cl.exe'), reverse=True):
        return found
    return None


def lxo_files(paths):
    """The Modo scenes among paths: files ending in .lxo, and those in folders, their subfolders too, each once, in order."""
    found, seen = [], set()
    for path in map(Path, paths):
        for scene in (sorted(path.rglob('*.lxo'), key=lambda p: str(p).lower()) if path.is_dir() else [path]):
            key = str(scene.resolve()).lower()
            if scene.suffix.lower() == '.lxo' and scene.is_file() and key not in seen:
                seen.add(key)
                found.append(scene.resolve())
    return found


def targets(scenes, kind, folder=None):
    """Where each scene is written: beside it, or in folder, by its name. Two scenes of the same name going to one
    folder are told apart by a number (shot.rdla, shot_2.rdla), so that neither is written over the other."""
    suffix, taken, placed = SUFFIX[kind], set(), []
    for scene in scenes:
        where = Path(folder) if folder else Path(scene).parent
        name, count = Path(scene).stem, 1
        target = where / (name + suffix)
        while str(target).lower() in taken:
            count += 1
            target = where / ('%s_%d%s' % (name, count, suffix))
        taken.add(str(target).lower())
        placed.append(target)
    return placed


def command_text(scene, target, kind, frames=False, outputs=True, collect=False, report=None):
    """What modo_cl is given: the export, then quit. Quotes around the paths, not braces (modo_cl misreads a brace
    around a path that holds a space); the script by its full path in braces. report: the file the script says what it
    wrote in (modo_cl does not pass on what a script says)."""
    words = ['format=' + kind, 'outputs=%d' % bool(outputs), 'collect=%d' % bool(collect)] + (['frames'] if frames else [])
    if report is not None:
        words.append('"report=%s"' % Path(report))
    return '@{%s} "%s" "%s" %s\napp.quit\n' % (script(), Path(scene), Path(target), ' '.join(words))


def read_report(path):
    """What the export script said it did (export_moonray.py, report=): the files written, the notices, and the error
    that stopped it, if one did."""
    written, notices, errors = [], [], []
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = []
    for line in lines:
        kind, _, text = line.partition('\t')
        {'wrote': written, 'notice': notices, 'error': errors}.get(kind, []).append(text)
    return written, notices, errors


class Batch(QtCore.QObject):
    """Scenes converted in the background, at most `at_once` modo_cl at a time. Each job is a dict: scene, target, state
    (waiting, converting, done, failed, stopped), written (the files), notices, log (what modo_cl said)."""
    changed = QtCore.Signal(int)
    finished = QtCore.Signal()

    def __init__(self, scenes, kind='rdla', folder=None, frames=False, outputs=True, collect=False, at_once=1, parent=None):
        super().__init__(parent)
        self.engine = modo_cl()
        self.options = dict(kind=kind, frames=frames, outputs=outputs, collect=collect)
        self.jobs = [dict(scene=Path(s), target=t, state='waiting', written=[], notices=[], log='')
                     for s, t in zip(scenes, targets(scenes, kind, folder))]
        self.at_once = max(1, int(at_once))
        self.running = {}
        self.stopping = False
        self.folder = Path(tempfile.mkdtemp(prefix='moonray-lxo-'))

    def start(self):
        if self.engine is None:
            for index, job in enumerate(self.jobs):
                job.update(state='failed', log="Modo's command-line engine (modo_cl.exe) was not found beside Modo.")
                self.changed.emit(index)
            self.finished.emit()
            return
        self._next()

    def stop(self):
        """The conversions under way ended, the ones waiting left out; what was written so far stays."""
        self.stopping = True
        for index, job in enumerate(self.jobs):
            if job['state'] == 'waiting':
                job['state'] = 'stopped'
                self.changed.emit(index)
        for process in list(self.running.values()):
            process.kill()

    def counts(self):
        held = {}
        for job in self.jobs:
            held[job['state']] = held.get(job['state'], 0) + 1
        return held

    def _next(self):
        while not self.stopping and len(self.running) < self.at_once:
            index = next((i for i, job in enumerate(self.jobs) if job['state'] == 'waiting'), None)
            if index is None:
                break
            self._begin(index)
        if not self.running:
            # Over: its command files and reports go with it.
            import shutil
            shutil.rmtree(self.folder, ignore_errors=True)
            self.finished.emit()

    def _begin(self, index):
        job = self.jobs[index]
        commands = self.folder / ('%d.txt' % index)
        job['report'] = self.folder / ('%d.report.txt' % index)
        commands.write_text(command_text(job['scene'], job['target'], report=job['report'], **self.options), encoding='utf-8')
        job['target'].parent.mkdir(parents=True, exist_ok=True)
        process = QtCore.QProcess(self)
        process.setProgram(str(self.engine))
        process.setWorkingDirectory(str(self.folder))
        process.setStandardInputFile(str(commands))
        process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda index=index, process=process: self._read(index, process))
        # Modo's PySide2 hands finished the exit code alone (its finished(int) form): the status is not asked for.
        process.finished.connect(lambda code, *rest, index=index, process=process: self._ended(index, process, code))
        process.errorOccurred.connect(lambda error, index=index, process=process: self._failed_to_start(index, process, error))
        self.running[index] = process
        job['state'] = 'converting'
        self.changed.emit(index)
        process.start()

    def _read(self, index, process):
        job = self.jobs[index]
        text = bytes(process.readAllStandardOutput()).decode('utf-8', errors='replace')
        job['log'] = (job['log'] + text)[-200000:]
        for line in text.splitlines():
            wrote, notice = WROTE.search(line), NOTICE.search(line)
            if wrote and wrote.group(1) not in job['written']:
                job['written'].append(wrote.group(1))
            elif notice and notice.group(1) not in job['notices']:
                job['notices'].append(notice.group(1))
        self.changed.emit(index)

    def _ended(self, index, process, code):
        if self.running.pop(index, None) is None:
            return
        self._read(index, process)
        job = self.jobs[index]
        written, notices, errors = read_report(job['report'])
        job['written'] = written or job['written']
        job['notices'] = notices or job['notices']
        if errors:
            job['log'] = '\n'.join(errors) + '\n\n' + job['log']
        made = [p for p in job['written'] if Path(p).is_file()]
        job['state'] = 'stopped' if self.stopping else ('done' if made and len(made) == len(job['written']) else 'failed')
        self.changed.emit(index)
        process.deleteLater()
        self._next()

    def _failed_to_start(self, index, process, error):
        if error == QtCore.QProcess.FailedToStart and self.running.pop(index, None) is not None:
            job = self.jobs[index]
            job.update(state='failed', log=job['log'] + "\nModo's command-line engine could not be started: " + process.errorString())
            self.changed.emit(index)
            process.deleteLater()
            self._next()
