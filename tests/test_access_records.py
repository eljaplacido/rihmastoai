"""Access control, the remaining should-fix items (FR-ID3, D-0016, D-0017).

- A request replaced by `rihmasto intake` is on record with who replaced it.
- The guide lists every command of the command line as signed or unsigned, completely.
- The docs say how the sign-in and the isolation work and what is built, and the assistant can take a
  person to the access note.
"""

import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_access import write_access  # noqa: E402
from test_access_hardening import cli, prose  # noqa: E402
from test_cli_capability import leaves  # noqa: E402

from kernel.assistant import ask, find_in_map, ui_map  # noqa: E402
from kernel.cli import build_parser  # noqa: E402
from kernel.store import Factory  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
GUIDE = REPO / "docs" / "guides" / "access.md"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IntakeReplacedTest(FactoryTestCase):
    """FR-ID3-AC-1: a request replaced by intake names who replaced it, and what it replaced."""

    def test_FR_ID3_AC_1_a_replaced_request_is_on_record_with_who_replaced_it(self):
        p = self.new(title="Shipment webhook")
        first, second, third = ("When the carrier posts, update the stock.", "Update the stock from the webhook",
                                "Update the stock and tell the warehouse")
        for text, who in ((first, "Ida Example"), (second, "Olli Example")):       # a single operator's factory
            code, _, err = cli(self.factory, "olli", "intake", p.pid, "--source", text, "--requested-by", who)
            self.assertEqual(code, 0, err)
        records = [r["event"]["payload"] for r in p.ledger().of_kind("request_replaced")]
        self.assertEqual(len(records), 1)                                         # the first request replaced nothing
        self.assertEqual(records[0], {"requested_by": "Olli Example", "previous_sha256": sha(first),
                                      "sha256": sha(second), "previous_requested_by": "Ida Example"})
        write_access(self.factory)                                                # access enforced: signed, by identity
        code, _, err = cli(self.factory, "aino", "intake", p.pid, "--source", third, "--requested-by", "Aino Example",
                           "--persona", "product_owner")
        self.assertEqual(code, 0, err)
        last = p.ledger().of_kind("request_replaced")[-1]["event"]["payload"]
        self.assertEqual((last["requested_by"], last["identity"], last["previous_requested_by"]),
                         ("Aino Example", "local:aino", "Olli Example"))
        self.assertEqual((last["previous_sha256"], last["sha256"]), (sha(second), sha(third)))
        self.assertTrue(p.ledger().verify().intact)


class CommandListsTest(unittest.TestCase):
    """FR-ID3-AC-2: the guide's lists of signed and unsigned commands are complete."""

    def listed(self, guide: str, label: str) -> list:
        found = re.search(rf"\*\*{label} \((\d+)\):\*\*(.*?)\n\n", guide, re.S)
        self.assertIsNotNone(found, f"the guide's **{label} (n):** list")
        names = re.findall(r"`([^`]+)`", found.group(2))
        self.assertEqual(int(found.group(1)), len(names), f"the count beside **{label}**")
        return names

    def test_FR_ID3_AC_2_the_guide_lists_every_command_as_signed_or_unsigned(self):
        guide = GUIDE.read_text(encoding="utf-8")
        signed, unsigned = self.listed(guide, "Signed"), self.listed(guide, "Unsigned")
        parsed = leaves(build_parser())
        takes_a_person = {name for name, parser in parsed.items()
                          if any(a.dest in ("person", "requested_by") and a.option_strings for a in parser._actions)}
        missing = sorted(set(parsed) - set(signed) - set(unsigned))
        self.assertEqual(missing, [], "add these commands to the guide's Signed or Unsigned list (docs/guides/access.md)")
        self.assertEqual(set(signed), takes_a_person)
        self.assertEqual(set(unsigned), set(parsed) - takes_a_person)
        self.assertEqual(len(signed) + len(unsigned), len(parsed))               # each once


class DocsTest(unittest.TestCase):
    """FR-ID3-AC-3: what the docs say, and where the assistant takes a person."""

    def test_FR_ID3_AC_3_the_docs_say_how_sign_in_and_isolation_work_and_what_is_built(self):
        guide, security = prose(GUIDE), prose(REPO / "SECURITY.md")
        integrations, cockpit = prose(REPO / "docs" / "integrations.md"), prose(REPO / "docs" / "cockpit.md")
        self.assertNotIn("The stdlib cannot verify RS256", integrations)
        self.assertIn("RS256 or ES256, with the standard library (`kernel/jwt_verify.py`)", integrations)
        for said in ("the cockpit holds no shared secret", "**Built:**", "**Planned:**", "## Isolation",
                     "## Tutorial: turn access on for a team", "rihmasto access check --token-file",
                     "rihmasto access keys", "`x-goog-iap-jwt-assertion`", "`x-amzn-oidc-data`",
                     "--pass-authorization-header", "`X-Rihmasto-Session`", "`sudo -n -u <account>`",
                     "`none` and `HS*` are never accepted"):
            self.assertIn(said, guide)
        for text in (security, cockpit):
            self.assertIn("holds no shared secret", text)
        self.assertIn("isolation runner", security)
        control = next(c for c in ui_map()["controls"] if c["id"] == "access")
        self.assertIn("sign-in token", control["does"])
        for question in ("who signs decisions", "where does untrusted code run", "isolation runner"):
            self.assertEqual(find_in_map(question)[0]["id"], "access", question)
        with tempfile.TemporaryDirectory() as home:                             # Ask Rihma, without a model
            out = ask(Factory(home), "Who signs decisions here?", persona="business_owner")
        self.assertEqual(out["navigate"], {"route": None, "control": "access"})
        self.assertIn("Access note is in the top bar", out["answer"])
        index = (REPO / "cockpit" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(index.count('data-control="access"'), 2)                 # the top bar and the person menu


if __name__ == "__main__":
    unittest.main()
