"""Main window: wires detection, the feeds, the engine and the two pages together."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from . import __version__, theme, updater
from .engine import MeterEngine, Snapshot, keep_only, with_party_rows
from .hotkey import GlobalHotkey
from .overlay import OverlayWindow
from .capture import CaptureFeed, capture_available
from .startup import is_enabled as is_startup_enabled
from .startup import set_enabled as set_startup_enabled
from .feeds import (
    CharacterDetector,
    DemoFeed,
    GameWatcher,
    LogFeed,
    candidate_feed_paths,
    find_feed,
    read_session_file,
    write_session_file,
)
from .widgets import DetailPage, RosterPage

# ogni quanto ricontrollare GitHub, e ogni quanto riprovare dopo un errore
UPDATE_CHECK_INTERVAL = 30 * 60
UPDATE_RETRY_INTERVAL = 90
UPDATE_FAIL_RETRY = 5 * 60


class MainWindow(QWidget):
    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self.setObjectName("window")
        self.setWindowTitle("Aion 2 Damage Meter")
        self.setStyleSheet(theme.QSS)
        self.setMinimumSize(640, 560)

        self.engine = MeterEngine()
        self.demo = DemoFeed()
        self.demo_enabled = demo
        self.watcher = GameWatcher()
        self.detector = CharacterDetector()
        feed_path = find_feed()
        self.feed = LogFeed(feed_path) if feed_path else None
        self.capture: CaptureFeed | None = None
        self.live = False
        self.tab = "damage"
        self.merge_pets = True
        self.include_brawler = False
        self._detail_key: str | None = None
        self._scan_ticks = 0
        self._update_info: updater.UpdateInfo | None = None
        self._update_shown = False
        self._update_busy = False
        self._next_update_check = time.monotonic() + 2.5
        self._download_busy = False
        self._download_percent = -1
        self._download_result: tuple[Path, bool] | None = None
        self._overlay_dismissed = False
        self._saved_self = False
        self.party_only = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.roster_page = RosterPage()
        self.detail_page = DetailPage()
        self.stack.addWidget(self.roster_page)
        self.stack.addWidget(self.detail_page)
        layout.addWidget(self.stack)

        self.roster_page.player_clicked.connect(self.open_detail)
        self.roster_page.tab_selected.connect(self.set_tab)
        self.roster_page.merge_changed.connect(self.set_merge_pets)
        self.roster_page.brawler_changed.connect(self.set_include_brawler)
        self.detail_page.back_requested.connect(self.show_roster)
        self.roster_page.update_clicked.connect(self.install_update)
        self.roster_page.self_pick.connect(self.pick_self)
        self.roster_page.startup_toggled.connect(self.set_startup)
        self.roster_page.party_only_changed.connect(self.set_party_only)
        self.roster_page.set_startup_checked(is_startup_enabled())

        self.overlay = OverlayWindow()
        self.overlay.load_settings()
        self.overlay.open_requested.connect(self.bring_to_front)
        self.overlay.hidden_by_user.connect(self._on_overlay_hidden)
        self.roster_page.overlay_toggled.connect(self.set_overlay_visible)
        self.hotkey = GlobalHotkey(self)
        if self.hotkey.register():
            self.hotkey.activated.connect(self.toggle_overlay)

        self.watcher.scan()
        self.auto_show_overlay()
        self.roster_page.set_feed_hint(self.feed_hint())

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

        self.refresh()
        self.update_status()

    # ----------------------------------------------------------- aggiornamenti
    def check_updates(self) -> None:
        """Chiede a GitHub se esiste una versione nuova (una richiesta alla volta)."""
        if self._update_busy:
            return
        self._update_busy = True

        def work() -> None:
            try:
                info = updater.check()
            except Exception:
                info = None
            self._update_info = info
            self._update_busy = False
            if info is not None:
                self._update_shown = False
                self._next_update_check = time.monotonic() + UPDATE_CHECK_INTERVAL
            else:
                # rete o GitHub non raggiungibili: riprova tra poco
                self._next_update_check = time.monotonic() + UPDATE_RETRY_INTERVAL

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def install_update(self) -> None:
        info = self._update_info
        if info is None or self._download_busy:
            return
        if not getattr(sys, "frozen", False):
            self.roster_page.set_update_text("Aggiorna (solo exe)")
            return
        self._download_busy = True
        self._download_percent = 0
        self.roster_page.set_update_text("Aggiorno a 0%")

        def work() -> None:
            dest = Path(tempfile.gettempdir()) / "Aion2DamageMeter-update.exe"
            ok = updater.download(info, dest, progress=self._progress_update)
            self._download_result = (dest, ok)

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _progress_update(self, done: int, total: int) -> None:
        if total:
            self._download_percent = min(99, int(done * 100 / total))

    def _poll_updates(self) -> None:
        if (
            self._update_info is None
            and not self._update_busy
            and time.monotonic() >= self._next_update_check
        ):
            self.check_updates()
        if self._update_info is not None and not self._update_shown:
            self._update_shown = True
            self.roster_page.set_update(self._update_info.version)
            # un aggiornamento disponibile si installa da solo e riapre l'app
            self.install_update()
        if self._download_busy and self._download_percent >= 0:
            self.roster_page.set_update_text(f"Aggiorno a {self._download_percent}%")
        if self._download_result is not None:
            dest, ok = self._download_result
            self._download_result = None
            if ok and updater.apply_update(dest):
                self.roster_page.set_update_text("Riavvio…")
                QTimer.singleShot(400, QApplication.quit)
            else:
                # download o sostituzione fallita: riprova da solo più tardi
                self._download_busy = False
                self._download_percent = -1
                self._update_info = None
                self._update_shown = False
                self._next_update_check = time.monotonic() + UPDATE_FAIL_RETRY
                self.roster_page.set_update_text("Riprovo tra poco…")

    # ------------------------------------------------------------------ overlay
    def _on_overlay_hidden(self) -> None:
        self._overlay_dismissed = True
        self.roster_page.set_overlay_checked(False)

    def set_overlay_visible(self, visible: bool) -> None:
        if visible:
            self.overlay.show()
            self.overlay.raise_()
            self.overlay.set_snapshot(self.snapshot(), self.live)
        else:
            self.overlay.hide()
            self._overlay_dismissed = True
        self.overlay.save_settings()

    def auto_show_overlay(self) -> None:
        """Show the overlay by itself as soon as Aion 2 is running."""
        if not self.watcher.running or self._overlay_dismissed or self.overlay.isVisible():
            return
        self.roster_page.set_overlay_checked(True)
        self.set_overlay_visible(True)

    def toggle_overlay(self) -> None:
        self.set_overlay_visible(not self.overlay.isVisible())
        self.roster_page.set_overlay_checked(self.overlay.isVisible())

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------- interactions
    def set_tab(self, key: str) -> None:
        self.tab = key
        self.refresh()

    def set_merge_pets(self, value: bool) -> None:
        self.merge_pets = value
        self.refresh()

    def set_include_brawler(self, value: bool) -> None:
        self.include_brawler = value
        self.refresh()

    def show_roster(self) -> None:
        self._detail_key = None
        self.roster_page.set_selected(None)
        self.stack.setCurrentIndex(0)

    def open_detail(self, key: str) -> None:
        self._detail_key = key
        self.roster_page.set_selected(key)
        snap = self.snapshot()
        member = next((m for m in snap.members if m.key == key), None)
        if member is None:
            return
        self.detail_page.set_member(member)
        self.stack.setCurrentIndex(1)

    # ------------------------------------------------------------------- feeds
    def snapshot(self) -> Snapshot:
        snap = self.engine.snapshot(self.tab, self.merge_pets, self.include_brawler)
        if self.capture is None:
            return snap
        party_names = self.capture.party()
        if party_names:
            snap = with_party_rows(snap, party_names)
        if not self.party_only:
            return snap
        party = set(party_names)
        if not party:
            return snap
        me = self.capture.detected_name()
        if me:
            party.add(me)
        # resta visibile anche chi ha danni ma non ha ancora il nome (compagno non mappato)
        keep = party | {member.name for member in snap.members if member.name.startswith("Player ")}
        return keep_only(snap, keep)

    def set_party_only(self, enabled: bool) -> None:
        self.party_only = bool(enabled)
        self.refresh()

    def _apply(self, event: dict) -> None:
        kind = str(event.get("type", "hit")).lower()

        if kind in ("session", "info", "self", "me", "player_info"):
            self.engine.set_session(
                event.get("server"), event.get("character") or event.get("name"), event.get("class")
            )
            return

        if kind in ("party", "roster", "dungeon"):
            for member in event.get("members") or []:
                if not isinstance(member, dict):
                    continue
                name = member.get("name") or member.get("src")
                if name:
                    self.engine.define(
                        str(name),
                        member.get("class") or member.get("cls"),
                        member.get("role"),
                        bool(member.get("pet")),
                        member.get("owner"),
                        joined=True,
                    )
            return

        if kind in ("join", "member_join", "member", "player"):
            name = event.get("src") or event.get("name")
            if name:
                self.engine.define(
                    str(name),
                    event.get("class") or event.get("cls"),
                    event.get("role"),
                    bool(event.get("pet")),
                    event.get("owner"),
                    joined=True,
                )
            return

        if kind in ("leave", "member_leave", "player_leave"):
            name = event.get("src") or event.get("name")
            if name:
                self.engine.drop(str(name))
            return

        # any other line is a combat event: a new source is added automatically
        self.engine.add(event)

    def tick(self) -> None:
        events: list[dict] = []
        became_live = False
        self._tick_capture()
        if self.capture is not None:
            capture_events = self.capture.poll()
            if capture_events:
                if not self.live:
                    self.live = True
                    became_live = True
                    self.engine.reset()
                for event in capture_events:
                    self._apply(event)
            for old, new in self.capture.take_renames():
                self.engine.rename(old, new)
        if self.feed is not None:
            events = self.feed.poll()
            if events and not self.live:
                self.live = True
                became_live = True
                self.engine.reset()
        if events:
            for event in events:
                self._apply(event)
        elif not self.live and self.demo_enabled:
            for event in self.demo.poll(0.25):
                self._apply(event)

        self._poll_updates()

        self._scan_ticks += 1
        if became_live or self._scan_ticks % 8 == 0:
            self.watcher.scan()
            self.auto_show_overlay()
            if self.feed is None:
                path = find_feed()
                if path is not None:
                    self.feed = LogFeed(path)
                    self.roster_page.set_feed_hint(self.feed_hint())
            self.update_status()

        self.refresh()

    def pick_self(self) -> None:
        """Dice al meter quale riga e' il giocatore (il suo danno finisce in 'Tu')."""
        if self.capture is None:
            return
        from PyQt6.QtWidgets import QInputDialog

        candidates = self.capture.candidates()
        label, ok = QInputDialog.getItem(
            self,
            "Chi sei tu",
            "Scegli la tua riga nel meter (o scrivi il tuo nome di gioco):",
            candidates or ["Player 0"],
            0,
            True,
        )
        if not ok or not label:
            return
        chosen = label.strip()
        real_name = not chosen.startswith("Player ")
        self.capture.set_self_label(chosen)
        if real_name:
            # un nome vero resta valido anche alla prossima apertura
            self.capture.set_known_name(chosen)
            write_session_file(chosen, self.capture.detected_class())
        for old, new in self.capture.take_renames():
            self.engine.rename(old, chosen if (real_name and new == "Tu") else new)
        self.refresh()
        self.update_status()

    def _tick_capture(self) -> None:
        """Avvia la cattura quando il gioco gira, la ferma quando si chiude."""
        if self.demo_enabled or not capture_available():
            return
        if self.watcher.running:
            if self.capture is None:
                self.capture = CaptureFeed()
                known = self.detector.character or read_session_file().get("character")
                if known:
                    self.capture.set_known_name(known)
                self.capture.start()
            if self.detector.character:
                self.capture.set_self_hint(self.detector.character)
        elif self.capture is not None and not self.capture.running:
            self.capture.stop()
            self.capture = None

    # ----------------------------------------------------------------- display
    def feed_hint(self) -> str:
        if self.capture is not None and self.capture.running:
            return f"Cattura pacchetti attiva · {self.capture.packets:,} pacchetti"
        if self.feed is not None:
            return f"Log di combattimento: {self.feed.path}"
        candidates = candidate_feed_paths()
        return f"Nessun log trovato. Atteso: {candidates[0]}"

    def refresh(self) -> None:
        snap = self.snapshot()
        self.roster_page.set_snapshot(snap)
        if self.overlay.isVisible():
            self.overlay.set_snapshot(snap, self.live)
        if self.stack.currentIndex() == 1 and self._detail_key:
            member = next((m for m in snap.members if m.key == self._detail_key), None)
            if member is not None:
                self.detail_page.set_member(member)
            else:
                self.show_roster()

    def update_status(self) -> None:
        from_file = read_session_file()
        from_feed = {k: v for k, v in self.engine.session.items() if v}
        info = self.detector.update(self.watcher, {**from_file, **from_feed})

        # la cattura conosce il personaggio e la classe meglio dei file locali
        if self.capture is not None:
            detected_class = self.capture.detected_class()
            detected_name = self.capture.detected_name()
            if detected_class:
                info["class"] = detected_class
                self.engine.set_session(cls=detected_class)
            if detected_name:
                info["character"] = detected_name
                self.engine.set_session(character=detected_name)
                if not self._saved_self and detected_name.isalnum():
                    self._saved_self = True
                    write_session_file(detected_name, detected_class, info.get("server"))

        character = info.get("character")
        char_class = info.get("class")
        server = info.get("server")

        if character and char_class:
            self.roster_page.set_you(f"Tu: {character} · {char_class}")
        elif character:
            self.roster_page.set_you(f"Tu: {character}")
        elif self.watcher.running:
            self.roster_page.set_you("Tu: classe non rilevata")
        else:
            self.roster_page.set_you("Tu: in attesa")

        if self.capture is not None:
            self.roster_page.set_self_pick_visible(
                self.live and self.capture.protocol.self_actor is None
            )
            party = self.capture.party()
            if party:
                self.roster_page.set_party(party)
            elif self.party_only:
                self.roster_page.set_party_note(
                    "Solo gruppo: lista non ancora ricevuta dal server "
                    "— apri la finestra gruppo (P) col meter aperto"
                )
            if not self.capture.protocol.names and not self.capture.party():
                self.roster_page.set_you_hint(
                    "I nomi dei giocatori arrivano dal server solo al caricamento della zona. "
                    "Tieni il meter aperto prima del login (o attiva 'Avvia con Windows') "
                    "oppure cambia zona una volta: le righe 'Player N' diventano nomi."
                )
            else:
                self.roster_page.set_you_hint("La tua riga nel meter")

        if self.watcher.running:
            parts = [f"Aion 2 rilevato · {self.watcher.exe} (PID {self.watcher.pid})"]
            if self.capture is not None:
                if self.capture.packets:
                    parts.append(f"cattura {self.capture.packets:,} pacchetti")
                elif self.capture.error:
                    parts.append(self.capture.error)
            parts.append(f"v{__version__}")
            if server:
                parts.append(f"server {server}")
            if character:
                parts.append(f"{character} ({char_class})" if char_class else character)
            self.roster_page.set_status("  ·  ".join(parts), self.live)
        else:
            self.roster_page.set_status(
                "Aion 2 non rilevato — in attesa dell'avvio del gioco", self.live
            )

    def set_startup(self, enabled: bool) -> None:
        """Avvio con Windows: la cattura parte prima del login e vede i nomi."""
        if not set_startup_enabled(enabled):
            self.roster_page.set_startup_checked(not enabled)
            return
        self.roster_page.set_startup_checked(enabled)

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        if self.capture is not None:
            self.capture.stop()
            self.capture = None
        self.overlay.save_settings()
        self.hotkey.unregister()
        super().closeEvent(event)
