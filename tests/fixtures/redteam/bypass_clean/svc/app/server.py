"""The server the container runs: it binds every interface, behind the platform's network rules."""

from http.server import HTTPServer, SimpleHTTPRequestHandler


def serve():
    HTTPServer(("0.0.0.0", 8080), SimpleHTTPRequestHandler).serve_forever()
