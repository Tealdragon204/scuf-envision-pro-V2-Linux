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

    def handle_request(self, profile_mgr, state: dict) -> None:
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
                response = self._dispatch(data, profile_mgr, state)
                client.sendall((response + "\n").encode())
        except OSError:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _dispatch(self, cmd: str, profile_mgr, state: dict) -> str:
        if cmd == "ping":
            return "pong"

        if cmd == "status":
            return json.dumps({**state, "profile": profile_mgr.active_name,
                                "profiles": profile_mgr.list_profiles()})

        if cmd.startswith("profile "):
            name = cmd[len("profile "):].strip()
            try:
                profile_mgr.switch(name)
                return "ok"
            except KeyError:
                return f"error: unknown profile '{name}'"

        return "error: unknown command"

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            os.unlink(self._path)
        except OSError:
            pass
