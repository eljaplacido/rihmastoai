"""Projects with Gnomon files of their own, for the Gnomon posture (FR-GNP1).

`WEAK` and `STRONG` are `.gnomon/config.toml` and `.gnomon/policy.toml` texts: the weak one runs shell commands on
the host, governs at observe, keeps an audit trail without a chain and uses the old `[sandbox] level` key; the
strong one sets every checked setting. `project(factory, tmp, files, folders=())` makes a project attached to a
folder of its own holding those files (and the named `.gnomon/` folders); `files=None` makes one with no `.gnomon`
folder. `write_routes(case, w)` is the signed cockpit write for the completeness tables (tests/test_brief_ln.py,
tests/test_access.py); `cli_writes(pid)` the signed command for tests/test_access.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WEAK = {
    "config.toml": '[defaults]\nedit_format = "str_replace"\n\n[audit]\nenabled = true\n',
    "policy.toml": ('[approval]\nmodes = ["ask", "auto"]\ndefault = "ask"\n\n[sandbox]\nlevel = "confined"\n'
                    'network = false\n\n[verify]\ncommand = "python -m pytest -q"\nafter = "always"\n\n'
                    '[governance]\nlevel = "observe"\n'),
}
STRONG = {
    "config.toml": ('[defaults]\nedit_format = "hashline"\n\n[context]\nretain = 8\n\n[resilience]\n'
                    'stream_idle_timeout_ms = 60000\n\n[audit]\nenabled = true\nchain = true\n\n[audit.anchor]\n'
                    'witness = "git"\n'),
    "policy.toml": ('[approval]\nmodes = ["ask"]\ndefault = "ask"\n\n[sandbox]\nexec = "os"\nnetwork = false\n'
                    'reads = "scoped"\n\n[verify]\ncommand = "python -m pytest -q"\nafter = "change"\n'
                    'protects = ["@detected"]\nexit_on_fail = true\n\n[governance]\nlevel = "prevent"\n'),
}


def project(factory: Any, tmp: Path, files: dict[str, str] | None, folders: tuple[str, ...] = (),
            title: str = "Shop app", folder: str = "shop-app") -> Any:
    """A project attached to a folder of its own holding ``files`` under `.gnomon/` (none when ``files`` is None)."""
    where = Path(tmp) / folder
    where.mkdir(parents=True, exist_ok=True)
    (where / "app.py").write_text("print('shop')\n", encoding="utf-8")
    if files is not None:
        (where / ".gnomon").mkdir(exist_ok=True)
        for name, text in files.items():
            (where / ".gnomon" / name).write_text(text, encoding="utf-8")
        for name in folders:
            (where / ".gnomon" / name).mkdir(exist_ok=True)
    p = factory.new_project(title)
    p.update_meta(source_kind="attached", attached={"repo": str(where)})
    return p


def write_routes(case: Any, w: dict[str, Any]) -> list:
    """A developer files the weak project's first suggestion as a change card, signed."""
    shop = project(case.factory, case.tmp, WEAK, folder="posture-shop")
    return [("post_gnomon_posture_propose", "POST", f"/api/projects/{shop.pid}/gnomon-posture/propose",
             lambda who, got: {"suggestion": "GP-sandbox-exec", "person": who, "persona": "developer"})]


def cli_writes(pid: str) -> dict[str, list[str]]:
    """The signed `rihmasto gnomon-posture` command (kernel/gnomon_posture/cli.py)."""
    return {"gnomon-posture propose": ["gnomon-posture", "propose", pid, "GP-sandbox-exec", "--person",
                                       "Mallory Example", "--persona", "developer"]}
