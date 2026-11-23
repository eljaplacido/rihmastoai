"""Debug modes switched on by mapping, by position, and by the interactive debugger."""

from flask import Flask
from werkzeug.debug import DebuggedApplication

app = Flask(__name__)
app.config.update(DEBUG=True)  # seeded: RT-PY-DEBUG
application = DebuggedApplication(app, evalex=True)  # seeded: RT-PY-DEBUG


def main():
    app.run("127.0.0.1", 5000, True)  # seeded: RT-PY-DEBUG
