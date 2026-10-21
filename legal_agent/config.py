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

# Written at runtime, so NOT inside the installed package (site-packages may be
# read-only). Order: LEGAL_AGENT_HOME, then the platform per-user data dir.
# The DB therefore lives outside the repo and survives deleting it; tests and
# CLI runs share it (AGENTS.md trap 1).
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
#                 at zero cost. An 8GB GPU runs a 7-8B model well.
#   "anthropic" — the real Claude API (needs MODEL set above + ANTHROPIC_API_KEY).
# Read from the environment because an installed copy of this file lives in
# site-packages, where no one should have to edit it.
LLM_PROVIDER = os.environ.get("LEGAL_AGENT_PROVIDER", "ollama")

# Local Ollama backend (used when LLM_PROVIDER = "ollama").
OLLAMA_HOST = os.environ.get("LEGAL_AGENT_OLLAMA_HOST", "http://localhost:11434")
# 要更好的繁中可換 qwen3:latest 等.
OLLAMA_MODEL = os.environ.get("LEGAL_AGENT_OLLAMA_MODEL", "llama3.1:latest")


def _tri_state(name: str) -> bool | None:
    """Env flag with a real third state: unset means 「do not send the key」,
    which is not the same as sending false."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Thinking models can spend the whole budget inside <think> and return nothing
# (qwen3:4b); the backend retries, at one wasted generation per call.
# LEGAL_AGENT_OLLAMA_THINK=false avoids that up front. Unset keeps the key out
# of the payload entirely.
OLLAMA_THINK = _tri_state("LEGAL_AGENT_OLLAMA_THINK")

# Hybrid retrieval (retrieval/dense.py): "auto" fuses BM25 with local-Ollama
# bge-m3 embeddings via RRF when the index/daemon is available, and SILENTLY
# falls back to pure BM25 on any failure (counted by
# retriever.dense_fallback_count — AGENTS.md trap 2); "off" = pure BM25 always.
# BM25 scores drive the honesty tier either way; dense only reorders/recalls.
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
