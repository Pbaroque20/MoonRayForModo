"""Plugin About window with user-supplied artwork and separate license credits."""
from pathlib import Path
from PySide2 import QtCore,QtGui,QtWidgets
from . import __version__


def show(parent=None):
    root=Path(__file__).resolve().parents[2]
    dialog=QtWidgets.QDialog(parent);dialog.setWindowTitle('About MoonRay for Modo');dialog.resize(760,570)
    layout=QtWidgets.QVBoxLayout(dialog);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
    artwork=QtWidgets.QLabel();artwork.setAlignment(QtCore.Qt.AlignCenter);artwork.setStyleSheet('background:black;')
    pixmap=QtGui.QPixmap(str(root/'assets/about-moonray.png'))
    if not pixmap.isNull(): artwork.setPixmap(pixmap.scaledToWidth(760,QtCore.Qt.SmoothTransformation))
    layout.addWidget(artwork)
    credits=QtWidgets.QLabel('MoonRay for Modo\nDeveloped by Raphael Tobar w/ AI-Assistance\nVersion '+__version__+' — Development build\n\nMIT License · Copyright © 2026 Raphael Tobar\nMoonRay renderer: Apache License 2.0 · DreamWorks Animation / OpenMoonRay\nModo 16.1v9 · Windows x64 · CPU / AVX + NVIDIA XPU\n\nIndependent integration. MaterialX translation is a supported subset.\nRendering and compatibility validation are ongoing.')
    credits.setWordWrap(True);credits.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    credits.setStyleSheet('background:#000000;color:#ffffff;padding:20px;font-size:13px;')
    layout.addWidget(credits)
    buttons=QtWidgets.QWidget();buttons.setStyleSheet('background:#000000;color:white;');row=QtWidgets.QHBoxLayout(buttons)
    def license_text(filename,title):
        child=QtWidgets.QDialog(dialog);child.setWindowTitle(title);child.resize(680,500)
        form=QtWidgets.QVBoxLayout(child);text=QtWidgets.QPlainTextEdit();text.setReadOnly(True)
        text.setPlainText((root/filename).read_text(encoding='utf-8'));form.addWidget(text);child.exec_()
    for title,filename in [('MIT License','LICENSE.txt'),('Third-party notices','THIRD_PARTY.txt')]:
        button=QtWidgets.QPushButton(title);button.clicked.connect(lambda checked=False,f=filename,t=title:license_text(f,t));row.addWidget(button)
    row.addStretch();close=QtWidgets.QPushButton('Close');close.clicked.connect(dialog.accept);row.addWidget(close);layout.addWidget(buttons)
    dialog.exec_()
