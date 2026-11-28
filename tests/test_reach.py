"""FR-RCH1: the reachability doctor. ssh's own output, recorded in the shapes it prints, is classified; no real ssh,
https or gh runs here (a fake runner and opener stand in), and no test writes anything.
"""

import contextlib
import io
import json
import socket
import ssl
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import machines, reach  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

DANA = {"person": "Dana Example", "persona": "developer"}
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleOnlyNotARealKey0000000000000000 dana@workstation"

OUTPUTS = {      # what `ssh -v -o BatchMode=yes ... exit` prints, in its own words, per case
    "ok": (0, "debug1: Authenticated to laptop ([10.0.0.2]:22) using \"publickey\".\ndebug1: Exit status 0"),
    "dns": (255, "ssh: Could not resolve hostname laptop: Name or service not known"),
    "no_route": (255, "ssh: connect to host 10.0.0.2 port 22: No route to host"),
    "refused": (255, "ssh: connect to host 10.0.0.2 port 22: Connection refused"),
    "timeout": (255, "ssh: connect to host 10.0.0.2 port 22: Connection timed out"),
    "host_key": (255, "No ED25519 host key is known for laptop and you have requested strict checking.\n"
                      "Host key verification failed."),
    "auth_denied": (255, "debug1: Offering public key: /home/dana/.ssh/id_ed25519 ED25519 SHA256:abc\n"
                         "debug1: Authentications that can continue: publickey,password,keyboard-interactive\n"
                         "me@laptop: Permission denied (publickey,password,keyboard-interactive)."),
    "session_reset": (255, "debug1: Server accepts key: /home/dana/.ssh/id_ed25519 ED25519 SHA256:abc\n"
                           "Authenticated to laptop ([10.0.0.2]:22) using \"publickey\".\n"
                           "debug1: channel 0: new session [client-session]\n"
                           "Read from remote host laptop: Connection reset by peer\n"
                           "client_loop: send disconnect: Connection reset by peer"),
    "unknown": (255, "kex_exchange_identification: something else entirely"),
}


def runner_for(case):
    seen = []

    def run(argv, timeout):
        seen.append(argv)
        return OUTPUTS[case]
    run.seen = seen
    return run


class ClassifyTest(unittest.TestCase):
    def test_FR_RCH1_AC_1_each_ssh_outcome_is_classified_and_the_test_is_batch_mode_read_only(self):
        for case, (code, out) in OUTPUTS.items():
            self.assertEqual(reach.classify_ssh(code, out), case, case)
        run = runner_for("ok")
        self.assertEqual(reach.test_ssh("me@laptop", runner=run), "ok")
        argv = run.seen[0]
        self.assertEqual(argv[:2], ["ssh", "-v"])
        self.assertIn("BatchMode=yes", argv)                        # never asks for a password, never a prompt
        self.assertTrue(any(a.startswith("ConnectTimeout=") for a in argv))
        self.assertEqual(argv[-3:], ["--", "me@laptop", "exit"])          # stops ssh option parsing; runs nothing
        self.assertFalse(any("StrictHostKeyChecking" in a for a in argv))    # never accepts a host key
        for bad in ("-oProxyCommand=id", r"-F\\evil.example\share\cfg@host", "-Elog@host"):
            with self.assertRaises(machines.MachineRefused):
                reach.test_ssh(bad, runner=run)
        with mock.patch.object(reach.shutil, "which", return_value=None):
            self.assertEqual(reach.test_ssh("me@laptop"), "no_tool")

    def test_FR_RCH1_AC_2_each_verdict_has_fix_steps_for_the_targets_system(self):
        win = " ".join(reach.fix("refused", "windows"))
        self.assertIn("Add-WindowsCapability", win)
        self.assertIn("Start-Service sshd", win)
        self.assertIn("apt install openssh-server", " ".join(reach.fix("refused", "linux")))
        self.assertIn("Remote Login", " ".join(reach.fix("refused", "macos")))
        keys = " ".join(reach.fix("auth_denied", "windows", key=KEY))
        self.assertIn(KEY, keys)
        self.assertIn("administrators_authorized_keys", keys)
        self.assertIn("icacls", keys)
        self.assertIn("domain\\user", keys)
        self.assertIn("chmod 600 ~/.ssh/authorized_keys", " ".join(reach.fix("auth_denied", "linux", key=KEY)))
        reset = " ".join(reach.fix("session_reset", "windows"))
        self.assertIn("OpenSSH/Operational", reset)
        self.assertIn("local account", reset)
        self.assertIn("never accepts a host key", " ".join(reach.fix("host_key", "linux", address="laptop")))
        self.assertIn("laptop resolves", " ".join(reach.fix("dns", "linux", address="me@laptop")))
        for verdict in reach.FAIL:
            self.assertTrue(reach.fix(verdict, "windows"), verdict)
        self.assertEqual(reach.fix("ok"), [])
        with mock.patch.object(reach.Path, "home", return_value=Path("/nonexistent-home")):
            self.assertEqual(reach.public_key(), (None, None))


class DoctorTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.factory.new_project("Webshop", mode="mixed", maturity="demo")
        machines.add(self.factory, {"name": "laptop", "reach": "ssh", "address": "me@laptop", "os": "windows",
                                    "agents": ["claude-code"]}, **DANA)
        self.ledgers = self._ledgers()

    def _ledgers(self):
        own = factory_project(self.factory).path("ledger.jsonl")
        return (self.p.path("ledger.jsonl").read_bytes(), own.read_bytes())

    def test_FR_RCH1_AC_3_an_unreachable_machine_gets_a_drafted_ask_and_no_test_writes(self):
        with mock.patch.object(reach, "public_key", return_value=("/k.pub", KEY)):
            r = reach.doctor(self.factory, "laptop", runner=runner_for("auth_denied"))
        self.assertEqual((r["verdict"], r["ok"], r["os"]), ("auth_denied", False, "windows"))
        d = r["draft"]
        self.assertEqual((d["to"], d["machine"]), ("claude-code", "laptop"))
        self.assertIn(KEY, d["text"])
        self.assertIn("1. ", d["text"])
        self.assertEqual(d["source"], {"reach": "auth_denied", "machine": "laptop"})
        ok = reach.doctor(self.factory, "laptop", runner=runner_for("ok"))
        self.assertTrue(ok["ok"])
        self.assertNotIn("draft", ok)
        nowhere = self.p                                                     # made here: no working copy
        out = reach.doctor(self.factory, nowhere.pid)
        self.assertEqual((out["kind"], out["verdict"]), ("project", "not_found"))
        self.assertEqual(out["draft"]["machine"], "laptop")
        self.assertIn("git status", out["draft"]["text"])

        def opener_ok(url, timeout):
            return 200

        def opener_dns(url, timeout):
            raise urllib.error.URLError(socket.gaierror("getaddrinfo failed"))

        def opener_tls(url, timeout):
            raise urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))

        def opener_500(url, timeout):
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)
        self.assertEqual(reach.doctor(self.factory, "https://hub.example", opener=opener_ok)["verdict"], "ok")
        self.assertEqual(reach.doctor(self.factory, "https://hub.example", opener=opener_dns)["verdict"], "dns")
        self.assertEqual(reach.doctor(self.factory, "https://hub.example", opener=opener_tls)["verdict"], "tls")
        self.assertIn("HTTP 503", reach.doctor(self.factory, "https://hub.example", opener=opener_500)["said"])
        for private_url in ("https://127.0.0.1:8787/api/meta", "https://169.254.169.254/latest/meta-data/",
                            "https://localhost/"):
            with self.assertRaises(machines.MachineRefused):
                reach.doctor(self.factory, private_url, opener=opener_ok)
        self.assertEqual(reach.doctor(self.factory, "github", runner=lambda a, t: (1, "not logged in"))["verdict"],
                         "gh_signed_out")
        with self.assertRaises(machines.MachineRefused):
            reach.doctor(self.factory, "nowhere")
        machines.add(self.factory, {"name": "desk", "reach": "hand"}, **DANA)
        self.assertEqual(reach.doctor(self.factory, "desk")["verdict"], "hand")
        machines.remove(self.factory, "desk", **DANA)
        self.ledgers = self._ledgers()
        reach.doctor(self.factory, "laptop", runner=runner_for("refused"))
        self.assertEqual(self._ledgers(), self.ledgers)                      # a test writes nothing

    def test_FR_RCH1_AC_4_the_command_line_the_cockpit_and_ask_rihma_give_the_same_verdict(self):
        with mock.patch.object(reach, "test_ssh", return_value="session_reset"):
            status, api, _ = self.call("POST", "/api/reach", {"target": "laptop"})
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--home", str(self.factory.home), "reach", "laptop"])
            chat = ask(self.factory, "is the laptop reachable?", persona="developer", project_id=self.p.pid, model=None)
        cli = json.loads(buf.getvalue())
        self.assertEqual((status, code), (200, 0))
        self.assertEqual(api["verdict"], cli["verdict"])
        self.assertEqual(api["fix"], cli["fix"])
        self.assertEqual(api["draft"]["text"], cli["draft"]["text"])
        self.assertIn(reach.VERDICTS["session_reset"], chat["answer"])
        self.assertEqual(chat["propose"][0]["args"]["text"], api["draft"]["text"])
        status, body, _ = self.call("POST", "/api/reach", {"target": "rm -rf /"})
        self.assertEqual(status, 400)
        self.assertEqual(self._ledgers(), self.ledgers)


if __name__ == "__main__":
    unittest.main()
