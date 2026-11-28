"""The reachability doctor (FR-RCH1): test a connection Rihmasto needs, say why it fails, and how to fix it.

The owner (2026-11-27), after an afternoon of "permission denied", "connection reset" and pasted logs between two
computers: "when these situations occur in the future, whether it's in terminal or chat or moving back and forth,
this should happen in Rihmasto, not going elsewhere." So wherever Rihmasto says something is not reachable, Test
connection gives:

- a plain **verdict** with the specific reason (``VERDICTS``): the name does not resolve, no route, refused,
  timed out, an unknown host key, the key refused, signed in but the session dropped (a Windows SSH server and a
  directory account), the tool missing; for an https address its status or why not; for a folder, whether it is
  there and a git working copy;
- the **fix**, as numbered steps for the target's system (``FIXES``): what to run there, by whom;
- a **drafted ask** (kernel/asks.py) to the agent on that machine with the same steps, offered as a card the person
  confirms ("Send to the agent on laptop"); nothing is sent without that Confirm.

A test only reads: ``ssh -v -o BatchMode=yes -o ConnectTimeout=… <address> exit`` (it never accepts a host key, never
asks for a password and runs nothing there), one https GET, ``gh auth status``, a folder's existence. Its output is
classified here and dropped: only the verdict is kept or shown. The public key offered for a fix is read from this
machine's ``~/.ssh/*.pub`` (never a private key).
"""

from __future__ import annotations

import ipaddress
import shutil
import socket
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import machines, wip
from kernel.learn import FACTORY_PID

TIMEOUT = 15                 # seconds for one test: a machine that does not answer says so, never hangs a page
Runner = Callable[[list[str], float], tuple[int, str]]      # argv, timeout -> (exit code, its stderr and stdout)
Opener = Callable[[str, float], int]                        # url, timeout -> HTTP status (raises when it cannot)

VERDICTS = {
    "ok": "reachable",
    "dns": "its name does not resolve from this machine",
    "no_route": "there is no network route to it",
    "refused": "it refuses the connection: nothing listens there (no SSH server running, or the port is closed)",
    "timeout": "it does not answer: it is off, asleep, or a firewall drops the connection",
    "host_key": "its host key is not known to this machine yet, so the connection was not trusted",
    "auth_denied": "it answers, but refuses this machine's key for that user",
    "session_reset": "the key was accepted, but the machine dropped the session as it started",
    "no_tool": "this machine has no ssh client to test with",
    "unknown": "the connection failed for a reason the test does not recognise",
    "http_error": "it answers, with an error status",
    "tls": "its certificate is not trusted from this machine",
    "not_found": "the folder is not there on this machine",
    "not_git": "the folder is not a git working copy",
    "gh_signed_out": "the GitHub command line is not signed in on this machine",
}
FAIL = {k for k in VERDICTS if k != "ok"}

# What ``ssh -v`` prints, read in this order: the first that matches is the verdict.
_SSH = (("session_reset", ("Authenticated to",), ("reset by peer", "Connection closed by", "closed by remote host",
                                                   "client_loop: send disconnect")),
        ("host_key", ("Host key verification failed",), ()),
        ("auth_denied", ("Permission denied",), ()),
        ("dns", ("Could not resolve hostname", "Name or service not known", "nodename nor servname"), ()),
        ("no_route", ("No route to host", "Network is unreachable"), ()),
        ("refused", ("Connection refused",), ()),
        ("timeout", ("timed out", "Operation timed out"), ()))


def classify_ssh(code: int, output: str) -> str:
    """The verdict of one ``ssh -v -o BatchMode=yes … exit`` run, from its exit code and what it printed."""
    if code == 0:
        return "ok"
    for verdict, needles, also in _SSH:
        if any(n in output for n in needles) and (not also or any(a in output for a in also)):
            return verdict
    return "unknown"


def _ssh_runner(argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        run = subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return 255, "ssh: connect: Connection timed out"
    return run.returncode, (run.stderr + run.stdout).decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> Any:
        return None  # a redirect is an answer, never followed (prevents https -> loopback/http downgrade)


def _opener(url: str, timeout: float) -> int:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "rihmasto-reach"})
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(req, timeout=timeout) as res:   # noqa: S310 - an https address the person set
        return int(res.status)


