#!/usr/bin/env python3
"""
scuf-tray — system tray for the SCUF Envision Pro V2 driver.

Polls the driver IPC socket every 3 s and reflects connection state, battery
level, active profile, and RGB mode in a notification-area icon with a menu.

Requires: PyQt6, pillow
"""

import json
import logging
import socket
import sys
import threading
import time
from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QActionGroup, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

log = logging.getLogger(__name__)

SOCKET_PATH = "/run/scuf-envision/ipc.sock"
POLL_INTERVAL = 3.0

# Sentinel objects returned by _ipc() on error — never returned as real data.
_OFFLINE  = object()  # socket not found / connection refused
_TIMEOUT  = object()  # connected but timed out waiting for response
_BADRESP  = object()  # connected, got data, but not valid JSON


def _ipc(cmd: str):
    """Send a command to the driver IPC socket and return the raw string response.

    Returns one of: a str (success), _OFFLINE, _TIMEOUT, or _BADRESP.
    Never raises.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(SOCKET_PATH)
            s.sendall((cmd + "\n").encode())
            chunks = []
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks).decode().strip()
    except (FileNotFoundError, ConnectionRefusedError):
        return _OFFLINE
    except (TimeoutError, BlockingIOError):
        return _TIMEOUT
    except OSError as e:
        log.debug("IPC error for %r: %s", cmd, e)
        return _OFFLINE


def _make_controller_icon(r: int, g: int, b: int) -> Image.Image:
    """Draw a simple gamepad silhouette in the given colour."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (r, g, b, 255)
    hi = (255, 255, 255, 160)

    d.rounded_rectangle([6, 15, 58, 44], radius=11, fill=c)
    d.ellipse([3, 32, 25, 58], fill=c)
    d.ellipse([39, 32, 61, 58], fill=c)

    # D-pad
    d.rectangle([14, 26, 20, 39], fill=hi)
    d.rectangle([10, 30, 24, 35], fill=hi)

    # Face buttons
    for cx, cy in [(46, 26), (52, 31), (46, 36), (40, 31)]:
        d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=hi)

    # Analog sticks
    d.ellipse([22, 35, 31, 44], fill=hi)
    d.ellipse([33, 29, 42, 38], fill=hi)

    return img


def _pil_to_qicon(img: Image.Image) -> QIcon:
    # QPixmap requires a QGuiApplication to already exist — call only after
    # QApplication(sys.argv) has been constructed.
    return QIcon(QPixmap.fromImage(ImageQt(img)))


