"""A project folder set up for AI coding tools (FR-AGC1): every kind of file kernel/agent_context.py
recognises, with frontmatter, built in the test. Nothing here holds a real secret: the "secret-looking"
values are built so that the release's secret scan does not take them for real ones."""

import json
import subprocess
from pathlib import Path

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
       "-c", "core.autocrlf=false"]
STATED_TEST = 'python -m unittest discover -s checks -p "check_*.py"'
# A value the credential rules read as a secret, assembled so no file in the repository holds it whole.
FAKE_TOKEN = "ghp_" + "Zx9" * 12


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build(root: Path, *, code: bool = True) -> Path:
    """The folder: a README, the instructions of six tools, a skill with bundled files, a subagent, slash
    commands, hooks and permissions, three MCP configurations, personal settings and a little code."""
    write(root, "README.md", "# Loan desk\n\nThe library's loan desk: who borrowed what, and when it is due.\n")
    write(root, "CLAUDE.md", "# Loan desk: notes for Claude Code\n\n## Commands\n\n"
                             f"- Run the tests: `{STATED_TEST}`\n- Lint: `ruff check .`\n\n"
                             "```bash\nnpm run build\n```\n\n## Rules\n\n- Dates are stored in UTC.\n"
                             "- Never call the payment service from a request handler.\n")
    write(root, "AGENTS.md", "# Agents\n\nKeep every module under 300 lines. Loans are never deleted.\n")
    write(root, "GEMINI.md", "# Gemini\n\nAnswer in English.\n")
    write(root, "web/CLAUDE.md", "# The web folder\n\nEvery page escapes what it shows.\n")
    write(root, ".cursorrules", "Prefer small functions. The overdue list is sorted by due date.\n")
    write(root, ".cursor/rules/python.mdc", "---\ndescription: Python style for the service\nglobs: app/**/*.py, "
                                            "checks/*.py\nalwaysApply: false\n---\n\n# Python\n\nType hints on "
                                            "every public function.\n")
    write(root, ".cursor/rules/web.mdc", "---\ndescription: Web pages\nglobs: [\"web/**/*.ts\"]\n---\n\n"
                                         "# Web\n\nNo inline styles.\n")
    write(root, ".cursor/rules/always.mdc", "---\ndescription: House rules\nalwaysApply: true\n---\n\n"
                                            "Write the test first.\n")
    write(root, ".cursor/rules/db.mdc", "---\ndescription: Database migrations\n---\n\nMigrations are reversible.\n")
    write(root, ".cursor/commands/release.md", "# Release\n\nTag and push the release.\n")
    write(root, ".github/copilot-instructions.md", "# Copilot\n\nUse the standard library first.\n")
    write(root, ".github/instructions/tests.instructions.md", "---\napplyTo: \"checks/**\"\n---\n\nOne check per "
                                                              "behaviour.\n")
    write(root, ".windsurfrules", "Windsurf: keep the README current.\n")
    write(root, ".clinerules", "Cline: ask before deleting files.\n")
    write(root, ".claude/skills/loan-report/SKILL.md", "---\nname: loan-report\ndescription: >\n  Builds the "
                                                       "weekly overdue report\n  from the loans table.\n---\n\n"
                                                       "# Loan report\n\nRun scripts/report.py.\n")
    write(root, ".claude/skills/loan-report/scripts/report.py", "print('report')\n")
    write(root, ".claude/skills/loan-report/template.md", "# Weekly overdue loans\n")
    write(root, ".claude/agents/reviewer.md", "---\nname: reviewer\ndescription: Reviews a change for loan rules\n"
                                              "tools: Read, Grep\n---\n\nYou review changes.\n")
    write(root, ".claude/commands/overdue.md", "---\ndescription: List the overdue loans\n---\n\nList them.\n")
    write(root, ".claude/commands/db/migrate.md", "# Migrate the database\n\nRun the migrations.\n")
    write(root, ".claude/settings.json", json.dumps({
        "permissions": {"allow": ["Bash(npm run test:*)", "Read(./docs/**)"], "deny": ["Bash(rm -rf:*)"],
                        "ask": ["Bash(curl -H 'Authorization: Bearer $DESK_TOKEN':*)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
                                                                "command": "python hooks/never_run.py"}]}],
                  "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "ruff format"}]}]},
        "env": {"LOAN_DESK_MODE": "dev"}}, indent=2) + "\n")
    write(root, ".claude/settings.local.json", json.dumps({"permissions": {"allow": ["Bash(personal-only:*)"]},
                                                          "env": {"MY_OWN": "personal-value"}}) + "\n")
    write(root, "CLAUDE.local.md", "# Mine\n\npersonal notes\n")
    write(root, ".mcp.json", json.dumps({"mcpServers": {
        "loans-db": {"command": "/usr/local/bin/loans-mcp", "args": ["--dsn", "postgres://desk@db/loans"],
                     "env": {"LOANS_PASSWORD": "${LOANS_PASSWORD}"}},
        "docs": {"type": "http", "url": "https://docs.example.com/mcp?team=desk",
                 "headers": {"X-Team": "desk"}}}}, indent=2) + "\n")
    write(root, ".cursor/mcp.json", json.dumps({"mcpServers": {"tickets": {"command": "npx",
                                                                           "args": ["-y", "tickets-mcp"]}}}) + "\n")
    write(root, ".vscode/mcp.json", json.dumps({"servers": {"wiki": {"type": "sse",
                                                                     "url": "https://wiki.example.org/sse"}}}) + "\n")
    if code:
        write(root, "app/__init__.py", "")
        write(root, "app/loans.py", "def overdue(loans, today):\n    return sorted(l for l in loans if l < today)\n")
        write(root, "checks/__init__.py", "")
        write(root, "checks/check_loans.py", "import unittest\n\nfrom app.loans import overdue\n\n\n"
                                             "class Overdue(unittest.TestCase):\n    def test_sorted(self):\n"
                                             "        self.assertEqual(overdue([3, 1, 9], 5), [1, 3])\n")
    return root


def commit(root: Path) -> str:
    """Make ``root`` a git repository with everything committed but the personal files; return its head."""
    write(root, ".gitignore", ".claude/settings.local.json\nCLAUDE.local.md\n")
    subprocess.run([*GIT, "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=root, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "loan desk"], cwd=root, check=True)
    return subprocess.run([*GIT, "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()
