"""A small admin console, started beside the product by hand."""

from http.server import HTTPServer, SimpleHTTPRequestHandler

from flask import Flask

console = Flask(__name__)


def serve_files():
    HTTPServer(("0.0.0.0", 9000), SimpleHTTPRequestHandler).serve_forever()  # seeded: RT-PY-BINDALL


def run_console():
    console.run(debug=True)  # seeded: RT-PY-DEBUG
