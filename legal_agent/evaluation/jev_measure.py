"""Does Jev (a calibrated yes/no model) beat the local models on the two yes/no
checks this repo could not pass? Measured, not shipped.

Two question sets, both fixed by the repo before this file existed:

  semantic   the `mutation --semantic` set: every structurally clean citation the
             4th axis is asked about (each corpus article, restated correctly =
             the CONTROLS) plus the planted `_SUBJECT_SWAPS` (the errors). Local
             llama3.1 caught all of them and called 43% of the controls wrong.
  direction  the `judge_direction` set: 5 answers whose conclusion points the
             wrong way, 11 that point the right way (blind coding, RESULTS §7.1).
             Qwen2.5 and Llama3.1 caught 3/5 and flagged 8/11 of the right ones.

Jev answers a yes/no question with a probability. Every question is sent once;
the probability is stored (checkpointed to evals/jev_run1.partial.json), and the
threshold is swept OFFLINE over the stored numbers, so the table is a curve, not
a tuned point. The free tier has a daily limit: on HTTP 429 with a long
Retry-After the run stops and the same command resumes after the reset.

Endpoint: OpenCode Zen's free `jev-1.13-free`, called with NO key. Every reply is
checked for `usage.opencode.billing_source == "free"` and cost 0; anything else,
or HTTP 401/402/403/404, raises PaidError and the whole run stops. Nothing here
pays or registers. What leaves the machine: the claim sentence and the verbatim
article (semantic), or the person's description and the generated answer
(direction) — all of it already public in this repo.

Run:  python -m legal_agent.evaluation.jev_measure semantic    # ~3,000 calls
      python -m legal_agent.evaluation.jev_measure direction
      python -m legal_agent.evaluation.jev_measure report      # re-print the saved run
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = "https://opencode.ai/inference/systemone/v1/systemone"
MODEL = "jev-1.13-free"
OUT = Path(__file__).resolve().parents[2] / "evals" / "jev_run1.json"
THRESHOLDS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99)

# Fixed before the first call, never tuned. p = probability the answer is YES.
SEMANTIC_Q = "主張是否與逐字條文明確牴觸?(主張把權利義務歸給與條文不同的主體,或明確改寫條文的要件。主張省略主體、未提及要件、或只是籠統摘要條文,不算牴觸。)"
DIRECTION_Q = (
    "這段回答的結論方向是否站不住?(它說法律站在對方那一邊卻說這個人有理,"
    "或叫這個人去走所引法條根本沒有提供的路。條文是否存在、格式、文筆都不算。)"
)


class PaidError(RuntimeError):
    """The free endpoint stopped being free or was withdrawn: stop, do not retry,
    do not switch to a paid endpoint."""


class QuotaExhausted(RuntimeError):
    """HTTP 429 with a Retry-After too long to wait out (the free daily limit).
    Nothing is paid; the run stops, keeps its checkpoint, and resumes later."""


def ask(state: str, instructions: str, timeout: float = 60.0) -> float:
    body = json.dumps({"model": MODEL, "state": state,
                       "questions": {"q": {"type": "noul", "instructions": instructions}}}
                      ).encode()
    req = urllib.request.Request(
        URL, data=body, headers={"Content-Type": "application/json", "User-Agent": "curl/8"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 402, 403, 404):
            raise PaidError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
        raise
    u = r.get("usage") or {}
    src = (u.get("opencode") or {}).get("billing_source")
    if src != "free" or u.get("cost", 0) != 0:
        raise PaidError(f"billing_source={src!r} cost={u.get('cost')!r}")
    return float(r["answers"]["q"]["noul"])


def _ask_retry(state: str, instructions: str, tries: int = 8) -> float:
    for i in range(tries):
        try:
            return ask(state, instructions)
        except PaidError:
            raise
        except urllib.error.HTTPError as e:
            # 429 / 5xx are rate limits and hiccups, not billing: wait and retry.
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            wait = e.headers.get("Retry-After") if e.headers else None
            if e.code == 429 and wait and wait.isdigit() and int(wait) > 600:
                raise QuotaExhausted(
                    f"HTTP 429 Retry-After {wait}s: {e.read()[:400].decode('utf-8', 'replace')}"
                ) from e
            time.sleep(float(wait) if wait and wait.isdigit() else min(120, 5 * 2 ** i))
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise AssertionError("unreachable")


PARTIAL = OUT.with_suffix(".partial.json")


def _ask_many(jobs: dict[str, tuple[str, str]], workers: int = 2) -> dict[str, float]:
    """key -> (state, instructions). Stops everything on the first PaidError.
    Answers are checkpointed to a .partial.json so a rate limit does not cost
    the calls already made."""
    stop = threading.Event()
    done: dict[str, float] = (
        json.loads(PARTIAL.read_text(encoding="utf-8")) if PARTIAL.exists() else {})
    todo = {k: v for k, v in jobs.items() if k not in done}
    lock = threading.Lock()

    def one(item):
        key, (state, instr) = item
        if stop.is_set():
            return
        try:
            p = _ask_retry(state, instr)
        except (PaidError, QuotaExhausted):
            stop.set()
            raise
        with lock:
            done[key] = p
            n = len(done)
            if n % 100 == 0:
                PARTIAL.write_text(json.dumps(done), encoding="utf-8")
                print(f"  {n}/{len(jobs)}", flush=True)

    try:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(one, todo.items()))
    finally:
        PARTIAL.write_text(json.dumps(done), encoding="utf-8")
    return {k: done[k] for k in jobs}


# ── semantic: the mutation --semantic set ───────────────────────────────────
_PROMPT_RE = re.compile(r"逐字條文:\n(.*)\n\n答案中的主張:\n(.*)\n\n問題:", re.DOTALL)


def _pair_key(verbatim: str, claim: str) -> str:
    return hashlib.sha1(f"{verbatim}\x00{claim}".encode()).hexdigest()[:16]


def _semantic_state(verbatim: str, claim: str) -> str:
    return f"逐字條文:\n{verbatim}\n\n答案中的主張:\n{claim}"


def collect_semantic_pairs(conn) -> dict[str, dict]:
    """Run the real mutation suite with a recording stand-in for the model, so
    the pairs are exactly the ones `mutation --semantic` would ask about.
    key -> {verbatim, claim, kind}; kind is 'swap' (a planted _SUBJECT_SWAPS
    error, structurally clean by construction) or 'control' (a correct citation)."""
    from legal_agent.evaluation.mutation import _SUBJECT_SWAPS, run_mutation_test

    swap_answers = [ans for _, _, ans in _SUBJECT_SWAPS]
    pairs: dict[str, dict] = {}

    def recorder(prompt: str) -> str:
        m = _PROMPT_RE.search(prompt)
        if m:
            verbatim, claim = m.group(1), m.group(2)
            kind = "swap" if any(claim in a for a in swap_answers) else "control"
            pairs[_pair_key(verbatim, claim)] = {"verbatim": verbatim, "claim": claim,
                                                 "kind": kind}
        return '{"consistent": true}'

    run_mutation_test(conn, semantic_llm=recorder)
    return pairs


def semantic_table(probs: dict[str, float], kinds: dict[str, str], threshold: float):
    """(swaps caught, swaps asked, controls flagged, controls asked) over the
    pairs that have a stored probability. A swap is structurally clean, so the
    4th axis alone decides it; a control is flagged only by the 4th axis (the
    structural axes flag 0 of them, §1)."""
    swaps = [k for k, v in kinds.items() if v == "swap" and k in probs]
    controls = [k for k, v in kinds.items() if v == "control" and k in probs]
    return (sum(probs[k] >= threshold for k in swaps), len(swaps),
            sum(probs[k] >= threshold for k in controls), len(controls))


def run_semantic() -> dict:
    from legal_agent.config import DB_PATH
    from legal_agent.data.database import connect

    conn = connect(DB_PATH)
    pairs = collect_semantic_pairs(conn)
    kinds = {k: v["kind"] for k, v in pairs.items()}
    print(f"{len(pairs)} distinct pairs: {sum(v == 'swap' for v in kinds.values())} planted "
          f"subject swaps, {sum(v == 'control' for v in kinds.values())} correct citations",
          flush=True)
    # Swaps first, then the controls in hash order — a pseudo-random order, so
    # if the free quota runs out part-way the controls already asked are a
    # random sample, not the first N articles of the code.
    order = sorted(pairs, key=lambda k: (kinds[k] != "swap", k))
    jobs = {k: (_semantic_state(pairs[k]["verbatim"], pairs[k]["claim"]), SEMANTIC_Q)
            for k in order}
    probs = _ask_many(jobs)
    return {"probs": probs, "kinds": kinds, "pairs": len(pairs)}


# ── direction: the judge_direction set ──────────────────────────────────────
def run_direction(passes: int = 2) -> dict:
    from legal_agent.evaluation.judge_direction import DEFAULT_ANSWERS

    answers = json.loads(Path(DEFAULT_ANSWERS).read_text(encoding="utf-8"))
    jobs = {}
    for p in range(passes):
        for cid, e in answers.items():
            state = f"【民眾的陳述】\n{e['initial_text']}\n\n【法律助理的回答】\n{e['answer']}"
            jobs[f"{p}|{cid}"] = (state, DIRECTION_Q)
    probs = _ask_many(jobs)
    return {"probs": probs, "passes": passes}


def score_direction(probs: dict[str, float], passes: int, threshold: float):
    from legal_agent.evaluation.judge_direction import labels

    truth = labels()
    out = []
    for p in range(passes):
        rows = {cid: probs[f"{p}|{cid}"] >= threshold for cid in truth}
        wrong = [i for i, t in truth.items() if t["truth"] == "wrong"]
        right = [i for i, t in truth.items() if t["truth"] == "right"]
        out.append((sum(rows[i] for i in wrong), len(wrong), sum(rows[i] for i in right),
                    len(right), sum(rows.values())))
    return out


def direction_auc(probs: dict[str, float], p: int) -> float:
    """P(a wrong-direction answer gets a higher p than a right-direction one);
    0.5 = no separation, ties count half."""
    from legal_agent.evaluation.judge_direction import labels

    truth = labels()
    w = [probs[f"{p}|{i}"] for i, t in truth.items() if t["truth"] == "wrong"]
    r = [probs[f"{p}|{i}"] for i, t in truth.items() if t["truth"] == "right"]
    return sum((a > b) + 0.5 * (a == b) for a in w for b in r) / (len(w) * len(r))


# ── report ──────────────────────────────────────────────────────────────────
def render(saved: dict) -> str:
    lines = []
    if "semantic" in saved:
        sem = saved["semantic"]
        lines.append("semantic 4th axis — flag when Jev p(contradicts) >= t")
        lines.append("| t | subject swaps caught | controls flagged (correct citations) |")
        lines.append("|---|---|---|")
        for t in THRESHOLDS:
            c, n, f, m = semantic_table(sem["probs"], sem["kinds"], t)
            lines.append(f"| {t} | {c}/{n} | {f}/{m} ({f / m:.1%}) |" if m
                         else f"| {t} | {c}/{n} | no controls asked |")
    if "direction" in saved:
        d = saved["direction"]
        lines.append("")
        lines.append("direction — flag when Jev p(direction does not hold) >= t; two passes")
        lines.append("| t | wrong caught /5 | right flagged /11 | flagged of 24 |")
        lines.append("|---|---|---|---|")
        for t in THRESHOLDS:
            cells = score_direction(d["probs"], d["passes"], t)
            lines.append(f"| {t} | " + " , ".join(str(c[0]) for c in cells)
                         + " | " + " , ".join(str(c[2]) for c in cells)
                         + " | " + " , ".join(str(c[4]) for c in cells) + " |")
        lines.append("AUC (wrong vs right, per pass): " + ", ".join(
            f"{direction_auc(d['probs'], p):.2f}" for p in range(d["passes"])))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    from legal_agent.evaluation import enable_utf8_stdout

    enable_utf8_stdout()
    mode = argv[0] if argv else "report"
    saved = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    try:
        if mode == "semantic":
            saved["semantic"] = run_semantic()
        elif mode == "direction":
            saved["direction"] = run_direction()
        elif mode != "report":
            print(__doc__)
            return 2
    except PaidError as e:
        print(f"STOP — the free endpoint is no longer free or is gone: {e}")
        return 3
    except QuotaExhausted as e:
        print(f"STOP — free usage limit reached (nothing paid; answers so far are in "
              f"{PARTIAL.name}, rerun the same command after the limit resets): {e}")
        return 4
    if mode != "report":
        OUT.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    print(render(saved))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
