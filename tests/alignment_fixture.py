"""A repository with its own development structure, for the alignment tests (FR-ALN1).

`make_repo` writes and commits a small loans service the way a team in an IDE keeps it: a spec-kit feature
(spec, plan, tasks), a Kiro spec (requirements and tasks), two ADRs, a Gherkin feature, an OpenAPI contract,
a pytest suite and a jest suite, a GitHub Actions workflow that does not run the tests, quality tools, an AI
tool's instructions and a secret that must never be read. The specs are committed in January and the code in
March, so a spec is older than the code it describes. `change_repo` makes the change a re-scan finds as drift.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SECRET_VALUE = "sk-" + "live-4f9b2c7d1e8a6b3c5d0e9f7a2b4c6d8e"   # built at run time: no key-shaped literal ships

SPEC_KIT = """# Feature Specification: Loan items

**Feature Branch**: `001-loan-items`

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Borrow an item (Priority: P1)

A team member borrows a drill from the tool store. Implemented in src/items.py.

**Acceptance Scenarios**:

1. **Given** an item that is in the store, **When** a member borrows it, **Then** the item is marked as on loan
2. **Given** an item on loan, **When** another member tries to borrow it, **Then** the request is refused with a message

### User Story 2 - Return an item (Priority: P2)

A borrower brings the item back.

**Acceptance Scenarios**:

1. **Given** an item on loan, **When** the borrower returns it, **Then** the item is back in the store

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST list every item with its state
- **FR-002**: System MUST keep a history of loans per item
- **FR-003**: The interface MUST be user-friendly
"""

SPEC_KIT_TASKS = """# Tasks: Loan items

- [x] T001 Create the item model in src/items.py
- [ ] T002 [P] Add the loan history endpoint for FR-002
- [x] T003 Borrow an item [US1]
"""

KIRO_REQS = """# Requirements Document

## Introduction

Overdue loans are flagged for the store keeper.

## Requirements

### Requirement 1

**User Story:** As a store keeper, I want overdue loans flagged, so that I can chase them.

#### Acceptance Criteria

1. WHEN a loan is older than 14 days THEN the system SHALL mark it overdue
2. WHEN the store keeper opens the list THEN the system SHALL show overdue loans first
"""

KIRO_TASKS = """# Implementation Plan

- [ ] 1. Flag overdue loans
  - _Requirements: 1.1_
- [x] 2. Sort the list with overdue loans first
  - _Requirements: 1.2_
"""

ADR_1 = """# 1. Record architecture decisions

Date: 2026-01-10

## Status

Accepted

## Context

We need to record the architectural decisions made on this project.
"""

ADR_2 = """# 2. Keep loans in SQLite

Date: 2026-01-12

## Status

Proposed

## Decision

Loans are kept in one SQLite file.
"""

FEATURE = """@REQ-SEARCH
Feature: Search items

  Scenario: Search by name
    Given the store holds a drill and a saw
    When a member searches for "drill"
    Then only the drill is listed
"""

OPENAPI = """openapi: 3.0.3
info:
  title: Loans API
  version: 1.2.0
paths:
  /items:
    get:
      operationId: listItems
      summary: List every item
  /items/{id}/borrow:
    post:
      operationId: borrowItem
      summary: Borrow an item
"""

PYTEST = '''import pytest

from src.items import Store


def test_borrow_marks_the_item_on_loan():
    """A member borrows an item in the store: it is on loan."""
    assert Store().borrow("drill")


def test_FR_001_lists_every_item_with_its_state():
    assert Store().items() == []


def test_return_puts_the_item_back_in_the_store():
    assert Store().give_back("drill")


def test_configuration_loads_defaults():
    assert True
'''

JEST = """describe('overdue loans', () => {
  it('marks a loan older than 14 days overdue', () => {
    expect(true).toBe(true);
  });
  it('shows overdue loans first in the list', () => {
    expect(true).toBe(true);
  });
});
"""

WORKFLOW = """name: ci
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint
        run: ruff check .
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          npm ci
          npm run build
"""

PACKAGE = """{"name": "loans-web", "scripts": {"test": "jest", "build": "echo build"},
 "devDependencies": {"jest": "^29.0.0"}}
"""

PYPROJECT = """[project]
name = "loans"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
"""

FIRST = {
    "specs/001-loan-items/spec.md": SPEC_KIT,
    "specs/001-loan-items/plan.md": "# Implementation Plan: Loan items\n\nPython 3.12, src/items.py.\n",
    "specs/001-loan-items/tasks.md": SPEC_KIT_TASKS,
    ".kiro/specs/overdue/requirements.md": KIRO_REQS,
    ".kiro/specs/overdue/tasks.md": KIRO_TASKS,
    "docs/adr/0001-record-architecture-decisions.md": ADR_1,
    "docs/adr/0002-keep-loans-in-sqlite.md": ADR_2,
    "features/search.feature": FEATURE,
    "api/openapi.yaml": OPENAPI,
    "docs/architecture.md": "# Architecture\n\nOne service and one web page.\n",
    "README.md": "# Loans\n\nThe tool store's loans.\n",
}
SECOND = {
    "src/__init__.py": "",
    "src/items.py": "class Store:\n    def items(self):\n        return []\n",
    "tests/test_loans.py": PYTEST,
    "web/loans.test.js": JEST,
    "package.json": PACKAGE,
    "pyproject.toml": PYPROJECT,
    ".github/workflows/ci.yml": WORKFLOW,
    ".pre-commit-config.yaml": "repos:\n  - repo: local\n    hooks:\n      - id: ruff\n",
    "CLAUDE.md": "# Loans\n\nRun the tests with pytest.\n",
    ".env": f"LOANS_API_TOKEN={SECRET_VALUE}\n",
}


def git(root: Path, *args: str, when: str = "2026-01-05T10:00:00+00:00") -> str:
    env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when, GIT_AUTHOR_NAME="Dev",
               GIT_AUTHOR_EMAIL="dev@example.org", GIT_COMMITTER_NAME="Dev", GIT_COMMITTER_EMAIL="dev@example.org",
               GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=root, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def make_repo(root: Path) -> Path:
    """The repository, committed on main: the specs in January, the code and tests in March."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    write(root, FIRST)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Specs and decisions", when="2026-01-05T10:00:00+00:00")
    write(root, SECOND)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Code, tests and CI", when="2026-03-01T10:00:00+00:00")
    return root


def change_repo(root: Path) -> None:
    """A later change: a new requirement, a criterion restated, a test removed and a new one added."""
    spec = (root / "specs/001-loan-items/spec.md").read_text(encoding="utf-8")
    spec = spec.replace("**Then** the item is back in the store", "**Then** the item is back in the store and its loan closed")
    spec = spec.replace("- **FR-003**", "- **FR-004**: System MUST export loans as CSV\n- **FR-003**")
    write(root, {"specs/001-loan-items/spec.md": spec,
                 "tests/test_loans.py": PYTEST.replace("def test_configuration_loads_defaults():\n    assert True\n",
                                                       "def test_FR_004_exports_loans_as_csv():\n    assert True\n")})
    (root / "features/search.feature").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "CSV export", when="2026-04-01T10:00:00+00:00")
