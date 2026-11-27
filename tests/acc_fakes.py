"""The demo home the developer acceptance tests read (tests/test_acc_developer.py, test_epics.py,
test_ui_acc_developer.py): built once per test process with the real kernel and the demo's scripted stand-ins
(kernel/demo.py), then copied for each test that writes, so no test sees another's records."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

_BUILT: dict[str, Path] = {}
STOCK, WEBHOOK = "stock-levels-service", "shipment-webhook-to-the-stock"


def _cleanup(root: Path) -> None:
    from kernel import roads

    roads.stop_started()
    roads.rmtree(root)


def demo_home() -> Path:
    """The built demo home (read only: copy it with ``copy_home`` before writing)."""
    if "home" not in _BUILT:
        from kernel.demo import build_demo

        root = Path(tempfile.mkdtemp(prefix="rihma-acc-demo-")).resolve()
        atexit.register(_cleanup, root)
        with mock.patch.dict(os.environ, {"GF_LANES": str(root / "lanes"), "GNOMON_CMD": "rihma-acc-no-such-gnomon"}):
            build_demo(root / "home", echo=lambda line: None)
        _BUILT["home"] = root / "home"
    return _BUILT["home"]


def copy_home(to: Path) -> Path:
    """A copy of the demo home at ``to``/home, for a test that writes."""
    shutil.copytree(demo_home(), to / "home")
    return to / "home"


def pid_of(factory: object, prefix: str) -> str:
    return next(p.pid for p in factory.projects() if p.pid.startswith(prefix))  # type: ignore[attr-defined]
