#!/usr/bin/env python3
"""
scuf-tray — system tray for the SCUF Envision Pro V2 driver.

Polls the driver IPC socket every 3 s and reflects connection state, battery
level, active profile, and RGB mode in a notification-area icon with a menu.

Requires: pystray, pillow
"""

import json
import logging
import socket
import threading
import time
from PIL import Image, ImageDraw
import pystray

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


ICON_CONNECTED = _make_controller_icon(0, 180, 70)
ICON_WIRELESS  = _make_controller_icon(220, 170, 0)
ICON_OFFLINE   = _make_controller_icon(180, 50, 50)


class TrayApp:
    def __init__(self):
        self._state: dict = {}
        self._ipc_error = _OFFLINE   # last _ipc sentinel (or None if OK)
        self._lock = threading.Lock()
        self._icon = pystray.Icon(
            "scuf_envision",
            ICON_OFFLINE,
            "SCUF Envision — offline",
            menu=pystray.Menu(self._build_menu),
        )

    # ── menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        with self._lock:
            state     = dict(self._state)
            ipc_error = self._ipc_error

        connected = bool(state) and "status" not in state

        if ipc_error is _TIMEOUT:
            status_text = "Driver not responding"
        elif ipc_error is _BADRESP:
            status_text = "Driver error (bad response)"
        elif not state:
            status_text = "Driver not running"
        elif not connected:
            status_text = "Searching for controller\u2026"
        else:
            status_text = f"Connected ({state.get('connection', '?')})"

        items = [pystray.MenuItem(status_text, None, enabled=False)]

        battery = state.get("battery", -1)
        if isinstance(battery, int) and battery >= 0:
            items.append(pystray.MenuItem(f"Battery: {battery}%", None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)

        # Profile submenu — always present; greyed when not connected
        profiles = state.get("profiles", [])
        active   = state.get("profile", "default")

        def _profile_item(name):
            return pystray.MenuItem(
                name,
                lambda _icon, _item, n=name: self._switch_profile(n),
                checked=lambda _item, n=name: self._state.get("profile") == n,
                radio=True,
            )

        profile_submenu = (
            pystray.Menu(*[_profile_item(p) for p in profiles])
            if profiles
            else pystray.Menu(pystray.MenuItem("Not connected", None, enabled=False))
        )
        profile_label = f"Profile: {active}" if connected else "Profile"
        items.append(pystray.MenuItem(profile_label, profile_submenu, enabled=connected))

        items.append(pystray.Menu.SEPARATOR)

        # RGB submenu — always present; greyed when not connected or no RGB
        rgb_ok = connected and bool(state.get("rgb", False))
        rgb_menu = pystray.Menu(
            pystray.MenuItem("Off",             lambda _: self._set_rgb("rgb off")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("White",           lambda _: self._set_rgb("rgb static ffffff")),
            pystray.MenuItem("Red",             lambda _: self._set_rgb("rgb static ff0000")),
            pystray.MenuItem("Blue",            lambda _: self._set_rgb("rgb static 0044ff")),
            pystray.MenuItem("Green",           lambda _: self._set_rgb("rgb static 00ff44")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Breathe",         lambda _: self._set_rgb("rgb breathe")),
            pystray.MenuItem("Rainbow",         lambda _: self._set_rgb("rgb rainbow")),
            pystray.MenuItem("CPU Temperature", lambda _: self._set_rgb("rgb cpu-temperature")),
        )
        items.append(pystray.MenuItem("RGB", rgb_menu, enabled=rgb_ok))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", lambda _: self._icon.stop()))

        return tuple(items)

    # ── actions ───────────────────────────────────────────────────────────────

    def _switch_profile(self, name: str) -> None:
        _ipc(f"profile {name}")
        self._poll_once()

    def _set_rgb(self, cmd: str) -> None:
        _ipc(cmd)

    # ── polling ───────────────────────────────────────────────────────────────

    def _poll_once(self) -> None:
        raw = _ipc("status")
        with self._lock:
            if raw is _OFFLINE or raw is _TIMEOUT:
                self._state     = {}
                self._ipc_error = raw
            elif isinstance(raw, str):
                try:
                    self._state     = json.loads(raw)
                    self._ipc_error = None
                except (json.JSONDecodeError, ValueError):
                    log.warning("Unexpected IPC response: %r", raw)
                    self._state     = {}
                    self._ipc_error = _BADRESP
        self._refresh_icon()

    def _poll_loop(self) -> None:
        while True:
            try:
                self._poll_once()
            except Exception:
                log.exception("Poll error")
            time.sleep(POLL_INTERVAL)

    def _refresh_icon(self) -> None:
        with self._lock:
            state     = dict(self._state)
            ipc_error = self._ipc_error

        connected = bool(state) and "status" not in state
        if not connected:
            self._icon.icon  = ICON_OFFLINE
            if ipc_error is _TIMEOUT:
                self._icon.title = "SCUF Envision \u2014 not responding"
            elif state.get("status") == "searching_for_controller":
                self._icon.title = "SCUF Envision \u2014 searching\u2026"
            else:
                self._icon.title = "SCUF Envision \u2014 driver offline"
        elif state.get("connection") == "wireless":
            self._icon.icon  = ICON_WIRELESS
            self._icon.title = f"SCUF Envision \u2014 wireless | {state.get('profile', '?')}"
        else:
            self._icon.icon  = ICON_CONNECTED
            self._icon.title = f"SCUF Envision \u2014 wired | {state.get('profile', '?')}"

    # ── entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._icon.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    TrayApp().run()