def public_key() -> tuple[str | None, str | None]:
    """This machine's public key for a fix (its path and its one line), or (None, None). Never a private key."""
    for name in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"):
        path = Path.home() / ".ssh" / name
        try:
            line = path.read_text(encoding="utf-8").strip().splitlines()[0]
        except (OSError, IndexError):
            continue
        if line.startswith(("ssh-", "ecdsa-")) and "PRIVATE" not in line:
            return str(path), line
    return None, None


def this_machine() -> str:
    return socket.gethostname().split(".")[0].lower() or "this machine"


# -- the fix, for the target's system ----------------------------------------------------------------------------

def _key_steps(system: str, key: str | None) -> list[str]:
    line = key or "<this machine's public key: the one line of ~/.ssh/id_ed25519.pub>"
    if system == "windows":
        return [f"Add this public key on one line: {line}",
                "If the account is an administrator: to C:\\ProgramData\\ssh\\administrators_authorized_keys, then "
                "limit that file to Administrators and SYSTEM: icacls "
                "C:\\ProgramData\\ssh\\administrators_authorized_keys /inheritance:r /grant \"Administrators:F\" "
                "/grant \"SYSTEM:F\"",
                "Otherwise: to %USERPROFILE%\\.ssh\\authorized_keys, readable by that user and SYSTEM only",
                "Check the user name the connection uses: a directory (company sign-in) account is domain\\user",
                "Restart-Service sshd"]
    return [f"Add this public key on one line to ~/.ssh/authorized_keys: {line}",
            "chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys",
            "Check the user name the connection uses is that account's"]


def _server_steps(system: str) -> list[str]:
    if system == "windows":
        return ["In an administrator PowerShell: Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 "
                "(or: winget install Microsoft.OpenSSH.Preview)",
                "Start-Service sshd; Set-Service sshd -StartupType Automatic",
                "Allow inbound TCP 22 in the firewall for your private network only"]
    if system == "macos":
        return ["System Settings > General > Sharing: turn on Remote Login, for the users who may sign in"]
    return ["sudo apt install openssh-server (or your system's package)", "sudo systemctl enable --now ssh",
            "Allow inbound TCP 22 for your private network only"]


def _reset_steps(system: str) -> list[str]:
    if system == "windows":
        return ["Read the SSH server's log: Get-WinEvent -LogName OpenSSH/Operational -MaxEvents 15 | "
                "Format-List TimeCreated,Message",
                "Check that no broken DefaultShell is set (HKLM:\\SOFTWARE\\OpenSSH) and that sshd_config has "
                "no ForceCommand",
                "A directory (company sign-in) account often gets no session from a key alone: create a local "
                "account with read access to the project folders, put the key in its own authorized_keys, and "
                "connect as that account"]
    return ["Check the account's login shell and any ForceCommand in sshd_config",
            "Read the SSH server's log (journalctl -u ssh)"]


def _network_steps(address: str) -> list[str]:
    return ["Check the machine is on and awake", f"Check it is on the same network or private network (VPN) as "
            f"this machine, and that {address.split('@')[-1] or 'its name'} resolves here", "Then test again"]


def _host_key_steps(address: str) -> list[str]:
    return [f"Connect once by hand from this machine (ssh {address or '<address>'}) and accept the host key only "
            "if its fingerprint matches the one the machine itself shows (ssh-keygen -lf on its host key); "
            "Rihmasto never accepts a host key for you"]


