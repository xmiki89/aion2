"""Optional global hotkey (Ctrl+Shift+O) to show/hide the overlay while playing."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

WM_HOTKEY = 0x0312
MOD_SHIFT = 0x0004
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_O = 0x4F


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner: "GlobalHotkey") -> None:
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):  # noqa: N802, ANN001
        if event_type == b"windows_generic_MSG" and self.owner.hotkey_id:
            try:
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == WM_HOTKEY and int(msg.wParam) == self.owner.hotkey_id:
                    self.owner.activated.emit()
            except (ValueError, TypeError, OSError):
                pass
        return False, 0


class GlobalHotkey(QObject):
    """Registers a system-wide hotkey; silently does nothing if unavailable."""

    activated = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.hotkey_id = 0
        self._filter: _Filter | None = None
        self._user32 = None

    def register(self) -> bool:
        if os.name != "nt":
            return False
        try:
            self._user32 = ctypes.windll.user32
            hotkey_id = 0xA10F
            if not self._user32.RegisterHotKey(
                None, hotkey_id, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_O
            ):
                self.hotkey_id = 0
                return False
            self.hotkey_id = hotkey_id
            self._filter = _Filter(self)
            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)
            return True
        except (OSError, AttributeError):
            self.hotkey_id = 0
            return False

    def unregister(self) -> None:
        if self._user32 is not None and self.hotkey_id:
            try:
                self._user32.UnregisterHotKey(None, self.hotkey_id)
            except OSError:
                pass
        if self._filter is not None:
            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._filter)
            self._filter = None
        self.hotkey_id = 0
