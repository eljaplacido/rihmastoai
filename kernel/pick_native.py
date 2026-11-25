"""The computer's own folder or file dialog, opened on the cockpit's machine (FR-PICK1; docs/guides/inputs.md).

Browse… in the cockpit opens the operating system's own dialog when the person sits at the cockpit's machine:
the request comes from the loopback browser of a single operator's cockpit (never under enforced access, and
never through a public origin: the cockpit route says so). The dialog runs in a child process, so a dialog that
hangs never holds the cockpit:

- Windows and anything with Tk: ``python -c`` with tkinter's ``askdirectory`` or ``askopenfilename`` on a hidden,
  topmost window (on Windows that is Explorer's own dialog);
- macOS: ``osascript`` ``choose folder`` or ``choose file``;
- Linux: ``zenity`` or ``kdialog`` when present, else tkinter, with a display; else it is not available here.

One dialog at a time, for at most ten minutes; ``cancel()`` closes the one open now (the page offers Browse here
instead while it is open, for a person who is not at this machine). ``RIHMA_PICK_COMMAND`` (a JSON list: a program and its first
arguments) stands in for the dialog in tests: it is given the kind, the title and the folder to start in, and
prints the chosen path, or nothing when cancelled. Opening a dialog records nothing; what is chosen is checked
by kernel/source_guard.py before any use.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading

PICK_ENV = "RIHMA_PICK_COMMAND"
TIMEOUT = 600.0          # seconds a dialog may stay open
KINDS = ("folder", "file")
_ONE = threading.Lock()  # one dialog at a time on this machine
_OPEN: dict[str, subprocess.Popen[bytes]] = {}   # the dialog open now, so it can be cancelled
TK = ("import sys, tkinter as tk\n"
      "from tkinter import filedialog\n"
      "kind, title, start = sys.argv[1:4]\n"
      "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); root.update()\n"
      "opts = {'parent': root, 'title': title, 'initialdir': start or None}\n"
      "ask = filedialog.askopenfilename\n"
      "if kind == 'folder':\n"
      "    got = filedialog.askdirectory(mustexist=True, **opts)\n"
      "else:\n"
      "    got = ask(**opts)\n"
      "root.destroy()\n"
      "sys.stdout.buffer.write(str(got or '').encode('utf-8'))\n")
OSA = ("on run argv\n"
       "  if item 1 of argv is \"folder\" then\n"
       "    return POSIX path of (choose folder with prompt (item 2 of argv))\n"
       "  end if\n"
       "  return POSIX path of (choose file with prompt (item 2 of argv))\n"
       "end run")


class NativeUnavailable(RuntimeError):
    """No dialog can be opened on this machine (no display, no tool)."""


class NativeBusy(RuntimeError):
    """A dialog is open already."""


def _stand_in() -> list[str] | None:
    raw = os.environ.get(PICK_ENV, "").strip()
    if not raw:
        return None
    try:
        argv = json.loads(raw)
    except ValueError:
        return [raw]
    return [str(a) for a in argv] if isinstance(argv, list) and argv else None


def _display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _tk() -> bool:
    return importlib.util.find_spec("tkinter") is not None


def _linux(kind: str, title: str, start: str) -> list[str] | None:
    if not _display():
        return None
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", *(["--directory"] if kind == "folder" else []), f"--title={title}",
                *([f"--filename={start.rstrip('/')}/"] if start else [])]
    if shutil.which("kdialog"):
        verb = "--getexistingdirectory" if kind == "folder" else "--getopenfilename"
        return ["kdialog", verb, start or os.path.expanduser("~"), "--title", title]
    return [sys.executable, "-c", TK, kind, title, start] if _tk() else None


def command(kind: str, title: str, start: str) -> list[str] | None:
    """The child process that opens the dialog, or None when none can be opened here."""
    stand_in = _stand_in()
    if stand_in is not None:
        return [*stand_in, kind, title, start]
    if sys.platform == "darwin":
        return ["osascript", "-e", OSA, kind, title] if shutil.which("osascript") else None
    if os.name == "nt":
        return [sys.executable, "-c", TK, kind, title, start] if _tk() else None
    return _linux(kind, title, start)


def tool() -> str | None:
    """What would open the dialog here ("stand-in", "tkinter", "osascript", "zenity", "kdialog"), or None."""
    argv = command("folder", "", "")
    if argv is None:
        return None
    if _stand_in() is not None:
        return "stand-in"
    return "tkinter" if argv[0] == sys.executable else os.path.basename(argv[0])


def busy() -> bool:
    return _ONE.locked()


def _run(argv: list[str], timeout: float) -> str | None:
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise NativeUnavailable(f"the dialog could not be opened: {exc}") from None
    _OPEN["dialog"] = proc
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None
    finally:
        _OPEN.pop("dialog", None)
    picked = out.decode("utf-8", "replace").strip().splitlines()
    return picked[0].strip() if proc.returncode == 0 and picked and picked[0].strip() else None


def cancel() -> bool:
    """Close the dialog open now, which then answers cancelled: the person is not at this machine (say, the
    page came through an SSH tunnel) and browses in the page instead. True when one was open."""
    proc = _OPEN.get("dialog")
    if proc is None or proc.poll() is not None:
        return False
    proc.kill()
    return True


def choose(kind: str, title: str = "", start: str = "", *, timeout: float = TIMEOUT) -> str | None:
    """Open the dialog and wait for the person: the chosen path, or None (cancelled, or open too long)."""
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    argv = command(kind, title or ("Choose a folder" if kind == "folder" else "Choose a file"),
                   start if start and os.path.isdir(start) else "")
    if argv is None:
        raise NativeUnavailable("no folder dialog can be opened on this machine (no display, or no dialog tool): "
                                "use the folder browser")
    if not _ONE.acquire(blocking=False):
        raise NativeBusy("a folder dialog is open on this machine already: finish it first")
    try:
        return _run(argv, timeout)
    finally:
        _ONE.release()
