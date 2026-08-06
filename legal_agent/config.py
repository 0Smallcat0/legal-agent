"""Project-wide paths and constants + runtime model config. Kept deliberately
tiny: the spec calls for a minimal personal-use build, not a config framework.
"""
import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
# Repo root. Valid only in a git checkout — an installed copy lives in
# site-packages, where this points at site-packages itself. Nothing needed at
# runtime may hang off it; shipped data hangs off PACKAGE_ROOT.
PROJECT_ROOT = PACKAGE_ROOT.parent

# Shipped WITH the package (see [tool.setuptools.package-data] in pyproject), so
# `pip install` carries its own corpus and a fresh install can build the
# database without a git clone.
CORPUS_DIR = PACKAGE_ROOT / "corpus"               # human-verified source material (§1.5)
PROMPTS_DIR = PACKAGE_ROOT / "prompts"             # system-prompt text files (§2)

# Written at runtime, so it may NOT live inside the installed package:
# site-packages is read-only on many systems and shared across projects.
# Order: explicit override, then the platform's per-user data directory.
_DEFAULT_DATA_DIR = Path(
    os.environ.get("LOCALAPPDATA")             # Windows
    or os.environ.get("XDG_DATA_HOME")         # Linux, when set
    or (Path.home() / ".local" / "share")      # POSIX default
) / "legal-agent"
DATA_DIR = Path(os.environ.get("LEGAL_AGENT_HOME", _DEFAULT_DATA_DIR))
DB_PATH = Path(os.environ.get("LEGAL_AGENT_DB", DATA_DIR / "legal_agent.db"))

# ── Runtime reasoning model (spec §0.4) ──────────────────────────────────────
# NOIR: set MODEL to a real model id before running the agent live. It ships as a
# PLACEHOLDER on purpose, so `python -m legal_agent.run` fails fast with a clear
# message until you consciously choose one. Options:
#   "claude-opus-4-8"            (most capable — best for the hardest legal reasoning)
#   "claude-sonnet-5"            (balanced)
#   "claude-haiku-4-5-20251001" (cheapest)
MODEL_PLACEHOLDER = "SET_MODEL_ID_IN_CONFIG"
MODEL = MODEL_PLACEHOLDER

# ── Runtime backend selection ────────────────────────────────────────────────
# The Stage-3 pipeline only needs a str->str callable, so the model backend is
# swappable (spec §0.4). Pick one:
#   "manual"    — NO cost, NO key: the agent prints the assembled prompt, you
#                 paste it into any chat you already have (e.g. your Claude
#                 subscription) and paste the answer back. Ideal for validating
#                 the pipeline / building the golden set without paying for API.
#   "ollama"    — a FREE local model via Ollama (needs the Ollama service running
#                 + a pulled model; see OLLAMA_MODEL). Enables intelligent intake
#                 at zero cost. Your RTX 4060 (8GB) runs a 7-8B model well.
#   "anthropic" — the real Claude API (needs MODEL set above + ANTHROPIC_API_KEY).
# (gemini can be added later as its own builder.)
#
# Environment first, because the default assumes a machine with Ollama on it and
# `pip install` puts this file in site-packages. Measured on a clean venv: the
# library path (verify + retrieval) needs no model and works in two commands, but
# someone who then runs the CLI without Ollama had to edit an INSTALLED file to
# reach the free 「manual」 backend. That was the one place the documented path
# left the reader stuck, so it is an env var now.
LLM_PROVIDER = os.environ.get("LEGAL_AGENT_PROVIDER", "ollama")

# Local Ollama backend (used when LLM_PROVIDER = "ollama").
OLLAMA_HOST = os.environ.get("LEGAL_AGENT_OLLAMA_HOST", "http://localhost:11434")
# 要更好的繁中可換 qwen3:latest 等 — same reason as above, no source edit needed.
OLLAMA_MODEL = os.environ.get("LEGAL_AGENT_OLLAMA_MODEL", "llama3.1:latest")


def _tri_state(name: str) -> bool | None:
    """Env flag with a real third state: unset means 「do not send the key」,
    which is not the same as sending false."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Reasoning models can spend the whole generation budget inside <think> and
# return an empty answer (measured on qwen3:4b — see ollama_llm). The backend
# detects that and retries, but the retry costs a wasted generation on EVERY
# call, so a user who knows their model thinks can turn it off up front with
# LEGAL_AGENT_OLLAMA_THINK=false. Unset keeps the key out of the payload
# entirely, so servers and models that never heard of it are unaffected.
OLLAMA_THINK = _tri_state("LEGAL_AGENT_OLLAMA_THINK")

# Hybrid retrieval (retrieval/dense.py): "auto" fuses BM25 with local-Ollama
# bge-m3 embeddings via RRF when the index/daemon is available, and silently
# falls back to pure BM25 on ANY failure; "off" = pure BM25 always.
# BM25 scores still drive the honesty tier either way (the floor keeps its
# meaning); dense only improves the ORDERING and recall of candidates.
DENSE_RETRIEVAL = "auto"

# Query expansion (retrieval/lexicon.py): "on" appends hand-curated statutory
# vocabulary when everyday trigger words appear (「精神賠償」 -> 「非財產上之
# 損害」), bridging the gap between how people speak and how statutes are
# written. Retrieval-side only — the answer, citations and verifier are
# untouched. "off" = raw user wording only.
QUERY_EXPANSION = "on"

# When the provider is a real model (ollama/anthropic), let the model DRIVE the
# intake conversation (natural, understands free-form input) instead of the
# rule-based checklist. Ignored in "manual" mode (per-turn paste is impractical).
SMART_INTAKE = True

# API key comes from the ENVIRONMENT (never hardcoded); a local .env (gitignored)
# is loaded by load_env() below.
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"


def is_model_configured() -> bool:
    """True iff MODEL has been set to a real id (not the shipped placeholder)."""
    return bool(MODEL) and MODEL != MODEL_PLACEHOLDER


def get_anthropic_api_key() -> str | None:
    """The Anthropic API key from the environment, or None if unset."""
    return os.environ.get(ANTHROPIC_API_KEY_ENV)


def load_env() -> None:
    """Load a local .env (gitignored) into the environment if python-dotenv is
    installed; no-op otherwise. Call before reading the API key."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass
