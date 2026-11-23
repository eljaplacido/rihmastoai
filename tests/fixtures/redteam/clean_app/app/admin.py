"""A small admin console, started beside the product by hand."""

import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

from flask import Flask

console = Flask(__name__)


def serve_files():
    HTTPServer(("127.0.0.1", 9000), SimpleHTTPRequestHandler).serve_forever()


def run_console():
    console.run(debug=os.environ.get("CONSOLE_DEBUG") == "1")
