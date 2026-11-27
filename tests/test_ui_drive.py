"""The cockpit in a real browser (FR-T1-AC-17): headless Chrome over the DevTools protocol.

The test builds a demo home (``kernel.demo``, what ``rihma demo`` builds), starts the cockpit on
127.0.0.1 over it, and drives the page as a person does, with real mouse clicks and typing: sign in
and say who is deciding, switch the lens, open the delivery square and validate a concept as a
business owner, open a project and decide a card, switch the lens there and change the theme and
density (kept with that lens's layout; the arrow keys switch the lens back), Customize (resize a
widget, Done), ask the
assistant a where-is question and press Take me there (to the Releases view, whose capability pack
is read and never built), switch to the Compliance lens (the demo's evidence pack and autonomy cap),
and open Settings (the demo's website chat). After every step there is no console error, no
uncaught exception, no failed request and no Content-Security-Policy violation.

Standard library only: the DevTools protocol goes over a WebSocket client written here on a plain
socket. It is skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary)
or git is missing for the demo. ``RIHMA_UI_SHOTS=<folder>`` also saves a screenshot per step.
"""

import base64
import contextlib
import hashlib
import http.client
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).parent))

from cockpit.server import make_server  # noqa: E402
from kernel import roads  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
# The page records every CSP violation it sees, from before its first script runs.
CSP_LISTENER = ("window.__cspViolations = [];"
                "document.addEventListener('securitypolicyviolation', (e) => window.__cspViolations.push("
                "e.violatedDirective + ' blocked ' + (e.blockedURI || 'inline')"
                " + ' at ' + (e.sourceFile || '?') + ':' + e.lineNumber));")


def find_chrome() -> str | None:
    """Chrome or Chromium on this machine, or None (then the test is skipped)."""
    named = os.environ.get("RIHMA_CHROME")
    if named:
        return named if Path(named).is_file() else None
    candidates = [Path(os.environ.get(v, "")) / "Google" / "Chrome" / "Application" / "chrome.exe"
                  for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(v)]
    candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for path in candidates:
        if path.is_file():
            return str(path)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    return None



# A shared CI runner is several times slower than a workstation: every wait gets that much longer there
# (GitHub sets CI=true), never shorter here. RIHMA_UI_SLOW overrides it.
SLOW = float(os.environ.get("RIHMA_UI_SLOW") or (3 if os.environ.get("CI") else 1))
# The machine running out of sockets (Windows' ERR_NO_BUFFER_SPACE under load) is the test bench's trouble,
# not the page's: a request the page retries on its next poll.
TRANSIENT = ("ERR_NO_BUFFER_SPACE", "ERR_NETWORK_IO_SUSPENDED")
if sys.platform == "win32":       # a long walk exhausts Windows' ephemeral ports: refused or reset, then it recovers
    TRANSIENT += ("ERR_CONNECTION_REFUSED", "ERR_CONNECTION_RESET", "ERR_CONNECTION_ABORTED")


def _transient(text: object) -> bool:
    return any(k in str(text or "") for k in TRANSIENT)

