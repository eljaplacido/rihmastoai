"""Gnomon's native outcome to a factory verdict (FR-C5). The native values always travel with it.

Gnomon reports a bucket (result, refusal or apparatus_failure), an exit code, and, when a verify
command ran, a verify status. The mapping:

| Native | Verdict |
|---|---|
| result with verify passed | passed |
| result with verify failed, regressed or passed_unverified | failed |
| result with verify unrunnable, skipped or declined | not measured |
| result with no verify configured | not measured (the factory's own gate must judge) |
| refusal (exit 2) | violation |
| refusal for record tamper (exit 3) | not measured, marked tampered |
| apparatus failure (exit 10, 11, 12 or 13) | not measured, marked as an apparatus failure (FR-C6) |

Anything else raises: an unknown value never defaults to a verdict (FR-C5-AC-2). "Apparatus
failure" is not a verdict (FR-G3-AC-3). It is a flag beside "not measured", so rates can
exclude it.

The record's own `bucket` and `code` decide, never the process exit. Under Gnomon's
`[verify] exit_on_fail` or `gnomon task --require-verify` (CONTRACTS §1 and §53, in 0.6.6) a
`result` exits 1 for a failed, regressed or passed_unverified check and 4 for an unrunnable one,
while the record still says `bucket: "result"`, `code: 0`. The process exit (`_exit`, set by
kernel/model.py), `verify_exit`, `verify_rounds` and `verify_reason` travel as native values.
`verify_tail` does not: it is the check's own output (content), and the record keeps it.
"""

from __future__ import annotations

from kernel.verdicts import VERDICTS

BUCKETS = ("result", "refusal", "apparatus_failure")
VERIFY_PASSED = ("passed",)
VERIFY_FAILED = ("failed", "regressed", "passed_unverified")
VERIFY_NOT_MEASURED = ("unrunnable", "skipped", "declined")
# CONTRACTS §1: 10 launch_failed, 11 timed_out, 12 provider_unreachable, 13 context_exhausted. A turn
# that ends on `stop_reason: "endpoint_error"` carries 10 to 13 ("the code says which"); 0.6.6 sends
# more context overflows to 13 (Anthropic, Gemini, LiteLLM and HTTP 413 wordings), and 12 is the
# endpoint that is down, refusing or overloaded past the transport grace.
APPARATUS_CODES = (10, 11, 12, 13)
# Why the tool loop ended (CONTRACTS `stop_reason`; the StopReason type in prompt_loop.ts, the same
# 13 values in 0.6.5 and 0.6.6). A separate axis from the bucket: it never decides the verdict here.
STOP_REASONS = ("answered", "empty", "stall", "step_wall", "cancelled", "truncated", "tamper", "apparatus",
                "malformed", "endpoint_error", "in_progress", "killed", "deadline")


class UnknownNative(ValueError):
    """A native value the mapping does not know. It is never guessed."""


def _verify_status(record: dict):
    v = record.get("verify")
    if isinstance(v, dict):
        v = v.get("status")
    return v


def outcome(record: dict) -> dict:
    """Map one Gnomon task record to {verdict, apparatus_failure, tampered, native}."""
    bucket, code, status = record.get("bucket"), record.get("code"), _verify_status(record)
    native = {"bucket": bucket, "code": code, "verify": status, "stop_reason": record.get("stop_reason"),
              "verify_exit": record.get("verify_exit"), "verify_rounds": record.get("verify_rounds"),
              "verify_reason": record.get("verify_reason"), "exit": record.get("_exit")}
    flags = {"apparatus_failure": False, "tampered": False}
    if bucket not in BUCKETS:
        raise UnknownNative(f"unknown Gnomon bucket {bucket!r}")
    if not isinstance(code, int) or isinstance(code, bool):
        raise UnknownNative(f"Gnomon exit code must be an integer, got {code!r}")
    if bucket == "apparatus_failure":
        if code not in APPARATUS_CODES:
            raise UnknownNative(f"apparatus failure with an unknown exit code {code!r}")
        verdict, flags["apparatus_failure"] = "not measured", True
    elif bucket == "refusal":
        if code == 2:
            verdict = "violation"
        elif code == 3:
            verdict, flags["tampered"] = "not measured", True
        else:
            raise UnknownNative(f"refusal with an unknown exit code {code!r}")
    else:  # result
        if code != 0:
            raise UnknownNative(f"a result with exit code {code!r}")
        if status in VERIFY_PASSED:
            verdict = "passed"
        elif status in VERIFY_FAILED:
            verdict = "failed"
        elif status in VERIFY_NOT_MEASURED or status is None:
            verdict = "not measured"
        else:
            raise UnknownNative(f"unknown verify status {status!r}")
    assert verdict in VERDICTS
    return {"verdict": verdict, **flags, "native": native}