# Each verdict's steps, from (system, address, key).
_FIXES: dict[str, Callable[[str, str, str | None], list[str]]] = {
    "ok": lambda s, a, k: [],
    "dns": lambda s, a, k: _network_steps(a),
    "no_route": lambda s, a, k: _network_steps(a),
    "refused": lambda s, a, k: [*_server_steps(s), "Then test again"],
    "timeout": lambda s, a, k: ["Check the machine is on and not asleep",
                                "Allow inbound TCP 22 from your private network", "Then test again"],
    "host_key": lambda s, a, k: _host_key_steps(a),
    "auth_denied": lambda s, a, k: _key_steps(s, k),
    "session_reset": lambda s, a, k: _reset_steps(s),
    "no_tool": lambda s, a, k: ["Install the OpenSSH client on this machine"],
    "http_error": lambda s, a, k: ["Open the address in a browser on this machine to see the error",
                                   "Check the service behind it runs"],
    "not_found": lambda s, a, k: ["Check the folder's path, or clone the repository there",
                                  "Or adopt the project from the machine that holds it"],
    "not_git": lambda s, a, k: ["Point the project at the repository's own folder (the one with .git)"],
    "gh_signed_out": lambda s, a, k: ["Run gh auth login on this machine (you sign in yourself)"],
}
_FIXES["tls"] = _FIXES["http_error"]


def fix(verdict: str, system: str = "unknown", *, address: str = "", key: str | None = None) -> list[str]:
    """Numbered steps that fix ``verdict`` on a target running ``system``."""
    steps = _FIXES.get(verdict)
    return steps(system, address, key) if steps else ["Run the same test by hand with ssh -v and read the last lines"]


# -- the tests -------------------------------------------------------------------------------------------------

def test_ssh(address: str, *, runner: Runner | None = None, timeout: float = TIMEOUT) -> str:
    if not machines.SSH_ADDRESS.match(str(address or "")):
        raise machines.MachineRefused("an ssh address is an alias or user@host (never an option starting with '-')")
    if runner is None:
        if shutil.which("ssh") is None:
            return "no_tool"
        runner = _ssh_runner
    code, out = runner(["ssh", "-v", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={int(timeout)}", "--", address,
                        "exit"], timeout + 5)
    return classify_ssh(code, out)


def test_https(url: str, *, opener: Opener | None = None, timeout: float = TIMEOUT) -> tuple[str, int | None]:
    try:
        status = (opener or _opener)(url, timeout)
    except urllib.error.HTTPError as exc:
        return "http_error", exc.code
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        text = str(reason)
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in text.upper():
            return "tls", None
        if isinstance(reason, socket.gaierror) or "getaddrinfo" in text or "Name or service" in text:
            return "dns", None
        if isinstance(reason, ConnectionRefusedError) or "refused" in text.lower():
            return "refused", None
        if isinstance(reason, TimeoutError) or "timed out" in text.lower():
            return "timeout", None
        return "unknown", None
    return ("ok" if status < 400 else "http_error"), status


def test_gh(*, runner: Runner | None = None) -> str:
    if runner is None:
        if shutil.which("gh") is None:
            return "no_tool"
        runner = _ssh_runner
    code, _ = runner(["gh", "auth", "status"], TIMEOUT)
    return "ok" if code == 0 else "gh_signed_out"


# -- the doctor -------------------------------------------------------------------------------------------------

def _result(kind: str, target: str, verdict: str, system: str, *, address: str = "", status: int | None = None,
            machine: dict[str, Any] | None = None) -> dict[str, Any]:
    _, key = public_key() if verdict == "auth_denied" else (None, None)
    said = VERDICTS[verdict] + (f" (HTTP {status})" if status else "")
    out = {"kind": kind, "target": target, "verdict": verdict, "ok": verdict == "ok",
           "said": f"{target}: {said}.", "fix": fix(verdict, system, address=address, key=key), "os": system,
           "tested_from": this_machine()}
    if machine is not None and verdict != "ok":
        out["draft"] = draft_ask(machine, out)
    return out


def draft_ask(machine: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """The ask Rihma offers to the agent on ``machine`` when it cannot reach it: the same steps, for that agent to do
    (or for the person to do by hand there). Never sent without the person's Confirm."""
    agent = (machine.get("agents") or ["agent"])[0]
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(result["fix"], 1))
    return {"to": agent, "machine": machine["name"],
            "text": f"Rihmasto on {result['tested_from']} cannot reach {machine['name']}: "
                    f"{VERDICTS[result['verdict']]}. Please, on {machine['name']}:\n{steps}",
            "why": f"so Rihmasto can read the work on {machine['name']} and carry asks to its agents",
            "expects": "done, or the exact error you see at the step that fails",
            "source": {"reach": result["verdict"], "machine": machine["name"]}}