class WebSocket:
    """A minimal WebSocket client (RFC 6455) for the DevTools protocol on loopback: text frames out,
    masked; text frames in, possibly fragmented; pings answered."""

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        parts = urlsplit(url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self.sock.sendall((f"GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                           f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("the DevTools endpoint closed during the handshake")
            head += chunk
        header, self.buf = head.split(b"\r\n\r\n", 1)
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest())
        if b" 101 " not in header.split(b"\r\n")[0] or accept not in header:
            raise ConnectionError(f"no WebSocket upgrade: {header[:200]!r}")

    def send(self, text: str, opcode: int = 0x1) -> None:
        payload = text.encode("utf-8")
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", n)
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i & 3] for i, b in enumerate(payload)))

    def _exactly(self, n: int) -> bytes:
        out = bytearray(self.buf[:n])
        self.buf = self.buf[n:]
        while len(out) < n:
            chunk = self.sock.recv(max(65536, n - len(out)))
            if not chunk:
                raise ConnectionError("the DevTools endpoint closed")
            out += chunk
        if len(out) > n:
            self.buf, out = bytes(out[n:]) + self.buf, out[:n]
        return bytes(out)

    def recv(self) -> str:
        message = b""
        while True:
            b0, b1 = self._exactly(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._exactly(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._exactly(8))[0]
            payload = self._exactly(n)
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("the DevTools endpoint closed the connection")
            if opcode == 0x9:
                self.send(payload.decode("utf-8", "replace"), opcode=0xA)
                continue
            if opcode in (0x0, 0x1, 0x2):
                message += payload
                if b0 & 0x80:
                    return message.decode("utf-8")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.close()


def _get_json(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        return json.loads(conn.getresponse().read())
    finally:
        conn.close()


class Browser:
    """Headless Chrome with one page, driven over the DevTools protocol. Every console error, uncaught
    exception, failed request and CSP violation is kept with the step it happened in."""

    def __init__(self, chrome: str, profile: Path, width: int = 1440, height: int = 1000) -> None:
        self.profile = profile
        # A busy CI machine can take long to start Chrome, or start it without its DevTools port: it gets longer
        # there (SLOW), and one fresh start if the first one never opens the port.
        for attempt in (1, 2):
            self.proc = subprocess.Popen(
                [chrome, "--headless=new", f"--remote-debugging-port={os.environ.get('RIHMA_DEVTOOLS_PORT', '0')}",
                 f"--user-data-dir={profile}", "--no-first-run",
                 "--no-default-browser-check", "--no-proxy-server", "--disable-extensions", "--hide-scrollbars",
                 "--disable-background-networking", "--disable-component-update", "--mute-audio", "about:blank"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.port, self.browser_path = self._devtools_port()
                break
            except RuntimeError:
                self.proc.kill()
                self.proc.wait(10)
                shutil.rmtree(profile, ignore_errors=True)
                if attempt == 2:
                    raise
        page = None
        for _ in range(100):
            try:
                page = next((t for t in _get_json(self.port, "/json/list") if t.get("type") == "page"), None)
            except OSError:  # listening, but not answering yet
                page = None
            if page:
                break
            time.sleep(0.1)
        if page is None:
            raise RuntimeError("Chrome opened no page")
        self.ws = WebSocket(page["webSocketDebuggerUrl"])
        self.n, self.step, self.problems = 0, "start", []
        self.shots: Path | None = None                     # where a timed-out wait leaves a screenshot
        for method in ("Page.enable", "Runtime.enable", "Log.enable"):
            self.cmd(method)
        self.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": CSP_LISTENER})
        if os.environ.get("RIHMA_UI_FONT"):       # a wide fallback font, as a Linux runner has: layouts must still fit
            font = json.dumps(os.environ["RIHMA_UI_FONT"] + ", sans-serif")
            self.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": (   # a constructed sheet: the strict CSP allows it
                "{ const s = new CSSStyleSheet();"
                f" s.replaceSync(':root, body {{ --font-sans: ' + {font} + ' !important; }}');"
                " document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; }")})
        self.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                        "mobile": False})

    def _devtools_port(self) -> tuple[int, str]:
        marker = self.profile / "DevToolsActivePort"
        for _ in range(int(300 * SLOW)):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chrome exited with {self.proc.returncode}")
            try:
                port, path = marker.read_text(encoding="utf-8").split("\n")[:2]
                return int(port), path.strip()
            except (OSError, ValueError):
                fixed = int(os.environ.get("RIHMA_DEVTOOLS_PORT") or 0)    # a port of its own writes no marker
                try:
                    if fixed:
                        url = _get_json(fixed, "/json/version")["webSocketDebuggerUrl"]
                        return fixed, "/" + url.split("/", 3)[3]
                except (OSError, ValueError, KeyError, IndexError):
                    pass
                time.sleep(0.1)
        raise RuntimeError("Chrome did not open its DevTools port")

    def _note(self, msg: dict) -> None:
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "Runtime.exceptionThrown":
            d = params.get("exceptionDetails") or {}
            text = (d.get("exception") or {}).get("description") or d.get("text")
            self.problems.append((self.step, "exception", text))
        elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert"):
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args") or [])
            self.problems.append((self.step, "console." + params["type"], text))
        elif method == "Log.entryAdded":
            e = params.get("entry") or {}
            if (e.get("level") == "error" or e.get("source") == "security") and not _transient(e.get("text")):
                self.problems.append((self.step, f"log:{e.get('source')}:{e.get('level')}", e.get("text")))
            elif _transient(e.get("text")):
                self.passing = (getattr(self, "passing", []) + [(self.step, e.get("url") or e.get("text"))])[-8:]

    def cmd(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result") or {}
            self._note(msg)

    def eval(self, expression: str):
        out = self.cmd("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        if out.get("exceptionDetails"):
            d = out["exceptionDetails"]
            raise RuntimeError(f"the driver's script failed: {(d.get('exception') or {}).get('description') or d}")
        return (out.get("result") or {}).get("value")

    def state(self) -> str:
        """What the page shows, for a timeout's message: where it is, whether it is signed in, and its first words."""
        try:
            return str(self.eval("JSON.stringify({url: location.href.replace(/#k=[^&]*/, '#k=…'), ready: document.readyState,"
                                 " html: document.documentElement.className, token: !!sessionStorage.getItem('gf.token'),"
                                 " text: (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 300)})"))
        except (RuntimeError, OSError) as e:
            return f"unreadable ({e})"

    def wait(self, expression: str, what: str, timeout: float = 20.0):
        end = time.monotonic() + timeout * SLOW
        while True:
            try:
                value = self.eval(expression)
            except RuntimeError:
                # While a page navigates, the document can be briefly empty (documentElement is
                # null), so a waited-for expression may throw; that is not yet, not a failure.
                if time.monotonic() > end:
                    raise
                time.sleep(0.05)
                continue
            if value:
                return value
            if time.monotonic() > end:
                if self.shots:
                    self.shots.mkdir(parents=True, exist_ok=True)
                    self.screenshot(self.shots / f"timeout-{self.step.replace(' ', '-')}.png")
                raise AssertionError(f"[{self.step}] timed out waiting for {what}; problems so far: {self.problems}; "
                                     f"the page: {self.state()}; transient network errors: {getattr(self, 'passing', [])}")
            time.sleep(0.1)

    def click(self, selector: str, text: str | None = None, what: str | None = None) -> None:
        """A real mouse click at the centre of the first visible element that matches (and holds the
        text), once it stands still (a drawer that slides in moves its buttons); it fails when another
        element covers that point."""
        find = (f"Array.from(document.querySelectorAll({json.dumps(selector)})).find((e) => e.getClientRects().length"
                f" && (!{json.dumps(text)} || e.textContent.includes({json.dumps(text)})))")
        box = self.wait(f"""(async () => {{ const el = {find}; if (!el) return null;
            el.scrollIntoView({{block: "center", inline: "center"}});
            const at = () => {{ const r = el.getBoundingClientRect();
                                return [r.left, r.top, r.width, r.height].join(); }};
            const before = at(); await new Promise((done) => setTimeout(done, 150));
            if (at() !== before) return null;
            const r = el.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2, hit = document.elementFromPoint(x, y);
            return {{x, y, ok: !!hit && (el === hit || el.contains(hit) || hit.contains(el)),
                     hit: hit ? hit.tagName + "." + hit.className : null}}; }})()""",
                        what or f"{selector} {text or ''}")
        if not box["ok"]:
            raise AssertionError(f"[{self.step}] {what or selector} is covered by {box['hit']}")
        for kind in ("mousePressed", "mouseReleased"):
            self.cmd("Input.dispatchMouseEvent", {"type": kind, "x": box["x"], "y": box["y"], "button": "left",
                                                  "clickCount": 1})

    def key(self, key: str, code: int) -> None:
        """Press and release a key (by its name and Windows key code) on whatever has the focus."""
        for kind in ("rawKeyDown", "keyUp"):
            self.cmd("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code,
                                                "nativeVirtualKeyCode": code})

    def active(self) -> str:
        """What has the focus: its id, else its lens, else its tag."""
        return self.eval("(() => { const a = document.activeElement;"
                         " return a ? a.id || (a.dataset && a.dataset.lens) || a.tagName : null; })()")

    def type(self, selector: str, text: str) -> None:
        """Focus a field, clear it and type into it, as keyboard input."""
        self.wait(f"(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;"
                  " el.focus(); el.select && el.select(); return document.activeElement === el; })()", selector)
        self.cmd("Input.insertText", {"text": text})

    def screenshot(self, path: Path) -> None:
        shot = self.cmd("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(shot["data"]))

    def violations(self) -> list:
        return self.eval("window.__cspViolations || ['the CSP listener did not run']") or []

    def close(self) -> None:
        try:
            ws = WebSocket(f"ws://127.0.0.1:{self.port}{self.browser_path}", timeout=5)
            ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            ws.close()
            self.proc.wait(10)
        except (OSError, ConnectionError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait(10)
        finally:
            self.ws.close()
            shutil.rmtree(self.profile, ignore_errors=True)


class QuietRunner:
    """The cockpit's job runner in this test: it starts nothing, and records what it was asked."""

    def __init__(self) -> None:
        self.started: list = []

    def start(self, args: list, log_path) -> str:
        self.started.append(list(args))
        return f"J-{len(self.started):04d}"

    def status(self, job_id: str) -> dict:
        return {"state": "done", "code": 0}


class UiDriveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-drive-")).resolve()
        try:
            build_demo(cls.tmp / "demo", echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(cls.tmp / "demo")
        cls.runner = QuietRunner()
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):  # a file Chrome still holds: the OS clears the temp folder later
            roads.rmtree(cls.tmp)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / f"chrome-{self.id().rsplit('.', 1)[-1][:12]}")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def step(self, name: str) -> None:
        """Start a step: the previous one must have left no problem behind."""
        if self.browser.step != "start":                # about:blank opened before the CSP listener
            self.check()
        self.browser.step = name

    def check(self) -> None:
        b = self.browser
        b.eval("1")                                    # drain the events that arrived meanwhile
        time.sleep(0.3)
        b.eval("1")
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"{b.step.replace(' ', '-')}.png")

    def project(self, title: str):
        return next(p for p in self.factory.projects() if p.meta.get("title") == title)

    def test_FR_T1_AC_17_a_person_drives_the_cockpit_in_chrome_with_no_console_error_or_csp_violation(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.step("switch lens")
        b.click('#lens-switch [data-lens="delivery"]', what="the Delivery lens")
        b.wait("document.title.startsWith('Delivery') && !!document.querySelector('#grid .widget[data-type=\"live\"]')",
               "the Delivery dashboard")
        self.assertEqual(b.active(), "delivery")                    # choosing a lens keeps the focus on it
        self.assertEqual(b.eval("[...document.querySelectorAll('#lens-switch .lens-b')].filter((x) => x.tabIndex === 0)"
                                ".map((x) => x.dataset.lens).join()"), "delivery")   # one tab stop: the chosen lens
        self.step("validate a concept")
        self.validate_concept()
        self.step("decide a card")
        webhook = self.decide_a_card()
        self.step("theme off Home")
        self.theme_off_home()
        self.step("customize")
        self.customize()
        self.step("ask the assistant")
        self.take_me_there(webhook)
        self.step("compliance lens")
        self.compliance_lens()
        self.step("settings")
        b.click('#sb-foot a[href="#/settings"]', what="Settings")
        note = "(document.querySelector('[aria-labelledby=\"embeds-h\"] .note.warning') || {}).textContent"
        self.assertIn("http://127.0.0.1:8790", b.wait(note, "the embed address note"))
        row = b.wait("(document.querySelector('.emb-list .emb-row') || {}).textContent", "the demo's website chat")
        for said in ("Warehouse feedback", "E-001", "Feedback on Shipment webhook to the stock system",
                     "https://warehouse.example", "1 message", "by demo-product", "Active"):
            self.assertIn(said, row)
        self.check()
        self.assertEqual(self.runner.started, [])                  # nothing in the drive started a job
        # the watch itself: an inline style and a console error made on purpose are both seen
        b.step = "probe"
        b.eval("document.body.setAttribute('style', 'outline: 0'); console.error('rihma probe'); true")
        b.wait("window.__cspViolations.length > 0", "the probe's CSP violation")
        self.assertIn("style-src", b.violations()[0])
        self.assertIn(("probe", "console.error", "rihma probe"), b.problems)

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out')"
               " && !!document.querySelector('#grid .widget')", "the signed-in dashboard")
        self.assertEqual(b.eval("location.hash"), "#/home")         # the one-use link left the address bar
        self.assertTrue(b.eval("!!sessionStorage.getItem('gf.token')"))
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}"
               " && document.querySelector('#pc-persona').textContent === 'Business owner'", "the person chip")

    def validate_concept(self) -> None:
        b = self.browser
        b.click('#sb-nav a[href="#/square"]', what="Square in the sidebar")
        b.wait("!!document.querySelector('.concepts .concept')", "a concept on the square")
        title = b.eval("document.querySelector('.concepts .concept .concept-h b').textContent")
        b.type('.concepts .concept input[aria-label="Reason"]', "Worth a demo for the maintenance team")
        b.click('.concepts [data-control="validate_concept"]', what="Validate")
        b.wait(f"location.hash.startsWith('#/p/') && (document.querySelector('#view-title') || {{}}).textContent === "
               f"{json.dumps(title)}", "the new project opened")
        self.assertEqual(b.eval("window.scrollY"), 0)                 # a new page opens at its top
        decision = next(c for c in Canon(factory_project(self.factory)).cards(state=None, kind="concept"))["decision"]
        self.assertEqual((decision["verdict"], decision["person"], decision["persona"]),
                         ("validate", PERSON, "business_owner"))
        self.assertIn(title, [p.meta.get("title") for p in self.factory.projects()])

    def decide_a_card(self):
        b = self.browser
        webhook = self.project("Shipment webhook to the stock system")
        b.click('#sb-nav a[href="#/projects"]', what="Projects in the sidebar")
        b.click(".proj-card", text="Shipment webhook", what="the webhook project")
        b.wait(f"location.hash.startsWith('#/p/{webhook.pid}')", "the webhook project")
        b.click(f'.tabs a[href="#/p/{webhook.pid}/inbox"]', what="the project's Inbox tab")   # in the Now capsule
        key = b.wait("(document.querySelector('.card.decision [data-key$=\":defer\"]') || {dataset: {}}).dataset.key",
                     "a card to defer")
        cid = key.split(":")[0]
        # FR-UXO1: the choice first, then Why (optional, saved with the decision), then Confirm
        b.click(f'[data-key="{key}"]', what=f"Defer on {cid}")
        b.type(f"#reason-{cid}", "Not before the stock system's own release")
        b.click(f'[data-key="{cid}:confirm"]', what=f"Confirm on {cid}")
        b.wait(f"!document.querySelector('[data-key=\"{key}\"]')", f"{cid} decided")
        card = Canon(webhook).get_card(cid)
        self.assertEqual((card["state"], card["decision"]["verdict"], card["decision"]["person"]),
                         ("decided", "defer", PERSON))
        return webhook

    def theme_off_home(self) -> None:
        """On a project page, switch to the Operations lens, choose Light and compact density: both are kept
        with the Operations layout (never the Delivery one Home loaded, which the server refuses), the focus
        goes back to Theme, and the arrow keys take the lens back to Delivery with the focus on it."""
        b = self.browser
        b.click('#lens-switch [data-lens="operations"]', what="the Operations lens")
        b.wait("document.querySelector('#lens-switch [aria-checked=\"true\"]').dataset.lens === 'operations'",
               "the Operations lens chosen")
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text="Light", what="Light in the theme menu")
        b.wait("document.documentElement.dataset.theme === 'light' && document.activeElement.id === 'theme'",
               "the light theme, with the focus back on Theme")
        b.click("#density", what="Density")
        b.wait("document.documentElement.dataset.density === 'compact'", "the compact density")
        path = next(iter((self.factory.home / "_cockpit" / "layouts").glob("*/business_owner")), None)
        end = time.monotonic() + 20
        theme = None
        while time.monotonic() < end and (theme or {}).get("density") != "compact":
            saved = path / "operations.json" if path else None
            if saved and saved.is_file():
                theme = json.loads(saved.read_text(encoding="utf-8"))["layout"].get("theme")
            time.sleep(0.1)
        self.assertEqual(((theme or {}).get("mode"), (theme or {}).get("density")), ("light", "compact"))
        self.assertEqual(b.eval("document.documentElement.dataset.theme"), "light")   # the density kept the light theme
        b.eval("document.querySelector('#lens-switch [data-lens=\"operations\"]').focus(); true")
        b.key("ArrowLeft", 37)
        b.wait("document.querySelector('#lens-switch [aria-checked=\"true\"]').dataset.lens === 'delivery'"
               " && document.activeElement.dataset.lens === 'delivery'", "the Delivery lens again, by the arrow key")

    def customize(self) -> None:
        b = self.browser
        b.click('#sb-nav a[href="#/home"]', what="Home in the sidebar")
        b.wait("!!document.querySelector('#grid .widget')", "the dashboard")
        b.click("#customize", what="Customize")
        b.wait("!document.querySelector('#cz-bar').hidden && !!document.querySelector('#grid .widget.cz')", "Customize")
        wid, before = b.eval("(() => { const w = document.querySelector('#grid .widget.cz');"
                             " return [w.dataset.wid, w.className.match(/size-(\\w+)/)[1]]; })()")
        b.click(f'#grid .widget[data-wid="{wid}"] button[data-fk="size"]', what="the size button")
        after = b.wait(f"(() => {{ const w = document.querySelector('#grid .widget[data-wid=\"{wid}\"]');"
                       " const s = w && w.className.match(/size-(\\w+)/)[1];"
                       f" return s !== {json.dumps(before)} && s; }})()", "the widget resized")
        b.click("#cz-bar button", text="Done", what="Done")
        b.wait("document.querySelector('#cz-bar').hidden"
               " && !document.documentElement.classList.contains('customizing')", "Customize closed")
        saved = [json.loads(p.read_text(encoding="utf-8"))
                 for p in (self.factory.home / "_cockpit" / "layouts").rglob("delivery.json")]
        self.assertEqual([(s["person"], s["persona"]) for s in saved], [(PERSON, "business_owner")])
        sizes = [{"id": w["id"], "size": w["size"]} for w in saved[0]["layout"]["widgets"]]
        self.assertIn({"id": wid, "size": after}, sizes)
        self.assertEqual(b.eval("document.querySelector('.layout-kind').textContent"), "Your layout")

    def compliance_lens(self) -> None:
        """The demo's evidence pack and autonomy cap, as the Compliance lens shows them: read only."""
        b = self.browser
        b.click('#sb-nav a[href="#/home"]', what="Home in the sidebar")
        b.wait("!!document.querySelector('#grid .widget')", "the dashboard")
        b.click('#lens-switch [data-lens="compliance"]', what="the Compliance lens")
        packs = b.wait("document.title.startsWith('Compliance')"
                       " && (document.querySelector('#grid .widget[data-type=\"evidence_packs\"] .ev-list') || {}).textContent",
                       "the Evidence packs widget")
        row = next(line for line in b.eval("[...document.querySelectorAll('#grid .ev-row')].map((r) => r.textContent)")
                   if "Shipment webhook" in line)
        for said in ("Attestable", "release 1.0 ready to hand over", "decision record intact"):   # in a business owner's words
            self.assertIn(said, row)
        self.assertIn("Access review check", packs)
        autonomy = b.wait("(document.querySelector('#grid .widget[data-type=\"autonomy\"] .autonomy') || {}).textContent",
                          "the Autonomy widget")
        self.assertIn("Lower caps: Access review check 3", autonomy)

    def take_me_there(self, webhook) -> None:
        b = self.browser
        b.click('#sb-nav a[href="#/projects"]', what="Projects in the sidebar")
        b.click(".proj-card", text="Shipment webhook", what="the webhook project")
        title = json.dumps(webhook.meta["title"])
        b.wait(f"location.hash.startsWith('#/p/{webhook.pid}')"
               f" && (document.querySelector('#view-title') || {{}}).textContent === {title}", "the project")
        records, packs = len(webhook.ledger().records()), webhook.read("packs.json")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "Where are the releases?")
        b.click("#as-send", what="Send")
        b.click("#as-log .msg.bot button", text="Take me there", what="Take me there")
        b.wait(f"location.hash === '#/p/{webhook.pid}/releases' && !!document.querySelector('.card.pack')",
               "the Releases view with its capability pack")
        # the capability pack, in a business owner's words (cockpit/static/words.js)
        self.assertIn("Release package v1.0.0", b.eval("document.querySelector('.card.pack').textContent"))
        self.assertEqual((len(webhook.ledger().records()), webhook.read("packs.json")), (records, packs))


if __name__ == "__main__":
    unittest.main()