class TrayApp(QObject):
    # Emitted from the poll thread; all UI mutations happen in the Qt main thread.
    state_updated = pyqtSignal(dict, object)  # (state_dict, ipc_error_sentinel_or_None)

    def __init__(self, app: QApplication):
        super().__init__()
        self._app       = app
        self._state: dict = {}
        self._ipc_error = _OFFLINE

        # Build icons here — QApplication already exists at this point.
        self._icon_connected = _pil_to_qicon(_make_controller_icon(0, 180, 70))
        self._icon_wireless  = _pil_to_qicon(_make_controller_icon(220, 170, 0))
        self._icon_offline   = _pil_to_qicon(_make_controller_icon(180, 50, 50))

        self._tray = QSystemTrayIcon(self._icon_offline, self)
        self._tray.setToolTip("SCUF Envision \u2014 offline")
        self._menu = QMenu()
        self._tray.setContextMenu(self._menu)
        self._tray.show()

        self.state_updated.connect(self._on_state_updated)
        self._rebuild_menu()  # initial "Driver not running" state

        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ── polling (worker thread) ───────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while True:
            try:
                raw = _ipc("status")
                if raw is _OFFLINE or raw is _TIMEOUT:
                    self.state_updated.emit({}, raw)
                elif isinstance(raw, str):
                    try:
                        self.state_updated.emit(json.loads(raw), None)
                    except (json.JSONDecodeError, ValueError):
                        log.warning("Unexpected IPC response: %r", raw)
                        self.state_updated.emit({}, _BADRESP)
            except Exception:
                log.exception("Poll error")
            time.sleep(POLL_INTERVAL)

    # ── slot (Qt main thread) ─────────────────────────────────────────────────

    def _on_state_updated(self, state: dict, ipc_error) -> None:
        self._state     = state
        self._ipc_error = ipc_error
        self._refresh_icon()
        self._rebuild_menu()

    def _refresh_icon(self) -> None:
        state = self._state
        connected = bool(state) and "status" not in state
        if not connected:
            self._tray.setIcon(self._icon_offline)
            if self._ipc_error is _TIMEOUT:
                self._tray.setToolTip("SCUF Envision \u2014 not responding")
            elif state.get("status") == "searching_for_controller":
                self._tray.setToolTip("SCUF Envision \u2014 searching\u2026")
            else:
                self._tray.setToolTip("SCUF Envision \u2014 driver offline")
        elif state.get("connection") == "wireless":
            self._tray.setIcon(self._icon_wireless)
            self._tray.setToolTip(f"SCUF Envision \u2014 wireless | {state.get('profile', '?')}")
        else:
            self._tray.setIcon(self._icon_connected)
            self._tray.setToolTip(f"SCUF Envision \u2014 wired | {state.get('profile', '?')}")

    def _rebuild_menu(self) -> None:
        state, err = self._state, self._ipc_error
        connected  = bool(state) and "status" not in state
        m = self._menu
        m.clear()

        if   err is _TIMEOUT:  status_text = "Driver not responding"
        elif err is _BADRESP:  status_text = "Driver error (bad response)"
        elif not state:        status_text = "Driver not running"
        elif not connected:    status_text = "Searching for controller\u2026"
        else:                  status_text = f"Connected ({state.get('connection', '?')})"
        a = m.addAction(status_text); a.setEnabled(False)

        battery = state.get("battery", -1)
        if isinstance(battery, int) and battery >= 0:
            a = m.addAction(f"Battery: {battery}%"); a.setEnabled(False)

        m.addSeparator()

        # Profile submenu
        active   = state.get("profile", "default")
        profiles = state.get("profiles", [])
        prof_label = f"Profile: {active}" if connected else "Profile"
        prof_menu  = m.addMenu(prof_label)
        prof_menu.setEnabled(connected)
        if profiles:
            grp = QActionGroup(prof_menu); grp.setExclusive(True)
            for name in profiles:
                a = prof_menu.addAction(name)
                a.setCheckable(True)
                a.setChecked(name == active)
                a.setActionGroup(grp)
                a.triggered.connect(lambda _checked, n=name: self._switch_profile(n))
        else:
            a = prof_menu.addAction("Not connected"); a.setEnabled(False)

        m.addSeparator()

        # RGB submenu
        rgb_ok   = connected and bool(state.get("rgb", False))
        rgb_menu = m.addMenu("RGB")
        rgb_menu.setEnabled(rgb_ok)
        for label, cmd in [
            ("Off",             "rgb off"),
            (None, None),
            ("White",           "rgb static ffffff"),
            ("Red",             "rgb static ff0000"),
            ("Blue",            "rgb static 0044ff"),
            ("Green",           "rgb static 00ff44"),
            (None, None),
            ("Breathe",         "rgb breathe"),
            ("Rainbow",         "rgb rainbow"),
            ("CPU Temperature", "rgb cpu-temperature"),
        ]:
            if label is None:
                rgb_menu.addSeparator()
            else:
                rgb_menu.addAction(label, lambda c=cmd: _ipc(c))

        m.addSeparator()
        m.addAction("Quit", self._app.quit)

    # ── actions ───────────────────────────────────────────────────────────────

    def _switch_profile(self, name: str) -> None:
        _ipc(f"profile {name}")
        # Immediate refresh so the radio check updates without waiting 3 s.
        raw = _ipc("status")
        if isinstance(raw, str):
            try:
                self._on_state_updated(json.loads(raw), None)
            except (json.JSONDecodeError, ValueError):
                pass


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray-only app; no windows to close
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("scuf-tray: no system tray available on this desktop", file=sys.stderr)
        sys.exit(1)
    _tray = TrayApp(app)  # noqa: F841 — must stay alive for the event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
