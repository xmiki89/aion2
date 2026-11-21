"""Aion 2 Damage Meter – entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from aion2meter import updater
from aion2meter.window import MainWindow


def run_selftest(app: QApplication, window: MainWindow, prefix: str) -> None:
    """Render both pages to PNG files and quit (used to verify the build)."""

    def first() -> None:
        window.grab().save(f"{prefix}_roster.png")
        snap = window.snapshot()
        if snap.members:
            window.open_detail(snap.members[0].key)
        QTimer.singleShot(700, second)

    def second() -> None:
        window.grab().save(f"{prefix}_detail.png")
        window.set_overlay_visible(True)
        QTimer.singleShot(600, third)

    def third() -> None:
        window.overlay.grab().save(f"{prefix}_overlay.png")
        app.quit()

    QTimer.singleShot(1400, first)


def _install_excepthook() -> None:
    def hook(exc_type, exc_value, exc_tb):  # noqa: ANN001
        import traceback

        traceback.print_exception(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def uninstall(app: QApplication) -> int:
    """Removes shortcuts and the install folder entry, then deletes the exe."""
    from PyQt6.QtWidgets import QMessageBox

    from aion2meter import wininstall

    quiet = "--quiet" in sys.argv
    if not quiet:
        answer = QMessageBox.question(
            None,
            "Disinstalla Aion 2 Damage Meter",
            "Rimuovere Aion 2 Damage Meter da questo PC?\n\n"
            "Vengono eliminati il programma e i collegamenti. I file combat.log e session.json "
            "non vengono toccati.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return 1

    wininstall.remove_shortcuts()
    wininstall.remove_uninstall_entry()
    if getattr(sys, "frozen", False):
        wininstall.schedule_removal(wininstall.current_exe())
    if not quiet:
        QMessageBox.information(
            None, "Disinstallazione", "Fatto: il programma viene rimosso tra pochi secondi."
        )
    return 0


def _cli() -> int | None:
    if "--check-update" in sys.argv:
        return updater.cli_check()
    if "--update" in sys.argv:
        return updater.cli_update()
    if "--apply-update" in sys.argv:
        index = sys.argv.index("--apply-update")
        if index + 1 >= len(sys.argv):
            return 2
        ok = updater.apply_update(Path(sys.argv[index + 1]), restart="--no-restart" not in sys.argv)
        return 0 if ok else 1
    return None


def main() -> int:
    _install_excepthook()
    cli_result = _cli()
    if cli_result is not None:
        return cli_result

    app = QApplication(sys.argv)
    app.setApplicationName("Aion 2 Damage Meter")
    app.setFont(QFont("Segoe UI", 9))

    if "--uninstall" in sys.argv:
        return uninstall(app)

    window = MainWindow(demo="--demo" in sys.argv)
    window.resize(792, 660)
    window.show()

    selftest_prefix = None
    if "--selftest" in sys.argv:
        args = sys.argv[sys.argv.index("--selftest") + 1:]
        selftest_prefix = args[0] if args else "selftest"
        run_selftest(app, window, selftest_prefix)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
