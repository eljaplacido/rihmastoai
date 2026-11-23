"""The product's HTTP server: the container's entry point (the Dockerfile's CMD runs it)."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTES = {}


def route(method, pattern):
    def register(fn):
        ROUTES[(method, pattern)] = fn
        return fn
    return register


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"path": self.path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def main():
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")  # the container's entry point: all interfaces are expected here
    ThreadingHTTPServer((host, port), Handler).serve_forever()
