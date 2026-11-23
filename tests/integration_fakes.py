"""Local fakes for the integration edges' tests: every outbound call goes to one of these, on 127.0.0.1.

- ``Receiver``: an HTTP server that records each POST, and each GET a followed redirect would make
  (path, headers, body, method), and answers the status and Location it is told, so a test can take
  a receiver down, bring it back or have it redirect;
- ``FakeSmtp``: the few SMTP commands smtplib sends, recording each message it is handed.

Neither opens anything but a loopback socket.
"""

from __future__ import annotations

import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Receiver:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.status = 200
        self.location: str | None = None          # sent as Location: a receiver that redirects
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                status = owner.status
                owner.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                       "body": body, "status": status, "method": self.command})
                self.send_response(status)
                if owner.location:
                    self.send_header("Location", owner.location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST                      # a followed redirect arrives as a GET: it is recorded too

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def at(self, path: str) -> list[dict]:
        return [r for r in self.requests if r["path"] == path]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class FakeSmtp:
    """Enough of SMTP for smtplib.send_message: greeting, EHLO, MAIL, RCPT, DATA, QUIT."""

    def __init__(self) -> None:
        self.messages: list[bytes] = []
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def reply(self, line: str) -> None:
                self.wfile.write((line + "\r\n").encode("ascii"))

            def handle(self) -> None:
                self.reply("220 fake smtp")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    verb = line[:4].upper()
                    if verb == b"DATA":
                        self.reply("354 go on")
                        data = b""
                        while not data.endswith(b"\r\n.\r\n"):
                            chunk = self.rfile.readline()
                            if not chunk:
                                return
                            data += chunk
                        owner.messages.append(data[:-5])
                        self.reply("250 queued")
                    elif verb == b"QUIT":
                        self.reply("221 bye")
                        return
                    else:
                        self.reply("250 ok")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
