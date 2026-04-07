"""Unix domain socket IPC server for scuf-ctl commands.

Integrates with the bridge's select.poll() loop — register fileno() in poll(),
call handle_request() on POLLIN. Each request is handled synchronously:
accept → recv (100 ms timeout) → dispatch → send response → close client.
"""

import json
import logging
import os
import socket
import struct

log = logging.getLogger(__name__)

SOCKET_PATH = "/run/scuf-envision/ipc.sock"
_RECV_TIMEOUT = 0.1  # seconds; SO_RCVTIMEO on each accepted client


class IPCServer:
    """Non-blocking Unix socket server for scuf-ctl commands."""

    def __init__(self, socket_path: str = SOCKET_PATH):
        self._path = socket_path
        os.makedirs(os.path.dirname(socket_path), mode=0o755, exist_ok=True)
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.setblocking(False)
        self._sock.bind(socket_path)
        os.chmod(socket_path, 0o666)
        self._sock.listen(1)
        log.info("IPC socket: %s", socket_path)

    def fileno(self) -> int:
        return self._sock.fileno()

    def handle_request(self, profile_mgr, state: dict,
                       extras: dict | None = None) -> None:
        """Accept one client, dispatch command, send response, close."""
        try:
            client, _ = self._sock.accept()
        except OSError:
            return
        try:
            # 100 ms timeout so a stalled client can't block the event loop
            tv = struct.pack("ll", 0, int(_RECV_TIMEOUT * 1_000_000))
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, tv)
            data = client.recv(4096).decode(errors="replace").strip()
            if data:
                response = self._dispatch(data, profile_mgr, state, extras)
                client.sendall((response + "\n").encode())
        except OSError:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _dispatch(self, cmd: str, profile_mgr, state: dict,
                  extras: dict | None = None) -> str:
        if cmd == "ping":
            return "pong"

        if cmd == "status":
            if profile_mgr is None:
                return json.dumps({"status": "searching_for_controller"})
            return json.dumps({**state, "profile": profile_mgr.active_name,
                                "profiles": profile_mgr.list_profiles()})

        if cmd.startswith("profile "):
            if profile_mgr is None:
                return "error: controller not connected yet"
            name = cmd[len("profile "):].strip()
            try:
                profile_mgr.switch(name)
                cb = (extras or {}).get("on_profile_switch")
                if cb:
                    cb()
                return "ok"
            except KeyError:
                return f"error: unknown profile '{name}'"

        if cmd.startswith("rgb "):
            set_rgb = (extras or {}).get("set_rgb")
            if set_rgb is None:
                return "error: rgb not available"
            return self._dispatch_rgb(cmd[4:].strip(), set_rgb)

        return "error: unknown command"

    @staticmethod
    def _parse_hex(s: str) -> tuple[int, int, int] | None:
        s = s.lstrip("#")
        if len(s) != 6:
            return None
        try:
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        except ValueError:
            return None

    def _dispatch_rgb(self, args: str, set_rgb) -> str:
        from .rgb import RGB_MODES
        from .config import rgb_color, rgb_color2, rgb_speed, rgb_brightness

        parts = args.split()
        if not parts:
            return "error: missing mode"

        mode = parts[0]

        # Backward compat: bare hex color → static
        if len(mode) == 6 and all(c in "0123456789abcdefABCDEF" for c in mode):
            color = self._parse_hex(mode)
            if color is None:
                return "error: invalid hex color"
            r2, g2, b2 = rgb_color2()
            set_rgb("static", r=color[0], g=color[1], b=color[2],
                    r2=r2, g2=g2, b2=b2, brightness=rgb_brightness(), speed=rgb_speed())
            return "ok"

        if mode not in RGB_MODES:
            return f"error: unknown mode '{mode}' (valid: {', '.join(RGB_MODES)})"

        # Defaults from config
        r, g, b = rgb_color()
        r2, g2, b2 = rgb_color2()
        speed = rgb_speed()
        brightness = rgb_brightness()
        rest = parts[1:]

        try:
            # Modes that accept: [color] [color2] [speed]
            if mode in ("colorpulse", "colorshift", "storm", "flickering"):
                if rest:
                    c = self._parse_hex(rest[0])
                    if c is None:
                        return f"error: invalid hex color '{rest[0]}'"
                    r, g, b = c
                    rest = rest[1:]
                if rest:
                    c = self._parse_hex(rest[0])
                    if c is None:
                        return f"error: invalid hex color '{rest[0]}'"
                    r2, g2, b2 = c
                    rest = rest[1:]
                if rest and mode != "storm":
                    speed = float(rest[0])
            # Modes that accept: [color] [speed]
            elif mode in ("breathe", "static"):
                if rest:
                    c = self._parse_hex(rest[0])
                    if c is None:
                        return f"error: invalid hex color '{rest[0]}'"
                    r, g, b = c
                    rest = rest[1:]
                if rest and mode != "static":
                    speed = float(rest[0])
            # Modes that accept only [speed]
            elif mode in ("rainbow", "pastelrainbow", "watercolor", "rotator", "cpu-temperature"):
                if rest:
                    speed = float(rest[0])
            # off: no params
        except (ValueError, IndexError) as e:
            return f"error: bad argument — {e}"

        set_rgb(mode, r=r, g=g, b=b, r2=r2, g2=g2, b2=b2, speed=speed, brightness=brightness)
        return "ok"

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            os.unlink(self._path)
        except OSError:
            pass
