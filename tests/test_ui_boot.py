"""FR-T1-AC-18: the cockpit never sits on a blank page when its code cannot load.

In a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py): one of the page's modules is
refused, as a busy machine refuses a connection. The page reloads once by itself, then says it didn't finish loading,
with a Reload button; the one-use sign-in link in the address is still unused. Once the module is served again,
Reload signs in with that same link. Without Chrome only the static half runs: the boot guard is a classic script
loaded before the module, app.js tells it the page started, and the server queues enough connections.
"""

import contextlib
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import CockpitServer, make_server  # noqa: E402
from kernel.store import Factory  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "cockpit" / "static"
SIGNED_IN = "!document.documentElement.classList.contains('signed-out') && !!sessionStorage.getItem('gf.token')"


class BootGuardStaticTest(unittest.TestCase):
    def test_FR_T1_AC_18_the_boot_guard_loads_first_and_the_server_queues_the_pages_modules(self):
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        guard = index.find('<script src="/static/boot.js"></script>')       # classic: it runs even if modules fail
        self.assertGreater(guard, 0)
        self.assertLess(guard, index.find('<script type="module" src="/static/app.js"></script>'))
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("window.__rihmaBooted = true;", app)
        self.assertIn('sessionStorage.removeItem("gf.bootRetry")', app)
        boot = (STATIC / "boot.js").read_text(encoding="utf-8")
        self.assertNotRegex(boot, r"\.innerHTML|eval\(|setAttribute\(\"style\"")   # the strict CSP holds
        self.assertIn("location.reload()", boot)
        self.assertGreaterEqual(CockpitServer.request_queue_size, 64)
        modules = len(re.findall(r"\.js$", "\n".join(p.name for p in STATIC.glob("*.js")), re.M))
        self.assertGreater(modules, 5)                                 # why the default queue of 5 was not enough


class BootGuardUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-boot-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp)

    def test_FR_T1_AC_18_a_page_whose_code_cannot_load_retries_once_says_so_and_reload_signs_in(self):
        b = Browser(self.chrome, self.tmp / "chrome-boot")
        self.addCleanup(b.close)
        port = self.server.server_address[1]
        b.cmd("Network.enable")
        b.cmd("Network.setBlockedURLs", {"urls": ["*/static/words.js"]})      # one module app.js imports
        b.step = "a module refused"
        b.cmd("Page.navigate", {"url": f"http://127.0.0.1:{port}/#k={self.bootstrap}"})
        said = b.wait("(document.querySelector('[data-key=boot-failed]') || {}).innerText", "the boot failure, said")
        self.assertIn("didn't finish loading", said)
        self.assertEqual(b.eval("sessionStorage.getItem('gf.bootRetry')"), "1")       # it reloaded once by itself
        self.assertTrue(b.eval("document.documentElement.classList.contains('signed-out')"))
        self.assertTrue(b.eval("location.hash.startsWith('#k=')"))                      # the link is still unused
        self.assertTrue(b.eval("!!document.querySelector('[data-key=boot-reload]')"))
        b.cmd("Network.setBlockedURLs", {"urls": []})                                   # the server answers again
        b.problems.clear()                                 # the refused module was expected to fail
        b.step = "reload"
        b.click("[data-key=boot-reload]", what="Reload")
        b.wait(SIGNED_IN, "the signed-in page, from the same link")
        self.assertIsNone(b.eval("sessionStorage.getItem('gf.bootRetry')"))             # ready to retry next time
        self.assertFalse(b.eval("!!document.querySelector('[data-key=boot-failed]')"))
        b.eval("1")
        self.assertEqual(b.problems, [])
        self.assertEqual(b.violations(), [])


if __name__ == "__main__":
    unittest.main()