def test_machine(factory: Any, name: str, *, runner: Runner | None = None, opener: Opener | None = None
                 ) -> dict[str, Any]:
    m = machines.get(factory, name)
    if m is None:
        raise machines.MachineRefused(f"there is no machine {name!r}: add it first")
    system = m.get("os") or "unknown"
    if m["reach"] == "ssh":
        return _result("machine", m["name"], test_ssh(m["address"], runner=runner), system, address=m["address"],
                       machine=m)
    if m["reach"] == "https":
        verdict, status = test_https(m["address"], opener=opener)
        return _result("machine", m["name"], verdict, system, status=status, machine=m)
    return {"kind": "machine", "target": m["name"], "verdict": "hand", "ok": False, "os": system, "fix": [],
            "said": f"{m['name']} is reached by hand: asks to its agents go by copy and paste.",
            "tested_from": this_machine()}


def test_project(project: Any) -> dict[str, Any]:
    """The project's own working copy on this machine: there, and a git working copy."""
    path, why = wip.working_copy(project)
    if path is not None:
        return {"kind": "project", "target": project.pid, "verdict": "ok", "ok": True, "fix": [], "os": "unknown",
                "said": f"{project.pid}: its working copy {path} is here.", "tested_from": this_machine()}
    verdict = "not_git" if why and "not a git" in why else "not_found"
    out = {"kind": "project", "target": project.pid, "verdict": verdict, "ok": False, "os": "unknown",
           "said": f"{project.pid}: {why}.", "fix": fix(verdict), "tested_from": this_machine()}
    elsewhere = [m for m in machines.listed(project.factory) if m["reach"] != "hand" or m.get("agents")]
    if elsewhere:
        m = elsewhere[0]
        out["draft"] = {"to": (m.get("agents") or ["agent"])[0], "machine": m["name"],
                        "text": f"Rihmasto cannot read {project.meta.get('title') or project.pid} here: {why}. If the "
                                f"working copy is on {m['name']}, please reply with its folder, its branch and "
                                f"git status --short | head -20.",
                        "why": "so Rihmasto reads the project from the copy where the work happens",
                        "expects": "the folder, the branch and the first lines of git status",
                        "source": {"reach": verdict, "project": project.pid}}
    return out


def _check_ad_hoc_https(url: str) -> None:
    """Ad-hoc https:// probes must not target loopback, link-local or private addresses (add a machine if needed)."""
    host = (urllib.parse.urlsplit(url).hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise machines.MachineRefused("ad-hoc https checks refuse localhost: add a machine in Settings if intended")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved:
        raise machines.MachineRefused(
            "ad-hoc https checks refuse loopback or private IP addresses: add a machine in Settings if intended"
        )


def doctor(factory: Any, target: str, *, runner: Runner | None = None, opener: Opener | None = None
           ) -> dict[str, Any]:
    """Test what ``target`` names: a machine of the list, a project (its working copy here), an https address, or
    ``github`` (the GitHub command line)."""
    t = str(target or "").strip()
    if not t:
        raise machines.MachineRefused("name what to test: a machine, a project, an https:// address or github")
    if machines.get(factory, t):
        return test_machine(factory, t, runner=runner, opener=opener)
    if t.lower() == "github":
        verdict = test_gh(runner=runner)
        return _result("github", "GitHub command line", verdict, "unknown")
    if t.startswith("https://"):
        _check_ad_hoc_https(t)
        verdict, status = test_https(t, opener=opener)
        return _result("https", t, verdict, "unknown", status=status)
    if t != FACTORY_PID and t in {p.pid for p in factory.projects()}:
        return test_project(factory.project(t))
    raise machines.MachineRefused(f"{t!r} is not a machine, a project, an https:// address or github")
