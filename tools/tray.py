#!/usr/bin/env python3
"""
scuf-tray — system tray for the SCUF Envision Pro V2 driver.

Polls the driver IPC socket every 3 s and reflects connection state, battery
level, active profile, and RGB mode in a notification-area icon with a menu.

Requires: pystray, pillow
"""

import json
import socket
import threading
import time
from PIL import Image, ImageDraw
import pystray

SOCKET_PATH = "/run/scuf-envision/ipc.sock"
POLL_INTERVAL = 3.0


def _ipc(cmd: str) -> str | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(SOCKET_PATH)
            s.sendall((cmd + "\n").encode())
            return b"".join(iter(lambda: s.recv(4096), b"")).decode().strip()
    except OSError:
        return None


def _make_icon(r: int, g: int, b: int) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((4, 4, 60, 60), fill=(r, g, b, 255))
    return img


ICON_CONNECTED = _make_icon(0, 200, 80)    # green  — wired
ICON_WIRELESS  = _make_icon(255, 200, 0)   # yellow — wireless
ICON_OFFLINE   = _make_icon(200, 60, 60)   # red    — driver offline / searching


class TrayApp:
    def __init__(self):
        self._state: dict = {}
        self._lock = threading.Lock()
        self._icon = pystray.Icon(
            "scuf-envision",
            ICON_OFFLINE,
            "SCUF Envision — offline",
            menu=pystray.Menu(self._build_menu),
        )

    # ── menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        with self._lock:
            state = dict(self._state)

        if not state:
            status_text = "Driver not running"
        elif state.get("status") == "searching_for_controller":
            status_text = "Searching for controller\u2026"
        else:
            status_text = f"Connected ({state.get('connection', '?')})"

        items = [pystray.MenuItem(status_text, None, enabled=False)]

        battery = state.get("battery", -1)
        if isinstance(battery, int) and battery >= 0:
            items.append(pystray.MenuItem(f"Battery: {battery}%", None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)

        # Profile submenu
        profiles = state.get("profiles", [])
        active   = state.get("profile", "default")
        if profiles:
            def _profile_item(name):
                return pystray.MenuItem(
                    name,
                    lambda _icon, _item, n=name: self._switch_profile(n),
                    checked=lambda _item, n=name: self._state.get("profile") == n,
                    radio=True,
                )
            items.append(pystray.MenuItem(
                f"Profile: {active}",
                pystray.Menu(*[_profile_item(p) for p in profiles]),
            ))

        items.append(pystray.Menu.SEPARATOR)

        # RGB submenu
        rgb_ok = state.get("rgb", False)
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
            self._state = json.loads(raw) if raw else {}
        self._refresh_icon()

    def _poll_loop(self) -> None:
        while True:
            self._poll_once()
            time.sleep(POLL_INTERVAL)

    def _refresh_icon(self) -> None:
        with self._lock:
            state = dict(self._state)
        if not state:
            self._icon.icon  = ICON_OFFLINE
            self._icon.title = "SCUF Envision \u2014 driver offline"
        elif state.get("status") == "searching_for_controller":
            self._icon.icon  = ICON_OFFLINE
            self._icon.title = "SCUF Envision \u2014 searching\u2026"
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
    TrayApp().run()
