"""Aion 2 Damage Meter setup: lets the user pick the install folder.

Run from source:      python installer/setup_app.py
Silent install:       Aion2DamageMeter-Setup.exe --silent --dir "D:\\Giochi\\Aion2Meter"
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QDesktopServices, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QUrl

from aion2meter import wininstall

APP_NAME = "Aion 2 Damage Meter"
EXE_NAME = "Aion2DamageMeter.exe"

QSS = """
QWidget { background: #131316; color: #F1F2F5; font-family: "Segoe UI"; font-size: 12px; }
QLabel { background: transparent; }
QLabel#title { font-size: 20px; font-weight: 700; }
QLabel#subtitle { color: #8C8F99; font-size: 12px; }
QLabel#section { color: #C9CCD4; font-size: 11.5px; font-weight: 600; }
QLabel#hint { color: #7C7F89; font-size: 10.5px; }
QLineEdit { background: #17171C; border: 1px solid #2A2A31; border-radius: 8px; padding: 8px 10px; color: #F1F2F5; }
QLineEdit:focus { border-color: #4C6FFF; }
QPushButton#primary { background: #4C6FFF; border: none; border-radius: 8px; padding: 9px 20px; color: #FFFFFF; font-weight: 600; }
QPushButton#primary:hover { background: #5E7DFF; }
QPushButton#ghost { background: #1D1D22; border: 1px solid #2C2C34; border-radius: 8px; padding: 8px 14px; color: #DCDFE6; }
QPushButton#ghost:hover { border-color: #3B3B44; }
QCheckBox { color: #C9CCD4; font-size: 11.5px; spacing: 8px; }
QCheckBox::indicator { width: 13px; height: 13px; border-radius: 4px;
                       border: 1px solid #3A3A44; background: #17171C; }
QCheckBox::indicator:hover { border-color: #4C6FFF; }
QCheckBox::indicator:checked { background: #4C6FFF; border: 1px solid #4C6FFF; }
QPlainTextEdit { background: #101013; border: 1px solid #222228; border-radius: 8px; color: #B9BCC6;
                 font-family: Consolas, monospace; font-size: 10.5px; }
"""


def bundled_app() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "payload" / EXE_NAME
    return PROJECT_ROOT / "dist" / EXE_NAME


def default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Aion2DamageMeter"


def resolve_dir(raw: str) -> Path:
    text = raw.strip().strip('"').strip()
    text = os.path.expandvars(os.path.expanduser(text))
    return Path(text)


def install(
    target: Path,
    desktop_shortcut: bool = True,
    start_shortcut: bool = True,
    registry: bool = True,
    log=print,
) -> bool:
    payload = bundled_app()
    if not payload.is_file():
        log(f"ERRORE: pacchetto applicazione mancante ({payload})")
        return False

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"ERRORE: impossibile creare la cartella: {exc}")
        return False
    if not os.access(target, os.W_OK):
        log(f"ERRORE: nessun permesso di scrittura in {target}")
        return False

    exe = target / EXE_NAME
    log(f"Cartella scelta: {target}")
    try:
        shutil.copy2(payload, exe)
    except OSError as exc:
        log(f"ERRORE: copia non riuscita ({exc}). Chiudi il meter se è aperto e riprova.")
        return False
    log(f"Installato: {exe}")

    if desktop_shortcut:
        ok = wininstall.create_shortcut(
            wininstall.desktop_dir() / f"{APP_NAME}.lnk", exe, target, "Damage meter per Aion 2"
        )
        log("Collegamento sul desktop: " + ("creato" if ok else "non creato"))

    if start_shortcut:
        start = wininstall.start_menu_dir()
        ok = wininstall.create_shortcut(start / f"{APP_NAME}.lnk", exe, target, "Damage meter per Aion 2")
        log("Collegamento menu Start: " + ("creato" if ok else "non creato"))
        wininstall.create_shortcut(
            start / f"Disinstalla {APP_NAME}.lnk", exe, target, "Disinstalla Aion 2 Damage Meter"
        )

    if registry:
        ok = wininstall.write_uninstall_entry(target, exe)
        log("Voce in App e funzionalità: " + ("registrata" if ok else "non registrata"))

    log("Installazione completata.")
    return True


class SetupWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Installazione")
        self.setStyleSheet(QSS)
        self.setFixedSize(580, 430)
        self.target_exe: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)
        self.stack.addWidget(self._intro_page())
        self.stack.addWidget(self._progress_page())
        self.stack.addWidget(self._done_page())

    # ------------------------------------------------------------------- pages
    def _intro_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setObjectName("title")
        subtitle = QLabel(
            "Scegli dove installare l'app. Verrà copiato un solo file eseguibile nella cartella scelta."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)

        section = QLabel("Cartella di installazione")
        section.setObjectName("section")

        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(str(default_dir()))
        browse = QPushButton("Sfoglia…")
        browse.setObjectName("ghost")
        browse.clicked.connect(self.browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)

        self.desktop_check = QCheckBox("Crea collegamento sul desktop")
        self.desktop_check.setChecked(True)
        self.start_check = QCheckBox("Aggiungi al menu Start")
        self.start_check.setChecked(True)
        self.launch_check = QCheckBox("Avvia il meter al termine dell'installazione")
        self.launch_check.setChecked(True)

        hint = QLabel(
            "Suggerimento: va bene anche una cartella su un altro disco, ad esempio D:\\Giochi\\Aion2Meter."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.close)
        install_button = QPushButton("Installa")
        install_button.setObjectName("primary")
        install_button.setDefault(True)
        install_button.clicked.connect(self.start_install)
        buttons.addWidget(cancel)
        buttons.addWidget(install_button)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(section)
        layout.addLayout(row)
        layout.addSpacing(6)
        layout.addWidget(self.desktop_check)
        layout.addWidget(self.start_check)
        layout.addWidget(self.launch_check)
        layout.addSpacing(4)
        layout.addWidget(hint)
        layout.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _progress_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(10)
        title = QLabel("Installazione in corso")
        title.setObjectName("title")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(title)
        layout.addWidget(self.log_view, 1)
        return page

    def _done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(10)
        title = QLabel("Installazione completata")
        title.setObjectName("title")
        self.done_path = QLabel("")
        self.done_path.setObjectName("subtitle")
        self.done_path.setWordWrap(True)
        hint = QLabel("Puoi avviare il meter dal collegamento creato o dalla cartella scelta.")
        hint.setObjectName("hint")

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        open_folder = QPushButton("Apri cartella")
        open_folder.setObjectName("ghost")
        open_folder.clicked.connect(self.open_folder)
        self.launch_button = QPushButton("Avvia il meter")
        self.launch_button.setObjectName("ghost")
        self.launch_button.clicked.connect(self.launch)
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(self.close)
        buttons.addWidget(open_folder)
        buttons.addWidget(self.launch_button)
        buttons.addWidget(close)

        layout.addWidget(title)
        layout.addWidget(self.done_path)
        layout.addWidget(hint)
        layout.addStretch(1)
        layout.addLayout(buttons)
        return page

    # ---------------------------------------------------------------- actions
    def browse(self) -> None:
        start = str(resolve_dir(self.path_edit.text()) or default_dir())
        chosen = QFileDialog.getExistingDirectory(self, "Scegli la cartella di installazione", start)
        if chosen:
            self.path_edit.setText(chosen)

    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        QApplication.processEvents()

    def start_install(self) -> None:
        target = resolve_dir(self.path_edit.text())
        if not str(target) or not target.is_absolute():
            QMessageBox.warning(
                self,
                "Cartella non valida",
                "Scegli un percorso completo, ad esempio C:\\Program Files\\Aion2Meter.",
            )
            return

        self.log_view.clear()
        self.stack.setCurrentIndex(1)
        QApplication.processEvents()
        ok = install(
            target,
            desktop_shortcut=self.desktop_check.isChecked(),
            start_shortcut=self.start_check.isChecked(),
            log=self.append_log,
        )
        if not ok:
            QMessageBox.critical(
                self,
                "Installazione non riuscita",
                "Controlla il riquadro dei messaggi e riprova con un'altra cartella.",
            )
            self.stack.setCurrentIndex(0)
            return

        self.target_exe = target / EXE_NAME
        self.done_path.setText(str(self.target_exe))
        self.stack.setCurrentIndex(2)
        if self.launch_check.isChecked():
            QTimer.singleShot(250, self.launch)

    def launch(self) -> None:
        if self.target_exe and self.target_exe.is_file():
            wininstall.launch_app(self.target_exe)

    def open_folder(self) -> None:
        if self.target_exe:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.target_exe.parent)))


def run_silent(args: list[str]) -> int:
    if "--dir" not in args:
        print("Uso: --silent --dir \"C:\\percorso\\installazione\" [--no-shortcuts] [--no-launch]")
        return 2
    target = resolve_dir(args[args.index("--dir") + 1])
    shortcuts = "--no-shortcuts" not in args
    ok = install(target, desktop_shortcut=shortcuts, start_shortcut=shortcuts)
    if ok and "--no-launch" not in args:
        wininstall.launch_app(target / EXE_NAME)
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--silent" in args:
        return run_silent(args)

    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} Setup")
    app.setFont(QFont("Segoe UI", 9))
    icon = bundled_app()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    window = SetupWindow()
    window.show()

    if "--ui-screenshot" in args:
        path = args[args.index("--ui-screenshot") + 1]
        QTimer.singleShot(900, lambda: (window.grab().save(path), app.quit()))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
