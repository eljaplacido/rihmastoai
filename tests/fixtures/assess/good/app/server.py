"""The HTTP service. Its address and stock file come from the environment."""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.routes import app

log = logging.getLogger(__name__)
STOCK = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = "/health" if self.path == "/health" else "/stock"
        status, body = app.routes[("GET", route)](STOCK, self.path)
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


def main():
    host = os.environ.get("STOCK_HOST", "127.0.0.1")
    port = int(os.environ.get("STOCK_PORT", "8080"))
    log.info("serving stock levels on %s:%s", host, port)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
