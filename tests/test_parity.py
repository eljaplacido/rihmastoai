"""FR-SET1-AC-8: UI and chat parity. Every control of the cockpit's map that changes something can be done through
Ask Rihma (an action, an operation, a walkthrough, a goal step, a chat answer) or has a recorded reason; every
assistant action and operation has its control; every signed command has its cockpit route or a recorded reason.
kernel/parity.py holds the tables; this test reads them against the code, so whatever is added without its other
half fails here until it gets one."""

import importlib
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_cli_capability import leaves  # noqa: E402

from cockpit import server  # noqa: E402
from kernel import assistant_ops, copilot, parity  # noqa: E402
from kernel.assistant_rules import ACTIONS, ui_map  # noqa: E402
from kernel.cli import build_parser  # noqa: E402

KINDS = ("action", "op", "walk", "goal", "chat", "open")
SAMPLE = {"pid": "loans-0a1b2c", "item": "checks", "suggestion": "nightly_gate", "automation_id": "AU-001",
          "check": "secrets", "proposal": "OPT-0123456789",   # an Agent operations proposal (FR-AOP1)
          "source": "SRC-1",   # a project's own source (FR-SRC1)
          "epic": "E-1"}   # an epic (FR-S2)


def walkthroughs() -> set:
    from kernel.walkthrough_adopt import FLOWS as ADOPT
    from kernel.walkthrough_more import FLOWS as MORE

    return set(ADOPT) | set(MORE)


def signed_commands() -> set:
    return {name for name, p in leaves(build_parser()).items()
            if any(a.dest in ("person", "requested_by") and a.option_strings for a in p._actions)}


class ParityTest(unittest.TestCase):
    def test_FR_SET1_AC_8_every_control_that_changes_something_has_a_chat_path_or_a_recorded_reason(self):
        controls = {c["id"] for c in ui_map()["controls"]}
        both = parity.READS & set(parity.CHAT)
        self.assertEqual(both, set(), "a control is either a read or has a chat path, never both")
        missing = sorted(controls - parity.READS - set(parity.CHAT))
        self.assertEqual(missing, [], "add these controls to kernel/parity.py: READS if they change nothing, "
                                      "else CHAT with how Ask Rihma does the same (or a recorded reason)")
        stale = sorted((parity.READS | set(parity.CHAT)) - controls)
        self.assertEqual(stale, [], "these are in kernel/parity.py but not on the map (cockpit/ui_map.json)")
        walks, intents = walkthroughs(), set(copilot.INTENTS)
        for cid, (kind, ref) in parity.CHAT.items():
            self.assertIn(kind, KINDS, cid)
            if kind == "action":
                self.assertIn(ref, ACTIONS, cid)
            elif kind == "op":
                self.assertIn(ref, assistant_ops.OPS, cid)
            elif kind == "walk":
                self.assertIn(ref, walks, cid)
            elif kind == "goal":
                self.assertIn(ref, intents, cid)
            elif kind == "chat":
                module, _, name = ref.partition(":")
                self.assertTrue(callable(getattr(importlib.import_module(module), name, None)), (cid, ref))
            else:
                self.assertGreater(len(ref), 20, f"{cid}: a recorded reason, in words")

    def test_FR_SET1_AC_8_every_assistant_action_and_operation_has_its_control_and_its_cockpit_route(self):
        controls = {c["id"] for c in ui_map()["controls"]}
        self.assertEqual(set(parity.ACTION_CONTROLS), set(ACTIONS), "every assistant action has its control")
        for action, control in parity.ACTION_CONTROLS.items():
            self.assertIn(control, controls, action)
        routes = {name for _, _, name in server.ROUTES}
        for op, (label, method, path, needed, sent, control) in assistant_ops.OPS.items():
            self.assertIn(control, controls, op)
            self.assertTrue(label, op)
            self.assertIsInstance(sent, tuple, op)
            filled = path.format(**SAMPLE)
            found = server._route(method, filled)
            self.assertIsNotNone(found, f"{op}: {method} {filled} is not a cockpit route")
            self.assertIn(found[1], routes, op)
            for key in re.findall(r"\{(\w+)\}", path):
                self.assertIn(key, ("pid", *needed), op)
        # every operation is a chat path of some control, so nothing in Ask Rihma lacks its click
        self.assertEqual(set(assistant_ops.OPS) - {ref for kind, ref in parity.CHAT.values() if kind == "op"}, set())

    def test_FR_SET1_AC_8_every_signed_command_has_its_cockpit_route_or_a_recorded_reason(self):
        signed = signed_commands()
        both = set(parity.CLI_ROUTES) & set(parity.CLI_WHY_NOT)
        self.assertEqual(both, set(), "a command has a route or a reason, never both")
        self.assertEqual(sorted(signed - set(parity.CLI_ROUTES) - set(parity.CLI_WHY_NOT)), [],
                         "add these signed commands to kernel/parity.py CLI_ROUTES (or CLI_WHY_NOT with a reason)")
        self.assertEqual(sorted((set(parity.CLI_ROUTES) | set(parity.CLI_WHY_NOT)) - signed), [],
                         "these are in kernel/parity.py but are not signed commands")
        writes = {name for method, _, name in server.ROUTES if method in ("POST", "PUT")}
        for command, route in parity.CLI_ROUTES.items():
            self.assertIn(route, writes, command)
        for command, why in parity.CLI_WHY_NOT.items():
            self.assertGreater(len(why), 20, command)

    def test_FR_SET1_AC_8_the_parity_check_fails_on_a_gap(self):
        """The tables are read, not trusted: a control, an operation or a command without its half is found."""
        controls = {c["id"] for c in ui_map()["controls"]} | {"a_new_button"}
        self.assertEqual(sorted(controls - parity.READS - set(parity.CHAT)), ["a_new_button"])
        signed = signed_commands() | {"frobnicate"}
        self.assertEqual(sorted(signed - set(parity.CLI_ROUTES) - set(parity.CLI_WHY_NOT)), ["frobnicate"])
        self.assertIsNone(server._route("POST", "/api/projects/x/frobnicate"))


if __name__ == "__main__":
    unittest.main()
