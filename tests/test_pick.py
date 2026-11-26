"""FR-PICK1: choose a folder or a file by browsing (kernel/pick.py, kernel/pick_native.py, cockpit/pick_routes.py).

The places to start from, one folder's contents with git and project badges and a readable flag, never outside
the allowed folders' rules or through a link out of them, the computer's own dialog through a stand-in (chosen,
cancelled, refused from another computer, one at a time), the recent folders kept per person, and chat parity:
Ask Rihma's words propose the same flow, and every path field of the page offers Browse.
"""

import json
import os
import re
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_brief_ln import NON_PERSON, tree  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from kernel import pick as kpick  # noqa: E402
from kernel import pick_native as knative  # noqa: E402
from kernel import walkthrough_intent  # noqa: E402
from kernel.source_guard import ROOTS_ENV, SourceRefused  # noqa: E402

WHO = {"person": "Aino Tester", "persona": "developer"}
Q = "person=Aino%20Tester&persona=developer"
SYSTEM = "C:\\Windows" if os.name == "nt" else "/etc"


def stand_in(code: str) -> str:
    """RIHMA_PICK_COMMAND for a dialog that runs ``code`` (its argv: kind, title, start) instead of opening."""
    return json.dumps([sys.executable, "-c", code])


def make_link(link: Path, target: Path) -> None:
    """A link to a folder: a symbolic link, or a junction where Windows allows no symbolic link."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


class PickTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = self.tmp.resolve()
        self.root = self.tmp / "dev"
        self.root.mkdir()
        self.outside = self.tmp / "elsewhere"
        self.outside.mkdir()
        for p in (mock.patch.dict(os.environ, {ROOTS_ENV: str(self.root)}),
                  mock.patch("pathlib.Path.home", return_value=self.tmp / "me")):
            p.start()
            self.addCleanup(p.stop)
        (self.tmp / "me").mkdir()

    def listing(self, path, files=False):
        return self.call("GET", f"/api/pick/list?{Q}&files={int(files)}&path={urllib.request.quote(str(path))}")

    # -- places ------------------------------------------------------------------------------------------

    def test_FR_PICK1_AC_1_places_are_recent_folders_the_roots_home_and_drives_with_readable_flags(self):
        app = self.root / "app"
        app.mkdir()
        status, out, _ = self.call("POST", "/api/pick/recent", {"path": str(app), **WHO})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["recent"], [str(app)])
        status, out, _ = self.call("GET", f"/api/pick/places?{Q}")
        self.assertEqual(status, 200, out)
        kinds = [p["kind"] for p in out["places"]]
        self.assertEqual(kinds[:3], ["recent", "root", "home"])
        self.assertIn("drive", kinds)
        recent, root, home = out["places"][:3]
        self.assertEqual((recent["path"], root["path"], home["path"]), (str(app), str(self.root), str(self.tmp / "me")))
        self.assertTrue(all(p["readable"] for p in (recent, root, home)))
        drive = next(p for p in out["places"] if p["kind"] == "drive")
        self.assertFalse(drive["readable"])
        self.assertIn("outside your home folder", drive["why"])
        self.assertEqual(len({os.path.normcase(p["path"]) for p in out["places"]}), len(out["places"]))   # each once
        # another person's recent folders are their own
        status, other, _ = self.call("GET", "/api/pick/places?person=Ilkka&persona=developer")
        self.assertNotIn("recent", [p["kind"] for p in other["places"]])
        # a folder the cockpit may not read is never remembered
        status, out, _ = self.call("POST", "/api/pick/recent", {"path": str(self.outside), **WHO})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("POST", "/api/pick/recent", {"path": str(app), "person": NON_PERSON,
                                                                 "persona": "developer"})
        self.assertEqual(status, 403, out)

    # -- one folder's contents -------------------------------------------------------------------------------

    def test_FR_PICK1_AC_2_a_folder_lists_its_folders_with_git_and_project_badges_folded_and_capped(self):
        repo = self.root / "orders"
        (repo / ".git").mkdir(parents=True)
        held = self.root / "billing"
        held.mkdir()
        p = self.factory.new_project("Billing")
        p.update_meta(source_kind="adopted")
        p.path("adopted.json").write_text(json.dumps({"source": str(held)}), encoding="utf-8")
        for name in ("Zeta", "alpha", ".cache", "node_modules", ".venv"):
            (self.root / name).mkdir()
        (self.root / "README.md").write_text("# dev\n", encoding="utf-8")
        (self.root / ".env").write_text("X=1\n", encoding="utf-8")
        status, out, _ = self.listing(self.root)
        self.assertEqual(status, 200, out)
        f = out["folder"]
        self.assertTrue(f["readable"])
        self.assertEqual([r["name"] for r in f["folders"]], ["alpha", "billing", "orders", "Zeta"])   # sorted by name
        self.assertEqual(sorted(r["name"] for r in f["hidden"]), [".cache", ".venv", "node_modules"])      # folded
        rows = {r["name"]: r for r in f["folders"]}
        self.assertTrue(rows["orders"]["git"])
        self.assertFalse(rows["alpha"]["git"])
        self.assertEqual(rows["billing"]["project"], {"project": p.pid, "title": "Billing", "how": "adopted"})
        self.assertTrue(all(r["readable"] and r["modified"] for r in f["folders"]))
        self.assertEqual(f["files"], [])                                 # files only when asked
        self.assertEqual([c["path"] for c in f["crumbs"]][-2:], [str(self.tmp), str(self.root)])
        self.assertEqual(f["parent"], str(self.tmp))
        status, out, _ = self.listing(self.root, files=True)
        self.assertEqual([r["name"] for r in out["folder"]["files"]], ["README.md"])   # a dot file is never listed
        with mock.patch.object(kpick, "MAX_ROWS", 2):
            f = self.listing(self.root)[1]["folder"]
        self.assertEqual((len(f["folders"]), f["more"]), (2, 2))         # capped, with how many more

    def test_FR_PICK1_AC_2_outside_the_allowed_folders_names_only_and_never_a_system_or_keys_folder(self):
        (self.outside / "notes").mkdir()
        (self.outside / "notes.txt").write_text("x\n", encoding="utf-8")
        status, out, _ = self.listing(self.outside, files=True)
        self.assertEqual(status, 200, out)                               # a single operator looks, to allow one
        f = out["folder"]
        self.assertFalse(f["readable"])
        self.assertIn("outside your home folder", f["why"])
        self.assertEqual(f["offer"]["who"], "you")
        self.assertEqual([r["name"] for r in f["folders"]], ["notes"])
        self.assertEqual((f["files"], f["files_listed"]), ([], False))   # never a file outside
        self.assertFalse(f["folders"][0]["readable"])
        self.assertTrue(f["folders"][0]["allow"])
        for never in (SYSTEM, self.root / ".ssh"):
            Path(never).mkdir(exist_ok=True)
            status, out, _ = self.listing(never)
            self.assertEqual(status, 403, out)
        (self.root / ".ssh").mkdir(exist_ok=True)
        hidden = {r["name"]: r for r in self.listing(self.root)[1]["folder"]["hidden"]}
        self.assertTrue(hidden[".ssh"]["never"])
        self.assertNotIn("allow", hidden[".ssh"])
        status, out, _ = self.call("GET", f"/api/pick/list?person=Sanna&persona=stakeholder&path={self.root}")
        self.assertEqual(status, 403, out)                               # a persona that may not read a folder
        with self.assertRaises(SourceRefused):                           # enforced access: refused outright
            kpick.listing(self.factory, str(self.outside), persona="developer", enforced=True)

    def test_FR_PICK1_AC_2_a_link_out_of_the_allowed_folders_is_never_followed(self):
        (self.outside / "secret-project").mkdir()
        make_link(self.root / "shortcut", self.outside)
        (self.root / "inside").mkdir()
        make_link(self.root / "near", self.root / "inside")
        rows = {r["name"]: r for r in self.listing(self.root)[1]["folder"]["folders"]}
        self.assertTrue(rows["shortcut"]["link"])
        self.assertFalse(rows["shortcut"]["readable"])
        self.assertIn("not followed", rows["shortcut"]["why"])
        self.assertFalse(rows["shortcut"]["git"])
        self.assertNotIn("allow", rows["shortcut"])
        self.assertTrue(rows["near"]["readable"])                        # a link that stays inside is fine
        f = self.listing(self.root / "shortcut", files=True)[1]["folder"]   # opened by name: where it leads, not read
        self.assertEqual(f["path"], str(self.outside))
        self.assertFalse(f["readable"])
        self.assertEqual(f["files"], [])

    # -- the computer's own dialog ------------------------------------------------------------------------------

    def native(self, code, *, origin=None, **body):
        env = mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in(code)})
        with env:
            kw = {"origin": origin} if origin else {}
            return self.call("POST", "/api/pick/native", {"kind": "folder", "title": "Choose", **WHO, **body}, **kw)

    def test_FR_PICK1_AC_3_the_native_dialog_returns_the_chosen_path_or_cancelled_and_records_nothing(self):
        app = self.root / "app"
        app.mkdir()
        seen = self.tmp / "argv.json"
        before = tree(self.factory.home)
        code = f"import sys, json; open({str(seen)!r}, 'w').write(json.dumps(sys.argv[1:])); print({str(app)!r})"
        status, out, _ = self.native(code, start=str(self.root))
        self.assertEqual(status, 200, out)
        self.assertEqual(out["picked"], {"path": str(app), "kind": "folder", "readable": True, "why": None, "offer": None})
        self.assertEqual(json.loads(seen.read_text()), ["folder", "Choose", str(self.root)])
        status, out, _ = self.native(f"print({str(self.outside)!r})")
        self.assertFalse(out["picked"]["readable"])                      # chosen, and said: checked before any use
        self.assertEqual(out["picked"]["offer"]["who"], "you")
        self.assertEqual(self.native("pass")[1], {"cancelled": True})
        self.assertEqual(self.native("import sys; sys.exit(1)")[1], {"cancelled": True})
        self.assertEqual(tree(self.factory.home), before)                # nothing recorded
        status, out, _ = self.native("pass", kind="drive")
        self.assertEqual(status, 400, out)
        status, out, _ = self.call("POST", "/api/pick/native", {"kind": "folder", "person": NON_PERSON,
                                                                 "persona": "developer"})
        self.assertEqual(status, 403, out)
        with mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in("pass")}):
            places = self.call("GET", f"/api/pick/places?{Q}")[1]
        self.assertEqual(places["native"]["available"], True)
        self.assertEqual(places["native"]["tool"], "stand-in")

    def test_FR_PICK1_AC_3_the_native_dialog_is_refused_from_another_computer_or_through_a_proxy(self):
        self.server.public_origin = "https://desk.example.ts.net"
        status, out, _ = self.native("print('x')", origin="https://desk.example.ts.net")
        self.assertEqual(status, 409, out)
        self.assertIn("use the folder browser", out["error"])
        req = urllib.request.Request(self.origin + "/api/pick/native", method="POST",
                                     data=json.dumps({"kind": "folder", **WHO}).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "Origin": self.origin,
                                              "Content-Type": "application/json", "X-Forwarded-For": "100.64.0.9"})
        with mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in("print('x')")}):
            try:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10)
                self.fail("a forwarded request opened the dialog")
            except urllib.error.HTTPError as exc:
                with exc:
                    self.assertEqual(exc.code, 409)
        with mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in("print('x')")}):
            places = self.call("GET", f"/api/pick/places?{Q}")[1]["native"]
        self.assertTrue(places["available"])                              # from the loopback page it still opens
        with mock.patch.object(knative, "command", return_value=None), mock.patch.dict(os.environ, {knative.PICK_ENV: ""}):
            status, out, _ = self.call("POST", "/api/pick/native", {"kind": "folder", **WHO})
        self.assertEqual(status, 501, out)                                # nothing can open a dialog here
        self.assertIn("folder browser", out["error"])

    def test_FR_PICK1_AC_3_one_dialog_at_a_time_and_it_holds_no_write(self):
        self.assertIn("post_pick_native", cockpit.UNLOCKED)              # never the write lock: it waits on a person
        got = {}

        def slow():
            got["first"] = self.call("POST", "/api/pick/native", {"kind": "folder", **WHO})
        with mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in("import time; time.sleep(2)")}):
            t = threading.Thread(target=slow)
            t.start()
            end = time.monotonic() + 10
            while not knative.busy() and time.monotonic() < end:
                time.sleep(0.02)
            status, out, _ = self.call("POST", "/api/pick/native", {"kind": "folder", **WHO})
            self.assertEqual(status, 409, out)
            self.assertIn("already", out["error"])
            status, out, _ = self.call("POST", "/api/source/roots", {"folder": str(self.outside), "confirm": True, **WHO})
            self.assertEqual(status, 200, out)                            # a write goes on while the dialog is open
            t.join(10)
        self.assertEqual(got["first"][0], 200)

    def test_FR_PICK1_AC_3_a_dialog_opened_through_an_ssh_tunnel_names_its_computer_and_can_be_cancelled(self):
        # A page through `ssh -L 8872:127.0.0.1:8872` sends the loopback Origin and no X-Forwarded-For: the cockpit
        # cannot tell it from the page at its own machine, so the page says where the dialog opened and may close it.
        got = {}

        def tunnelled():
            got["first"] = self.native("import time; time.sleep(60)", origin=self.origin)
        with mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in("pass")}):
            native = self.call("GET", f"/api/pick/places?{Q}", origin=self.origin)[1]["native"]
        self.assertEqual((native["available"], native["host"]), (True, socket.gethostname()))
        t = threading.Thread(target=tunnelled)
        t.start()
        end = time.monotonic() + 10
        while not (knative.busy() and knative._OPEN) and time.monotonic() < end:
            time.sleep(0.02)
        status, out, _ = self.call("POST", "/api/pick/native/cancel", {"person": NON_PERSON, "persona": "developer"})
        self.assertEqual(status, 403, out)                               # signed like every write
        began = time.monotonic()
        status, out, _ = self.call("POST", "/api/pick/native/cancel", WHO)
        self.assertEqual((status, out), (200, {"cancelled": True}))
        t.join(15)
        self.assertLess(time.monotonic() - began, 10)                    # not the ten minutes the dialog may stay open
        self.assertEqual(got["first"][:2], (200, {"cancelled": True}))
        self.assertFalse(knative.busy())                                  # the one-dialog slot is free again
        self.assertEqual(self.call("POST", "/api/pick/native/cancel", WHO)[1], {"cancelled": False})
        self.assertIn("post_pick_cancel", cockpit.UNLOCKED)

    def test_FR_PICK1_AC_2_the_filter_searches_the_whole_folder_not_only_the_rows_shown(self):
        for i in range(12):
            (self.root / f"d{i:04d}").mkdir()
        (self.root / "d0011.md").write_text("x\n", encoding="utf-8")
        with mock.patch.object(kpick, "MAX_ROWS", 3):
            f = self.listing(self.root)[1]["folder"]
            self.assertEqual((len(f["folders"]), f["more"], f["q"]), (3, 9, ""))
            status, out, _ = self.call("GET", f"/api/pick/list?{Q}&files=1&q=D0011&path={urllib.request.quote(str(self.root))}")
            self.assertEqual(status, 200, out)
            f = out["folder"]
        self.assertEqual(([r["name"] for r in f["folders"]], [r["name"] for r in f["files"]]), (["d0011"], ["d0011.md"]))
        self.assertEqual((f["more"], f["files_more"], f["q"]), (0, 0, "D0011"))   # any case, past the first rows
        status, out, _ = self.listing(self.root / "d0011.md")            # a field holding a file: its folder
        self.assertEqual((status, out["folder"]["path"]), (200, str(self.root)))
        js = (cockpit.STATIC_DIR / "picker.js").read_text(encoding="utf-8")
        self.assertIn('"&q=" + encodeURIComponent(text)', js)            # the page sends the filter to the server
        self.assertNotIn("filter to find them", js)

    def test_FR_PICK1_AC_3_the_dialog_command_for_each_system(self):
        with mock.patch.dict(os.environ, {knative.PICK_ENV: ""}):
            with mock.patch.object(knative.sys, "platform", "darwin"), mock.patch.object(knative.shutil, "which",
                                                                                         return_value="/usr/bin/osascript"):
                self.assertEqual(knative.command("folder", "T", "")[:1], ["osascript"])
            with mock.patch.object(knative.os, "name", "posix"), mock.patch.object(knative.sys, "platform", "linux"):
                with mock.patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
                    self.assertIsNone(knative.command("folder", "T", ""))      # no display: not available here
                with mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                        mock.patch.object(knative.shutil, "which", side_effect=lambda n: "/usr/bin/zenity" if n == "zenity" else None):
                    argv = knative.command("folder", "T", "/srv")
                    self.assertEqual(argv[:3], ["zenity", "--file-selection", "--directory"])
        with mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in("print('/x')")}):
            self.assertEqual(knative.choose("folder", "T", ""), "/x")
            with self.assertRaises(ValueError):
                knative.choose("drive")
        with mock.patch.dict(os.environ, {knative.PICK_ENV: stand_in("import time; time.sleep(5)")}):
            self.assertIsNone(knative.choose("file", timeout=0.5))      # open too long: cancelled, never stuck


class PickParityTest(unittest.TestCase):
    """Ask Rihma proposes the same flow, and every path field of the page offers Browse."""

    def test_FR_PICK1_AC_4_ask_rihma_proposes_the_plug_in_flow_with_the_folder_it_names(self):
        got = walkthrough_intent.offer("adopt the project in C:\\dev\\x")
        self.assertEqual((got["name"], got["said"]), ("plug_in", "C:\\dev\\x"))
        got = walkthrough_intent.offer("please open the folder picker")
        self.assertEqual(got["name"], "plug_in")
        self.assertNotIn("said", got)
        self.assertEqual(walkthrough_intent.offer("plug in ~/code/shop.")["said"], "~/code/shop")
        self.assertEqual(walkthrough_intent.offer("valitse kansio")["name"], "plug_in")
        self.assertIsNone(walkthrough_intent.named_path("compare and/or contrast"))

    def test_FR_PICK1_AC_4_a_quoted_path_with_spaces_is_taken_whole(self):
        said = walkthrough_intent.offer('adopt the project in "C:\\Users\\me\\My Projects\\shop"')
        self.assertEqual((said["name"], said["said"]), ("plug_in", "C:\\Users\\me\\My Projects\\shop"))
        for words, path in (("plug in 'D:\\Omat tiedostot\\kassa' please", "D:\\Omat tiedostot\\kassa"),
                            ("tuo projekti ”C:\\Users\\me\\OneDrive - Firma\\app”", "C:\\Users\\me\\OneDrive - Firma\\app"),
                            ('adopt my existing repo at: "/home/me/my code/shop".', "/home/me/my code/shop"),
                            ("adopt the project in C:\\dev\\x, thanks", "C:\\dev\\x"),        # unquoted: as before
                            ("it's my existing project at ~/code/shop", "~/code/shop")):
            self.assertEqual(walkthrough_intent.named_path(words), path, words)
        ui = json.loads((cockpit.STATIC_DIR.parent / "ui_map.json").read_text(encoding="utf-8"))
        ids = {c["id"]: c for c in ui["controls"]}
        self.assertIn("folder picker", ids["pick_browse"]["synonyms"])
        self.assertIn("pick_here", ids)

    def test_FR_PICK1_AC_4_every_local_path_field_offers_browse(self):
        js = {p.name: p.read_text(encoding="utf-8") for p in cockpit.STATIC_DIR.glob("*.js")}
        uses = {name: len(re.findall(r"\b(pathField|browseButtons)\(", text)) for name, text in js.items()
                if name != "picker.js"}
        self.assertEqual({k: v for k, v in uses.items() if v},
                         {"screens.js": 2, "shape.js": 1, "change.js": 1, "folders.js": 1, "automations.js": 1,
                          "roads.js": 1, "walkthrough.js": 1})
        self.assertIn('pathField(repo, { kind: "folder"', js["screens.js"])            # New project > existing
        self.assertIn('"data-control": "pick_browse"', js["picker.js"])
        self.assertIn('"data-control": "pick_here"', js["picker.js"])


if __name__ == "__main__":
    unittest.main()
