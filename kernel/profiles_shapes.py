"""Work profiles for the shapes real projects come in (FR-RPJ1; docs/guides/profiles.md, Real project shapes).

kernel/profiles.py holds the catalogue; these five join it: a game, an ML experiment or model, a knowledge or
tooling project (a second brain, scripts, local services), a library or command-line tool, and a data
pipeline. Each has its panel focus, questions and gates (what must hold before a release of that kind of
work counts), and each is recognised by rule from its words and, for an existing folder, from its files
(`file_hints`): a Godot, Unity or Unreal project file or an assets folder beside lore and world documents is
a game; training scripts, datasets and evaluation reports are an ML experiment; a notes vault is a knowledge
project; a package with an entry point and no screens is a library or CLI; DAGs and dbt models are a pipeline.
The ML experiment profile ties to D-0020: its runs, metrics and model cards are evidence like any other.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

SHAPES: dict[str, dict[str, Any]] = {
    "game": {
        "deliverable": "product", "label": "Game", "icon": "gamepad", "status": "preview", "template": "web-service",
        "summary": "A game: its code, assets, levels, world and lore, its builds and playtests.",
        "keywords": ["game", "gamedev", "godot", "unity", "unreal", "lore", "worldbuilding", "playtest*", "sprite*",
                     "npc", "gameplay", "game world", "peli", "pelit", "pelimaailm*"],
        "panel_focus": {
            "end_user": "the player's first minutes, the core loop and what a playtest showed",
            "delivery": "the asset pipeline, the build per platform and which levels are playable",
            "business": "the milestone the next build serves (a vertical slice, a demo, a release)",
        },
        "seed_questions": [
            {"text": "Which build or milestone comes next, and what must be playable in it?", "perspective": "business",
             "proposed": "a playable vertical slice of one level, from start to its end",
             "options": ["a playable vertical slice of one level, from start to its end",
                         "a demo build for a showcase", "an internal playtest build"]},
            {"text": "How is a build checked before people play it?", "perspective": "delivery",
             "proposed": "it builds headless, its scenes load, and a smoke playtest reaches the first goal",
             "options": ["it builds headless, its scenes load, and a smoke playtest reaches the first goal",
                         "a person plays it through by hand", "it builds: nothing more yet"]},
        ],
        "screens": True,
        "spec_guidance": "Write criteria a build can show: the project builds headless, each scene loads, the core "
                         "loop's first goal is reachable in a scripted playtest. Assets, levels and lore are "
                         "tracked by area (how much changed, what is new), not judged by a model.",
        "gates": ["the project builds headless", "every scene in the build loads", "a smoke playtest reaches the "
                  "first goal", "no asset is missing from the build"],
        "widgets": ["releases"],
        "vocabulary": {"release": "build", "criterion": "check"},
        "note": "Monitored by area (assets, levels, world, lore) through its repository; a game template is not built.",
    },
    "ml_experiment": {
        "deliverable": "report", "label": "ML experiment or model", "icon": "flask", "status": "preview",
        "template": "web-service",
        "summary": "A training or fine-tuning experiment, or a model: datasets, runs, metrics, evaluations and a "
                   "model card, tracked and evaluated.",
        "keywords": ["fine-tun*", "finetun*", "training run", "experiment*", "lora", "checkpoint*", "hyperparameter*",
                     "epoch*", "wandb", "mlflow", "model card", "eval set", "perplexity", "kokeilu*"],
        "panel_focus": {
            "business": "the question the experiment answers and the metric that decides it",
            "delivery": "the runs, their configurations, the data versions and whether a run can be reproduced",
            "it_security": "the data's source, licence and personal data, and where the weights may go",
        },
        "seed_questions": [
            {"text": "What does the experiment have to show, and on which metric?", "perspective": "business",
             "proposed": "a metric on a fixed evaluation set beats the named baseline",
             "options": ["a metric on a fixed evaluation set beats the named baseline",
                         "it is exploratory: record what was learned", "a model card good enough to publish"]},
        ],
        "screens": False,
        "spec_guidance": "Each claim names its run, its data version and its metric on a fixed evaluation set; a "
                         "result without its run is not measured. The model card says what the model is for and "
                         "what it was not tested on (D-0020).",
        "gates": ["each reported metric names its run and its evaluation set", "the evaluation set is fixed and "
                  "versioned", "a model card states its limits"],
        "widgets": ["eval_trend"],
        "vocabulary": {"release": "run", "criterion": "metric"},
        "note": "Tracked and evaluated from its documents and results; nothing is trained by the factory.",
    },
    "knowledge_tooling": {
        "deliverable": "product", "label": "Knowledge or tooling", "icon": "book", "status": "preview",
        "template": "web-service",
        "summary": "Notes, scripts and local services that support a person's own work: a second brain, a "
                   "dev toolbox, an internal helper.",
        "keywords": ["second brain", "vault", "obsidian", "zettelkasten", "knowledge base", "toolbox", "dotfiles",
                     "local service*", "muistiinpano*"],
        "panel_focus": {
            "business": "what the person relies on it for every day, and what must never break",
            "it_security": "which personal notes, keys and local services it touches",
            "operations": "what runs on the machine, when, and how a person knows it stopped",
        },
        "seed_questions": [
            {"text": "What do you rely on it for every day?", "perspective": "business",
             "proposed": "finding and linking my notes, and the scripts I run daily",
             "options": ["finding and linking my notes, and the scripts I run daily",
                         "a local service other tools call", "an archive I rarely change"]},
        ],
        "screens": False,
        "spec_guidance": "Keep what the person relies on as criteria: its scripts run, its local services answer, "
                         "its notes stay linked. Personal notes are material, never shared beyond the project.",
        "gates": ["its scripts' own checks pass", "its local services answer where they run"],
        "widgets": ["releases"],
        "vocabulary": {"release": "version"},
        "note": "Monitored and maintained as it is; nothing is rebuilt.",
    },
    "library_cli": {
        "deliverable": "product", "label": "Library or command-line tool", "icon": "terminal", "status": "preview",
        "template": "web-service",
        "summary": "A package other code imports, or a command-line tool people run: its API, its commands and "
                   "its releases.",
        "keywords": ["sdk", "cli", "command-line", "command line", "pip install", "npm install", "crate",
                     "python package", "komentori*"],
        "panel_focus": {
            "delivery": "the public API or commands, semantic versions and what a breaking change is",
            "end_user": "the developer's first five minutes: install, the first call, the error messages",
        },
        "seed_questions": [
            {"text": "What counts as a breaking change?", "perspective": "delivery",
             "proposed": "any change to a public function, command or flag, released as a new major version",
             "options": ["any change to a public function, command or flag, released as a new major version",
                         "we do not promise compatibility yet", "only documented behaviour"]},
        ],
        "screens": False,
        "spec_guidance": "Each public function or command has a test; a breaking change is a criterion of its own. "
                         "The install and first-run journey is a holdout.",
        "gates": ["its test suite passes", "the package builds and installs", "the changelog names breaking changes"],
        "widgets": ["releases"],
        "vocabulary": {"release": "version"},
    },
    "data_pipeline": {
        "deliverable": "product", "label": "Data pipeline", "icon": "pipeline", "status": "preview",
        "template": "web-service",
        "summary": "Moves and transforms data on a schedule: ingestion, transformations, quality checks and the "
                   "tables or files it delivers.",
        "keywords": ["data pipeline", "elt", "airflow", "dag", "dbt", "data warehouse", "ingest*", "spark",
                     "lakehouse", "data quality", "tietoputk*"],
        "panel_focus": {
            "business": "which tables or files people use, and how fresh they must be",
            "operations": "the schedule, late or failed runs, backfills and who is told",
            "it_security": "the sources, personal data, and where the outputs land",
        },
        "seed_questions": [
            {"text": "How fresh must its outputs be, and who is told when a run fails?", "perspective": "operations",
             "proposed": "daily by 06:00; a failed run tells the data owner",
             "options": ["daily by 06:00; a failed run tells the data owner", "hourly", "on demand"]},
        ],
        "screens": False,
        "spec_guidance": "Each output has a data-quality criterion (row counts, nulls, keys) on a fixed sample; "
                         "freshness is a probe; a backfill is a holdout.",
        "gates": ["data-quality checks pass on the sample", "a run finishes within its window"],
        "widgets": ["feed_health"],
        "vocabulary": {"release": "release", "criterion": "check"},
    },
}

# -- recognised by its files ---------------------------------------------------------------------------

_GAME_FILE = re.compile(r"(?i)(^|/)(project\.godot|[\w.-]+\.uproject|[\w.-]+\.unity|ProjectSettings/ProjectVersion\.txt"
                        r"|[\w.-]+\.(tscn|tres|umap|uasset|prefab|blend|fbx|gdshader))$")
_GAME_DIR = re.compile(r"(?i)(^|/)(assets?|levels?|maps|scenes|sprites|textures|lore|world|worldbuilding|quests"
                       r"|characters|dialogues?)/")
_ML_FILE = re.compile(r"(?i)(^|/)((train|finetune|fine_tune|eval(uate)?|sweep)[\w-]*\.(py|ipynb|ya?ml|sh|log)"
                      r"|[\w.-]+\.(ipynb|safetensors|ckpt|pt|pth|onnx|gguf)|model[-_]?card\.md|results?\.(zip|csv|json)"
                      r"|metrics?\.(csv|json)|(eval|evaluation)[-_ ]?(report|results?)[\w.-]*)$")
_ML_DIR = re.compile(r"(?i)(^|/)(datasets?|data/(raw|processed)|runs|checkpoints|experiments?|wandb|mlruns|evals?)/")
_NOTES_DIR = re.compile(r"(?i)(^|/)(\.obsidian|\.logseq|notes|vault|journal|daily|zettel\w*|inbox)/")
_LIB_FILE = re.compile(r"(?i)(^|/)(setup\.py|pyproject\.toml|cargo\.toml|package\.json|[\w.-]+\.gemspec|go\.mod)$")
_CLI_DIR = re.compile(r"(?i)(^|/)(bin|cli|cmd)/")
_PIPE = re.compile(r"(?i)(^|/)(dags/|dbt_project\.yml|airflow[\w.-]*\.(cfg|ya?ml|py)|[\w.-]*\.dag\.py"
                   r"|great_expectations/)")


Hint = dict[str, Any]


def _hit(profile: str, words: list[str], why: str) -> Hint:
    return {"profile": profile, "words": words, "why": why}


def _matching(files: list[str], rule: re.Pattern[str]) -> list[str]:
    return [p for p in files if rule.search(p)][:3]


def _folders(files: list[str], rule: re.Pattern[str]) -> list[str]:
    return sorted({m.group(2).lower() for p in files if (m := rule.search(p))})


def _game(files: list[str]) -> Hint | None:
    engine, dirs = _matching(files, _GAME_FILE), _folders(files, _GAME_DIR)
    if engine:
        return _hit("game", ["game", "gameplay", "game world"], f"a game engine's files ({', '.join(engine)})")
    if len(dirs) >= 2:
        words = ["game", "game world"] if len(dirs) >= 3 else ["game"]
        return _hit("game", words, f"folders named {', '.join(dirs[:4])}")
    return None


def _ml(files: list[str]) -> Hint | None:
    ml, dirs = _matching(files, _ML_FILE), _folders(files, _ML_DIR)
    if ml and (dirs or len(ml) > 1):
        return _hit("ml_experiment", ["experiment", "training run", "eval set"],
                    f"training or evaluation files ({', '.join(ml)})")
    return _hit("ml_experiment", ["experiment"], ", ".join(ml or dirs)) if ml or dirs else None


def _notes(files: list[str]) -> Hint | None:
    notes = _folders(files, _NOTES_DIR)
    md = sum(1 for p in files if PurePosixPath(p.lower()).suffix in (".md", ".markdown"))
    return _hit("knowledge_tooling", ["vault", "knowledge base", "second brain"],
                f"a notes folder ({', '.join(notes[:3])}) and {md} notes") if notes and md >= 5 else None


_UNIT = re.compile(r"(?i)(^|/)[\w.@-]+\.(service|timer|socket)$|(^|/)launchagents/[\w.-]+\.plist$")


def _services(files: list[str]) -> Hint | None:
    """Service units a person runs on their own machines (systemd units and timers, launchd agents) with no
    package manifest: a toolbox of local services and scripts, not a product that is shipped."""
    units = _matching(files, _UNIT)
    if not units or any(_LIB_FILE.search(p) for p in files):
        return None
    return _hit("knowledge_tooling", ["toolbox", "local service"], f"service units of its own ({', '.join(units)})")


def _pipeline(files: list[str]) -> Hint | None:
    pipe = _matching(files, _PIPE)
    return _hit("data_pipeline", ["data pipeline", "dag", "data quality"],
                f"pipeline files ({', '.join(pipe)})") if pipe else None


def _cli(files: list[str]) -> Hint | None:
    found = any(_LIB_FILE.search(p) for p in files) and any(_CLI_DIR.search(p) for p in files)
    return _hit("library_cli", ["cli"], "a package manifest and a bin, cli or cmd folder") if found else None


def file_hints(paths: Iterable[str]) -> list[Hint]:
    """The profiles a folder's files point to, with the words they add to the proposal and why: three of the
    profile's words for a strong sign (a Godot project file), one or two for a weaker one (an assets folder)."""
    files = [p.replace("\\", "/") for p in paths]
    out = [h for h in (rule(files) for rule in (_game, _ml, _notes, _pipeline)) if h]
    services = _services(files)
    if services and not any(h["profile"] == "knowledge_tooling" for h in out):   # a notes vault says it already
        out.append(services)
    cli = _cli(files)
    return out + ([cli] if cli and not any(h["profile"] == "game" for h in out) else [])


def hint_text(hints: list[dict[str, Any]]) -> str:
    """The hints' words, as text a proposal by rule reads beside the title and the README."""
    return "\n".join(" ".join(h["words"]) for h in hints)
