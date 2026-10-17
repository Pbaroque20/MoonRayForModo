"""The MoonRay Terminal window: the programs the plugin runs, their commands, what they print and how they end
(terminal.py), followed as they happen."""
import html
import time
from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets
from . import terminal

COLOURS = {'command': '#7cc4ff', 'note': '#8a8a8a', 'end': '#7fd67f', 'stop': '#e0b060', 'fail': '#ff7b72', 'out': '#d4d4d4'}
ALL = 'All programs'


class TerminalWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MoonRay Terminal')
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinMaxButtonsHint)
        self.setModal(False)
        self.resize(940, 520)
        self.last = 0
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        layout.addLayout(row)
        self.program = QtWidgets.QComboBox()
        self.program.addItem(ALL)
        self.program.setToolTip('Show one program only')
        row.addWidget(self.program)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Filter lines')
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        self.packets = QtWidgets.QCheckBox('Progress packets')
        self.packets.setToolTip("Show the lines MoonRay prints for the plugin to read (buckets and progress), which start with @@")
        row.addWidget(self.packets)
        self.times = QtWidgets.QCheckBox('Times')
        self.times.setChecked(True)
        row.addWidget(self.times)
        self.follow = QtWidgets.QCheckBox('Follow')
        self.follow.setChecked(True)
        self.follow.setToolTip('Keep the newest line in view')
        row.addWidget(self.follow)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(terminal.LIMIT)
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        font.setFamily('Consolas')
        font.setPointSize(9)
        self.text.setFont(font)
        self.text.setStyleSheet('QPlainTextEdit{background:#0c0c0c;color:#d4d4d4;border:none;}')
        # The prompt under the lines: "ready" and a blinking underline while nothing runs, as a terminal waits.
        self.prompt = QtWidgets.QLabel()
        self.prompt.setFont(font)
        self.prompt.setTextFormat(QtCore.Qt.RichText)
        self.prompt.setStyleSheet('QLabel{background:#0c0c0c;color:#d4d4d4;border:none;padding:2px 4px 6px 4px;}')
        self.prompt.setFixedHeight(QtGui.QFontMetrics(font).height() + 10)
        self.blink = True
        screen = QtWidgets.QFrame()
        screen.setObjectName('screen')
        screen.setStyleSheet('QFrame#screen{background:#0c0c0c;border:1px solid #333;}')
        stacked = QtWidgets.QVBoxLayout(screen)
        stacked.setContentsMargins(1, 1, 1, 1)
        stacked.setSpacing(0)
        stacked.addWidget(self.text, 1)
        stacked.addWidget(self.prompt)
        layout.addWidget(screen, 1)
        footer = QtWidgets.QHBoxLayout()
        layout.addLayout(footer)
        self.count = QtWidgets.QLabel()
        self.count.setStyleSheet('color:#8a8a8a;')
        footer.addWidget(self.count, 1)
        for label, action in (('Clear', self.clear), ('Copy', self.copy), ('Save...', self.save), ('Close', self.close)):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(action)
            button.setAutoDefault(False)
            footer.addWidget(button)
        self.search.textChanged.connect(self.rebuild)
        self.program.currentIndexChanged.connect(self.rebuild)
        self.packets.toggled.connect(self.rebuild)
        self.times.toggled.connect(self.rebuild)
        self.follow.toggled.connect(lambda on: on and self._to_end())
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.blinker = QtCore.QTimer(self)
        self.blinker.setInterval(530)
        self.blinker.timeout.connect(self._blink)
        self.rebuild()

    def showEvent(self, event):
        self.timer.start()
        self.blinker.start()
        self.refresh()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        self.blinker.stop()
        super().hideEvent(event)

    def _shown(self, entry):
        serial, moment, kind, source, line = entry
        if kind == 'out' and line.startswith(terminal.PACKET_PREFIX) and not self.packets.isChecked():
            return False
        chosen = self.program.currentText()
        if chosen != ALL and source != chosen:
            return False
        wanted = self.search.text().strip().lower()
        return not wanted or wanted in line.lower() or wanted in source.lower()

    def _html(self, entry):
        serial, moment, kind, source, line = entry
        stamp = '<span style="color:#6a6a6a">%s </span>' % time.strftime('%H:%M:%S', time.localtime(moment)) if self.times.isChecked() else ''
        tag = '<span style="color:#b48ead">[%s] </span>' % html.escape(source)
        mark = {'command': '&gt; ', 'end': '&#9632; ', 'stop': '&#9632; ', 'fail': '&#9632; '}.get(kind, '')
        weight = 'font-weight:bold;' if kind == 'command' else ''
        return '%s%s<span style="color:%s;%s">%s%s</span>' % (stamp, tag, COLOURS.get(kind, COLOURS['out']), weight, mark,
                                                               html.escape(line).replace(' ', '&nbsp;'))

    def _plain(self, entry):
        serial, moment, kind, source, line = entry
        mark = {'command': '> ', 'end': '# ', 'stop': '# ', 'fail': '# '}.get(kind, '')
        stamp = time.strftime('%H:%M:%S ', time.localtime(moment)) if self.times.isChecked() else ''
        return '%s[%s] %s%s' % (stamp, source, mark, line)

    def _sources(self):
        known = {self.program.itemText(i) for i in range(self.program.count())}
        for source in sorted(terminal.sources - known):
            self.program.addItem(source)

    def _to_end(self):
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _append(self, chosen):
        if not chosen:
            return
        bar = self.text.verticalScrollBar()
        held = bar.value()
        # Long lines run on to the right; the view goes across only as far as the viewer scrolls it, never to follow a
        # new line's end.
        across = self.text.horizontalScrollBar()
        sideways = across.value()
        for entry in chosen:
            self.text.appendHtml(self._html(entry))
        if self.follow.isChecked():
            self._to_end()
        else:
            bar.setValue(held)
        across.setValue(sideways)

    def refresh(self):
        fresh = terminal.entries(self.last)
        if fresh:
            self.last = fresh[-1][0]
            self._sources()
            self._append([entry for entry in fresh if self._shown(entry)])
        self.count.setText('%d programs started this session' % sum(1 for e in terminal.entries() if e[2] == 'command'))
        self._show_prompt()

    def _blink(self):
        self.blink = not self.blink
        self._show_prompt()

    def _show_prompt(self):
        if terminal.busy():
            self.prompt.setText('')
        else:
            self.prompt.setText('ready<span style="color:#d4d4d4">%s</span>' % ('_' if self.blink else '&nbsp;'))

    def rebuild(self):
        self.text.clear()
        everything = terminal.entries()
        self.last = everything[-1][0] if everything else 0
        self._sources()
        shown = [entry for entry in everything if self._shown(entry)]
        self._append(shown)
        self.refresh()

    def clear(self):
        terminal.clear()
        self.rebuild()

    def lines(self):
        return '\n'.join(self._plain(entry) for entry in terminal.entries() if self._shown(entry))

    def copy(self):
        QtWidgets.QApplication.clipboard().setText(self.lines())

    def save(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save terminal', str(Path.home() / 'moonray_terminal.txt'), 'Text (*.txt)')
        if path:
            try:
                Path(path).write_text(self.lines() + '\n', encoding='utf-8')
            except OSError as exc:
                QtWidgets.QMessageBox.warning(self, 'MoonRay Terminal', 'Could not save: %s' % exc)
